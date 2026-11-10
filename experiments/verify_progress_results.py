"""Reconstruct finite migration histories using only the standard library."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
POLICIES = ("validated_budget", "transactional_first", "validated_fallback")
COLUMNS = ["epoch", "request_id", "operation", "payload_sha256", "revision"]
SOURCES = ("src/progress_store.py", "experiments/progress_worker.py", "experiments/run_progress_comparison.py",
           "experiments/verify_progress_results.py", "tests/test_progress_store.py", "docs/PROGRESS_PROTOCOL.md",
           "src/selection_store.py", "src/compaction_store.py", "src/publication_store.py", "src/retry_store.py",
           "src/retirement_store.py", "src/overlap_store.py", "experiments/run_overlap_comparison.py")
METRICS = ("budget_observed", "terminal_correct", "progress_boundary", "completed", "exhausted", "attempts",
           "declared_intents", "attempted_intents", "committed", "refused", "original_replays", "compact_replays",
           "full_replays", "changed_conflicts", "unavailable_pairs", "seed_replays", "seed_conflicts", "queries_inert",
           "summary_rows", "full_rows", "missing_authority", "duplicate_authority", "stale_attempts", "stale_untouched",
           "busy_attempts", "busy_retries", "busy_unchanged", "publication_results_correct", "coherent_current",
           "publication_epochs_valid", "migration_witness_complete", "barriers", "publisher_children", "child_completions",
           "false_history", "query_results_correct", "consistent_observations")


def digest(value):
    return None if value is None else hashlib.sha256(value.encode("utf-8")).hexdigest()


def load_manifest(path):
    document = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(document, dict) or set(document) != {"schema_version", "cases"} or document["schema_version"] != "progress-eval-v1":
        raise ValueError("wrong manifest version")
    cases = document["cases"]
    if not isinstance(cases, list) or len(cases) != 24:
        raise ValueError("24 cases required")
    seen = set()
    names = set()
    for c in cases:
        if (not isinstance(c, dict) or set(c) != {"case_id", "budget", "publications", "pattern"}
                or not isinstance(c["case_id"], str) or not c["case_id"] or c["case_id"] in names
                or type(c["budget"]) is not int or type(c["publications"]) is not int
                or not isinstance(c["pattern"], str)):
            raise ValueError("invalid case declaration or repeated ID")
        names.add(c["case_id"])
        seen.add((c["budget"], c["publications"], c["pattern"]))
    if seen != {(b, n, p) for b in range(1, 4) for n in (0, 1, 2, 4) for p in ("updates", "revocations")}:
        raise ValueError("semantic case grid changed")
    return cases


def intent(case, index):
    cycle = ("approved=version-b\n", "", "approved=안전 ✓\n")
    return {"epoch": 1, "request_id": "item-"+str(index),
            "content_utf8": None if case["pattern"] == "revocations" else cycle[(index-1) % 3]}


def originals(case):
    return [{"epoch": 1, "request_id": "seed-a", "content_utf8": "approved=version-b\n"},
            {"epoch": 1, "request_id": "seed-b", "content_utf8": None}]+[intent(case, i) for i in range(1, case["publications"]+1)]


def acknowledgment(status, req, revision=None, approval=None):
    return dict(status=status, epoch=req["epoch"], request_id=req["request_id"], revision=revision, approved_sha256=approval)


def full_receipt(req, revision):
    return dict(epoch=1, request_id=req["request_id"], operation="revoke" if req["content_utf8"] is None else "update",
                payload_utf8=req["content_utf8"], revision=revision, approved_sha256=digest(req["content_utf8"]))


def summary_receipt(full):
    return dict(epoch=full["epoch"], request_id=full["request_id"], operation=full["operation"],
                payload_sha256=full["approved_sha256"], revision=full["revision"])


def snapshot(case, value):
    schema = {"state", "active_epoch", "effects", "receipts", "summaries", "summary_columns", "publication_witnesses", "migration_witness", "delivery", "sqlite_settings"}
    if set(value) != schema or value["active_epoch"] not in (1, 2) or value["summary_columns"] != COLUMNS:
        raise ValueError("snapshot schema, namespace or compact columns changed")
    expected = {r["request_id"]: r for r in originals(case)}
    committed = originals(case)[:2]
    keys = set()
    for sequence, w in enumerate(value["publication_witnesses"], 4):
        key = w["request_id"]
        if (set(w) != {"revision", "requested_epoch", "active_epoch", "request_id"} or key not in expected or key.startswith("seed-")
                or key in keys or w["revision"] != sequence or w["requested_epoch"] != 1 or w["active_epoch"] not in (1, 2)):
            raise ValueError("unknown or duplicate commit witness")
        keys.add(key)
        committed.append(expected[key])
    receipts = [full_receipt(req, n) for n, req in enumerate(committed, 2)]
    effects = [{k: v for k, v in r.items() if k != "payload_utf8"} for r in receipts]
    current = "approved=version-a\n"
    for r in receipts:
        if r["payload_utf8"] is not None:
            current = r["payload_utf8"]
    approval = receipts[-1]["approved_sha256"]
    state = dict(revision=len(receipts)+1, approved_sha256=approval, content_utf8=current, content_sha256=digest(current))
    delivery = dict(status="blocked" if approval is None else "delivered", reason="approval_revoked" if approval is None else "verified_recovery",
                    revision=state["revision"], delivered_utf8=None if approval is None else current)
    if (value["effects"] != effects or value["state"] != state or value["delivery"] != delivery
            or value["sqlite_settings"] != dict(journal_mode="delete", synchronous=2, integrity_check="ok")):
        raise ValueError("state, effects, delivery or settings contradict commit history")
    lookup = {r["revision"]: r for r in receipts}
    for table in ("receipts", "summaries"):
        observed = value[table]
        ids = [(r["epoch"], r["request_id"]) for r in observed]
        if ids != sorted(set(ids)):
            raise ValueError("unordered or duplicate authority")
        for r in observed:
            original = lookup.get(r["revision"])
            if original is None or r != (original if table == "receipts" else summary_receipt(original)):
                raise ValueError("uncommitted or incorrectly typed receipt")
    return {r["request_id"]: r for r in receipts}


def view(value):
    rows = []
    for r in value["receipts"]:
        if r["epoch"] < 2:
            rows.append({**summary_receipt(r), "approved_sha256": r["approved_sha256"]})
    return dict(active_epoch=value["active_epoch"], current_revision=value["state"]["revision"], receipts=rows)


def expected_scope(row, number):
    locking = row["mode"] == "transactional_first" or (row["mode"] == "validated_fallback" and number == row["budget"])
    return "transactional_selection" if locking else "validated_selection"


def child_trace(row, child, role, events, options):
    command = child["command"]
    if (len(command) < 4 or len(command) % 2 or not command[0] or Path(command[1]).name != "progress_worker.py"
            or any(not isinstance(s, str) for s in command)):
        raise ValueError("invalid child executable/command")
    flags = dict(zip(command[2::2], command[3::2]))
    if len(flags) != (len(command)-2)//2 or not flags.get("--root"):
        raise ValueError("duplicate child flags or missing root")
    required = {"--root": flags["--root"], "--mode": row["mode"], "--budget": str(row["budget"]), "--role": role, **options}
    if flags != required:
        raise ValueError("child command changed the declared role, intent or attempt")
    numbered = [dict(seq=n, **event) for n, event in enumerate(events)]
    if (child["returncode"] != 0 or child["stderr"] != "" or child["events"] != numbered
            or [json.loads(line) for line in child["stdout"].splitlines()] != numbered):
        raise ValueError("incomplete normal child exit or contradictory trace")
    return flags["--root"]


def inspect_publisher(row, p):
    if type(p["index"]) is not int or not 1 <= p["index"] <= row["publications"] or p["request"] != intent(row, p["index"]):
        raise ValueError("publisher substituted identity or bytes")
    before, after, answer, req = p["before"], p["after"], p["response"], p["request"]
    snapshot(row, before)
    actual = snapshot(row, after)
    events = [dict(kind="publication_started", epoch=1, request_id=req["request_id"], operation="revoke" if req["content_utf8"] is None else "update", payload_sha256=digest(req["content_utf8"]))]
    if answer["status"] == "busy":
        events.append(dict(kind="writer_busy", at="begin_immediate", sqlite_errorcode=5, sqlite_errorname="SQLITE_BUSY", busy_timeout_ms=0))
        if before != after or answer != acknowledgment("busy", req):
            raise ValueError("busy attempted publication changed storage")
        correct = True
    else:
        if any(r["request_id"] == req["request_id"] for r in before["receipts"]+before["summaries"]):
            raise ValueError("fresh request has preexisting authority")
        open_epoch = before["active_epoch"] == 1
        events.append(dict(kind="publication_view", requested_epoch=1, observed_epoch=before["active_epoch"], current_revision=before["state"]["revision"], receipt_kind="none", decision="new" if open_epoch else "outcome_unavailable"))
        if open_epoch:
            events.extend([dict(kind="checkpoint", stage="before_commit"), dict(kind="checkpoint", stage="after_commit")])
            rev = before["state"]["revision"]+1
            witness = dict(revision=rev, requested_epoch=1, active_epoch=before["active_epoch"], request_id=req["request_id"])
            if (after["publication_witnesses"] != before["publication_witnesses"]+[witness] or after["active_epoch"] != before["active_epoch"]
                    or after["migration_witness"] != before["migration_witness"] or after["summaries"] != before["summaries"]
                    or after["receipts"] != sorted(before["receipts"]+[full_receipt(req, rev)], key=lambda r: (r["epoch"], r["request_id"]))):
                raise ValueError("publication transition lacks matching atomic receipt/witness")
        elif before != after:
            raise ValueError("closed request changed storage")
        original = actual.get(req["request_id"])
        wanted = acknowledgment("outcome_unavailable", req) if original is None else acknowledgment("committed", req, original["revision"], original["approved_sha256"])
        correct = answer == wanted
    events.extend([dict(kind="publication_result", response=answer), dict(kind="completed")])
    root = child_trace(row, p, "publish", events, {"--index": str(p["index"]), "--pattern": row["pattern"]})
    return root, correct


def inspect_migration(row, m):
    before, pause, after, number = m["before"], m["pause_capture"], m["after"], m["attempt"]
    for state in (before, pause, after):
        snapshot(row, state)
    if before["active_epoch"] != 1 or before["migration_witness"] is not None or before["summaries"]:
        raise ValueError("migration began outside open source namespace")
    scope = expected_scope(row, number)
    if m["selection_scope"] != scope:
        raise ValueError("policy plan switched selection scope")
    source, observed = view(before), view(pause)
    match = source == observed
    stale = scope == "validated_selection" and not match
    binding = dict(stage="after_selection", role="migrate", attempt=number, budget=row["budget"])
    events = [dict(kind="migration_started", target_epoch=2),
              dict(kind="attempt_plan", policy=row["mode"], budget=row["budget"], attempt=number, selection_scope=scope),
              dict(kind="selection", scope="initial", origin="transaction" if scope == "transactional_selection" else "read", **source),
              dict(kind="checkpoint", stage="after_selection"), dict(kind="paused", **binding), dict(kind="resumed", **binding),
              dict(kind="selection", scope="final", origin="transaction" if scope == "transactional_selection" else "cached", **source),
              dict(kind="checkpoint", stage="after_refresh"), dict(kind="validation", matched=match, observed=observed)]
    result = dict(status="stale_selection" if stale else "migrated", active_epoch=1 if stale else 2, target_epoch=2)
    if m["response"] != result:
        raise ValueError("migration answer contradicts observed validation")
    if stale:
        events.append(dict(kind="selection_changed", transaction_rolled_back=True))
        if after != pause:
            raise ValueError("stale validation changed storage")
    else:
        events.extend([dict(kind="checkpoint", stage="before_commit"), dict(kind="checkpoint", stage="after_commit")])
        witness = dict(target_epoch=2, selected_revision=source["current_revision"], write_revision=observed["current_revision"], selected_count=len(source["receipts"]), write_count=len(observed["receipts"]))
        wanted = {**pause, "active_epoch": 2, "receipts": [], "summaries": [summary_receipt(r) for r in before["receipts"]], "migration_witness": witness}
        if after != wanted:
            raise ValueError("migration state transition contradicts source/witness")
    events.extend([dict(kind="migration_result", response=result), dict(kind="completed")])
    root = child_trace(row, m, "migrate", events, {"--attempt": str(number)})
    return root


def evaluate(row):
    initial, stop, final, afterward = (row[k] for k in ("initial", "stop", "final", "after_queries"))
    for state in (initial, stop, final, afterward):
        snapshot(row, state)
    if initial["publication_witnesses"] or initial["active_epoch"] != 1 or len(initial["receipts"]) != 2 or initial["summaries"] or initial["migration_witness"] is not None:
        raise ValueError("wrong seeded fixture")
    migrations, pubs = row["migrations"], row["publishers"]
    roots = {inspect_migration(row, m) for m in migrations}
    pub_checks = [inspect_publisher(row, p) for p in pubs]
    roots.update(root for root, _ in pub_checks)
    if len(roots) != 1:
        raise ValueError("child attempts did not share one fixture")
    journal = []
    def append(kind, **fields):
        journal.append(dict(seq=len(journal), kind=kind, **fields))
    append("seeded")
    current, used, next_intent = initial, 0, 1
    def consume(phase, during, index, number):
        nonlocal used, current
        if used >= len(pubs):
            raise ValueError("scheduled publisher missing")
        p = pubs[used]
        if p["before"] != current or (p["phase"], p["during_attempt"], p["index"], p["attempt"]) != (phase, during, index, number):
            raise ValueError("publisher causal continuity or original retry changed")
        append("publication_requested", record=used)
        append("publication_completed", record=used, status=p["response"]["status"])
        current = p["after"]
        used += 1
        return p
    previous = None
    for number, m in enumerate(migrations, 1):
        if m["attempt"] != number or current != m["before"] or (previous is not None and previous != "stale_selection"):
            raise ValueError("invalid attempt sequence or migration prefix")
        append("migration_requested", attempt=number)
        append("migration_paused", attempt=number)
        contender = None
        if next_intent <= row["publications"]:
            contender = consume("during_attempt", number, next_intent, 1)
            next_intent += 1
        if current != m["pause_capture"]:
            raise ValueError("pause snapshot lacks its preceding publication history")
        append("pause_observed", attempt=number)
        append("migration_resumed", attempt=number)
        append("migration_completed", attempt=number, status=m["response"]["status"])
        current, previous = m["after"], m["response"]["status"]
        if contender is not None and contender["response"]["status"] == "busy":
            retry = consume("after_busy", number, contender["index"], 2)
            if retry["request"] != contender["request"] or retry["response"]["status"] == "busy":
                raise ValueError("deferred publisher retry changed intent or failed to finish")
    if current != stop:
        raise ValueError("stop snapshot changed after final budgeted attempt")
    append("migration_stopped", terminal=row["terminal"])
    while next_intent <= row["publications"]:
        consume("drain", None, next_intent, 1)
        next_intent += 1
    if used != len(pubs) or current != final:
        raise ValueError("drain lost or added a publisher")
    append("final_observed")
    append("queries_completed", count=len(row["queries"]))
    if row["timeline"] != journal:
        raise ValueError("controller causal journal inconsistent")
    committed = snapshot(row, final)
    rows = final["receipts"]+final["summaries"]
    authority = {r["request_id"]: r for r in rows}
    queries = row["queries"]
    requests = originals(row)
    if len(queries) != len(requests):
        raise ValueError("query coverage changed")
    full_count = compact_count = conflicts = absent_pairs = seed_ok = seed_changed = false = 0
    query_ok = True
    for req, q in zip(requests, queries):
        changed = {**req, "content_utf8": "changed-intent\n" if req["content_utf8"] is None else None}
        if q["request"] != req or q["changed_request"] != changed:
            raise ValueError("original or changed query identity differs")
        known = committed.get(req["request_id"])
        correct_original = acknowledgment("outcome_unavailable", req) if known is None else acknowledgment("replayed", req, known["revision"], known["approved_sha256"])
        correct_changed = acknowledgment("outcome_unavailable" if known is None else "conflict", req)
        replay = known is not None and req["request_id"] in authority and q["original_response"] == correct_original
        original_ok, changed_ok = q["original_response"] == correct_original, q["changed_response"] == correct_changed
        query_ok = query_ok and original_ok and changed_ok
        false += int(q["original_response"]["status"] in ("replayed", "conflict") and not replay)
        false += int(q["changed_response"]["status"] == "replayed" or (known is None and q["changed_response"]["status"] == "conflict"))
        if req["request_id"].startswith("seed-"):
            seed_ok += replay
            seed_changed += changed_ok
        elif known is not None:
            stored = authority.get(req["request_id"], {})
            full_count += replay and "payload_utf8" in stored
            compact_count += replay and "payload_sha256" in stored
            conflicts += changed_ok
        else:
            absent_pairs += original_ok and changed_ok
    stale = [m for m in migrations if m["response"]["status"] == "stale_selection"]
    busy = [p for p in pubs if p["response"]["status"] == "busy"]
    terminal = row["terminal"]
    completed = terminal["status"] == "completed"
    expected_count = min(row["publications"]+1, row["budget"]) if row["mode"] != "transactional_first" else 1
    target_met = final["active_epoch"] == 2
    terminal_expected = dict(status="completed" if target_met else "budget_exhausted", budget=row["budget"], attempts=len(migrations), active_epoch=stop["active_epoch"])
    witness = final["migration_witness"]
    consistent_witness = witness is None and not target_met
    if witness is not None:
        consistent_witness = target_met and witness["selected_revision"] == witness["write_revision"] and witness["selected_count"] == witness["write_count"] == len(committed)
    return dict(budget_observed=1 <= len(migrations) <= row["budget"], terminal_correct=terminal == terminal_expected,
                progress_boundary=completed == (row["mode"] != "validated_budget" or row["publications"] < row["budget"]) and len(migrations) == expected_count,
                completed=completed, exhausted=terminal["status"] == "budget_exhausted", attempts=len(migrations), declared_intents=row["publications"],
                attempted_intents=len({p["index"] for p in pubs}), committed=len(committed)-2, refused=sum(p["response"]["status"] == "outcome_unavailable" for p in pubs),
                original_replays=full_count+compact_count, compact_replays=compact_count, full_replays=full_count, changed_conflicts=conflicts, unavailable_pairs=absent_pairs,
                seed_replays=seed_ok, seed_conflicts=seed_changed, queries_inert=afterward == final, summary_rows=len(final["summaries"]), full_rows=len(final["receipts"]),
                missing_authority=sum(key not in authority for key in committed), duplicate_authority=len(rows)-len(authority), stale_attempts=len(stale),
                stale_untouched=sum(m["after"] == m["pause_capture"] and m["after"]["active_epoch"] == 1 and m["after"]["migration_witness"] is None for m in stale),
                busy_attempts=len(busy), busy_retries=sum(p["phase"] == "after_busy" for p in pubs), busy_unchanged=sum(p["before"] == p["after"] for p in busy),
                publication_results_correct=all(ok for _, ok in pub_checks), coherent_current=final["state"]["approved_sha256"] in (None, final["state"]["content_sha256"]),
                publication_epochs_valid=all(w["requested_epoch"] == w["active_epoch"] for w in final["publication_witnesses"]), migration_witness_complete=consistent_witness,
                barriers=len(migrations), publisher_children=len(pubs), child_completions=len(migrations)+len(pubs), false_history=false, query_results_correct=query_ok, consistent_observations=True)


def recount(records, cases):
    declared = {c["case_id"]: c for c in cases}
    expected = {(name, mode) for name in declared for mode in POLICIES}
    if len(records) != 72 or {(r["case_id"], r["mode"]) for r in records} != expected:
        raise ValueError("missing, duplicate or unknown case/policy record")
    arms = {}
    for mode in POLICIES:
        selected = [r for r in records if r["mode"] == mode]
        audited = []
        for row in selected:
            if any(row[k] != v for k, v in declared[row["case_id"]].items()):
                raise ValueError("raw case differs from frozen declaration")
            if row["status"] == "complete":
                metric = evaluate(row)
                if metric != row["oracle"]:
                    raise ValueError("recorded oracle differs from independent reconstruction")
                audited.append(metric)
            elif row["status"] != "infrastructure_error" or row["oracle"] is not None:
                raise ValueError("invalid execution status")
        arms[mode] = dict(cases=len(selected), infrastructure_errors=len(selected)-len(audited), **{k: sum(m[k] for m in audited) for k in METRICS})
    def counts(name):
        return [arms[m][name] for m in POLICIES]
    criteria = {
        "finite_budget_and_terminal": counts("budget_observed") == counts("terminal_correct") == [24,24,24],
        "progress_boundary": counts("progress_boundary") == [24]*3 and counts("completed") == [12,24,24] and counts("exhausted") == [12,0,0],
        "equal_publication_intents": counts("declared_intents") == counts("attempted_intents") == [42]*3 and counts("committed") == [42,0,16] and counts("refused") == [0,42,26],
        "supported_original_and_changed_replies": counts("original_replays") == counts("changed_conflicts") == [42,0,16] and counts("unavailable_pairs") == [0,42,26] and counts("seed_replays") == counts("seed_conflicts") == [48]*3 and counts("queries_inert") == [24]*3,
        "complete_authority_and_representation": counts("summary_rows") == [32,48,64] and counts("full_rows") == [58,0,0] and counts("full_replays") == [34,0,0] and counts("compact_replays") == [8,0,16] and counts("missing_authority") == counts("duplicate_authority") == [0]*3,
        "stale_attempts_are_inert": counts("stale_attempts") == counts("stale_untouched") == [28,0,16],
        "numeric_busy_and_same_intent_retry": counts("busy_attempts") == counts("busy_retries") == counts("busy_unchanged") == [0,18,12],
        "current_state_and_transaction_witnesses": all(counts(k) == [24]*3 for k in ("coherent_current", "publication_epochs_valid", "migration_witness_complete")),
        "complete_process_and_barrier_coverage": counts("attempts") == counts("barriers") == [40,24,40] and counts("publisher_children") == [42,60,54] and counts("child_completions") == [82,84,94],
        "supported_evidence_and_provenance": counts("false_history") == counts("infrastructure_errors") == [0]*3 and all(counts(k) == [24]*3 for k in ("publication_results_correct", "query_results_correct", "consistent_observations"))}
    return dict(arms=arms, criteria=criteria)


def verify(summary_path, dataset):
    metadata = json.loads(summary_path.read_text(encoding="utf-8"))
    if metadata["dataset_sha256"] != hashlib.sha256(dataset.read_bytes()).hexdigest():
        raise ValueError("manifest hash changed")
    hashes = {p: hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in SOURCES}
    if metadata["source_sha256"] != hashes:
        raise ValueError("source hash set or file bytes changed")
    if any(re.fullmatch(r"[0-9a-f]{40}", metadata[k]) is None for k in ("base_commit", "freeze_commit")):
        raise ValueError("invalid provenance commit label")
    name = metadata["results_file"]
    if Path(name).name != name or not name.endswith("-progress-v1.jsonl"):
        raise ValueError("invalid raw results filename")
    raw = summary_path.parent/name
    records = [json.loads(line) for line in raw.read_text(encoding="utf-8").splitlines()]
    actual = recount(records, load_manifest(dataset))
    if actual != metadata["summary"]:
        raise ValueError("summary differs from independently counted observations")
    return dict(verified_at_utc=datetime.now(timezone.utc).isoformat(), summary_file=summary_path.name, raw_file=name, records=len(records),
                source_hashes_checked=len(hashes), summary_sha256=hashlib.sha256(summary_path.read_bytes()).hexdigest(), raw_sha256=hashlib.sha256(raw.read_bytes()).hexdigest(),
                independent_summary=actual, all_criteria_passed=all(actual["criteria"].values()),
                scope="Independent standard-library reconstruction; finite budgets and actual committed-history denominators; trusted trace/hash inputs, not external attestation.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--summary", type=Path, required=True)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = verify(args.summary, args.dataset)
    encoded = json.dumps(report, indent=2, sort_keys=True)+"\n"
    if args.output:
        with args.output.open("x", encoding="utf-8") as handle:
            handle.write(encoded)
    print(encoded, end="")
    return int(not report["all_criteria_passed"])


if __name__ == "__main__":
    raise SystemExit(main())
