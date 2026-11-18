"""Frozen, paired two-caller schedules with exits and parent publications."""
from __future__ import annotations

import argparse
import copy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import selectors
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from src.restart_store import RestartPublicationStore
from experiments.resume_worker import MODES

DATASET = ROOT/"experiments/tasks/resume-eval-v1/tasks.json"
PROTOCOL = "docs/RESUME_PROTOCOL.md"
SOURCES = tuple(sorted(str(p.relative_to(ROOT)) for p in (ROOT/"src").glob('*.py'))) + (
    "experiments/resume_worker.py", "experiments/run_resume_comparison.py", "experiments/verify_resume_results.py", "tests/test_resume.py", PROTOCOL)
TIMEOUT = 15


def load_cases(path=DATASET):
    data = json.loads(Path(path).read_text())
    if data.get('schema_version') != 'resume-eval-v1' or len(data.get('cases',[])) != 32:
        raise ValueError("32 frozen resumption cases required")
    cases = data['cases']
    if len({c['case_id'] for c in cases}) != 32 or any(type(c['budget']) is not int or c['budget'] not in (1,2) for c in cases):
        raise ValueError("unique case IDs and exact integer budgets required")
    return cases


def snapshot(store):
    result = store.inspect()
    state = result['state']
    result['state'] = dict(revision=state.revision, approved_sha256=state.approved_sha256,
                           content_utf8=state.content.decode('utf-8'))
    for record in result['receipts']:
        payload = record.pop('payload')
        record['payload_utf8'] = None if payload is None else payload.decode('utf-8')
    return result


class Peer:
    def __init__(self, root, mode, budget, action):
        self.generation = action['generation']
        self.command = [sys.executable, str(ROOT/'experiments/resume_worker.py'), '--root', str(root), '--mode',mode,
                        '--budget',str(budget),'--generation',str(self.generation),'--pauses',','.join(action['pauses'])]
        self.process = subprocess.Popen(self.command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, bufsize=0)
        self.buffer = b''
        self.pause = None
        self.terminal = False

    def boundary(self):
        lines, events = [], []
        deadline = time.monotonic()+TIMEOUT
        while True:
            while b'\n' not in self.buffer:
                remaining = deadline-time.monotonic()
                if remaining <= 0:
                    raise TimeoutError("worker boundary timed out")
                with selectors.DefaultSelector() as selector:
                    selector.register(self.process.stdout, selectors.EVENT_READ)
                    if not selector.select(remaining):
                        raise TimeoutError("worker boundary timed out")
                chunk = self.process.stdout.read(65536)
                if not chunk:
                    raise RuntimeError("worker ended without a bound terminal message")
                self.buffer += chunk
            line, self.buffer = self.buffer.split(b'\n',1)
            lines.append(line.decode('utf-8')+'\n')
            record = json.loads(line); events.append(record)
            kind = record['kind']
            if kind == 'paused':
                self.pause = {k:v for k,v in record.items() if k not in ('seq','kind')}
                return dict(events=events, stdout=''.join(lines), stderr=None, returncode=None)
            if kind in ('planned_exit','worker_completed'):
                self.terminal, self.pause = True, None
                tail, errors = self.process.communicate(timeout=TIMEOUT)
                if self.buffer or tail:
                    raise ValueError("unexpected output after terminal event")
                return dict(events=events, stdout=''.join(lines), stderr=errors.decode('utf-8'), returncode=self.process.returncode)

    def resume(self, action):
        if self.terminal or self.pause is None:
            raise ValueError("caller is not paused")
        command = {"command":action['action'], **self.pause}
        self.process.stdin.write((json.dumps(command)+'\n').encode()); self.process.stdin.flush()
        self.pause = None
        return command

    def close(self):
        if self.process.poll() is None:
            self.process.kill()
        self.process.communicate(timeout=TIMEOUT)


def content(req):
    return None if req['content_utf8'] is None else req['content_utf8'].encode('utf-8')


def run_case(case, mode):
    row = {**copy.deepcopy(case), 'mode':mode, 'status':'infrastructure_error', 'steps':[], 'queries':[], 'measures':None}
    peers = {}
    phase = 'fixture'
    try:
        with tempfile.TemporaryDirectory(prefix='codeguardian-resume-') as directory:
            store = RestartPublicationStore(Path(directory)/'store', 'reserved_reconcile', case['budget'])
            store.initialize(b'approved=version-a\n')
            requests = [dict(epoch=1,request_id='seed-a',content_utf8='approved=version-b\n'), dict(epoch=1,request_id='seed-b',content_utf8=None)]
            for req in requests:
                store.publish_once(1,req['request_id'],content(req))
            row['initial'] = snapshot(store)
            for action in case['steps']:
                phase = action['op']
                step = dict(action=copy.deepcopy(action))
                if phase == 'start':
                    peer = Peer(store.root,mode,case['budget'],action); peers[action['generation']]=peer
                    step['command'] = peer.command
                    step.update(peer.boundary())
                elif phase == 'resume':
                    peer = peers[action['generation']]
                    step['command'] = peer.resume(action)
                    step.update(peer.boundary())
                elif phase == 'publish':
                    req = case['publication']
                    step['request'] = req
                    step['response'] = store.publish_once(req['epoch'],req['request_id'],content(req))
                    requests.append(req)
                else:
                    raise ValueError("unknown frozen action")
                step['snapshot'] = snapshot(store); row['steps'].append(step)
            row['final'] = snapshot(store)
            phase = 'queries'
            for req in requests:
                changed = None if content(req) is not None else b'changed=typed-intent\n'
                row['queries'].append(dict(request=req, original=store.publish_once(1,req['request_id'],content(req)),
                                           changed=store.publish_once(1,req['request_id'],changed)))
            row['after_queries'] = snapshot(store)
            row['status'] = 'complete'; row['measures'] = measure(row)
    except Exception as error:
        row.update(error_phase=phase,error_type=type(error).__name__,error_detail=str(error))
    finally:
        for peer in peers.values():
            peer.close()
    return row


def measure(row):
    final = row['final']; live = set(); errors = retries = violations = live_exhausted = exhausted = barriers = exits = normal = 0
    for step in row['steps']:
        if step['action']['op']=='publish':
            continue
        generation = step['action']['generation']; live.add(generation)
        for event in step['events']:
            kind = event['kind']
            barriers += kind=='paused'; errors += kind=='caller_error'
            if kind=='caller_result':
                answer = event['response']; status = answer['status']; state = step['snapshot']
                if status=='completed':
                    violations += state['active_epoch']!=2 or answer!=dict(status='completed',active_epoch=2,used=state['job']['used'],budget=row['budget'])
                elif status=='budget_exhausted':
                    exhausted += 1; live_exhausted += bool(live-{generation})
                    violations += state['active_epoch']!=1 or answer!=dict(status='budget_exhausted',active_epoch=1,used=row['budget'],budget=row['budget'])
                elif status=='retry_later':
                    retries += 1
                    violations += answer!=dict(status='retry_later',reason='writer_busy',budget=row['budget']) or not any(e['kind']=='resumption_busy' and e['sqlite_errorcode']==5 for e in step['events'])
                else:
                    violations += 1
        if step['returncode'] is not None:
            live.remove(generation); exits += step['returncode']==73; normal += step['returncode']==0
    query_failures = 0
    effects = {r['request_id']:r for r in final['effects']}
    for query in row['queries']:
        original = effects.get(query['request']['request_id'])
        expected = None if original is None else dict(status='replayed',epoch=1,request_id=original['request_id'],revision=original['revision'],approved_sha256=original['approved_sha256'])
        query_failures += query['original']!=expected or query['changed']['status']!='conflict'
    authority = final['receipts']+final['summaries']; keys=[(r['epoch'],r['request_id']) for r in authority]
    return dict(admissions=len(final['admissions']),excess_admissions=max(0,len(final['admissions'])-row['budget']),
                counter_agrees=final['job']['used']==len(final['admissions']),actual_completed=final['active_epoch']==2,
                caller_errors=errors,retry_later=retries,response_violations=violations,exhausted_while_peer_live=live_exhausted,
                exhausted_then_closed=exhausted if final['active_epoch']==2 else 0,planned_exits=exits,normal_children=normal,
                barriers=barriers,publications=sum(s['action']['op']=='publish' for s in row['steps']),
                missing_authority=len(set(effects)-{r['request_id'] for r in authority}),duplicate_authority=len(keys)-len(set(keys)),
                query_failures=query_failures,queries_inert=final==row['after_queries'])


def summarize(rows, cases):
    expected={(c['case_id'],m) for c in cases for m in MODES}
    if len(rows)!=len(expected) or {(r['case_id'],r['mode']) for r in rows}!=expected:
        raise ValueError("complete paired grid required")
    arms={}
    for mode in MODES:
        arm=dict(cases=0,infrastructure_errors=0)
        for row in rows:
            if row['mode']!=mode:continue
            arm['cases']+=1
            if row['status']!='complete':arm['infrastructure_errors']+=1;continue
            counts=measure(row)
            if counts!=row['measures']:raise ValueError("recorded measures changed")
            for key,value in counts.items():arm[key]=arm.get(key,0)+int(value)
        arms[mode]=arm
    return arms


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--dataset',type=Path,default=DATASET)
    parser.add_argument('--output',type=Path,required=True);parser.add_argument('--base-commit',required=True);parser.add_argument('--freeze-commit',required=True)
    args=parser.parse_args();cases=load_cases(args.dataset)
    for path in (PROTOCOL,str(args.dataset.relative_to(ROOT))):
        frozen=subprocess.check_output(['git','show',args.freeze_commit+':'+path],cwd=ROOT)
        if frozen!=(ROOT/path).read_bytes():raise ValueError("freeze identity changed")
    for path in sorted((ROOT/'src').glob('*.py')):
        original=subprocess.check_output(['git','show',args.base_commit+':'+str(path.relative_to(ROOT))],cwd=ROOT)
        if original!=path.read_bytes():raise ValueError("mechanism changed after baseline")
    rows=[run_case(c,m) for c in cases for m in MODES]
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(''.join(json.dumps(r,ensure_ascii=False,sort_keys=True)+'\n' for r in rows))
    metadata=dict(base_commit=args.base_commit,freeze_commit=args.freeze_commit,executed_at_utc=datetime.now(timezone.utc).isoformat(),
                  python=sys.version,results_file=args.output.name,results_sha256=hashlib.sha256(args.output.read_bytes()).hexdigest(),
                  dataset_sha256=hashlib.sha256(args.dataset.read_bytes()).hexdigest(),source_sha256={p:hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in SOURCES},summary=summarize(rows,cases))
    args.output.with_suffix('.metadata.json').write_text(json.dumps(metadata,indent=2)+'\n')
    print(json.dumps(metadata['summary'],indent=2))
    if any(a['infrastructure_errors'] for a in metadata['summary'].values()):raise SystemExit(1)


if __name__=='__main__':main()
