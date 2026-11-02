"""Independently recount Phase 8 raw observations, traces, and provenance.

This verifier does not import the store, worker, or experiment runner. It checks
artifact consistency; it is not an independent evaluation of SQLite or the OS.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ARMS = ("split_unchecked", "split_verified", "sqlite_atomic")
INITIAL = {"ascii": "approved=version-a\n", "empty": "", "unicode": "approved=안전 ✓\n"}


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def expected(case: dict) -> dict:
    committed = case["transition"] in {"update", "revoke"} and case["cut"] in {"after_commit", "after_ack"}
    payload = "approved=version-b\n" if committed and case["transition"] == "update" else INITIAL[case["fixture"]]
    return {"revision": 2 if committed else 1,
            "approved_sha256": None if committed and case["transition"] == "revoke" else digest(payload.encode("utf-8")),
            "content_utf8": payload, "content_sha256": digest(payload.encode("utf-8"))}


def evaluate(row: dict) -> dict:
    wanted = expected(row)
    state, recovered = row["observed_state"], row["recovery"]
    if not isinstance(state, dict) or set(state) != set(wanted) or type(state["revision"]) is not int:
        raise ValueError("invalid state observation")
    if state["content_sha256"] != digest(state["content_utf8"].encode("utf-8")):
        raise ValueError("recovered content hash differs from bytes")
    delivered = recovered["status"] == "delivered"
    blocked = recovered["status"] == "blocked"
    payload = recovered["delivered_utf8"]
    if not (delivered or blocked) or (delivered and not isinstance(payload, str)) or (blocked and payload is not None):
        raise ValueError("delivery status differs from payload presence")
    if recovered["revision"] != state["revision"] or (delivered and payload != state["content_utf8"]):
        raise ValueError("delivery differs from the captured state")
    active = wanted["approved_sha256"] is not None
    valid = bool(delivered and active and recovered["revision"] == wanted["revision"] and payload == wanted["content_utf8"])
    coherent = state == wanted
    return {"state_coherent": coherent, "active_approval_case": active,
            "valid_delivery": valid, "invalid_delivery": delivered and not valid,
            "revocation_denied": not active and blocked and recovered["reason"] == "approval_revoked",
            "acknowledged_recovered": row["cut"] == "after_ack" and coherent,
            "committed_without_ack_recovered": row["cut"] == "after_commit" and coherent}


def verify_trace(row: dict) -> None:
    if row["transition"] == "none":
        sequence = [{"seq": 0, "kind": "control"}, {"seq": 1, "kind": "completed"}]
        code = 0
    else:
        sequence = []
        for stage in ("before_publish", "after_stage", "after_commit", "after_ack"):
            if stage == "after_ack":
                sequence.append({"seq": len(sequence), "kind": "acknowledged", "revision": 2,
                                 "approved_sha256": None if row["transition"] == "revoke" else digest(b"approved=version-b\n")})
            sequence.append({"seq": len(sequence), "kind": "checkpoint", "stage": stage})
            if stage == row["cut"]:
                break
        code = 73
    decoded = [json.loads(line) for line in row["worker_stdout"].splitlines()]
    if row["worker_returncode"] != code or row["worker_events"] != sequence or decoded != sequence or row["worker_stderr"]:
        raise ValueError("termination trace did not reach the declared boundary")


def verify(summary_path: Path, dataset: Path, root: Path = ROOT) -> dict:
    metadata = json.loads(summary_path.read_text(encoding="utf-8"))
    manifest = json.loads(dataset.read_text(encoding="utf-8"))
    if manifest["schema_version"] != "recovery-eval-v1":
        raise ValueError("unsupported input version")
    cases = manifest["cases"]
    # This version is a fixed 19-case matrix, not an arbitrary larger sample.
    expected_schedules = {(fixture, "none", "none") for fixture in INITIAL}
    expected_schedules.update((f, t, c) for f in ("ascii", "empty") for t in ("update", "revoke")
                              for c in ("before_publish", "after_stage", "after_commit", "after_ack"))
    schedules = [(c["fixture"], c["transition"], c["cut"]) for c in cases]
    ids = [c["case_id"] for c in cases]
    if len(ids) != 19 or len(set(ids)) != 19 or len(set(schedules)) != 19 or set(schedules) != expected_schedules:
        raise ValueError("input is not the frozen nineteen-case matrix")
    raw_name = metadata["results_file"]
    if Path(raw_name).name != raw_name:
        raise ValueError("raw result must be a sibling filename")
    raw = summary_path.parent / raw_name
    rows = [json.loads(line) for line in raw.read_text(encoding="utf-8").splitlines()]
    grid = [(r["case_id"], r["arm"]) for r in rows]
    if len(grid) != 57 or set(grid) != {(case_id, arm) for case_id in ids for arm in ARMS}:
        raise ValueError("missing, duplicate, or unknown case/arm")
    declared = {c["case_id"]: c for c in cases}
    counters = {arm: {k: 0 for k in (
        "cases", "termination_cases", "verified_terminations", "coherent_states", "active_approval_cases",
        "valid_deliveries", "invalid_deliveries", "update_gap_cases", "invalid_gap_deliveries", "denials",
        "mismatch_denials", "committed_revocations", "revocation_denials", "acknowledged_cases", "acknowledged_recovered",
        "committed_without_ack_cases", "committed_without_ack_recovered", "controls", "valid_control_deliveries", "infrastructure_errors")}
        for arm in ARMS}
    for row in rows:
        if any(row[k] != v for k, v in declared[row["case_id"]].items()):
            raise ValueError("record changed a declared case")
        count = counters[row["arm"]]
        count["cases"] += 1
        count["termination_cases"] += row["cut"] != "none"
        count["active_approval_cases"] += expected(row)["approved_sha256"] is not None
        count["committed_revocations"] += expected(row)["approved_sha256"] is None
        gap = row["transition"] == "update" and row["cut"] == "after_stage"
        count["update_gap_cases"] += gap
        count["acknowledged_cases"] += row["cut"] == "after_ack"
        count["committed_without_ack_cases"] += row["cut"] == "after_commit"
        count["controls"] += row["transition"] == "none"
        if row["status"] == "infrastructure_error":
            count["infrastructure_errors"] += 1
            continue
        if row["status"] != "complete":
            raise ValueError("unknown record status")
        verify_trace(row)
        count["verified_terminations"] += row["cut"] != "none"
        verdict = evaluate(row)
        if verdict != row["oracle"]:
            raise ValueError("recorded oracle differs from independent recount")
        for source, destination in (("state_coherent", "coherent_states"), ("valid_delivery", "valid_deliveries"),
                                    ("invalid_delivery", "invalid_deliveries"), ("revocation_denied", "revocation_denials"),
                                    ("acknowledged_recovered", "acknowledged_recovered"),
                                    ("committed_without_ack_recovered", "committed_without_ack_recovered")):
            count[destination] += verdict[source]
        count["invalid_gap_deliveries"] += gap and verdict["invalid_delivery"]
        count["denials"] += row["recovery"]["status"] == "blocked"
        count["mismatch_denials"] += row["recovery"]["reason"] == "recovered_digest_mismatch"
        count["valid_control_deliveries"] += row["transition"] == "none" and verdict["valid_delivery"]
        if row["arm"] == "sqlite_atomic" and row["sqlite_settings"] != {"journal_mode": "delete", "synchronous": 2, "integrity_check": "ok"}:
            raise ValueError("SQLite settings differ from the protocol")
    if counters != metadata["summary"]["arms"]:
        raise ValueError("summary counters differ from raw observations")
    if digest(dataset.read_bytes()) != metadata["dataset_sha256"]:
        raise ValueError("dataset hash mismatch")
    source_paths = {"src/publication_store.py", "experiments/recovery_worker.py", "experiments/run_recovery_comparison.py",
                    "experiments/verify_recovery_results.py", "tests/test_publication_store.py", "docs/RECOVERY_PROTOCOL.md"}
    if set(metadata["source_sha256"]) != source_paths:
        raise ValueError("unexpected source inventory")
    for name, expected_hash in metadata["source_sha256"].items():
        if digest((root / name).read_bytes()) != expected_hash:
            raise ValueError("source version differs from recorded run: " + name)
    a, b, c = (counters[arm] for arm in ARMS)
    hypotheses = {
        "unchecked_two_invalid_gap_deliveries": a["invalid_gap_deliveries"] == a["invalid_deliveries"] == 2,
        "verified_zero_invalid_and_two_mismatch_denials": b["invalid_deliveries"] == 0 and b["mismatch_denials"] == 2,
        "atomic_zero_invalid_and_fifteen_valid_deliveries": c["invalid_deliveries"] == 0 and c["valid_deliveries"] == 15,
        "split_seventeen_coherent_states": a["coherent_states"] == b["coherent_states"] == 17,
        "atomic_nineteen_coherent_states": c["coherent_states"] == 19,
        "split_thirteen_valid_deliveries": a["valid_deliveries"] == b["valid_deliveries"] == 13,
        "all_committed_revocations_denied": all(x["committed_revocations"] == x["revocation_denials"] == 4 for x in counters.values()),
        "all_acknowledged_publications_recovered": all(x["acknowledged_cases"] == x["acknowledged_recovered"] == 4 for x in counters.values()),
        "unacknowledged_commits_also_recovered": all(x["committed_without_ack_cases"] == x["committed_without_ack_recovered"] == 4 for x in counters.values()),
        "all_three_controls_delivered": all(x["controls"] == x["valid_control_deliveries"] == 3 for x in counters.values()),
        "all_declared_cuts_reached_without_infrastructure_error": all(x["termination_cases"] == x["verified_terminations"] == 16 and x["infrastructure_errors"] == 0 for x in counters.values()),
    }
    if hypotheses != metadata["summary"]["criteria"]:
        raise ValueError("declared criteria differ from recount")
    return {"verified_at_utc": datetime.now(timezone.utc).isoformat(), "raw_rows": len(rows),
            "raw_sha256": digest(raw.read_bytes()), "summary_sha256": digest(summary_path.read_bytes()),
            "dataset_hash_matches": True, "source_hashes_checked": len(source_paths),
            "case_arm_grid_complete": True, "trace_and_counter_recount_matches": True,
            "recounted_arms": counters, "criteria": hypotheses,
            "infrastructure_errors": sum(x["infrastructure_errors"] for x in counters.values())}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--summary", type=Path, required=True)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = verify(args.summary, args.dataset)
    encoded = json.dumps(result, indent=2) + "\n"
    if args.output:
        with args.output.open("x", encoding="utf-8") as handle:
            handle.write(encoded)
    print(encoded, end="")
    return int(result["infrastructure_errors"] != 0 or not all(result["criteria"].values()))


if __name__ == "__main__":
    raise SystemExit(main())
