"""Reconstruct Phase 13 evidence independently with the Python standard library."""
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODES = ("retry_missing", "fenced_resolution", "guarded_resolution")
VALUES = {"b": "approved=version-b\n", "c": "approved=version-c\n", "empty": "", "revoke": None,
          "unicode": "approved=안전 ✓\n", "nfc": "approved=é\n", "nfd": "approved=e\u0301\n", "later": "approved=version-d\n"}
PATTERNS = {"same_ascii": ("b", "b"), "same_empty": ("empty", "empty"), "same_unicode": ("unicode", "unicode"),
            "same_revoke": ("revoke", "revoke"), "changed_bytes": ("b", "c"), "update_to_revoke": ("empty", "revoke"),
            "revoke_to_update": ("revoke", "empty"), "changed_unicode_bytes": ("nfc", "nfd")}
SOURCES = (
    "src/resolution_store.py", "experiments/resolution_worker.py", "experiments/run_resolution_comparison.py",
    "experiments/verify_resolution_results.py", "tests/test_resolution_store.py", "docs/RESOLUTION_PROTOCOL.md",
    "src/publication_store.py", "src/retry_store.py", "src/retirement_store.py", "src/overlap_store.py",
    "experiments/run_overlap_comparison.py",
)
FIELDS = (
    "extra_gap_effect", "one_shared_effect", "new_effects", "safe_gap_resolution", "unavailable_gap",
    "original_gap_resolution", "identical_gap_replay", "changed_gap_conflict", "later_state_preserved",
    "control_original_resolution", "receipt_pk_aborts", "rollback_verified", "busy_retirements",
    "completed_retirement_retry", "final_epoch_3", "final_epoch_2", "coherent_final", "invalid_old_commit",
    "recreated_old_receipt", "retired_old_receipts_absent", "consistent_observations", "verified_barriers", "child_completions",
)


def digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def load_manifest(path: Path) -> list[dict]:
    data = json.loads(path.read_text())
    if not isinstance(data, dict) or set(data) != {"schema_version", "cases"} or data["schema_version"] != "resolution-eval-v1":
        raise ValueError("unsupported manifest")
    allowed = {("retire_gap", p) for p in PATTERNS}
    allowed.update(("retire_gap_later", p) for p in ("same_ascii", "same_revoke", "changed_bytes", "update_to_revoke"))
    allowed.update(("resolution_first", p) for p in ("same_ascii", "changed_bytes"))
    allowed.update(("retained", p) for p in ("same_empty", "changed_unicode_bytes"))
    cases = data["cases"]
    if (not isinstance(cases, list) or len(cases) != 16
            or any(not isinstance(c, dict) or set(c) != {"case_id", "schedule", "pattern"}
                   or not all(isinstance(v, str) and v for v in c.values()) for c in cases)
            or len({c["case_id"] for c in cases}) != 16
            or {(c["schedule"], c["pattern"]) for c in cases} != allowed):
        raise ValueError("manifest lost or repeated a semantic history")
    return cases


def request(row, caller):
    alias = "later" if caller == "later" else PATTERNS[row["pattern"]][0 if caller == "first" else 1]
    return {"caller": caller, "epoch": 3 if caller == "later" else 2,
            "request_id": "later" if caller == "later" else "shared-request",
            "intent": alias, "content_utf8": VALUES[alias]}


def response(status, req, revision=None, approval=None):
    return {"status": status, "epoch": req["epoch"], "request_id": req["request_id"],
            "revision": revision, "approved_sha256": approval}


def audit_snapshot(row, observed):
    active = observed["active_epoch"]
    if active not in (2, 3):
        raise ValueError("invalid namespace epoch")
    payload, approval = VALUES["b"], None
    history = [
        {"revision": 2, "epoch": 1, "request_id": "seed-a", "operation": "update", "approved_sha256": digest(payload)},
        {"revision": 3, "epoch": 1, "request_id": "seed-b", "operation": "revoke", "approved_sha256": None},
    ]
    retained = {}
    last_epoch = 2
    actors = observed["commits"]
    for index, actor in enumerate(actors):
        if actor["caller"] not in {"first", "second", "later"}:
            raise ValueError("unknown committing actor")
        req = request(row, actor["caller"])
        when = actor["active_epoch"]
        if when not in (2, 3) or not last_epoch <= when <= active:
            raise ValueError("witness epoch reverses committed namespace history")
        last_epoch = when
        value = req["content_utf8"]
        if value is not None:
            payload = value
        approval = None if value is None else digest(value)
        item = {"revision": index + 4, "epoch": req["epoch"], "request_id": req["request_id"],
                "operation": "revoke" if value is None else "update", "approved_sha256": approval}
        if actor != {**item, "caller": req["caller"], "active_epoch": when}:
            raise ValueError("observer, request bytes and effect disagree")
        history.append(item)
        # Old receipts are removed at closure. An old write observed in the
        # current epoch can recreate one after that deletion, a separate failure.
        if req["epoch"] >= active or when == active:
            retained[(req["epoch"], req["request_id"])] = {**item, "payload_utf8": value}
    state = {"revision": 3 + len(actors), "approved_sha256": approval,
             "content_utf8": payload, "content_sha256": digest(payload)}
    delivery = {"status": "blocked" if approval is None else "delivered",
                "reason": "approval_revoked" if approval is None else "verified_recovery",
                "revision": state["revision"], "delivered_utf8": None if approval is None else payload}
    reconstructed = {"state": state, "active_epoch": active, "effects": history,
                     "receipts": [retained[k] for k in sorted(retained)], "commits": actors, "delivery": delivery,
                     "sqlite_settings": {"journal_mode": "delete", "synchronous": 2, "integrity_check": "ok"}}
    if reconstructed != observed:
        raise ValueError("snapshot differs from reconstructed state/receipt/delivery history")
    return actors


def check_trace(record, expected, flags):
    command = record["command"]
    if (len(command) != 2 + 2 * len(flags) or Path(command[1]).name != "resolution_worker.py"
            or len(set(command[2::2])) != len(flags) or dict(zip(command[2::2], command[3::2])) != flags):
        raise ValueError("saved child invocation differs from its declared identity")
    events = [{"seq": n, **event} for n, event in enumerate(expected)]
    if (record["returncode"] != 0 or record["stderr"] or record["events"] != events
            or [json.loads(line) for line in record["stdout"].splitlines()] != events):
        raise ValueError("incomplete or contradictory actor trace")


def retirement_trace(row, record):
    busy = record["response"]["status"] == "busy"
    value = {"target_epoch": 3, "busy_timeout_ms": 0, "sqlite_errorcode": 5 if busy else None,
             "sqlite_errorname": "SQLITE_BUSY" if busy else None, "status": "busy" if busy else "retired",
             "active_epoch": None if busy else 3}
    if record["response"] != value or record["mode"] != row["mode"]:
        raise ValueError("retirement target or numeric result changed")
    expected = [{"kind": "retirement_started", "target_epoch": 3},
                {"kind": "retirement_result", "response": value}, {"kind": "completed"}]
    command = record["command"]
    if len(command) < 4 or not command[3]:
        raise ValueError("missing fixture root")
    check_trace(record, expected, {"--root": command[3], "--mode": row["mode"], "--role": "retire", "--target": "3"})
    return busy


def caller_trace(row, record):
    caller = record["caller"]
    req = request(row, caller)
    value = req["content_utf8"]
    reply = record["response"]
    if (record["request"] != req or record["mode"] != row["mode"]
            or set(reply) != {"status", "epoch", "request_id", "revision", "approved_sha256"}
            or reply["epoch"] != req["epoch"] or reply["request_id"] != req["request_id"]
            or reply["status"] not in {"committed", "replayed", "conflict", "outcome_unavailable", "storage_error", "busy", "future_epoch"}):
        raise ValueError("caller request or result identity changed")
    e = []
    def add(kind, **fields):
        e.append({"kind": kind, **fields})
    def checkpoint(stage):
        add("checkpoint", stage=stage)
        if caller == "first" and stage in {"after_precheck", "before_resolution"}:
            add("paused", stage=stage, caller=caller)
            add("resumed", stage=stage, caller=caller)
    def lookup(scope, epoch, current, seen, decision, origin):
        add("lookup", scope=scope, origin=origin, observed_epoch=epoch, current_revision=current,
            receipt_seen=seen, receipt_revision=4 if seen else None, decision=decision)
    add("caller_started", caller=caller, epoch=req["epoch"], request_id=req["request_id"],
        operation="revoke" if value is None else "update", payload_sha256=None if value is None else digest(value))
    lookup("initial", req["epoch"], 4 if caller == "later" else 3, False, "missing", "read")
    checkpoint("after_precheck")
    add("write_view", revision=4 if caller == "second" else 5, requested_epoch=req["epoch"], active_epoch=req["epoch"])
    if caller != "first":
        checkpoint("before_commit")
        checkpoint("after_commit")
    else:
        add("duplicate_receipt", at="receipt_insert", sqlite_errorcode=1555,
            sqlite_errorname="SQLITE_CONSTRAINT_PRIMARYKEY", transaction_rolled_back=True)
        guarded = row["mode"] == "guarded_resolution"
        add("resolution_guard", held=guarded)
        checkpoint("before_resolution")
        snapshot = row["resolution_capture"]
        epoch = snapshot["active_epoch"]
        seen = any(r["epoch"] == 2 and r["request_id"] == "shared-request" for r in snapshot["receipts"])
        same = value == request(row, "second")["content_utf8"]
        decision = ("replayed" if same else "conflict") if seen else "outcome_unavailable" if epoch > 2 else "missing"
        lookup("resolution", epoch, snapshot["state"]["revision"], seen, decision, "transaction" if guarded else "read")
        if row["mode"] == "retry_missing" and not seen:
            add("unsafe_retry", requested_epoch=2, observed_epoch=epoch)
            add("write_view", revision=snapshot["state"]["revision"] + 1, requested_epoch=2, active_epoch=epoch)
            checkpoint("before_commit")
            checkpoint("after_commit")
        elif guarded:
            add("resolution_released")
    add("caller_result", response=reply)
    add("completed")
    command = record["command"]
    if len(command) < 4 or not command[3]:
        raise ValueError("missing caller fixture")
    check_trace(record, e, {"--root": command[3], "--mode": row["mode"], "--role": "caller", "--caller": caller,
                            "--epoch": str(req["epoch"]), "--key": req["request_id"], "--intent": req["intent"],
                            "--pauses": "both" if caller == "first" else "none"})


def evaluate(row):
    gap = row["schedule"].startswith("retire_gap")
    later = row["schedule"] == "retire_gap_later"
    callers, retirements = row["callers"], row["retirements"]
    invocations = [r["command"] for r in (*callers, *retirements)]
    if any(len(c) < 4 for c in invocations) or len({(c[0], c[1], c[3]) for c in invocations}) != 1:
        raise ValueError("actors did not preserve a common interpreter, worker and fixture")
    if [c["caller"] for c in callers] != ["first", "second"] + (["later"] if later else []):
        raise ValueError("logical caller coverage changed")
    busy = bool(retirements and retirements[0]["response"]["status"] == "busy")
    phases = []
    if gap:
        phases.append("during_resolution")
    if busy or row["schedule"] == "resolution_first":
        phases.append("after_resolution")
    if ([r["phase"] for r in retirements] != phases or (busy and row["mode"] != "guarded_resolution")
            or (retirements and retirements[-1]["response"]["status"] != "retired")):
        raise ValueError("retirement ordering/retry differs from observed execution")
    for record in callers:
        caller_trace(row, record)
    for record in retirements:
        retirement_trace(row, record)
        audit_snapshot(row, record["capture"])
    seed = audit_snapshot(row, row["initial"])
    winner = audit_snapshot(row, row["winner_capture"])
    during = audit_snapshot(row, row["resolution_capture"])
    completed = audit_snapshot(row, row["after_first"])
    final = audit_snapshot(row, row["final"])
    if (seed or row["initial"]["active_epoch"] != 2 or [c["caller"] for c in winner] != ["second"]
            or winner[0]["active_epoch"] != 2 or row["winner_capture"]["active_epoch"] != 2):
        raise ValueError("wrong fixture or winner evidence")
    for r in retirements:
        expected = winner if r["phase"] == "during_resolution" else completed
        if r["capture"]["commits"] != expected or r["capture"]["active_epoch"] != (2 if r["response"]["status"] == "busy" else 3):
            raise ValueError("retirement rewrote a durable effect prefix")
    independent = None
    if later:
        independent = audit_snapshot(row, row["later_capture"])
        if [c["caller"] for c in independent] != ["second", "later"] or row["later_capture"]["active_epoch"] != 3:
            raise ValueError("later publication does not follow closure")
        item = independent[-1]
        if callers[-1]["response"] != response("committed", request(row, "later"), item["revision"], item["approved_sha256"]):
            raise ValueError("later response differs from its effect")
    elif row["later_capture"] is not None:
        raise ValueError("undeclared independent work")
    prefix = independent if later and not busy else winner
    if during != prefix or row["resolution_capture"]["active_epoch"] != (3 if gap and not busy else 2):
        raise ValueError("resolution did not follow the observed retirement position")
    if completed[:len(prefix)] != prefix or any(c["caller"] != "first" for c in completed[len(prefix):]):
        raise ValueError("resolution completion changed an earlier causal prefix")
    if later and busy and independent[:-1] != completed:
        raise ValueError("later work changed completed resolution history")
    if (final != (independent if later and busy else completed)
            or row["final"]["active_epoch"] != (2 if row["schedule"] == "retained" else 3)):
        raise ValueError("unscheduled final writer or namespace")
    journal = []
    def note(kind, **fields):
        journal.append({"kind": kind, **fields})
    def start(caller):
        note("caller_started", caller=caller)
    def done(caller):
        value = next(c["response"] for c in callers if c["caller"] == caller)
        note("caller_completed", caller=caller, status=value["status"])
    def retire(index):
        item = retirements[index]
        note("retirement_requested", attempt=index + 1, phase=item["phase"])
        note("retirement_completed", attempt=index + 1, status=item["response"]["status"], sqlite_errorcode=item["response"]["sqlite_errorcode"])
        note("retirement_observed", attempt=index + 1)
    def publish_later():
        start("later")
        done("later")
        note("later_observed")
    note("seeded")
    start("first")
    note("first_paused", stage="after_precheck")
    start("second")
    done("second")
    note("winner_observed")
    note("first_resumed", stage="after_precheck")
    note("first_paused", stage="before_resolution")
    if gap:
        retire(0)
        if later and not busy:
            publish_later()
    note("resolution_observed")
    note("first_resumed", stage="before_resolution")
    done("first")
    note("first_observed")
    if busy or row["schedule"] == "resolution_first":
        retire(1 if busy else 0)
        if later:
            publish_later()
    note("final_observed")
    if row["timeline"] != [{"seq": n, **item} for n, item in enumerate(journal)]:
        raise ValueError("controller journal contradicts process ordering")
    first, second = request(row, "first"), request(row, "second")
    same = first["content_utf8"] == second["content_utf8"]
    original = response("replayed", first, winner[0]["revision"], winner[0]["approved_sha256"]) if same else response("conflict", first)
    expected_winner = response("committed", second, winner[0]["revision"], winner[0]["approved_sha256"])
    winner_ok = callers[1]["response"] == expected_winner
    shared = [c for c in final if c["request_id"] == "shared-request"]
    one = len(shared) == 1
    first_result = callers[0]["response"]
    receipt_available = any(r["epoch"] == 2 and r["request_id"] == "shared-request" for r in row["resolution_capture"]["receipts"])
    original_ok = winner_ok and one and receipt_available and first_result == original
    missing_closed = row["resolution_capture"]["active_epoch"] > 2 and not receipt_available
    unavailable = first_result == response("outcome_unavailable", first)
    safe = original_ok or (winner_ok and one and missing_closed and unavailable)
    return {
        "extra_gap_effect": gap and len(shared) > 1, "one_shared_effect": one, "new_effects": len(final),
        "safe_gap_resolution": gap and safe, "unavailable_gap": gap and unavailable and missing_closed and one,
        "original_gap_resolution": gap and original_ok, "identical_gap_replay": gap and same and original_ok,
        "changed_gap_conflict": gap and not same and original_ok,
        "later_state_preserved": later and row["final"]["state"] == row["later_capture"]["state"] and row["final"]["delivery"] == row["later_capture"]["delivery"],
        "control_original_resolution": not gap and original_ok, "receipt_pk_aborts": 1, "rollback_verified": True,
        "busy_retirements": int(busy), "completed_retirement_retry": busy,
        "final_epoch_3": row["final"]["active_epoch"] == 3, "final_epoch_2": row["final"]["active_epoch"] == 2,
        "coherent_final": row["final"]["state"]["approved_sha256"] in (None, row["final"]["state"]["content_sha256"]),
        "invalid_old_commit": any(c["epoch"] < c["active_epoch"] for c in final),
        "recreated_old_receipt": any(r["epoch"] < row["final"]["active_epoch"] for r in row["final"]["receipts"]),
        "retired_old_receipts_absent": row["final"]["active_epoch"] == 3 and not any(r["epoch"] < 3 for r in row["final"]["receipts"]),
        "consistent_observations": True, "verified_barriers": 2,
        "child_completions": len(callers) + len(retirements),
    }


def recount(records, cases):
    wanted = {(c["case_id"], m) for c in cases for m in MODES}
    if len(records) != 48 or {(r["case_id"], r["mode"]) for r in records} != wanted:
        raise ValueError("missing, extra or repeated record")
    declared = {c["case_id"]: c for c in cases}
    arms = {}
    for mode in MODES:
        rows = [r for r in records if r["mode"] == mode]
        outcomes = []
        for row in rows:
            if any(row[k] != v for k, v in declared[row["case_id"]].items()):
                raise ValueError("raw declaration differs from frozen manifest")
            if row["status"] == "complete":
                outcome = evaluate(row)
                if outcome != row["oracle"]:
                    raise ValueError("independent reconstruction disagrees with stored oracle")
                outcomes.append(outcome)
            elif row["status"] != "infrastructure_error" or row["oracle"] is not None:
                raise ValueError("invalid execution status")
        gaps = [r for r in rows if r["schedule"].startswith("retire_gap")]
        arms[mode] = {"cases": len(rows), "gap_cases": len(gaps),
                      "identical_gap_cases": sum(PATTERNS[r["pattern"]][0] == PATTERNS[r["pattern"]][1] for r in gaps),
                      "changed_gap_cases": sum(PATTERNS[r["pattern"]][0] != PATTERNS[r["pattern"]][1] for r in gaps),
                      "later_cases": sum(r["schedule"] == "retire_gap_later" for r in rows),
                      "control_cases": len(rows) - len(gaps), "retired_cases": sum(r["schedule"] != "retained" for r in rows),
                      "infrastructure_errors": len(rows) - len(outcomes),
                      **{name: sum(v[name] for v in outcomes) for name in FIELDS}}
    def vector(field):
        return [arms[m][field] for m in MODES]
    criteria = {
        "one_effect_and_total_effects": vector("extra_gap_effect") == [12, 0, 0] and vector("one_shared_effect") == [4, 16, 16] and vector("new_effects") == [32, 20, 20],
        "safe_outcomes_and_unavailability": vector("safe_gap_resolution") == [0, 12, 12] and vector("unavailable_gap") == [0, 12, 0],
        "original_outcomes": vector("original_gap_resolution") == [0, 0, 12] and vector("identical_gap_replay") == [0, 0, 6] and vector("changed_gap_conflict") == [0, 0, 6],
        "later_policy_preserved": vector("later_state_preserved") == [0, 4, 4],
        "original_controls": vector("control_original_resolution") == [4, 4, 4],
        "collision_and_rollback": vector("receipt_pk_aborts") == vector("rollback_verified") == [16, 16, 16],
        "retirement_contention_and_retries": vector("busy_retirements") == vector("completed_retirement_retry") == [0, 0, 12],
        "current_epoch_and_coherence": vector("final_epoch_3") == [14, 14, 14] and vector("final_epoch_2") == [2, 2, 2] and vector("coherent_final") == vector("consistent_observations") == [16, 16, 16],
        "closed_epoch_evidence": vector("invalid_old_commit") == vector("recreated_old_receipt") == [12, 0, 0] and vector("retired_old_receipts_absent") == [2, 14, 14],
        "complete_process_and_barrier_coverage": vector("verified_barriers") == [32, 32, 32] and vector("child_completions") == [50, 50, 62] and vector("infrastructure_errors") == [0, 0, 0],
    }
    return {"arms": arms, "criteria": criteria}


def verify(summary_path: Path, dataset: Path):
    metadata = json.loads(summary_path.read_text())
    if metadata["dataset_sha256"] != hashlib.sha256(dataset.read_bytes()).hexdigest():
        raise ValueError("dataset hash changed")
    hashes = {p: hashlib.sha256((ROOT / p).read_bytes()).hexdigest() for p in SOURCES}
    if hashes != metadata["source_sha256"]:
        raise ValueError("source bytes or source hash set changed")
    raw_name = metadata["results_file"]
    if Path(raw_name).name != raw_name or not raw_name.endswith("-resolution-v1.jsonl"):
        raise ValueError("invalid raw evidence filename")
    raw = summary_path.parent / raw_name
    records = [json.loads(line) for line in raw.read_text().splitlines()]
    reconstructed = recount(records, load_manifest(dataset))
    if reconstructed != metadata["summary"]:
        raise ValueError("summary counters differ from raw observations")
    return {"verified_at_utc": datetime.now(timezone.utc).isoformat(), "summary_file": summary_path.name,
            "raw_file": raw_name, "records": len(records), "source_hashes_checked": len(hashes),
            "summary_sha256": hashlib.sha256(summary_path.read_bytes()).hexdigest(),
            "raw_sha256": hashlib.sha256(raw.read_bytes()).hexdigest(), "independent_summary": reconstructed,
            "all_criteria_passed": all(reconstructed["criteria"].values()),
            "scope": "Independent stdlib reconstruction; no measured module imports; unavailable outcomes and original historical replies counted separately; trusted local witnesses, not external attestation."}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--summary", type=Path, required=True)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = verify(args.summary, args.dataset)
    encoded = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.output:
        with args.output.open("x", encoding="utf-8") as handle:
            handle.write(encoded)
    print(encoded, end="")
    return int(not report["all_criteria_passed"])


if __name__ == "__main__":
    raise SystemExit(main())
