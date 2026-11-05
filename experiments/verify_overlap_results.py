"""Recount Phase 11 observations without importing stores or controller."""
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODES = ("cached_admission", "separate_recheck", "transactional_admission")
STAGES = ("after_admission", "after_final_check", "before_commit", "after_commit")
A, B, C = "approved=version-a\n", "approved=version-b\n", "approved=version-c\n"
VALUES = {"ascii": B, "empty": "", "unicode": "approved=안전 ✓\n"}


def digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def snapshot(case: dict, has_effect: bool, active: int, write_epoch: int | None) -> dict:
    initial_intents = [(1, "request-1", B), (1, "request-2", None)] if case["operation"] == "update" else [(1, "request-1", None), (1, "request-2", C)]
    epoch = 2 if case["schedule"] == "current_epoch" else 1
    incoming = None if case["operation"] == "revoke" else VALUES[case["value"]]
    prefix = initial_intents + ([(epoch, "inflight", incoming)] if has_effect else [])
    payload, approval, effects, receipts = A, digest(A.encode()), [], []
    for revision, (generation, key, value) in enumerate(prefix, 2):
        if value is not None:
            payload = value
        approval = None if value is None else digest(value.encode())
        effect = {"revision": revision, "epoch": generation, "request_id": key,
                  "operation": "revoke" if value is None else "update", "approved_sha256": approval}
        effects.append(effect)
        if generation >= active or (key == "inflight" and write_epoch == active):
            receipts.append({**effect, "payload_utf8": value})
    state = {"revision": len(prefix) + 1, "approved_sha256": approval,
             "content_utf8": payload, "content_sha256": digest(payload.encode())}
    output = {"status": "blocked" if approval is None else "delivered", "reason": "approval_revoked" if approval is None else "verified_recovery",
              "revision": state["revision"], "delivered_utf8": None if approval is None else payload}
    witnesses = [{"revision": 4, "requested_epoch": epoch, "active_epoch": write_epoch, "request_id": "inflight"}] if has_effect else []
    return {"state": state, "active_epoch": active, "effects": effects,
            "receipts": sorted(receipts, key=lambda r: (r["epoch"], r["request_id"])), "commit_witnesses": witnesses,
            "delivery": output, "sqlite_settings": {"journal_mode": "delete", "synchronous": 2, "integrity_check": "ok"}}


def check_retirement(record: dict) -> dict:
    answer = record["response"]
    busy = answer.get("status") == "busy"
    expected = {"target_epoch": 2, "busy_timeout_ms": 0, "sqlite_errorcode": 5 if busy else None,
                "sqlite_errorname": "SQLITE_BUSY" if busy else None, "status": "busy" if busy else "retired",
                "active_epoch": None if busy else 2}
    if answer != expected:
        raise ValueError("invalid retirement result/code")
    events = [{"seq": 0, "kind": "retirement_started", "target_epoch": 2},
              {"seq": 1, "kind": "retirement_result", "response": expected}, {"seq": 2, "kind": "completed"}]
    if (record["returncode"] != 0 or record["stderr"] or record["events"] != events
            or [json.loads(line) for line in record["stdout"].splitlines()] != events):
        raise ValueError("retirement child trace incomplete")
    return answer


def evaluate(row: dict) -> dict:
    attempts = row["retirement_attempts"]
    if not attempts:
        raise ValueError("missing retirement attempt")
    answers = [check_retirement(r) for r in attempts]
    busy = answers[0]["status"] == "busy"
    if len(answers) != 1 + int(busy) or answers[-1]["status"] != "retired":
        raise ValueError("missing or extra retirement retry")
    schedule, mode = row["schedule"], row["mode"]
    paused = schedule in STAGES
    before = schedule in {"retire_first", "current_epoch"}
    phases = ["before_publication" if before else "during_pause" if paused else "after_publication"]
    if busy:
        phases.append("after_publication")
    if [r["phase"] for r in attempts] != phases:
        raise ValueError("retirement attempt order changed")
    epoch = 2 if schedule == "current_epoch" else 1
    admission_epoch = 2 if before else 1
    denied_at_admission = epoch < admission_epoch
    final_epoch = admission_epoch
    if mode == "separate_recheck" and schedule == "after_admission" and not busy:
        final_epoch = 2
    committed = not denied_at_admission and epoch == final_epoch
    value = None if row["operation"] == "revoke" else VALUES[row["value"]]
    answer = {"status": "committed" if committed else "epoch_retired", "epoch": epoch, "request_id": "inflight",
              "revision": 4 if committed else None, "approved_sha256": digest(value.encode()) if committed and value is not None else None}
    write_epoch = (2 if epoch == 2 or (schedule in {"after_admission", "after_final_check"} and not busy) else 1) if committed else None
    # Build the event sequence from separate initial/final scopes and the
    # observable retirement position, independently of the measured controller.
    origin = "transaction" if mode == "transactional_admission" else "read"
    event_data = [("admission", {"origin": origin, "observed_epoch": admission_epoch,
                                 "decision": "epoch_retired" if denied_at_admission else "allowed"})]
    if not denied_at_admission:
        event_data.append(("checkpoint", {"stage": "after_admission"}))
        last_origin = "cached" if mode == "cached_admission" else origin
        event_data.append(("final_decision", {"origin": last_origin, "observed_epoch": final_epoch,
                                              "decision": "allowed" if epoch == final_epoch else "epoch_retired"}))
        event_data.append(("checkpoint", {"stage": "after_final_check"}))
        if committed:
            event_data.extend(("checkpoint", {"stage": s}) for s in ("before_commit", "after_commit"))
    event_data.extend((("publication_result", {"response": answer}), ("completed", {})))
    publisher_events = []
    for kind, fields in event_data:
        publisher_events.append({"seq": len(publisher_events), "kind": kind, **fields})
        if kind == "checkpoint" and fields["stage"] == schedule:
            for marker in ("paused", "resumed"):
                publisher_events.append({"seq": len(publisher_events), "kind": marker, "stage": schedule})
    pub = row["publisher"]
    if (pub["returncode"] != 0 or pub["stderr"] or pub["response"] != answer or pub["events"] != publisher_events
            or [json.loads(line) for line in pub["stdout"].splitlines()] != publisher_events):
        raise ValueError("publisher checks/barrier/result trace inconsistent")
    journal = []
    def note(kind, **fields):
        journal.append({"seq": len(journal), "kind": kind, **fields})
    def retirement(index):
        item = attempts[index-1]
        note("retirement_requested", attempt=index, phase=item["phase"])
        note("retirement_returned", attempt=index, status=item["response"]["status"], sqlite_errorcode=item["response"]["sqlite_errorcode"])
    note("seeded")
    if before:
        retirement(1)
    note("publisher_started")
    if paused:
        note("publisher_paused", stage=schedule)
        retirement(1)
        note("pause_observed")
        note("publisher_resumed", stage=schedule)
    note("publisher_completed", status=answer["status"])
    if not before and not paused:
        retirement(1)
    if busy:
        retirement(2)
    note("final_observed")
    if row["timeline"] != journal:
        raise ValueError("controller journal contradicts declared actor order")
    if row["initial"] != snapshot(row, False, 1, None):
        raise ValueError("wrong seed fixture")
    if row["final"] != snapshot(row, committed, 2, write_epoch):
        raise ValueError("final committed state/epoch/witness inconsistent")
    if paused:
        at_commit = schedule == "after_commit"
        if row["pause_capture"] != snapshot(row, at_commit, 1 if busy else 2, 1 if at_commit else None):
            raise ValueError("pause capture contradicts effect/retirement order")
    elif row["pause_capture"] is not None:
        raise ValueError("undeclared pause capture")
    witnesses = row["final"]["commit_witnesses"]
    invalid = any(w["requested_epoch"] != w["active_epoch"] for w in witnesses)
    state = row["final"]["state"]
    coherent = state["approved_sha256"] is None or state["approved_sha256"] == digest(state["content_utf8"].encode())
    return {"contract_satisfied": not invalid, "invalid_old_effect": epoch == 1 and invalid,
            "invalid_opportunity": invalid and schedule in {"after_admission", "after_final_check"},
            "invalid_after_admission": invalid and schedule == "after_admission",
            "invalid_after_final_check": invalid and schedule == "after_final_check",
            "valid_old_commit": epoch == 1 and committed and not invalid, "old_denial": epoch == 1 and not committed,
            "new_current_success": epoch == 2 and committed and not invalid,
            "retirement_deferred": busy, "retirement_retry_completed": busy and answers[-1]["status"] == "retired",
            "postcommit_historical_reply": schedule == "after_commit" and committed and write_epoch == 1,
            "retired_receipt_recreated": any(r["epoch"] < 2 for r in row["final"]["receipts"]),
            "intrinsic_state_coherent": coherent, "final_epoch_closed": row["final"]["active_epoch"] == 2,
            "barrier_verified": paused, "observations_consistent": True}


def verify(summary_path: Path, dataset: Path, root: Path = ROOT) -> dict:
    metadata = json.loads(summary_path.read_text(encoding="utf-8"))
    manifest = json.loads(dataset.read_text(encoding="utf-8"))
    if set(manifest) != {"schema_version", "cases"} or manifest["schema_version"] != "overlap-eval-v1":
        raise ValueError("unsupported overlap input")
    expected = {(s, o, "ascii") for s in ("retire_first", "publication_first", *STAGES) for o in ("update", "revoke")}
    expected |= {("current_epoch", "update", v) for v in VALUES} | {("current_epoch", "revoke", "ascii")}
    cases = manifest["cases"]
    if (not isinstance(cases, list) or len(cases) != 16 or any(set(c) != {"case_id", "schedule", "operation", "value"}
            or not all(isinstance(v, str) for v in c.values()) or not c["case_id"] for c in cases)):
        raise ValueError("invalid sixteen-case input")
    ids = [c["case_id"] for c in cases]
    if len(set(ids)) != 16 or {(c["schedule"], c["operation"], c["value"]) for c in cases} != expected:
        raise ValueError("input differs from frozen schedules")
    raw_name = metadata["results_file"]
    if Path(raw_name).name != raw_name:
        raise ValueError("raw artifact must be a sibling filename")
    raw = summary_path.parent / raw_name
    rows = [json.loads(line) for line in raw.read_text(encoding="utf-8").splitlines()]
    grid = [(r["case_id"], r["mode"]) for r in rows]
    if len(grid) != 48 or set(grid) != {(i, m) for i in ids for m in MODES}:
        raise ValueError("missing, repeated, or unknown case/mode")
    keys = ("cases", "old_epoch_cases", "opportunity_cases", "pause_cases", "current_controls", "publisher_completions",
            "retirement_attempts", "retirement_completions", "retirement_commits", "busy_attempts", "infrastructure_errors",
            "contracts_satisfied", "invalid_old_effects", "invalid_opportunities", "invalid_after_admission", "invalid_after_final_check",
            "valid_old_commits", "old_denials", "current_successes", "retirement_deferrals", "completed_retries",
            "postcommit_historical_replies", "retired_receipt_recreations", "coherent_final_states", "final_epoch_closed",
            "verified_barriers", "consistent_observations")
    counts = {m: {k: 0 for k in keys} for m in MODES}
    fields = {"contract_satisfied": "contracts_satisfied", "invalid_old_effect": "invalid_old_effects", "invalid_opportunity": "invalid_opportunities",
              "invalid_after_admission": "invalid_after_admission", "invalid_after_final_check": "invalid_after_final_check",
              "valid_old_commit": "valid_old_commits", "old_denial": "old_denials", "new_current_success": "current_successes",
              "retirement_deferred": "retirement_deferrals", "retirement_retry_completed": "completed_retries",
              "postcommit_historical_reply": "postcommit_historical_replies", "retired_receipt_recreated": "retired_receipt_recreations",
              "intrinsic_state_coherent": "coherent_final_states", "final_epoch_closed": "final_epoch_closed",
              "barrier_verified": "verified_barriers", "observations_consistent": "consistent_observations"}
    declared = {c["case_id"]: c for c in cases}
    for row in rows:
        if any(row[k] != v for k, v in declared[row["case_id"]].items()):
            raise ValueError("raw row changed a declared case")
        n = counts[row["mode"]]
        n["cases"] += 1
        n["old_epoch_cases"] += row["schedule"] != "current_epoch"
        n["opportunity_cases"] += row["schedule"] in {"after_admission", "after_final_check"}
        n["pause_cases"] += row["schedule"] in STAGES
        n["current_controls"] += row["schedule"] == "current_epoch"
        if row["status"] == "infrastructure_error":
            if row["oracle"] is not None:
                raise ValueError("infrastructure error claims a security verdict")
            n["infrastructure_errors"] += 1
            continue
        if row["status"] != "complete":
            raise ValueError("unknown record status")
        verdict = evaluate(row)
        if verdict != row["oracle"]:
            raise ValueError("stored oracle differs from independent witness recount")
        n["publisher_completions"] += 1
        n["retirement_attempts"] += len(row["retirement_attempts"])
        n["retirement_completions"] += len(row["retirement_attempts"])
        n["retirement_commits"] += sum(a["response"]["status"] == "retired" for a in row["retirement_attempts"])
        n["busy_attempts"] += sum(a["response"]["status"] == "busy" for a in row["retirement_attempts"])
        for source, destination in fields.items():
            n[destination] += bool(verdict[source])
    if counts != metadata["summary"]["arms"]:
        raise ValueError("summary differs from raw witness counters")
    ordered = [counts[m] for m in MODES]
    conditions = {
        "invalid_epoch_effect_counts": all([n[k] for n in ordered] == [4, 2, 0] for k in ("invalid_old_effects", "invalid_opportunities")),
        "admission_and_final_decision_gaps": [n["invalid_after_admission"] for n in ordered] == [2, 0, 0] and [n["invalid_after_final_check"] for n in ordered] == [2, 2, 0],
        "writer_deferrals_and_completed_retries": all([n[k] for n in ordered] == [2, 2, 6] for k in ("retirement_deferrals", "completed_retries", "busy_attempts")),
        "valid_old_commits_and_denials": [n["valid_old_commits"] for n in ordered] == [6, 6, 10] and [n["old_denials"] for n in ordered] == [2, 4, 2],
        "all_current_epoch_controls_complete": all(n["current_successes"] == 4 for n in ordered),
        "postcommit_replies_are_historical": all(n["postcommit_historical_replies"] == 2 for n in ordered),
        "retired_receipt_recreation_counts": [n["retired_receipt_recreations"] for n in ordered] == [4, 2, 0],
        "all_scheduled_retirements_commit": all(n["retirement_commits"] == n["final_epoch_closed"] == 16 for n in ordered) and [n["retirement_attempts"] for n in ordered] == [18, 18, 22],
        "all_states_and_witnesses_consistent": all(n["coherent_final_states"] == n["consistent_observations"] == 16 for n in ordered),
        "all_process_and_barrier_coverage_verified": all(n["verified_barriers"] == 8 and n["publisher_completions"] == 16 and n["retirement_completions"] == n["retirement_attempts"] and n["infrastructure_errors"] == 0 for n in ordered),
    }
    if conditions != metadata["summary"]["criteria"]:
        raise ValueError("criteria differ from independent recount")
    if digest(dataset.read_bytes()) != metadata["dataset_sha256"]:
        raise ValueError("input hash differs")
    sources = {"src/overlap_store.py", "src/retirement_store.py", "src/publication_store.py", "src/retry_store.py",
               "experiments/overlap_worker.py", "experiments/run_overlap_comparison.py", "experiments/verify_overlap_results.py",
               "tests/test_overlap_store.py", "docs/OVERLAP_PROTOCOL.md"}
    if set(metadata["source_sha256"]) != sources:
        raise ValueError("source inventory differs")
    for path, recorded in metadata["source_sha256"].items():
        if digest((root / path).read_bytes()) != recorded:
            raise ValueError("source version differs: " + path)
    return {"verified_at_utc": datetime.now(timezone.utc).isoformat(), "raw_rows": len(rows),
            "raw_sha256": digest(raw.read_bytes()), "summary_sha256": digest(summary_path.read_bytes()),
            "dataset_hash_matches": True, "source_hashes_checked": len(sources), "case_mode_grid_complete": True,
            "independent_actor_and_witness_recount_matches": True, "recounted_arms": counts, "criteria": conditions,
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
