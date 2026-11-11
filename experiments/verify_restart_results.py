"""Independently replay restart accounting and process evidence with stdlib."""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
POLICIES = ("volatile_budget","post_accounting","reserved_limit_first","reserved_reconcile")
CUTS = ("after_admission","after_stale","after_accounting","before_commit","after_commit")
SCHEDULES = ("quiet_control","interference_control",*CUTS)
SOURCES = ("src/restart_store.py","experiments/restart_worker.py","experiments/run_restart_comparison.py",
           "experiments/verify_restart_results.py","tests/test_restart_store.py","docs/RESTART_PROTOCOL.md",
           "src/selection_store.py","src/compaction_store.py","src/publication_store.py","src/retry_store.py",
           "src/retirement_store.py","src/overlap_store.py","src/progress_store.py","experiments/progress_worker.py",
           "experiments/run_progress_comparison.py","experiments/run_overlap_comparison.py")
METRICS = ("admissions","within_budget","exceeded_cases","excess_admissions","actual_completed","reported_completed",
           "reported_exhausted","false_exhausted","false_completed","truthful_outcome","joint_contract","persisted_used",
           "counter_recovery_verified","declared_intents","attempted_intents","committed","refused","original_replays",
           "changed_conflicts","unavailable_pairs","seed_replays","seed_conflicts","queries_inert","query_results_correct",
           "false_history","summary_rows","full_rows","missing_authority","duplicate_authority","source_selections",
           "stale_attempts","stale_inert","current_coherent","publication_epochs_valid","migration_source_complete",
           "marked_exits","normal_invocations","publisher_children","normal_child_completions","child_processes",
           "quiet_controls_completed","interference_controls_exhausted","publication_results_correct","consistent_observations")


def load_manifest(path):
    document = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(document,dict) or set(document)!={"schema_version","cases"} or document["schema_version"]!="restart-eval-v1":
        raise ValueError("unsupported restart manifest")
    cases = document["cases"]
    if not isinstance(cases,list) or len(cases)!=28:
        raise ValueError("28 declarations required")
    names,semantics = set(),set()
    for c in cases:
        if (not isinstance(c,dict) or set(c)!={"case_id","budget","schedule","pattern"} or not isinstance(c["case_id"],str)
                or not c["case_id"] or c["case_id"] in names or type(c["budget"]) is not int or not isinstance(c["schedule"],str) or not isinstance(c["pattern"],str)):
            raise ValueError("invalid or duplicate case")
        names.add(c["case_id"])
        semantics.add((c["budget"],c["schedule"],c["pattern"]))
    if semantics!={(b,s,p) for b in (1,2) for s in SCHEDULES for p in ("updates","revocations")}:
        raise ValueError("semantic grid changed")
    return cases


def digest(value):
    return None if value is None else hashlib.sha256(value.encode()).hexdigest()


def runtime_request(row,index):
    updates = ("approved=version-b\n","","approved=안전 ✓\n")
    return dict(epoch=1,request_id="item-"+str(index),content_utf8=None if row["pattern"]=="revocations" else updates[(index-1)%3])


def requests(row):
    return [dict(epoch=1,request_id="seed-a",content_utf8="approved=version-b\n"),dict(epoch=1,request_id="seed-b",content_utf8=None)]+[runtime_request(row,i) for i in range(1,5)]


def reply(status,req,revision=None,approval=None):
    return dict(status=status,epoch=1,request_id=req["request_id"],revision=revision,approved_sha256=approval)


def full(req,revision):
    return dict(epoch=1,request_id=req["request_id"],operation="revoke" if req["content_utf8"] is None else "update",payload_utf8=req["content_utf8"],revision=revision,approved_sha256=digest(req["content_utf8"]))


def short(receipt):
    return dict(epoch=receipt["epoch"],request_id=receipt["request_id"],operation=receipt["operation"],payload_sha256=receipt["approved_sha256"],revision=receipt["revision"])


def cut_count(row):
    return {"quiet_control":0,"interference_control":0,"after_stale":2}.get(row["schedule"],1)


def snapshot(row,snap):
    fields = {"state","active_epoch","effects","receipts","summaries","summary_columns","publication_witnesses","migration_witness","delivery","sqlite_settings","job","admissions"}
    job = snap["job"]
    if (set(snap)!=fields or set(job)!={"policy","budget","target_epoch","used"} or job["policy"]!=row["mode"]
            or job["budget"]!=row["budget"] or job["target_epoch"]!=2 or type(job["used"]) is not int or not 0<=job["used"]<=row["budget"]
            or snap["active_epoch"] not in (1,2) or snap["summary_columns"]!=["epoch","request_id","operation","payload_sha256","revision"]):
        raise ValueError("wrong recovered job or snapshot schema")
    known = {r["request_id"]:r for r in requests(row)}
    ordered = requests(row)[:2]
    seen = set()
    for number,w in enumerate(snap["publication_witnesses"],4):
        key = w["request_id"]
        if (set(w)!={"revision","requested_epoch","active_epoch","request_id"} or key not in known or key.startswith("seed-") or key in seen
                or w["revision"]!=number or w["requested_epoch"]!=1 or w["active_epoch"] not in (1,2)):
            raise ValueError("unknown or repeated publication witness")
        ordered.append(known[key]);seen.add(key)
    records = [full(req,n) for n,req in enumerate(ordered,2)]
    payload = "approved=version-a\n"
    for r in records:
        if r["payload_utf8"] is not None:
            payload = r["payload_utf8"]
    approval = records[-1]["approved_sha256"]
    state = dict(revision=len(records)+1,approved_sha256=approval,content_utf8=payload,content_sha256=digest(payload))
    delivery = dict(status="blocked" if approval is None else "delivered",reason="approval_revoked" if approval is None else "verified_recovery",revision=state["revision"],delivered_utf8=None if approval is None else payload)
    if (snap["state"]!=state or snap["delivery"]!=delivery or snap["effects"]!=[{k:v for k,v in r.items() if k!="payload_utf8"} for r in records]
            or snap["sqlite_settings"]!=dict(journal_mode="delete",synchronous=2,integrity_check="ok")):
        raise ValueError("current state/delivery or effects contradict committed requests")
    revisions = {r["revision"]:r for r in records}
    for table in ("receipts","summaries"):
        ids = [(r["epoch"],r["request_id"]) for r in snap[table]]
        if ids!=sorted(set(ids)):
            raise ValueError("unordered or repeated receipt authority")
        for r in snap[table]:
            original = revisions.get(r["revision"])
            if original is None or r!=(original if table=="receipts" else short(original)):
                raise ValueError("receipt does not bind an actual committed intent")
    for ordinal,a in enumerate(snap["admissions"],1):
        if (set(a)!={"ordinal","generation","attempt_number","persisted_before","persisted_after"} or a["ordinal"]!=ordinal
                or not 1<=a["generation"]<=cut_count(row)+1 or not 1<=a["attempt_number"]<=row["budget"]
                or not 0<=a["persisted_before"]<=a["persisted_after"]<=row["budget"]):
            raise ValueError("invalid admitted-attempt record")
    return {r["request_id"]:r for r in records}


def selected(snap):
    return dict(active_epoch=snap["active_epoch"],current_revision=snap["state"]["revision"],receipts=[{**short(r),"approved_sha256":r["approved_sha256"]} for r in snap["receipts"] if r["epoch"]<2])


def trace(child,filename,flags,events=None):
    command = child["command"]
    if len(command)<4 or len(command)%2 or not command[0] or Path(command[1]).name!=filename:
        raise ValueError("invalid child executable/arguments")
    options = dict(zip(command[2::2],command[3::2]))
    if len(options)!=(len(command)-2)//2 or not options.get("--root") or options!={"--root":options["--root"],**flags}:
        raise ValueError("child role, job or intent flags changed")
    actual = child["events"]
    if child["stderr"] or [json.loads(s) for s in child["stdout"].splitlines()]!=actual or any(e["seq"]!=n for n,e in enumerate(actual)):
        raise ValueError("child stderr or event/stream mismatch")
    if events is not None and actual!=[dict(seq=n,**e) for n,e in enumerate(events)]:
        raise ValueError("publisher events contradict its state transition")
    return options["--root"]


def publisher(row,p):
    req = runtime_request(row,p["index"])
    if type(p["index"]) is not int or not 1<=p["index"]<=4 or p["request"]!=req or p["returncode"]!=0:
        raise ValueError("runtime publisher identity/exit changed")
    before,after,answer = p["before"],p["after"],p["response"]
    snapshot(row,before);actual = snapshot(row,after)
    if any(before[k]!=after[k] for k in ("job","admissions")) or answer["status"]=="busy":
        raise ValueError("unexpected publisher deferral or accounting change")
    if any(r["request_id"]==req["request_id"] for r in before["receipts"]+before["summaries"]):
        raise ValueError("fresh runtime key was already committed")
    open_epoch = before["active_epoch"]==1
    events = [dict(kind="publication_started",epoch=1,request_id=req["request_id"],operation="revoke" if req["content_utf8"] is None else "update",payload_sha256=digest(req["content_utf8"])),
              dict(kind="publication_view",requested_epoch=1,observed_epoch=before["active_epoch"],current_revision=before["state"]["revision"],receipt_kind="none",decision="new" if open_epoch else "outcome_unavailable")]
    if open_epoch:
        events.extend([dict(kind="checkpoint",stage="before_commit"),dict(kind="checkpoint",stage="after_commit")])
        revision = before["state"]["revision"]+1
        w = dict(revision=revision,requested_epoch=1,active_epoch=1,request_id=req["request_id"])
        if (after["publication_witnesses"]!=before["publication_witnesses"]+[w] or after["active_epoch"]!=1 or after["summaries"]!=before["summaries"]
                or after["migration_witness"]!=before["migration_witness"] or after["receipts"]!=sorted(before["receipts"]+[full(req,revision)],key=lambda r:(r["epoch"],r["request_id"]))):
            raise ValueError("publication not atomic with effect/receipt/witness")
    elif before!=after:
        raise ValueError("closed old intent changed the database")
    events.extend([dict(kind="publication_result",response=answer),dict(kind="completed")])
    root = trace(p,"progress_worker.py",{"--mode":"validated_budget","--budget":str(row["budget"]),"--role":"publish","--index":str(p["index"]),"--pattern":row["pattern"]},events)
    known = actual.get(req["request_id"])
    wanted = reply("outcome_unavailable",req) if known is None else reply("committed",req,known["revision"],known["approved_sha256"])
    return root,answer==wanted


def evaluate(row):
    for value in (row["initial"],row["stop"],row["final"],row["after_queries"]):
        snapshot(row,value)
    initial = row["initial"]
    if initial["admissions"] or initial["job"]["used"] or initial["active_epoch"]!=1 or len(initial["receipts"])!=2 or initial["summaries"] or initial["migration_witness"] is not None:
        raise ValueError("wrong trusted initial state")
    pub_checks = [publisher(row,p) for p in row["publishers"]]
    roots = {root for root,_ in pub_checks}
    state = copy.deepcopy(initial)
    journal = []
    def note(kind,**fields):
        journal.append(dict(seq=len(journal),kind=kind,**fields))
    note("seeded")
    pub_cursor,next_id,source_count,stales = 0,1,0,0
    def consume(phase,generation,attempt):
        nonlocal state,pub_cursor,next_id
        if pub_cursor>=len(row["publishers"]):
            raise ValueError("publisher missing from causal history")
        p = row["publishers"][pub_cursor]
        if (p["index"],p["phase"],p["generation"],p["attempt_number"])!=(next_id,phase,generation,attempt) or p["before"]!=state:
            raise ValueError("publisher generation, causal prefix or original index changed")
        note("publication_requested",record=pub_cursor)
        note("publication_completed",record=pub_cursor,status=p["response"]["status"])
        state = copy.deepcopy(p["after"])
        number = pub_cursor
        pub_cursor+=1;next_id+=1
        return number
    terminal = None
    for generation,inv in enumerate(row["invocations"],1):
        armed = row["schedule"] if generation<=cut_count(row) else "none"
        if terminal is not None or inv["before"]!=state or inv["generation"]!=generation or inv["cut"]!=armed:
            raise ValueError("invalid process restart sequence or prefix")
        snapshot(row,inv["before"]);snapshot(row,inv["after"])
        root = trace(inv,"restart_worker.py",{"--mode":row["mode"],"--budget":str(row["budget"]),"--generation":str(generation),"--cut":armed})
        roots.add(root)
        note("invocation_requested",generation=generation,cut=armed)
        stream = inv["events"]
        cursor,barrier_cursor,memory = 0,0,0
        answer = None
        class Exited(Exception):
            pass
        def need(kind,**fields):
            nonlocal cursor
            expected = dict(seq=cursor,kind=kind,**fields)
            if cursor>=len(stream) or stream[cursor]!=expected:
                raise ValueError("unexpected event at "+str(cursor)+": "+kind)
            cursor+=1
        def checkpoint(stage):
            need("checkpoint",stage=stage)
            if armed==stage:
                need("planned_exit",stage=stage,code=73)
                raise Exited
        need("invocation_started",policy=row["mode"],budget=row["budget"],generation=generation,cut=armed,target_epoch=2)
        expected_code = 0
        try:
            while True:
                observed_used = memory if row["mode"]=="volatile_budget" else state["job"]["used"]
                active = state["active_epoch"]
                need("budget_view",active_epoch=active,used=observed_used,persisted_used=state["job"]["used"],counter_source="memory" if row["mode"]=="volatile_budget" else "durable")
                limit_first = row["mode"]=="reserved_limit_first" and observed_used>=row["budget"]
                if limit_first or active==2 or observed_used>=row["budget"]:
                    status = "budget_exhausted" if limit_first or active!=2 else "completed"
                    answer = dict(status=status,active_epoch=active,used=observed_used,budget=row["budget"])
                    break
                persisted = state["job"]["used"]
                if row["mode"] in ("reserved_limit_first","reserved_reconcile"):
                    state["job"]["used"]+=1
                if row["mode"]=="volatile_budget":
                    memory+=1
                admission = dict(ordinal=len(state["admissions"])+1,generation=generation,attempt_number=observed_used+1,persisted_before=persisted,persisted_after=state["job"]["used"])
                need("admitted",**admission)
                state["admissions"].append(admission)
                checkpoint("after_admission")
                chosen = selected(state)
                need("selection",scope="initial",origin="read",**chosen)
                checkpoint("after_selection")
                binding = dict(role="migrate",stage="after_selection",generation=generation,attempt_number=observed_used+1,budget=row["budget"])
                need("paused",**binding)
                if barrier_cursor>=len(inv["barriers"]):
                    raise ValueError("live pause has no captured barrier")
                barrier = inv["barriers"][barrier_cursor]
                if barrier["binding"]!=binding or barrier["before"]!=state:
                    raise ValueError("barrier binding or admission prefix changed")
                note("migration_paused",**binding)
                pub_number = consume("barrier",generation,observed_used+1) if row["schedule"] in ("interference_control","after_stale","after_accounting") and next_id<=4 else None
                resume = dict(command="resume",**binding)
                if barrier["after"]!=state or barrier["publisher_record"]!=pub_number or barrier["resume"]!=resume:
                    raise ValueError("resumed source is not caused by its publisher")
                note("migration_resumed",**binding)
                need("resumed",**binding)
                source_count+=1;barrier_cursor+=1
                need("selection",scope="final",origin="cached",**chosen)
                checkpoint("after_refresh")
                actual_source = selected(state)
                same = chosen==actual_source
                need("validation",matched=same,observed=actual_source)
                if same:
                    checkpoint("before_commit")
                    state["summaries"] = [short(r) for r in state["receipts"]]
                    state["receipts"] = []
                    state["active_epoch"] = 2
                    state["migration_witness"] = dict(target_epoch=2,selected_revision=chosen["current_revision"],write_revision=actual_source["current_revision"],selected_count=len(chosen["receipts"]),write_count=len(actual_source["receipts"]))
                    checkpoint("after_commit")
                    result = dict(status="migrated",active_epoch=2,target_epoch=2)
                else:
                    stales+=1
                    need("selection_changed",transaction_rolled_back=True)
                    result = dict(status="stale_selection",active_epoch=1,target_epoch=2)
                need("attempt_result",response=result)
                if not same:
                    checkpoint("after_stale")
                if row["mode"]=="post_accounting":
                    state["job"]["used"]+=1
                used_after = memory if row["mode"]=="volatile_budget" else state["job"]["used"]
                need("accounted",used=used_after,persisted_used=state["job"]["used"])
                checkpoint("after_accounting")
                if same:
                    answer = dict(status="completed",active_epoch=2,used=used_after,budget=row["budget"])
                    break
            need("migration_result",response=answer)
            need("completed")
        except Exited:
            expected_code = 73
        if (cursor!=len(stream) or barrier_cursor!=len(inv["barriers"]) or inv["response"]!=answer or inv["returncode"]!=expected_code or inv["after"]!=state):
            raise ValueError("exit prefix, terminal answer or recovered accounting differs")
        note("invocation_completed",generation=generation,returncode=expected_code)
        if expected_code==0:
            terminal = answer
    if terminal is None or row["terminal"]!=terminal or row["stop"]!=state or len(roots)!=1:
        raise ValueError("missing final invocation or wrong job/fixture state")
    note("migration_stopped",terminal=terminal)
    while next_id<=4:
        consume("drain",None,None)
    if pub_cursor!=len(row["publishers"]) or row["final"]!=state:
        raise ValueError("remaining intents omitted or hidden work added")
    note("final_observed")
    note("queries_completed",count=len(row["queries"]))
    if row["timeline"]!=journal:
        raise ValueError("causal journal differs")
    committed = snapshot(row,state)
    authority = {r["request_id"]:r for r in state["receipts"]+state["summaries"]}
    if len(row["queries"])!=6:
        raise ValueError("all six original/changed pairs required")
    replayed=conflicts=unavailable=seed_replies=seed_changes=false=0
    query_ok = True
    for req,q in zip(requests(row),row["queries"]):
        changed = {**req,"content_utf8":"changed-intent\n" if req["content_utf8"] is None else None}
        if q["request"]!=req or q["changed_request"]!=changed:
            raise ValueError("query changed original or alternate intent")
        known = committed.get(req["request_id"])
        original_reply = reply("outcome_unavailable",req) if known is None else reply("replayed",req,known["revision"],known["approved_sha256"])
        changed_reply = reply("outcome_unavailable" if known is None else "conflict",req)
        support = known is not None and req["request_id"] in authority and q["original_response"]==original_reply
        original_ok,changed_ok = q["original_response"]==original_reply,q["changed_response"]==changed_reply
        query_ok = query_ok and original_ok and changed_ok
        false += int(q["original_response"]["status"] in ("replayed","conflict") and not support)
        false += int(q["changed_response"]["status"]=="replayed" or (known is None and q["changed_response"]["status"]=="conflict"))
        if req["request_id"].startswith("seed-"):
            seed_replies+=support;seed_changes+=changed_ok
        elif known is not None:
            replayed+=support;conflicts+=changed_ok
        else:
            unavailable+=original_ok and changed_ok
    count = len(state["admissions"])
    bounded = count<=row["budget"]
    closed = state["active_epoch"]==2
    complete_reply = terminal["status"]=="completed"
    truthful = closed==complete_reply and (complete_reply or terminal["used"]==row["budget"])
    witness = state["migration_witness"]
    witness_ok = witness is None and not closed
    if witness is not None:
        witness_ok = closed and witness["selected_revision"]==witness["write_revision"] and witness["selected_count"]==witness["write_count"]==len(committed)
    marked = sum(inv["returncode"]==73 for inv in row["invocations"])
    normal = len(row["invocations"])-marked
    return dict(admissions=count,within_budget=bounded,exceeded_cases=not bounded,excess_admissions=max(0,count-row["budget"]),actual_completed=closed,
                reported_completed=complete_reply,reported_exhausted=not complete_reply,false_exhausted=closed and not complete_reply,false_completed=complete_reply and not closed,
                truthful_outcome=truthful,joint_contract=bounded and truthful,persisted_used=state["job"]["used"],counter_recovery_verified=True,
                declared_intents=4,attempted_intents=len({p["index"] for p in row["publishers"]}),committed=len(committed)-2,refused=sum(p["response"]["status"]=="outcome_unavailable" for p in row["publishers"]),
                original_replays=replayed,changed_conflicts=conflicts,unavailable_pairs=unavailable,seed_replays=seed_replies,seed_conflicts=seed_changes,
                queries_inert=row["after_queries"]==state,query_results_correct=query_ok,false_history=false,summary_rows=len(state["summaries"]),full_rows=len(state["receipts"]),
                missing_authority=sum(key not in authority for key in committed),duplicate_authority=len(state["receipts"])+len(state["summaries"])-len(authority),source_selections=source_count,
                stale_attempts=stales,stale_inert=stales,current_coherent=state["state"]["approved_sha256"] in (None,state["state"]["content_sha256"]),
                publication_epochs_valid=all(w["requested_epoch"]==w["active_epoch"] for w in state["publication_witnesses"]),migration_source_complete=witness_ok,
                marked_exits=marked,normal_invocations=normal,publisher_children=len(row["publishers"]),normal_child_completions=normal+len(row["publishers"]),child_processes=len(row["invocations"])+len(row["publishers"]),
                quiet_controls_completed=row["schedule"]=="quiet_control" and closed,interference_controls_exhausted=row["schedule"]=="interference_control" and not closed and not complete_reply,
                publication_results_correct=all(ok for _,ok in pub_checks),consistent_observations=True)


def recount(records,cases):
    declared = {c["case_id"]:c for c in cases}
    if len(records)!=112 or {(r["case_id"],r["mode"]) for r in records}!={(name,policy) for name in declared for policy in POLICIES}:
        raise ValueError("one record per declared case/policy required")
    arms = {}
    for policy in POLICIES:
        selected_rows = [r for r in records if r["mode"]==policy]
        audited = []
        for r in selected_rows:
            if any(r[k]!=v for k,v in declared[r["case_id"]].items()):
                raise ValueError("raw declaration differs from manifest")
            if r["status"]=="complete":
                metric = evaluate(r)
                if metric!=r["oracle"]:
                    raise ValueError("stored oracle differs from independent event replay")
                audited.append(metric)
            elif r["status"]!="infrastructure_error" or r["oracle"] is not None:
                raise ValueError("invalid execution status")
        arms[policy] = dict(cases=len(selected_rows),infrastructure_errors=len(selected_rows)-len(audited),**{field:sum(m[field] for m in audited) for field in METRICS})
    def matches(field,expected):
        return [arms[p][field] for p in POLICIES]==expected
    def all_match(mapping):
        return all(matches(k,v) for k,v in mapping.items())
    criteria = {
        "complete_case_grid_and_job_binding": all_match({"cases":[28]*4,"counter_recovery_verified":[28]*4,"attempted_intents":[112]*4,"declared_intents":[112]*4}),
        "admission_bounds_and_excess": all_match({"admissions":[54,50,38,38],"exceeded_cases":[12,8,0,0],"excess_admissions":[16,12,0,0],"within_budget":[16,20,28,28]}),
        "actual_and_reported_outcome": all_match({"actual_completed":[16,16,12,12],"reported_completed":[16,16,10,12],"reported_exhausted":[12,12,18,16],"false_exhausted":[0,0,2,0],"false_completed":[0]*4,"joint_contract":[16,20,26,28]}),
        "counter_recovery_and_conservative_cost": all_match({"persisted_used":[0,30,38,38],"truthful_outcome":[28,28,26,28],"quiet_controls_completed":[4]*4,"interference_controls_exhausted":[4]*4}),
        "equal_intents_and_supported_queries": all_match({"committed":[48,48,64,64],"original_replays":[48,48,64,64],"changed_conflicts":[48,48,64,64],"refused":[64,64,48,48],"unavailable_pairs":[64,64,48,48],"seed_replays":[56]*4,"seed_conflicts":[56]*4,"queries_inert":[28]*4,"query_results_correct":[28]*4}),
        "authority_representation": all_match({"summary_rows":[32,32,24,24],"full_rows":[72,72,96,96],"missing_authority":[0]*4,"duplicate_authority":[0]*4}),
        "stale_sources_and_current_history": all_match({"stale_attempts":[30,26,18,18],"stale_inert":[30,26,18,18],"current_coherent":[28]*4,"publication_epochs_valid":[28]*4,"migration_source_complete":[28]*4}),
        "exact_exit_prefixes_and_normal_completions": all_match({"marked_exits":[24,24,22,22],"normal_invocations":[28]*4,"normal_child_completions":[140]*4}),
        "barriers_processes_and_causal_order": all_match({"source_selections":[50,46,34,34],"publisher_children":[112]*4,"child_processes":[164,164,162,162],"consistent_observations":[28]*4}),
        "supported_evidence_and_no_unexpected_errors": all_match({"false_history":[0]*4,"infrastructure_errors":[0]*4,"publication_results_correct":[28]*4})}
    return dict(arms=arms,criteria=criteria)


def verify(summary_path,dataset):
    metadata = json.loads(summary_path.read_text(encoding="utf-8"))
    if metadata["dataset_sha256"]!=hashlib.sha256(dataset.read_bytes()).hexdigest():
        raise ValueError("manifest hash changed")
    hashes = {p:hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in SOURCES}
    if metadata["source_sha256"]!=hashes:
        raise ValueError("source bytes or hash set changed")
    if any(re.fullmatch(r"[0-9a-f]{40}",metadata[k]) is None for k in ("base_commit","freeze_commit")):
        raise ValueError("invalid commit label")
    filename = metadata["results_file"]
    if Path(filename).name!=filename or not filename.endswith("-restart-v1.jsonl"):
        raise ValueError("invalid raw results filename")
    raw = summary_path.parent/filename
    records = [json.loads(s) for s in raw.read_text(encoding="utf-8").splitlines()]
    actual = recount(records,load_manifest(dataset))
    if actual!=metadata["summary"]:
        raise ValueError("summary counters differ from independent reconstruction")
    return dict(verified_at_utc=datetime.now(timezone.utc).isoformat(),summary_file=summary_path.name,raw_file=filename,records=len(records),source_hashes_checked=len(hashes),
                summary_sha256=hashlib.sha256(summary_path.read_bytes()).hexdigest(),raw_sha256=hashlib.sha256(raw.read_bytes()).hexdigest(),independent_summary=actual,
                all_criteria_passed=all(actual["criteria"].values()),scope="Independent stdlib event replay; admission bounds and terminal truth separated from actual closure and history; trusted evidence inputs, not external attestation.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--summary",type=Path,required=True)
    parser.add_argument("--dataset",type=Path,required=True)
    parser.add_argument("--output",type=Path)
    args = parser.parse_args()
    report = verify(args.summary,args.dataset)
    encoded = json.dumps(report,indent=2,sort_keys=True)+"\n"
    if args.output:
        with args.output.open("x",encoding="utf-8") as handle:
            handle.write(encoded)
    print(encoded,end="")
    return int(not report["all_criteria_passed"])


if __name__ == "__main__":
    raise SystemExit(main())
