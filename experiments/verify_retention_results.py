"""Independent stdlib reconstruction of epoch retirement and bounded results."""
from __future__ import annotations
import argparse
import copy
import hashlib
import gzip
import json
from pathlib import Path
import re
import subprocess

ROOT=Path(__file__).resolve().parents[1]
MODES=('erase_only','cached_floor','atomic_floor')
CAPACITY=2
SCENARIOS=('quiet_retirement','exit_before_rotation','exit_after_rotation','exit_before_rotation_reply','stale_admission_unused','stale_admission_changed','lookup_holds_writer','rotation_holds_writer','reply_after_retirement','capacity_and_reuse','multiple_rotations','future_namespace','closed_target_retirement','conflict_retirement','decision_rollback_then_retire','lost_result_then_retire')
DATASET=ROOT/'experiments/tasks/retention-eval-v1/tasks.json'
PROTOCOL='docs/RETENTION_PROTOCOL.md'
INHERITED=tuple(sorted(str(p.relative_to(ROOT)) for p in (ROOT/'src').glob('*.py')))+('src/reclamation/store.py','src/recovery_requests/store.py')
SOURCES=INHERITED+('src/recovery_retention/store.py','experiments/run_resume_comparison.py','experiments/resume_worker.py',
 'experiments/retention_worker.py','experiments/run_retention_comparison.py','experiments/verify_retention_results.py','tests/test_retention.py',PROTOCOL)

def same(a,b):return json.dumps(a,sort_keys=True,ensure_ascii=False,separators=(',',':'))==json.dumps(b,sort_keys=True,ensure_ascii=False,separators=(',',':'))
def digest(v):return None if v is None else hashlib.sha256(v.encode('utf-8')).hexdigest()
def pair(v):return {k:v[k] for k in ('owner','token')}
def key(r):return (r['recovery_epoch'],r['request_id'])
def fields(r):return {k:r[k] for k in ('recovery_epoch','request_id','expected_token','owner')}
def reply(status,r,**v):return dict(status=status,recovery_epoch=r['recovery_epoch'],request_id=r['request_id'],**v)

def positive(v):
 if type(v) is not int or not 1<=v<=2**63-1:raise ValueError('positive exact integer required')

def load_manifest(path=DATASET):
 doc=json.loads(Path(path).read_text());cases=doc.get('cases',[])
 if set(doc)!={'schema_version','capacity','cases'} or doc['schema_version']!='retention-eval-v1' or not same(doc['capacity'],2) or len(cases)!=32 or len({c['case_id'] for c in cases})!=32 or {(c['scenario'],c['pattern']) for c in cases}!={(s,p) for s in SCENARIOS for p in ('ascii_revoked','unicode_empty')}:raise ValueError('manifest grid changed')
 for c in cases:
  if set(c)!={'case_id','scenario','pattern','seeds','steps'} or c['case_id']!=c['scenario']+'-'+c['pattern'] or len(c['seeds'])!=2:raise ValueError('case schema changed')
  generations=[];live=set()
  for s in c['steps']:
   if s['op']=='start':
    if set(s)!={'op','role','generation','request','pauses'} or s['role'] not in ('replace','advance'):raise ValueError('start schema changed')
    positive(s['generation']);generations.append(s['generation']);r=s['request'];role=s['role']
    if role=='replace':
     if set(r)!={'recovery_epoch','request_id','expected_token','owner'} or type(r['request_id']) is not str or not 1<=len(r['request_id'])<=128 or any(ord(ch)<32 or ord(ch)==127 for ch in r['request_id']):raise ValueError('exact request required')
     r['request_id'].encode('utf-8')
     for k in ('recovery_epoch','expected_token','owner'):positive(r[k])
     stages=('after_admission','after_lookup','before_decision_commit','after_decision_commit','before_reply')
    else:
     if set(r)!={'expected_epoch'}:raise ValueError('advance schema changed')
     positive(r['expected_epoch']);stages=('before_rotation_commit','after_rotation_commit','before_reply')
    if type(s['pauses']) is not list or len(s['pauses'])!=len(set(s['pauses'])) or any(v not in stages for v in s['pauses']):raise ValueError('pause schema changed')
   elif s['op']=='resume':
    if set(s)!={'op','generation','action'} or type(s['generation']) is not int or s['generation'] not in generations or s['action'] not in ('continue','exit'):raise ValueError('resume schema changed')
   elif s!={'op':'migrate'}:raise ValueError('action schema changed')
  if generations!=list(range(1,len(generations)+1)):raise ValueError('generation order changed')
 return cases

class Model:
    def __init__(self,case,mode):
        self.mode=mode;self.epoch=1;self.revision=1;self.value='approved=version-a\n';self.approval=digest(self.value)
        self.lease=dict(policy='transactional_fence',owner=1,token=1);self.grants=[dict(token=1,owner=1,previous=0)]
        self.receipts=[];self.summaries=[];self.effects=[];self.witnesses=[];self.migration=None;self.lease_effect=None
        self.records={};self.decisions=[];self.first={};self.writer=None;self.floor=1;self.retirements=[]
        for request in case['seeds']:
            self.revision+=1;value=request['content_utf8'];self.approval=digest(value)
            if value is not None:self.value=value
            effect=dict(revision=self.revision,epoch=1,request_id=request['request_id'],operation='revoke' if value is None else 'update',approved_sha256=self.approval)
            self.effects.append(effect);self.receipts.append({**effect,'payload_utf8':value})
            self.witnesses.append(dict(revision=self.revision,requested_epoch=1,active_epoch=1,request_id=request['request_id']))
        self.receipts.sort(key=lambda r:r['request_id'])

    def lookup(self,r):return copy.deepcopy(self.records.get(key(r)))

    def prepare(self,r):
        if self.epoch==2:outcome=dict(status='completed',active_epoch=2);token=None
        elif self.lease['token']!=r['expected_token']:outcome=dict(status='conflict',lease=pair(self.lease));token=None
        else:
            token=self.lease['token']+1;outcome=dict(status='reclaimed',lease=dict(owner=r['owner'],token=token),previous=r['expected_token'])
        return dict(ordinal=len(self.decisions)+1,**r,outcome=outcome,effect_token=token,active_recovery_epoch=self.floor)

    def commit(self,d):
        self.decisions.append(copy.deepcopy(d));self.first.setdefault(key(d),copy.deepcopy(d))
        if d['effect_token'] is not None:
            self.lease=dict(policy='transactional_fence',owner=d['owner'],token=d['effect_token'])
            self.grants.append(dict(token=d['effect_token'],owner=d['owner'],previous=d['expected_token']))
        self.records[key(d)]=dict(**fields(d),outcome=copy.deepcopy(d['outcome']));self.writer=None

    def rotation(self):
        return dict(ordinal=len(self.retirements)+1,from_epoch=self.floor,to_epoch=self.floor+1,removed_receipts=sum(k[0]<=self.floor for k in self.records))

    def advance(self,witness):
        self.floor+=1;self.records={k:v for k,v in self.records.items() if k[0]>=self.floor};self.retirements.append(copy.deepcopy(witness));self.writer=None

    def migrate(self,lease):
        if not same(lease,pair(self.lease)) or self.writer is not None:raise ValueError('migration did not use current granted authority')
        if self.epoch==2:return dict(status='completed',active_epoch=2)
        count=len(self.receipts);self.epoch=2
        self.summaries=[dict(epoch=r['epoch'],request_id=r['request_id'],operation=r['operation'],payload_sha256=digest(r['payload_utf8']),revision=r['revision']) for r in self.receipts];self.receipts=[]
        self.migration=dict(target_epoch=2,selected_revision=self.revision,write_revision=self.revision,selected_count=count,write_count=count)
        self.lease_effect=dict(owner=lease['owner'],token=lease['token'],current_owner=lease['owner'],current_token=lease['token'],authorized=True)
        return dict(status='migrated',active_epoch=2,**lease)

    def snapshot(self):
        return copy.deepcopy(dict(state=dict(revision=self.revision,approved_sha256=self.approval,content_utf8=self.value),active_epoch=self.epoch,
          effects=self.effects,receipts=self.receipts,summaries=self.summaries,publication_witnesses=self.witnesses,migration_witness=self.migration,
          summary_columns=['epoch','request_id','operation','payload_sha256','revision'],lease=self.lease,grants=self.grants,lease_effect=self.lease_effect,
          retention_mode=self.mode,capacity=2,active_recovery_epoch=self.floor,retained_results=[self.records[k] for k in sorted(self.records)],decisions=self.decisions,retirements=self.retirements))


class Cut(Exception):pass

class Invocation:
 def __init__(self,m,role,r,generation,pauses,child=True):
  self.m=m;self.role=role;self.request=r;self.generation=generation;self.pauses=pauses;self.child=child
  self.seq=0;self.pause=None;self.done=False;self.answer=None;self.stream=self.run()
 def event(self,kind,**v):
  e=dict(seq=self.seq,kind=kind,**copy.deepcopy(v));self.seq+=1;return e
 def checkpoint(self,stage):
  yield self.event('checkpoint',stage=stage)
  if stage not in self.pauses:return
  binding=dict(generation=self.generation,**self.request,stage=stage,role=self.role);self.pause=binding
  action=yield self.event('paused',**binding);self.pause=None
  yield self.event('resumed',action=action,**binding)
  if action=='exit':
   if self.m.writer==self.generation:self.m.writer=None
   self.done=True;yield self.event('planned_exit',stage=stage,code=73);raise Cut
 def finish(self,answer):
  yield from self.checkpoint('before_reply');return answer
 def admit(self,scope):
  m=self.m;r=self.request
  fate='future_epoch' if r['recovery_epoch']>m.floor else 'retired' if r['recovery_epoch']<m.floor and m.mode!='erase_only' else 'accepted'
  answer=None if fate=='accepted' else reply(fate,r,active_recovery_epoch=m.floor)
  yield self.event('admission_checked',scope=scope,active_recovery_epoch=m.floor,fate=fate)
  yield from self.checkpoint('after_admission');return answer
 def busy(self):
  yield self.event('writer_busy',role=self.role,sqlite_errorcode=5)
  answer=reply('busy',self.request,sqlite_errorcode=5) if self.role=='replace' else dict(status='busy',sqlite_errorcode=5)
  return (yield from self.finish(answer))
 def replace(self):
  m=self.m;r=self.request
  if m.mode!='atomic_floor':
   denied=yield from self.admit('separate')
   if denied is not None:return (yield from self.finish(denied))
  if m.writer is not None:return (yield from self.busy())
  m.writer=self.generation
  if m.mode=='atomic_floor':
   denied=yield from self.admit('transaction')
   if denied is not None:
    m.writer=None;return (yield from self.finish(denied))
  record=m.lookup(r);yield self.event('receipt_lookup',receipt=record)
  yield from self.checkpoint('after_lookup')
  if record is not None:
   m.writer=None;answer=reply('replayed',r,outcome=record['outcome']) if same(fields(record),r) else reply('request_conflict',r)
   return (yield from self.finish(answer))
  count=sum(k[0]==r['recovery_epoch'] for k in m.records)
  yield self.event('capacity_checked',count=count,capacity=2)
  if count>=2:
   m.writer=None;return (yield from self.finish(reply('capacity_exhausted',r,capacity=2)))
  witness=m.prepare(r);yield self.event('decision_prepared',**witness)
  yield self.event('receipt_prepared',receipt=dict(**r,outcome=witness['outcome']))
  yield from self.checkpoint('before_decision_commit')
  m.commit(witness);yield self.event('decision_committed',**witness)
  yield from self.checkpoint('after_decision_commit')
  return (yield from self.finish(reply('recorded',r,outcome=witness['outcome'])))
 def rotate(self):
  m=self.m;r=self.request
  if m.writer is not None:return (yield from self.busy())
  m.writer=self.generation;yield self.event('rotation_view',active_recovery_epoch=m.floor)
  if m.floor!=r['expected_epoch']:
   m.writer=None;return (yield from self.finish(dict(status='epoch_conflict',active_recovery_epoch=m.floor)))
  witness=m.rotation();yield self.event('rotation_prepared',**witness)
  yield from self.checkpoint('before_rotation_commit')
  m.advance(witness);yield self.event('rotation_committed',**witness)
  yield from self.checkpoint('after_rotation_commit')
  return (yield from self.finish(dict(status='advanced',previous_epoch=witness['from_epoch'],active_recovery_epoch=witness['to_epoch'],removed_receipts=witness['removed_receipts'])))
 def run(self):
  if self.child:yield self.event('invocation_started',generation=self.generation,mode=self.m.mode,role=self.role,request=self.request,pauses=self.pauses)
  else:yield self.event('query_started',mode=self.m.mode,role=self.role,request=self.request)
  try:
   self.answer=yield from (self.replace() if self.role=='replace' else self.rotate());yield self.event('caller_result',response=self.answer)
  except Cut:return
  self.done=True;yield self.event('worker_completed' if self.child else 'query_completed')
 def boundary(self,action=None):
  events=[];e=self.stream.send(action) if action is not None else next(self.stream)
  while True:
   events.append(e)
   if e['kind'] in ('paused','planned_exit','worker_completed','query_completed'):return events
   e=next(self.stream)


def check_events(actual,expected,counts):
 if len(actual)!=len(expected):raise ValueError('event count changed')
 for left,right in zip(actual,expected):
  if not same(left,right):
   if left.get('kind')==right['kind']=='caller_result' and same(left.get('seq'),right['seq']):counts['transport_response_errors']+=1
   else:raise ValueError('event contradicts epoch/transaction history: '+right['kind'])


def evaluate(row,case):
 if any(not same(row[k],case[k]) for k in ('case_id','scenario','pattern','seeds')) or row['mode'] not in MODES:raise ValueError('case binding changed')
 if row['status']!='complete':
  if row['measures'] is not None or not row.get('error_type'):raise ValueError('unexplained infrastructure failure')
  return None
 m=Model(case,row['mode']);peers={};root=None
 counts=dict(lifetime_grants=0,decisions=0,retirements=0,retired_decisions=0,retired_grants=0,rebound_ids=0,max_live_result_rows=0,
  result_bound_violations=0,stale_result_snapshots=0,snapshot_observations=0,retired_queries=0,correct_retired_queries=0,retired_query_state_changes=0,
  fresh_requests=0,fresh_request_failures=0,current_queries=0,current_query_failures=0,capacity_queries=0,capacity_failures=0,
  busy=0,caller_errors=0,transport_response_errors=0,planned_exits=0,normal_children=0,barriers=0,actual_completed=False,
  publication_replays=0,publication_conflicts=0,publication_failures=0,publication_queries_inert=True)
 def observe(actual):
  expected=m.snapshot()
  if not same(actual,expected):raise ValueError('snapshot contradicts retirement/result/grant history')
  size=len(m.records);counts['snapshot_observations']+=1;counts['max_live_result_rows']=max(counts['max_live_result_rows'],size)
  counts['result_bound_violations']+=size>2;counts['stale_result_snapshots']+=any(k[0]<m.floor for k in m.records)
 def query(q,role,r):
  before=m.snapshot()
  if not same(q['request'],r) or q['role']!=role or not same(q['before'],before):raise ValueError('query identity or causal prefix changed')
  inv=Invocation(m,role,r,0,[],False);expected=inv.boundary();check_events(q['events'],expected,counts)
  answer=next(e['response'] for e in q['events'] if e['kind']=='caller_result')
  if not same(q['response'],answer):raise ValueError('query response/stream mismatch')
  counts['busy']+=answer.get('status')=='busy';observe(q['after']);return answer,before
 observe(row['initial'])
 if len(row['steps'])!=len(case['steps']):raise ValueError('action count changed')
 for action,step in zip(case['steps'],row['steps']):
  if not same(action,step['action']):raise ValueError('action order changed')
  if action['op']=='migrate':
   expected=m.migrate(step['lease'])
   if not same(step['response'],expected):raise ValueError('migration response changed')
  else:
   g=action['generation']
   if action['op']=='start':
    cmd=step['command']
    if len(cmd)!=14 or not cmd[0] or Path(cmd[1]).name!='retention_worker.py':raise ValueError('worker command changed')
    flags=dict(zip(cmd[2::2],cmd[3::2]));root=flags.get('--root') if root is None else root
    if set(flags)!={'--root','--mode','--role','--generation','--request','--pauses'} or flags['--root']!=root or flags['--mode']!=row['mode'] or flags['--role']!=action['role'] or flags['--generation']!=str(g) or flags['--pauses']!=','.join(action['pauses']) or not same(json.loads(flags['--request']),action['request']) or g in peers:raise ValueError('command binding changed')
    peer=Invocation(m,action['role'],action['request'],g,action['pauses']);peers[g]=peer;expected=peer.boundary()
   elif action['op']=='resume':
    peer=peers[g]
    if peer.pause is None or not same(step['command'],dict(command=action['action'],**peer.pause)):raise ValueError('exact typed resume changed')
    expected=peer.boundary(action['action'])
   else:raise ValueError('unknown action')
   actual=step['events']
   if not same([json.loads(line) for line in step['stdout'].splitlines()],actual):raise ValueError('raw stream changed')
   check_events(actual,expected,counts)
   for e in actual:
    counts['barriers']+=e['kind']=='paused';counts['caller_errors']+=e['kind']=='caller_error'
    if e['kind']=='caller_result':counts['busy']+=e['response'].get('status')=='busy'
   last=expected[-1]['kind'];code=73 if last=='planned_exit' else 0 if last=='worker_completed' else None
   if not same(step['returncode'],code) or not same(step['stderr'],None if code is None else ''):raise ValueError('unmarked/failed process exit')
   counts['planned_exits']+=code==73;counts['normal_children']+=code==0
  observe(step['snapshot'])
 if any(not p.done for p in peers.values()) or m.writer is not None:raise ValueError('unsettled history')
 observe(row['settled']);originals=[fields(d) for d in m.first.values()]
 query(row['final_rotation'],'advance',dict(expected_epoch=m.floor))
 retired=[]
 for original in originals:
  retired.append(('original',original));retired.append(('changed',{**original,'owner':original['owner']+1,'expected_token':m.lease['token']}))
 retired.append(('unused',dict(recovery_epoch=1,request_id='never-used',expected_token=m.lease['token'],owner=99)))
 if len(row['retired_probes'])!=2*len(retired) or len(row['fresh'])!=2 or len(row['current_probes'])!=10:raise ValueError('probe denominator changed')
 retired_i=current_i=0;fresh=[]
 for stage in ('before_close','after_close'):
  for kind,r in retired:
   q=row['retired_probes'][retired_i];retired_i+=1
   if q['stage']!=stage or q['kind']!=kind:raise ValueError('retired query order changed')
   answer,before=query(q,'replace',r);counts['retired_queries']+=1
   counts['correct_retired_queries']+=same(answer,reply('retired',r,active_recovery_epoch=before['active_recovery_epoch']))
   counts['retired_query_state_changes']+=not same(before,m.snapshot())
  if stage=='before_close':
   for i,q in enumerate(row['fresh'],1):
    r=dict(recovery_epoch=m.floor,request_id='fresh-'+str(i),expected_token=m.lease['token'],owner=100+i)
    answer,_=query(q,'replace',r);fresh.append(r);counts['fresh_requests']+=1
    counts['fresh_request_failures']+=not same(answer,reply('recorded',r,outcome=m.first[key(r)]['outcome']))
  for original in fresh:
   for kind,r in (('original',original),('changed',{**original,'owner':original['owner']+1})):
    q=row['current_probes'][current_i];current_i+=1
    if q['stage']!=stage or q['kind']!=kind:raise ValueError('current query order changed')
    answer,before=query(q,'replace',r);counts['current_queries']+=1
    expected=reply('request_conflict',r) if kind=='changed' else reply('replayed',r,outcome=m.first[key(r)]['outcome'])
    counts['current_query_failures']+=not same(answer,expected) or not same(before,m.snapshot())
  q=row['current_probes'][current_i];current_i+=1;r=dict(recovery_epoch=m.floor,request_id='overflow-current',expected_token=m.lease['token'],owner=103)
  if q['stage']!=stage or q['kind']!='overflow':raise ValueError('overflow order changed')
  answer,before=query(q,'replace',r);counts['current_queries']+=1;counts['capacity_queries']+=1
  ok=same(answer,reply('capacity_exhausted',r,capacity=2));counts['capacity_failures']+=not ok
  counts['current_query_failures']+=not ok or not same(before,m.snapshot())
  if stage=='before_close':
   c=row['closure'];answer=m.migrate(c['lease'])
   if not same(c['response'],answer):raise ValueError('closure changed authority')
   observe(c['snapshot'])
 observe(row['final'])
 if len(row['publication_queries'])!=len(case['seeds']):raise ValueError('publication denominator changed')
 for r,q in zip(case['seeds'],row['publication_queries']):
  if not same(r,q['request']):raise ValueError('publication identity changed')
  effect=next(e for e in m.effects if e['request_id']==r['request_id'])
  ok=same(q['original'],dict(status='replayed',epoch=1,request_id=r['request_id'],revision=effect['revision'],approved_sha256=effect['approved_sha256']))
  conflict=same(q['changed'],dict(status='conflict',epoch=1,request_id=r['request_id'],revision=None,approved_sha256=None))
  counts['publication_replays']+=ok;counts['publication_conflicts']+=conflict;counts['publication_failures']+=not(ok and conflict)
 observe(row['after_publication_queries'])
 counts.update(lifetime_grants=len(m.grants),decisions=len(m.decisions),retirements=len(m.retirements),actual_completed=m.epoch==2,
  publication_queries_inert=same(row['final'],row['after_publication_queries']),
  retired_decisions=sum(d['recovery_epoch']<d['active_recovery_epoch'] for d in m.decisions),
  retired_grants=sum(d['recovery_epoch']<d['active_recovery_epoch'] and d['effect_token'] is not None for d in m.decisions),
  rebound_ids=sum(d['ordinal']!=m.first[key(d)]['ordinal'] for d in m.decisions))
 if not same(counts,row['measures']):raise ValueError('independent counts disagree')
 return counts


def recount(rows,cases):
 declarations={c['case_id']:c for c in cases};keys=[(r['case_id'],r['mode']) for r in rows]
 if len(keys)!=96 or len(set(keys))!=96 or set(keys)!={(c,m) for c in declarations for m in MODES}:raise ValueError('full 96-record grid required')
 arms={m:dict(cases=0,infrastructure_errors=0) for m in MODES}
 for row in rows:
  arm=arms[row['mode']];arm['cases']+=1;counts=evaluate(row,declarations[row['case_id']])
  if counts is None:arm['infrastructure_errors']+=1;continue
  for k,v in counts.items():arm[k]=max(arm.get(k,0),v) if k=='max_live_result_rows' else arm.get(k,0)+int(v)
 return arms


def verify(path):
 path=Path(path);meta=json.loads(path.read_text());cases=load_manifest()
 for k in ('base_commit','freeze_commit'):
  if not re.fullmatch('[0-9a-f]{40}',meta[k]):raise ValueError('invalid provenance commit')
 if subprocess.check_output(['git','rev-parse',meta['freeze_commit']+'^'],cwd=ROOT,text=True).strip()!=meta['base_commit']:raise ValueError('freeze parent changed')
 for n in (PROTOCOL,str(DATASET.relative_to(ROOT))):
  if subprocess.check_output(['git','show',meta['freeze_commit']+':'+n],cwd=ROOT)!=(ROOT/n).read_bytes():raise ValueError('frozen identity changed')
 if hashlib.sha256(DATASET.read_bytes()).hexdigest()!=meta['dataset_sha256'] or set(meta['source_sha256'])!=set(SOURCES):raise ValueError('source/manifest coverage changed')
 for n,h in meta['source_sha256'].items():
  if hashlib.sha256((ROOT/n).read_bytes()).hexdigest()!=h:raise ValueError('source hash changed: '+n)
  if n in INHERITED and subprocess.check_output(['git','show',meta['base_commit']+':'+n],cwd=ROOT)!=(ROOT/n).read_bytes():raise ValueError('inherited mechanism changed')
 if type(meta['results_file']) is not str or Path(meta['results_file']).name!=meta['results_file']:raise ValueError('raw filename required')
 raw=path.parent/meta['results_file']
 if hashlib.sha256(raw.read_bytes()).hexdigest()!=meta['results_sha256']:raise ValueError('raw identity changed')
 encoded=raw.read_bytes();decoded=gzip.decompress(encoded) if raw.suffix=='.gz' else encoded
 arms=recount([json.loads(line) for line in decoded.decode('utf-8').splitlines()],cases)
 if not same(arms,meta['summary']):raise ValueError('summary changed')
 safe=arms['atomic_floor']
 criteria=dict(complete_evidence=all(a['infrastructure_errors']==0 for a in arms.values()),
  atomic_retirement=all(safe.get(k,1)==0 for k in ('retired_decisions','retired_grants','rebound_ids','stale_result_snapshots','result_bound_violations')) and safe.get('max_live_result_rows')==2,
  atomic_retired_rejection=safe.get('correct_retired_queries',-1)==safe.get('retired_queries',-2) and safe.get('retired_query_state_changes',1)==0,
  current_results_and_capacity=all(a.get('fresh_request_failures',1)==a.get('current_query_failures',1)==a.get('capacity_failures',1)==0 for a in arms.values()),
  supported_execution=all(a.get('caller_errors',1)==a.get('transport_response_errors',1)==0 for a in arms.values()),
  retained_publication_authority=all(a.get('publication_failures',1)==0 and a.get('publication_queries_inert')==32 and a.get('actual_completed')==32 for a in arms.values()))
 return dict(summary=arms,criteria=criteria,all_criteria_passed=all(criteria.values()))

if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('metadata',type=Path);a=p.parse_args();r=verify(a.metadata);print(json.dumps(r,indent=2));raise SystemExit(0 if r['all_criteria_passed'] else 1)
