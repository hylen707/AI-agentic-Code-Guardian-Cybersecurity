"""Independent stdlib model of explicit replacement, stale holders and effects."""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path
import re
import subprocess

ROOT=Path(__file__).resolve().parents[1]
MODES=('cached_permission','separate_fence','transactional_fence')
SCENARIOS=('no_reclaim','stale_before_select','reclaim_after_selection','reclaim_after_fence','reclaim_before_commit',
           'exit_before_commit','exit_after_commit','source_changed','aba_owner','stale_recovery_cas')
SOURCES=tuple(sorted(str(p.relative_to(ROOT)) for p in (ROOT/'src').glob('*.py'))) + (
    'src/reclamation/store.py','experiments/run_resume_comparison.py','experiments/resume_worker.py',
    'experiments/reclaim_worker.py','experiments/run_reclaim_comparison.py','experiments/verify_reclaim_results.py','tests/test_reclaim.py','docs/RECLAIM_PROTOCOL.md')
DATASET=ROOT/'experiments/tasks/reclaim-eval-v1/tasks.json'


def load_manifest(path=DATASET):
    doc=json.loads(Path(path).read_text())
    if set(doc)!={'schema_version','cases'} or doc['schema_version']!='reclaim-eval-v1':raise ValueError('manifest schema changed')
    cases=doc['cases']
    if len(cases)!=20 or len({c['case_id'] for c in cases})!=20 or {(c['scenario'],c['pattern']) for c in cases}!={(s,p) for s in SCENARIOS for p in ('updates','revocations')}:raise ValueError('manifest grid changed')
    for c in cases:
        if set(c)!={'case_id','scenario','pattern','seeds','publication','steps'}:raise ValueError('case schema changed')
        starts=[s for s in c['steps'] if s['op']=='start']
        if [s['generation'] for s in starts]!=[1,2] or starts[0]['lease']!='initial' or starts[1]['lease']!='current':raise ValueError('caller identities changed')
        for s in c['steps']:
            if s['op']=='reclaim' and any(type(s[k]) is not int or s[k]<1 for k in ('expected_token','owner')):raise ValueError('positive exact recovery integers required')
        if len(c['seeds'])!=2 or bool([s for s in c['steps'] if s['op']=='publish'])!=(c['publication'] is not None):raise ValueError('publication declarations changed')
    return cases


def same(left,right):
    return json.dumps(left,sort_keys=True,ensure_ascii=False,separators=(',',':'))==json.dumps(right,sort_keys=True,ensure_ascii=False,separators=(',',':'))


def digest(value):return None if value is None else hashlib.sha256(value.encode('utf-8')).hexdigest()
def pair(lease):return {key:lease[key] for key in ('owner','token')}
def reply(status,key,revision=None,approved=None):return dict(status=status,epoch=1,request_id=key,revision=revision,approved_sha256=approved)


class Model:
    def __init__(self,case,mode):
        self.mode=mode;self.epoch=1;self.revision=1;self.value='approved=version-a\n';self.approval=digest(self.value)
        self.receipts=[];self.summaries=[];self.effects=[];self.witnesses=[];self.migration=None
        self.lease=dict(policy=mode,owner=1,token=1);self.grants=[dict(token=1,owner=1,previous=0)]
        self.effect=None;self.writer=None
        for req in case['seeds']:self.publish(req)

    def publish(self,req):
        if self.writer is not None or self.epoch!=1 or req['epoch']!=1:raise ValueError('publication outside granted open writer')
        self.revision+=1;value=req['content_utf8'];key=req['request_id'];self.approval=digest(value)
        if value is not None:self.value=value
        effect=dict(revision=self.revision,epoch=1,request_id=key,operation='revoke' if value is None else 'update',approved_sha256=self.approval)
        self.effects.append(effect);self.receipts.append({**effect,'payload_utf8':value});self.receipts.sort(key=lambda r:r['request_id'])
        self.witnesses.append(dict(revision=self.revision,requested_epoch=1,active_epoch=1,request_id=key))
        return reply('committed',key,self.revision,self.approval)

    def replace(self,expected,owner):
        if self.writer is not None:return dict(status='busy',sqlite_errorcode=5)
        if self.epoch==2:return dict(status='completed',active_epoch=2)
        if self.lease['token']!=expected:return dict(status='conflict',lease=pair(self.lease))
        self.lease=dict(policy=self.mode,owner=owner,token=expected+1);self.grants.append(dict(token=expected+1,owner=owner,previous=expected))
        return dict(status='reclaimed',lease=pair(self.lease),previous=expected)

    def selection(self):
        return dict(active_epoch=self.epoch,current_revision=self.revision,receipts=[dict(epoch=r['epoch'],request_id=r['request_id'],operation=r['operation'],payload_sha256=digest(r['payload_utf8']),revision=r['revision'],approved_sha256=r['approved_sha256']) for r in self.receipts])

    def commit(self,selected,witness):
        self.epoch=2;self.summaries=[{k:v for k,v in r.items() if k!='approved_sha256'} for r in selected['receipts']];self.receipts=[]
        self.migration=dict(target_epoch=2,selected_revision=selected['current_revision'],write_revision=self.revision,selected_count=len(selected['receipts']),write_count=len(selected['receipts']))
        self.effect=witness;self.writer=None

    def snapshot(self):
        return copy.deepcopy(dict(state=dict(revision=self.revision,approved_sha256=self.approval,content_utf8=self.value),active_epoch=self.epoch,
                                  effects=self.effects,receipts=self.receipts,summaries=self.summaries,publication_witnesses=self.witnesses,
                                  migration_witness=self.migration,summary_columns=['epoch','request_id','operation','payload_sha256','revision'],
                                  lease=self.lease,grants=self.grants,lease_effect=self.effect))


class PlannedExit(Exception):pass


class Invocation:
    def __init__(self,model,generation,lease,pauses):
        self.m=model;self.generation=generation;self.lease=lease;self.pauses=pauses;self.seq=0;self.pause=None;self.done=False;self.stream=self.run()

    def event(self,kind,**fields):
        value=dict(seq=self.seq,kind=kind,**fields);self.seq+=1;return value

    def checkpoint(self,stage):
        yield self.event('checkpoint',stage=stage)
        if stage not in self.pauses:return
        binding=dict(generation=self.generation,owner=self.lease['owner'],token=self.lease['token'],stage=stage,role='migrate')
        self.pause=binding;action=yield self.event('paused',**binding);self.pause=None
        yield self.event('resumed',action=action,**binding)
        if action=='exit':
            if self.m.writer==self.generation:self.m.writer=None
            self.done=True;yield self.event('planned_exit',stage=stage,code=73);raise PlannedExit

    def migrate(self):
        m=self.m
        yield from self.checkpoint('before_selection')
        selected=m.selection();yield self.event('source_selected',**selected)
        if m.epoch==2:return dict(status='completed',active_epoch=2)
        yield from self.checkpoint('after_selection')
        if m.mode=='separate_fence':
            current=pair(m.lease);valid=current==self.lease
            yield self.event('fence_checked',scope='separate',lease=current,valid=valid)
            if not valid:return dict(status='stale_lease',active_epoch=1)
            yield from self.checkpoint('after_fence')
        elif m.mode=='cached_permission':
            yield self.event('fence_cached',lease=self.lease)
            yield from self.checkpoint('after_fence')
        if m.writer is not None:
            yield self.event('writer_busy',sqlite_errorcode=5);return dict(status='busy',sqlite_errorcode=5)
        m.writer=self.generation
        try:
            current=pair(m.lease);observed=m.selection()
            yield self.event('writer_view',lease=current,active_epoch=m.epoch)
            if m.epoch==2:return dict(status='completed',active_epoch=2)
            valid=current==self.lease
            if m.mode=='transactional_fence':
                yield self.event('fence_checked',scope='transaction',lease=current,valid=valid)
                if not valid:return dict(status='stale_lease',active_epoch=1)
                yield from self.checkpoint('after_fence')
            matched=selected==observed
            yield self.event('source_validation',matched=matched,observed=observed)
            if not matched:return dict(status='stale_source',active_epoch=m.epoch)
            witness=dict(owner=self.lease['owner'],token=self.lease['token'],current_owner=current['owner'],current_token=current['token'],authorized=valid)
            yield self.event('effect_prepared',**witness)
            yield from self.checkpoint('before_commit')
            m.commit(selected,witness)
            yield self.event('effect_committed',**witness)
            yield from self.checkpoint('after_commit')
            return dict(status='migrated',active_epoch=2,**self.lease)
        finally:
            if m.writer==self.generation:m.writer=None

    def run(self):
        yield self.event('invocation_started',generation=self.generation,mode=self.m.mode,lease=self.lease,pauses=self.pauses,target_epoch=2)
        try:
            answer=yield from self.migrate();yield self.event('caller_result',response=answer)
        except PlannedExit:return
        self.done=True;yield self.event('worker_completed')

    def boundary(self,action=None):
        result=[];event=self.stream.send(action) if action is not None else next(self.stream)
        while True:
            result.append(event)
            if event['kind'] in ('paused','planned_exit','worker_completed'):return result
            event=next(self.stream)


def evaluate(row,case):
    if any(not same(row[k],case[k]) for k in ('case_id','scenario','pattern','seeds','publication')) or row['mode'] not in MODES:raise ValueError('case binding changed')
    if row['status']!='complete':
        if row['measures'] is not None or not row.get('error_type'):raise ValueError('unexplained infrastructure failure')
        return None
    m=Model(case,row['mode']);peers={};root=None;initial=pair(m.lease)
    if not same(row['initial'],m.snapshot()) or len(row['steps'])!=len(case['steps']):raise ValueError('initial fixture or action count changed')
    counts=dict(invalid_effects=0,original_holder_commits=0,stale_token_refusals=0,source_refusals=0,reclaimed=0,recovery_busy=0,
                recovery_conflicts=0,recovery_completed=0,lifetime_grants=0,aba_cases=int(case['scenario']=='aba_owner'),actual_completed=False,
                caller_errors=0,response_violations=0,planned_exits=0,normal_children=0,barriers=0,publications=0,
                original_replays=0,changed_conflicts=0,query_failures=0,missing_authority=0,duplicate_authority=0,queries_inert=True)
    for action,step in zip(case['steps'],row['steps']):
        if not same(action,step['action']):raise ValueError('causal order changed')
        if action['op']=='reclaim':
            response=m.replace(action['expected_token'],action['owner'])
            if not same(step['response'],response):raise ValueError('recovery reply contradicts writer/authority history')
            key={'reclaimed':'reclaimed','busy':'recovery_busy','conflict':'recovery_conflicts','completed':'recovery_completed'}[response['status']];counts[key]+=1
        elif action['op']=='publish':
            if not same(step['request'],case['publication']) or not same(step['response'],m.publish(case['publication'])):raise ValueError('source publication changed')
            counts['publications']+=1
        else:
            generation=action['generation']
            if action['op']=='start':
                lease=initial if action['lease']=='initial' else pair(m.lease)
                if not same(step['lease'],lease):raise ValueError('caller token changed')
                command=step['command']
                if len(command)!=14 or not command[0] or Path(command[1]).name!='reclaim_worker.py':raise ValueError('worker command changed')
                flags=dict(zip(command[2::2],command[3::2]));root=flags.get('--root') if root is None else root
                expected_flags={'--root':root,'--mode':row['mode'],'--generation':str(generation),'--owner':str(lease['owner']),'--token':str(lease['token']),'--pauses':','.join(action['pauses'])}
                if not same(flags,expected_flags) or generation in peers:raise ValueError('bound caller command changed')
                peer=Invocation(m,generation,lease,action['pauses']);peers[generation]=peer;expected=peer.boundary()
            elif action['op']=='resume':
                peer=peers[generation]
                if peer.pause is None or not same(step['command'],{'command':action['action'],**peer.pause}) or not same(step['lease'],peer.lease):raise ValueError('bound resume changed')
                expected=peer.boundary(action['action'])
            else:raise ValueError('unknown action')
            actual=step['events']
            if not same([json.loads(s) for s in step['stdout'].splitlines()],actual) or len(actual)!=len(expected):raise ValueError('raw stream changed')
            for left,right in zip(actual,expected):
                if not same(left,right):
                    if left.get('kind')==right['kind']=='caller_result' and same(left.get('seq'),right['seq']):counts['response_violations']+=1
                    else:raise ValueError('event contradicts authority/transaction history: '+right['kind'])
                kind=left['kind'];counts['barriers']+=kind=='paused';counts['original_holder_commits']+=kind=='effect_committed' and generation==1
                if kind=='caller_result':
                    counts['stale_token_refusals']+=left['response'].get('status')=='stale_lease';counts['source_refusals']+=left['response'].get('status')=='stale_source'
            last=expected[-1]['kind'];code=73 if last=='planned_exit' else 0 if last=='worker_completed' else None
            if not same(step['returncode'],code) or not same(step['stderr'],None if code is None else ''):raise ValueError('unmarked or failed exit')
            counts['planned_exits']+=code==73;counts['normal_children']+=code==0
        if not same(step['snapshot'],m.snapshot()):raise ValueError('durable state contradicts authority/commit history')
    if any(not p.done for p in peers.values()) or m.writer is not None or not same(row['final'],m.snapshot()):raise ValueError('unsettled final state')
    originals=case['seeds']+([] if case['publication'] is None else [case['publication']])
    if len(row['queries'])!=len(originals):raise ValueError('missing actual original query')
    for req,q in zip(originals,row['queries']):
        if not same(q['request'],req):raise ValueError('query identity changed')
        effect=next(e for e in m.effects if e['request_id']==req['request_id'])
        replay=same(q['original'],reply('replayed',effect['request_id'],effect['revision'],effect['approved_sha256']))
        conflict=same(q['changed'],reply('conflict',effect['request_id']))
        counts['original_replays']+=replay;counts['changed_conflicts']+=conflict;counts['query_failures']+=not(replay and conflict)
    counts.update(invalid_effects=int(m.effect is not None and not m.effect['authorized']),lifetime_grants=len(m.grants),actual_completed=m.epoch==2,queries_inert=same(row['after_queries'],row['final']))
    if not same(counts,row['measures']):raise ValueError('independent counts disagree')
    return counts


def recount(rows,cases):
    declarations={c['case_id']:c for c in cases};keys=[(r['case_id'],r['mode']) for r in rows]
    if len(keys)!=60 or len(set(keys))!=60 or set(keys)!={(c,m) for c in declarations for m in MODES}:raise ValueError('full sixty-record grid required')
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
    for name in ('docs/RECLAIM_PROTOCOL.md',str(DATASET.relative_to(ROOT))):
        if subprocess.check_output(['git','show',meta['freeze_commit']+':'+name],cwd=ROOT)!=(ROOT/name).read_bytes():raise ValueError('frozen identity changed')
    if hashlib.sha256(DATASET.read_bytes()).hexdigest()!=meta['dataset_sha256'] or set(meta['source_sha256'])!=set(SOURCES):raise ValueError('source/manifest coverage changed')
    for name,hash_value in meta['source_sha256'].items():
        if hashlib.sha256((ROOT/name).read_bytes()).hexdigest()!=hash_value:raise ValueError('source hash changed: '+name)
        if name.startswith('src/') and name.count('/')==1 and subprocess.check_output(['git','show',meta['base_commit']+':'+name],cwd=ROOT)!=(ROOT/name).read_bytes():raise ValueError('earlier mechanism changed')
    raw=path.parent/meta['results_file']
    if raw.parent!=path.parent or hashlib.sha256(raw.read_bytes()).hexdigest()!=meta['results_sha256']:raise ValueError('raw identity changed')
    arms=recount([json.loads(s) for s in raw.read_text().splitlines()],cases)
    if not same(arms,meta['summary']):raise ValueError('summary changed')
    safe=arms['transactional_fence']
    criteria=dict(complete_evidence=all(a['infrastructure_errors']==0 for a in arms.values()),
                  transactional_fence=safe.get('invalid_effects',1)==0,
                  supported_responses=all(a.get('caller_errors',1)==a.get('response_violations',1)==0 for a in arms.values()),
                  historical_authority=all(a.get('missing_authority',1)==a.get('duplicate_authority',1)==a.get('query_failures',1)==0 and a.get('queries_inert')==20 for a in arms.values()))
    return dict(summary=arms,criteria=criteria,all_criteria_passed=all(criteria.values()))


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('metadata',type=Path);a=p.parse_args();r=verify(a.metadata);print(json.dumps(r,indent=2));raise SystemExit(0 if r['all_criteria_passed'] else 1)
