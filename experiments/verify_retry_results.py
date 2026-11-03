"""Recount the frozen Phase 9 grid independently of publisher and runner.

The expected audit prefixes below are specific to this declared matrix. This
checks recorded observations and provenance, not arbitrary storage correctness.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ARMS = ("unkeyed", "split_receipt", "atomic_receipt")
VALUES = {"ascii": "approved=version-b\n", "empty": "", "unicode": "approved=안전 ✓\n"}
INITIAL = "approved=version-a\n"
LATER = "approved=version-c\n"
CUTS = ("before_commit", "after_state_commit", "after_record_commit", "after_ack")


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def content(case: dict) -> str | None:
    return None if case["operation"] == "revoke" else VALUES[case["value"]]


def state_for(intents: list[tuple]) -> tuple[dict, list[dict], dict]:
    payload, approval = INITIAL, digest(INITIAL.encode())
    effects = []
    for index, (key, value) in enumerate(intents, 2):
        if value is not None:
            payload = value
        approval = None if value is None else digest(value.encode())
        effects.append({"revision": index, "request_id": key, "operation": "revoke" if value is None else "update",
                        "approved_sha256": approval})
    state = {"revision": len(intents) + 1, "approved_sha256": approval,
             "content_utf8": payload, "content_sha256": digest(payload.encode())}
    output = {"status": "blocked" if approval is None else "delivered", "revision": state["revision"],
              "reason": "approval_revoked" if approval is None else "verified_recovery",
              "delivered_utf8": None if approval is None else payload}
    return state, effects, output


def validate_observation(observation: dict) -> bool:
    if set(observation) != {"state", "effects", "receipts", "delivery", "sqlite_settings"}:
        raise ValueError("incomplete captured observation")
    if observation["sqlite_settings"] != {"journal_mode": "delete", "synchronous": 2, "integrity_check": "ok"}:
        raise ValueError("wrong SQLite settings or integrity")
    state, output = observation["state"], observation["delivery"]
    if (set(state) != {"revision", "approved_sha256", "content_utf8", "content_sha256"}
            or type(state["revision"]) is not int or state["revision"] < 1
            or state["content_sha256"] != digest(state["content_utf8"].encode())):
        raise ValueError("state bytes/hash or revision invalid")
    if (output["status"] not in {"delivered", "blocked"} or output["revision"] != state["revision"]
            or (output["status"] == "delivered" and output["delivered_utf8"] != state["content_utf8"])
            or (output["status"] == "blocked" and output["delivered_utf8"] is not None)):
        raise ValueError("delivery differs from capture")
    effects, receipts = observation["effects"], observation["receipts"]
    if (not isinstance(effects, list) or [e["revision"] for e in effects] != list(range(2, state["revision"] + 1))
            or any(set(e) != {"revision", "request_id", "operation", "approved_sha256"} for e in effects)):
        raise ValueError("effect sequence inconsistent")
    if (not isinstance(receipts, list) or any(set(r) != {"request_id", "operation", "payload_utf8", "revision", "approved_sha256"} for r in receipts)
            or len({r["request_id"] for r in receipts}) != len(receipts)):
        raise ValueError("receipt observation invalid")
    return state["approved_sha256"] is None or state["approved_sha256"] == state["content_sha256"]


def trace(row: dict) -> None:
    events = []
    for cut in CUTS:
        if cut == "after_ack":
            value = content(row)
            events.append({"seq": len(events), "kind": "acknowledged", "response": {
                "status": "committed", "request_id": "request-1", "revision": 2,
                "approved_sha256": None if value is None else digest(value.encode())}})
        events.append({"seq": len(events), "kind": "checkpoint", "stage": cut})
        if cut == row["cut"]:
            break
    if row["cut"] == "none":
        events.append({"seq": len(events), "kind": "completed"})
    decoded = [json.loads(line) for line in row["worker_stdout"].splitlines()]
    if (row["worker_returncode"] != (0 if row["cut"] == "none" else 73)
            or row["worker_events"] != events or decoded != events or row["worker_stderr"]):
        raise ValueError("declared process boundary not verified")


def evaluate(row: dict) -> dict:
    """Enumerate expected effect prefixes for the fixed schedules, not statuses."""
    value, scenario = content(row), row["scenario"]
    initial = [] if row["cut"] == "before_commit" else [("request-1", value)]
    # Each tuple: follow-up input, expected committed intent prefix, reply revision.
    plans = []
    if scenario in {"repeat", "crash"}:
        plans = [("request-1", value, [("request-1", value)], 2, False)]
    elif scenario in {"conflict_value", "conflict_operation"}:
        changed = LATER if scenario == "conflict_value" else None
        plans = [("request-1", changed, initial, None, True)]
    elif scenario == "distinct":
        plans = [("request-2", value, initial + [("request-2", value)], 3, False)]
    elif scenario == "intervening":
        next_value = None if value is not None else LATER
        later = initial + [("request-2", next_value)]
        plans = [("request-2", next_value, later, 3, False), ("request-1", value, later, 2, False)]
    elif scenario != "single":
        raise ValueError("unknown schedule")
    if len(row["attempts"]) != len(plans):
        raise ValueError("wrong number of follow-up attempts")
    observations = [row["initial_recovery"], *(attempt["after"] for attempt in row["attempts"])]
    coherences = [validate_observation(o) for o in observations]

    def matches(observation: dict, intents: list[tuple]) -> bool:
        state, effects, output = state_for(intents)
        return observation["state"] == state and observation["effects"] == effects and observation["delivery"] == output

    initial_matches = matches(observations[0], initial)
    success = initial_matches
    for attempt, (key, requested, intents, revision, conflict) in zip(row["attempts"], plans):
        if attempt["request"] != {"request_id": key, "content_utf8": requested}:
            raise ValueError("follow-up differs from declared intent")
        response = attempt["response"]
        if (set(response) != {"status", "request_id", "revision", "approved_sha256"}
                or response["status"] not in {"committed", "replayed", "conflict"}):
            raise ValueError("invalid semantic receipt")
        wanted_digest = None if conflict or requested is None else digest(requested.encode())
        equivalent = (response["request_id"] == key and response["revision"] == revision
                      and response["approved_sha256"] == wanted_digest
                      and (response["status"] == "conflict") == conflict)
        success = success and equivalent and matches(attempt["after"], intents)
    final = observations[-1]
    same_retry = scenario in {"repeat", "crash", "intervening"}
    extra = max(0, len([e for e in final["effects"] if e["request_id"] == "request-1"]) - 1)
    gap, late = row["cut"] == "after_state_commit", scenario == "intervening"
    unchanged = len(observations) > 1 and observations[-1] == observations[-2]
    return {"intrinsic_state_coherent": coherences[-1], "initial_state_matches_schedule": initial_matches,
            "contract_satisfied": bool(success), "same_intent_retry_case": same_retry,
            "retry_contract_satisfied": same_retry and bool(success), "extra_request1_effects": extra,
            "retry_duplicate_case": same_retry and extra > 0, "gap_duplicate_case": gap and extra > 0,
            "first_receipt_missing_at_gap": gap and not any(r["request_id"] == "request-1" for r in observations[0]["receipts"]),
            "conflict_case_success": scenario in {"conflict_value", "conflict_operation"} and bool(success) and unchanged,
            "distinct_case_success": scenario == "distinct" and bool(success),
            "late_retry_preserved": late and bool(success) and unchanged,
            "revoked_value_reinstated": late and row["operation"] == "update" and observations[-2]["delivery"]["reason"] == "approval_revoked" and final["delivery"]["status"] == "delivered",
            "newer_approval_withdrawn": late and row["operation"] == "revoke" and observations[-2]["delivery"]["status"] == "delivered" and final["delivery"]["reason"] == "approval_revoked",
            "single_control_success": scenario == "single" and bool(success)}


def verify(summary_path: Path, dataset: Path, root: Path = ROOT) -> dict:
    metadata = json.loads(summary_path.read_text(encoding="utf-8"))
    manifest = json.loads(dataset.read_text(encoding="utf-8"))
    if set(manifest) != {"schema_version", "cases"} or manifest["schema_version"] != "retry-eval-v1":
        raise ValueError("unsupported manifest")
    expected = {("single", "update", v, "none") for v in VALUES} | {("single", "revoke", "ascii", "none")}
    expected |= {(s, o, "ascii", "none") for s in ("repeat", "distinct", "intervening") for o in ("update", "revoke")}
    expected |= {(s, "update", "ascii", "none") for s in ("conflict_value", "conflict_operation")}
    expected |= {("crash", o, "ascii", c) for o in ("update", "revoke") for c in CUTS}
    cases = manifest["cases"]
    if any(set(c) != {"case_id", "scenario", "operation", "value", "cut"} for c in cases):
        raise ValueError("invalid case schema")
    ids = [c["case_id"] for c in cases]
    if (len(ids) != 20 or len(set(ids)) != 20
            or {tuple(c[k] for k in ("scenario", "operation", "value", "cut")) for c in cases} != expected):
        raise ValueError("manifest differs from fixed twenty-case matrix")
    raw_name = metadata["results_file"]
    if Path(raw_name).name != raw_name:
        raise ValueError("raw artifact must be a sibling filename")
    raw = summary_path.parent / raw_name
    rows = [json.loads(line) for line in raw.read_text(encoding="utf-8").splitlines()]
    pairs = [(r["case_id"], r["arm"]) for r in rows]
    if len(pairs) != 60 or set(pairs) != {(i, a) for i in ids for a in ARMS}:
        raise ValueError("missing, repeated, or unknown case/arm")
    keys = ("cases", "retry_cases", "gap_cases", "conflict_cases", "distinct_cases", "late_retry_cases", "single_controls",
            "termination_cases", "verified_terminations", "verified_normal_completions", "infrastructure_errors",
            "coherent_final_states", "initial_states_match", "contracts_satisfied", "successful_retries", "retry_duplicate_cases",
            "gap_duplicate_cases", "first_receipt_gaps", "correct_conflicts", "distinct_completions", "late_states_preserved",
            "revoked_values_reinstated", "newer_approvals_withdrawn", "single_control_successes")
    counts = {a: {k: 0 for k in keys} for a in ARMS}
    fields = {"intrinsic_state_coherent": "coherent_final_states", "initial_state_matches_schedule": "initial_states_match",
              "contract_satisfied": "contracts_satisfied", "retry_contract_satisfied": "successful_retries",
              "retry_duplicate_case": "retry_duplicate_cases", "gap_duplicate_case": "gap_duplicate_cases",
              "first_receipt_missing_at_gap": "first_receipt_gaps", "conflict_case_success": "correct_conflicts",
              "distinct_case_success": "distinct_completions", "late_retry_preserved": "late_states_preserved",
              "revoked_value_reinstated": "revoked_values_reinstated", "newer_approval_withdrawn": "newer_approvals_withdrawn",
              "single_control_success": "single_control_successes"}
    by_id = {c["case_id"]: c for c in cases}
    for row in rows:
        if any(row[k] != v for k, v in by_id[row["case_id"]].items()):
            raise ValueError("raw record changed a frozen case")
        count = counts[row["arm"]]
        count["cases"] += 1
        count["retry_cases"] += row["scenario"] in {"repeat", "crash", "intervening"}
        count["gap_cases"] += row["cut"] == "after_state_commit"
        count["conflict_cases"] += row["scenario"] in {"conflict_value", "conflict_operation"}
        count["distinct_cases"] += row["scenario"] == "distinct"
        count["late_retry_cases"] += row["scenario"] == "intervening"
        count["single_controls"] += row["scenario"] == "single"
        count["termination_cases"] += row["cut"] != "none"
        if row["status"] == "infrastructure_error":
            count["infrastructure_errors"] += 1
            continue
        if row["status"] != "complete":
            raise ValueError("unknown record status")
        trace(row)
        verdict = evaluate(row)
        if verdict != row["oracle"]:
            raise ValueError("oracle differs from independent effect-prefix model")
        count["verified_terminations"] += row["cut"] != "none"
        count["verified_normal_completions"] += row["cut"] == "none"
        for source, destination in fields.items():
            count[destination] += bool(verdict[source])
    if counts != metadata["summary"]["arms"]:
        raise ValueError("summary differs from independent counts")
    a, b, c = (counts[name] for name in ARMS)
    conditions = {
        "unkeyed_ten_duplicate_retry_cases": a["retry_duplicate_cases"] == 10 and a["successful_retries"] == 2,
        "split_two_gap_duplicates": b["retry_duplicate_cases"] == b["gap_duplicate_cases"] == b["first_receipt_gaps"] == 2 and b["successful_retries"] == 10,
        "atomic_twelve_successful_retries_no_duplicates": c["successful_retries"] == 12 and c["retry_duplicate_cases"] == c["first_receipt_gaps"] == 0,
        "keyed_reject_changed_intent": all(x["correct_conflicts"] == 2 for x in (b, c)),
        "all_accept_distinct_ids_identical_intent": all(x["distinct_completions"] == 2 for x in counts.values()),
        "keyed_preserve_later_state": all(x["late_states_preserved"] == 2 and x["revoked_values_reinstated"] == x["newer_approvals_withdrawn"] == 0 for x in (b, c)),
        "unkeyed_reauthorization_and_withdrawal": a["revoked_values_reinstated"] == a["newer_approvals_withdrawn"] == 1,
        "all_four_single_controls_succeed": all(x["single_control_successes"] == 4 for x in counts.values()),
        "all_twenty_final_states_coherent": all(x["coherent_final_states"] == 20 for x in counts.values()),
        "all_declared_process_boundaries_verified": all(x["verified_terminations"] == 8 and x["verified_normal_completions"] == 12 and x["infrastructure_errors"] == 0 for x in counts.values()),
    }
    if conditions != metadata["summary"]["criteria"]:
        raise ValueError("criteria differ from independent recount")
    if digest(dataset.read_bytes()) != metadata["dataset_sha256"]:
        raise ValueError("input hash differs")
    sources = {"src/retry_store.py", "src/publication_store.py", "experiments/retry_worker.py",
               "experiments/run_retry_comparison.py", "experiments/verify_retry_results.py",
               "tests/test_retry_store.py", "docs/RETRY_PROTOCOL.md"}
    if set(metadata["source_sha256"]) != sources:
        raise ValueError("source inventory differs")
    for path, recorded in metadata["source_sha256"].items():
        if digest((root / path).read_bytes()) != recorded:
            raise ValueError("source version differs: " + path)
    return {"verified_at_utc": datetime.now(timezone.utc).isoformat(), "raw_rows": len(rows),
            "raw_sha256": digest(raw.read_bytes()), "summary_sha256": digest(summary_path.read_bytes()),
            "dataset_hash_matches": True, "source_hashes_checked": len(sources),
            "case_arm_grid_complete": True, "independent_effect_prefix_recount_matches": True,
            "recounted_arms": counts, "criteria": conditions,
            "infrastructure_errors": sum(x["infrastructure_errors"] for x in counts.values())}


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
