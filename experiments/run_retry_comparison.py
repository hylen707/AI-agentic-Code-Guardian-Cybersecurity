"""Compare request retry semantics after known publisher-process exits."""
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

from src.publication_store import recover_value
from src.retry_store import ARMS, RetryPublicationStore

CUTS = ("before_commit", "after_state_commit", "after_record_commit", "after_ack")
VALUES = {"ascii": "approved=version-b\n", "empty": "", "unicode": "approved=안전 ✓\n"}
INITIAL = "approved=version-a\n"
LATER = "approved=version-c\n"
SETTINGS = {"journal_mode": "delete", "synchronous": 2, "integrity_check": "ok"}
SOURCES = ("src/retry_store.py", "src/publication_store.py", "experiments/retry_worker.py",
           "experiments/run_retry_comparison.py", "experiments/verify_retry_results.py",
           "tests/test_retry_store.py", "docs/RETRY_PROTOCOL.md")


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def schedules() -> set[tuple]:
    result = {("single", "update", value, "none") for value in VALUES}
    result.add(("single", "revoke", "ascii", "none"))
    result.update((s, op, "ascii", "none") for s in ("repeat", "distinct", "intervening") for op in ("update", "revoke"))
    result.update((s, "update", "ascii", "none") for s in ("conflict_value", "conflict_operation"))
    result.update(("crash", op, "ascii", cut) for op in ("update", "revoke") for cut in CUTS)
    return result


def load_cases(path: Path) -> list[dict]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or set(data) != {"schema_version", "cases"} or data["schema_version"] != "retry-eval-v1":
        raise ValueError("unsupported retry manifest")
    cases = data["cases"]
    if not isinstance(cases, list) or len(cases) != 20:
        raise ValueError("twenty frozen cases required")
    ids, actual = set(), set()
    for case in cases:
        if (not isinstance(case, dict) or set(case) != {"case_id", "scenario", "operation", "value", "cut"}
                or not all(isinstance(v, str) for v in case.values()) or not case["case_id"] or case["case_id"] in ids):
            raise ValueError("invalid or duplicate case")
        signature = tuple(case[k] for k in ("scenario", "operation", "value", "cut"))
        if signature in actual:
            raise ValueError("repeated semantic schedule")
        ids.add(case["case_id"])
        actual.add(signature)
    if actual != schedules():
        raise ValueError("manifest differs from the fixed retry matrix")
    return cases


def first_content(case: dict) -> str | None:
    return None if case["operation"] == "revoke" else VALUES[case["value"]]


def followups(case: dict) -> list[dict]:
    content, scenario = first_content(case), case["scenario"]
    same = {"request_id": "request-1", "content_utf8": content}
    if scenario == "single":
        return []
    if scenario in {"repeat", "crash"}:
        return [same]
    if scenario == "conflict_value":
        return [{"request_id": "request-1", "content_utf8": LATER}]
    if scenario == "conflict_operation":
        return [{"request_id": "request-1", "content_utf8": None}]
    if scenario == "distinct":
        return [{"request_id": "request-2", "content_utf8": content}]
    if scenario == "intervening":
        return [{"request_id": "request-2", "content_utf8": None if content is not None else LATER}, same]
    raise ValueError("unknown scenario")


def expected_trace(case: dict) -> tuple[int, list[dict]]:
    events = []
    for stage in CUTS:
        if stage == "after_ack":
            content = first_content(case)
            events.append({"seq": len(events), "kind": "acknowledged", "response": {
                "status": "committed", "request_id": "request-1", "revision": 2,
                "approved_sha256": None if content is None else sha(content.encode("utf-8"))}})
        events.append({"seq": len(events), "kind": "checkpoint", "stage": stage})
        if stage == case["cut"]:
            return 73, events
    events.append({"seq": len(events), "kind": "completed"})
    return 0, events


def validate_trace(row: dict) -> None:
    code, events = expected_trace(row)
    decoded = [json.loads(line) for line in row["worker_stdout"].splitlines()]
    if row["worker_returncode"] != code or row["worker_events"] != events or decoded != events or row["worker_stderr"]:
        raise ValueError("publisher did not reach the exact declared boundary")


def capture(store: RetryPublicationStore) -> dict:
    observed = store.inspect()
    state = observed["state"]
    response = recover_value(state)
    payload = response.pop("content")
    requests = [{**{k: v for k, v in r.items() if k != "payload"},
                 "payload_utf8": None if r["payload"] is None else r["payload"].decode("utf-8")}
                for r in observed["receipts"]]
    return {"state": {"revision": state.revision, "approved_sha256": state.approved_sha256,
                      "content_utf8": state.content.decode("utf-8"), "content_sha256": sha(state.content)},
            "effects": observed["effects"], "receipts": requests,
            "delivery": {**response, "delivered_utf8": None if payload is None else payload.decode("utf-8")},
            "sqlite_settings": store.settings()}


def validate_capture(observed: dict) -> bool:
    if set(observed) != {"state", "effects", "receipts", "delivery", "sqlite_settings"} or observed["sqlite_settings"] != SETTINGS:
        raise ValueError("incomplete capture or wrong SQLite settings")
    state, output = observed["state"], observed["delivery"]
    if (set(state) != {"revision", "approved_sha256", "content_utf8", "content_sha256"}
            or type(state["revision"]) is not int or state["revision"] < 1
            or state["content_sha256"] != sha(state["content_utf8"].encode("utf-8"))):
        raise ValueError("invalid direct state observation")
    delivered = output["status"] == "delivered"
    if (output["status"] not in {"blocked", "delivered"} or output["revision"] != state["revision"]
            or (delivered and output["delivered_utf8"] != state["content_utf8"])
            or (not delivered and output["delivered_utf8"] is not None)):
        raise ValueError("output differs from captured state")
    effects = observed["effects"]
    if (not isinstance(effects, list) or [e["revision"] for e in effects] != list(range(2, state["revision"] + 1))
            or any(set(e) != {"revision", "request_id", "operation", "approved_sha256"} for e in effects)):
        raise ValueError("effect observer differs from committed revision sequence")
    requests = observed["receipts"]
    if (not isinstance(requests, list) or any(set(r) != {"request_id", "operation", "payload_utf8", "revision", "approved_sha256"} for r in requests)
            or len({r["request_id"] for r in requests}) != len(requests)):
        raise ValueError("invalid receipt observation")
    return state["approved_sha256"] is None or state["approved_sha256"] == state["content_sha256"]


def assess(row: dict) -> dict:
    """Build an ideal identity model; use actual state/effects to test replies."""
    declared = followups(row)
    if len(row["attempts"]) != len(declared) or any(a["request"] != r for a, r in zip(row["attempts"], declared)):
        raise ValueError("follow-up requests differ from declared schedule")
    observations = [row["initial_recovery"], *(a["after"] for a in row["attempts"])]
    coherent = [validate_capture(o) for o in observations]
    state = {"revision": 1, "approved_sha256": sha(INITIAL.encode()), "content_utf8": INITIAL,
             "content_sha256": sha(INITIAL.encode())}
    effects, identities = [], {}

    def model(request: dict) -> dict:
        key, content = request["request_id"], request["content_utf8"]
        if key in identities:
            prior = identities[key]
            if prior[0] != content:
                return {"status": "conflict", "request_id": key, "revision": None, "approved_sha256": None}
            return {**prior[1], "status": "replayed"}
        state["revision"] += 1
        if content is not None:
            state["content_utf8"] = content
            state["content_sha256"] = sha(content.encode())
        state["approved_sha256"] = None if content is None else sha(content.encode())
        effects.append({"revision": state["revision"], "request_id": key,
                        "operation": "revoke" if content is None else "update", "approved_sha256": state["approved_sha256"]})
        result = {"status": "committed", "request_id": key, "revision": state["revision"],
                  "approved_sha256": state["approved_sha256"]}
        identities[key] = (content, result.copy())
        return result

    def matches(observed: dict) -> bool:
        active = state["approved_sha256"] is not None
        delivery = {"status": "delivered" if active else "blocked", "revision": state["revision"],
                    "reason": "verified_recovery" if active else "approval_revoked",
                    "delivered_utf8": state["content_utf8"] if active else None}
        return observed["state"] == state and observed["effects"] == effects and observed["delivery"] == delivery

    committed = row["cut"] != "before_commit"
    if committed:
        model({"request_id": "request-1", "content_utf8": first_content(row)})
    initial_matches = matches(observations[0])
    success = initial_matches
    for actual, request in zip(row["attempts"], declared):
        wanted = model(request)
        response = actual["response"]
        if set(response) != set(wanted) or response["status"] not in {"committed", "replayed", "conflict"}:
            raise ValueError("invalid response shape")
        semantic = (all(response[k] == wanted[k] for k in ("request_id", "revision", "approved_sha256"))
                    and (response["status"] == "conflict") == (wanted["status"] == "conflict"))
        success = success and semantic and matches(actual["after"])
    final = observations[-1]
    same_retry = row["scenario"] in {"repeat", "intervening", "crash"}
    extra = max(0, sum(e["request_id"] == "request-1" for e in final["effects"]) - 1)
    gap = row["cut"] == "after_state_commit"
    late = row["scenario"] == "intervening"
    conflict = row["scenario"] in {"conflict_value", "conflict_operation"}
    unchanged = len(observations) > 1 and observations[-1] == observations[-2]
    return {"intrinsic_state_coherent": coherent[-1], "initial_state_matches_schedule": initial_matches,
            "contract_satisfied": bool(success), "same_intent_retry_case": same_retry,
            "retry_contract_satisfied": same_retry and bool(success), "extra_request1_effects": extra,
            "retry_duplicate_case": same_retry and extra > 0, "gap_duplicate_case": gap and extra > 0,
            "first_receipt_missing_at_gap": gap and not any(r["request_id"] == "request-1" for r in observations[0]["receipts"]),
            "conflict_case_success": conflict and bool(success) and unchanged,
            "distinct_case_success": row["scenario"] == "distinct" and bool(success),
            "late_retry_preserved": late and bool(success) and unchanged,
            "revoked_value_reinstated": late and row["operation"] == "update" and observations[-2]["delivery"]["reason"] == "approval_revoked" and final["delivery"]["status"] == "delivered",
            "newer_approval_withdrawn": late and row["operation"] == "revoke" and observations[-2]["delivery"]["status"] == "delivered" and final["delivery"]["reason"] == "approval_revoked",
            "single_control_success": row["scenario"] == "single" and bool(success)}


def run_case(case: dict, arm: str) -> dict:
    if arm not in ARMS:
        raise ValueError("unknown arm")
    row = {**case, "arm": arm, "status": "pending", "error_phase": "setup", "error_type": None,
           "worker_returncode": None, "worker_stdout": "", "worker_stderr": "", "worker_events": [],
           "initial_recovery": None, "attempts": [], "oracle": None}
    with tempfile.TemporaryDirectory(prefix="codeguardian-retry-") as directory:
        root = Path(directory)
        try:
            RetryPublicationStore(root, arm).initialize(INITIAL.encode("utf-8"))
            command = [sys.executable, str(ROOT / "experiments/retry_worker.py"), "--root", str(root), "--arm", arm,
                       "--operation", case["operation"], "--value", case["value"], "--cut", case["cut"]]
            row["worker_command"] = command
            row["error_phase"] = "publisher"
            child = subprocess.run(command, capture_output=True, text=True, timeout=15)
            row.update(worker_returncode=child.returncode, worker_stdout=child.stdout, worker_stderr=child.stderr)
            row["error_phase"] = "trace_validation"
            row["worker_events"] = [json.loads(line) for line in child.stdout.splitlines()]
            validate_trace(row)
            row["error_phase"] = "restart"
            row["initial_recovery"] = capture(RetryPublicationStore(root, arm))
            for request in followups(case):
                row["error_phase"] = "follow_up"
                content = request["content_utf8"]
                response = RetryPublicationStore(root, arm).publish_request(request["request_id"], None if content is None else content.encode("utf-8"))
                row["attempts"].append({"request": request, "response": response, "after": capture(RetryPublicationStore(root, arm))})
            row["error_phase"] = "oracle"
            row["oracle"] = assess(row)
            row.update(status="complete", error_phase=None)
        except (OSError, ValueError, RuntimeError, UnicodeError, sqlite3.Error, subprocess.SubprocessError) as exc:
            row.update(status="infrastructure_error", error_type=type(exc).__name__)
            if isinstance(exc, subprocess.TimeoutExpired):
                for field, data in (("worker_stdout", exc.stdout), ("worker_stderr", exc.stderr)):
                    row[field] = data.decode("utf-8", errors="replace") if isinstance(data, bytes) else data or ""
    return row


def criteria(arms: dict) -> dict:
    a, b, c = (arms[name] for name in ARMS)
    keyed = (b, c)
    return {
        "unkeyed_ten_duplicate_retry_cases": a["retry_duplicate_cases"] == 10 and a["successful_retries"] == 2,
        "split_two_gap_duplicates": b["retry_duplicate_cases"] == b["gap_duplicate_cases"] == b["first_receipt_gaps"] == 2 and b["successful_retries"] == 10,
        "atomic_twelve_successful_retries_no_duplicates": c["successful_retries"] == 12 and c["retry_duplicate_cases"] == c["first_receipt_gaps"] == 0,
        "keyed_reject_changed_intent": all(x["correct_conflicts"] == 2 for x in keyed),
        "all_accept_distinct_ids_identical_intent": all(x["distinct_completions"] == 2 for x in arms.values()),
        "keyed_preserve_later_state": all(x["late_states_preserved"] == 2 and x["revoked_values_reinstated"] == x["newer_approvals_withdrawn"] == 0 for x in keyed),
        "unkeyed_reauthorization_and_withdrawal": a["revoked_values_reinstated"] == a["newer_approvals_withdrawn"] == 1,
        "all_four_single_controls_succeed": all(x["single_control_successes"] == 4 for x in arms.values()),
        "all_twenty_final_states_coherent": all(x["coherent_final_states"] == 20 for x in arms.values()),
        "all_declared_process_boundaries_verified": all(x["verified_terminations"] == 8 and x["verified_normal_completions"] == 12 and x["infrastructure_errors"] == 0 for x in arms.values()),
    }


def summarize(records: list[dict], cases: list[dict]) -> dict:
    grid = [(r["case_id"], r["arm"]) for r in records]
    wanted = {(c["case_id"], arm) for c in cases for arm in ARMS}
    if len(grid) != len(wanted) or set(grid) != wanted:
        raise ValueError("exactly one record per declared case/arm required")
    declared = {c["case_id"]: c for c in cases}
    for row in records:
        if any(row[k] != v for k, v in declared[row["case_id"]].items()):
            raise ValueError("record changed a declared case")
        if row["status"] == "complete":
            validate_trace(row)
            if row["oracle"] != assess(row):
                raise ValueError("stored oracle differs from raw observations")
        elif row["status"] != "infrastructure_error" or row.get("oracle") is not None:
            raise ValueError("invalid run status")
    arms = {}
    mapping = {"coherent_final_states": "intrinsic_state_coherent", "initial_states_match": "initial_state_matches_schedule",
               "contracts_satisfied": "contract_satisfied", "successful_retries": "retry_contract_satisfied",
               "retry_duplicate_cases": "retry_duplicate_case", "gap_duplicate_cases": "gap_duplicate_case",
               "first_receipt_gaps": "first_receipt_missing_at_gap", "correct_conflicts": "conflict_case_success",
               "distinct_completions": "distinct_case_success", "late_states_preserved": "late_retry_preserved",
               "revoked_values_reinstated": "revoked_value_reinstated", "newer_approvals_withdrawn": "newer_approval_withdrawn",
               "single_control_successes": "single_control_success"}
    for arm in ARMS:
        rows = [r for r in records if r["arm"] == arm]
        arms[arm] = {"cases": len(rows), "retry_cases": sum(r["scenario"] in {"repeat", "crash", "intervening"} for r in rows),
                     "gap_cases": sum(r["cut"] == "after_state_commit" for r in rows),
                     "conflict_cases": sum(r["scenario"].startswith("conflict_") for r in rows),
                     "distinct_cases": sum(r["scenario"] == "distinct" for r in rows),
                     "late_retry_cases": sum(r["scenario"] == "intervening" for r in rows),
                     "single_controls": sum(r["scenario"] == "single" for r in rows),
                     "termination_cases": sum(r["cut"] != "none" for r in rows),
                     "verified_terminations": sum(r["status"] == "complete" and r["cut"] != "none" for r in rows),
                     "verified_normal_completions": sum(r["status"] == "complete" and r["cut"] == "none" for r in rows),
                     "infrastructure_errors": sum(r["status"] == "infrastructure_error" for r in rows),
                     **{dst: sum(bool((r.get("oracle") or {}).get(src)) for r in rows) for dst, src in mapping.items()}}
    return {"arms": arms, "criteria": criteria(arms)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--base-commit", required=True)
    parser.add_argument("--freeze-commit", required=True)
    parser.add_argument("--output-dir", type=Path, default=ROOT / "experiments/results")
    args = parser.parse_args()
    started = datetime.now(timezone.utc)
    cases = load_cases(args.dataset)
    records = [run_case(case, arm) for case in cases for arm in ARMS]
    summary = summarize(records, cases)
    run_id = started.strftime("%Y-%m-%dT%H-%M-%S-%fZ-retry-v1")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    raw = args.output_dir / (run_id + ".jsonl")
    metadata = {"started_at_utc": started.isoformat(), "finished_at_utc": datetime.now(timezone.utc).isoformat(),
                "python_version": platform.python_version(), "sqlite_version": sqlite3.sqlite_version, "platform": platform.platform(),
                "base_commit": args.base_commit, "freeze_commit": args.freeze_commit, "command": [sys.executable, *sys.argv],
                "dataset": str(args.dataset), "dataset_sha256": sha(args.dataset.read_bytes()),
                "source_sha256": {p: sha((ROOT / p).read_bytes()) for p in SOURCES},
                "results_file": raw.name, "summary": summary,
                "interpretation_limit": "Twenty developer-visible sequential request schedules per arm; no receipt eviction, concurrent writers, external effects, power loss, or live-agent evaluation."}
    with raw.open("x", encoding="utf-8") as handle:
        for row in records:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    with (args.output_dir / (run_id + "-summary.json")).open("x", encoding="utf-8") as handle:
        json.dump(metadata, handle, indent=2, ensure_ascii=False)
        handle.write("\n")
    print(json.dumps(summary, indent=2))
    print("Saved " + run_id)
    return int(any(x["infrastructure_errors"] for x in summary["arms"].values()))


if __name__ == "__main__":
    raise SystemExit(main())
