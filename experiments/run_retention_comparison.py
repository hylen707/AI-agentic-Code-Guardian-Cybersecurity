"""Frozen recovery-result retirement histories and bounded current result probes."""
from __future__ import annotations
import argparse
import copy
from datetime import datetime, timezone
import hashlib
import gzip
import json
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))
from experiments.run_resume_comparison import Peer as BoundPeer, snapshot
from src.reclamation.store import pair
from src.recovery_retention.store import CAPACITY,MODES,RecoveryRetentionStore

DATASET=ROOT/'experiments/tasks/retention-eval-v1/tasks.json'
PROTOCOL='docs/RETENTION_PROTOCOL.md'
INHERITED=tuple(sorted(str(p.relative_to(ROOT)) for p in (ROOT/'src').glob('*.py')))+('src/reclamation/store.py','src/recovery_requests/store.py')
SOURCES=INHERITED+('src/recovery_retention/store.py','experiments/run_resume_comparison.py','experiments/resume_worker.py',
 'experiments/retention_worker.py','experiments/run_retention_comparison.py','experiments/verify_retention_results.py','tests/test_retention.py',PROTOCOL)

def same(a,b):return json.dumps(a,sort_keys=True,ensure_ascii=False,separators=(',',':'))==json.dumps(b,sort_keys=True,ensure_ascii=False,separators=(',',':'))
def fields(r):return {k:r[k] for k in ('recovery_epoch','request_id','expected_token','owner')}
def key(r):return (r['recovery_epoch'],r['request_id'])
def reply(status,r,**v):return dict(status=status,recovery_epoch=r['recovery_epoch'],request_id=r['request_id'],**v)

def load_cases(path=DATASET):
 doc=json.loads(Path(path).read_text());cases=doc.get('cases',[])
 if doc.get('schema_version')!='retention-eval-v1' or doc.get('capacity')!=CAPACITY or len(cases)!=32 or len({c['case_id'] for c in cases})!=32:raise ValueError('32 unique frozen cases required')
 return cases

class Peer(BoundPeer):
 def __init__(self,root,mode,action):
  self.generation=action['generation']
  self.command=[sys.executable,str(ROOT/'experiments/retention_worker.py'),'--root',str(root),'--mode',mode,'--role',action['role'],'--generation',str(self.generation),'--request',json.dumps(action['request'],ensure_ascii=False),'--pauses',','.join(action['pauses'])]
  self.process=subprocess.Popen(self.command,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,bufsize=0)
  self.buffer=b'';self.pause=None;self.terminal=False

def firsts(state):
 result={}
 for d in state['decisions']:result.setdefault(key(d),d)
 return result

def query(store,role,request):
 events=[]
 def event(kind,**fields):events.append(copy.deepcopy(dict(seq=len(events),kind=kind,**fields)))
 event('query_started',mode=store.retention_mode,role=role,request=request);before=snapshot(store)
 operation=store.replace_once if role=='replace' else store.advance_epoch
 response=operation(request,checkpoint=lambda stage:event('checkpoint',stage=stage),event=event)
 event('caller_result',response=response);event('query_completed')
 return dict(role=role,request=copy.deepcopy(request),before=before,events=events,response=response,after=snapshot(store))

def run_case(case,mode):
 row={**copy.deepcopy(case),'mode':mode,'status':'infrastructure_error','steps':[],'retired_probes':[],'fresh':[],'current_probes':[],'publication_queries':[],'measures':None}
 peers={};phase='fixture'
 try:
  with tempfile.TemporaryDirectory(prefix='codeguardian-retention-') as directory:
   store=RecoveryRetentionStore(Path(directory)/'store',mode);store.initialize(b'approved=version-a\n')
   for r in case['seeds']:store.publish_once(1,r['request_id'],None if r['content_utf8'] is None else r['content_utf8'].encode())
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
   row['settled']=snapshot(store);originals=[fields(d) for d in firsts(row['settled']).values()]
   phase='final_rotation';row['final_rotation']=query(store,'advance',dict(expected_epoch=row['settled']['active_recovery_epoch']))
   retired=[]
   for original in originals:
    retired.append(dict(kind='original',request=original))
    retired.append(dict(kind='changed',request={**original,'owner':original['owner']+1,'expected_token':snapshot(store)['lease']['token']}))
   retired.append(dict(kind='unused',request=dict(recovery_epoch=1,request_id='never-used',expected_token=snapshot(store)['lease']['token'],owner=99)))
   for stage in ('before_close','after_close'):
    phase='retired_probes'
    for item in retired:row['retired_probes'].append(dict(stage=stage,kind=item['kind'],**query(store,'replace',item['request'])))
    if stage=='before_close':
     phase='fresh'
     for i in (1,2):
      r=dict(recovery_epoch=snapshot(store)['active_recovery_epoch'],request_id='fresh-'+str(i),expected_token=snapshot(store)['lease']['token'],owner=100+i)
      row['fresh'].append(query(store,'replace',r))
    phase='current_probes'
    for item in row['fresh']:
     original=item['request'];changed={**original,'owner':original['owner']+1}
     for kind,r in (('original',original),('changed',changed)):
      row['current_probes'].append(dict(stage=stage,kind=kind,**query(store,'replace',r)))
    overflow=dict(recovery_epoch=snapshot(store)['active_recovery_epoch'],request_id='overflow-current',expected_token=snapshot(store)['lease']['token'],owner=103)
    row['current_probes'].append(dict(stage=stage,kind='overflow',**query(store,'replace',overflow)))
    if stage=='before_close':
     phase='closure';lease=pair(snapshot(store)['lease']);answer=store.migrate_once(lease)
     row['closure']=dict(lease=lease,response=answer,snapshot=snapshot(store))
   row['final']=snapshot(store);phase='publication_queries'
   for r in case['seeds']:
    value=None if r['content_utf8'] is None else r['content_utf8'].encode();changed=None if value is not None else b'changed=publication\n'
    row['publication_queries'].append(dict(request=r,original=store.publish_once(1,r['request_id'],value),changed=store.publish_once(1,r['request_id'],changed)))
   row['after_publication_queries']=snapshot(store);row['status']='complete';row['measures']=measure(row)
 except Exception as error:row.update(error_phase=phase,error_type=type(error).__name__,error_detail=str(error))
 finally:
  for peer in peers.values():peer.close()
 return row

def expected_answer(events,role,request):
 if any(e['kind']=='writer_busy' for e in events):return reply('busy',request,sqlite_errorcode=5) if role=='replace' else dict(status='busy',sqlite_errorcode=5)
 if role=='advance':
  committed=next((e for e in events if e['kind']=='rotation_committed'),None)
  if committed:return dict(status='advanced',previous_epoch=committed['from_epoch'],active_recovery_epoch=committed['to_epoch'],removed_receipts=committed['removed_receipts'])
  return dict(status='epoch_conflict',active_recovery_epoch=next(e['active_recovery_epoch'] for e in events if e['kind']=='rotation_view'))
 for e in events:
  if e['kind']=='admission_checked' and e['fate']!='accepted':return reply(e['fate'],request,active_recovery_epoch=e['active_recovery_epoch'])
  if e['kind']=='receipt_lookup' and e['receipt'] is not None:
   r=e['receipt'];return reply('replayed',request,outcome=r['outcome']) if same(fields(r),request) else reply('request_conflict',request)
  if e['kind']=='capacity_checked' and e['count']>=e['capacity']:return reply('capacity_exhausted',request,capacity=e['capacity'])
 d=next(e for e in events if e['kind']=='decision_committed');return reply('recorded',request,outcome=d['outcome'])

def observations(row):
 yield row['initial']
 for step in row['steps']:yield step['snapshot']
 yield row['settled'];yield row['final_rotation']['after']
 for stage in ('before_close','after_close'):
  for q in row['retired_probes']:
   if q['stage']==stage:yield q['after']
  if stage=='before_close':
   for q in row['fresh']:yield q['after']
  for q in row['current_probes']:
   if q['stage']==stage:yield q['after']
  if stage=='before_close':yield row['closure']['snapshot']
 yield row['final'];yield row['after_publication_queries']

def measure(row):
 counts=dict(lifetime_grants=len(row['final']['grants']),decisions=len(row['final']['decisions']),retirements=len(row['final']['retirements']),
  retired_decisions=0,retired_grants=0,rebound_ids=0,max_live_result_rows=0,result_bound_violations=0,stale_result_snapshots=0,snapshot_observations=0,
  retired_queries=0,correct_retired_queries=0,retired_query_state_changes=0,fresh_requests=0,fresh_request_failures=0,current_queries=0,current_query_failures=0,
  capacity_queries=0,capacity_failures=0,busy=0,caller_errors=0,transport_response_errors=0,planned_exits=0,normal_children=0,barriers=0,
  actual_completed=row['final']['active_epoch']==2,publication_replays=0,publication_conflicts=0,publication_failures=0,
  publication_queries_inert=same(row['final'],row['after_publication_queries']))
 first=firsts(row['final'])
 for d in row['final']['decisions']:
  retired=d['recovery_epoch']<d['active_recovery_epoch'];counts['retired_decisions']+=retired;counts['retired_grants']+=retired and d['effect_token'] is not None
  counts['rebound_ids']+=d['ordinal']!=first[key(d)]['ordinal']
 for state in observations(row):
  size=len(state['retained_results']);counts['snapshot_observations']+=1
  counts['max_live_result_rows']=max(counts['max_live_result_rows'],size)
  counts['result_bound_violations']+=size>CAPACITY
  counts['stale_result_snapshots']+=any(r['recovery_epoch']<state['active_recovery_epoch'] for r in state['retained_results'])
 traces={}
 starts={s['action']['generation']:s['action'] for s in row['steps'] if s['action']['op']=='start'}
 for step in row['steps']:
  if step['action']['op']=='migrate':continue
  generation=step['action']['generation'];action=starts[generation];prefix=traces.setdefault(generation,[])
  for e in step['events']:
   prefix.append(e);counts['barriers']+=e['kind']=='paused';counts['caller_errors']+=e['kind']=='caller_error'
   if e['kind']=='caller_result':
    counts['transport_response_errors']+=not same(e['response'],expected_answer(prefix,action['role'],action['request']))
    counts['busy']+=e['response'].get('status')=='busy'
  counts['planned_exits']+=step['returncode']==73;counts['normal_children']+=step['returncode']==0
 queries=[row['final_rotation']]+row['retired_probes']+row['fresh']+row['current_probes']
 for q in queries:
  counts['transport_response_errors']+=not same(q['response'],expected_answer(q['events'],q['role'],q['request']))
  counts['busy']+=q['response'].get('status')=='busy'
 for q in row['retired_probes']:
  counts['retired_queries']+=1;counts['correct_retired_queries']+=same(q['response'],reply('retired',q['request'],active_recovery_epoch=q['before']['active_recovery_epoch']))
  counts['retired_query_state_changes']+=not same(q['before'],q['after'])
 for q in row['fresh']:
  counts['fresh_requests']+=1;counts['fresh_request_failures']+=not same(q['response'],reply('recorded',q['request'],outcome=first[key(q['request'])]['outcome']))
 for q in row['current_probes']:
  counts['current_queries']+=1
  if q['kind']=='overflow':
   counts['capacity_queries']+=1;ok=same(q['response'],reply('capacity_exhausted',q['request'],capacity=CAPACITY));counts['capacity_failures']+=not ok
  elif q['kind']=='changed':ok=same(q['response'],reply('request_conflict',q['request']))
  else:ok=same(q['response'],reply('replayed',q['request'],outcome=first[key(q['request'])]['outcome']))
  counts['current_query_failures']+=not ok or not same(q['before'],q['after'])
 effects={r['request_id']:r for r in row['final']['effects']}
 for q in row['publication_queries']:
  effect=effects[q['request']['request_id']]
  ok=same(q['original'],dict(status='replayed',epoch=1,request_id=effect['request_id'],revision=effect['revision'],approved_sha256=effect['approved_sha256']))
  conflict=same(q['changed'],dict(status='conflict',epoch=1,request_id=effect['request_id'],revision=None,approved_sha256=None))
  counts['publication_replays']+=ok;counts['publication_conflicts']+=conflict;counts['publication_failures']+=not(ok and conflict)
 return counts

def summarize(rows,cases):
 keys=[(r['case_id'],r['mode']) for r in rows]
 if len(keys)!=96 or len(set(keys))!=96 or set(keys)!={(c['case_id'],m) for c in cases for m in MODES}:raise ValueError('full 96-record grid required')
 arms={m:dict(cases=0,infrastructure_errors=0) for m in MODES}
 for row in rows:
  arm=arms[row['mode']];arm['cases']+=1
  if row['status']!='complete':arm['infrastructure_errors']+=1;continue
  counts=measure(row)
  if not same(counts,row['measures']):raise ValueError('recorded counts changed')
  for k,v in counts.items():arm[k]=max(arm.get(k,0),v) if k=='max_live_result_rows' else arm.get(k,0)+int(v)
 return arms

def main():
 p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);p.add_argument('--base-commit',required=True);p.add_argument('--freeze-commit',required=True);a=p.parse_args()
 for n in (PROTOCOL,str(DATASET.relative_to(ROOT))):
  if subprocess.check_output(['git','show',a.freeze_commit+':'+n],cwd=ROOT)!=(ROOT/n).read_bytes():raise ValueError('frozen identity changed')
 for n in INHERITED:
  if subprocess.check_output(['git','show',a.base_commit+':'+n],cwd=ROOT)!=(ROOT/n).read_bytes():raise ValueError('inherited mechanism changed')
 cases=load_cases();rows=[run_case(c,m) for c in cases for m in MODES]
 a.output.parent.mkdir(parents=True,exist_ok=True);serialized=''.join(json.dumps(r,ensure_ascii=False,sort_keys=True)+'\n' for r in rows).encode('utf-8')
 a.output.write_bytes(gzip.compress(serialized,mtime=0) if a.output.suffix=='.gz' else serialized)
 meta=dict(base_commit=a.base_commit,freeze_commit=a.freeze_commit,executed_at_utc=datetime.now(timezone.utc).isoformat(),python=sys.version,
  results_file=a.output.name,results_sha256=hashlib.sha256(a.output.read_bytes()).hexdigest(),dataset_sha256=hashlib.sha256(DATASET.read_bytes()).hexdigest(),
  source_sha256={n:hashlib.sha256((ROOT/n).read_bytes()).hexdigest() for n in SOURCES},summary=summarize(rows,cases))
 (a.output.with_suffix('') if a.output.suffix=='.gz' else a.output).with_suffix('.metadata.json').write_text(json.dumps(meta,indent=2)+'\n');print(json.dumps(meta['summary'],indent=2))
 if any(a['infrastructure_errors'] for a in meta['summary'].values()):raise SystemExit(1)

if __name__=='__main__':main()
