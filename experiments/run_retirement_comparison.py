"""Compare receipt retirement, historical replies, and delayed request effects."""
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
from src.retirement_store import ARMS, RetirementPublicationStore

CUTS = ("before_retire", "after_cleanup", "after_commit", "after_ack")
INITIAL = "approved=version-a\n"
VALUES = {"ascii": "approved=version-b\n", "empty": "", "unicode": "approved=안전 ✓\n"}
LATER = "approved=version-c\n"
SETTINGS = {"journal_mode": "delete", "synchronous": 2, "integrity_check": "ok"}
SOURCES = ("src/retirement_store.py", "src/publication_store.py", "src/retry_store.py",
           "experiments/retirement_worker.py", "experiments/run_retirement_comparison.py",
           "experiments/verify_retirement_results.py", "tests/test_retirement_store.py", "docs/RETIREMENT_PROTOCOL.md")


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def schedules() -> set[tuple]:
    result = {("late_known", op, "ascii", cut) for op in ("update", "revoke") for cut in ("none", *CUTS)}
    result.update((s, op, "ascii", "none") for s in ("current_repeat", "unseen_retired") for op in ("update", "revoke"))
    result.update(("current_single", "update", value, "none") for value in ("empty", "unicode"))
    result.update((s, "update", value, "none") for s, value in (
        ("current_conflict_value", "ascii"), ("current_conflict_operation", "empty"),
        ("future", "ascii"), ("new_epoch_same_id", "ascii")))
    return result


def load_cases(path: Path) -> list[dict]:
    manifest = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(manifest, dict) or set(manifest) != {"schema_version", "cases"} or manifest["schema_version"] != "retirement-eval-v1":
        raise ValueError("unsupported retirement manifest")
    cases = manifest["cases"]
    if not isinstance(cases, list) or len(cases) != 20:
        raise ValueError("twenty fixed cases required")
    ids, signatures = set(), set()
    for case in cases:
        if (not isinstance(case, dict) or set(case) != {"case_id", "scenario", "operation", "value", "cut"}
                or not all(isinstance(v, str) for v in case.values()) or not case["case_id"] or case["case_id"] in ids):
            raise ValueError("invalid or repeated case ID")
        signature = tuple(case[k] for k in ("scenario", "operation", "value", "cut"))
        if signature in signatures:
            raise ValueError("repeated semantic schedule")
        ids.add(case["case_id"])
        signatures.add(signature)
    if signatures != schedules():
        raise ValueError("manifest differs from the frozen matrix")
    return cases


def request(epoch: int, key: str, content: str | None) -> dict:
    return {"epoch": epoch, "request_id": key, "content_utf8": content}


def seed_requests(case: dict) -> list[dict]:
    update = case["operation"] == "update"
    return [request(1, "request-1", VALUES["ascii"] if update else None),
            request(1, "request-2", None if update else LATER)]


def followups(case: dict) -> list[dict]:
    value = None if case["operation"] == "revoke" else VALUES[case["value"]]
    scenario = case["scenario"]
    current = request(2, "current-1", value)
    if scenario == "late_known":
        return [seed_requests(case)[0]]
    if scenario == "current_repeat":
        return [current, current.copy()]
    if scenario in {"current_conflict_value", "current_conflict_operation"}:
        changed = LATER if scenario == "current_conflict_value" else None
        return [current, request(2, "current-1", changed)]
    if scenario == "current_single":
        return [current]
    if scenario == "unseen_retired":
        return [request(1, "unseen-1", value)]
    if scenario == "future":
        return [request(3, "future-1", value)]
    if scenario == "new_epoch_same_id":
        return [request(2, "request-1", value)]
    raise ValueError("unknown follow-up schedule")


def expected_trace(cut: str) -> tuple[int, list[dict]]:
    events = []
    for stage in CUTS:
        if stage == "after_ack":
            events.append({"seq": len(events), "kind": "acknowledged", "response": {"status": "retired", "active_epoch": 2}})
        events.append({"seq": len(events), "kind": "checkpoint", "stage": stage})
        if stage == cut:
            return 73, events
    events.append({"seq": len(events), "kind": "completed"})
    return 0, events


def validate_trace(row: dict) -> None:
    code, events = expected_trace(row["cut"])
    decoded = [json.loads(line) for line in row["worker_stdout"].splitlines()]
    if row["worker_returncode"] != code or row["worker_events"] != events or decoded != events or row["worker_stderr"]:
        raise ValueError("retirement did not reach the exact declared boundary")


def capture(store: RetirementPublicationStore) -> dict:
    observed = store.inspect()
    state = observed["state"]
    delivered = recover_value(state)
    payload = delivered.pop("content")
    receipts = [{**{k: v for k, v in r.items() if k != "payload"},
                 "payload_utf8": None if r["payload"] is None else r["payload"].decode("utf-8")}
                for r in observed["receipts"]]
    return {"state": {"revision": state.revision, "approved_sha256": state.approved_sha256,
                      "content_utf8": state.content.decode("utf-8"), "content_sha256": sha(state.content)},
            "active_epoch": observed["active_epoch"], "effects": observed["effects"], "receipts": receipts,
            "delivery": {**delivered, "delivered_utf8": None if payload is None else payload.decode("utf-8")},
            "sqlite_settings": store.settings()}


def validate_capture(observed: dict) -> bool:
    if set(observed) != {"state", "active_epoch", "effects", "receipts", "delivery", "sqlite_settings"} or observed["sqlite_settings"] != SETTINGS:
        raise ValueError("incomplete capture or wrong SQLite settings")
    active, state, output = observed["active_epoch"], observed["state"], observed["delivery"]
    if type(active) is not int or not 1 <= active <= 2**63 - 1:
        raise ValueError("invalid active epoch observation")
    if (set(state) != {"revision", "approved_sha256", "content_utf8", "content_sha256"}
            or type(state["revision"]) is not int or state["revision"] < 1
            or state["content_sha256"] != sha(state["content_utf8"].encode("utf-8"))):
        raise ValueError("invalid state bytes/hash or revision")
    if (output["status"] not in {"delivered", "blocked"} or output["revision"] != state["revision"]
            or (output["status"] == "delivered" and output["delivered_utf8"] != state["content_utf8"])
            or (output["status"] == "blocked" and output["delivered_utf8"] is not None)):
        raise ValueError("delivery differs from captured state")
    effects, receipts = observed["effects"], observed["receipts"]
    if (not isinstance(effects, list) or [e["revision"] for e in effects] != list(range(2, state["revision"] + 1))
            or any(set(e) != {"revision", "epoch", "request_id", "operation", "approved_sha256"} or type(e["epoch"]) is not int or e["epoch"] < 1 for e in effects)):
        raise ValueError("invalid effect observer sequence")
    if effects and effects[-1]["approved_sha256"] != state["approved_sha256"]:
        raise ValueError("last effect differs from current approval")
    if (not isinstance(receipts, list) or any(set(r) != {"epoch", "request_id", "operation", "payload_utf8", "revision", "approved_sha256"} for r in receipts)
            or len({(r["epoch"], r["request_id"]) for r in receipts}) != len(receipts)):
        raise ValueError("invalid receipt observation")
    by_revision = {e["revision"]: e for e in effects}
    for r in receipts:
        effect = by_revision.get(r["revision"])
        if effect is None or any(effect[k] != r[k] for k in ("epoch", "request_id", "operation", "approved_sha256")):
            raise ValueError("receipt lacks its matching committed effect")
        if r["operation"] == "revoke":
            valid = r["payload_utf8"] is None and r["approved_sha256"] is None
        else:
            valid = r["operation"] == "update" and isinstance(r["payload_utf8"], str) and r["approved_sha256"] == sha(r["payload_utf8"].encode())
        if not valid:
            raise ValueError("receipt intent/digest differs")
    return state["approved_sha256"] is None or state["approved_sha256"] == state["content_sha256"]


def assess(row: dict) -> dict:
    wanted_inputs = followups(row)
    if len(row["attempts"]) != len(wanted_inputs) or any(a["request"] != r for a, r in zip(row["attempts"], wanted_inputs)):
        raise ValueError("follow-up input differs from declared schedule")
    observations = [row["before_retirement"], row["recovered"], *(a["after"] for a in row["attempts"])]
    coherences = [validate_capture(o) for o in observations]
    state = {"revision": 1, "approved_sha256": sha(INITIAL.encode()), "content_utf8": INITIAL, "content_sha256": sha(INITIAL.encode())}
    effects, bindings = [], {}

    def reply(status: str, req: dict, revision=None, approved=None) -> dict:
        return {"status": status, "epoch": req["epoch"], "request_id": req["request_id"],
                "revision": revision, "approved_sha256": approved}

    def ideal_publish(req: dict) -> dict:
        key, value = (req["epoch"], req["request_id"]), req["content_utf8"]
        if key in bindings:
            prior = bindings[key]
            return reply("conflict", req) if prior[0] != value else {**prior[1], "status": "replayed"}
        state["revision"] += 1
        if value is not None:
            state["content_utf8"], state["content_sha256"] = value, sha(value.encode())
        state["approved_sha256"] = None if value is None else sha(value.encode())
        effects.append({"revision": state["revision"], "epoch": req["epoch"], "request_id": req["request_id"],
                        "operation": "revoke" if value is None else "update", "approved_sha256": state["approved_sha256"]})
        result = reply("committed", req, state["revision"], state["approved_sha256"])
        bindings[key] = (value, result.copy())
        return result

    def record(req: dict, result: dict) -> dict:
        return {"epoch": req["epoch"], "request_id": req["request_id"], "operation": "revoke" if req["content_utf8"] is None else "update",
                "payload_utf8": req["content_utf8"], "revision": result["revision"], "approved_sha256": result["approved_sha256"]}

    def matches_current(observation: dict) -> bool:
        active = state["approved_sha256"] is not None
        output = {"status": "delivered" if active else "blocked", "reason": "verified_recovery" if active else "approval_revoked",
                  "revision": state["revision"], "delivered_utf8": state["content_utf8"] if active else None}
        return observation["state"] == state and observation["effects"] == effects and observation["delivery"] == output

    originals = seed_requests(row)
    original_receipts = [record(req, ideal_publish(req)) for req in originals]
    if (not matches_current(observations[0]) or observations[0]["active_epoch"] != 1
            or observations[0]["receipts"] != original_receipts):
        raise ValueError("seed fixture differs from declared initial publications")
    seed_state, seed_effects, seed_delivery = state.copy(), list(effects), observations[0]["delivery"].copy()
    logical_active = 1 if row["cut"] in {"before_retire", "after_cleanup"} else 2
    expected_receipts = original_receipts if (row["arm"] == "retain_all" or logical_active == 1) else []
    if row["arm"] == "split_fence" and row["cut"] == "after_cleanup":
        expected_receipts = []
    physical = {(r["epoch"], r["request_id"]): r.copy() for r in expected_receipts}
    recovered = row["recovered"]
    layout = (matches_current(recovered) and recovered["active_epoch"] == logical_active and recovered["receipts"] == expected_receipts)
    success = layout
    for attempt, req in zip(row["attempts"], wanted_inputs):
        epoch, key = req["epoch"], (req["epoch"], req["request_id"])
        if epoch > logical_active:
            allowed = [reply("future_epoch", req)]
        elif epoch < logical_active:
            allowed = [reply("epoch_retired", req)]
            if key in bindings:
                allowed.append({**bindings[key][1], "status": "replayed"} if bindings[key][0] == req["content_utf8"] else reply("conflict", req))
        else:
            result = ideal_publish(req)
            allowed = [result]
            if result["status"] == "committed":
                physical[key] = record(req, result)
        ordered = [physical[k] for k in sorted(physical)]
        success = (success and attempt["response"] in allowed and matches_current(attempt["after"])
                   and attempt["after"]["active_epoch"] == logical_active and attempt["after"]["receipts"] == ordered)
    final = observations[-1]
    late = row["scenario"] == "late_known"
    preserved = final["state"] == seed_state and final["effects"] == seed_effects and final["delivery"] == seed_delivery
    old_reply = {**bindings[(1, "request-1")][1], "status": "replayed"}
    last_response = row["attempts"][-1]["response"]
    extra = max(0, sum((e["epoch"], e["request_id"]) == (1, "request-1") for e in final["effects"]) - 1)
    unchanged = observations[-1] == observations[-2]
    old_rows = sum(r["epoch"] < recovered["active_epoch"] for r in recovered["receipts"])
    return {"contract_satisfied": bool(success), "intrinsic_state_coherent": coherences[-1], "retirement_layout_matches": bool(layout),
            "known_duplicate_case": late and extra > 0, "known_extra_effects": extra if late else 0,
            "known_policy_preserved": late and preserved,
            "historical_reply": late and preserved and last_response == old_reply,
            "known_closed_denial": late and logical_active == 2 and preserved and last_response == reply("epoch_retired", originals[0]),
            "revoked_value_reinstated": late and row["operation"] == "update" and extra > 0 and final["delivery"]["status"] == "delivered" and final["state"]["content_utf8"] == VALUES["ascii"],
            "newer_approval_withdrawn": late and row["operation"] == "revoke" and extra > 0 and final["delivery"]["reason"] == "approval_revoked",
            "cleanup_gap": recovered["active_epoch"] == 1 and not recovered["receipts"],
            "completed_retirement": recovered["active_epoch"] == 2,
            "old_receipt_rows_after_commit": old_rows if recovered["active_epoch"] == 2 else 0,
            "new_current_success": row["scenario"] in {"current_single", "new_epoch_same_id"} and bool(success),
            "current_repeat_success": row["scenario"] == "current_repeat" and bool(success) and unchanged,
            "current_conflict_success": row["scenario"].startswith("current_conflict_") and bool(success) and unchanged,
            "unseen_old_denied": row["scenario"] == "unseen_retired" and bool(success) and unchanged and last_response == reply("epoch_retired", wanted_inputs[-1]),
            "unseen_old_applied": row["scenario"] == "unseen_retired" and any((e["epoch"], e["request_id"]) == (1, "unseen-1") for e in final["effects"]),
            "future_rejected": row["scenario"] == "future" and bool(success) and unchanged}


def run_case(case: dict, arm: str) -> dict:
    if arm not in ARMS:
        raise ValueError("unknown retirement arm")
    row = {**case, "arm": arm, "status": "pending", "error_phase": "setup", "error_type": None,
           "worker_returncode": None, "worker_stdout": "", "worker_stderr": "", "worker_events": [],
           "before_retirement": None, "recovered": None, "attempts": [], "oracle": None}
    with tempfile.TemporaryDirectory(prefix="codeguardian-retirement-") as directory:
        root = Path(directory)
        try:
            store = RetirementPublicationStore(root, arm)
            store.initialize(INITIAL.encode())
            for req in seed_requests(case):
                value = req["content_utf8"]
                store.publish_request(req["epoch"], req["request_id"], None if value is None else value.encode())
            row["before_retirement"] = capture(store)
            command = [sys.executable, str(ROOT / "experiments/retirement_worker.py"), "--root", str(root), "--arm", arm, "--cut", case["cut"]]
            row["worker_command"] = command
            row["error_phase"] = "retirement_process"
            child = subprocess.run(command, capture_output=True, text=True, timeout=15)
            row.update(worker_returncode=child.returncode, worker_stdout=child.stdout, worker_stderr=child.stderr)
            row["error_phase"] = "trace_validation"
            row["worker_events"] = [json.loads(line) for line in child.stdout.splitlines()]
            validate_trace(row)
            row["error_phase"] = "recovery"
            row["recovered"] = capture(RetirementPublicationStore(root, arm))
            for req in followups(case):
                row["error_phase"] = "follow_up"
                value = req["content_utf8"]
                result = RetirementPublicationStore(root, arm).publish_request(req["epoch"], req["request_id"], None if value is None else value.encode())
                row["attempts"].append({"request": req, "response": result, "after": capture(RetirementPublicationStore(root, arm))})
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
    a, b, c, d = (arms[n] for n in ARMS)
    values = list(arms[n] for n in ARMS)
    return {
        "known_duplicate_counts": [x["known_duplicate_cases"] for x in values] == [0, 6, 2, 0],
        "known_preserved_policy_counts": [x["known_policy_preserved"] for x in values] == [10, 4, 8, 10],
        "historical_reply_and_rejection_tradeoff": [x["historical_replies"] for x in values] == [10, 4, 2, 4] and [x["known_closed_denials"] for x in values] == [0, 0, 6, 6],
        "known_policy_reversal_counts": all([x[k] for x in values] == [0, 3, 1, 0] for k in ("revoked_values_reinstated", "newer_approvals_withdrawn")),
        "only_split_has_cleanup_gap": [x["cleanup_gap_captures"] for x in values] == [0, 0, 2, 0],
        "committed_retirement_row_counts": all(x["completed_retirements"] == 16 for x in values) and [x["old_receipt_rows_after_commit"] for x in values] == [32, 0, 0, 0],
        "all_three_new_current_intents_complete": all(x["new_current_successes"] == 3 for x in values),
        "all_current_retries_preserve_one_effect": all(x["current_repeat_successes"] == 2 for x in values),
        "all_current_conflicts_rejected": all(x["current_conflict_successes"] == 2 for x in values),
        "unseen_old_cutoff_observed": [x["unseen_old_denials"] for x in values] == [2, 0, 2, 2] and [x["unseen_old_applications"] for x in values] == [0, 2, 0, 0],
        "all_future_epochs_rejected": all(x["future_rejections"] == 1 for x in values),
        "all_states_and_process_boundaries_verified": all(x["coherent_final_states"] == x["retirement_layouts_match"] == 20 and x["verified_terminations"] == 8 and x["verified_normal_completions"] == 12 and x["infrastructure_errors"] == 0 for x in values),
    }


def summarize(records: list[dict], cases: list[dict]) -> dict:
    grid = [(r["case_id"], r["arm"]) for r in records]
    expected = {(c["case_id"], arm) for c in cases for arm in ARMS}
    if len(grid) != len(expected) or set(grid) != expected:
        raise ValueError("exactly one record per declared case/arm required")
    declared = {c["case_id"]: c for c in cases}
    for row in records:
        if any(row[k] != v for k, v in declared[row["case_id"]].items()):
            raise ValueError("raw case changed its declaration")
        if row["status"] == "complete":
            validate_trace(row)
            if row["oracle"] != assess(row):
                raise ValueError("stored oracle differs from direct observations")
        elif row["status"] != "infrastructure_error" or row.get("oracle") is not None:
            raise ValueError("invalid run status")
    mapping = {"contracts_satisfied": "contract_satisfied", "coherent_final_states": "intrinsic_state_coherent",
               "retirement_layouts_match": "retirement_layout_matches", "known_duplicate_cases": "known_duplicate_case",
               "known_policy_preserved": "known_policy_preserved", "historical_replies": "historical_reply",
               "known_closed_denials": "known_closed_denial", "revoked_values_reinstated": "revoked_value_reinstated",
               "newer_approvals_withdrawn": "newer_approval_withdrawn", "cleanup_gap_captures": "cleanup_gap",
               "completed_retirements": "completed_retirement", "new_current_successes": "new_current_success",
               "current_repeat_successes": "current_repeat_success", "current_conflict_successes": "current_conflict_success",
               "unseen_old_denials": "unseen_old_denied", "unseen_old_applications": "unseen_old_applied", "future_rejections": "future_rejected"}
    arms = {}
    for arm in ARMS:
        rows = [r for r in records if r["arm"] == arm]
        arms[arm] = {"cases": len(rows), "known_late_cases": sum(r["scenario"] == "late_known" for r in rows),
                     "known_closed_cases": sum(r["scenario"] == "late_known" and r["cut"] in {"none", "after_commit", "after_ack"} for r in rows),
                     "new_current_cases": sum(r["scenario"] in {"current_single", "new_epoch_same_id"} for r in rows),
                     "current_repeat_cases": sum(r["scenario"] == "current_repeat" for r in rows),
                     "current_conflict_cases": sum(r["scenario"].startswith("current_conflict_") for r in rows),
                     "unseen_old_cases": sum(r["scenario"] == "unseen_retired" for r in rows),
                     "future_cases": sum(r["scenario"] == "future" for r in rows),
                     "termination_cases": sum(r["cut"] != "none" for r in rows),
                     "verified_terminations": sum(r["status"] == "complete" and r["cut"] != "none" for r in rows),
                     "verified_normal_completions": sum(r["status"] == "complete" and r["cut"] == "none" for r in rows),
                     "infrastructure_errors": sum(r["status"] == "infrastructure_error" for r in rows),
                     "old_receipt_rows_after_commit": sum((r.get("oracle") or {}).get("old_receipt_rows_after_commit", 0) for r in rows),
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
    run_id = started.strftime("%Y-%m-%dT%H-%M-%S-%fZ-retirement-v1")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    raw = args.output_dir / (run_id + ".jsonl")
    metadata = {"started_at_utc": started.isoformat(), "finished_at_utc": datetime.now(timezone.utc).isoformat(),
                "python_version": platform.python_version(), "sqlite_version": sqlite3.sqlite_version, "platform": platform.platform(),
                "base_commit": args.base_commit, "freeze_commit": args.freeze_commit, "command": [sys.executable, *sys.argv],
                "dataset": str(args.dataset), "dataset_sha256": sha(args.dataset.read_bytes()),
                "source_sha256": {p: sha((ROOT / p).read_bytes()) for p in SOURCES},
                "results_file": raw.name, "summary": summary,
                "interpretation_limit": "Twenty developer-visible sequential epoch-retirement schedules per arm; trusted epoch identity; no wall-clock TTL, physical reclamation, concurrent requests, power loss, external effects, or live-task evaluation."}
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
