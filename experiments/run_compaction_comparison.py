"""Measure historical receipt representation and migration recovery separately."""
from __future__ import annotations

import argparse
import hashlib
import json
import platform
import sqlite3
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.compaction_store import MODES, STAGES, SUMMARY_COLUMNS, CompactionPublicationStore
from src.publication_store import recover_value

VALUES = {"ascii": "approved=version-b\n", "empty": "", "unicode": "approved=안전 ✓\n", "revoke": None,
          "nfc": "approved=é\n", "nfd": "approved=e\u0301\n", "c": "approved=version-c\n", "d": "approved=version-d\n"}
CONTROLS = {"changed_bytes": "ascii", "update_to_revoke": "empty", "revoke_to_update": "revoke",
            "unicode_bytes": "nfc", "new_epoch": "ascii", "unseen_old": "ascii"}
SOURCES = ("src/compaction_store.py", "experiments/compaction_worker.py", "experiments/run_compaction_comparison.py",
           "experiments/verify_compaction_results.py", "tests/test_compaction_store.py", "docs/COMPACTION_PROTOCOL.md",
           "src/publication_store.py", "src/retry_store.py", "src/retirement_store.py")
FIELDS = ("known_no_extra", "repeat_supported", "changed_supported", "unavailable_known", "gap_supported",
          "completed_known_supported", "completed_captures", "completed_full_rows", "completed_summary_rows",
          "completed_no_old_payload", "new_epoch_completed", "unseen_old_refused", "recovered_epoch_1",
          "recovered_epoch_2", "layout_matches", "coherent_final", "current_policy_preserved", "declared_exit",
          "normal_compaction", "child_completions", "false_history", "consistent_observations", "summary_schema_valid",
          "old_full_payload_bytes")
STEP_TIMEOUT = 15


def sha(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def load_cases(path: Path) -> list[dict]:
    data = json.loads(path.read_text())
    if not isinstance(data, dict) or set(data) != {"schema_version", "cases"} or data["schema_version"] != "compaction-eval-v1":
        raise ValueError("unsupported compaction manifest")
    cases = data["cases"]
    wanted = {(cut, "repeat", value) for cut in (*STAGES, "normal") for value in ("ascii", "empty", "unicode", "revoke")}
    wanted |= {("normal", scenario, value) for scenario, value in CONTROLS.items()}
    if (not isinstance(cases, list) or len(cases) != 26
            or any(not isinstance(c, dict) or set(c) != {"case_id", "cut", "scenario", "value"}
                   or not all(isinstance(v, str) and v for v in c.values()) for c in cases)
            or len({c["case_id"] for c in cases}) != 26
            or {(c["cut"], c["scenario"], c["value"]) for c in cases} != wanted):
        raise ValueError("26 unique frozen histories required")
    return cases


def requests(case):
    original = VALUES[case["value"]]
    later = VALUES["c"] if original is None else None
    scenario = case["scenario"]
    incoming = {"changed_bytes": VALUES["c"], "update_to_revoke": None, "revoke_to_update": "",
                "unicode_bytes": VALUES["nfd"], "new_epoch": VALUES["d"], "unseen_old": VALUES["ascii"]}.get(scenario, original)
    return [
        {"epoch": 1, "request_id": "original", "content_utf8": original},
        {"epoch": 1, "request_id": "later-policy", "content_utf8": later},
        {"epoch": 2 if scenario == "new_epoch" else 1,
         "request_id": "unseen" if scenario == "unseen_old" else "original", "content_utf8": incoming},
    ]


def reply(status, req, revision=None, approval=None):
    return {"status": status, "epoch": req["epoch"], "request_id": req["request_id"],
            "revision": revision, "approved_sha256": approval}


def full_receipt(req, revision):
    value = req["content_utf8"]
    return {"epoch": req["epoch"], "request_id": req["request_id"], "operation": "revoke" if value is None else "update",
            "payload_utf8": value, "revision": revision, "approved_sha256": None if value is None else sha(value.encode())}


def summary_receipt(receipt):
    return {"epoch": receipt["epoch"], "request_id": receipt["request_id"], "operation": receipt["operation"],
            "payload_sha256": receipt["approved_sha256"], "revision": receipt["revision"]}


def capture(store):
    observed = store.inspect()
    state = observed.pop("state")
    output = recover_value(state)
    content = output.pop("content")
    observed["receipts"] = [{**{k: v for k, v in r.items() if k != "payload"},
                             "payload_utf8": None if r["payload"] is None else r["payload"].decode()}
                            for r in observed["receipts"]]
    return {**observed, "state": {"revision": state.revision, "approved_sha256": state.approved_sha256,
                                 "content_utf8": state.content.decode(), "content_sha256": sha(state.content)},
            "delivery": {**output, "delivered_utf8": None if content is None else content.decode()},
            "sqlite_settings": store.settings()}


def audit_capture(case, observed, after=False):
    if observed["active_epoch"] not in (1, 2) or observed["summary_columns"] != list(SUMMARY_COLUMNS):
        raise ValueError("unexpected epoch or compact schema")
    effects = observed["effects"]
    if len(effects) not in ((2, 3) if after else (2,)):
        raise ValueError("unexpected publication effect count")
    selected = requests(case)[:len(effects)]
    payload, approved, expected_effects, options = "approved=version-a\n", None, [], {}
    for revision, req in enumerate(selected, 2):
        receipt = full_receipt(req, revision)
        if req["content_utf8"] is not None:
            payload = req["content_utf8"]
        approved = receipt["approved_sha256"]
        expected_effects.append({k: v for k, v in receipt.items() if k != "payload_utf8"})
        options[revision] = receipt
    state = {"revision": 1 + len(effects), "approved_sha256": approved, "content_utf8": payload,
             "content_sha256": sha(payload.encode())}
    delivery = {"status": "blocked" if approved is None else "delivered",
                "reason": "approval_revoked" if approved is None else "verified_recovery",
                "revision": state["revision"], "delivered_utf8": None if approved is None else payload}
    for table, compact in (("receipts", False), ("summaries", True)):
        rows = observed[table]
        if rows != sorted(rows, key=lambda r: (r["epoch"], r["request_id"])) or len({(r["epoch"], r["request_id"]) for r in rows}) != len(rows):
            raise ValueError("duplicate or unordered authoritative receipts")
        for row in rows:
            original = options.get(row["revision"])
            if original is None or row != (summary_receipt(original) if compact else original):
                raise ValueError("receipt does not bind an actual committed operation and value")
    if (set(observed) != {"state", "active_epoch", "effects", "receipts", "summaries", "summary_columns", "delivery", "sqlite_settings"}
            or effects != expected_effects or observed["state"] != state or observed["delivery"] != delivery
            or observed["sqlite_settings"] != {"journal_mode": "delete", "synchronous": 2, "integrity_check": "ok"}):
        raise ValueError("snapshot contradicts state/effect/current delivery")


def recovered_layout(case, mode):
    cut = case["cut"]
    committed = cut in {"after_commit", "normal"}
    lost_split = mode == "split_summary" and cut in {"after_fence_cleanup", "after_summary"}
    active = 2 if committed or lost_split else 1
    originals = sorted([full_receipt(req, n) for n, req in enumerate(requests(case)[:2], 2)], key=lambda r: r["request_id"])
    if active == 1 or mode == "retain_full":
        return active, originals, []
    if mode in {"split_summary", "atomic_summary"} and not lost_split:
        return active, [], [summary_receipt(r) for r in originals]
    return active, [], []


def validate_child(row):
    child = row["child"]
    events = [{"seq": 0, "kind": "compaction_started", "target_epoch": 2}]
    for stage in STAGES:
        events.append({"seq": len(events), "kind": "checkpoint", "stage": stage})
        if stage == row["cut"]:
            events.append({"seq": len(events), "kind": "declared_exit", "stage": stage, "exit_code": 73})
            break
    normal = row["cut"] == "normal"
    answer = {"status": "compacted", "active_epoch": 2} if normal else None
    if normal:
        events.extend([{"seq": len(events), "kind": "compaction_result", "response": answer},
                       {"seq": len(events) + 1, "kind": "completed"}])
    command = child["command"]
    if (len(command) != 8 or Path(command[1]).name != "compaction_worker.py" or command[2] != "--root" or not command[3]
            or command[4:] != ["--mode", row["mode"], "--cut", row["cut"]]
            or child["returncode"] != (0 if normal else 73) or child["stderr"] or child["response"] != answer
            or child["events"] != events or [json.loads(line) for line in child["stdout"].splitlines()] != events):
        raise ValueError("child did not execute its exact declared completion/exit prefix")


def assess(row):
    validate_child(row)
    for field in ("initial", "recovered", "final"):
        audit_capture(row, row[field], field == "final")
    initial, recovered, final = row["initial"], row["recovered"], row["final"]
    initial_full = sorted([full_receipt(req, n) for n, req in enumerate(requests(row)[:2], 2)], key=lambda r: r["request_id"])
    if initial["active_epoch"] != 1 or initial["receipts"] != initial_full or initial["summaries"]:
        raise ValueError("fixture does not contain the original full receipts")
    req = requests(row)[2]
    if row["followup_request"] != req:
        raise ValueError("follow-up changed its declared epoch, ID or bytes")
    answer = row["followup_response"]
    if (set(answer) != {"status", "epoch", "request_id", "revision", "approved_sha256"}
            or answer["epoch"] != req["epoch"] or answer["request_id"] != req["request_id"]
            or answer["status"] not in {"committed", "replayed", "conflict", "outcome_unavailable", "future_epoch"}):
        raise ValueError("invalid follow-up response shape")
    if final["active_epoch"] != recovered["active_epoch"]:
        raise ValueError("follow-up unexpectedly changed the namespace")
    known = row["scenario"] not in {"new_epoch", "unseen_old"}
    no_extra = len(final["effects"]) == len(recovered["effects"])
    expected_full = {(r["epoch"], r["request_id"]): r for r in recovered["receipts"]}
    if not no_extra:
        expected_full[(req["epoch"], req["request_id"])] = full_receipt(req, 4)
    if (final["receipts"] != [expected_full[k] for k in sorted(expected_full)]
            or final["summaries"] != recovered["summaries"]):
        raise ValueError("follow-up rewrote historical authority without a scheduled migration")
    available = any(r["epoch"] == 1 and r["request_id"] == "original" for r in (*recovered["receipts"], *recovered["summaries"]))
    original = requests(row)[0]
    same = req["content_utf8"] == original["content_utf8"]
    original_approval = next(r["approved_sha256"] for r in initial_full if r["request_id"] == "original")
    wanted = reply("replayed", req, 2, original_approval) if same else reply("conflict", req)
    supported = known and no_extra and available and answer == wanted
    unavailable = known and no_extra and answer == reply("outcome_unavailable", req)
    normal = row["cut"] == "normal"
    completed = row["cut"] in {"after_commit", "normal"}
    full_rows = [r for r in recovered["receipts"] if r["epoch"] == 1]
    summaries = [r for r in recovered["summaries"] if r["epoch"] == 1]
    active, full, compact = recovered_layout(row, row["mode"])
    new_intent = row["scenario"] == "new_epoch"
    new_ok = new_intent and len(final["effects"]) == 3 and answer == reply("committed", req, 4, sha(req["content_utf8"].encode()))
    return {
        "known_no_extra": known and no_extra,
        "repeat_supported": row["scenario"] == "repeat" and supported,
        "changed_supported": known and row["scenario"] != "repeat" and supported,
        "unavailable_known": unavailable,
        "gap_supported": row["scenario"] == "repeat" and row["cut"] in {"after_fence_cleanup", "after_summary"} and supported,
        "completed_known_supported": completed and supported, "completed_captures": completed,
        "completed_full_rows": len(full_rows) if completed else 0,
        "completed_summary_rows": len(summaries) if completed else 0,
        "completed_no_old_payload": completed and not any(r["payload_utf8"] is not None for r in full_rows),
        "new_epoch_completed": new_ok,
        "unseen_old_refused": row["scenario"] == "unseen_old" and no_extra and answer == reply("outcome_unavailable", req),
        "recovered_epoch_1": recovered["active_epoch"] == 1, "recovered_epoch_2": recovered["active_epoch"] == 2,
        "layout_matches": (recovered["active_epoch"], recovered["receipts"], recovered["summaries"]) == (active, full, compact),
        "coherent_final": final["state"]["approved_sha256"] in (None, final["state"]["content_sha256"]),
        "current_policy_preserved": not new_intent and final["state"] == initial["state"] and final["delivery"] == initial["delivery"],
        "declared_exit": not normal, "normal_compaction": normal, "child_completions": 1,
        "false_history": int(known and answer["status"] in {"replayed", "conflict"} and not supported),
        "consistent_observations": True, "summary_schema_valid": recovered["summary_columns"] == list(SUMMARY_COLUMNS),
        "old_full_payload_bytes": sum(len(r["payload_utf8"].encode()) for r in full_rows if r["payload_utf8"] is not None),
    }


def criteria(arms):
    def vector(name):
        return [arms[m][name] for m in MODES]
    return {
        "mutation_safety_and_current_policy": vector("known_no_extra") == [24]*4 and vector("current_policy_preserved") == [25]*4 and vector("coherent_final") == [26]*4,
        "repeat_outcomes_and_unavailability": vector("repeat_supported") == [20,12,12,20] and vector("unavailable_known") == [0,12,8,0],
        "changed_intent_classification": vector("changed_supported") == [4,0,4,4],
        "migration_gap_availability": vector("gap_supported") == [8,8,0,8],
        "completed_compact_representation": vector("completed_captures") == [14]*4 and vector("completed_full_rows") == [28,0,0,0] and vector("completed_summary_rows") == [0,0,28,28] and vector("completed_no_old_payload") == [0,14,14,14] and vector("summary_schema_valid") == [26]*4,
        "new_namespace_and_unseen_old_controls": vector("new_epoch_completed") == vector("unseen_old_refused") == [1]*4,
        "recovered_epoch_and_layout": vector("recovered_epoch_2") == [14,14,22,14] and vector("recovered_epoch_1") == [12,12,4,12] and vector("layout_matches") == [26]*4,
        "completed_original_outcomes": vector("completed_known_supported") == [12,0,12,12],
        "exact_fault_and_completion_coverage": vector("declared_exit") == [16]*4 and vector("normal_compaction") == [10]*4 and vector("child_completions") == [26]*4,
        "supported_evidence_and_no_unexpected_errors": vector("false_history") == [0]*4 and vector("consistent_observations") == [26]*4 and vector("infrastructure_errors") == [0]*4,
    }


def summarize(records, cases):
    wanted = {(c["case_id"], m) for c in cases for m in MODES}
    if len(records) != 104 or {(r["case_id"], r["mode"]) for r in records} != wanted:
        raise ValueError("one record per declared case/mode required")
    declared = {c["case_id"]: c for c in cases}
    arms = {}
    for mode in MODES:
        rows = [r for r in records if r["mode"] == mode]
        good = []
        for row in rows:
            if any(row[k] != v for k, v in declared[row["case_id"]].items()):
                raise ValueError("raw case declaration changed")
            if row["status"] == "complete":
                actual = assess(row)
                if actual != row["oracle"]:
                    raise ValueError("stored oracle differs from raw evidence")
                good.append(actual)
            elif row["status"] != "infrastructure_error" or row["oracle"] is not None:
                raise ValueError("invalid raw execution status")
        arms[mode] = {"cases": len(rows), "known_cases": 24, "repeat_cases": 20, "changed_cases": 4,
                      "gap_cases": 8, "completed_known_cases": 12, "infrastructure_errors": len(rows)-len(good),
                      **{field: sum(v[field] for v in good) for field in FIELDS}}
    return {"arms": arms, "criteria": criteria(arms)}


def run_case(case, mode):
    if mode not in MODES:
        raise ValueError("unknown compaction mode")
    row = {**case, "mode": mode, "status": "pending", "error_phase": "setup", "error_type": None,
           "error_detail": None, "initial": None, "recovered": None, "final": None,
           "followup_request": requests(case)[2], "followup_response": None, "oracle": None,
           "child": {"command": [], "returncode": None, "stdout": "", "stderr": "", "events": [], "response": None}}
    with tempfile.TemporaryDirectory(prefix="codeguardian-compaction-") as directory:
        root = Path(directory)
        try:
            store = CompactionPublicationStore(root, mode)
            store.initialize(b"approved=version-a\n")
            for req in requests(case)[:2]:
                value = req["content_utf8"]
                store.publish(req["epoch"], req["request_id"], None if value is None else value.encode())
            row["initial"] = capture(store)
            child = row["child"]
            child["command"] = [sys.executable, str(ROOT / "experiments/compaction_worker.py"), "--root", str(root),
                                "--mode", mode, "--cut", case["cut"]]
            row["error_phase"] = "child_execution"
            try:
                result = subprocess.run(child["command"], capture_output=True, text=True, timeout=STEP_TIMEOUT)
            except subprocess.TimeoutExpired as error:
                child["stdout"] = error.stdout.decode(errors="replace") if isinstance(error.stdout, bytes) else error.stdout or ""
                child["stderr"] = error.stderr.decode(errors="replace") if isinstance(error.stderr, bytes) else error.stderr or ""
                raise
            child.update(returncode=result.returncode, stdout=result.stdout, stderr=result.stderr)
            child["events"] = [json.loads(line) for line in child["stdout"].splitlines()]
            responses = [e["response"] for e in child["events"] if e.get("kind") == "compaction_result"]
            child["response"] = responses[0] if len(responses) == 1 else None
            row["error_phase"] = "child_validation"
            validate_child(row)
            row["error_phase"] = "recovery"
            reopened = CompactionPublicationStore(root, mode)
            row["recovered"] = capture(reopened)
            req = row["followup_request"]
            value = req["content_utf8"]
            row["error_phase"] = "followup"
            row["followup_response"] = reopened.publish(req["epoch"], req["request_id"], None if value is None else value.encode())
            row["final"] = capture(CompactionPublicationStore(root, mode))
            row["error_phase"] = "oracle"
            row["oracle"] = assess(row)
            row.update(status="complete", error_phase=None)
        except (OSError, ValueError, RuntimeError, UnicodeError, sqlite3.Error, subprocess.SubprocessError) as error:
            row.update(status="infrastructure_error", error_type=type(error).__name__, error_detail=str(error))
    return row


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--base-commit", required=True)
    parser.add_argument("--freeze-commit", required=True)
    parser.add_argument("--output-dir", type=Path, default=ROOT / "experiments/results")
    args = parser.parse_args()
    started = datetime.now(timezone.utc)
    cases = load_cases(args.dataset)
    records = [run_case(c, m) for c in cases for m in MODES]
    result = summarize(records, cases)
    run = started.strftime("%Y-%m-%dT%H-%M-%S-%fZ-compaction-v1")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    raw = args.output_dir / (run + ".jsonl")
    metadata = {"started_at_utc": started.isoformat(), "finished_at_utc": datetime.now(timezone.utc).isoformat(),
                "python_version": platform.python_version(), "sqlite_version": sqlite3.sqlite_version, "platform": platform.platform(),
                "base_commit": args.base_commit, "freeze_commit": args.freeze_commit, "command": [sys.executable, *sys.argv],
                "dataset": str(args.dataset), "dataset_sha256": sha(args.dataset.read_bytes()),
                "source_sha256": {p: sha((ROOT/p).read_bytes()) for p in SOURCES}, "results_file": raw.name, "summary": result,
                "interpretation_limit": "Curated application-exit migration histories; typed SHA-256 summaries assume collision/second-preimage resistance; no total-space, secure-erasure, concurrency, performance or host-power-loss claim."}
    with raw.open("x", encoding="utf-8") as handle:
        for row in records:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    with (args.output_dir/(run+"-summary.json")).open("x", encoding="utf-8") as handle:
        json.dump(metadata, handle, indent=2, ensure_ascii=False, sort_keys=True)
        handle.write("\n")
    print(json.dumps(result, indent=2, sort_keys=True))
    print("Saved " + run)
    return int(any(a["infrastructure_errors"] for a in result["arms"].values()))


if __name__ == "__main__":
    raise SystemExit(main())
