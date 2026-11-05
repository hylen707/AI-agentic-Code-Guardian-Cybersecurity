"""Independently reconstruct Phase 12 caller outcomes using only the stdlib."""
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODES = ("precheck_insert", "constraint_conflict", "resolve_duplicate", "transactional_lookup")
VALUES = {
    "b": "approved=version-b\n", "c": "approved=version-c\n",
    "later": "approved=version-d\n", "empty": "", "revoke": None,
    "unicode": "approved=안전 ✓\n", "nfc": "approved=é\n", "nfd": "approved=e\u0301\n",
}
PATTERNS = {
    "same_ascii": ("b", "b"), "same_empty": ("empty", "empty"),
    "same_unicode": ("unicode", "unicode"), "same_revoke": ("revoke", "revoke"),
    "changed_bytes": ("b", "c"), "update_to_revoke": ("empty", "revoke"),
    "revoke_to_update": ("revoke", "empty"), "changed_unicode_bytes": ("nfc", "nfd"),
}
SOURCES = (
    "src/caller_store.py", "experiments/caller_worker.py", "experiments/run_caller_comparison.py",
    "experiments/verify_caller_results.py", "tests/test_caller_store.py", "docs/CALLER_PROTOCOL.md",
    "src/publication_store.py", "src/retry_store.py", "src/retirement_store.py", "src/overlap_store.py",
    "experiments/run_overlap_comparison.py",
)


def digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def manifest(path: Path) -> list[dict]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if set(data) != {"schema_version", "cases"} or data["schema_version"] != "caller-eval-v1":
        raise ValueError("unsupported manifest")
    cases = data["cases"]
    grid = {("overlap", name) for name in PATTERNS}
    grid |= {("overlap_with_later", name) for name in ("same_ascii", "same_revoke", "changed_bytes", "update_to_revoke")}
    grid |= {("serial", name) for name in ("same_ascii", "same_empty", "changed_bytes")}
    grid.add(("distinct_overlap", "same_ascii"))
    if (not isinstance(cases, list) or len(cases) != 16
            or any(not isinstance(c, dict) or set(c) != {"case_id", "schedule", "pattern"}
                   or not all(isinstance(v, str) and v for v in c.values()) for c in cases)
            or len({c["case_id"] for c in cases}) != 16
            or {(c["schedule"], c["pattern"]) for c in cases} != grid):
        raise ValueError("manifest lost or repeated a declared history")
    return cases


def inputs(row: dict) -> dict:
    aliases = dict(zip(("first", "second"), PATTERNS[row["pattern"]]))
    aliases["later"] = "later"
    result = {}
    for caller, alias in aliases.items():
        key = "later" if caller == "later" else "other-request" if caller == "second" and row["schedule"] == "distinct_overlap" else "shared-request"
        result[caller] = {"caller": caller, "epoch": 2, "request_id": key,
                          "intent": alias, "content_utf8": VALUES[alias]}
    return result


def answer(status: str, req: dict, revision=None, approval=None) -> dict:
    return {"status": status, "epoch": 2, "request_id": req["request_id"],
            "revision": revision, "approved_sha256": approval}


def audit_capture(row: dict, observed: dict) -> list[dict]:
    """Rebuild publication, receipt and delivery bytes from committing actors."""
    declared = inputs(row)
    commits = observed["call_commits"]
    effects = [
        {"revision": 2, "epoch": 1, "request_id": "seed-a", "operation": "update", "approved_sha256": digest(VALUES["b"])},
        {"revision": 3, "epoch": 1, "request_id": "seed-b", "operation": "revoke", "approved_sha256": None},
    ]
    payload, approval = VALUES["b"], None
    receipt_options = {}
    for offset, commit in enumerate(commits):
        caller = commit["caller"]
        if caller not in declared or (caller == "later" and row["schedule"] != "overlap_with_later"):
            raise ValueError("undeclared committing actor")
        req = declared[caller]
        value = req["content_utf8"]
        if value is not None:
            payload = value
        approval = None if value is None else digest(value)
        effect = {"revision": offset + 4, "epoch": 2, "request_id": req["request_id"],
                  "operation": "revoke" if value is None else "update", "approved_sha256": approval}
        if commit != {**effect, "caller": caller}:
            raise ValueError("committing actor does not bind its exact input")
        effects.append(effect)
        receipt_options.setdefault(req["request_id"], []).append({**effect, "payload_utf8": value})
    receipts = observed["receipts"]
    if (len(receipts) != len(receipt_options)
            or len({r["request_id"] for r in receipts}) != len(receipts)
            or any(r not in receipt_options.get(r["request_id"], []) for r in receipts)):
        raise ValueError("receipt lacks its exact effect and payload")
    state = {"revision": len(commits) + 3, "approved_sha256": approval,
             "content_utf8": payload, "content_sha256": digest(payload)}
    delivery = {"status": "blocked" if approval is None else "delivered",
                "reason": "approval_revoked" if approval is None else "verified_recovery",
                "revision": state["revision"], "delivered_utf8": None if approval is None else payload}
    expected = {"state": state, "active_epoch": 2, "effects": effects, "receipts": receipts,
                "call_commits": commits, "delivery": delivery,
                "sqlite_settings": {"journal_mode": "delete", "synchronous": 2, "integrity_check": "ok"}}
    if observed != expected:
        raise ValueError("capture contradicts reconstructed durable history")
    return commits


def audit_attempt(row: dict, attempt: dict, contended: bool) -> tuple[int, int]:
    req = inputs(row)[attempt["caller"]]
    if attempt["request"] != req or attempt["mode"] != row["mode"]:
        raise ValueError("retry changed caller, identity, bytes or mode")
    caller, number = attempt["caller"], attempt["attempt"]
    paused = row["schedule"] != "serial" and caller == "first"
    command = attempt["command"]
    tail = ["--mode", row["mode"], "--caller", caller, "--key", req["request_id"],
            "--epoch", "2", "--intent", req["intent"], "--pause", "after_lookup" if paused else "none"]
    if (len(command) != 16 or Path(command[1]).name != "caller_worker.py"
            or command[2] != "--root" or not command[3] or command[4:] != tail):
        raise ValueError("saved invocation differs from requested attempt")
    response = attempt["response"]
    if (set(response) != {"status", "epoch", "request_id", "revision", "approved_sha256"}
            or response["epoch"] != 2 or response["request_id"] != req["request_id"]
            or response["status"] not in {"committed", "replayed", "conflict", "storage_error", "busy", "epoch_retired", "future_epoch"}):
        raise ValueError("invalid response identity or shape")
    events = attempt["events"]
    if (attempt["returncode"] != 0 or attempt["stderr"]
            or [json.loads(line) for line in attempt["stdout"].splitlines()] != events
            or any(e["seq"] != n for n, e in enumerate(events))):
        raise ValueError("child did not preserve a complete normal trace")
    pending = iter(events)

    def take(kind, **fields):
        item = next(pending, None)
        if item is None or {k: v for k, v in item.items() if k != "seq"} != {"kind": kind, **fields}:
            raise ValueError("unexpected caller event: " + kind)

    value = req["content_utf8"]
    take("attempt_started", caller=caller, epoch=2, request_id=req["request_id"],
         operation="revoke" if value is None else "update", payload_sha256=None if value is None else digest(value))
    busy = contended and caller == "second" and number == 1
    collision = row["schedule"] in {"overlap", "overlap_with_later"} and caller == "first" and not contended
    if busy:
        take("writer_busy", at="begin_immediate", sqlite_errorcode=5, sqlite_errorname="SQLITE_BUSY", busy_timeout_ms=0)
        if response != answer("busy", req):
            raise ValueError("busy attempt claims an effect")
    else:
        has_prior = caller == "second" and (row["schedule"] == "serial" or number == 2) and row["schedule"] != "distinct_overlap"
        current = 4 if caller == "later" or has_prior or number == 2 else 3
        if number == 2 and row["schedule"] == "overlap_with_later":
            current = 5
        same = value == inputs(row)["first"]["content_utf8"]
        decision = ("replayed" if same else "conflict") if has_prior else "missing"
        take("lookup", scope="initial", origin="transaction" if row["mode"] == "transactional_lookup" else "read",
             observed_epoch=2, current_revision=current, receipt_seen=has_prior,
             receipt_revision=4 if has_prior else None, decision=decision)
        if not has_prior:
            take("checkpoint", stage="after_lookup")
            if paused:
                take("paused", stage="after_lookup", caller="first")
                take("resumed", stage="after_lookup", caller="first")
            if collision:
                take("duplicate_receipt", at="receipt_insert", sqlite_errorcode=1555,
                     sqlite_errorname="SQLITE_CONSTRAINT_PRIMARYKEY", transaction_rolled_back=True)
                if row["mode"] == "resolve_duplicate":
                    take("lookup", scope="resolution", origin="read", observed_epoch=2,
                         current_revision=5 if row["schedule"] == "overlap_with_later" else 4,
                         receipt_seen=True, receipt_revision=4,
                         decision="replayed" if value == inputs(row)["second"]["content_utf8"] else "conflict")
            else:
                take("checkpoint", stage="before_commit")
                take("checkpoint", stage="after_commit")
    take("result", response=response)
    take("completed")
    if next(pending, None) is not None:
        raise ValueError("trailing caller events")
    return int(collision), int(busy)


def evaluate(row: dict) -> dict:
    forced = row["schedule"] != "serial"
    later = row["schedule"] == "overlap_with_later"
    shared = row["schedule"] != "distinct_overlap"
    reqs = inputs(row)
    attempts = row["attempts"]
    second = [a for a in attempts if a["caller"] == "second"]
    if not second:
        raise ValueError("second caller missing")
    contended = second[0]["response"]["status"] == "busy"
    order = [("first", 1), ("second", 1)]
    if later:
        order.append(("later", 1))
    if contended:
        order.append(("second", 2))
    if ([(a["caller"], a["attempt"]) for a in attempts] != order
            or (contended and (not forced or row["mode"] != "transactional_lookup"))):
        raise ValueError("caller attempt order or retry scope changed")
    collisions, busy_count = 0, 0
    for attempt in attempts:
        duplicate, busy = audit_attempt(row, attempt, contended)
        collisions += duplicate
        busy_count += busy
    logical = {c: [a for a in attempts if a["caller"] == c][-1]["response"] for c in ("first", "second")}
    if row["logical_results"] != logical or any(v["status"] == "busy" for v in logical.values()):
        raise ValueError("logical caller has no final outcome")
    if audit_capture(row, row["initial"]):
        raise ValueError("fixture already contains caller work")
    first_done = audit_capture(row, row["after_first"])
    final = audit_capture(row, row["final"])
    prefix = []
    if forced:
        prefix = audit_capture(row, row["during_pause"])
        roles = [] if contended else ["second"] + (["later"] if later else [])
        if [c["caller"] for c in prefix] != roles:
            raise ValueError("pause does not establish declared winner ordering")
    elif row["during_pause"] is not None:
        raise ValueError("serial history has an undeclared pause")
    if first_done[:len(prefix)] != prefix or any(c["caller"] != "first" for c in first_done[len(prefix):]):
        raise ValueError("first completion rewrote a causal prefix")
    after_later = None
    if later:
        after_later = audit_capture(row, row["later_capture"])
        if [c["caller"] for c in after_later] != (["first"] if contended else ["second"]) + ["later"]:
            raise ValueError("independent publication in wrong position")
        intervention = next(a["response"] for a in attempts if a["caller"] == "later")
        if intervention != answer("committed", reqs["later"], after_later[-1]["revision"], after_later[-1]["approved_sha256"]):
            raise ValueError("later caller acknowledgment is incorrect")
        if contended and after_later[:-1] != first_done:
            raise ValueError("later publication rewrote the first completion prefix")
        if not contended and after_later != prefix:
            raise ValueError("pause changed the independent publication prefix")
    elif row["later_capture"] is not None:
        raise ValueError("undeclared independent publication")
    if forced and not contended:
        if final != first_done:
            raise ValueError("unscheduled writer after first completion")
    else:
        prefix = after_later if later else first_done
        if final[:len(prefix)] != prefix or any(c["caller"] != "second" for c in final[len(prefix):]):
            raise ValueError("second completion rewrote a causal prefix")
    journal = []

    def note(kind, **fields):
        journal.append({"seq": len(journal), "kind": kind, **fields})

    def start(caller, number):
        note("attempt_started", caller=caller, attempt=number)

    def finish(caller, number):
        response = next(a["response"] for a in attempts if (a["caller"], a["attempt"]) == (caller, number))
        note("attempt_completed", caller=caller, attempt=number, status=response["status"])

    def independent():
        start("later", 1)
        finish("later", 1)
        note("later_observed")

    note("seeded")
    start("first", 1)
    if forced:
        note("first_paused")
        start("second", 1)
        finish("second", 1)
        if later and not contended:
            independent()
        note("pause_observed")
        note("first_resumed")
        finish("first", 1)
        note("first_observed")
        if contended:
            if later:
                independent()
            start("second", 2)
            finish("second", 2)
    else:
        finish("first", 1)
        note("first_observed")
        start("second", 1)
        finish("second", 1)
    note("final_observed")
    if row["timeline"] != journal:
        raise ValueError("controller timeline contradicts caller trace")
    expected = {}
    for caller in ("first", "second"):
        req = reqs[caller]
        effects = [c for c in final if c["request_id"] == req["request_id"]]
        expected[caller] = None
        if effects:
            winner = effects[0]
            status = "committed" if winner["caller"] == caller else "replayed" if req["content_utf8"] == reqs[winner["caller"]]["content_utf8"] else "conflict"
            expected[caller] = answer(status, req, None if status == "conflict" else winner["revision"],
                                      None if status == "conflict" else winner["approved_sha256"])
    one_effect = shared and sum(c["request_id"] == "shared-request" for c in final) == 1
    shape_correct = one_effect if shared else len(final) == 2 and {c["request_id"] for c in final} == {"shared-request", "other-request"}
    correct = bool(shape_correct and all(expected[c] is not None and logical[c] == expected[c] for c in logical))
    race = row["schedule"] in {"overlap", "overlap_with_later"}
    same = reqs["first"]["content_utf8"] == reqs["second"]["content_utf8"]
    preserved = later and row["final"] == row["later_capture"]
    return {
        "pair_correct": correct, "race_pair_correct": race and correct,
        "identical_race_replayed": race and same and correct, "changed_race_conflicted": race and not same and correct,
        "false_conflicts": sum(logical[c]["status"] == "conflict" and expected[c] is not None and expected[c]["status"] == "replayed" for c in logical),
        "modeled_storage_errors": sum(v["status"] == "storage_error" for v in logical.values()),
        "receipt_pk_aborts": collisions, "busy_attempts": busy_count,
        "completed_busy_retry": contended and second[-1]["response"]["status"] != "busy",
        "one_shared_effect": one_effect, "new_effects": len(final),
        "serial_pair_correct": row["schedule"] == "serial" and correct,
        "distinct_pair_correct": not shared and correct, "later_state_preserved": preserved,
        "historical_replay_correct": later and same and correct and preserved,
        "later_pair_correct": later and correct,
        "intrinsic_state_coherent": row["final"]["state"]["approved_sha256"] in (None, row["final"]["state"]["content_sha256"]),
        "final_epoch_current": row["final"]["active_epoch"] == 2,
        "barrier_verified": forced, "observations_consistent": True,
    }


def recount(records: list[dict], cases: list[dict]) -> dict:
    grid = {(c["case_id"], m) for c in cases for m in MODES}
    if len(records) != 64 or {(r["case_id"], r["mode"]) for r in records} != grid:
        raise ValueError("missing, extra or repeated case/mode")
    declarations = {c["case_id"]: c for c in cases}
    mapping = {
        "pairs_correct": "pair_correct", "race_pairs_correct": "race_pair_correct",
        "identical_race_replays": "identical_race_replayed", "changed_race_conflicts": "changed_race_conflicted",
        "completed_busy_retries": "completed_busy_retry", "one_shared_effect_cases": "one_shared_effect",
        "serial_pairs_correct": "serial_pair_correct", "distinct_pairs_correct": "distinct_pair_correct",
        "later_states_preserved": "later_state_preserved", "historical_replays": "historical_replay_correct",
        "later_pairs_correct": "later_pair_correct", "coherent_final_states": "intrinsic_state_coherent",
        "final_epoch_current": "final_epoch_current", "verified_barriers": "barrier_verified",
        "consistent_observations": "observations_consistent",
    }
    direct = ("false_conflicts", "modeled_storage_errors", "receipt_pk_aborts", "busy_attempts", "new_effects")
    arms = {}
    for mode in MODES:
        rows = [r for r in records if r["mode"] == mode]
        verdicts = []
        for row in rows:
            if any(row[k] != v for k, v in declarations[row["case_id"]].items()):
                raise ValueError("raw input declaration changed")
            if row["status"] == "complete":
                actual = evaluate(row)
                if row["oracle"] != actual:
                    raise ValueError("saved oracle disagrees with independent reconstruction")
                verdicts.append(actual)
            elif row["status"] != "infrastructure_error" or row["oracle"] is not None:
                raise ValueError("invalid raw execution status")
        race = [r for r in rows if r["schedule"] in {"overlap", "overlap_with_later"}]
        arm = {"cases": len(rows), "shared_cases": sum(r["schedule"] != "distinct_overlap" for r in rows),
               "race_cases": len(race), "identical_race_cases": sum(PATTERNS[r["pattern"]][0] == PATTERNS[r["pattern"]][1] for r in race),
               "changed_race_cases": sum(PATTERNS[r["pattern"]][0] != PATTERNS[r["pattern"]][1] for r in race),
               "later_cases": sum(r["schedule"] == "overlap_with_later" for r in rows),
               "serial_controls": sum(r["schedule"] == "serial" for r in rows),
               "distinct_controls": sum(r["schedule"] == "distinct_overlap" for r in rows),
               "child_completions": sum(len(r["attempts"]) for r in rows if r["status"] == "complete"),
               "infrastructure_errors": len(rows) - len(verdicts)}
        arm.update({name: sum(v[name] for v in verdicts) for name in direct})
        arm.update({name: sum(v[field] for v in verdicts) for name, field in mapping.items()})
        arms[mode] = arm
    v = list(arms.values())
    criteria = {
        "shared_effect_and_total_effect_counts": all(a["one_shared_effect_cases"] == 15 and a["new_effects"] == 21 for a in v),
        "concurrent_pair_results": [a["race_pairs_correct"] for a in v] == [0, 6, 12, 12],
        "replay_and_parameter_conflict_results": [a["identical_race_replays"] for a in v] == [0, 0, 6, 6] and [a["changed_race_conflicts"] for a in v] == [0, 6, 6, 6],
        "false_conflicts_and_storage_errors": [a["false_conflicts"] for a in v] == [0, 6, 0, 0] and [a["modeled_storage_errors"] for a in v] == [12, 0, 0, 0],
        "primary_key_abort_counts": [a["receipt_pk_aborts"] for a in v] == [12, 12, 12, 0],
        "identity_preserving_busy_retries": all([a[field] for a in v] == [0, 0, 0, 13] for field in ("busy_attempts", "completed_busy_retries")),
        "historical_replies_and_later_state": [a["historical_replays"] for a in v] == [0, 0, 2, 2] and all(a["later_states_preserved"] == 4 for a in v) and [a["later_pairs_correct"] for a in v] == [0, 2, 4, 4],
        "serial_and_distinct_controls": all(a["serial_pairs_correct"] == 3 and a["distinct_pairs_correct"] == 1 for a in v),
        "all_captures_coherent_and_current": all(a["coherent_final_states"] == a["final_epoch_current"] == a["consistent_observations"] == 16 for a in v),
        "all_process_and_barrier_coverage": all(a["verified_barriers"] == 13 and a["infrastructure_errors"] == 0 for a in v) and [a["child_completions"] for a in v] == [36, 36, 36, 49],
    }
    return {"arms": arms, "criteria": criteria}


def verify(summary_path: Path, dataset: Path) -> dict:
    metadata = json.loads(summary_path.read_text(encoding="utf-8"))
    if metadata["dataset_sha256"] != hashlib.sha256(dataset.read_bytes()).hexdigest():
        raise ValueError("dataset hash differs")
    actual_hashes = {p: hashlib.sha256((ROOT / p).read_bytes()).hexdigest() for p in SOURCES}
    if metadata["source_sha256"] != actual_hashes:
        raise ValueError("source hash set or bytes differ")
    raw_name = metadata["results_file"]
    if Path(raw_name).name != raw_name or not raw_name.endswith("-caller-v1.jsonl"):
        raise ValueError("invalid raw artifact name")
    records = [json.loads(line) for line in (summary_path.parent / raw_name).read_text(encoding="utf-8").splitlines()]
    actual = recount(records, manifest(dataset))
    if actual != metadata["summary"]:
        raise ValueError("summary counters differ from raw observations")
    return {"verified_at_utc": datetime.now(timezone.utc).isoformat(), "summary_file": summary_path.name,
            "raw_file": raw_name, "records": len(records), "source_hashes_checked": len(actual_hashes),
            "summary_sha256": hashlib.sha256(summary_path.read_bytes()).hexdigest(),
            "raw_sha256": hashlib.sha256((summary_path.parent / raw_name).read_bytes()).hexdigest(),
            "independent_summary": actual, "all_criteria_passed": all(actual["criteria"].values()),
            "scope": "Pure-stdlib reconstruction; no store, worker or measured-controller imports; trusted local observer and declared source labels, not external attestation."}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--summary", type=Path, required=True)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = verify(args.summary, args.dataset)
    encoded = json.dumps(report, indent=2, ensure_ascii=False) + "\n"
    if args.output:
        with args.output.open("x", encoding="utf-8") as handle:
            handle.write(encoded)
    print(encoded, end="")
    return int(not report["all_criteria_passed"])


if __name__ == "__main__":
    raise SystemExit(main())
