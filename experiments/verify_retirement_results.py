"""Independent recount of the fixed epoch-retirement experiment artifacts.

Expected effect prefixes are enumerated from the declared matrix. This module
imports neither publication stores, child worker, nor measured runner.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ARMS = ("retain_all", "forget_only", "split_fence", "atomic_fence")
CUTS = ("before_retire", "after_cleanup", "after_commit", "after_ack")
INITIAL, B, C = "approved=version-a\n", "approved=version-b\n", "approved=version-c\n"
VALUES = {"ascii": B, "empty": "", "unicode": "approved=안전 ✓\n"}


def digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def req(epoch, key, value):
    return {"epoch": epoch, "request_id": key, "content_utf8": value}


def result(status, request, revision=None, approved=None):
    return {"status": status, "epoch": request["epoch"], "request_id": request["request_id"],
            "revision": revision, "approved_sha256": approved}


def materialize(prefix: list[dict]) -> tuple[dict, list, list, dict]:
    payload, approved, effects, receipts = INITIAL, digest(INITIAL.encode()), [], []
    for revision, request in enumerate(prefix, 2):
        value = request["content_utf8"]
        if value is not None:
            payload = value
        approved = None if value is None else digest(value.encode())
        effect = {"revision": revision, "epoch": request["epoch"], "request_id": request["request_id"],
                  "operation": "revoke" if value is None else "update", "approved_sha256": approved}
        effects.append(effect)
        receipts.append({**effect, "payload_utf8": value})
    state = {"revision": len(prefix) + 1, "approved_sha256": approved,
             "content_utf8": payload, "content_sha256": digest(payload.encode())}
    delivery = {"status": "blocked" if approved is None else "delivered", "revision": state["revision"],
                "reason": "approval_revoked" if approved is None else "verified_recovery",
                "delivered_utf8": None if approved is None else payload}
    return state, effects, sorted(receipts, key=lambda r: (r["epoch"], r["request_id"])), delivery


def validate_observation(observation: dict) -> bool:
    if (set(observation) != {"state", "active_epoch", "effects", "receipts", "delivery", "sqlite_settings"}
            or observation["sqlite_settings"] != {"journal_mode": "delete", "synchronous": 2, "integrity_check": "ok"}):
        raise ValueError("incomplete observation or wrong SQLite settings")
    state, active, output = observation["state"], observation["active_epoch"], observation["delivery"]
    if type(active) is not int or not 1 <= active < 2**63:
        raise ValueError("invalid epoch observation")
    if (set(state) != {"revision", "approved_sha256", "content_utf8", "content_sha256"}
            or type(state["revision"]) is not int or state["revision"] < 1
            or state["content_sha256"] != digest(state["content_utf8"].encode())):
        raise ValueError("invalid bytes/hash or state revision")
    if (output["status"] not in {"delivered", "blocked"} or output["revision"] != state["revision"]
            or (output["status"] == "delivered" and output["delivered_utf8"] != state["content_utf8"])
            or (output["status"] == "blocked" and output["delivered_utf8"] is not None)):
        raise ValueError("delivery differs from direct capture")
    effects, receipts = observation["effects"], observation["receipts"]
    if (not isinstance(effects, list) or [e["revision"] for e in effects] != list(range(2, state["revision"] + 1))
            or any(set(e) != {"revision", "epoch", "request_id", "operation", "approved_sha256"} or type(e["epoch"]) is not int or e["epoch"] < 1 for e in effects)):
        raise ValueError("effect revisions or schema invalid")
    if effects and effects[-1]["approved_sha256"] != state["approved_sha256"]:
        raise ValueError("current approval differs from last effect")
    if (not isinstance(receipts, list) or any(set(r) != {"epoch", "request_id", "operation", "payload_utf8", "revision", "approved_sha256"} for r in receipts)
            or len({(r["epoch"], r["request_id"]) for r in receipts}) != len(receipts)):
        raise ValueError("invalid receipt schema or duplicate key")
    indexed = {e["revision"]: e for e in effects}
    for receipt in receipts:
        effect = indexed.get(receipt["revision"])
        if effect is None or any(effect[k] != receipt[k] for k in ("epoch", "request_id", "operation", "approved_sha256")):
            raise ValueError("receipt differs from its committed effect")
        if receipt["operation"] == "revoke":
            valid = receipt["payload_utf8"] is None and receipt["approved_sha256"] is None
        else:
            valid = receipt["operation"] == "update" and isinstance(receipt["payload_utf8"], str) and receipt["approved_sha256"] == digest(receipt["payload_utf8"].encode())
        if not valid:
            raise ValueError("receipt bytes differ from its intent")
    return state["approved_sha256"] is None or state["approved_sha256"] == state["content_sha256"]


def trace(row: dict) -> None:
    events = []
    for cut in CUTS:
        if cut == "after_ack":
            events.append({"seq": len(events), "kind": "acknowledged", "response": {"status": "retired", "active_epoch": 2}})
        events.append({"seq": len(events), "kind": "checkpoint", "stage": cut})
        if cut == row["cut"]:
            break
    if row["cut"] == "none":
        events.append({"seq": len(events), "kind": "completed"})
    decoded = [json.loads(line) for line in row["worker_stdout"].splitlines()]
    if (row["worker_returncode"] != (0 if row["cut"] == "none" else 73)
            or row["worker_events"] != events or decoded != events or row["worker_stderr"]):
        raise ValueError("unverified retirement process boundary")


def evaluate(row: dict) -> dict:
    update = row["operation"] == "update"
    seeds = [req(1, "request-1", B if update else None), req(1, "request-2", None if update else C)]
    before = row["before_retirement"]
    seed_state, seed_effects, seed_receipts, seed_output = materialize(seeds)
    active = 1 if row["cut"] in {"before_retire", "after_cleanup"} else 2
    retain_seed = row["arm"] == "retain_all" or (active == 1 and not (row["arm"] == "split_fence" and row["cut"] == "after_cleanup"))
    kept_receipts = seed_receipts if retain_seed else []
    value = VALUES[row["value"]] if update else None
    current = req(2, "current-1", value)
    scenario = row["scenario"]
    # Enumerate input, ideal committed prefix, and allowed response semantics.
    plans = []
    old_reply = result("replayed", seeds[0], 2, digest(B.encode()) if update else None)
    if scenario == "late_known":
        allowed = [old_reply]
        if active == 2:
            allowed.append(result("epoch_retired", seeds[0]))
        plans = [(seeds[0], seeds, allowed)]
    elif scenario == "current_repeat":
        approved = None if value is None else digest(value.encode())
        plans = [(current, seeds + [current], [result("committed", current, 4, approved)]),
                 (current, seeds + [current], [result("replayed", current, 4, approved)])]
    elif scenario in {"current_conflict_value", "current_conflict_operation"}:
        changed = req(2, "current-1", C if scenario == "current_conflict_value" else None)
        plans = [(current, seeds + [current], [result("committed", current, 4, digest(value.encode()))]),
                 (changed, seeds + [current], [result("conflict", changed)])]
    elif scenario in {"current_single", "new_epoch_same_id"}:
        incoming = current if scenario == "current_single" else req(2, "request-1", value)
        plans = [(incoming, seeds + [incoming], [result("committed", incoming, 4, digest(value.encode()))])]
    elif scenario == "unseen_retired":
        incoming = req(1, "unseen-1", value)
        plans = [(incoming, seeds, [result("epoch_retired", incoming)])]
    elif scenario == "future":
        incoming = req(3, "future-1", value)
        plans = [(incoming, seeds, [result("future_epoch", incoming)])]
    else:
        raise ValueError("unknown fixed schedule")
    if len(row["attempts"]) != len(plans):
        raise ValueError("wrong number of attempts")
    observations = [before, row["recovered"], *(a["after"] for a in row["attempts"])]
    coherent = [validate_observation(o) for o in observations]

    def matches(snapshot: dict, prefix: list[dict], epoch: int, retained: list[dict]) -> bool:
        state, effects, receipts, delivery = materialize(prefix)
        expected_receipts = retained + [r for r in receipts if r["epoch"] == 2]
        expected_receipts.sort(key=lambda r: (r["epoch"], r["request_id"]))
        return (snapshot["state"] == state and snapshot["effects"] == effects and snapshot["delivery"] == delivery
                and snapshot["active_epoch"] == epoch and snapshot["receipts"] == expected_receipts)

    if not matches(before, seeds, 1, seed_receipts):
        raise ValueError("declared seed fixture does not match")
    layout = matches(row["recovered"], seeds, active, kept_receipts)
    success = layout
    for attempt, (incoming, prefix, allowed) in zip(row["attempts"], plans):
        if attempt["request"] != incoming:
            raise ValueError("follow-up request differs from fixed matrix")
        success = success and attempt["response"] in allowed and matches(attempt["after"], prefix, active, kept_receipts)
    final, recovered = observations[-1], row["recovered"]
    late = scenario == "late_known"
    preserved = final["state"] == seed_state and final["effects"] == seed_effects and final["delivery"] == seed_output
    extra = max(0, sum(e["epoch"] == 1 and e["request_id"] == "request-1" for e in final["effects"]) - 1)
    unchanged = observations[-1] == observations[-2]
    last_response = row["attempts"][-1]["response"]
    return {"contract_satisfied": bool(success), "intrinsic_state_coherent": coherent[-1], "retirement_layout_matches": bool(layout),
            "known_duplicate_case": late and extra > 0, "known_extra_effects": extra if late else 0,
            "known_policy_preserved": late and preserved,
            "historical_reply": late and preserved and last_response == old_reply,
            "known_closed_denial": late and active == 2 and preserved and last_response == result("epoch_retired", seeds[0]),
            "revoked_value_reinstated": late and update and extra > 0 and final["delivery"]["status"] == "delivered" and final["state"]["content_utf8"] == B,
            "newer_approval_withdrawn": late and not update and extra > 0 and final["delivery"]["reason"] == "approval_revoked",
            "cleanup_gap": recovered["active_epoch"] == 1 and not recovered["receipts"],
            "completed_retirement": recovered["active_epoch"] == 2,
            "old_receipt_rows_after_commit": sum(r["epoch"] < 2 for r in recovered["receipts"]) if recovered["active_epoch"] == 2 else 0,
            "new_current_success": scenario in {"current_single", "new_epoch_same_id"} and bool(success),
            "current_repeat_success": scenario == "current_repeat" and bool(success) and unchanged,
            "current_conflict_success": scenario in {"current_conflict_value", "current_conflict_operation"} and bool(success) and unchanged,
            "unseen_old_denied": scenario == "unseen_retired" and bool(success) and unchanged and last_response == result("epoch_retired", plans[-1][0]),
            "unseen_old_applied": scenario == "unseen_retired" and any(e["epoch"] == 1 and e["request_id"] == "unseen-1" for e in final["effects"]),
            "future_rejected": scenario == "future" and bool(success) and unchanged}


def verify(summary_path: Path, dataset: Path, root: Path = ROOT) -> dict:
    metadata = json.loads(summary_path.read_text(encoding="utf-8"))
    manifest = json.loads(dataset.read_text(encoding="utf-8"))
    if set(manifest) != {"schema_version", "cases"} or manifest["schema_version"] != "retirement-eval-v1":
        raise ValueError("unsupported manifest")
    expected = {("late_known", op, "ascii", cut) for op in ("update", "revoke") for cut in ("none", *CUTS)}
    expected |= {(s, op, "ascii", "none") for s in ("current_repeat", "unseen_retired") for op in ("update", "revoke")}
    expected |= {("current_single", "update", v, "none") for v in ("empty", "unicode")}
    expected |= {(s, "update", v, "none") for s, v in (("current_conflict_value", "ascii"), ("current_conflict_operation", "empty"), ("future", "ascii"), ("new_epoch_same_id", "ascii"))}
    cases = manifest["cases"]
    if (not isinstance(cases, list) or len(cases) != 20
            or any(set(c) != {"case_id", "scenario", "operation", "value", "cut"} or not all(isinstance(v, str) for v in c.values()) or not c["case_id"] for c in cases)):
        raise ValueError("invalid twenty-case input schema")
    ids = [c["case_id"] for c in cases]
    if len(set(ids)) != 20 or {tuple(c[k] for k in ("scenario", "operation", "value", "cut")) for c in cases} != expected:
        raise ValueError("input differs from frozen matrix")
    raw_name = metadata["results_file"]
    if Path(raw_name).name != raw_name:
        raise ValueError("raw result must be a sibling file")
    raw = summary_path.parent / raw_name
    rows = [json.loads(line) for line in raw.read_text(encoding="utf-8").splitlines()]
    grid = [(r["case_id"], r["arm"]) for r in rows]
    if len(grid) != 80 or set(grid) != {(i, arm) for i in ids for arm in ARMS}:
        raise ValueError("missing, repeated, or unknown case/arm")
    counter_keys = ("cases", "known_late_cases", "known_closed_cases", "new_current_cases", "current_repeat_cases", "current_conflict_cases",
                    "unseen_old_cases", "future_cases", "termination_cases", "verified_terminations", "verified_normal_completions",
                    "infrastructure_errors", "old_receipt_rows_after_commit", "contracts_satisfied", "coherent_final_states",
                    "retirement_layouts_match", "known_duplicate_cases", "known_policy_preserved", "historical_replies",
                    "known_closed_denials", "revoked_values_reinstated", "newer_approvals_withdrawn", "cleanup_gap_captures",
                    "completed_retirements", "new_current_successes", "current_repeat_successes", "current_conflict_successes",
                    "unseen_old_denials", "unseen_old_applications", "future_rejections")
    counts = {arm: {key: 0 for key in counter_keys} for arm in ARMS}
    fields = {"contract_satisfied": "contracts_satisfied", "intrinsic_state_coherent": "coherent_final_states",
              "retirement_layout_matches": "retirement_layouts_match", "known_duplicate_case": "known_duplicate_cases",
              "known_policy_preserved": "known_policy_preserved", "historical_reply": "historical_replies",
              "known_closed_denial": "known_closed_denials", "revoked_value_reinstated": "revoked_values_reinstated",
              "newer_approval_withdrawn": "newer_approvals_withdrawn", "cleanup_gap": "cleanup_gap_captures",
              "completed_retirement": "completed_retirements", "new_current_success": "new_current_successes",
              "current_repeat_success": "current_repeat_successes", "current_conflict_success": "current_conflict_successes",
              "unseen_old_denied": "unseen_old_denials", "unseen_old_applied": "unseen_old_applications", "future_rejected": "future_rejections"}
    declared = {c["case_id"]: c for c in cases}
    for row in rows:
        if any(row[k] != v for k, v in declared[row["case_id"]].items()):
            raise ValueError("record differs from declared case")
        n = counts[row["arm"]]
        n["cases"] += 1
        n["known_late_cases"] += row["scenario"] == "late_known"
        n["known_closed_cases"] += row["scenario"] == "late_known" and row["cut"] in {"none", "after_commit", "after_ack"}
        n["new_current_cases"] += row["scenario"] in {"current_single", "new_epoch_same_id"}
        n["current_repeat_cases"] += row["scenario"] == "current_repeat"
        n["current_conflict_cases"] += row["scenario"] in {"current_conflict_value", "current_conflict_operation"}
        n["unseen_old_cases"] += row["scenario"] == "unseen_retired"
        n["future_cases"] += row["scenario"] == "future"
        n["termination_cases"] += row["cut"] != "none"
        if row["status"] == "infrastructure_error":
            if row["oracle"] is not None:
                raise ValueError("infrastructure error has a claimed verdict")
            n["infrastructure_errors"] += 1
            continue
        if row["status"] != "complete":
            raise ValueError("unknown run status")
        trace(row)
        verdict = evaluate(row)
        if verdict != row["oracle"]:
            raise ValueError("oracle differs from independent prefix recount")
        n["verified_terminations"] += row["cut"] != "none"
        n["verified_normal_completions"] += row["cut"] == "none"
        n["old_receipt_rows_after_commit"] += verdict["old_receipt_rows_after_commit"]
        for source, destination in fields.items():
            n[destination] += bool(verdict[source])
    if counts != metadata["summary"]["arms"]:
        raise ValueError("summary counters differ from raw recount")
    ordered = [counts[arm] for arm in ARMS]
    conditions = {
        "known_duplicate_counts": [n["known_duplicate_cases"] for n in ordered] == [0, 6, 2, 0],
        "known_preserved_policy_counts": [n["known_policy_preserved"] for n in ordered] == [10, 4, 8, 10],
        "historical_reply_and_rejection_tradeoff": [n["historical_replies"] for n in ordered] == [10, 4, 2, 4] and [n["known_closed_denials"] for n in ordered] == [0, 0, 6, 6],
        "known_policy_reversal_counts": all([n[k] for n in ordered] == [0, 3, 1, 0] for k in ("revoked_values_reinstated", "newer_approvals_withdrawn")),
        "only_split_has_cleanup_gap": [n["cleanup_gap_captures"] for n in ordered] == [0, 0, 2, 0],
        "committed_retirement_row_counts": all(n["completed_retirements"] == 16 for n in ordered) and [n["old_receipt_rows_after_commit"] for n in ordered] == [32, 0, 0, 0],
        "all_three_new_current_intents_complete": all(n["new_current_successes"] == 3 for n in ordered),
        "all_current_retries_preserve_one_effect": all(n["current_repeat_successes"] == 2 for n in ordered),
        "all_current_conflicts_rejected": all(n["current_conflict_successes"] == 2 for n in ordered),
        "unseen_old_cutoff_observed": [n["unseen_old_denials"] for n in ordered] == [2, 0, 2, 2] and [n["unseen_old_applications"] for n in ordered] == [0, 2, 0, 0],
        "all_future_epochs_rejected": all(n["future_rejections"] == 1 for n in ordered),
        "all_states_and_process_boundaries_verified": all(n["coherent_final_states"] == n["retirement_layouts_match"] == 20 and n["verified_terminations"] == 8 and n["verified_normal_completions"] == 12 and n["infrastructure_errors"] == 0 for n in ordered),
    }
    if conditions != metadata["summary"]["criteria"]:
        raise ValueError("criteria differ from independent recount")
    if digest(dataset.read_bytes()) != metadata["dataset_sha256"]:
        raise ValueError("input hash differs")
    sources = {"src/retirement_store.py", "src/publication_store.py", "src/retry_store.py", "experiments/retirement_worker.py",
               "experiments/run_retirement_comparison.py", "experiments/verify_retirement_results.py", "tests/test_retirement_store.py", "docs/RETIREMENT_PROTOCOL.md"}
    if set(metadata["source_sha256"]) != sources:
        raise ValueError("source inventory differs")
    for path, recorded in metadata["source_sha256"].items():
        if digest((root / path).read_bytes()) != recorded:
            raise ValueError("source version differs: " + path)
    return {"verified_at_utc": datetime.now(timezone.utc).isoformat(), "raw_rows": len(rows),
            "raw_sha256": digest(raw.read_bytes()), "summary_sha256": digest(summary_path.read_bytes()),
            "dataset_hash_matches": True, "source_hashes_checked": len(sources), "case_arm_grid_complete": True,
            "independent_prefix_and_retirement_recount_matches": True, "recounted_arms": counts, "criteria": conditions,
            "infrastructure_errors": sum(n["infrastructure_errors"] for n in ordered)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--summary", type=Path, required=True)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = verify(args.summary, args.dataset)
    encoded = json.dumps(report, indent=2) + "\n"
    if args.output:
        with args.output.open("x", encoding="utf-8") as handle:
            handle.write(encoded)
    print(encoded, end="")
    return int(report["infrastructure_errors"] != 0 or not all(report["criteria"].values()))


if __name__ == "__main__":
    raise SystemExit(main())
