"""Independent stdlib replay of recovery request decisions, receipts and replies."""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path
import re
import subprocess

ROOT=Path(__file__).resolve().parents[1]
MODES=('current_only','separate_receipt','atomic_receipt')
SCENARIOS=('quiet_retry','exit_before_decision','exit_after_decision','exit_before_reply','later_replacement_after_loss','target_closes_after_loss',
           'overlap_lookup_same','overlap_lookup_changed','receipt_gap_same','receipt_gap_changed','first_conflict_then_applicable','owner_reuse_after_loss')
DATASET=ROOT/'experiments/tasks/request-eval-v1/tasks.json'
SOURCES=tuple(sorted(str(p.relative_to(ROOT)) for p in (ROOT/'src').glob('*.py'))) + (
    'src/reclamation/store.py','src/recovery_requests/store.py','experiments/run_resume_comparison.py','experiments/resume_worker.py',
    'experiments/request_worker.py','experiments/run_request_comparison.py','experiments/verify_request_results.py','tests/test_requests.py','docs/REQUEST_PROTOCOL.md')


def same(a,b):return json.dumps(a,sort_keys=True,ensure_ascii=False,separators=(',',':'))==json.dumps(b,sort_keys=True,ensure_ascii=False,separators=(',',':'))
def digest(v):return None if v is None else hashlib.sha256(v.encode('utf-8')).hexdigest()
def pair(v):return {k:v[k] for k in ('owner','token')}
def fields(v):return {k:v[k] for k in ('request_id','expected_token','owner')}
def reply(status,request,outcome=None):return dict(status=status,request_id=request['request_id'],**({} if outcome is None else {'outcome':outcome}))


def load_manifest(path=DATASET):
    doc=json.loads(Path(path).read_text());cases=doc.get('cases',[])
    if set(doc)!={'schema_version','cases'} or doc['schema_version']!='request-eval-v1' or len(cases)!=24 or len({c['case_id'] for c in cases})!=24 or {(c['scenario'],c['pattern']) for c in cases}!={(s,p) for s in SCENARIOS for p in ('ascii_revoked','unicode_empty')}:raise ValueError('manifest grid changed')
    for c in cases:
        if set(c)!={'case_id','scenario','pattern','seeds','steps'} or len(c['seeds'])!=2:raise ValueError('case schema changed')
        generations=[]
        for step in c['steps']:
            if step['op']=='start':
                generations.append(step['generation']);r=step['request']
                if set(r)!={'request_id','expected_token','owner'} or type(r['request_id']) is not str or not r['request_id'] or any(type(r[k]) is not int or not 1<=r[k]<=2**63-1 for k in ('expected_token','owner')):raise ValueError('exact request types required')
                if len(step['pauses'])!=len(set(step['pauses'])) or any(s not in ('after_lookup','before_decision_commit','after_decision_commit','before_reply') for s in step['pauses']):raise ValueError('pause declaration changed')
        if generations!=list(range(1,len(generations)+1)) or any(type(g) is not int for g in generations):raise ValueError('generation sequence changed')
    return cases


class Model:
    def __init__(self,case,mode):
        self.mode=mode;self.epoch=1;self.revision=1;self.value='approved=version-a\n';self.approval=digest(self.value)
        self.lease=dict(policy='transactional_fence',owner=1,token=1);self.grants=[dict(token=1,owner=1,previous=0)]
        self.receipts=[];self.summaries=[];self.effects=[];self.witnesses=[];self.migration=None;self.lease_effect=None
        self.records={};self.decisions=[];self.first={};self.writer=None
        for request in case['seeds']:
            self.revision+=1;value=request['content_utf8'];self.approval=digest(value)
            if value is not None:self.value=value
            effect=dict(revision=self.revision,epoch=1,request_id=request['request_id'],operation='revoke' if value is None else 'update',approved_sha256=self.approval)
            self.effects.append(effect);self.receipts.append({**effect,'payload_utf8':value})
            self.witnesses.append(dict(revision=self.revision,requested_epoch=1,active_epoch=1,request_id=request['request_id']))
        self.receipts.sort(key=lambda r:r['request_id'])

    def lookup(self,request):return copy.deepcopy(self.records.get(request['request_id']))

    def prepare(self,request):
        if self.epoch==2:outcome=dict(status='completed',active_epoch=2);token=None
        elif self.lease['token']!=request['expected_token']:outcome=dict(status='conflict',lease=pair(self.lease));token=None
        else:
            token=self.lease['token']+1
            outcome=dict(status='reclaimed',lease=dict(owner=request['owner'],token=token),previous=request['expected_token'])
        return dict(ordinal=len(self.decisions)+1,**request,outcome=outcome,effect_token=token)

    def commit(self,witness,record):
        self.decisions.append(witness);self.first.setdefault(witness['request_id'],witness)
        if witness['effect_token'] is not None:
            self.lease=dict(policy='transactional_fence',owner=witness['owner'],token=witness['effect_token'])
            self.grants.append(dict(token=witness['effect_token'],owner=witness['owner'],previous=witness['expected_token']))
        if record is not None:self.records[record['request_id']]=record
        self.writer=None

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
                    request_mode=self.mode,recovery_receipts=[self.records[k] for k in sorted(self.records)],decisions=self.decisions))


class Cut(Exception):pass


class Invocation:
    def __init__(self,model,request,generation,pauses,child=True):
        self.m=model;self.request=request;self.generation=generation;self.pauses=pauses;self.child=child
        self.seq=0;self.pause=None;self.done=False;self.stream=self.run();self.answer=None

    def event(self,kind,**value):
        result=dict(seq=self.seq,kind=kind,**value);self.seq+=1;return result

    def checkpoint(self,stage):
        yield self.event('checkpoint',stage=stage)
        if stage not in self.pauses:return
        binding=dict(generation=self.generation,**self.request,stage=stage,role='replace');self.pause=binding
        action=yield self.event('paused',**binding);self.pause=None
        yield self.event('resumed',action=action,**binding)
        if action=='exit':
            if self.m.writer==self.generation:self.m.writer=None
            self.done=True;yield self.event('planned_exit',stage=stage,code=73);raise Cut

    def finish(self,answer):
        yield from self.checkpoint('before_reply');return answer

    def from_record(self,record):
        return reply('replayed',self.request,record['outcome']) if same(fields(record),self.request) else reply('request_conflict',self.request)

    def busy(self,at):
        yield self.event('writer_busy',at=at,sqlite_errorcode=5)
        return (yield from self.finish(dict(status='busy',request_id=self.request['request_id'],sqlite_errorcode=5)))

    def operation(self):
        m=self.m;r=self.request
        if m.mode=='separate_receipt':
            record=m.lookup(r);yield self.event('receipt_lookup',scope='separate',receipt=record)
            yield from self.checkpoint('after_lookup')
            if record is not None:return (yield from self.finish(self.from_record(record)))
        elif m.mode=='current_only':
            yield self.event('receipt_lookup',scope='none',receipt=None)
            yield from self.checkpoint('after_lookup')
        if m.writer is not None:return (yield from self.busy('decision'))
        m.writer=self.generation
        if m.mode=='atomic_receipt':
            record=m.lookup(r);yield self.event('receipt_lookup',scope='transaction',receipt=record)
            yield from self.checkpoint('after_lookup')
            if record is not None:
                m.writer=None;return (yield from self.finish(self.from_record(record)))
        witness=m.prepare(r);yield self.event('decision_prepared',**witness)
        record={**r,'outcome':witness['outcome']} if m.mode=='atomic_receipt' else None
        if record is not None:yield self.event('receipt_prepared',receipt=record)
        yield from self.checkpoint('before_decision_commit')
        m.commit(witness,record);yield self.event('decision_committed',**witness)
        yield from self.checkpoint('after_decision_commit')
        if m.mode=='separate_receipt':
            if m.writer is not None:return (yield from self.busy('receipt'))
            m.writer=self.generation;record=m.lookup(r);yield self.event('receipt_resolution',receipt=record)
            if record is not None:
                m.writer=None;return (yield from self.finish(self.from_record(record)))
            record={**r,'outcome':witness['outcome']};m.records[r['request_id']]=record;m.writer=None
            yield self.event('receipt_committed',receipt=record)
            return (yield from self.finish(reply('recorded',r,witness['outcome'])))
        return (yield from self.finish(reply('recorded' if m.mode=='atomic_receipt' else 'observed',r,witness['outcome'])))

    def run(self):
        if self.child:yield self.event('invocation_started',generation=self.generation,mode=self.m.mode,request=self.request,pauses=self.pauses)
        else:yield self.event('query_started',mode=self.m.mode,request=self.request)
        try:
            self.answer=yield from self.operation();yield self.event('caller_result',response=self.answer)
        except Cut:return
        self.done=True;yield self.event('worker_completed' if self.child else 'query_completed')

    def boundary(self,action=None):
        events=[];event=self.stream.send(action) if action is not None else next(self.stream)
        while True:
            events.append(event)
            if event['kind'] in ('paused','planned_exit','worker_completed','query_completed'):return events
            event=next(self.stream)


def authority(snapshot):return {k:v for k,v in snapshot.items() if k not in ('decisions','recovery_receipts','request_mode')}


def classify(request,answer,model,counts):
    if answer.get('status')=='busy':counts['busy']+=1;return 'busy'
    original=model.first.get(request['request_id'])
    if original is None:counts['transport_response_errors']+=1;return 'unsupported'
    if not same(request,fields(original)):
        if same(answer,reply('request_conflict',request)):return 'correct_conflict'
        counts['identity_failures']+=1;return 'identity_failure'
    if answer.get('status') in ('observed','recorded','replayed') and answer.get('request_id')==request['request_id'] and same(answer.get('outcome'),original['outcome']):return 'correct_original'
    if answer.get('status') in ('recorded','replayed'):counts['false_history']+=1;return 'false_history'
    counts['unresolved_originals']+=1;return 'unresolved_original'


def check_events(actual,expected,counts):
    if len(actual)!=len(expected):raise ValueError('event count changed')
    for left,right in zip(actual,expected):
        if not same(left,right):
            if left.get('kind')==right['kind']=='caller_result' and same(left.get('seq'),right['seq']):counts['transport_response_errors']+=1
            else:raise ValueError('event contradicts request/transaction history: '+right['kind'])


def evaluate(row,case):
    if any(not same(row[k],case[k]) for k in ('case_id','scenario','pattern','seeds')) or row['mode'] not in MODES:raise ValueError('case binding changed')
    if row['status']!='complete':
        if row['measures'] is not None or not row.get('error_type'):raise ValueError('unexplained infrastructure failure')
        return None
    model=Model(case,row['mode']);peers={};root=None
    counts=dict(lifetime_grants=0,distinct_requests=0,unjustified_grants=0,correct_original_queries=0,original_queries=0,
                correct_changed_queries=0,changed_queries=0,false_history=0,unresolved_originals=0,identity_failures=0,busy=0,caller_errors=0,
                transport_response_errors=0,query_authority_changes=0,planned_exits=0,normal_children=0,barriers=0,actual_completed=False,
                publication_replays=0,publication_conflicts=0,publication_failures=0,publication_queries_inert=True)
    if not same(row['initial'],model.snapshot()) or len(row['steps'])!=len(case['steps']):raise ValueError('initial fixture or action count changed')
    for action,step in zip(case['steps'],row['steps']):
        if not same(action,step['action']):raise ValueError('causal order changed')
        if action['op']=='migrate':
            expected=model.migrate(step['lease'])
            if not same(step['response'],expected):raise ValueError('closure response changed')
        else:
            generation=action['generation']
            if action['op']=='start':
                command=step['command']
                if len(command)!=12 or not command[0] or Path(command[1]).name!='request_worker.py':raise ValueError('worker command changed')
                flags=dict(zip(command[2::2],command[3::2]));root=flags.get('--root') if root is None else root
                if set(flags)!={'--root','--mode','--generation','--request','--pauses'} or flags['--root']!=root or flags['--mode']!=row['mode'] or flags['--generation']!=str(generation) or flags['--pauses']!=','.join(action['pauses']) or not same(json.loads(flags['--request']),action['request']) or generation in peers:raise ValueError('request command binding changed')
                peer=Invocation(model,action['request'],generation,action['pauses']);peers[generation]=peer;expected=peer.boundary()
            elif action['op']=='resume':
                peer=peers[generation]
                if peer.pause is None or not same(step['command'],dict(command=action['action'],**peer.pause)):raise ValueError('exact typed resume changed')
                expected=peer.boundary(action['action'])
            else:raise ValueError('unknown action')
            actual=step['events']
            if not same([json.loads(line) for line in step['stdout'].splitlines()],actual):raise ValueError('raw stream changed')
            check_events(actual,expected,counts)
            for e in actual:
                counts['barriers']+=e['kind']=='paused';counts['caller_errors']+=e['kind']=='caller_error'
                if e['kind']=='caller_result':classify(peer.request,e['response'],model,counts)
            last=expected[-1]['kind'];code=73 if last=='planned_exit' else 0 if last=='worker_completed' else None
            if not same(step['returncode'],code) or not same(step['stderr'],None if code is None else ''):raise ValueError('unmarked/failed process exit')
            counts['planned_exits']+=code==73;counts['normal_children']+=code==0
        if not same(step['snapshot'],model.snapshot()):raise ValueError('snapshot contradicts durable decision/grant/receipt history')
    if any(not p.done for p in peers.values()) or model.writer is not None or not same(row['settled'],model.snapshot()):raise ValueError('unsettled request history')
    originals=[fields(r) for r in model.first.values()];probe_index=0
    if len(row['probes'])!=4*len(originals):raise ValueError('actual-original probe denominator changed')
    for stage in ('before_close','after_close'):
        for original in originals:
            changed={**original,'owner':original['owner']+1}
            for kind,request in (('original',original),('changed',changed)):
                q=row['probes'][probe_index];probe_index+=1
                if q['stage']!=stage or q['kind']!=kind or not same(q['request'],request) or not same(q['before'],model.snapshot()):raise ValueError('probe identity or causal prefix changed')
                before=model.snapshot();invocation=Invocation(model,request,0,[],child=False);expected=invocation.boundary()
                check_events(q['events'],expected,counts)
                result=next(e['response'] for e in q['events'] if e['kind']=='caller_result')
                if not same(q['response'],result) or not same(q['after'],model.snapshot()):raise ValueError('probe stream/state mismatch')
                classification=classify(request,result,model,counts)
                if kind=='original':counts['original_queries']+=1;counts['correct_original_queries']+=classification=='correct_original'
                else:counts['changed_queries']+=1;counts['correct_changed_queries']+=classification=='correct_conflict'
                counts['query_authority_changes']+=not same(authority(before),authority(model.snapshot()))
        if stage=='before_close':
            closure=row['closure'];expected=model.migrate(closure['lease'])
            if not same(closure['response'],expected) or not same(closure['snapshot'],model.snapshot()):raise ValueError('closure changed authority or history')
    if not same(row['final'],model.snapshot()):raise ValueError('final durable state changed')
    if len(row['publication_queries'])!=len(case['seeds']):raise ValueError('publication query denominator changed')
    for req,q in zip(case['seeds'],row['publication_queries']):
        if not same(req,q['request']):raise ValueError('publication query identity changed')
        original=next(r for r in model.effects if r['request_id']==req['request_id'])
        expected=dict(status='replayed',epoch=1,request_id=original['request_id'],revision=original['revision'],approved_sha256=original['approved_sha256'])
        replay=same(q['original'],expected);conflict=same(q['changed'],dict(status='conflict',epoch=1,request_id=req['request_id'],revision=None,approved_sha256=None))
        counts['publication_replays']+=replay;counts['publication_conflicts']+=conflict;counts['publication_failures']+=not(replay and conflict)
    counts.update(lifetime_grants=len(model.grants),distinct_requests=len(model.first),actual_completed=model.epoch==2,
                  publication_queries_inert=same(row['final'],row['after_publication_queries']),
                  unjustified_grants=sum(d['effect_token'] is not None and d['ordinal']!=model.first[d['request_id']]['ordinal'] for d in model.decisions))
    if not same(counts,row['measures']):raise ValueError('independent outcome counts disagree')
    return counts


def recount(rows,cases):
    declarations={c['case_id']:c for c in cases};keys=[(r['case_id'],r['mode']) for r in rows]
    if len(keys)!=72 or len(set(keys))!=72 or set(keys)!={(c,m) for c in declarations for m in MODES}:raise ValueError('full 72-record grid required')
    arms={m:dict(cases=0,infrastructure_errors=0) for m in MODES}
    for row in rows:
        arm=arms[row['mode']];arm['cases']+=1;counts=evaluate(row,declarations[row['case_id']])
        if counts is None:arm['infrastructure_errors']+=1;continue
        for k,v in counts.items():arm[k]=arm.get(k,0)+int(v)
    return arms


def verify(path):
    path=Path(path);meta=json.loads(path.read_text());cases=load_manifest()
    for key in ('base_commit','freeze_commit'):
        if not re.fullmatch('[0-9a-f]{40}',meta[key]):raise ValueError('invalid provenance commit')
    if subprocess.check_output(['git','rev-parse',meta['freeze_commit']+'^'],cwd=ROOT,text=True).strip()!=meta['base_commit']:raise ValueError('freeze parent changed')
    for name in ('docs/REQUEST_PROTOCOL.md',str(DATASET.relative_to(ROOT))):
        if subprocess.check_output(['git','show',meta['freeze_commit']+':'+name],cwd=ROOT)!=(ROOT/name).read_bytes():raise ValueError('frozen identity changed')
    if hashlib.sha256(DATASET.read_bytes()).hexdigest()!=meta['dataset_sha256'] or set(meta['source_sha256'])!=set(SOURCES):raise ValueError('source/manifest coverage changed')
    for name,hash_value in meta['source_sha256'].items():
        if hashlib.sha256((ROOT/name).read_bytes()).hexdigest()!=hash_value:raise ValueError('source hash changed: '+name)
        if (name.startswith('src/') and name.count('/')==1 or name=='src/reclamation/store.py') and subprocess.check_output(['git','show',meta['base_commit']+':'+name],cwd=ROOT)!=(ROOT/name).read_bytes():raise ValueError('inherited mechanism changed')
    raw=path.parent/meta['results_file']
    if raw.parent!=path.parent or hashlib.sha256(raw.read_bytes()).hexdigest()!=meta['results_sha256']:raise ValueError('raw identity changed')
    arms=recount([json.loads(line) for line in raw.read_text().splitlines()],cases)
    if not same(arms,meta['summary']):raise ValueError('summary changed')
    safe=arms['atomic_receipt']
    criteria=dict(complete_evidence=all(a['infrastructure_errors']==0 for a in arms.values()),
                  atomic_request_identity=safe.get('unjustified_grants',1)==safe.get('identity_failures',1)==0,
                  atomic_historical_answers=safe.get('false_history',1)==safe.get('unresolved_originals',1)==0 and safe.get('correct_original_queries',-1)==safe.get('original_queries',-2) and safe.get('correct_changed_queries',-1)==safe.get('changed_queries',-2),
                  supported_execution=all(a.get('caller_errors',1)==a.get('transport_response_errors',1)==0 for a in arms.values()),
                  retained_authority_and_publications=all(a.get('query_authority_changes',1)==a.get('publication_failures',1)==0 and a.get('publication_queries_inert')==24 for a in arms.values()))
    return dict(summary=arms,criteria=criteria,all_criteria_passed=all(criteria.values()))


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('metadata',type=Path);a=p.parse_args();r=verify(a.metadata);print(json.dumps(r,indent=2));raise SystemExit(0 if r['all_criteria_passed'] else 1)
