"""Arrange publication around migration source selection and commit."""
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

from experiments.run_overlap_comparison import BarrierFailure, wait_for_pause
from src.compaction_store import SUMMARY_COLUMNS
from src.publication_store import recover_value
from src.selection_store import MODES, STAGES, SelectionPublicationStore

VALUES = {"ascii": "approved=version-b\n", "empty": "", "unicode": "approved=안전 ✓\n", "revoke": None,
          "later": "approved=version-d\n"}
SCHEDULES = {"after_selection": tuple(VALUES)[:4], "after_refresh": tuple(VALUES)[:4],
             "before_commit": ("ascii", "revoke"), "after_commit": ("ascii", "revoke"),
             "publisher_first": tuple(VALUES)[:4], "migration_first": ("ascii", "revoke"),
             "current_epoch": tuple(VALUES)[:4], "publisher_first_later": ("ascii", "revoke")}
SOURCES = ("src/selection_store.py", "experiments/selection_worker.py", "experiments/run_selection_comparison.py",
           "experiments/verify_selection_results.py", "tests/test_selection_store.py", "docs/SELECTION_PROTOCOL.md",
           "src/compaction_store.py", "src/publication_store.py", "src/retry_store.py", "src/retirement_store.py",
           "src/overlap_store.py", "experiments/run_overlap_comparison.py")
FIELDS = ("final_epoch_2", "old_full_absent", "coherent_final", "current_history_correct", "gap_lost_history",
          "gap_old_committed", "gap_old_denied", "old_committed", "old_replayed", "current_completed", "current_replayed",
          "summary_rows", "missing_summary_rows", "complete_summary_coverage", "busy_attempts", "completed_pub_retry",
          "old_denied", "stale_migrations", "completed_migration_retry", "stale_untouched", "prefix_original_supported",
          "later_historical_supported", "migration_first_denied", "before_commit_denied", "after_commit_denied",
          "migration_witness_present", "stale_commit_witness", "publication_epochs_valid", "verified_barriers",
          "migration_completions", "publisher_completions", "later_completions", "child_completions", "false_history",
          "followup_no_effect", "publisher_result_correct", "followup_result_correct", "consistent_observations")
STEP_TIMEOUT = 15


def sha(value):
    return None if value is None else hashlib.sha256(value.encode()).hexdigest()


def load_cases(path):
    data = json.loads(path.read_text())
    if not isinstance(data, dict) or set(data) != {"schema_version", "cases"} or data["schema_version"] != "selection-eval-v1":
        raise ValueError("unsupported selection manifest")
    cases = data["cases"]
    wanted = {(s, v) for s, values in SCHEDULES.items() for v in values}
    if (not isinstance(cases, list) or len(cases) != 24
            or any(not isinstance(c, dict) or set(c) != {"case_id", "schedule", "value"}
                   or not all(isinstance(v, str) and v for v in c.values()) for c in cases)
            or len({c["case_id"] for c in cases}) != 24
            or {(c["schedule"], c["value"]) for c in cases} != wanted):
        raise ValueError("24 unique declared histories required")
    return cases


def request(case, role="inflight"):
    return {"epoch": 2 if role == "inflight" and case["schedule"] == "current_epoch" else 1,
            "request_id": role, "value": "later" if role == "later" else case["value"],
            "content_utf8": VALUES["later" if role == "later" else case["value"]]}


def reply(status, req, revision=None, approval=None):
    return {"status": status, "epoch": req["epoch"], "request_id": req["request_id"],
            "revision": revision, "approved_sha256": approval}


def full(req, revision):
    value = req["content_utf8"]
    return {"epoch": req["epoch"], "request_id": req["request_id"], "operation": "revoke" if value is None else "update",
            "payload_utf8": value, "revision": revision, "approved_sha256": sha(value)}


def compact(receipt):
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
                                 "content_utf8": state.content.decode(), "content_sha256": sha(state.content.decode())},
            "delivery": {**output, "delivered_utf8": None if content is None else content.decode()},
            "sqlite_settings": store.settings()}


def history(case, observed):
    seeds = [{"epoch": 1, "request_id": "seed-a", "content_utf8": VALUES["ascii"]},
             {"epoch": 1, "request_id": "seed-b", "content_utf8": None}]
    intents = seeds[:]
    prior_epoch = 1
    for revision, witness in enumerate(observed["publication_witnesses"], 4):
        if witness["request_id"] not in {"inflight", "later"} or (witness["request_id"] == "later" and case["schedule"] != "publisher_first_later"):
            raise ValueError("undeclared runtime publication witness")
        req = request(case, witness["request_id"])
        if (set(witness) != {"revision", "requested_epoch", "active_epoch", "request_id"}
                or witness["revision"] != revision or witness["requested_epoch"] != req["epoch"]
                or not prior_epoch <= witness["active_epoch"] <= observed["active_epoch"]):
            raise ValueError("publication witness contradicts request or namespace")
        prior_epoch = witness["active_epoch"]
        intents.append(req)
    return [full(req, revision) for revision, req in enumerate(intents, 2)]


def audit_capture(case, observed):
    if observed["active_epoch"] not in (1, 2) or observed["summary_columns"] != list(SUMMARY_COLUMNS):
        raise ValueError("wrong namespace or summary schema")
    records = history(case, observed)
    effects = [{k: v for k, v in r.items() if k != "payload_utf8"} for r in records]
    payload, approval = "approved=version-a\n", sha("approved=version-a\n")
    for r in records:
        if r["payload_utf8"] is not None:
            payload = r["payload_utf8"]
        approval = r["approved_sha256"]
    state = {"revision": len(records)+1, "approved_sha256": approval, "content_utf8": payload, "content_sha256": sha(payload)}
    delivery = {"status": "blocked" if approval is None else "delivered", "reason": "approval_revoked" if approval is None else "verified_recovery",
                "revision": state["revision"], "delivered_utf8": None if approval is None else payload}
    by_revision = {r["revision"]: r for r in records}
    for table, shortened in (("receipts", False), ("summaries", True)):
        rows = observed[table]
        keys = [(r["epoch"], r["request_id"]) for r in rows]
        if keys != sorted(set(keys)):
            raise ValueError("duplicate or unordered receipt authority")
        for r in rows:
            original = by_revision.get(r["revision"])
            if original is None or r != (compact(original) if shortened else original):
                raise ValueError("receipt does not bind an actual committed value")
    witness = observed["migration_witness"]
    if witness is not None and (set(witness) != {"target_epoch", "selected_revision", "write_revision", "selected_count", "write_count"}
                                or witness["target_epoch"] != 2 or not 3 <= witness["selected_revision"] <= witness["write_revision"] <= state["revision"]):
        raise ValueError("invalid migration witness")
    expected_keys = {"state", "active_epoch", "effects", "receipts", "summaries", "summary_columns", "publication_witnesses", "migration_witness", "delivery", "sqlite_settings"}
    if (set(observed) != expected_keys or observed["effects"] != effects or observed["state"] != state or observed["delivery"] != delivery
            or observed["sqlite_settings"] != {"journal_mode": "delete", "synchronous": 2, "integrity_check": "ok"}):
        raise ValueError("snapshot differs from publication/current delivery history")
    return records


def selection_view(observed):
    return {"active_epoch": observed["active_epoch"], "current_revision": observed["state"]["revision"],
            "receipts": [{**compact(r), "approved_sha256": r["approved_sha256"]} for r in observed["receipts"] if r["epoch"] < 2]}


def check_process(record, events, result_kind):
    if (record["returncode"] != 0 or record["stderr"] or record["events"] != events
            or [json.loads(line) for line in record["stdout"].splitlines()] != events
            or [e["response"] for e in events if e["kind"] == result_kind] != [record["response"]]):
        raise ValueError("incomplete or inconsistent child trace")


def audit_publication(case, record):
    req = request(case, record["role"])
    command = record["command"]
    if (record["request"] != req or len(command) != 14 or Path(command[1]).name != "selection_worker.py"
            or command[2] != "--root" or not command[3]
            or command[4:] != ["--mode", case["mode"], "--role", "publish", "--epoch", str(req["epoch"]),
                               "--key", req["request_id"], "--value", req["value"]]):
        raise ValueError("publisher changed original identity/bytes/command")
    before, after, answer = record["before"], record["after"], record["response"]
    audit_capture(case, before)
    audit_capture(case, after)
    if (set(answer) != {"status", "epoch", "request_id", "revision", "approved_sha256"}
            or answer["epoch"] != req["epoch"] or answer["request_id"] != req["request_id"]
            or answer["status"] not in {"committed", "replayed", "conflict", "outcome_unavailable", "future_epoch", "busy"}):
        raise ValueError("invalid publisher response")
    events = []
    def event(kind, **fields):
        events.append({"seq": len(events), "kind": kind, **fields})
    event("publication_started", epoch=req["epoch"], request_id=req["request_id"],
          operation="revoke" if req["content_utf8"] is None else "update", payload_sha256=sha(req["content_utf8"]))
    busy = answer["status"] == "busy"
    if busy:
        event("writer_busy", at="begin_immediate", sqlite_errorcode=5, sqlite_errorname="SQLITE_BUSY", busy_timeout_ms=0)
        if answer != reply("busy", req) or after != before:
            raise ValueError("busy publication changed state or claimed a commitment")
    else:
        existing = next((r for r in before["receipts"]+before["summaries"] if (r["epoch"], r["request_id"]) == (req["epoch"], req["request_id"])), None)
        kind = "none" if existing is None else "full" if "payload_utf8" in existing else "compact"
        if existing is not None:
            raise ValueError("fresh runtime publisher unexpectedly reused an existing identity")
        decision = "new" if req["epoch"] == before["active_epoch"] else "outcome_unavailable" if req["epoch"] < before["active_epoch"] else "future_epoch"
        event("publication_view", requested_epoch=req["epoch"], observed_epoch=before["active_epoch"], current_revision=before["state"]["revision"], receipt_kind=kind, decision=decision)
        if decision == "new":
            event("checkpoint", stage="before_commit")
            event("checkpoint", stage="after_commit")
            revision = before["state"]["revision"]+1
            expected_witness = {"revision": revision, "requested_epoch": req["epoch"], "active_epoch": before["active_epoch"], "request_id": req["request_id"]}
            if (after["publication_witnesses"] != before["publication_witnesses"]+[expected_witness]
                    or after["summaries"] != before["summaries"] or after["migration_witness"] != before["migration_witness"]
                    or after["receipts"] != sorted(before["receipts"]+[full(req, revision)], key=lambda r: (r["epoch"], r["request_id"]))):
                raise ValueError("publication did not atomically extend its effect/receipt/witness")
        elif after != before:
            raise ValueError("refused publication changed current state or history")
    event("publication_result", response=answer)
    event("completed")
    check_process(record, events, "publication_result")


def audit_migration(case, record):
    command, pause = record["command"], record["pause"]
    if (len(command) != 10 or Path(command[1]).name != "selection_worker.py" or command[2] != "--root" or not command[3]
            or command[4:] != ["--mode", case["mode"], "--role", "migrate", "--pause", pause]):
        raise ValueError("migration command changed role/mode/pause")
    before, after = record["before"], record["after"]
    audit_capture(case, before)
    audit_capture(case, after)
    if before["active_epoch"] != 1 or before["summaries"] or before["migration_witness"] is not None:
        raise ValueError("migration did not start in an open unconverted namespace")
    if pause != "none":
        audit_capture(case, record["pause_capture"])
    elif record["pause_capture"] is not None:
        raise ValueError("undeclared pause capture")
    initial = selection_view(before)
    selected = selection_view(record["pause_capture"]) if case["mode"] == "separate_refresh" and pause == "after_selection" else initial
    observed = selection_view(record["pause_capture"]) if pause in {"after_selection", "after_refresh", "before_commit"} else initial
    matched = selected == observed
    stale = case["mode"] == "validated_selection" and not matched
    events = []
    def event(kind, **fields):
        events.append({"seq": len(events), "kind": kind, **fields})
    def checkpoint(stage):
        event("checkpoint", stage=stage)
        if stage == pause:
            event("paused", stage=stage, role="migrate")
            event("resumed", stage=stage, role="migrate")
    origin = "transaction" if case["mode"] == "transactional_selection" else "read"
    event("migration_started", target_epoch=2)
    event("selection", scope="initial", origin=origin, **initial)
    checkpoint("after_selection")
    final_origin = "transaction" if case["mode"] == "transactional_selection" else "read" if case["mode"] == "separate_refresh" else "cached"
    event("selection", scope="final", origin=final_origin, **selected)
    checkpoint("after_refresh")
    event("validation", matched=matched, observed=observed)
    if stale:
        event("selection_changed", transaction_rolled_back=True)
        answer = {"status": "stale_selection", "active_epoch": observed["active_epoch"], "target_epoch": 2}
        if after != record["pause_capture"]:
            raise ValueError("stale migration changed authority or the fence")
    else:
        checkpoint("before_commit")
        checkpoint("after_commit")
        answer = {"status": "migrated", "active_epoch": 2, "target_epoch": 2}
        source = record["pause_capture"] if pause in {"after_selection", "after_refresh", "before_commit"} else before
        expected_witness = {"target_epoch": 2, "selected_revision": selected["current_revision"], "write_revision": observed["current_revision"],
                            "selected_count": len(selected["receipts"]), "write_count": len(observed["receipts"])}
        expected_summaries = [{k: v for k, v in r.items() if k != "approved_sha256"} for r in selected["receipts"]]
        if (after["state"] != source["state"] or after["publication_witnesses"] != source["publication_witnesses"]
                or after["active_epoch"] != 2 or after["receipts"] or after["summaries"] != expected_summaries
                or after["migration_witness"] != expected_witness):
            raise ValueError("migration commit differs from chosen source and durable publication history")
    event("migration_result", response=answer)
    event("completed")
    if record["response"] != answer:
        raise ValueError("migration returned an incorrect control signal")
    check_process(record, events, "migration_result")


def assess(row):
    migrations, publications = row["migrations"], row["publications"]
    if not migrations or not publications:
        raise ValueError("missing migration or publisher role")
    all_commands = [r["command"] for r in migrations+publications]
    if any(len(c) < 4 for c in all_commands) or len({(c[0], c[1], c[3]) for c in all_commands}) != 1:
        raise ValueError("actors changed interpreter, worker or fixture")
    for record in publications:
        audit_publication(row, record)
    for record in migrations:
        audit_migration(row, record)
    for name in ("initial", "followup_before", "followup_after"):
        audit_capture(row, row[name])
    if row["initial"]["active_epoch"] != 1 or row["initial"]["publication_witnesses"] or row["initial"]["summaries"] or row["initial"]["migration_witness"] is not None:
        raise ValueError("invalid fresh selection fixture")
    seed_full = history(row, row["initial"])
    if row["initial"]["receipts"] != sorted(seed_full, key=lambda r: (r["epoch"], r["request_id"])):
        raise ValueError("seed receipts missing before selection")
    primary = [r for r in publications if r["role"] == "inflight"]
    later = [r for r in publications if r["role"] == "later"]
    busy = primary[0]["response"]["status"] == "busy"
    stale = migrations[0]["response"]["status"] == "stale_selection"
    if ([r["attempt"] for r in primary] != list(range(1, 2+int(busy)))
            or [r["attempt"] for r in migrations] != list(range(1, 2+int(stale)))
            or len(later) != int(row["schedule"] == "publisher_first_later")
            or (later and later[0]["attempt"] != 1)):
        raise ValueError("lost or repeated attempt identity")
    pause = row["schedule"] if row["schedule"] in STAGES else "none"
    if migrations[0]["pause"] != pause or any(r["pause"] != "none" for r in migrations[1:]):
        raise ValueError("wrong live pause or repeated barrier")
    journal = []
    def note(kind, **fields):
        journal.append({"seq": len(journal), "kind": kind, **fields})
    current = row["initial"]
    def pub(record):
        nonlocal current
        if record["before"] != current:
            raise ValueError("publication before-capture rewrote a causal prefix")
        note("publication_requested", role=record["role"], attempt=record["attempt"])
        note("publication_completed", role=record["role"], attempt=record["attempt"], status=record["response"]["status"])
        note("publication_observed", role=record["role"], attempt=record["attempt"])
        current = record["after"]
    def migration(record, forced=False):
        nonlocal current
        if record["before"] != current:
            raise ValueError("migration before-capture rewrote a causal prefix")
        note("migration_requested", attempt=record["attempt"], pause=record["pause"])
        if forced:
            note("migration_paused", stage=pause)
            if pause == "after_commit":
                current = record["after"]
            pub(primary[0])
            if record["pause_capture"] != current:
                raise ValueError("pause capture changed without a writer")
            note("migration_pause_observed")
            note("migration_resumed", stage=pause)
        note("migration_completed", attempt=record["attempt"], status=record["response"]["status"])
        note("migration_observed", attempt=record["attempt"])
        current = record["after"]
    note("seeded")
    if row["schedule"] in {"publisher_first", "publisher_first_later"}:
        pub(primary[0])
        if later:
            pub(later[0])
        migration(migrations[0])
    elif pause != "none":
        migration(migrations[0], True)
        if stale:
            migration(migrations[1])
        if busy:
            pub(primary[1])
    else:
        migration(migrations[0])
        pub(primary[0])
    if row["followup_before"] != current:
        raise ValueError("final capture rewrote the last actor result")
    note("final_observed")
    note("followup_requested")
    note("followup_completed", status=row["followup_response"]["status"])
    note("followup_observed")
    if row["timeline"] != journal:
        raise ValueError("controller journal contradicts actor order")
    req = request(row)
    answer = row["followup_response"]
    if (row["followup_request"] != req or set(answer) != {"status", "epoch", "request_id", "revision", "approved_sha256"}
            or answer["epoch"] != req["epoch"] or answer["request_id"] != req["request_id"]
            or answer["status"] not in {"committed", "replayed", "conflict", "outcome_unavailable", "future_epoch"}):
        raise ValueError("follow-up identity or result shape changed")
    final = row["followup_before"]
    records = history(row, final)
    inflight = [r for r in records if r["request_id"] == "inflight"]
    if len(inflight) > 1:
        raise ValueError("runtime identity committed more than one effect")
    committed = bool(inflight)
    available = any((r["epoch"], r["request_id"]) == (req["epoch"], req["request_id"]) for r in final["receipts"]+final["summaries"])
    expected_original = reply("replayed", req, inflight[0]["revision"], inflight[0]["approved_sha256"]) if committed else reply("outcome_unavailable", req)
    replayed = committed and available and answer == expected_original
    old = req["epoch"] == 1
    denied = old and not committed and primary[-1]["response"] == reply("outcome_unavailable", req)
    publisher_expected = reply("committed", req, inflight[0]["revision"], inflight[0]["approved_sha256"]) if committed else reply("outcome_unavailable", req)
    old_records = [r for r in records if r["epoch"] == 1]
    summary_keys = {(r["epoch"], r["request_id"], r["revision"]) for r in final["summaries"]}
    missing = [r for r in old_records if (r["epoch"], r["request_id"], r["revision"]) not in summary_keys]
    gap = row["schedule"] in {"after_selection", "after_refresh"}
    witness = final["migration_witness"]
    stale_attempts = [m for m in migrations if m["response"]["status"] == "stale_selection"]
    return {
        "final_epoch_2": final["active_epoch"] == 2, "old_full_absent": not any(r["epoch"] < 2 for r in final["receipts"]),
        "coherent_final": final["state"]["approved_sha256"] in (None, final["state"]["content_sha256"]), "current_history_correct": True,
        "gap_lost_history": gap and old and committed and not available, "gap_old_committed": gap and old and committed,
        "gap_old_denied": gap and denied, "old_committed": old and committed, "old_replayed": old and replayed,
        "current_completed": not old and committed and primary[-1]["response"] == publisher_expected, "current_replayed": not old and replayed,
        "summary_rows": len(final["summaries"]), "missing_summary_rows": len(missing), "complete_summary_coverage": not missing,
        "busy_attempts": sum(r["response"]["status"] == "busy" for r in publications), "completed_pub_retry": busy and primary[-1]["response"]["status"] != "busy",
        "old_denied": denied, "stale_migrations": len(stale_attempts), "completed_migration_retry": stale and migrations[-1]["response"]["status"] == "migrated",
        "stale_untouched": sum(m["after"] == m["pause_capture"] and m["after"]["active_epoch"] == 1 and len(m["after"]["receipts"]) == 3 and m["after"]["migration_witness"] is None for m in stale_attempts),
        "prefix_original_supported": row["schedule"] in {"publisher_first", "publisher_first_later"} and replayed,
        "later_historical_supported": row["schedule"] == "publisher_first_later" and replayed and answer["revision"] == 4 and final["state"]["revision"] == 5 and final["state"]["content_utf8"] == VALUES["later"],
        "migration_first_denied": row["schedule"] == "migration_first" and denied,
        "before_commit_denied": row["schedule"] == "before_commit" and denied, "after_commit_denied": row["schedule"] == "after_commit" and denied,
        "migration_witness_present": witness is not None, "stale_commit_witness": witness is not None and (witness["selected_revision"] != witness["write_revision"] or witness["selected_count"] != witness["write_count"]),
        "publication_epochs_valid": all(w["requested_epoch"] == w["active_epoch"] for w in final["publication_witnesses"]),
        "verified_barriers": int(pause != "none"), "migration_completions": len(migrations), "publisher_completions": len(primary), "later_completions": len(later),
        "child_completions": len(migrations)+len(publications), "false_history": int(answer["status"] in {"replayed", "conflict"} and not replayed),
        "followup_no_effect": row["followup_after"] == final, "publisher_result_correct": primary[-1]["response"] == publisher_expected,
        "followup_result_correct": answer == (expected_original if committed and available else reply("outcome_unavailable", req)),
        "consistent_observations": True,
    }


def criteria(arms):
    def v(field):
        return [arms[m][field] for m in MODES]
    return {
        "current_state_and_closure": all(v(f) == [24]*4 for f in ("final_epoch_2", "old_full_absent", "coherent_final", "current_history_correct")),
        "source_gap_losses_and_publication": v("gap_lost_history") == [8,4,0,0] and v("gap_old_committed") == [8,8,0,8] and v("gap_old_denied") == [0,0,8,0],
        "actual_committed_history_replays": v("old_committed") == [14,14,6,14] and v("old_replayed") == [6,10,6,14] and v("current_replayed") == [4]*4,
        "summary_completeness": v("summary_rows") == [56,60,56,64] and v("missing_summary_rows") == [8,4,0,0] and v("complete_summary_coverage") == [16,20,24,24],
        "publisher_contention_and_refusal": v("busy_attempts") == v("completed_pub_retry") == [2,2,10,2] and v("old_denied") == [6,6,14,6],
        "validated_retry_preserves_source": v("stale_migrations") == v("completed_migration_retry") == v("stale_untouched") == [0,0,0,8],
        "ordering_and_historical_controls": v("prefix_original_supported") == [6]*4 and v("later_historical_supported") == [2]*4 and v("migration_first_denied") == v("before_commit_denied") == v("after_commit_denied") == [2]*4 and v("current_completed") == [4]*4,
        "transactional_witnesses": v("migration_witness_present") == v("publication_epochs_valid") == [24]*4 and v("stale_commit_witness") == [8,4,0,0],
        "process_and_barrier_coverage": v("verified_barriers") == [12]*4 and v("migration_completions") == [24,24,24,32] and v("publisher_completions") == [26,26,34,26] and v("later_completions") == [2]*4 and v("child_completions") == [52,52,60,60],
        "supported_evidence_and_no_unexpected_errors": v("false_history") == [0]*4 and v("followup_no_effect") == v("publisher_result_correct") == v("followup_result_correct") == v("consistent_observations") == [24]*4 and v("infrastructure_errors") == [0]*4,
    }


def summarize(records, cases):
    wanted = {(c["case_id"], m) for c in cases for m in MODES}
    if len(records) != 96 or {(r["case_id"], r["mode"]) for r in records} != wanted:
        raise ValueError("one record per declared case/mode required")
    declared = {c["case_id"]: c for c in cases}
    arms = {}
    for mode in MODES:
        rows = [r for r in records if r["mode"] == mode]
        good = []
        for row in rows:
            if any(row[k] != v for k, v in declared[row["case_id"]].items()):
                raise ValueError("raw declaration changed")
            if row["status"] == "complete":
                actual = assess(row)
                if actual != row["oracle"]:
                    raise ValueError("stored verdict differs from observations")
                good.append(actual)
            elif row["status"] != "infrastructure_error" or row["oracle"] is not None:
                raise ValueError("invalid raw status")
        arms[mode] = {"cases": len(rows), "source_gap_cases": 8, "old_intent_cases": 20, "current_cases": 4,
                      "infrastructure_errors": len(rows)-len(good), **{f: sum(g[f] for g in good) for f in FIELDS}}
    return {"arms": arms, "criteria": criteria(arms)}


def run_case(case, mode):
    if mode not in MODES:
        raise ValueError("unknown selection mode")
    row = {**case, "mode": mode, "status": "pending", "error_phase": "setup", "error_type": None, "error_detail": None,
           "initial": None, "migrations": [], "publications": [], "timeline": [], "followup_before": None,
           "followup_after": None, "followup_request": request(case), "followup_response": None, "oracle": None}
    process, consumed, drained, held = None, b"", False, None
    def note(kind, **fields):
        row["timeline"].append({"seq": len(row["timeline"]), "kind": kind, **fields})
    with tempfile.TemporaryDirectory(prefix="codeguardian-selection-") as directory:
        root = Path(directory)
        store = SelectionPublicationStore(root, mode)
        def finish(record, code, stdout, stderr, result_kind):
            record.update(returncode=code, stdout=stdout.decode() if isinstance(stdout, bytes) else stdout,
                          stderr=stderr.decode() if isinstance(stderr, bytes) else stderr)
            record["events"] = [json.loads(line) for line in record["stdout"].splitlines()]
            candidates = [e["response"] for e in record["events"] if e.get("kind") == result_kind]
            if code != 0 or record["stderr"] or len(candidates) != 1:
                raise ValueError("child did not return a complete modeled result")
            record["response"] = candidates[0]
        def execute(record, result_kind):
            try:
                child = subprocess.run(record["command"], capture_output=True, text=True, timeout=STEP_TIMEOUT)
            except subprocess.TimeoutExpired as error:
                record["stdout"] = error.stdout.decode(errors="replace") if isinstance(error.stdout, bytes) else error.stdout or ""
                record["stderr"] = error.stderr.decode(errors="replace") if isinstance(error.stderr, bytes) else error.stderr or ""
                raise
            finish(record, child.returncode, child.stdout, child.stderr, result_kind)
        def publish(role="inflight", attempt=1):
            req = request(case, role)
            record = {"role": role, "attempt": attempt, "request": req,
                      "command": [sys.executable, str(ROOT/"experiments/selection_worker.py"), "--root", str(root),
                                  "--mode", mode, "--role", "publish", "--epoch", str(req["epoch"]), "--key", req["request_id"], "--value", req["value"]],
                      "returncode": None, "stdout": "", "stderr": "", "events": [], "response": None,
                      "before": capture(store), "after": None}
            row["publications"].append(record)
            note("publication_requested", role=role, attempt=attempt)
            row["error_phase"] = "publication_"+role
            execute(record, "publication_result")
            note("publication_completed", role=role, attempt=attempt, status=record["response"]["status"])
            record["after"] = capture(store)
            note("publication_observed", role=role, attempt=attempt)
            return record["response"]
        def migration_record(pause):
            attempt = len(row["migrations"])+1
            record = {"attempt": attempt, "pause": pause,
                      "command": [sys.executable, str(ROOT/"experiments/selection_worker.py"), "--root", str(root), "--mode", mode, "--role", "migrate", "--pause", pause],
                      "returncode": None, "stdout": "", "stderr": "", "events": [], "response": None,
                      "before": capture(store), "pause_capture": None, "after": None}
            row["migrations"].append(record)
            note("migration_requested", attempt=attempt, pause=pause)
            return record
        def migration_done(record):
            note("migration_completed", attempt=record["attempt"], status=record["response"]["status"])
            record["after"] = capture(store)
            note("migration_observed", attempt=record["attempt"])
        def migrate():
            record = migration_record("none")
            row["error_phase"] = "migration_process"
            execute(record, "migration_result")
            migration_done(record)
            return record["response"]
        try:
            store.initialize(b"approved=version-a\n")
            store.publish(1, "seed-a", VALUES["ascii"].encode())
            store.publish(1, "seed-b", None)
            row["initial"] = capture(store)
            note("seeded")
            schedule = case["schedule"]
            if schedule in {"publisher_first", "publisher_first_later"}:
                publish()
                if schedule == "publisher_first_later":
                    publish("later")
                migrate()
            elif schedule in STAGES:
                held = migration_record(schedule)
                process = subprocess.Popen(held["command"], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                row["error_phase"] = "pause_barrier"
                consumed = wait_for_pause(process, schedule, STEP_TIMEOUT)
                note("migration_paused", stage=schedule)
                pub_result = publish()
                held["pause_capture"] = capture(store)
                note("migration_pause_observed")
                resume = (json.dumps({"command": "resume", "stage": schedule, "role": "migrate"})+"\n").encode()
                note("migration_resumed", stage=schedule)
                row["error_phase"] = "migration_completion"
                tail, stderr = process.communicate(input=resume, timeout=STEP_TIMEOUT)
                drained = True
                finish(held, process.returncode, consumed+tail, stderr, "migration_result")
                migration_done(held)
                if held["response"]["status"] == "stale_selection":
                    if migrate()["status"] != "migrated":
                        raise ValueError("scheduled fresh migration retry did not complete")
                if pub_result["status"] == "busy":
                    if publish(attempt=2)["status"] == "busy":
                        raise ValueError("scheduled publisher retry did not finish")
            else:
                migrate()
                publish()
            row["followup_before"] = capture(store)
            note("final_observed")
            req = row["followup_request"]
            note("followup_requested")
            row["error_phase"] = "followup"
            value = req["content_utf8"]
            row["followup_response"] = store.publish(req["epoch"], req["request_id"], None if value is None else value.encode())
            note("followup_completed", status=row["followup_response"]["status"])
            row["followup_after"] = capture(store)
            note("followup_observed")
            row["error_phase"] = "oracle"
            row["oracle"] = assess(row)
            row.update(status="complete", error_phase=None)
        except (OSError, ValueError, RuntimeError, UnicodeError, sqlite3.Error, subprocess.SubprocessError) as error:
            if isinstance(error, BarrierFailure):
                consumed = error.output
            elif isinstance(error, subprocess.TimeoutExpired) and row["error_phase"] == "pause_barrier":
                consumed = error.stdout or b""
            row.update(status="infrastructure_error", error_type=type(error).__name__, error_detail=str(error))
        finally:
            if process is not None and not drained:
                if process.poll() is None:
                    process.kill()
                tail, stderr = process.communicate(timeout=STEP_TIMEOUT)
                held.update(returncode=process.returncode, stdout=(consumed+tail).decode(errors="replace"), stderr=stderr.decode(errors="replace"))
    return row


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--base-commit", required=True)
    parser.add_argument("--freeze-commit", required=True)
    parser.add_argument("--output-dir", type=Path, default=ROOT/"experiments/results")
    args = parser.parse_args()
    if sys.version_info < (3, 11):
        raise RuntimeError("Python 3.11+ numeric SQLite metadata required")
    started = datetime.now(timezone.utc)
    cases = load_cases(args.dataset)
    records = [run_case(c, m) for c in cases for m in MODES]
    result = summarize(records, cases)
    run = started.strftime("%Y-%m-%dT%H-%M-%S-%fZ-selection-v1")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    raw = args.output_dir/(run+".jsonl")
    metadata = {"started_at_utc": started.isoformat(), "finished_at_utc": datetime.now(timezone.utc).isoformat(),
                "python_version": platform.python_version(), "sqlite_version": sqlite3.sqlite_version, "platform": platform.platform(),
                "base_commit": args.base_commit, "freeze_commit": args.freeze_commit, "command": [sys.executable, *sys.argv],
                "dataset": str(args.dataset), "dataset_sha256": hashlib.sha256(args.dataset.read_bytes()).hexdigest(),
                "source_sha256": {p: hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in SOURCES}, "results_file": raw.name, "summary": result,
                "interpretation_limit": "Fixed source-selection/publication schedules; literal source validation retries versus writer deferral; committed-history loss distinguished from never-committed refusals; no general progress, performance, network or crash claim."}
    with raw.open("x", encoding="utf-8") as handle:
        for row in records:
            handle.write(json.dumps(row, ensure_ascii=False)+"\n")
    with (args.output_dir/(run+"-summary.json")).open("x", encoding="utf-8") as handle:
        json.dump(metadata, handle, indent=2, ensure_ascii=False, sort_keys=True)
        handle.write("\n")
    print(json.dumps(result, indent=2, sort_keys=True))
    print("Saved "+run)
    return int(any(a["infrastructure_errors"] for a in result["arms"].values()))


if __name__ == "__main__":
    raise SystemExit(main())
