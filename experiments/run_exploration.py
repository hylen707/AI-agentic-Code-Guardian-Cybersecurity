"""Execute the frozen finite grammar against unchanged SQLite mechanisms."""
from __future__ import annotations
import argparse
import copy
from datetime import datetime,timezone
import gzip
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))
from experiments.generate_histories import DATASET,generate,load_grammar,resolve
from experiments.run_retention_comparison import Peer,query,snapshot,expected_answer
from src.recovery_retention.store import MODES,RecoveryRetentionStore

PROTOCOL='docs/EXPLORATION_PROTOCOL.md'
INHERITED=tuple(sorted(str(p.relative_to(ROOT)) for p in (ROOT/'src').glob('*.py')))+('src/reclamation/store.py','src/recovery_requests/store.py','src/recovery_retention/store.py',
 'experiments/run_resume_comparison.py','experiments/resume_worker.py','experiments/retention_worker.py','experiments/run_retention_comparison.py','experiments/verify_retention_results.py')
SOURCES=INHERITED+('experiments/generate_histories.py','experiments/run_exploration.py','experiments/verify_exploration.py','tests/test_exploration.py',PROTOCOL)

def same(a,b):return json.dumps(a,sort_keys=True,ensure_ascii=False,separators=(',',':'))==json.dumps(b,sort_keys=True,ensure_ascii=False,separators=(',',':'))

def parent(store,template,g):
 role,request=resolve(template,snapshot(store),g)
 if role!='close':return dict(template=template,**query(store,role,request))
 before=snapshot(store);answer=store.migrate_once(request)
 return dict(template=template,role=role,request=request,before=before,events=[],response=answer,after=snapshot(store))

def run_case(case,mode,g):
 row={**copy.deepcopy(case),'mode':mode,'status':'infrastructure_error','prefix':[],'steps':[],'publication_queries':[],'measures':None};peers={};phase='fixture'
 try:
  with tempfile.TemporaryDirectory(prefix='codeguardian-explore-') as d:
   store=RecoveryRetentionStore(Path(d)/'store',mode);store.initialize(b'approved=version-a\n')
   for r in g['seeds']:store.publish_once(1,r['request_id'],None if r['content_utf8'] is None else r['content_utf8'].encode())
   row['initial']=snapshot(store)
   for template in case['path']:phase='prefix';row['prefix'].append(parent(store,template,g))
   if case['family']=='overlap':
    view=snapshot(store);a_role,a=resolve(case['pair']['a'],view,g);b_role,b=resolve(case['pair']['b'],view,g)
    for generation,role,request,pauses in ((1,a_role,a,[case['pause']]),(2,b_role,b,[])):
     phase='start';action=dict(op='start',generation=generation,role=role,request=request,pauses=pauses)
     peer=Peer(store.root,mode,action);peers[generation]=peer
     row['steps'].append(dict(action=action,command=peer.command,**peer.boundary(),snapshot=snapshot(store)))
    if peers[1].pause is not None:
     phase='resume';action=dict(op='resume',generation=1,action=case['finish']);peer=peers[1]
     row['steps'].append(dict(action=action,command=peer.resume(action),**peer.boundary(),snapshot=snapshot(store)))
   row['settled']=snapshot(store);phase='closure';row['closure']=parent(store,'close',g);row['final']=snapshot(store)
   for r in g['seeds']:
    phase='publication_queries';value=None if r['content_utf8'] is None else r['content_utf8'].encode();changed=None if value is not None else b'changed=publication\n'
    row['publication_queries'].append(dict(request=r,original=store.publish_once(1,r['request_id'],value),changed=store.publish_once(1,r['request_id'],changed)))
   row['after_publication_queries']=snapshot(store);row['status']='complete';row['measures']=measure(row)
 except Exception as e:row.update(error_phase=phase,error_type=type(e).__name__,error_detail=str(e))
 finally:
  for p in peers.values():p.close()
 return row

def measure(row):
 final=row['final'];seen=set();retired=grants=rebound=0
 for d in final['decisions']:
  bad=d['recovery_epoch']<d['active_recovery_epoch'];retired+=bad;grants+=bad and d['effect_token'] is not None
  k=(d['recovery_epoch'],d['request_id']);rebound+=k in seen;seen.add(k)
 observations=[row['initial']]+[p['after'] for p in row['prefix']]+[s['snapshot'] for s in row['steps']]+[row['settled'],row['closure']['after'],final,row['after_publication_queries']]
 counts=dict(retired_decisions=retired,retired_grants=grants,rebound_ids=rebound,max_live_result_rows=max(len(s['retained_results']) for s in observations),
  snapshot_observations=len(observations),stale_result_snapshots=sum(any(r['recovery_epoch']<s['active_recovery_epoch'] for r in s['retained_results']) for s in observations),
  result_bound_violations=sum(len(s['retained_results'])>2 for s in observations),pivots_realized=0,unreached_pivots=0,children=0,normal_children=0,planned_exits=0,barriers=0,
  busy=0,caller_errors=0,transport_response_errors=0,parent_operations=len(row['prefix'])+1,actual_completed=final['active_epoch']==2,
  publication_replays=0,publication_conflicts=0,publication_failures=0,publication_queries_inert=same(final,row['after_publication_queries']))
 if row['family']=='overlap':
  realized=any(e['kind']=='paused' for e in row['steps'][0]['events']);counts['pivots_realized']=int(realized);counts['unreached_pivots']=int(not realized)
 for p in row['prefix']+[row['closure']]:
  if p['role']=='close':continue
  counts['transport_response_errors']+=not same(p['response'],expected_answer(p['events'],p['role'],p['request']));counts['busy']+=p['response'].get('status')=='busy'
 histories={};starts={s['action']['generation']:s['action'] for s in row['steps'] if s['action']['op']=='start'}
 for step in row['steps']:
  action=step['action'];g=action['generation'];events=histories.setdefault(g,[]);counts['children']+=action['op']=='start'
  for e in step['events']:
   events.append(e);counts['barriers']+=e['kind']=='paused';counts['caller_errors']+=e['kind']=='caller_error'
   if e['kind']=='caller_result':
    counts['busy']+=e['response'].get('status')=='busy';a=starts[g]
    counts['transport_response_errors']+=not same(e['response'],expected_answer(events,a['role'],a['request']))
  counts['normal_children']+=step['returncode']==0;counts['planned_exits']+=step['returncode']==73
 effects={r['request_id']:r for r in final['effects']}
 for q in row['publication_queries']:
  e=effects[q['request']['request_id']];ok=same(q['original'],dict(status='replayed',epoch=1,request_id=e['request_id'],revision=e['revision'],approved_sha256=e['approved_sha256']))
  conflict=same(q['changed'],dict(status='conflict',epoch=1,request_id=e['request_id'],revision=None,approved_sha256=None))
  counts['publication_replays']+=ok;counts['publication_conflicts']+=conflict;counts['publication_failures']+=not(ok and conflict)
 return counts

def empty():return {m:{f:dict(cases=0,infrastructure_errors=0) for f in ('sequence','overlap')} for m in MODES}
def add(arms,row,counts):
 a=arms[row['mode']][row['family']];a['cases']+=1
 if counts is None:a['infrastructure_errors']+=1;return
 for k,v in counts.items():a[k]=max(a.get(k,0),v) if k=='max_live_result_rows' else a.get(k,0)+int(v)

def summarize(rows,cases):
 arms=empty();keys=[]
 for row in rows:
  keys.append((row['case_id'],row['mode']));counts=None if row['status']!='complete' else measure(row)
  if counts is not None and not same(counts,row['measures']):raise ValueError('recorded counts changed')
  add(arms,row,counts)
 if len(keys)!=3372 or len(set(keys))!=3372 or set(keys)!={(c['case_id'],m) for c in cases for m in MODES}:raise ValueError('complete 3372-history grid required')
 return arms

def main():
 p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);p.add_argument('--base-commit',required=True);p.add_argument('--freeze-commit',required=True);a=p.parse_args()
 for n in (PROTOCOL,str(DATASET.relative_to(ROOT))):
  if subprocess.check_output(['git','show',a.freeze_commit+':'+n],cwd=ROOT)!=(ROOT/n).read_bytes():raise ValueError('frozen grammar changed')
 for n in INHERITED:
  if subprocess.check_output(['git','show',a.base_commit+':'+n],cwd=ROOT)!=(ROOT/n).read_bytes():raise ValueError('inherited mechanism/reference changed')
 g=load_grammar();cases=generate(g);arms=empty();a.output.parent.mkdir(parents=True,exist_ok=True)
 with a.output.open('wb') as file:
  with gzip.GzipFile(fileobj=file,mode='wb',mtime=0) as stream:
   for i,c in enumerate(cases):
    for mode in MODES:
     row=run_case(c,mode,g);add(arms,row,row['measures']);stream.write((json.dumps(row,ensure_ascii=False,sort_keys=True)+'\n').encode())
    if (i+1)%200==0:print('completed',i+1,'of',len(cases),'histories per arm',flush=True)
 meta=dict(base_commit=a.base_commit,freeze_commit=a.freeze_commit,executed_at_utc=datetime.now(timezone.utc).isoformat(),python=sys.version,results_file=a.output.name,
  results_sha256=hashlib.sha256(a.output.read_bytes()).hexdigest(),dataset_sha256=hashlib.sha256(DATASET.read_bytes()).hexdigest(),source_sha256={n:hashlib.sha256((ROOT/n).read_bytes()).hexdigest() for n in SOURCES},summary=arms)
 a.output.with_suffix('').with_suffix('.metadata.json').write_text(json.dumps(meta,indent=2)+'\n');print(json.dumps(arms,indent=2))
 if any(f['infrastructure_errors'] for arm in arms.values() for f in arm.values()):raise SystemExit(1)

if __name__=='__main__':main()
