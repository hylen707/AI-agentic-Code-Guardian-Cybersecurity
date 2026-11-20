"""Frozen recovery-request histories, committed outcomes and original-result probes."""
from __future__ import annotations

import argparse
import copy
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))
from experiments.run_resume_comparison import Peer as BoundPeer,snapshot
from src.reclamation.store import pair
from src.recovery_requests.store import MODES,RecoveryRequestStore

DATASET=ROOT/'experiments/tasks/request-eval-v1/tasks.json'
PROTOCOL='docs/REQUEST_PROTOCOL.md'
SOURCES=tuple(sorted(str(p.relative_to(ROOT)) for p in (ROOT/'src').glob('*.py'))) + (
    'src/reclamation/store.py','src/recovery_requests/store.py','experiments/run_resume_comparison.py','experiments/resume_worker.py',
    'experiments/request_worker.py','experiments/run_request_comparison.py','experiments/verify_request_results.py','tests/test_requests.py',PROTOCOL)


def same(a,b):return json.dumps(a,sort_keys=True,ensure_ascii=False)==json.dumps(b,sort_keys=True,ensure_ascii=False)


def load_cases(path=DATASET):
    doc=json.loads(Path(path).read_text());cases=doc.get('cases',[])
    if doc.get('schema_version')!='request-eval-v1' or len(cases)!=24 or len({c['case_id'] for c in cases})!=24:raise ValueError('24 unique frozen cases required')
    return cases


class Peer(BoundPeer):
    def __init__(self,root,mode,action):
        self.generation=action['generation']
        self.command=[sys.executable,str(ROOT/'experiments/request_worker.py'),'--root',str(root),'--mode',mode,'--generation',str(self.generation),
                      '--request',json.dumps(action['request'],ensure_ascii=False),'--pauses',','.join(action['pauses'])]
        self.process=subprocess.Popen(self.command,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,bufsize=0)
        self.buffer=b'';self.pause=None;self.terminal=False


def originals(state):
    first={}
    for decision in state['decisions']:
        first.setdefault(decision['request_id'],{k:decision[k] for k in ('request_id','expected_token','owner')})
    return list(first.values())


def authority(state):return {k:v for k,v in state.items() if k not in ('decisions','recovery_receipts','request_mode')}


def parent_query(store,request):
    events=[]
    def event(kind,**fields):events.append(copy.deepcopy(dict(seq=len(events),kind=kind,**fields)))
    event('query_started',mode=store.request_mode,request=request)
    before=snapshot(store)
    answer=store.replace_once(request,checkpoint=lambda stage:event('checkpoint',stage=stage),event=event)
    event('caller_result',response=answer);event('query_completed')
    return dict(request=request,before=before,events=events,response=answer,after=snapshot(store))


def run_case(case,mode):
    row={**copy.deepcopy(case),'mode':mode,'status':'infrastructure_error','steps':[],'probes':[],'publication_queries':[],'measures':None}
    peers={};phase='fixture'
    try:
        with tempfile.TemporaryDirectory(prefix='codeguardian-requests-') as directory:
            store=RecoveryRequestStore(Path(directory)/'store',mode);store.initialize(b'approved=version-a\n')
            for req in case['seeds']:store.publish_once(1,req['request_id'],None if req['content_utf8'] is None else req['content_utf8'].encode())
            row['initial']=snapshot(store)
            for action in case['steps']:
                phase=action['op'];step=dict(action=copy.deepcopy(action))
                if phase=='start':
                    peer=Peer(store.root,mode,action);peers[action['generation']]=peer;step['command']=peer.command;step.update(peer.boundary())
                elif phase=='resume':
                    peer=peers[action['generation']];step['command']=peer.resume(action);step.update(peer.boundary())
                elif phase=='migrate':
                    step['lease']=pair(snapshot(store)['lease']);step['response']=store.migrate_once(step['lease'])
                else:raise ValueError('unknown frozen action')
                step['snapshot']=snapshot(store);row['steps'].append(step)
            row['settled']=snapshot(store);known=originals(row['settled'])
            phase='probes'
            for stage in ('before_close','after_close'):
                for original in known:
                    changed={**original,'owner':original['owner']+1}
                    for kind,request in (('original',original),('changed',changed)):
                        row['probes'].append(dict(stage=stage,kind=kind,**parent_query(store,request)))
                if stage=='before_close':
                    lease=pair(snapshot(store)['lease']);answer=store.migrate_once(lease)
                    row['closure']=dict(lease=lease,response=answer,snapshot=snapshot(store))
            row['final']=snapshot(store)
            for request in case['seeds']:
                value=None if request['content_utf8'] is None else request['content_utf8'].encode()
                changed=None if value is not None else b'changed=publication\n'
                row['publication_queries'].append(dict(request=request,original=store.publish_once(1,request['request_id'],value),changed=store.publish_once(1,request['request_id'],changed)))
            row['after_publication_queries']=snapshot(store);row['status']='complete';row['measures']=measure(row)
    except Exception as error:row.update(error_phase=phase,error_type=type(error).__name__,error_detail=str(error))
    finally:
        for peer in peers.values():peer.close()
    return row


def canonical(state):
    result={}
    for decision in state['decisions']:result.setdefault(decision['request_id'],decision)
    return result


def verdict(request,answer,state):
    if answer.get('status')=='busy':return 'busy'
    original=canonical(state).get(request['request_id'])
    if original is None:return 'unsupported'
    matching=all(same(request[k],original[k]) for k in ('request_id','expected_token','owner'))
    if not matching:return 'correct_conflict' if same(answer,dict(status='request_conflict',request_id=request['request_id'])) else 'identity_failure'
    if answer.get('status') in ('observed','recorded','replayed') and same(answer.get('outcome'),original['outcome']) and answer.get('request_id')==request['request_id']:return 'correct_original'
    if answer.get('status') in ('recorded','replayed'):return 'false_history'
    return 'unresolved_original'


def expected_answer(events,request,mode):
    if any(e['kind']=='writer_busy' for e in events):return dict(status='busy',request_id=request['request_id'],sqlite_errorcode=5)
    if mode!='current_only':
        receipt=None
        for event in events:
            if event['kind'] in ('receipt_lookup','receipt_resolution') and event.get('receipt') is not None:receipt=event['receipt']
            if event['kind']=='receipt_committed':return dict(status='recorded',request_id=request['request_id'],outcome=event['receipt']['outcome'])
        if receipt is not None:
            if any(not same(request[k],receipt[k]) for k in ('request_id','expected_token','owner')):return dict(status='request_conflict',request_id=request['request_id'])
            return dict(status='replayed',request_id=request['request_id'],outcome=receipt['outcome'])
    decision=next(e for e in reversed(events) if e['kind']=='decision_committed')
    return dict(status='observed' if mode=='current_only' else 'recorded',request_id=request['request_id'],outcome=decision['outcome'])


def measure(row):
    counts=dict(lifetime_grants=len(row['final']['grants']),distinct_requests=len(canonical(row['final'])),unjustified_grants=0,
                correct_original_queries=0,original_queries=0,correct_changed_queries=0,changed_queries=0,false_history=0,
                unresolved_originals=0,identity_failures=0,busy=0,caller_errors=0,transport_response_errors=0,
                query_authority_changes=0,planned_exits=0,normal_children=0,barriers=0,actual_completed=row['final']['active_epoch']==2,
                publication_replays=0,publication_conflicts=0,publication_failures=0,publication_queries_inert=same(row['final'],row['after_publication_queries']))
    first=canonical(row['final'])
    for decision in row['final']['decisions']:
        if decision['effect_token'] is not None and decision['ordinal']!=first[decision['request_id']]['ordinal']:counts['unjustified_grants']+=1
    traces={}
    for step in row['steps']:
        if step['action']['op']=='migrate':continue
        if step['action']['op']=='start':request=step['action']['request']
        else:request=next(s['action']['request'] for s in row['steps'] if s['action']['op']=='start' and s['action']['generation']==step['action']['generation'])
        generation=step['action']['generation'];prefix=traces.setdefault(generation,[])
        for event in step['events']:
            prefix.append(event)
            kind=event['kind'];counts['barriers']+=kind=='paused';counts['caller_errors']+=kind=='caller_error'
            if kind=='caller_result':
                counts['transport_response_errors']+=not same(event['response'],expected_answer(prefix,request,row['mode']))
                outcome=verdict(request,event['response'],step['snapshot'])
                if outcome in ('false_history','unresolved_original','identity_failure','busy'):counts[{'false_history':'false_history','unresolved_original':'unresolved_originals','identity_failure':'identity_failures','busy':'busy'}[outcome]]+=1
                elif outcome=='unsupported':counts['transport_response_errors']+=1
        counts['planned_exits']+=step['returncode']==73;counts['normal_children']+=step['returncode']==0
    for probe in row['probes']:
        counts['transport_response_errors']+=not same(probe['response'],expected_answer(probe['events'],probe['request'],row['mode']))
        outcome=verdict(probe['request'],probe['response'],probe['after'])
        if probe['kind']=='original':counts['original_queries']+=1;counts['correct_original_queries']+=outcome=='correct_original'
        else:counts['changed_queries']+=1;counts['correct_changed_queries']+=outcome=='correct_conflict'
        if outcome in ('false_history','unresolved_original','identity_failure','busy'):counts[{'false_history':'false_history','unresolved_original':'unresolved_originals','identity_failure':'identity_failures','busy':'busy'}[outcome]]+=1
        elif outcome=='unsupported':counts['transport_response_errors']+=1
        counts['query_authority_changes']+=not same(authority(probe['before']),authority(probe['after']))
    effects={r['request_id']:r for r in row['final']['effects']}
    for query in row['publication_queries']:
        original=effects[query['request']['request_id']]
        expected=dict(status='replayed',epoch=1,request_id=original['request_id'],revision=original['revision'],approved_sha256=original['approved_sha256'])
        replay=same(query['original'],expected);conflict=same(query['changed'],dict(status='conflict',epoch=1,request_id=original['request_id'],revision=None,approved_sha256=None))
        counts['publication_replays']+=replay;counts['publication_conflicts']+=conflict;counts['publication_failures']+=not(replay and conflict)
    return counts


def summarize(rows,cases):
    keys=[(r['case_id'],r['mode']) for r in rows]
    if len(keys)!=72 or len(set(keys))!=72 or set(keys)!={(c['case_id'],m) for c in cases for m in MODES}:raise ValueError('full 72-record grid required')
    arms={m:dict(cases=0,infrastructure_errors=0) for m in MODES}
    for row in rows:
        arm=arms[row['mode']];arm['cases']+=1
        if row['status']!='complete':arm['infrastructure_errors']+=1;continue
        counts=measure(row)
        if not same(counts,row['measures']):raise ValueError('recorded counts changed')
        for k,v in counts.items():arm[k]=arm.get(k,0)+int(v)
    return arms


def main():
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);p.add_argument('--base-commit',required=True);p.add_argument('--freeze-commit',required=True);a=p.parse_args()
    for name in (PROTOCOL,str(DATASET.relative_to(ROOT))):
        if subprocess.check_output(['git','show',a.freeze_commit+':'+name],cwd=ROOT)!=(ROOT/name).read_bytes():raise ValueError('frozen identity changed')
    for name in [str(p.relative_to(ROOT)) for p in (ROOT/'src').glob('*.py')]+['src/reclamation/store.py']:
        if subprocess.check_output(['git','show',a.base_commit+':'+name],cwd=ROOT)!=(ROOT/name).read_bytes():raise ValueError('inherited mechanism changed')
    cases=load_cases();rows=[run_case(c,m) for c in cases for m in MODES]
    a.output.parent.mkdir(parents=True,exist_ok=True);a.output.write_text(''.join(json.dumps(r,ensure_ascii=False,sort_keys=True)+'\n' for r in rows))
    meta=dict(base_commit=a.base_commit,freeze_commit=a.freeze_commit,executed_at_utc=datetime.now(timezone.utc).isoformat(),python=sys.version,
              results_file=a.output.name,results_sha256=hashlib.sha256(a.output.read_bytes()).hexdigest(),dataset_sha256=hashlib.sha256(DATASET.read_bytes()).hexdigest(),
              source_sha256={n:hashlib.sha256((ROOT/n).read_bytes()).hexdigest() for n in SOURCES},summary=summarize(rows,cases))
    a.output.with_suffix('.metadata.json').write_text(json.dumps(meta,indent=2)+'\n');print(json.dumps(meta['summary'],indent=2))
    if any(arm['infrastructure_errors'] for arm in meta['summary'].values()):raise SystemExit(1)


if __name__=='__main__':main()
