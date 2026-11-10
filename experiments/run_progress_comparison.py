"""Measure finite migration attempts under repeated controlled source changes."""
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
from src.progress_store import MODES, ProgressPublicationStore, publication_value, selection_scope
from src.publication_store import recover_value

SOURCES = ("src/progress_store.py", "experiments/progress_worker.py", "experiments/run_progress_comparison.py",
           "experiments/verify_progress_results.py", "tests/test_progress_store.py", "docs/PROGRESS_PROTOCOL.md",
           "src/selection_store.py", "src/compaction_store.py", "src/publication_store.py", "src/retry_store.py",
           "src/retirement_store.py", "src/overlap_store.py", "experiments/run_overlap_comparison.py")
FIELDS = ("budget_observed", "terminal_correct", "progress_boundary", "completed", "exhausted", "attempts",
          "declared_intents", "attempted_intents", "committed", "refused", "original_replays", "compact_replays",
          "full_replays", "changed_conflicts", "unavailable_pairs", "seed_replays", "seed_conflicts", "queries_inert",
          "summary_rows", "full_rows", "missing_authority", "duplicate_authority", "stale_attempts", "stale_untouched",
          "busy_attempts", "busy_retries", "busy_unchanged", "publication_results_correct", "coherent_current",
          "publication_epochs_valid", "migration_witness_complete", "barriers", "publisher_children", "child_completions",
          "false_history", "query_results_correct", "consistent_observations")
TIMEOUT = 15


def sha(text):
    return None if text is None else hashlib.sha256(text.encode()).hexdigest()


def load_cases(path):
    data = json.loads(path.read_text())
    if not isinstance(data, dict) or set(data) != {"schema_version", "cases"} or data["schema_version"] != "progress-eval-v1":
        raise ValueError("unsupported progress manifest")
    cases = data["cases"]
    expected = {(b, n, p) for b in (1, 2, 3) for n in (0, 1, 2, 4) for p in ("updates", "revocations")}
    if (not isinstance(cases, list) or len(cases) != 24
            or any(not isinstance(c, dict) or set(c) != {"case_id", "budget", "publications", "pattern"}
                   or not isinstance(c["case_id"], str) or not c["case_id"] or type(c["budget"]) is not int
                   or type(c["publications"]) is not int or not isinstance(c["pattern"], str) for c in cases)
            or len({c["case_id"] for c in cases}) != 24
            or {(c["budget"], c["publications"], c["pattern"]) for c in cases} != expected):
        raise ValueError("24 unique declared budget/publication histories required")
    return cases


def request(case, index):
    value = publication_value(case["pattern"], index)
    return {"epoch": 1, "request_id": "item-"+str(index), "content_utf8": None if value is None else value.decode()}


def response(status, req, revision=None, approval=None):
    return {"status": status, "epoch": req["epoch"], "request_id": req["request_id"], "revision": revision, "approved_sha256": approval}


def receipt(req, revision):
    return {"epoch": req["epoch"], "request_id": req["request_id"], "operation": "revoke" if req["content_utf8"] is None else "update",
            "payload_utf8": req["content_utf8"], "revision": revision, "approved_sha256": sha(req["content_utf8"])}


def compact(full):
    return {"epoch": full["epoch"], "request_id": full["request_id"], "operation": full["operation"],
            "payload_sha256": full["approved_sha256"], "revision": full["revision"]}


def capture(store):
    snap = store.inspect()
    state = snap.pop("state")
    delivered = recover_value(state)
    value = delivered.pop("content")
    snap["receipts"] = [{**{k: v for k, v in r.items() if k != "payload"},
                         "payload_utf8": None if r["payload"] is None else r["payload"].decode()} for r in snap["receipts"]]
    return {**snap, "state": {"revision": state.revision, "approved_sha256": state.approved_sha256,
                             "content_utf8": state.content.decode(), "content_sha256": sha(state.content.decode())},
            "delivery": {**delivered, "delivered_utf8": None if value is None else value.decode()}, "sqlite_settings": store.settings()}


def history(case, snap):
    intents = [{"epoch": 1, "request_id": "seed-a", "content_utf8": "approved=version-b\n"},
               {"epoch": 1, "request_id": "seed-b", "content_utf8": None}]
    keys = set()
    for revision, witness in enumerate(snap["publication_witnesses"], 4):
        key = witness["request_id"]
        expected = next((request(case, i) for i in range(1, case["publications"]+1) if key == "item-"+str(i)), None)
        if (expected is None or key in keys or set(witness) != {"revision", "requested_epoch", "active_epoch", "request_id"}
                or witness["revision"] != revision or witness["requested_epoch"] != 1 or witness["active_epoch"] not in (1, 2)):
            raise ValueError("invalid or repeated runtime publication witness")
        keys.add(key)
        intents.append(expected)
    return [receipt(req, revision) for revision, req in enumerate(intents, 2)]


def audit_snapshot(case, snap):
    records = history(case, snap)
    payload = "approved=version-a\n"
    for r in records:
        if r["payload_utf8"] is not None:
            payload = r["payload_utf8"]
    approved = records[-1]["approved_sha256"]
    state = {"revision": len(records)+1, "approved_sha256": approved, "content_utf8": payload, "content_sha256": sha(payload)}
    delivery = {"status": "blocked" if approved is None else "delivered", "reason": "approval_revoked" if approved is None else "verified_recovery",
                "revision": state["revision"], "delivered_utf8": None if approved is None else payload}
    if (set(snap) != {"state", "active_epoch", "effects", "receipts", "summaries", "summary_columns", "publication_witnesses", "migration_witness", "delivery", "sqlite_settings"}
            or snap["active_epoch"] not in (1, 2) or snap["summary_columns"] != list(SUMMARY_COLUMNS)
            or snap["effects"] != [{k: v for k, v in r.items() if k != "payload_utf8"} for r in records]
            or snap["state"] != state or snap["delivery"] != delivery
            or snap["sqlite_settings"] != {"journal_mode": "delete", "synchronous": 2, "integrity_check": "ok"}):
        raise ValueError("snapshot contradicts state/effect/delivery history")
    by_revision = {r["revision"]: r for r in records}
    for name, shorten in (("receipts", False), ("summaries", True)):
        keys = [(r["epoch"], r["request_id"]) for r in snap[name]]
        if keys != sorted(set(keys)):
            raise ValueError("duplicate or unordered authority rows")
        for r in snap[name]:
            original = by_revision.get(r["revision"])
            if original is None or r != (compact(original) if shorten else original):
                raise ValueError("authority row has no matching committed intent")
    return records


def source(snap):
    return {"active_epoch": snap["active_epoch"], "current_revision": snap["state"]["revision"],
            "receipts": [{**compact(r), "approved_sha256": r["approved_sha256"]} for r in snap["receipts"] if r["epoch"] < 2]}


def check_trace(record, events, expected_command):
    numbered = [{"seq": i, **e} for i, e in enumerate(events)]
    if (record["returncode"] != 0 or record["stderr"] or record["events"] != numbered
            or [json.loads(s) for s in record["stdout"].splitlines()] != numbered
            or record["command"] != expected_command):
        raise ValueError("child trace, role, command or normal exit differs")


def audit_publisher(row, p):
    req = request(row, p["index"])
    if req != p["request"]:
        raise ValueError("publisher changed original intent")
    before, after, answer = p["before"], p["after"], p["response"]
    audit_snapshot(row, before)
    audit_snapshot(row, after)
    events = [{"kind": "publication_started", "epoch": 1, "request_id": req["request_id"],
               "operation": "revoke" if req["content_utf8"] is None else "update", "payload_sha256": sha(req["content_utf8"])}]
    if answer["status"] == "busy":
        events.append({"kind": "writer_busy", "at": "begin_immediate", "sqlite_errorcode": 5, "sqlite_errorname": "SQLITE_BUSY", "busy_timeout_ms": 0})
        if before != after or answer != response("busy", req):
            raise ValueError("busy request changed state or claimed commitment")
    else:
        if any(r["request_id"] == req["request_id"] for r in before["receipts"]+before["summaries"]):
            raise ValueError("fresh publisher reused committed identity")
        new = before["active_epoch"] == 1
        events.append({"kind": "publication_view", "requested_epoch": 1, "observed_epoch": before["active_epoch"],
                       "current_revision": before["state"]["revision"], "receipt_kind": "none", "decision": "new" if new else "outcome_unavailable"})
        if new:
            events += [{"kind": "checkpoint", "stage": "before_commit"}, {"kind": "checkpoint", "stage": "after_commit"}]
            rev = before["state"]["revision"]+1
            witness = {"revision": rev, "requested_epoch": 1, "active_epoch": before["active_epoch"], "request_id": req["request_id"]}
            if (after["publication_witnesses"] != before["publication_witnesses"]+[witness]
                    or after["receipts"] != sorted(before["receipts"]+[receipt(req, rev)], key=lambda r: (r["epoch"], r["request_id"]))
                    or after["summaries"] != before["summaries"] or after["migration_witness"] != before["migration_witness"] or after["active_epoch"] != before["active_epoch"]):
                raise ValueError("publication transition differs from its witness/authority")
        elif before != after:
            raise ValueError("refused old request changed database")
    events += [{"kind": "publication_result", "response": answer}, {"kind": "completed"}]
    command = p["command"]
    if len(command) < 4 or not command[3]:
        raise ValueError("missing child fixture root")
    expected = [command[0], str(ROOT/"experiments/progress_worker.py"), "--root", command[3], "--mode", row["mode"],
                "--budget", str(row["budget"]), "--role", "publish", "--index", str(p["index"]), "--pattern", row["pattern"]]
    check_trace(p, events, expected)


def audit_migration(row, m):
    before, pause, after = m["before"], m["pause_capture"], m["after"]
    for snap in (before, pause, after):
        audit_snapshot(row, snap)
    if before["active_epoch"] != 1 or before["summaries"] or before["migration_witness"] is not None:
        raise ValueError("attempt started after namespace closure")
    scope = selection_scope(row["mode"], row["budget"], m["attempt"])
    if m["selection_scope"] != scope:
        raise ValueError("attempt changed its selection policy")
    binding = {"stage": "after_selection", "role": "migrate", "attempt": m["attempt"], "budget": row["budget"]}
    initial, observed = source(before), source(pause)
    matched = initial == observed
    stale = scope == "validated_selection" and not matched
    events = [{"kind": "migration_started", "target_epoch": 2},
              {"kind": "attempt_plan", "policy": row["mode"], "budget": row["budget"], "attempt": m["attempt"], "selection_scope": scope},
              {"kind": "selection", "scope": "initial", "origin": "transaction" if scope == "transactional_selection" else "read", **initial},
              {"kind": "checkpoint", "stage": "after_selection"}, {"kind": "paused", **binding}, {"kind": "resumed", **binding},
              {"kind": "selection", "scope": "final", "origin": "transaction" if scope == "transactional_selection" else "cached", **initial},
              {"kind": "checkpoint", "stage": "after_refresh"}, {"kind": "validation", "matched": matched, "observed": observed}]
    answer = {"status": "stale_selection" if stale else "migrated", "active_epoch": 1 if stale else 2, "target_epoch": 2}
    if m["response"] != answer:
        raise ValueError("migration result contradicts selection/validation")
    if stale:
        events.append({"kind": "selection_changed", "transaction_rolled_back": True})
        if after != pause:
            raise ValueError("stale attempt changed authority or namespace")
    else:
        events += [{"kind": "checkpoint", "stage": "before_commit"}, {"kind": "checkpoint", "stage": "after_commit"}]
        witness = {"target_epoch": 2, "selected_revision": initial["current_revision"], "write_revision": observed["current_revision"],
                   "selected_count": len(initial["receipts"]), "write_count": len(observed["receipts"])}
        expected = {**pause, "active_epoch": 2, "receipts": [], "summaries": [compact(r) for r in before["receipts"]], "migration_witness": witness}
        if after != expected:
            raise ValueError("migration did not atomically convert its selected source")
    events += [{"kind": "migration_result", "response": answer}, {"kind": "completed"}]
    command = m["command"]
    if len(command) < 4 or not command[3]:
        raise ValueError("missing migration fixture root")
    expected = [command[0], str(ROOT/"experiments/progress_worker.py"), "--root", command[3], "--mode", row["mode"],
                "--budget", str(row["budget"]), "--role", "migrate", "--attempt", str(m["attempt"])]
    check_trace(m, events, expected)


def assess(row):
    for snap in (row["initial"], row["stop"], row["final"], row["after_queries"]):
        audit_snapshot(row, snap)
    if row["initial"]["publication_witnesses"] or row["initial"]["active_epoch"] != 1 or len(row["initial"]["receipts"]) != 2:
        raise ValueError("fixture not in declared seed state")
    migrations, pubs = row["migrations"], row["publishers"]
    for m in migrations:
        audit_migration(row, m)
    for p in pubs:
        audit_publisher(row, p)
    timeline = []
    def note(kind, **fields):
        timeline.append({"seq": len(timeline), "kind": kind, **fields})
    note("seeded")
    current, cursor, next_index = row["initial"], 0, 1
    def use_pub(phase, during, index, attempt):
        nonlocal current, cursor
        if cursor >= len(pubs):
            raise ValueError("missing scheduled publisher")
        p = pubs[cursor]
        if (p["phase"], p["during_attempt"], p["index"], p["attempt"], p["before"]) != (phase, during, index, attempt, current):
            raise ValueError("publisher causal prefix, retry or phase changed")
        note("publication_requested", record=cursor)
        note("publication_completed", record=cursor, status=p["response"]["status"])
        current = p["after"]
        cursor += 1
        return p
    for attempt, m in enumerate(migrations, 1):
        if m["attempt"] != attempt or m["before"] != current or (attempt > 1 and migrations[attempt-2]["response"]["status"] != "stale_selection"):
            raise ValueError("migration attempt prefix or numbering changed")
        note("migration_requested", attempt=attempt)
        note("migration_paused", attempt=attempt)
        p = None
        if next_index <= row["publications"]:
            p = use_pub("during_attempt", attempt, next_index, 1)
            next_index += 1
        if current != m["pause_capture"]:
            raise ValueError("pause capture not caused by scheduled publisher")
        note("pause_observed", attempt=attempt)
        note("migration_resumed", attempt=attempt)
        note("migration_completed", attempt=attempt, status=m["response"]["status"])
        current = m["after"]
        if p is not None and p["response"]["status"] == "busy":
            retry = use_pub("after_busy", attempt, p["index"], 2)
            if retry["request"] != p["request"] or retry["response"]["status"] == "busy":
                raise ValueError("busy retry changed intent or did not terminate")
    if current != row["stop"]:
        raise ValueError("stop snapshot differs from final allowed attempt")
    note("migration_stopped", terminal=row["terminal"])
    while next_index <= row["publications"]:
        use_pub("drain", None, next_index, 1)
        next_index += 1
    if cursor != len(pubs) or current != row["final"]:
        raise ValueError("unaccounted publisher or final snapshot")
    note("final_observed")
    note("queries_completed", count=len(row["queries"]))
    if timeline != row["timeline"]:
        raise ValueError("controller causal journal changed")
    final = row["final"]
    records = history(row, final)
    by_key = {r["request_id"]: r for r in records}
    authority = {r["request_id"]: r for r in final["receipts"]+final["summaries"]}
    originals = [{"epoch": 1, "request_id": "seed-a", "content_utf8": "approved=version-b\n"},
                 {"epoch": 1, "request_id": "seed-b", "content_utf8": None}]+[request(row, i) for i in range(1, row["publications"]+1)]
    if len(row["queries"]) != len(originals):
        raise ValueError("missing exact/changed query pairs")
    full_replays = compact_replays = changed_conflicts = unavailable = seed_replays = seed_conflicts = false_history = 0
    all_query_correct = True
    for query, req in zip(row["queries"], originals):
        changed = {**req, "content_utf8": "changed-intent\n" if req["content_utf8"] is None else None}
        if query["request"] != req or query["changed_request"] != changed:
            raise ValueError("query changed the original or declared alternate intent")
        actual = by_key.get(req["request_id"])
        expected = response("outcome_unavailable", req) if actual is None else response("replayed", req, actual["revision"], actual["approved_sha256"])
        changed_expected = response("outcome_unavailable" if actual is None else "conflict", req)
        supported = actual is not None and req["request_id"] in authority
        replayed = supported and query["original_response"] == expected
        all_query_correct &= query["original_response"] == expected and query["changed_response"] == changed_expected
        false_history += int(query["original_response"]["status"] in {"replayed", "conflict"} and not replayed)
        false_history += int(query["changed_response"]["status"] == "replayed" or (actual is None and query["changed_response"]["status"] == "conflict"))
        if req["request_id"].startswith("seed-"):
            seed_replays += replayed
            seed_conflicts += query["changed_response"] == changed_expected
        elif actual is not None:
            full_replays += replayed and "payload_utf8" in authority.get(req["request_id"], {})
            compact_replays += replayed and "payload_sha256" in authority.get(req["request_id"], {})
            changed_conflicts += query["changed_response"] == changed_expected
        else:
            unavailable += query["original_response"] == expected and query["changed_response"] == changed_expected
    stale = [m for m in migrations if m["response"]["status"] == "stale_selection"]
    busy = [p for p in pubs if p["response"]["status"] == "busy"]
    committed = len(records)-2
    completed = row["terminal"]["status"] == "completed"
    expected_complete = row["mode"] != "validated_budget" or row["publications"] < row["budget"]
    expected_attempts = 1 if row["mode"] == "transactional_first" else min(row["budget"], row["publications"]+1)
    expected_terminal = {"status": "completed" if final["active_epoch"] == 2 else "budget_exhausted", "budget": row["budget"],
                         "attempts": len(migrations), "active_epoch": row["stop"]["active_epoch"]}
    witness = final["migration_witness"]
    witness_complete = (witness is None and final["active_epoch"] == 1) or (witness is not None and final["active_epoch"] == 2
                        and witness["selected_revision"] == witness["write_revision"] and witness["selected_count"] == witness["write_count"] == len(records))
    pub_correct = True
    for p in pubs:
        actual = next((r for r in history(row, p["after"]) if r["request_id"] == p["request"]["request_id"]), None)
        wanted = response("busy", p["request"]) if p["response"]["status"] == "busy" else response("outcome_unavailable", p["request"]) if actual is None else response("committed", p["request"], actual["revision"], actual["approved_sha256"])
        pub_correct &= p["response"] == wanted
    return {"budget_observed": 1 <= len(migrations) <= row["budget"], "terminal_correct": row["terminal"] == expected_terminal,
            "progress_boundary": completed == expected_complete and len(migrations) == expected_attempts,
            "completed": completed, "exhausted": row["terminal"]["status"] == "budget_exhausted", "attempts": len(migrations),
            "declared_intents": row["publications"], "attempted_intents": len({p["index"] for p in pubs}), "committed": committed,
            "refused": sum(p["response"]["status"] == "outcome_unavailable" for p in pubs), "original_replays": full_replays+compact_replays,
            "compact_replays": compact_replays, "full_replays": full_replays, "changed_conflicts": changed_conflicts, "unavailable_pairs": unavailable,
            "seed_replays": seed_replays, "seed_conflicts": seed_conflicts, "queries_inert": final == row["after_queries"],
            "summary_rows": len(final["summaries"]), "full_rows": len(final["receipts"]), "missing_authority": sum(r["request_id"] not in authority for r in records),
            "duplicate_authority": len(final["receipts"])+len(final["summaries"])-len(authority), "stale_attempts": len(stale),
            "stale_untouched": sum(m["after"] == m["pause_capture"] and m["after"]["active_epoch"] == 1 and m["after"]["migration_witness"] is None for m in stale),
            "busy_attempts": len(busy), "busy_retries": sum(p["phase"] == "after_busy" for p in pubs), "busy_unchanged": sum(p["before"] == p["after"] for p in busy),
            "publication_results_correct": pub_correct, "coherent_current": final["state"]["approved_sha256"] in (None, final["state"]["content_sha256"]),
            "publication_epochs_valid": all(w["requested_epoch"] == w["active_epoch"] for w in final["publication_witnesses"]),
            "migration_witness_complete": witness_complete, "barriers": len(migrations), "publisher_children": len(pubs), "child_completions": len(migrations)+len(pubs),
            "false_history": false_history, "query_results_correct": all_query_correct, "consistent_observations": True}


def criteria(arms):
    def v(field):
        return [arms[m][field] for m in MODES]
    return {
        "finite_budget_and_terminal": v("budget_observed") == v("terminal_correct") == [24]*3,
        "progress_boundary": v("completed") == [12,24,24] and v("exhausted") == [12,0,0] and v("progress_boundary") == [24]*3,
        "equal_publication_intents": v("declared_intents") == v("attempted_intents") == [42]*3 and v("committed") == [42,0,16] and v("refused") == [0,42,26],
        "supported_original_and_changed_replies": v("original_replays") == v("changed_conflicts") == [42,0,16] and v("unavailable_pairs") == [0,42,26] and v("seed_replays") == v("seed_conflicts") == [48]*3 and v("queries_inert") == [24]*3,
        "complete_authority_and_representation": v("summary_rows") == [32,48,64] and v("full_rows") == [58,0,0] and v("compact_replays") == [8,0,16] and v("full_replays") == [34,0,0] and v("missing_authority") == v("duplicate_authority") == [0]*3,
        "stale_attempts_are_inert": v("stale_attempts") == v("stale_untouched") == [28,0,16],
        "numeric_busy_and_same_intent_retry": v("busy_attempts") == v("busy_retries") == v("busy_unchanged") == [0,18,12],
        "current_state_and_transaction_witnesses": all(v(f) == [24]*3 for f in ("coherent_current", "publication_epochs_valid", "migration_witness_complete")),
        "complete_process_and_barrier_coverage": v("attempts") == v("barriers") == [40,24,40] and v("publisher_children") == [42,60,54] and v("child_completions") == [82,84,94],
        "supported_evidence_and_provenance": v("false_history") == v("infrastructure_errors") == [0]*3 and all(v(f) == [24]*3 for f in ("publication_results_correct", "query_results_correct", "consistent_observations"))}


def summarize(records, cases):
    expected = {(c["case_id"], m) for c in cases for m in MODES}
    if len(records) != 72 or {(r["case_id"], r["mode"]) for r in records} != expected:
        raise ValueError("one record per declared case/policy required")
    declarations = {c["case_id"]: c for c in cases}
    arms = {}
    for mode in MODES:
        rows = [r for r in records if r["mode"] == mode]
        metrics = []
        for row in rows:
            if any(row[k] != v for k, v in declarations[row["case_id"]].items()):
                raise ValueError("changed raw case declaration")
            if row["status"] == "complete":
                actual = assess(row)
                if row["oracle"] != actual:
                    raise ValueError("stored oracle differs from observations")
                metrics.append(actual)
            elif row["status"] != "infrastructure_error" or row["oracle"] is not None:
                raise ValueError("invalid raw execution status")
        arms[mode] = {"cases": len(rows), "infrastructure_errors": len(rows)-len(metrics), **{f: sum(m[f] for m in metrics) for f in FIELDS}}
    return {"arms": arms, "criteria": criteria(arms)}


def run_case(case, mode):
    selection_scope(mode, case["budget"], 1)
    row = {**case, "mode": mode, "status": "pending", "error_phase": "setup", "error_type": None, "error_detail": None,
           "initial": None, "migrations": [], "publishers": [], "timeline": [], "terminal": None, "stop": None,
           "final": None, "queries": [], "after_queries": None, "oracle": None}
    process, held, consumed, drained = None, None, b"", True
    def note(kind, **fields):
        row["timeline"].append({"seq": len(row["timeline"]), "kind": kind, **fields})
    with tempfile.TemporaryDirectory(prefix="codeguardian-progress-") as directory:
        root = Path(directory)
        store = ProgressPublicationStore(root, mode, case["budget"])
        prefix = [sys.executable, str(ROOT/"experiments/progress_worker.py"), "--root", str(root), "--mode", mode, "--budget", str(case["budget"])]
        def finish(record, code, stdout, stderr, kind):
            record.update(returncode=code, stdout=stdout.decode() if isinstance(stdout, bytes) else stdout,
                          stderr=stderr.decode() if isinstance(stderr, bytes) else stderr)
            record["events"] = [json.loads(s) for s in record["stdout"].splitlines()]
            answers = [e["response"] for e in record["events"] if e.get("kind") == kind]
            if code != 0 or record["stderr"] or len(answers) != 1:
                raise ValueError("child failed or omitted modeled result")
            record["response"] = answers[0]
        def publish(index, phase, during=None, attempt=1):
            p = {"index": index, "attempt": attempt, "phase": phase, "during_attempt": during, "request": request(case, index),
                 "command": prefix+["--role", "publish", "--index", str(index), "--pattern", case["pattern"]],
                 "before": capture(store), "after": None, "returncode": None, "stdout": "", "stderr": "", "events": [], "response": None}
            number = len(row["publishers"])
            row["publishers"].append(p)
            note("publication_requested", record=number)
            row["error_phase"] = "publisher_process"
            try:
                child = subprocess.run(p["command"], capture_output=True, timeout=TIMEOUT)
            except subprocess.TimeoutExpired as error:
                p.update(stdout=(error.stdout or b"").decode(errors="replace"), stderr=(error.stderr or b"").decode(errors="replace"))
                raise
            finish(p, child.returncode, child.stdout, child.stderr, "publication_result")
            p["after"] = capture(store)
            note("publication_completed", record=number, status=p["response"]["status"])
            return p["response"]
        try:
            store.initialize(b"approved=version-a\n")
            store.publish(1, "seed-a", b"approved=version-b\n")
            store.publish(1, "seed-b", None)
            row["initial"] = capture(store)
            note("seeded")
            next_index = 1
            for attempt in range(1, case["budget"]+1):
                held = {"attempt": attempt, "selection_scope": selection_scope(mode, case["budget"], attempt),
                        "command": prefix+["--role", "migrate", "--attempt", str(attempt)], "before": capture(store),
                        "pause_capture": None, "after": None, "returncode": None, "stdout": "", "stderr": "", "events": [], "response": None}
                row["migrations"].append(held)
                note("migration_requested", attempt=attempt)
                row["error_phase"] = "migration_start"
                process = subprocess.Popen(held["command"], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                drained, consumed = False, b""
                row["error_phase"] = "pause_barrier"
                consumed = wait_for_pause(process, "after_selection", TIMEOUT)
                binding = {"stage": "after_selection", "role": "migrate", "attempt": attempt, "budget": case["budget"]}
                if json.loads(consumed.splitlines()[-1]) != {"seq": 4, "kind": "paused", **binding}:
                    raise ValueError("pause belongs to another attempt or budget")
                note("migration_paused", attempt=attempt)
                busy_index = None
                if next_index <= case["publications"]:
                    answer = publish(next_index, "during_attempt", attempt)
                    if answer["status"] == "busy":
                        busy_index = next_index
                    next_index += 1
                held["pause_capture"] = capture(store)
                note("pause_observed", attempt=attempt)
                note("migration_resumed", attempt=attempt)
                row["error_phase"] = "migration_completion"
                tail, stderr = process.communicate(input=(json.dumps({"command": "resume", **binding})+"\n").encode(), timeout=TIMEOUT)
                drained = True
                finish(held, process.returncode, consumed+tail, stderr, "migration_result")
                held["after"] = capture(store)
                note("migration_completed", attempt=attempt, status=held["response"]["status"])
                if busy_index is not None:
                    if publish(busy_index, "after_busy", attempt, 2)["status"] == "busy":
                        raise ValueError("publisher retry remained busy after migration release")
                status = held["response"]["status"]
                if status == "migrated":
                    break
                if status != "stale_selection":
                    raise ValueError("unexpected migration terminal response")
            row["stop"] = capture(store)
            row["terminal"] = {"status": "completed" if status == "migrated" else "budget_exhausted", "budget": case["budget"],
                               "attempts": len(row["migrations"]), "active_epoch": row["stop"]["active_epoch"]}
            note("migration_stopped", terminal=row["terminal"])
            while next_index <= case["publications"]:
                publish(next_index, "drain")
                next_index += 1
            row["final"] = capture(store)
            note("final_observed")
            row["error_phase"] = "receipt_queries"
            seeds = [{"epoch": 1, "request_id": "seed-a", "content_utf8": "approved=version-b\n"},
                     {"epoch": 1, "request_id": "seed-b", "content_utf8": None}]
            for req in seeds+[request(case, i) for i in range(1, case["publications"]+1)]:
                value = req["content_utf8"]
                changed = {**req, "content_utf8": "changed-intent\n" if value is None else None}
                def query(r):
                    content = r["content_utf8"]
                    return store.publish(r["epoch"], r["request_id"], None if content is None else content.encode())
                row["queries"].append({"request": req, "changed_request": changed, "original_response": query(req), "changed_response": query(changed)})
            row["after_queries"] = capture(store)
            note("queries_completed", count=len(row["queries"]))
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
                tail, stderr = process.communicate(timeout=TIMEOUT)
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
        raise RuntimeError("Python 3.11+ numeric SQLite error metadata required")
    started = datetime.now(timezone.utc)
    cases = load_cases(args.dataset)
    records = [run_case(case, mode) for case in cases for mode in MODES]
    result = summarize(records, cases)
    run = started.strftime("%Y-%m-%dT%H-%M-%S-%fZ-progress-v1")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    raw = args.output_dir/(run+".jsonl")
    metadata = {"started_at_utc": started.isoformat(), "finished_at_utc": datetime.now(timezone.utc).isoformat(), "python_version": platform.python_version(),
                "sqlite_version": sqlite3.sqlite_version, "platform": platform.platform(), "base_commit": args.base_commit, "freeze_commit": args.freeze_commit,
                "command": [sys.executable, *sys.argv], "dataset": str(args.dataset), "dataset_sha256": hashlib.sha256(args.dataset.read_bytes()).hexdigest(),
                "source_sha256": {p: hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in SOURCES}, "results_file": raw.name, "summary": result,
                "interpretation_limit": "Finite scheduled source changes and per-invocation attempt budgets; history preservation, publication and closure counted separately; no fairness, wall-clock, crash or production claim."}
    with raw.open("x", encoding="utf-8") as handle:
        for r in records:
            handle.write(json.dumps(r, sort_keys=True)+"\n")
    with (args.output_dir/(run+"-summary.json")).open("x", encoding="utf-8") as handle:
        handle.write(json.dumps(metadata, indent=2, sort_keys=True)+"\n")
    print(json.dumps({"run": run, **result}, indent=2, sort_keys=True))
    return int(not all(result["criteria"].values()))


if __name__ == "__main__":
    raise SystemExit(main())
