"""Independent trace replay and bounded observable-prefix linearization search."""
from __future__ import annotations
import argparse
import copy
import gzip
import hashlib
import itertools
import json
from pathlib import Path
import re
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))
# Frozen independent reference; this module imports no mechanism or harness.
from experiments.verify_retention_results import Model,Invocation,check_events
MODES=('erase_only','cached_floor','atomic_floor')
DATASET=ROOT/'experiments/tasks/exploration-eval-v1/grammar.json'
ALPHABET=('old_a','changed_a','current_a','current_b','current_c','future_a','advance','close')
PROTOCOL='docs/EXPLORATION_PROTOCOL.md'
INHERITED=tuple(sorted(str(p.relative_to(ROOT)) for p in (ROOT/'src').glob('*.py')))+('src/reclamation/store.py','src/recovery_requests/store.py','src/recovery_retention/store.py',
 'experiments/run_resume_comparison.py','experiments/resume_worker.py','experiments/retention_worker.py','experiments/run_retention_comparison.py','experiments/verify_retention_results.py')
SOURCES=INHERITED+('experiments/generate_histories.py','experiments/run_exploration.py','experiments/verify_exploration.py','tests/test_exploration.py',PROTOCOL)

def same(a,b):return json.dumps(a,sort_keys=True,ensure_ascii=False,separators=(',',':'))==json.dumps(b,sort_keys=True,ensure_ascii=False,separators=(',',':'))
def encode(v):return json.dumps(v,sort_keys=True,ensure_ascii=False,separators=(',',':'))
def signature(v):return hashlib.sha256(encode(v).encode()).hexdigest()
def reply(status,r,**v):return dict(status=status,recovery_epoch=r['recovery_epoch'],request_id=r['request_id'],**v)

def load_manifest(path=DATASET):
 g=json.loads(Path(path).read_text())
 fields={'schema_version','sequence_depth','overlap_prefix_depth','capacity','alphabet','keys','pairs','request_checkpoints','advance_checkpoints','finishes','modes','seeds','expected_per_arm'}
 pairs=[('old_same','old_a','old_a'),('old_changed','old_a','changed_a'),('current_distinct','current_a','current_b'),('current_advance','current_a','advance'),('old_advance','old_a','advance'),('advance_old','advance','old_a'),('advance_future','advance','future_a'),('advance_same','advance','advance')]
 if set(g)!=fields or g['schema_version']!='exploration-eval-v1' or not same([g['sequence_depth'],g['overlap_prefix_depth'],g['capacity']],[3,1,2]) or g['alphabet']!=list(ALPHABET) or not same(g['pairs'],[dict(name=n,a=a,b=b) for n,a,b in pairs]):raise ValueError('fixed finite grammar required')
 if g['keys']!={'a':'request-α','b':'slot-b','c':'slot-c'} or g['request_checkpoints']!=['after_admission','after_lookup','before_decision_commit','after_decision_commit','before_reply'] or g['advance_checkpoints']!=['before_rotation_commit','after_rotation_commit','before_reply'] or g['finishes']!=['continue','exit'] or g['modes']!=list(MODES):raise ValueError('grammar domain changed')
 if not same(g['expected_per_arm'],dict(sequence=512,overlap=612,total=1124)) or not same(g['seeds'],[dict(epoch=1,request_id='seed-a',content_utf8='approved=안전 ✓\n'),dict(epoch=1,request_id='seed-b',content_utf8=None)]):raise ValueError('fixture or declared counts changed')
 return g

def declarations(g):
 result=[];lookup={v:str(i) for i,v in enumerate(ALPHABET)}
 for values in itertools.product(ALPHABET,repeat=3):result.append(dict(case_id='s-'+''.join(lookup[v] for v in values),family='sequence',path=list(values)))
 for seed in range(9):
  path=[] if seed==0 else [ALPHABET[seed-1]]
  for p,pair in enumerate(g['pairs']):
   stages=g['advance_checkpoints'] if pair['a']=='advance' else g['request_checkpoints']
   for k in range(len(stages)):
    for f in range(2):result.append(dict(case_id=f'o-{seed}-{p}-{k}-{f}',family='overlap',path=path,pair=dict(pair),pause=stages[k],finish=('continue','exit')[f]))
 return result

def inputs(template,m,g):
 if template=='advance':return 'advance',dict(expected_epoch=m.floor)
 if template=='close':return 'close',{k:m.lease[k] for k in ('owner','token')}
 epoch=m.floor
 if template in ('old_a','changed_a'):epoch=1
 elif template=='future_a':epoch+=1
 key=g['keys'][{'current_b':'b','current_c':'c'}.get(template,'a')]
 return 'replace',dict(recovery_epoch=epoch,request_id=key,expected_token=1 if template=='old_a' else m.lease['token'],owner=3 if template in ('changed_a','current_c') else 2)

def projection(s):
 return copy.deepcopy(dict(floor=s['active_recovery_epoch'],lease={k:s['lease'][k] for k in ('owner','token')},target=s['active_epoch'],grants=s['grants'],results=s['retained_results']))

def initial_spec():return dict(floor=1,lease=dict(owner=1,token=1),target=1,grants=[dict(token=1,owner=1,previous=0)],results=[])

def apply_spec(state,call):
 s=copy.deepcopy(state);r=call['request'];role=call['role']
 if (call.get('answer') or {}).get('status')=='busy':
  return s,reply('busy',r,sqlite_errorcode=5) if role=='replace' else dict(status='busy',sqlite_errorcode=5)
 if role=='advance':
  if r['expected_epoch']!=s['floor']:return s,dict(status='epoch_conflict',active_recovery_epoch=s['floor'])
  previous=s['floor'];s['floor']+=1;rows=s['results'];s['results']=[v for v in rows if v['recovery_epoch']>=s['floor']]
  return s,dict(status='advanced',previous_epoch=previous,active_recovery_epoch=s['floor'],removed_receipts=len(rows)-len(s['results']))
 if role=='close':
  if s['target']==2:return s,dict(status='completed',active_epoch=2)
  if not same(r,s['lease']):return s,dict(status='stale_lease',active_epoch=1)
  s['target']=2;return s,dict(status='migrated',active_epoch=2,**r)
 if r['recovery_epoch']!=s['floor']:
  return s,reply('retired' if r['recovery_epoch']<s['floor'] else 'future_epoch',r,active_recovery_epoch=s['floor'])
 record=next((v for v in s['results'] if v['recovery_epoch']==r['recovery_epoch'] and v['request_id']==r['request_id']),None)
 if record is not None:
  if not same({k:record[k] for k in r},r):return s,reply('request_conflict',r)
  return s,reply('replayed',r,outcome=record['outcome'])
 if len(s['results'])>=2:return s,reply('capacity_exhausted',r,capacity=2)
 if s['target']==2:outcome=dict(status='completed',active_epoch=2)
 elif r['expected_token']!=s['lease']['token']:outcome=dict(status='conflict',lease=copy.deepcopy(s['lease']))
 else:
  previous=s['lease']['token'];s['lease']=dict(owner=r['owner'],token=previous+1)
  s['grants'].append(dict(token=previous+1,owner=r['owner'],previous=previous))
  outcome=dict(status='reclaimed',lease=copy.deepcopy(s['lease']),previous=previous)
 s['results'].append(dict(**r,outcome=outcome));s['results'].sort(key=lambda v:(v['recovery_epoch'],v['request_id']))
 return s,reply('recorded',r,outcome=outcome)

def linearize(history,observed):
 """Search all bounded orders; no implementation event is an input."""
 memo=set()
 def visit(remaining,state,order):
  if not remaining:return order if same(state,observed) else None
  cache=(tuple(remaining),encode(state))
  if cache in memo:return None
  memo.add(cache)
  for i in remaining:
   c=history[i]
   if any(j!=i and history[j]['end'] is not None and history[j]['end']<c['start'] for j in remaining):continue
   rest=tuple(j for j in remaining if j!=i)
   if c['answer'] is None:
    result=visit(rest,state,order+[dict(id=c['id'],effect='omitted')])
    if result is not None:return result
   next_state,answer=apply_spec(state,{**c,'answer':c['answer'] or {}})
   if c['answer'] is not None and not same(c['answer'],answer):continue
   result=visit(rest,next_state,order+[dict(id=c['id'],effect='applied')])
   if result is not None:return result
  return None
 return visit(tuple(range(len(history))),initial_spec(),[])


def evaluate(row,case,g):
 if row['mode'] not in MODES or any(not same(row[k],v) for k,v in case.items()):raise ValueError('declared history binding changed')
 if row['status']!='complete':
  if row['measures'] is not None or not row.get('error_type'):raise ValueError('unexplained infrastructure error')
  return None,None
 m=Model(dict(seeds=g['seeds']),row['mode']);clock=0;history=[];peers={};operations={};root=None;previous=None
 c=dict(retired_decisions=0,retired_grants=0,rebound_ids=0,max_live_result_rows=0,snapshot_observations=0,stale_result_snapshots=0,result_bound_violations=0,
  pivots_realized=0,unreached_pivots=0,children=0,normal_children=0,planned_exits=0,barriers=0,busy=0,caller_errors=0,transport_response_errors=0,
  parent_operations=len(case['path'])+1,actual_completed=False,publication_replays=0,publication_conflicts=0,publication_failures=0,publication_queries_inert=True)
 stats=dict(checked_prefixes=0,consistent_prefixes=0,states=set(),transitions=set(),first_failure=None)
 def observe(actual,label):
  nonlocal previous
  if not same(actual,m.snapshot()):raise ValueError('snapshot contradicts independent transaction reconstruction')
  n=len(m.records);c['snapshot_observations']+=1;c['max_live_result_rows']=max(c['max_live_result_rows'],n)
  c['stale_result_snapshots']+=any(k[0]<m.floor for k in m.records);c['result_bound_violations']+=n>2
  state=projection(actual);stats['checked_prefixes']+=1;valid=linearize(history,state) is not None;stats['consistent_prefixes']+=valid
  stats['states'].add(signature(state))
  if previous is not None:stats['transitions'].add(signature([previous,label,state]))
  previous=state
  if not valid and stats['first_failure'] is None:
   stats['first_failure']=dict(case_id=case['case_id'],family=case['family'],operation_count=len(history),boundary_count=stats['checked_prefixes'],history=copy.deepcopy(history),observed_state=state)
 def parent(q,template):
  nonlocal clock
  role,r=inputs(template,m,g)
  if q['template']!=template or q['role']!=role or not same(q['request'],r) or not same(q['before'],m.snapshot()):raise ValueError('parent input or causal prefix changed')
  clock+=1;operation=dict(id='p'+str(len(history)),role=role,request=r,start=clock,end=clock+1,answer=q['response']);clock+=2;history.append(operation)
  if role=='close':
   answer=m.migrate(r)
   if q['events']!=[]:raise ValueError('unexpected migration wire events')
   c['transport_response_errors']+=not same(q['response'],answer)
  else:
   expected=Invocation(m,role,r,0,[],False).boundary();check_events(q['events'],expected,c)
   result=next(e['response'] for e in q['events'] if e['kind']=='caller_result')
   if not same(result,q['response']):raise ValueError('parent stream/reply mismatch')
   c['busy']+=result.get('status')=='busy'
  observe(q['after'],dict(role=role,request=r))
 observe(row['initial'],'initial')
 if len(row['prefix'])!=len(case['path']):raise ValueError('generated path length changed')
 for template,q in zip(case['path'],row['prefix']):parent(q,template)
 expected_starts=[]
 if case['family']=='overlap':
  for generation,label,pauses in ((1,'a',[case['pause']]),(2,'b',[])):
   role,r=inputs(case['pair'][label],m,g);expected_starts.append(dict(op='start',generation=generation,role=role,request=r,pauses=pauses))
  if len(row['steps']) not in (2,3):raise ValueError('single-pivot action count changed')
 elif row['steps']:raise ValueError('sequential history gained children')
 for i,step in enumerate(row['steps']):
  action=step['action'];generation=action['generation'];clock+=1
  if i<2:
   if not same(action,expected_starts[i]):raise ValueError('paired inputs must be fixed before invocation')
   command=step['command']
   if len(command)!=14 or not command[0] or Path(command[1]).name!='retention_worker.py':raise ValueError('worker command changed')
   flags=dict(zip(command[2::2],command[3::2]));root=flags.get('--root') if root is None else root
   if set(flags)!={'--root','--mode','--role','--generation','--request','--pauses'} or flags['--root']!=root or flags['--mode']!=row['mode'] or flags['--role']!=action['role'] or flags['--generation']!=str(generation) or flags['--pauses']!=','.join(action['pauses']) or not same(json.loads(flags['--request']),action['request']):raise ValueError('typed child command changed')
   peer=Invocation(m,action['role'],action['request'],generation,action['pauses']);peers[generation]=peer;expected=peer.boundary();c['children']+=1
   operation=dict(id='c'+str(generation),role=action['role'],request=action['request'],start=clock,end=None,answer=None);operations[generation]=operation;history.append(operation)
  else:
   peer=peers[1]
   if not same(action,{'op':'resume','generation':1,'action':case['finish']}) or peer.pause is None or not same(step['command'],dict(command=case['finish'],**peer.pause)):raise ValueError('exact typed continuation changed')
   expected=peer.boundary(case['finish']);operation=operations[1]
  actual=step['events']
  if not same([json.loads(line) for line in step['stdout'].splitlines()],actual):raise ValueError('raw stream changed')
  check_events(actual,expected,c);clock+=1
  for e in actual:
   c['barriers']+=e['kind']=='paused';c['caller_errors']+=e['kind']=='caller_error'
   if e['kind']=='caller_result':operation['answer']=e['response'];c['busy']+=e['response'].get('status')=='busy'
  last=expected[-1]['kind'];code=73 if last=='planned_exit' else 0 if last=='worker_completed' else None
  if not same(step['returncode'],code) or not same(step['stderr'],None if code is None else ''):raise ValueError('unmarked process failure')
  if code is not None:operation['end']=clock
  c['normal_children']+=code==0;c['planned_exits']+=code==73
  if i==0:
   realized=last=='paused';c['pivots_realized']=int(realized);c['unreached_pivots']=int(not realized)
   if len(row['steps'])!=2+int(realized):raise ValueError('unreached checkpoint fabricated a continuation')
  observe(step['snapshot'],dict(action=action))
 if any(not p.done for p in peers.values()) or m.writer is not None:raise ValueError('unsettled generated history')
 observe(row['settled'],'settled');parent(row['closure'],'close');observe(row['final'],'final')
 if len(row['publication_queries'])!=len(g['seeds']):raise ValueError('publication denominator changed')
 for seed,q in zip(g['seeds'],row['publication_queries']):
  if not same(q['request'],seed):raise ValueError('publication query identity changed')
  effect=next(e for e in m.effects if e['request_id']==seed['request_id'])
  ok=same(q['original'],dict(status='replayed',epoch=1,request_id=seed['request_id'],revision=effect['revision'],approved_sha256=effect['approved_sha256']))
  conflict=same(q['changed'],dict(status='conflict',epoch=1,request_id=seed['request_id'],revision=None,approved_sha256=None))
  c['publication_replays']+=ok;c['publication_conflicts']+=conflict;c['publication_failures']+=not(ok and conflict)
 observe(row['after_publication_queries'],'publication_queries')
 c['actual_completed']=m.epoch==2;c['publication_queries_inert']=same(row['final'],row['after_publication_queries'])
 for d in m.decisions:
  bad=d['recovery_epoch']<d['active_recovery_epoch'];c['retired_decisions']+=bad;c['retired_grants']+=bad and d['effect_token'] is not None;c['rebound_ids']+=d['ordinal']!=m.first[(d['recovery_epoch'],d['request_id'])]['ordinal']
 if not same(c,row['measures']):raise ValueError('independent outcome counts disagree')
 return c,stats


def recount(rows,g):
 cases=declarations(g);by_id={c['case_id']:c for c in cases};keys=set()
 arms={m:{f:dict(cases=0,infrastructure_errors=0) for f in ('sequence','overlap')} for m in MODES}
 checks={m:{f:dict(checked_prefixes=0,consistent_prefixes=0,consistent_histories=0,inconsistent_histories=0,states=set(),transitions=set(),shortest_observed_failure=None) for f in ('sequence','overlap')} for m in MODES}
 for row in rows:
  key=(row['case_id'],row['mode'])
  if key in keys or row['case_id'] not in by_id or row['mode'] not in MODES:raise ValueError('duplicate or unknown generated history')
  keys.add(key);case=by_id[row['case_id']];counts,stats=evaluate(row,case,g);a=arms[row['mode']][case['family']];a['cases']+=1
  if counts is None:a['infrastructure_errors']+=1;continue
  for k,v in counts.items():a[k]=max(a.get(k,0),v) if k=='max_live_result_rows' else a.get(k,0)+int(v)
  check=checks[row['mode']][case['family']]
  for k in ('checked_prefixes','consistent_prefixes'):check[k]+=stats[k]
  valid=stats['first_failure'] is None;check['consistent_histories']+=valid;check['inconsistent_histories']+=not valid
  check['states'].update(stats['states']);check['transitions'].update(stats['transitions'])
  failure=stats['first_failure'];current=check['shortest_observed_failure']
  rank=lambda v:(v['operation_count'],v['boundary_count'],v['case_id'])
  if failure is not None and (current is None or rank(failure)<rank(current)):check['shortest_observed_failure']=failure
 if len(keys)!=3372 or keys!={(c['case_id'],m) for c in cases for m in MODES}:raise ValueError('complete 3372-history grid required')
 for arm in checks.values():
  for check in arm.values():
   check['unique_observable_states']=len(check.pop('states'));check['unique_labeled_transitions']=len(check.pop('transitions'))
 return arms,checks


def verify(path):
 path=Path(path);meta=json.loads(path.read_text());g=load_manifest()
 for k in ('base_commit','freeze_commit'):
  if not re.fullmatch('[0-9a-f]{40}',meta[k]):raise ValueError('invalid provenance identity')
 if subprocess.check_output(['git','rev-parse',meta['freeze_commit']+'^'],cwd=ROOT,text=True).strip()!=meta['base_commit']:raise ValueError('freeze parent changed')
 for n in (PROTOCOL,str(DATASET.relative_to(ROOT))):
  if subprocess.check_output(['git','show',meta['freeze_commit']+':'+n],cwd=ROOT)!=(ROOT/n).read_bytes():raise ValueError('frozen grammar/protocol changed')
 if hashlib.sha256(DATASET.read_bytes()).hexdigest()!=meta['dataset_sha256'] or set(meta['source_sha256'])!=set(SOURCES):raise ValueError('source or manifest coverage changed')
 for n,h in meta['source_sha256'].items():
  if hashlib.sha256((ROOT/n).read_bytes()).hexdigest()!=h:raise ValueError('source identity changed: '+n)
  if n in INHERITED and subprocess.check_output(['git','show',meta['base_commit']+':'+n],cwd=ROOT)!=(ROOT/n).read_bytes():raise ValueError('inherited implementation/reference changed')
 if type(meta['results_file']) is not str or Path(meta['results_file']).name!=meta['results_file']:raise ValueError('raw filename required')
 raw=path.parent/meta['results_file']
 if hashlib.sha256(raw.read_bytes()).hexdigest()!=meta['results_sha256']:raise ValueError('compressed raw identity changed')
 with gzip.open(raw,'rt',encoding='utf-8') as stream:arms,checks=recount((json.loads(line) for line in stream),g)
 if not same(arms,meta['summary']):raise ValueError('summary disagrees with independent reconstruction')
 groups=[a for arm in arms.values() for a in arm.values()];safe=arms['atomic_floor']
 criteria=dict(complete_evidence=all(a['infrastructure_errors']==0 for a in groups),
  supported_execution=all(all(a.get(k,1)==0 for k in ('caller_errors','transport_response_errors','publication_failures')) and a.get('actual_completed')==a['cases'] and a.get('publication_queries_inert')==a['cases'] for a in groups),
  atomic_membership_and_bounds=all(all(a.get(k,1)==0 for k in ('retired_decisions','retired_grants','rebound_ids','stale_result_snapshots','result_bound_violations')) and a.get('max_live_result_rows',3)<=2 for a in safe.values()),
  atomic_prefix_consistency=all(c['inconsistent_histories']==0 and c['consistent_histories']==safe[f]['cases'] and c['checked_prefixes']==c['consistent_prefixes'] for f,c in checks['atomic_floor'].items()),
  weak_counterexamples_retained=checks['erase_only']['sequence']['inconsistent_histories']>0 and checks['cached_floor']['overlap']['inconsistent_histories']>0)
 return dict(summary=arms,prefix_checks=checks,criteria=criteria,all_criteria_passed=all(criteria.values()))

if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('metadata',type=Path);a=p.parse_args();r=verify(a.metadata);print(json.dumps(r,indent=2,ensure_ascii=False));raise SystemExit(0 if r['all_criteria_passed'] else 1)
