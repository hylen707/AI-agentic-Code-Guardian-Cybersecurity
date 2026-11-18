"""Independent stdlib replay of bound two-caller histories and durable effects."""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[1]
MODES = ('restart_baseline','reconciled_resumption')
DECLARATIONS = (('admission_finish',1),('admission_finish',2),('selection_finish',2),('writer_busy',1),('writer_busy',2),
                ('exit_admission',1),('exit_admission',2),('exit_stale',1),('exit_stale',2),('exit_before_commit',1),
                ('exit_before_commit',2),('exit_after_commit',1),('exit_after_commit',2),('both_selected_exit',2),
                ('both_selected_source_exit',2),('busy_reserved_exit',2))
SOURCE_NAMES = tuple(sorted(str(p.relative_to(ROOT)) for p in (ROOT/'src').glob('*.py'))) + (
    'experiments/resume_worker.py','experiments/run_resume_comparison.py','experiments/verify_resume_results.py','tests/test_resume.py','docs/RESUME_PROTOCOL.md')


def load_manifest(path):
    doc=json.loads(Path(path).read_text())
    if set(doc)!={'schema_version','cases'} or doc['schema_version']!='resume-eval-v1':raise ValueError('manifest schema')
    cases=doc['cases']
    expected={(s,b,p) for s,b in DECLARATIONS for p in ('updates','revocations')}
    if len(cases)!=32 or len({c['case_id'] for c in cases})!=32 or {(c['scenario'],c['budget'],c['pattern']) for c in cases}!=expected:
        raise ValueError('manifest grid')
    for c in cases:
        if type(c['budget']) is not int or not c['case_id'] or set(c)!={'case_id','scenario','budget','pattern','publication','steps'}:
            raise ValueError('invalid declaration')
        if [s['generation'] for s in c['steps'] if s['op']=='start']!=[1,2,3,4]:raise ValueError('caller generations')
        if c['steps'][-2:]!=[dict(op='start',generation=3,pauses=[]),dict(op='start',generation=4,pauses=[])]:raise ValueError('recovery suffix')
        pubs=[s for s in c['steps'] if s['op']=='publish']
        if bool(pubs)!=(c['publication'] is not None) or len(pubs)>1:raise ValueError('source declaration')
    return cases


def sha(value):
    return None if value is None else hashlib.sha256(value.encode('utf-8')).hexdigest()


def reply(status,key,revision=None,approved=None):
    return dict(status=status,epoch=1,request_id=key,revision=revision,approved_sha256=approved)


class Model:
    def __init__(self,budget):
        self.budget,self.used,self.epoch,self.revision=budget,0,1,1
        self.value,self.approval='approved=version-a\n',sha('approved=version-a\n')
        self.receipts,self.summaries,self.effects,self.admissions,self.witnesses=[],[],[],[],[]
        self.migration=None;self.writer=None;self.live=set()
        self.publish(dict(epoch=1,request_id='seed-a',content_utf8='approved=version-b\n'))
        self.publish(dict(epoch=1,request_id='seed-b',content_utf8=None))

    def publish(self,request):
        if self.writer is not None or self.epoch!=1 or request['epoch']!=1:raise ValueError('publication outside granted open writer')
        self.revision+=1;value=request['content_utf8'];key=request['request_id'];self.approval=sha(value)
        if value is not None:self.value=value
        effect=dict(revision=self.revision,epoch=1,request_id=key,operation='revoke' if value is None else 'update',approved_sha256=self.approval)
        self.effects.append(effect);self.receipts.append({**effect,'payload_utf8':value});self.receipts.sort(key=lambda r:r['request_id'])
        self.witnesses.append(dict(revision=self.revision,requested_epoch=1,active_epoch=1,request_id=key))
        return reply('committed',key,self.revision,self.approval)

    def selection(self):
        return dict(active_epoch=self.epoch,current_revision=self.revision,receipts=[dict(epoch=r['epoch'],request_id=r['request_id'],
                    operation=r['operation'],payload_sha256=sha(r['payload_utf8']),revision=r['revision'],approved_sha256=r['approved_sha256']) for r in self.receipts])

    def commit(self,selected):
        self.epoch=2
        self.summaries=[{k:v for k,v in r.items() if k!='approved_sha256'} for r in selected['receipts']]
        self.receipts=[]
        self.migration=dict(target_epoch=2,selected_revision=selected['current_revision'],write_revision=self.revision,
                            selected_count=len(selected['receipts']),write_count=len(selected['receipts']))
        self.writer=None

    def snapshot(self):
        return copy.deepcopy(dict(state=dict(revision=self.revision,approved_sha256=self.approval,content_utf8=self.value),
                    active_epoch=self.epoch,effects=self.effects,receipts=self.receipts,summaries=self.summaries,
                    publication_witnesses=self.witnesses,admissions=self.admissions,migration_witness=self.migration,
                    summary_columns=['epoch','request_id','operation','payload_sha256','revision'],
                    job=dict(policy='reserved_reconcile',budget=self.budget,target_epoch=2,used=self.used)))


class PlannedExit(Exception):pass
class Busy(Exception):pass


class Invocation:
    def __init__(self,model,mode,generation,pauses):
        self.model,self.mode,self.generation,self.pauses=model,mode,generation,pauses
        self.seq=0;self.attempt=None;self.pause=None;self.done=False;self.stream=self.run()
        model.live.add(generation)

    def event(self,kind,**fields):
        value=dict(seq=self.seq,kind=kind,**fields);self.seq+=1;return value

    def checkpoint(self,stage):
        yield self.event('checkpoint',stage=stage)
        if stage not in self.pauses:return
        binding=dict(generation=self.generation,attempt_number=self.attempt,budget=self.model.budget,stage=stage,role='migrate')
        self.pause=binding
        action=yield self.event('paused',**binding)
        self.pause=None
        yield self.event('resumed',action=action,**binding)
        if action=='exit':
            if self.model.writer==self.generation:self.model.writer=None
            self.model.live.remove(self.generation);self.done=True
            yield self.event('planned_exit',stage=stage,code=73)
            raise PlannedExit

    def writable(self):
        if self.model.writer not in (None,self.generation):raise Busy

    def job(self):
        m=self.model
        while True:
            self.writable()
            yield self.event('budget_view',active_epoch=m.epoch,used=m.used,persisted_used=m.used,counter_source='durable')
            if m.epoch==2:return dict(status='completed',active_epoch=2,used=m.used,budget=m.budget)
            if m.used>=m.budget:return dict(status='budget_exhausted',active_epoch=1,used=m.used,budget=m.budget)
            before=m.used;m.used+=1;self.attempt=m.used
            admission=dict(ordinal=len(m.admissions)+1,generation=self.generation,attempt_number=m.used,persisted_before=before,persisted_after=m.used)
            m.admissions.append(admission)
            yield self.event('admitted',**admission)
            yield from self.checkpoint('after_admission')
            if m.epoch==2:
                if self.mode=='restart_baseline':raise ValueError('unexpected live migration result')
                answer=dict(status='already_migrated',active_epoch=2,target_epoch=2)
            else:
                selected=m.selection()
                yield self.event('selection',scope='initial',origin='read',**selected)
                yield from self.checkpoint('after_selection')
                yield self.event('selection',scope='final',origin='cached',**selected)
                yield from self.checkpoint('after_refresh')
                self.writable();observed=m.selection();matched=selected==observed
                yield self.event('validation',matched=matched,observed=observed)
                if not matched:
                    yield self.event('selection_changed',transaction_rolled_back=True)
                    answer=dict(status='stale_selection',active_epoch=m.epoch,target_epoch=2)
                else:
                    m.writer=self.generation
                    yield from self.checkpoint('before_commit')
                    m.commit(selected)
                    yield from self.checkpoint('after_commit')
                    answer=dict(status='migrated',active_epoch=2,target_epoch=2)
            yield self.event('attempt_result',response=answer)
            if answer['status']=='stale_selection':yield from self.checkpoint('after_stale')
            self.writable()
            used=m.used
            yield self.event('accounted',used=used,persisted_used=used)
            yield from self.checkpoint('after_accounting')
            if self.mode=='restart_baseline' and answer['status']=='migrated':
                return dict(status='completed',active_epoch=2,used=used,budget=m.budget)

    def run(self):
        yield self.event('invocation_started',generation=self.generation,mode=self.mode,budget=self.model.budget,target_epoch=2,pauses=self.pauses)
        try:
            answer=yield from self.job()
            yield self.event('caller_result',response=answer)
        except PlannedExit:return
        except Busy:
            if self.mode=='restart_baseline':
                yield self.event('caller_error',error_type='OperationalError',detail='database is locked',sqlite_errorcode=5)
            else:
                yield self.event('resumption_busy',sqlite_errorcode=5)
                yield self.event('caller_result',response=dict(status='retry_later',reason='writer_busy',budget=self.model.budget))
        except ValueError as error:
            yield self.event('caller_error',error_type='ValueError',detail=str(error),sqlite_errorcode=None)
        self.model.live.remove(self.generation);self.done=True
        yield self.event('worker_completed')

    def boundary(self,action=None):
        events=[]
        event=self.stream.send(action) if action is not None else next(self.stream)
        while True:
            events.append(event)
            if event['kind'] in ('paused','planned_exit','worker_completed'):return events
            event=next(self.stream)


def evaluate(row,case):
    for key in ('case_id','scenario','budget','pattern','publication'):
        if row[key]!=case[key]:raise ValueError('case binding changed')
    if row['mode'] not in MODES:raise ValueError('unknown arm')
    if row['status']!='complete':
        if row['measures'] is not None or not row.get('error_type'):raise ValueError('unexplained infrastructure failure')
        return None
    m=Model(case['budget']);peers={};root=None
    if row['initial']!=m.snapshot() or len(row['steps'])!=len(case['steps']):raise ValueError('initial state or action count changed')
    counts=dict(admissions=0,excess_admissions=0,counter_agrees=True,actual_completed=False,caller_errors=0,retry_later=0,response_violations=0,
                exhausted_while_peer_live=0,exhausted_then_closed=0,planned_exits=0,normal_children=0,barriers=0,publications=0,
                missing_authority=0,duplicate_authority=0,query_failures=0,queries_inert=True)
    exhausted=0
    for action,step in zip(case['steps'],row['steps']):
        if action!=step['action']:raise ValueError('causal action changed')
        if action['op']=='publish':
            if step['request']!=case['publication'] or step['response']!=m.publish(case['publication']):raise ValueError('publication changed')
            counts['publications']+=1
        else:
            generation=action['generation']
            live_before=set(m.live)
            if action['op']=='start':
                command=step['command']
                if len(command)!=12 or Path(command[1]).name!='resume_worker.py' or not command[0]:raise ValueError('worker command changed')
                flags=dict(zip(command[2::2],command[3::2]))
                if set(flags)!={'--root','--mode','--budget','--generation','--pauses'}:raise ValueError('worker flags changed')
                if root is None:root=flags['--root']
                expected_flags={'--root':root,'--mode':row['mode'],'--budget':str(case['budget']),'--generation':str(generation),'--pauses':','.join(action['pauses'])}
                if flags!=expected_flags or generation in peers:raise ValueError('caller identity changed')
                peer=Invocation(m,row['mode'],generation,action['pauses']);peers[generation]=peer
                expected=peer.boundary()
            elif action['op']=='resume':
                peer=peers[generation]
                if peer.pause is None or step['command']!={'command':action['action'],**peer.pause}:raise ValueError('resume binding changed')
                expected=peer.boundary(action['action'])
            else:raise ValueError('unknown action')
            observed=step['events']
            if [json.loads(line) for line in step['stdout'].splitlines()]!=observed or len(observed)!=len(expected):raise ValueError('raw stream changed')
            for left,right in zip(observed,expected):
                if left!=right:
                    if left.get('kind')==right['kind']=='caller_result' and left.get('seq')==right['seq']:
                        counts['response_violations']+=1
                    else:raise ValueError('event contradicts granted live history: '+right['kind'])
                kind=left['kind'];counts['barriers']+=kind=='paused';counts['caller_errors']+=kind=='caller_error'
                if kind=='caller_result':
                    status=left['response'].get('status')
                    counts['retry_later']+=status=='retry_later'
                    if status=='budget_exhausted':
                        exhausted+=1;counts['exhausted_while_peer_live']+=bool(live_before-{generation})
            final_kind=expected[-1]['kind'];code=73 if final_kind=='planned_exit' else 0 if final_kind=='worker_completed' else None
            if step['returncode']!=code or step['stderr']!=(None if code is None else ''):raise ValueError('unmarked or failed process exit')
            counts['planned_exits']+=code==73;counts['normal_children']+=code==0
        if step['snapshot']!=m.snapshot():raise ValueError('durable snapshot contradicts committed history')
    if m.live or m.writer is not None or row['final']!=m.snapshot():raise ValueError('unsettled callers or final state')
    originals=[dict(epoch=1,request_id='seed-a',content_utf8='approved=version-b\n'),dict(epoch=1,request_id='seed-b',content_utf8=None)]
    if case['publication'] is not None:originals.append(case['publication'])
    if len(row['queries'])!=len(originals):raise ValueError('missing historical query')
    for request,query in zip(originals,row['queries']):
        if query['request']!=request:raise ValueError('changed query intent')
        original=next(r for r in m.effects if r['request_id']==request['request_id'])
        counts['query_failures']+=query['original']!=reply('replayed',original['request_id'],original['revision'],original['approved_sha256']) or query['changed']!=reply('conflict',original['request_id'])
    counts.update(admissions=m.used,actual_completed=m.epoch==2,exhausted_then_closed=exhausted if m.epoch==2 else 0,queries_inert=row['after_queries']==row['final'])
    if row['measures']!=counts:raise ValueError('recorded measures disagree with independent replay')
    return counts


def recount(rows,cases):
    declarations={c['case_id']:c for c in cases}
    keys=[(r['case_id'],r['mode']) for r in rows]
    if len(keys)!=64 or len(set(keys))!=64 or set(keys)!={(c,m) for c in declarations for m in MODES}:raise ValueError('full paired grid required')
    arms={mode:dict(cases=0,infrastructure_errors=0) for mode in MODES}
    for row in rows:
        arm=arms[row['mode']];arm['cases']+=1;counts=evaluate(row,declarations[row['case_id']])
        if counts is None:arm['infrastructure_errors']+=1;continue
        for key,value in counts.items():arm[key]=arm.get(key,0)+int(value)
    return arms


def verify(metadata_path,dataset=ROOT/'experiments/tasks/resume-eval-v1/tasks.json'):
    path=Path(metadata_path);meta=json.loads(path.read_text());cases=load_manifest(dataset)
    for name in ('base_commit','freeze_commit'):
        if not re.fullmatch('[0-9a-f]{40}',meta[name]):raise ValueError('invalid provenance commit')
    if subprocess.check_output(['git','rev-parse',meta['freeze_commit']+'^'],cwd=ROOT,text=True).strip()!=meta['base_commit']:raise ValueError('freeze parent changed')
    for name in ('docs/RESUME_PROTOCOL.md',str(Path(dataset).relative_to(ROOT))):
        if subprocess.check_output(['git','show',meta['freeze_commit']+':'+name],cwd=ROOT)!=(ROOT/name).read_bytes():raise ValueError('freeze changed')
    if hashlib.sha256(Path(dataset).read_bytes()).hexdigest()!=meta['dataset_sha256'] or set(meta['source_sha256'])!=set(SOURCE_NAMES):raise ValueError('source/manifest coverage changed')
    for name,hash_value in meta['source_sha256'].items():
        if hashlib.sha256((ROOT/name).read_bytes()).hexdigest()!=hash_value:raise ValueError('source hash changed: '+name)
        if name.startswith('src/') and subprocess.check_output(['git','show',meta['base_commit']+':'+name],cwd=ROOT)!=(ROOT/name).read_bytes():raise ValueError('mechanism changed')
    raw=path.parent/meta['results_file']
    if raw.parent!=path.parent or hashlib.sha256(raw.read_bytes()).hexdigest()!=meta['results_sha256']:raise ValueError('raw identity changed')
    arms=recount([json.loads(line) for line in raw.read_text().splitlines()],cases)
    if arms!=meta['summary']:raise ValueError('summary changed')
    safe=arms['reconciled_resumption']
    criteria=dict(complete_evidence=all(a['infrastructure_errors']==0 for a in arms.values()),
                  admission_bound=all(a.get('excess_admissions',1)==0 and a.get('counter_agrees')==32 for a in arms.values()),
                  response_contract=safe.get('caller_errors',1)==safe.get('response_violations',1)==0,
                  historical_authority=all(a.get('missing_authority',1)==a.get('duplicate_authority',1)==a.get('query_failures',1)==0 and a.get('queries_inert')==32 for a in arms.values()))
    return dict(summary=arms,criteria=criteria,all_criteria_passed=all(criteria.values()))


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('metadata',type=Path);args=parser.parse_args()
    result=verify(args.metadata);print(json.dumps(result,indent=2));raise SystemExit(0 if result['all_criteria_passed'] else 1)
