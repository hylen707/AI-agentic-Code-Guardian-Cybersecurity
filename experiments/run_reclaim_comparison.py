"""Frozen permission-replacement schedules over real disposable SQLite stores."""
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
from experiments.run_resume_comparison import Peer as BoundPeer, snapshot
from src.reclamation.store import MODES,ReclamationStore,pair

DATASET=ROOT/'experiments/tasks/reclaim-eval-v1/tasks.json'
PROTOCOL='docs/RECLAIM_PROTOCOL.md'
SOURCES=tuple(sorted(str(p.relative_to(ROOT)) for p in (ROOT/'src').glob('*.py'))) + (
    'src/reclamation/store.py','experiments/run_resume_comparison.py','experiments/resume_worker.py',
    'experiments/reclaim_worker.py','experiments/run_reclaim_comparison.py','experiments/verify_reclaim_results.py','tests/test_reclaim.py',PROTOCOL)


def load_cases(path=DATASET):
    doc=json.loads(Path(path).read_text());cases=doc.get('cases',[])
    if doc.get('schema_version')!='reclaim-eval-v1' or len(cases)!=20 or len({c['case_id'] for c in cases})!=20:
        raise ValueError('twenty unique frozen declarations required')
    return cases


class Peer(BoundPeer):
    def __init__(self,root,mode,action,lease):
        self.generation=action['generation'];self.lease=lease
        self.command=[sys.executable,str(ROOT/'experiments/reclaim_worker.py'),'--root',str(root),'--mode',mode,
                      '--generation',str(self.generation),'--owner',str(lease['owner']),'--token',str(lease['token']),'--pauses',','.join(action['pauses'])]
        self.process=subprocess.Popen(self.command,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,bufsize=0)
        self.buffer=b'';self.pause=None;self.terminal=False


def content(req):return None if req['content_utf8'] is None else req['content_utf8'].encode('utf-8')


def run_case(case,mode):
    row={**copy.deepcopy(case),'mode':mode,'status':'infrastructure_error','steps':[],'queries':[],'measures':None}
    peers={};phase='fixture'
    try:
        with tempfile.TemporaryDirectory(prefix='codeguardian-reclaim-') as directory:
            store=ReclamationStore(Path(directory)/'store',mode);store.initialize(b'approved=version-a\n')
            originals=[]
            for req in case['seeds']:
                store.publish_once(1,req['request_id'],content(req));originals.append(req)
            row['initial']=snapshot(store);initial=pair(row['initial']['lease'])
            for action in case['steps']:
                phase=action['op'];step=dict(action=copy.deepcopy(action))
                if phase=='start':
                    lease=initial if action['lease']=='initial' else pair(snapshot(store)['lease'])
                    peer=Peer(store.root,mode,action,lease);peers[action['generation']]=peer
                    step.update(command=peer.command,lease=lease);step.update(peer.boundary())
                elif phase=='resume':
                    peer=peers[action['generation']];step.update(command=peer.resume(action),lease=peer.lease)
                    step.update(peer.boundary())
                elif phase=='reclaim':step['response']=store.replace(action['expected_token'],action['owner'])
                elif phase=='publish':
                    req=case['publication'];step['request']=req;step['response']=store.publish_once(1,req['request_id'],content(req))
                    if step['response']['status']=='committed':originals.append(req)
                else:raise ValueError('unknown frozen action')
                step['snapshot']=snapshot(store);row['steps'].append(step)
            row['final']=snapshot(store);phase='queries'
            for req in originals:
                changed=None if content(req) is not None else b'changed=typed-intent\n'
                row['queries'].append(dict(request=req,original=store.publish_once(1,req['request_id'],content(req)),changed=store.publish_once(1,req['request_id'],changed)))
            row['after_queries']=snapshot(store);row['status']='complete';row['measures']=measure(row)
    except Exception as error:row.update(error_phase=phase,error_type=type(error).__name__,error_detail=str(error))
    finally:
        for peer in peers.values():peer.close()
    return row


def measure(row):
    final=row['final'];effect=final['lease_effect']
    counts=dict(invalid_effects=int(effect is not None and not effect['authorized']),original_holder_commits=0,stale_token_refusals=0,
                source_refusals=0,reclaimed=0,recovery_busy=0,recovery_conflicts=0,recovery_completed=0,lifetime_grants=len(final['grants']),
                aba_cases=int(row['scenario']=='aba_owner'),actual_completed=final['active_epoch']==2,caller_errors=0,response_violations=0,
                planned_exits=0,normal_children=0,barriers=0,publications=0,original_replays=0,changed_conflicts=0,query_failures=0,
                missing_authority=0,duplicate_authority=0,queries_inert=final==row['after_queries'])
    for step in row['steps']:
        op=step['action']['op']
        if op=='reclaim':
            key={'reclaimed':'reclaimed','busy':'recovery_busy','conflict':'recovery_conflicts','completed':'recovery_completed'}.get(step['response']['status'])
            if key is None:counts['response_violations']+=1
            else:counts[key]+=1
            continue
        if op=='publish':counts['publications']+=step['response']['status']=='committed';continue
        for event in step['events']:
            kind=event['kind'];counts['barriers']+=kind=='paused';counts['caller_errors']+=kind=='caller_error'
            counts['original_holder_commits']+=kind=='effect_committed' and step['action']['generation']==1
            if kind!='caller_result':continue
            answer=event['response'];status=answer['status'];state=step['snapshot'];lease=step['lease']
            counts['stale_token_refusals']+=status=='stale_lease';counts['source_refusals']+=status=='stale_source'
            if status=='completed':valid=state['active_epoch']==2 and answer==dict(status='completed',active_epoch=2)
            elif status=='migrated':
                witness=state['lease_effect'];valid=state['active_epoch']==2 and witness is not None and {k:witness[k] for k in ('owner','token')}==lease and answer==dict(status='migrated',active_epoch=2,**lease)
            elif status=='stale_lease':valid=state['active_epoch']==1 and pair(state['lease'])!=lease and answer==dict(status='stale_lease',active_epoch=1)
            elif status=='stale_source':valid=state['active_epoch']==1 and answer==dict(status='stale_source',active_epoch=1)
            elif status=='busy':valid=answer==dict(status='busy',sqlite_errorcode=5)
            else:valid=False
            counts['response_violations']+=not valid
        counts['planned_exits']+=step['returncode']==73;counts['normal_children']+=step['returncode']==0
    effects={r['request_id']:r for r in final['effects']};authority=final['receipts']+final['summaries'];keys=[(r['epoch'],r['request_id']) for r in authority]
    counts['missing_authority']=len(set(effects)-{r['request_id'] for r in authority});counts['duplicate_authority']=len(keys)-len(set(keys))
    for q in row['queries']:
        effect=effects[q['request']['request_id']]
        expected=dict(status='replayed',epoch=1,request_id=effect['request_id'],revision=effect['revision'],approved_sha256=effect['approved_sha256'])
        replay=q['original']==expected;conflict=q['changed']==dict(status='conflict',epoch=1,request_id=effect['request_id'],revision=None,approved_sha256=None)
        counts['original_replays']+=replay;counts['changed_conflicts']+=conflict;counts['query_failures']+=not(replay and conflict)
    return counts


def summarize(rows,cases):
    keys=[(r['case_id'],r['mode']) for r in rows]
    if len(keys)!=60 or len(set(keys))!=60 or set(keys)!={(c['case_id'],m) for c in cases for m in MODES}:raise ValueError('full sixty-record paired grid required')
    arms={m:dict(cases=0,infrastructure_errors=0) for m in MODES}
    for row in rows:
        arm=arms[row['mode']];arm['cases']+=1
        if row['status']!='complete':arm['infrastructure_errors']+=1;continue
        counts=measure(row)
        if counts!=row['measures']:raise ValueError('recorded counts changed')
        for key,value in counts.items():arm[key]=arm.get(key,0)+int(value)
    return arms


def main():
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);p.add_argument('--base-commit',required=True);p.add_argument('--freeze-commit',required=True)
    a=p.parse_args();cases=load_cases()
    for name in (PROTOCOL,str(DATASET.relative_to(ROOT))):
        if subprocess.check_output(['git','show',a.freeze_commit+':'+name],cwd=ROOT)!=(ROOT/name).read_bytes():raise ValueError('frozen identity changed')
    for path in (ROOT/'src').glob('*.py'):
        if subprocess.check_output(['git','show',a.base_commit+':'+str(path.relative_to(ROOT))],cwd=ROOT)!=path.read_bytes():raise ValueError('earlier mechanism changed')
    rows=[run_case(c,m) for c in cases for m in MODES]
    a.output.parent.mkdir(parents=True,exist_ok=True);a.output.write_text(''.join(json.dumps(r,ensure_ascii=False,sort_keys=True)+'\n' for r in rows))
    meta=dict(base_commit=a.base_commit,freeze_commit=a.freeze_commit,executed_at_utc=datetime.now(timezone.utc).isoformat(),python=sys.version,
              results_file=a.output.name,results_sha256=hashlib.sha256(a.output.read_bytes()).hexdigest(),dataset_sha256=hashlib.sha256(DATASET.read_bytes()).hexdigest(),
              source_sha256={n:hashlib.sha256((ROOT/n).read_bytes()).hexdigest() for n in SOURCES},summary=summarize(rows,cases))
    a.output.with_suffix('.metadata.json').write_text(json.dumps(meta,indent=2)+'\n');print(json.dumps(meta['summary'],indent=2))
    if any(arm['infrastructure_errors'] for arm in meta['summary'].values()):raise SystemExit(1)


if __name__=='__main__':main()
