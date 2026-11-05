"""Control real publisher/retirer processes at declared pipe barriers."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import selectors
import sqlite3
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.overlap_store import MODES, OverlapPublicationStore
from src.publication_store import recover_value

STAGES = ("after_admission", "after_final_check", "before_commit", "after_commit")
INITIAL, B, C = "approved=version-a\n", "approved=version-b\n", "approved=version-c\n"
VALUES = {"ascii": B, "empty": "", "unicode": "approved=안전 ✓\n"}
SETTINGS = {"journal_mode": "delete", "synchronous": 2, "integrity_check": "ok"}
SOURCES = ("src/overlap_store.py", "src/retirement_store.py", "src/publication_store.py", "src/retry_store.py",
           "experiments/overlap_worker.py", "experiments/run_overlap_comparison.py", "experiments/verify_overlap_results.py",
           "tests/test_overlap_store.py", "docs/OVERLAP_PROTOCOL.md")
STEP_TIMEOUT = 15


class BarrierFailure(ValueError):
    def __init__(self, message: str, output: bytes):
        super().__init__(message)
        self.output = output


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def load_cases(path: Path) -> list[dict]:
    manifest = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(manifest, dict) or set(manifest) != {"schema_version", "cases"} or manifest["schema_version"] != "overlap-eval-v1":
        raise ValueError("unsupported overlap manifest")
    cases = manifest["cases"]
    expected = {(s, o, "ascii") for s in ("retire_first", "publication_first", *STAGES) for o in ("update", "revoke")}
    expected.update(("current_epoch", "update", v) for v in VALUES)
    expected.add(("current_epoch", "revoke", "ascii"))
    if (not isinstance(cases, list) or len(cases) != 16 or any(set(c) != {"case_id", "schedule", "operation", "value"}
            or not all(isinstance(v, str) for v in c.values()) or not c["case_id"] for c in cases)):
        raise ValueError("sixteen well-formed cases required")
    ids = [c["case_id"] for c in cases]
    if len(set(ids)) != 16 or {(c["schedule"], c["operation"], c["value"]) for c in cases} != expected:
        raise ValueError("repeated or changed frozen schedule")
    return cases


def intent(case: dict) -> tuple[int, str | None]:
    return (2 if case["schedule"] == "current_epoch" else 1,
            None if case["operation"] == "revoke" else VALUES[case["value"]])


def seed_values(case: dict) -> tuple[str | None, str | None]:
    return (B, None) if case["operation"] == "update" else (None, C)


def capture(store: OverlapPublicationStore) -> dict:
    observed = store.inspect()
    state = observed["state"]
    output = recover_value(state)
    value = output.pop("content")
    receipts = [{**{k: v for k, v in r.items() if k != "payload"},
                 "payload_utf8": None if r["payload"] is None else r["payload"].decode()}
                for r in observed["receipts"]]
    return {"state": {"revision": state.revision, "approved_sha256": state.approved_sha256,
                      "content_utf8": state.content.decode(), "content_sha256": sha(state.content)},
            "active_epoch": observed["active_epoch"], "effects": observed["effects"], "receipts": receipts,
            "commit_witnesses": observed["commit_witnesses"],
            "delivery": {**output, "delivered_utf8": None if value is None else value.decode()}, "sqlite_settings": store.settings()}


def materialize(case: dict, committed: bool, active: int, witness_epoch: int | None) -> dict:
    payload, approved, effects, receipts = INITIAL, sha(INITIAL.encode()), [], []
    entries = [(1, "request-1", seed_values(case)[0]), (1, "request-2", seed_values(case)[1])]
    epoch, content = intent(case)
    if committed:
        entries.append((epoch, "inflight", content))
    for revision, (generation, key, value) in enumerate(entries, 2):
        if value is not None:
            payload = value
        approved = None if value is None else sha(value.encode())
        effect = {"revision": revision, "epoch": generation, "request_id": key,
                  "operation": "revoke" if value is None else "update", "approved_sha256": approved}
        effects.append(effect)
        receipts.append({**effect, "payload_utf8": value})
    # An old write after retirement can recreate its receipt below the fence.
    kept = [r for r in receipts if r["epoch"] >= active or (r["request_id"] == "inflight" and witness_epoch == active)]
    state = {"revision": len(entries) + 1, "approved_sha256": approved,
             "content_utf8": payload, "content_sha256": sha(payload.encode())}
    output = {"status": "blocked" if approved is None else "delivered", "reason": "approval_revoked" if approved is None else "verified_recovery",
              "revision": state["revision"], "delivered_utf8": None if approved is None else payload}
    witnesses = [] if not committed else [{"revision": 4, "requested_epoch": epoch, "active_epoch": witness_epoch, "request_id": "inflight"}]
    return {"state": state, "active_epoch": active, "effects": effects,
            "receipts": sorted(kept, key=lambda r: (r["epoch"], r["request_id"])),
            "commit_witnesses": witnesses, "delivery": output, "sqlite_settings": SETTINGS}


def retirement_result(busy: bool) -> dict:
    return {"target_epoch": 2, "busy_timeout_ms": 0, "sqlite_errorcode": 5 if busy else None,
            "sqlite_errorname": "SQLITE_BUSY" if busy else None, "status": "busy" if busy else "retired",
            "active_epoch": None if busy else 2}


def validate_retirement(attempt: dict) -> dict:
    events = [json.loads(line) for line in attempt["stdout"].splitlines()]
    answer = attempt["response"]
    if answer not in (retirement_result(True), retirement_result(False)):
        raise ValueError("unrecognized retirement result or contention code")
    expected = [{"seq": 0, "kind": "retirement_started", "target_epoch": 2},
                {"seq": 1, "kind": "retirement_result", "response": answer}, {"seq": 2, "kind": "completed"}]
    if attempt["returncode"] != 0 or attempt["stderr"] or events != expected or attempt["events"] != expected:
        raise ValueError("retirement child did not complete its declared operation")
    return answer


def expected_publisher(row: dict, first_busy: bool) -> tuple[list[dict], dict, int | None]:
    epoch, content = intent(row)
    schedule, mode = row["schedule"], row["mode"]
    initial = 2 if schedule in {"retire_first", "current_epoch"} else 1
    events = []

    def event(kind, **fields):
        events.append({"seq": len(events), "kind": kind, **fields})

    def checkpoint(stage):
        event("checkpoint", stage=stage)
        if schedule == stage:
            event("paused", stage=stage)
            event("resumed", stage=stage)

    admitted = epoch == initial
    event("admission", origin="transaction" if mode == "transactional_admission" else "read",
          observed_epoch=initial, decision="allowed" if admitted else "epoch_retired")
    committed = False
    if admitted:
        checkpoint("after_admission")
        observed = 2 if mode == "separate_recheck" and schedule == "after_admission" and not first_busy else initial
        origin = "cached" if mode == "cached_admission" else ("transaction" if mode == "transactional_admission" else "read")
        event("final_decision", origin=origin, observed_epoch=observed, decision="allowed" if epoch == observed else "epoch_retired")
        checkpoint("after_final_check")
        if epoch == observed:
            committed = True
            checkpoint("before_commit")
            checkpoint("after_commit")
    witness = None
    if committed:
        witness = 2 if epoch == 2 or (schedule in {"after_admission", "after_final_check"} and not first_busy) else 1
    answer = {"status": "committed" if committed else "epoch_retired", "epoch": epoch, "request_id": "inflight",
              "revision": 4 if committed else None, "approved_sha256": None if not committed or content is None else sha(content.encode())}
    event("publication_result", response=answer)
    event("completed")
    return events, answer, witness


def validate_timeline(row: dict, first_busy: bool) -> None:
    expected = []
    def add(kind, **fields):
        expected.append({"seq": len(expected), "kind": kind, **fields})
    def retire(number, phase):
        answer = row["retirement_attempts"][number-1]["response"]
        add("retirement_requested", attempt=number, phase=phase)
        add("retirement_returned", attempt=number, status=answer["status"], sqlite_errorcode=answer["sqlite_errorcode"])
    add("seeded")
    prefix = row["schedule"] in {"retire_first", "current_epoch"}
    pause = row["schedule"] in STAGES
    if prefix:
        retire(1, "before_publication")
    add("publisher_started")
    if pause:
        add("publisher_paused", stage=row["schedule"])
        retire(1, "during_pause")
        add("pause_observed")
        add("publisher_resumed", stage=row["schedule"])
    add("publisher_completed", status=row["publisher"]["response"]["status"])
    if not prefix and not pause:
        retire(1, "after_publication")
    if first_busy:
        retire(2, "after_publication")
    add("final_observed")
    if row["timeline"] != expected:
        raise ValueError("controller order differs from declared schedule")


def assess(row: dict) -> dict:
    attempts = row["retirement_attempts"]
    if not attempts:
        raise ValueError("missing retirement child")
    answers = [validate_retirement(a) for a in attempts]
    first_busy = answers[0]["status"] == "busy"
    if len(answers) != (2 if first_busy else 1) or answers[-1]["status"] != "retired":
        raise ValueError("deferred retirement did not complete exactly one scheduled retry")
    prefix = row["schedule"] in {"retire_first", "current_epoch"}
    pause = row["schedule"] in STAGES
    phases = (["before_publication"] if prefix else ["during_pause"] if pause else ["after_publication"]) + (["after_publication"] if first_busy else [])
    if [a["phase"] for a in attempts] != phases:
        raise ValueError("retirement attempts used the wrong controller phase")
    pub = row["publisher"]
    expected_events, response, witness_epoch = expected_publisher(row, first_busy)
    decoded = [json.loads(line) for line in pub["stdout"].splitlines()]
    if pub["returncode"] != 0 or pub["stderr"] or pub["response"] != response or pub["events"] != expected_events or decoded != expected_events:
        raise ValueError("publication trace/response differs from the controlled checks")
    validate_timeline(row, first_busy)
    if row["initial"] != materialize(row, False, 1, None):
        raise ValueError("seed fixture differs from declared values/effects")
    committed = bool(row["final"]["commit_witnesses"])
    if committed != (response["status"] == "committed"):
        raise ValueError("response disagrees with actual committed witness")
    if row["final"] != materialize(row, committed, 2, witness_epoch):
        raise ValueError("final state/effects/receipts/witnesses are inconsistent")
    if pause:
        pause_committed = row["schedule"] == "after_commit"
        pause_epoch = 1 if first_busy else 2
        if row["pause_capture"] != materialize(row, pause_committed, pause_epoch, 1 if pause_committed else None):
            raise ValueError("pause observation contradicts transaction/retirement order")
    elif row["pause_capture"] is not None:
        raise ValueError("serial control has an undeclared pause")
    epoch, _ = intent(row)
    witnesses = row["final"]["commit_witnesses"]
    invalid = any(w["requested_epoch"] < w["active_epoch"] for w in witnesses)
    old = epoch == 1
    coherent = row["final"]["state"]["approved_sha256"] is None or row["final"]["state"]["approved_sha256"] == row["final"]["state"]["content_sha256"]
    return {"contract_satisfied": not invalid, "invalid_old_effect": old and invalid,
            "invalid_opportunity": invalid and row["schedule"] in {"after_admission", "after_final_check"},
            "invalid_after_admission": invalid and row["schedule"] == "after_admission",
            "invalid_after_final_check": invalid and row["schedule"] == "after_final_check",
            "valid_old_commit": old and committed and not invalid, "old_denial": old and not committed,
            "new_current_success": epoch == 2 and committed and not invalid,
            "retirement_deferred": first_busy, "retirement_retry_completed": first_busy and answers[-1]["status"] == "retired",
            "postcommit_historical_reply": row["schedule"] == "after_commit" and committed and witness_epoch == 1,
            "retired_receipt_recreated": any(r["epoch"] < 2 for r in row["final"]["receipts"]),
            "intrinsic_state_coherent": coherent, "final_epoch_closed": row["final"]["active_epoch"] == 2,
            "barrier_verified": pause, "observations_consistent": True}


def wait_for_pause(process: subprocess.Popen, stage: str, timeout: float = STEP_TIMEOUT) -> bytes:
    if process.stdout is None:
        raise ValueError("publisher stdout pipe required")
    deadline, received, pending = time.monotonic() + timeout, bytearray(), b""
    with selectors.DefaultSelector() as selector:
        selector.register(process.stdout, selectors.EVENT_READ)
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0 or not selector.select(remaining):
                raise subprocess.TimeoutExpired(process.args, timeout, output=bytes(received))
            chunk = os.read(process.stdout.fileno(), 4096)
            if not chunk:
                raise BarrierFailure("publisher exited before the required pause", bytes(received))
            received.extend(chunk)
            if len(received) > 2**20:
                raise BarrierFailure("publisher trace exceeds protocol bound", bytes(received))
            pending += chunk
            while b"\n" in pending:
                line, pending = pending.split(b"\n", 1)
                try:
                    event = json.loads(line)
                except ValueError as exc:
                    raise BarrierFailure("malformed JSON before the pause", bytes(received)) from exc
                if event.get("kind") == "paused":
                    if event.get("stage") != stage or pending:
                        raise BarrierFailure("wrong or nonterminal pause barrier", bytes(received))
                    return bytes(received)


def run_case(case: dict, mode: str) -> dict:
    if mode not in MODES:
        raise ValueError("unknown overlap mode")
    row = {**case, "mode": mode, "status": "pending", "error_phase": "setup", "error_type": None,
           "initial": None, "pause_capture": None, "final": None, "timeline": [], "retirement_attempts": [],
           "publisher": {"command": None, "returncode": None, "stdout": "", "stderr": "", "events": [], "response": None}, "oracle": None}
    process, consumed, drained = None, b"", False
    def note(kind, **fields):
        row["timeline"].append({"seq": len(row["timeline"]), "kind": kind, **fields})
    with tempfile.TemporaryDirectory(prefix="codeguardian-overlap-") as directory:
        root = Path(directory)
        try:
            store = OverlapPublicationStore(root, mode)
            store.initialize(INITIAL.encode())
            for index, value in enumerate(seed_values(case), 1):
                store.publish_request(1, "request-" + str(index), None if value is None else value.encode())
            row["initial"] = capture(store)
            note("seeded")
            def retire(phase):
                number = len(row["retirement_attempts"]) + 1
                command = [sys.executable, str(ROOT / "experiments/overlap_worker.py"), "--role", "retire", "--root", str(root), "--mode", mode]
                record = {"phase": phase, "command": command, "returncode": None, "stdout": "", "stderr": "", "events": [], "response": None}
                row["retirement_attempts"].append(record)
                note("retirement_requested", attempt=number, phase=phase)
                row["error_phase"] = "retirement_process"
                try:
                    child = subprocess.run(command, capture_output=True, text=True, timeout=STEP_TIMEOUT)
                except subprocess.TimeoutExpired as exc:
                    record["stdout"] = exc.stdout.decode(errors="replace") if isinstance(exc.stdout, bytes) else exc.stdout or ""
                    record["stderr"] = exc.stderr.decode(errors="replace") if isinstance(exc.stderr, bytes) else exc.stderr or ""
                    raise
                record.update(returncode=child.returncode, stdout=child.stdout, stderr=child.stderr)
                record["events"] = [json.loads(line) for line in child.stdout.splitlines()]
                candidates = [e["response"] for e in record["events"] if e.get("kind") == "retirement_result"]
                if len(candidates) != 1:
                    raise ValueError("missing retirement result")
                record["response"] = candidates[0]
                answer = validate_retirement(record)
                note("retirement_returned", attempt=number, status=answer["status"], sqlite_errorcode=answer["sqlite_errorcode"])
                return answer
            prefix = case["schedule"] in {"retire_first", "current_epoch"}
            pause = case["schedule"] if case["schedule"] in STAGES else "none"
            if prefix:
                if retire("before_publication")["status"] != "retired":
                    raise ValueError("uncontended initial retirement deferred")
            epoch, _ = intent(case)
            command = [sys.executable, str(ROOT / "experiments/overlap_worker.py"), "--role", "publish", "--root", str(root),
                       "--mode", mode, "--epoch", str(epoch), "--operation", case["operation"], "--value", case["value"], "--pause", pause]
            row["publisher"]["command"] = command
            note("publisher_started")
            process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            first = None
            if pause != "none":
                row["error_phase"] = "pause_barrier"
                consumed = wait_for_pause(process, pause)
                note("publisher_paused", stage=pause)
                first = retire("during_pause")
                row["error_phase"] = "pause_observation"
                row["pause_capture"] = capture(OverlapPublicationStore(root, mode))
                note("pause_observed")
                note("publisher_resumed", stage=pause)
            row["error_phase"] = "publication_completion"
            resume = (json.dumps({"command": "resume", "stage": pause}) + "\n").encode() if pause != "none" else None
            tail, stderr = process.communicate(input=resume, timeout=STEP_TIMEOUT)
            drained = True
            pub = row["publisher"]
            pub.update(returncode=process.returncode, stdout=(consumed + tail).decode(), stderr=stderr.decode())
            pub["events"] = [json.loads(line) for line in pub["stdout"].splitlines()]
            results = [e["response"] for e in pub["events"] if e.get("kind") == "publication_result"]
            if process.returncode != 0 or pub["stderr"] or len(results) != 1:
                raise ValueError("publisher failed or omitted its response")
            pub["response"] = results[0]
            note("publisher_completed", status=pub["response"]["status"])
            if not prefix and pause == "none":
                first = retire("after_publication")
            if first is not None and first["status"] == "busy":
                if retire("after_publication")["status"] != "retired":
                    raise ValueError("scheduled retirement retry did not commit")
            row["error_phase"] = "final_observation"
            row["final"] = capture(OverlapPublicationStore(root, mode))
            note("final_observed")
            row["error_phase"] = "oracle"
            row["oracle"] = assess(row)
            row.update(status="complete", error_phase=None)
        except (OSError, ValueError, RuntimeError, UnicodeError, sqlite3.Error, subprocess.SubprocessError) as exc:
            if isinstance(exc, subprocess.TimeoutExpired) and row["error_phase"] == "pause_barrier":
                consumed = exc.stdout or b""
            elif isinstance(exc, BarrierFailure):
                consumed = exc.output
            row.update(status="infrastructure_error", error_type=type(exc).__name__)
        finally:
            if process is not None and not drained:
                if process.poll() is None:
                    process.kill()
                tail, stderr = process.communicate(timeout=STEP_TIMEOUT)
                row["publisher"].update(returncode=process.returncode, stdout=(consumed + tail).decode(errors="replace"), stderr=stderr.decode(errors="replace"))
    return row


def criteria(arms: dict) -> dict:
    values = [arms[m] for m in MODES]
    return {
        "invalid_epoch_effect_counts": all([v[k] for v in values] == [4, 2, 0] for k in ("invalid_old_effects", "invalid_opportunities")),
        "admission_and_final_decision_gaps": [v["invalid_after_admission"] for v in values] == [2, 0, 0] and [v["invalid_after_final_check"] for v in values] == [2, 2, 0],
        "writer_deferrals_and_completed_retries": all([v[k] for v in values] == [2, 2, 6] for k in ("retirement_deferrals", "completed_retries", "busy_attempts")),
        "valid_old_commits_and_denials": [v["valid_old_commits"] for v in values] == [6, 6, 10] and [v["old_denials"] for v in values] == [2, 4, 2],
        "all_current_epoch_controls_complete": all(v["current_successes"] == 4 for v in values),
        "postcommit_replies_are_historical": all(v["postcommit_historical_replies"] == 2 for v in values),
        "retired_receipt_recreation_counts": [v["retired_receipt_recreations"] for v in values] == [4, 2, 0],
        "all_scheduled_retirements_commit": all(v["retirement_commits"] == v["final_epoch_closed"] == 16 for v in values) and [v["retirement_attempts"] for v in values] == [18, 18, 22],
        "all_states_and_witnesses_consistent": all(v["coherent_final_states"] == v["consistent_observations"] == 16 for v in values),
        "all_process_and_barrier_coverage_verified": all(v["verified_barriers"] == 8 and v["publisher_completions"] == 16 and v["retirement_completions"] == v["retirement_attempts"] and v["infrastructure_errors"] == 0 for v in values),
    }


def summarize(records: list[dict], cases: list[dict]) -> dict:
    grid = [(r["case_id"], r["mode"]) for r in records]
    expected = {(c["case_id"], m) for c in cases for m in MODES}
    if len(grid) != len(expected) or set(grid) != expected:
        raise ValueError("exactly one record per declared case/mode required")
    declared = {c["case_id"]: c for c in cases}
    for row in records:
        if any(row[k] != v for k, v in declared[row["case_id"]].items()):
            raise ValueError("raw record changed its frozen declaration")
        if row["status"] == "complete":
            if row["oracle"] != assess(row):
                raise ValueError("stored oracle differs from observations")
        elif row["status"] != "infrastructure_error" or row["oracle"] is not None:
            raise ValueError("invalid record status")
    mapping = {"contracts_satisfied": "contract_satisfied", "invalid_old_effects": "invalid_old_effect", "invalid_opportunities": "invalid_opportunity",
               "invalid_after_admission": "invalid_after_admission", "invalid_after_final_check": "invalid_after_final_check",
               "valid_old_commits": "valid_old_commit", "old_denials": "old_denial", "current_successes": "new_current_success",
               "retirement_deferrals": "retirement_deferred", "completed_retries": "retirement_retry_completed",
               "postcommit_historical_replies": "postcommit_historical_reply", "retired_receipt_recreations": "retired_receipt_recreated",
               "coherent_final_states": "intrinsic_state_coherent", "final_epoch_closed": "final_epoch_closed",
               "verified_barriers": "barrier_verified", "consistent_observations": "observations_consistent"}
    arms = {}
    for mode in MODES:
        rows = [r for r in records if r["mode"] == mode]
        completed = [r for r in rows if r["status"] == "complete"]
        attempts = [a for r in completed for a in r["retirement_attempts"]]
        arms[mode] = {"cases": len(rows), "old_epoch_cases": sum(r["schedule"] != "current_epoch" for r in rows),
                      "opportunity_cases": sum(r["schedule"] in {"after_admission", "after_final_check"} for r in rows),
                      "pause_cases": sum(r["schedule"] in STAGES for r in rows), "current_controls": sum(r["schedule"] == "current_epoch" for r in rows),
                      "publisher_completions": len(completed), "retirement_attempts": len(attempts), "retirement_completions": len(attempts),
                      "retirement_commits": sum(a["response"]["status"] == "retired" for a in attempts),
                      "busy_attempts": sum(a["response"]["status"] == "busy" for a in attempts),
                      "infrastructure_errors": len(rows) - len(completed),
                      **{dst: sum(bool((r["oracle"] or {}).get(src)) for r in rows) for dst, src in mapping.items()}}
    return {"arms": arms, "criteria": criteria(arms)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--base-commit", required=True)
    parser.add_argument("--freeze-commit", required=True)
    parser.add_argument("--output-dir", type=Path, default=ROOT / "experiments/results")
    args = parser.parse_args()
    if sys.version_info < (3, 11):
        raise RuntimeError("overlap study requires Python 3.11+ numeric SQLite error metadata")
    started = datetime.now(timezone.utc)
    cases = load_cases(args.dataset)
    records = [run_case(c, m) for c in cases for m in MODES]
    summary = summarize(records, cases)
    run_id = started.strftime("%Y-%m-%dT%H-%M-%S-%fZ-overlap-v1")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    raw = args.output_dir / (run_id + ".jsonl")
    metadata = {"started_at_utc": started.isoformat(), "finished_at_utc": datetime.now(timezone.utc).isoformat(),
                "python_version": platform.python_version(), "sqlite_version": sqlite3.sqlite_version, "platform": platform.platform(),
                "base_commit": args.base_commit, "freeze_commit": args.freeze_commit, "command": [sys.executable, *sys.argv],
                "dataset": str(args.dataset), "dataset_sha256": sha(args.dataset.read_bytes()),
                "source_sha256": {p: sha((ROOT / p).read_bytes()) for p in SOURCES}, "results_file": raw.name, "summary": summary,
                "interpretation_limit": "Sixteen developer-visible schedules per mode; two process roles and fixed pipe barriers; effect-time epoch contract; no fairness, latency, random race probability, many-writer, crash, distributed, or live-task claim."}
    with raw.open("x", encoding="utf-8") as handle:
        for row in records:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    with (args.output_dir / (run_id + "-summary.json")).open("x", encoding="utf-8") as handle:
        json.dump(metadata, handle, indent=2, ensure_ascii=False)
        handle.write("\n")
    print(json.dumps(summary, indent=2))
    print("Saved " + run_id)
    return int(any(a["infrastructure_errors"] for a in summary["arms"].values()))


if __name__ == "__main__":
    raise SystemExit(main())
