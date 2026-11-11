"""Compose process exits, source changes and recovery of one migration job."""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import platform
import selectors
import sqlite3
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from experiments.run_progress_comparison import audit_publisher, audit_snapshot, capture, compact, history, request, response, source
from src.restart_store import CUTS, MODES, RestartPublicationStore

SCHEDULES = ("quiet_control", "interference_control", *CUTS)
INTERFERENCE = {"interference_control", "after_stale", "after_accounting"}
SOURCES = ("src/restart_store.py", "experiments/restart_worker.py", "experiments/run_restart_comparison.py",
           "experiments/verify_restart_results.py", "tests/test_restart_store.py", "docs/RESTART_PROTOCOL.md",
           "src/selection_store.py", "src/compaction_store.py", "src/publication_store.py", "src/retry_store.py",
           "src/retirement_store.py", "src/overlap_store.py", "src/progress_store.py", "experiments/progress_worker.py",
           "experiments/run_progress_comparison.py", "experiments/run_overlap_comparison.py")
FIELDS = ("admissions", "within_budget", "exceeded_cases", "excess_admissions", "actual_completed", "reported_completed",
          "reported_exhausted", "false_exhausted", "false_completed", "truthful_outcome", "joint_contract", "persisted_used",
          "counter_recovery_verified", "declared_intents", "attempted_intents", "committed", "refused", "original_replays",
          "changed_conflicts", "unavailable_pairs", "seed_replays", "seed_conflicts", "queries_inert", "query_results_correct",
          "false_history", "summary_rows", "full_rows", "missing_authority", "duplicate_authority", "source_selections",
          "stale_attempts", "stale_inert", "current_coherent", "publication_epochs_valid", "migration_source_complete",
          "marked_exits", "normal_invocations", "publisher_children", "normal_child_completions", "child_processes",
          "quiet_controls_completed", "interference_controls_exhausted", "publication_results_correct", "consistent_observations")
TIMEOUT = 15
EXIT_CODE = 73


def load_cases(path):
    data = json.loads(path.read_text())
    if not isinstance(data, dict) or set(data) != {"schema_version", "cases"} or data["schema_version"] != "restart-eval-v1":
        raise ValueError("unsupported restart manifest")
    cases = data["cases"]
    if (not isinstance(cases, list) or len(cases) != 28
            or any(not isinstance(c, dict) or set(c) != {"case_id", "budget", "schedule", "pattern"}
                   or not isinstance(c["case_id"], str) or not c["case_id"] or type(c["budget"]) is not int
                   or not isinstance(c["schedule"], str) or not isinstance(c["pattern"], str) for c in cases)
            or len({c["case_id"] for c in cases}) != 28
            or {(c["budget"], c["schedule"], c["pattern"]) for c in cases} != {(b,s,p) for b in (1,2) for s in SCHEDULES for p in ("updates","revocations")}):
        raise ValueError("28 unique restart histories required")
    return cases


def arm_count(case):
    return 2 if case["schedule"] == "after_stale" else int(case["schedule"] in CUTS)


def context(row):
    return {**row, "publications": 4}


def application(snapshot):
    return {k: v for k, v in snapshot.items() if k not in {"job", "admissions"}}


def audit(row, snapshot):
    audit_snapshot(context(row), application(snapshot))
    job = snapshot["job"]
    if (set(snapshot) != set(application(snapshot))|{"job", "admissions"}
            or set(job) != {"policy", "budget", "target_epoch", "used"}
            or (job["policy"],job["budget"],job["target_epoch"]) != (row["mode"],row["budget"],2)
            or type(job["used"]) is not int or not 0 <= job["used"] <= row["budget"]):
        raise ValueError("recovered job binding/counter changed")
    for n, a in enumerate(snapshot["admissions"], 1):
        if (set(a) != {"ordinal", "generation", "attempt_number", "persisted_before", "persisted_after"}
                or a["ordinal"] != n or not 1 <= a["attempt_number"] <= row["budget"]
                or not 1 <= a["generation"] <= arm_count(row)+1 or not 0 <= a["persisted_before"] <= a["persisted_after"] <= row["budget"]):
            raise ValueError("invalid admission observer")


def check_publisher(row, p):
    if p["request"] != request(context(row), p["index"]):
        raise ValueError("publisher changed declared identity")
    translated = {**p, "before": application(p["before"]), "after": application(p["after"])}
    audit_publisher({**context(row), "mode": "validated_budget"}, translated)
    audit(row, p["before"])
    audit(row, p["after"])
    if any(p["before"][k] != p["after"][k] for k in ("job", "admissions")) or p["response"]["status"] == "busy":
        raise ValueError("publisher changed accounting or unexpectedly encountered busy")


def assess(row):
    for snapshot in (row["initial"], row["stop"], row["final"], row["after_queries"]):
        audit(row, snapshot)
    if row["initial"]["job"]["used"] or row["initial"]["admissions"] or row["initial"]["active_epoch"] != 1 or len(row["initial"]["receipts"]) != 2:
        raise ValueError("wrong initial fixture")
    pubs, invocations = row["publishers"], row["invocations"]
    for p in pubs:
        check_publisher(row, p)
    journal = []
    def note(kind, **fields):
        journal.append({"seq": len(journal), "kind": kind, **fields})
    note("seeded")
    model, pub_cursor, next_index = copy.deepcopy(row["initial"]), 0, 1
    all_stale = barriers = 0
    def consume_publisher(phase, generation, attempt):
        nonlocal model, pub_cursor, next_index
        if pub_cursor >= len(pubs):
            raise ValueError("missing publisher from declared schedule")
        p = pubs[pub_cursor]
        if (p["phase"],p["generation"],p["attempt_number"],p["index"],p["before"]) != (phase,generation,attempt,next_index,model):
            raise ValueError("publisher causal prefix or generation changed")
        note("publication_requested", record=pub_cursor)
        note("publication_completed", record=pub_cursor, status=p["response"]["status"])
        model = copy.deepcopy(p["after"])
        number = pub_cursor
        pub_cursor += 1
        next_index += 1
        return number
    terminal = None
    roots = set()
    for generation, invocation in enumerate(invocations, 1):
        cut = row["schedule"] if generation <= arm_count(row) else "none"
        if terminal is not None or invocation["generation"] != generation or invocation["cut"] != cut or invocation["before"] != model:
            raise ValueError("restart generation or invocation prefix changed")
        audit(row, invocation["before"])
        audit(row, invocation["after"])
        note("invocation_requested", generation=generation, cut=cut)
        events = []
        def event(kind, **fields):
            events.append({"seq": len(events), "kind": kind, **fields})
        class CutReached(Exception):
            pass
        def checkpoint(stage):
            event("checkpoint", stage=stage)
            if cut == stage:
                event("planned_exit", stage=stage, code=EXIT_CODE)
                raise CutReached
        event("invocation_started", policy=row["mode"], budget=row["budget"], generation=generation, cut=cut, target_epoch=2)
        memory = 0
        barrier_cursor = 0
        answer, code = None, 0
        try:
            while True:
                used = memory if row["mode"] == "volatile_budget" else model["job"]["used"]
                active = model["active_epoch"]
                event("budget_view", active_epoch=active, used=used, persisted_used=model["job"]["used"], counter_source="memory" if row["mode"] == "volatile_budget" else "durable")
                status = "budget_exhausted" if row["mode"] == "reserved_limit_first" and used >= row["budget"] else "completed" if active == 2 else "budget_exhausted" if used >= row["budget"] else None
                if status is not None:
                    answer = dict(status=status, active_epoch=active, used=used, budget=row["budget"])
                    break
                before_used = model["job"]["used"]
                if row["mode"].startswith("reserved_"):
                    model["job"]["used"] += 1
                if row["mode"] == "volatile_budget":
                    memory += 1
                admission = dict(ordinal=len(model["admissions"])+1, generation=generation, attempt_number=used+1, persisted_before=before_used, persisted_after=model["job"]["used"])
                model["admissions"].append(admission)
                event("admitted", **admission)
                checkpoint("after_admission")
                first = source(model)
                event("selection", scope="initial", origin="read", **first)
                checkpoint("after_selection")
                binding = dict(role="migrate", stage="after_selection", generation=generation, attempt_number=used+1, budget=row["budget"])
                event("paused", **binding)
                if barrier_cursor >= len(invocation["barriers"]):
                    raise ValueError("missing live barrier")
                barrier = invocation["barriers"][barrier_cursor]
                if barrier["binding"] != binding or barrier["before"] != model:
                    raise ValueError("live barrier belongs to another generation/attempt")
                note("migration_paused", **binding)
                expected_pub = consume_publisher("barrier", generation, used+1) if row["schedule"] in INTERFERENCE and next_index <= 4 else None
                if barrier["publisher_record"] != expected_pub or barrier["after"] != model or barrier["resume"] != {"command":"resume", **binding}:
                    raise ValueError("barrier publication/resume or captured source changed")
                note("migration_resumed", **binding)
                event("resumed", **binding)
                barrier_cursor += 1
                barriers += 1
                event("selection", scope="final", origin="cached", **first)
                checkpoint("after_refresh")
                observed = source(model)
                matched = first == observed
                event("validation", matched=matched, observed=observed)
                if not matched:
                    all_stale += 1
                    event("selection_changed", transaction_rolled_back=True)
                    result = dict(status="stale_selection", active_epoch=1, target_epoch=2)
                else:
                    checkpoint("before_commit")
                    model["active_epoch"] = 2
                    model["summaries"] = [compact(r) for r in model["receipts"]]
                    model["receipts"] = []
                    model["migration_witness"] = dict(target_epoch=2, selected_revision=first["current_revision"], write_revision=observed["current_revision"], selected_count=len(first["receipts"]), write_count=len(observed["receipts"]))
                    checkpoint("after_commit")
                    result = dict(status="migrated", active_epoch=2, target_epoch=2)
                event("attempt_result", response=result)
                if result["status"] == "stale_selection":
                    checkpoint("after_stale")
                if row["mode"] == "post_accounting":
                    model["job"]["used"] += 1
                accounted = memory if row["mode"] == "volatile_budget" else model["job"]["used"]
                event("accounted", used=accounted, persisted_used=model["job"]["used"])
                checkpoint("after_accounting")
                if result["status"] == "migrated":
                    answer = dict(status="completed", active_epoch=2, used=accounted, budget=row["budget"])
                    break
            event("migration_result", response=answer)
            event("completed")
        except CutReached:
            code = EXIT_CODE
        if barrier_cursor != len(invocation["barriers"]):
            raise ValueError("extra barrier not caused by a source selection")
        command = invocation["command"]
        if len(command) < 4 or not command[3]:
            raise ValueError("missing worker fixture root")
        roots.add(command[3])
        expected_command = [command[0], str(ROOT/"experiments/restart_worker.py"), "--root", command[3], "--mode", row["mode"], "--budget", str(row["budget"]), "--generation", str(generation), "--cut", cut]
        if (command != expected_command or invocation["returncode"] != code or invocation["stderr"] or invocation["response"] != answer
                or invocation["events"] != events or [json.loads(s) for s in invocation["stdout"].splitlines()] != events or invocation["after"] != model):
            raise ValueError("invocation prefix, exit, accounting, source or recovered snapshot differs")
        note("invocation_completed", generation=generation, returncode=code)
        if code == 0:
            terminal = answer
    if terminal is None or row["terminal"] != terminal or model != row["stop"] or len(roots) != 1:
        raise ValueError("missing terminal outcome or changed post-restart state")
    note("migration_stopped", terminal=terminal)
    while next_index <= 4:
        consume_publisher("drain", None, None)
    if pub_cursor != len(pubs) or model != row["final"]:
        raise ValueError("extra publisher or missing final intent")
    if any(p["command"][3] not in roots for p in pubs):
        raise ValueError("publisher escaped the migration fixture")
    note("final_observed")
    note("queries_completed", count=len(row["queries"]))
    if row["timeline"] != journal:
        raise ValueError("causal controller journal changed")
    records = history(context(row), application(model))
    commits = {r["request_id"]:r for r in records}
    authority = {r["request_id"]:r for r in model["receipts"]+model["summaries"]}
    originals = [{"epoch":1,"request_id":"seed-a","content_utf8":"approved=version-b\n"}, {"epoch":1,"request_id":"seed-b","content_utf8":None}]+[request(context(row), i) for i in range(1,5)]
    if len(row["queries"]) != 6:
        raise ValueError("six original/changed query pairs required")
    replayed = conflicts = unavailable = seeds = seed_conflicts = false_history = 0
    query_correct = True
    for req, q in zip(originals, row["queries"]):
        changed = {**req,"content_utf8":"changed-intent\n" if req["content_utf8"] is None else None}
        if q["request"] != req or q["changed_request"] != changed:
            raise ValueError("query substituted original/alternate intent")
        committed = commits.get(req["request_id"])
        wanted = response("outcome_unavailable",req) if committed is None else response("replayed",req,committed["revision"],committed["approved_sha256"])
        other = response("outcome_unavailable" if committed is None else "conflict",req)
        supported = committed is not None and req["request_id"] in authority and q["original_response"] == wanted
        query_correct &= q["original_response"] == wanted and q["changed_response"] == other
        false_history += int(q["original_response"]["status"] in {"replayed","conflict"} and not supported)
        false_history += int(q["changed_response"]["status"] == "replayed" or (committed is None and q["changed_response"]["status"] == "conflict"))
        if req["request_id"].startswith("seed-"):
            seeds += supported
            seed_conflicts += q["changed_response"] == other
        elif committed is not None:
            replayed += supported
            conflicts += q["changed_response"] == other
        else:
            unavailable += q["original_response"] == wanted and q["changed_response"] == other
    within = len(model["admissions"]) <= row["budget"]
    closed, reported = model["active_epoch"] == 2, terminal["status"] == "completed"
    truthful = closed == reported and (reported or terminal["used"] == row["budget"])
    witness = model["migration_witness"]
    source_complete = (not closed and witness is None) or (closed and witness["selected_revision"] == witness["write_revision"] and witness["selected_count"] == witness["write_count"] == len(records))
    pub_correct = True
    for p in pubs:
        known = next((r for r in history(context(row),application(p["after"])) if r["request_id"] == p["request"]["request_id"]),None)
        wanted = response("outcome_unavailable",p["request"]) if known is None else response("committed",p["request"],known["revision"],known["approved_sha256"])
        pub_correct &= p["response"] == wanted
    marked = sum(i["returncode"] == EXIT_CODE for i in invocations)
    normal = len(invocations)-marked
    return dict(admissions=len(model["admissions"]),within_budget=within,exceeded_cases=not within,excess_admissions=max(0,len(model["admissions"])-row["budget"]),
                actual_completed=closed,reported_completed=reported,reported_exhausted=not reported,false_exhausted=closed and not reported,false_completed=reported and not closed,
                truthful_outcome=truthful,joint_contract=within and truthful,persisted_used=model["job"]["used"],counter_recovery_verified=True,
                declared_intents=4,attempted_intents=len({p["index"] for p in pubs}),committed=len(records)-2,refused=sum(p["response"]["status"] == "outcome_unavailable" for p in pubs),
                original_replays=replayed,changed_conflicts=conflicts,unavailable_pairs=unavailable,seed_replays=seeds,seed_conflicts=seed_conflicts,
                queries_inert=row["after_queries"] == model,query_results_correct=query_correct,false_history=false_history,
                summary_rows=len(model["summaries"]),full_rows=len(model["receipts"]),missing_authority=sum(key not in authority for key in commits),duplicate_authority=len(model["receipts"])+len(model["summaries"])-len(authority),
                source_selections=barriers,stale_attempts=all_stale,stale_inert=all_stale,current_coherent=model["state"]["approved_sha256"] in (None,model["state"]["content_sha256"]),
                publication_epochs_valid=all(w["requested_epoch"] == w["active_epoch"] for w in model["publication_witnesses"]),migration_source_complete=source_complete,
                marked_exits=marked,normal_invocations=normal,publisher_children=len(pubs),normal_child_completions=normal+len(pubs),child_processes=len(invocations)+len(pubs),
                quiet_controls_completed=row["schedule"] == "quiet_control" and closed,interference_controls_exhausted=row["schedule"] == "interference_control" and not closed and not reported,
                publication_results_correct=pub_correct,consistent_observations=True)


def criteria(arms):
    def v(field):
        return [arms[m][field] for m in MODES]
    return {
        "complete_case_grid_and_job_binding": v("cases") == v("counter_recovery_verified") == [28]*4 and v("attempted_intents") == v("declared_intents") == [112]*4,
        "admission_bounds_and_excess": v("admissions") == [54,50,38,38] and v("exceeded_cases") == [12,8,0,0] and v("excess_admissions") == [16,12,0,0] and v("within_budget") == [16,20,28,28],
        "actual_and_reported_outcome": v("actual_completed") == [16,16,12,12] and v("reported_completed") == [16,16,10,12] and v("reported_exhausted") == [12,12,18,16] and v("false_exhausted") == [0,0,2,0] and v("false_completed") == [0]*4 and v("joint_contract") == [16,20,26,28],
        "counter_recovery_and_conservative_cost": v("persisted_used") == [0,30,38,38] and v("truthful_outcome") == [28,28,26,28] and v("quiet_controls_completed") == v("interference_controls_exhausted") == [4]*4,
        "equal_intents_and_supported_queries": v("committed") == v("original_replays") == v("changed_conflicts") == [48,48,64,64] and v("refused") == v("unavailable_pairs") == [64,64,48,48] and v("seed_replays") == v("seed_conflicts") == [56]*4 and v("queries_inert") == v("query_results_correct") == [28]*4,
        "authority_representation": v("summary_rows") == [32,32,24,24] and v("full_rows") == [72,72,96,96] and v("missing_authority") == v("duplicate_authority") == [0]*4,
        "stale_sources_and_current_history": v("stale_attempts") == v("stale_inert") == [30,26,18,18] and v("current_coherent") == v("publication_epochs_valid") == v("migration_source_complete") == [28]*4,
        "exact_exit_prefixes_and_normal_completions": v("marked_exits") == [24,24,22,22] and v("normal_invocations") == [28]*4 and v("normal_child_completions") == [140]*4,
        "barriers_processes_and_causal_order": v("source_selections") == [50,46,34,34] and v("publisher_children") == [112]*4 and v("child_processes") == [164,164,162,162] and v("consistent_observations") == [28]*4,
        "supported_evidence_and_no_unexpected_errors": v("false_history") == v("infrastructure_errors") == [0]*4 and v("publication_results_correct") == [28]*4}


def summarize(records,cases):
    expected = {(c["case_id"],m) for c in cases for m in MODES}
    if len(records) != 112 or {(r["case_id"],r["mode"]) for r in records} != expected:
        raise ValueError("112 unique case/policy records required")
    declared = {c["case_id"]:c for c in cases}
    arms = {}
    for mode in MODES:
        rows = [r for r in records if r["mode"] == mode]
        good = []
        for row in rows:
            if any(row[k] != v for k,v in declared[row["case_id"]].items()):
                raise ValueError("raw declaration changed")
            if row["status"] == "complete":
                actual = assess(row)
                if actual != row["oracle"]:
                    raise ValueError("stored oracle differs from observations")
                good.append(actual)
            elif row["status"] != "infrastructure_error" or row["oracle"] is not None:
                raise ValueError("invalid execution status")
        arms[mode] = dict(cases=len(rows),infrastructure_errors=len(rows)-len(good),**{f:sum(g[f] for g in good) for f in FIELDS})
    return dict(arms=arms,criteria=criteria(arms))


def run_case(case,mode):
    row = {**case,"mode":mode,"status":"pending","error_phase":"setup","error_type":None,"error_detail":None,
           "initial":None,"invocations":[],"publishers":[],"timeline":[],"terminal":None,"stop":None,"final":None,"queries":[],"after_queries":None,"oracle":None}
    process, active_record, output, errors = None, None, bytearray(), bytearray()
    def note(kind,**fields):
        row["timeline"].append(dict(seq=len(row["timeline"]),kind=kind,**fields))
    with tempfile.TemporaryDirectory(prefix="codeguardian-restart-") as directory:
        root = Path(directory)
        store = RestartPublicationStore(root,mode,case["budget"])
        next_index = 1
        def publish(phase,generation=None,attempt=None):
            nonlocal next_index
            p = dict(index=next_index,phase=phase,generation=generation,attempt_number=attempt,request=request(context(row),next_index),
                     command=[sys.executable,str(ROOT/"experiments/progress_worker.py"),"--root",str(root),"--mode","validated_budget","--budget",str(case["budget"]),"--role","publish","--index",str(next_index),"--pattern",case["pattern"]],
                     before=capture(store),after=None,stdout="",stderr="",returncode=None,events=[],response=None)
            number = len(row["publishers"])
            row["publishers"].append(p)
            note("publication_requested",record=number)
            row["error_phase"] = "publisher_process"
            try:
                child = subprocess.run(p["command"],capture_output=True,text=True,timeout=TIMEOUT)
            except subprocess.TimeoutExpired as error:
                p.update(stdout=(error.stdout or b"").decode(errors="replace"),stderr=(error.stderr or b"").decode(errors="replace"))
                raise
            p.update(stdout=child.stdout,stderr=child.stderr,returncode=child.returncode,events=[json.loads(s) for s in child.stdout.splitlines()])
            results = [e["response"] for e in p["events"] if e.get("kind") == "publication_result"]
            if child.returncode or child.stderr or len(results) != 1 or results[0]["status"] == "busy":
                raise ValueError("publisher failed or unexpectedly deferred")
            p["response"] = results[0]
            p["after"] = capture(store)
            note("publication_completed",record=number,status=p["response"]["status"])
            next_index += 1
            return number
        try:
            store.initialize(b"approved=version-a\n")
            store.publish(1,"seed-a",b"approved=version-b\n")
            store.publish(1,"seed-b",None)
            row["initial"] = capture(store)
            note("seeded")
            for generation in range(1,arm_count(case)+2):
                cut = case["schedule"] if generation <= arm_count(case) else "none"
                active_record = dict(generation=generation,cut=cut,command=[sys.executable,str(ROOT/"experiments/restart_worker.py"),"--root",str(root),"--mode",mode,"--budget",str(case["budget"]),"--generation",str(generation),"--cut",cut],
                                     before=capture(store),after=None,barriers=[],stdout="",stderr="",events=[],response=None,returncode=None)
                row["invocations"].append(active_record)
                note("invocation_requested",generation=generation,cut=cut)
                row["error_phase"] = "invocation_start"
                output,errors = bytearray(),bytearray()
                process = subprocess.Popen(active_record["command"],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
                pending = b""
                deadline = time.monotonic()+TIMEOUT
                row["error_phase"] = "invocation_stream"
                with selectors.DefaultSelector() as selector:
                    selector.register(process.stdout,selectors.EVENT_READ,"stdout")
                    selector.register(process.stderr,selectors.EVENT_READ,"stderr")
                    while selector.get_map():
                        remaining = deadline-time.monotonic()
                        if remaining <= 0:
                            raise subprocess.TimeoutExpired(active_record["command"],TIMEOUT)
                        ready = selector.select(remaining)
                        if not ready:
                            raise subprocess.TimeoutExpired(active_record["command"],TIMEOUT)
                        for key,_ in ready:
                            chunk = os.read(key.fileobj.fileno(),65536)
                            if not chunk:
                                selector.unregister(key.fileobj)
                                continue
                            deadline = time.monotonic()+TIMEOUT
                            if key.data == "stderr":
                                errors.extend(chunk)
                                if len(errors)>2**20:
                                    raise ValueError("stderr exceeds protocol bound")
                                continue
                            output.extend(chunk)
                            if len(output)>8*2**20:
                                raise ValueError("worker trace exceeds protocol bound")
                            pending += chunk
                            while b"\n" in pending:
                                line,pending = pending.split(b"\n",1)
                                event = json.loads(line)
                                if event.get("seq") != len(active_record["events"]):
                                    raise ValueError("worker event sequence is not continuous")
                                active_record["events"].append(event)
                                if event.get("kind") == "paused":
                                    if pending:
                                        raise ValueError("pause is not a terminal live barrier")
                                    attempt = event.get("attempt_number")
                                    binding = dict(role="migrate",stage="after_selection",generation=generation,attempt_number=attempt,budget=case["budget"])
                                    if type(attempt) is not int or not 1<=attempt<=case["budget"] or event != dict(seq=event["seq"],kind="paused",**binding):
                                        raise ValueError("wrong generation/attempt/budget pause")
                                    barrier = dict(binding=binding,before=capture(store),after=None,publisher_record=None,resume={"command":"resume",**binding})
                                    active_record["barriers"].append(barrier)
                                    note("migration_paused",**binding)
                                    if case["schedule"] in INTERFERENCE and next_index<=4:
                                        barrier["publisher_record"] = publish("barrier",generation,attempt)
                                    barrier["after"] = capture(store)
                                    note("migration_resumed",**binding)
                                    row["error_phase"] = "invocation_stream"
                                    process.stdin.write((json.dumps(barrier["resume"])+"\n").encode())
                                    process.stdin.flush()
                                    deadline = time.monotonic()+TIMEOUT
                if pending:
                    raise ValueError("unterminated worker event")
                process.wait(timeout=TIMEOUT)
                process.stdin.close()
                active_record.update(stdout=output.decode(),stderr=errors.decode(),returncode=process.returncode,after=capture(store))
                results = [e["response"] for e in active_record["events"] if e.get("kind") == "migration_result"]
                markers = [e for e in active_record["events"] if e.get("kind") == "planned_exit"]
                if process.returncode == 0 and not errors and len(results)==1 and not markers:
                    active_record["response"] = results[0]
                elif process.returncode != EXIT_CODE or errors or results or len(markers)!=1 or markers[0] != {"seq":len(active_record["events"])-1,"kind":"planned_exit","stage":cut,"code":EXIT_CODE}:
                    raise ValueError("worker exit is not the declared prefix/code")
                note("invocation_completed",generation=generation,returncode=process.returncode)
                terminal_code = process.returncode
                process.stdout.close()
                process.stderr.close()
                process = None
                if terminal_code == 0:
                    row["terminal"] = active_record["response"]
                    break
            if row["terminal"] is None:
                raise ValueError("finite restart sequence did not produce a terminal result")
            row["stop"] = capture(store)
            note("migration_stopped",terminal=row["terminal"])
            while next_index<=4:
                publish("drain")
            row["final"] = capture(store)
            note("final_observed")
            row["error_phase"] = "receipt_queries"
            originals = [{"epoch":1,"request_id":"seed-a","content_utf8":"approved=version-b\n"},{"epoch":1,"request_id":"seed-b","content_utf8":None}]+[request(context(row),i) for i in range(1,5)]
            for req in originals:
                changed = {**req,"content_utf8":"changed-intent\n" if req["content_utf8"] is None else None}
                def query(r):
                    value = r["content_utf8"]
                    return store.publish(r["epoch"],r["request_id"],None if value is None else value.encode())
                row["queries"].append(dict(request=req,changed_request=changed,original_response=query(req),changed_response=query(changed)))
            row["after_queries"] = capture(store)
            note("queries_completed",count=len(row["queries"]))
            row["error_phase"] = "oracle"
            row["oracle"] = assess(row)
            row.update(status="complete",error_phase=None)
        except (OSError,ValueError,RuntimeError,UnicodeError,TypeError,KeyError,sqlite3.Error,subprocess.SubprocessError) as error:
            row.update(status="infrastructure_error",error_type=type(error).__name__,error_detail=str(error))
        finally:
            if process is not None:
                if process.poll() is None:
                    process.kill()
                if process.stdin is not None and process.stdin.closed:
                    process.stdin = None
                tail,stderr = process.communicate(timeout=TIMEOUT)
                if active_record["returncode"] is None:
                    active_record.update(stdout=(bytes(output)+(tail or b"")).decode(errors="replace"),stderr=(bytes(errors)+(stderr or b"")).decode(errors="replace"),returncode=process.returncode)
    return row


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset",type=Path,required=True)
    parser.add_argument("--base-commit",required=True)
    parser.add_argument("--freeze-commit",required=True)
    parser.add_argument("--output-dir",type=Path,default=ROOT/"experiments/results")
    args = parser.parse_args()
    if sys.version_info<(3,11):
        raise RuntimeError("Python 3.11+ SQLite error metadata required")
    started = datetime.now(timezone.utc)
    cases = load_cases(args.dataset)
    records = [run_case(c,m) for c in cases for m in MODES]
    result = summarize(records,cases)
    run = started.strftime("%Y-%m-%dT%H-%M-%S-%fZ-restart-v1")
    args.output_dir.mkdir(parents=True,exist_ok=True)
    raw = args.output_dir/(run+".jsonl")
    metadata = dict(started_at_utc=started.isoformat(),finished_at_utc=datetime.now(timezone.utc).isoformat(),python_version=platform.python_version(),sqlite_version=sqlite3.sqlite_version,platform=platform.platform(),
                    base_commit=args.base_commit,freeze_commit=args.freeze_commit,command=[sys.executable,*sys.argv],dataset=str(args.dataset),dataset_sha256=hashlib.sha256(args.dataset.read_bytes()).hexdigest(),
                    source_sha256={p:hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in SOURCES},results_file=raw.name,summary=result,
                    interpretation_limit="Fixed restarting job; admitted-attempt budget, terminal truth, actual closure and history separated; parent/OS survive named process exits; no power-loss, fairness or many-compactor guarantee.")
    with raw.open("x",encoding="utf-8") as handle:
        for row in records:
            handle.write(json.dumps(row,sort_keys=True)+"\n")
    with (args.output_dir/(run+"-summary.json")).open("x",encoding="utf-8") as handle:
        handle.write(json.dumps(metadata,indent=2,sort_keys=True)+"\n")
    print(json.dumps(dict(run=run,**result),indent=2,sort_keys=True))
    return int(not all(result["criteria"].values()))


if __name__ == "__main__":
    raise SystemExit(main())
