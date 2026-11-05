"""Fixed two-caller request races with optional later independent work."""
from __future__ import annotations
import argparse
import hashlib
import json
import platform
import sqlite3
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from experiments.caller_worker import PAYLOADS
from experiments.run_overlap_comparison import BarrierFailure, wait_for_pause
from src.caller_store import MODES, CallerPublicationStore
from src.publication_store import recover_value
PATTERNS = {'same_ascii': ('b', 'b'), 'same_empty': ('empty', 'empty'), 'same_unicode': ('unicode', 'unicode'), 'same_revoke': ('revoke', 'revoke'), 'changed_bytes': ('b', 'c'), 'update_to_revoke': ('empty', 'revoke'), 'revoke_to_update': ('revoke', 'empty'), 'changed_unicode_bytes': ('nfc', 'nfd')}
SOURCES = ('src/caller_store.py', 'experiments/caller_worker.py', 'experiments/run_caller_comparison.py', 'experiments/verify_caller_results.py', 'tests/test_caller_store.py', 'docs/CALLER_PROTOCOL.md', 'src/publication_store.py', 'src/retry_store.py', 'src/retirement_store.py', 'src/overlap_store.py', 'experiments/run_overlap_comparison.py')
STEP_TIMEOUT = 15
SETTINGS = {'journal_mode': 'delete', 'synchronous': 2, 'integrity_check': 'ok'}

def sha(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()

def load_cases(path: Path) -> list[dict]:
    data = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(data, dict) or set(data) != {'schema_version', 'cases'} or data['schema_version'] != 'caller-eval-v1':
        raise ValueError('unsupported caller manifest')
    cases = data['cases']
    expected = {('overlap', p) for p in PATTERNS}
    expected.update((('overlap_with_later', p) for p in ('same_ascii', 'same_revoke', 'changed_bytes', 'update_to_revoke')))
    expected.update((('serial', p) for p in ('same_ascii', 'same_empty', 'changed_bytes')))
    expected.add(('distinct_overlap', 'same_ascii'))
    if not isinstance(cases, list) or len(cases) != 16 or any((set(c) != {'case_id', 'schedule', 'pattern'} or not all((isinstance(v, str) for v in c.values())) or (not c['case_id']) for c in cases)):
        raise ValueError('sixteen well-formed cases required')
    if len({c['case_id'] for c in cases}) != 16 or {(c['schedule'], c['pattern']) for c in cases} != expected:
        raise ValueError('changed or repeated caller schedule')
    return cases

def requests(case: dict) -> dict:
    first, second = PATTERNS[case['pattern']]

    def make(caller, key, alias):
        value = PAYLOADS[alias]
        return {'caller': caller, 'epoch': 2, 'request_id': key, 'intent': alias, 'content_utf8': None if value is None else value.decode()}
    return {'first': make('first', 'shared-request', first), 'second': make('second', 'other-request' if case['schedule'] == 'distinct_overlap' else 'shared-request', second), 'later': make('later', 'later', 'later')}

def capture(store: CallerPublicationStore) -> dict:
    observed = store.inspect()
    state = observed['state']
    output = recover_value(state)
    value = output.pop('content')
    receipts = [{**{k: v for k, v in r.items() if k != 'payload'}, 'payload_utf8': None if r['payload'] is None else r['payload'].decode()} for r in observed['receipts']]
    return {'state': {'revision': state.revision, 'approved_sha256': state.approved_sha256, 'content_utf8': state.content.decode(), 'content_sha256': sha(state.content)}, 'active_epoch': observed['active_epoch'], 'effects': observed['effects'], 'receipts': receipts, 'call_commits': observed['call_commits'], 'delivery': {**output, 'delivered_utf8': None if value is None else value.decode()}, 'sqlite_settings': store.settings()}

def check_capture(case: dict, observed: dict) -> list[dict]:
    if set(observed) != {'state', 'active_epoch', 'effects', 'receipts', 'call_commits', 'delivery', 'sqlite_settings'}:
        raise ValueError('incomplete caller capture')
    if observed['active_epoch'] != 2 or observed['sqlite_settings'] != SETTINGS:
        raise ValueError('wrong epoch or SQLite settings')
    payload, approved = ('approved=version-b\n', None)
    effects = [{'revision': 2, 'epoch': 1, 'request_id': 'seed-a', 'operation': 'update', 'approved_sha256': sha(payload.encode())}, {'revision': 3, 'epoch': 1, 'request_id': 'seed-b', 'operation': 'revoke', 'approved_sha256': None}]
    inputs = requests(case)
    commits = observed['call_commits']
    for revision, commit in enumerate(commits, 4):
        if set(commit) != {'revision', 'caller', 'epoch', 'request_id', 'operation', 'approved_sha256'} or commit['caller'] not in inputs or (commit['caller'] == 'later' and case['schedule'] != 'overlap_with_later'):
            raise ValueError('invalid committing-caller observation')
        req = inputs[commit['caller']]
        value = req['content_utf8']
        if value is not None:
            payload = value
        approved = None if value is None else sha(value.encode())
        effect = {'revision': revision, 'epoch': 2, 'request_id': req['request_id'], 'operation': 'revoke' if value is None else 'update', 'approved_sha256': approved}
        if commit != {**effect, 'caller': req['caller']}:
            raise ValueError('caller witness differs from declared bytes/revision')
        effects.append(effect)
    state = {'revision': 3 + len(commits), 'approved_sha256': approved, 'content_utf8': payload, 'content_sha256': sha(payload.encode())}
    output = {'status': 'blocked' if approved is None else 'delivered', 'reason': 'approval_revoked' if approved is None else 'verified_recovery', 'revision': state['revision'], 'delivered_utf8': None if approved is None else payload}
    if observed['state'] != state or observed['effects'] != effects or observed['delivery'] != output:
        raise ValueError('state/effect/value differs from committed caller history')
    receipts = observed['receipts']
    by_revision = {c['revision']: c for c in commits}
    seen = set()
    for receipt in receipts:
        if set(receipt) != {'revision', 'epoch', 'request_id', 'operation', 'approved_sha256', 'payload_utf8'}:
            raise ValueError('invalid receipt schema')
        commit = by_revision.get(receipt['revision'])
        if commit is None or any((receipt[k] != commit[k] for k in ('epoch', 'request_id', 'operation', 'approved_sha256'))):
            raise ValueError('receipt lacks its committed caller effect')
        if receipt['payload_utf8'] != inputs[commit['caller']]['content_utf8']:
            raise ValueError('receipt intent differs from committed caller bytes')
        key = (receipt['epoch'], receipt['request_id'])
        if key in seen:
            raise ValueError('duplicate stored receipt identity')
        seen.add(key)
    if seen != {(c['epoch'], c['request_id']) for c in commits}:
        raise ValueError('committed identity missing its receipt')
    return commits

def reply(status, req, revision=None, approved=None):
    return {'status': status, 'epoch': req['epoch'], 'request_id': req['request_id'], 'revision': revision, 'approved_sha256': approved}

def canonical_replies(case, commits) -> dict:
    inputs = requests(case)
    result = {}
    for caller in ('first', 'second'):
        req = inputs[caller]
        matches = [c for c in commits if c['epoch'] == req['epoch'] and c['request_id'] == req['request_id']]
        if not matches:
            result[caller] = None
            continue
        winner = matches[0]
        same = req['content_utf8'] == inputs[winner['caller']]['content_utf8']
        status = 'committed' if winner['caller'] == caller else 'replayed' if same else 'conflict'
        result[caller] = reply(status, req, winner['revision'] if status != 'conflict' else None, winner['approved_sha256'] if status != 'conflict' else None)
    return result

def expected_lookup(req, current, winner=None, scope='initial', origin='read'):
    same = winner is not None and req['content_utf8'] == winner['content_utf8']
    return {'scope': scope, 'origin': origin, 'observed_epoch': 2, 'current_revision': current, 'receipt_seen': winner is not None, 'receipt_revision': 4 if winner is not None else None, 'decision': 'missing' if winner is None else 'replayed' if same else 'conflict'}

def validate_attempt(case, record, busy_case):
    req = requests(case)[record['caller']]
    if record['request'] != req:
        raise ValueError('caller attempt changed its original identity or bytes')
    command = record['command']
    pause = 'after_lookup' if record['caller'] == 'first' and case['schedule'] != 'serial' else 'none'
    if len(command) != 16 or Path(command[1]).name != 'caller_worker.py' or command[2] != '--root' or (not command[3]) or (command[4:] != ['--mode', record['mode'], '--caller', req['caller'], '--key', req['request_id'], '--epoch', '2', '--intent', req['intent'], '--pause', pause]):
        raise ValueError('saved command differs from caller inputs')
    answer = record['response']
    if not isinstance(answer, dict) or set(answer) != {'status', 'epoch', 'request_id', 'revision', 'approved_sha256'} or answer['epoch'] != 2 or (answer['request_id'] != req['request_id']) or (answer['status'] not in {'committed', 'replayed', 'conflict', 'storage_error', 'busy', 'epoch_retired', 'future_epoch'}):
        raise ValueError('invalid caller response shape')
    events = []

    def event(kind, **fields):
        events.append({'seq': len(events), 'kind': kind, **fields})
    value = req['content_utf8']
    event('attempt_started', caller=req['caller'], epoch=2, request_id=req['request_id'], operation='revoke' if value is None else 'update', payload_sha256=None if value is None else sha(value.encode()))
    caller, number, mode = (record['caller'], record['attempt'], record['mode'])
    forced = case['schedule'] != 'serial'
    distinct = case['schedule'] == 'distinct_overlap'
    later = case['schedule'] == 'overlap_with_later'
    origin = 'transaction' if mode == 'transactional_lookup' else 'read'
    collision = forced and (not distinct) and (caller == 'first') and (not busy_case)
    is_busy = caller == 'second' and number == 1 and busy_case
    if is_busy:
        event('writer_busy', at='begin_immediate', sqlite_errorcode=5, sqlite_errorname='SQLITE_BUSY', busy_timeout_ms=0)
        if answer != reply('busy', req):
            raise ValueError('busy attempt claims a commitment')
    else:
        winner = None
        current = 3
        if caller == 'later':
            current = 4
        elif caller == 'second':
            if not forced or number == 2:
                current = 5 if later else 4
                if not distinct:
                    winner = requests(case)['first']
        event('lookup', **expected_lookup(req, current, winner, origin=origin))
        if winner is None:
            event('checkpoint', stage='after_lookup')
            if forced and caller == 'first':
                event('paused', stage='after_lookup', caller='first')
                event('resumed', stage='after_lookup', caller='first')
            if collision:
                event('duplicate_receipt', at='receipt_insert', sqlite_errorcode=1555, sqlite_errorname='SQLITE_CONSTRAINT_PRIMARYKEY', transaction_rolled_back=True)
                if mode == 'resolve_duplicate':
                    event('lookup', **expected_lookup(req, 5 if later else 4, requests(case)['second'], scope='resolution', origin='read'))
            else:
                event('checkpoint', stage='before_commit')
                event('checkpoint', stage='after_commit')
    event('result', response=answer)
    event('completed')
    decoded = [json.loads(line) for line in record['stdout'].splitlines()]
    if record['returncode'] != 0 or record['stderr'] or record['events'] != events or (decoded != events):
        raise ValueError('caller trace does not cover its declared lookup/rollback/barrier path')
    return (collision, is_busy)

def assess(row):
    case = row
    reqs = requests(case)
    forced = case['schedule'] != 'serial'
    later = case['schedule'] == 'overlap_with_later'
    attempts = row['attempts']
    second = [a for a in attempts if a['caller'] == 'second']
    if not second:
        raise ValueError('missing second caller')
    busy_case = second[0]['response']['status'] == 'busy'
    expected_order = [('first', 1), ('second', 1)]
    if forced and (not busy_case) and later:
        expected_order.append(('later', 1))
    if forced and busy_case:
        if later:
            expected_order.append(('later', 1))
        expected_order.append(('second', 2))
    if [(a['caller'], a['attempt']) for a in attempts] != expected_order:
        raise ValueError('unexpected logical caller attempts or lost retry identity')
    if busy_case and (not forced or row['mode'] != 'transactional_lookup'):
        raise ValueError('unexpected contention outside the declared held-writer scope')
    collisions = 0
    for a in attempts:
        if a['mode'] != row['mode']:
            raise ValueError('attempt changed comparison mode')
        collision, _ = validate_attempt(case, a, busy_case)
        collisions += collision
    for caller in ('first', 'second'):
        actual = [a for a in attempts if a['caller'] == caller][-1]['response']
        if row['logical_results'][caller] != actual or actual['status'] == 'busy':
            raise ValueError('missing final caller result')
    initial = check_capture(case, row['initial'])
    final = check_capture(case, row['final'])
    after_first = check_capture(case, row['after_first'])
    if initial:
        raise ValueError('fresh fixture already contains caller effects')
    if forced:
        during = check_capture(case, row['during_pause'])
        expected = [] if busy_case else ['second'] + (['later'] if later else [])
        if [c['caller'] for c in during] != expected:
            raise ValueError('pause capture contradicts concurrent winner')
    elif row['during_pause'] is not None:
        raise ValueError('serial case has a pause')
    if later:
        after_later = check_capture(case, row['later_capture'])
        if [c['caller'] for c in after_later] != (['first'] if busy_case else ['second']) + ['later']:
            raise ValueError('independent later publication used wrong order')
        actual_later = next((a['response'] for a in attempts if a['caller'] == 'later'))
        committed_later = after_later[-1]
        if actual_later != reply('committed', reqs['later'], committed_later['revision'], committed_later['approved_sha256']):
            raise ValueError('independent later acknowledgment differs from its effect')
        if busy_case and after_later[:-1] != after_first:
            raise ValueError('later publication changed the first completion prefix')
        if not busy_case and after_later != during:
            raise ValueError('pause observation changed independent later work')
    elif row['later_capture'] is not None:
        raise ValueError('undeclared later work')
    # Captures must extend the prior causal prefix. Extra effects remain
    # failures of the one-effect contract, never successful blocks.
    prefix = during if forced else []
    if after_first[:len(prefix)] != prefix or any((c['caller'] != 'first' for c in after_first[len(prefix):])):
        raise ValueError('first completion changed an earlier causal prefix')
    if forced and (not busy_case):
        if final != after_first:
            raise ValueError('final state changed without a scheduled writer')
    else:
        prefix = after_later if later else after_first
        if final[:len(prefix)] != prefix or any((c['caller'] != 'second' for c in final[len(prefix):])):
            raise ValueError('second completion changed an earlier causal prefix')
    journal = []

    def note(kind, **fields):
        journal.append({'seq': len(journal), 'kind': kind, **fields})

    def start(caller, n):
        note('attempt_started', caller=caller, attempt=n)

    def done(caller, n):
        a = next((a for a in attempts if (a['caller'], a['attempt']) == (caller, n)))
        note('attempt_completed', caller=caller, attempt=n, status=a['response']['status'])

    def independent():
        start('later', 1)
        done('later', 1)
        note('later_observed')
    note('seeded')
    start('first', 1)
    if forced:
        note('first_paused')
        start('second', 1)
        done('second', 1)
        if later and (not busy_case):
            independent()
        note('pause_observed')
        note('first_resumed')
        done('first', 1)
        note('first_observed')
        if busy_case:
            if later:
                independent()
            start('second', 2)
            done('second', 2)
    else:
        done('first', 1)
        note('first_observed')
        start('second', 1)
        done('second', 1)
    note('final_observed')
    if row['timeline'] != journal:
        raise ValueError('controller journal contradicts caller order')
    expected = canonical_replies(case, final)
    shared = case['schedule'] != 'distinct_overlap'
    shared_commits = [c for c in final if c['request_id'] == 'shared-request']
    one_shared = shared and len(shared_commits) == 1
    bodies_same = reqs['first']['content_utf8'] == reqs['second']['content_utf8']
    pair_correct = all((expected[c] is not None and row['logical_results'][c] == expected[c] for c in ('first', 'second')))
    pair_correct = pair_correct and (one_shared if shared else len(final) == 2 and {c['request_id'] for c in final} == {'shared-request', 'other-request'})
    race = case['schedule'] in {'overlap', 'overlap_with_later'}
    false_conflicts = sum((row['logical_results'][c]['status'] == 'conflict' and expected[c] is not None and (expected[c]['status'] == 'replayed') for c in ('first', 'second')))
    storage = sum((row['logical_results'][c]['status'] == 'storage_error' for c in ('first', 'second')))
    replay_correct = race and bodies_same and pair_correct
    changed_correct = race and (not bodies_same) and pair_correct
    later_preserved = later and row['final'] == row['later_capture']
    state = row['final']['state']
    coherent = state['approved_sha256'] is None or state['approved_sha256'] == state['content_sha256']
    return {'pair_correct': bool(pair_correct), 'race_pair_correct': race and bool(pair_correct), 'identical_race_replayed': replay_correct, 'changed_race_conflicted': changed_correct, 'false_conflicts': false_conflicts, 'modeled_storage_errors': storage, 'receipt_pk_aborts': collisions, 'busy_attempts': int(busy_case), 'completed_busy_retry': busy_case and second[-1]['response']['status'] != 'busy', 'one_shared_effect': one_shared, 'new_effects': len(final), 'serial_pair_correct': case['schedule'] == 'serial' and bool(pair_correct), 'distinct_pair_correct': not shared and bool(pair_correct), 'later_state_preserved': later_preserved, 'historical_replay_correct': later and bodies_same and bool(pair_correct) and later_preserved, 'later_pair_correct': later and bool(pair_correct), 'intrinsic_state_coherent': coherent, 'final_epoch_current': row['final']['active_epoch'] == 2, 'barrier_verified': forced, 'observations_consistent': True}

def run_case(case, mode):
    if mode not in MODES:
        raise ValueError('unknown mode')
    row = {**case, 'mode': mode, 'status': 'pending', 'error_phase': 'setup', 'error_type': None, 'attempts': [], 'logical_results': {}, 'initial': None, 'during_pause': None, 'after_first': None, 'later_capture': None, 'final': None, 'timeline': [], 'oracle': None, 'error_detail': None}
    process, consumed, drained, held = (None, b'', False, None)

    def note(kind, **fields):
        row['timeline'].append({'seq': len(row['timeline']), 'kind': kind, **fields})
    with tempfile.TemporaryDirectory(prefix='codeguardian-caller-') as directory:
        root = Path(directory)
        inputs = requests(case)

        def record(caller, number, pause):
            req = inputs[caller]
            command = [sys.executable, str(ROOT / 'experiments/caller_worker.py'), '--root', str(root), '--mode', mode, '--caller', caller, '--key', req['request_id'], '--epoch', '2', '--intent', req['intent'], '--pause', pause]
            r = {'caller': caller, 'attempt': number, 'mode': mode, 'request': req.copy(), 'command': command, 'returncode': None, 'stdout': '', 'stderr': '', 'events': [], 'response': None}
            row['attempts'].append(r)
            note('attempt_started', caller=caller, attempt=number)
            return r

        def finish(r, code, stdout, stderr):
            r.update(returncode=code, stdout=stdout.decode() if isinstance(stdout, bytes) else stdout, stderr=stderr.decode() if isinstance(stderr, bytes) else stderr)
            r['events'] = [json.loads(line) for line in r['stdout'].splitlines()]
            results = [e['response'] for e in r['events'] if e.get('kind') == 'result']
            if code != 0 or r['stderr'] or len(results) != 1:
                raise ValueError('caller child did not return a complete modeled result')
            r['response'] = results[0]
            note('attempt_completed', caller=r['caller'], attempt=r['attempt'], status=r['response']['status'])
            return r['response']

        def invoke(caller, number=1):
            r = record(caller, number, 'none')
            row['error_phase'] = 'caller_process'
            try:
                child = subprocess.run(r['command'], capture_output=True, text=True, timeout=STEP_TIMEOUT)
            except subprocess.TimeoutExpired as exc:
                r['stdout'] = exc.stdout.decode(errors='replace') if isinstance(exc.stdout, bytes) else exc.stdout or ''
                r['stderr'] = exc.stderr.decode(errors='replace') if isinstance(exc.stderr, bytes) else exc.stderr or ''
                raise
            return finish(r, child.returncode, child.stdout, child.stderr)

        def independent():
            result = invoke('later')
            if result['status'] != 'committed':
                raise ValueError('independent later intent failed')
            row['later_capture'] = capture(CallerPublicationStore(root, mode))
            note('later_observed')
        try:
            store = CallerPublicationStore(root, mode)
            store.initialize(b'approved=version-a\n')
            store.publish_request(1, 'seed-a', b'approved=version-b\n')
            store.publish_request(1, 'seed-b', None)
            store.retire(2)
            row['initial'] = capture(store)
            note('seeded')
            forced = case['schedule'] != 'serial'
            later = case['schedule'] == 'overlap_with_later'
            held = record('first', 1, 'after_lookup' if forced else 'none')
            process = subprocess.Popen(held['command'], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            if forced:
                row['error_phase'] = 'pause_barrier'
                consumed = wait_for_pause(process, 'after_lookup', STEP_TIMEOUT)
                note('first_paused')
                second = invoke('second')
                busy = second['status'] == 'busy'
                if later and (not busy):
                    independent()
                row['during_pause'] = capture(CallerPublicationStore(root, mode))
                note('pause_observed')
                note('first_resumed')
                resume = (json.dumps({'command': 'resume', 'stage': 'after_lookup', 'caller': 'first'}) + '\n').encode()
            else:
                busy = False
                resume = None
            row['error_phase'] = 'first_completion'
            tail, stderr = process.communicate(input=resume, timeout=STEP_TIMEOUT)
            drained = True
            row['logical_results']['first'] = finish(held, process.returncode, consumed + tail, stderr)
            row['after_first'] = capture(CallerPublicationStore(root, mode))
            note('first_observed')
            if forced:
                if busy:
                    if later:
                        independent()
                    second = invoke('second', 2)
                    if second['status'] == 'busy':
                        raise ValueError('scheduled caller retry did not complete')
                row['logical_results']['second'] = second
            else:
                row['logical_results']['second'] = invoke('second')
            row['final'] = capture(CallerPublicationStore(root, mode))
            note('final_observed')
            row['error_phase'] = 'oracle'
            row['oracle'] = assess(row)
            row.update(status='complete', error_phase=None)
        except (OSError, ValueError, RuntimeError, UnicodeError, sqlite3.Error, subprocess.SubprocessError) as exc:
            if isinstance(exc, subprocess.TimeoutExpired) and row['error_phase'] == 'pause_barrier':
                consumed = exc.stdout or b''
            elif isinstance(exc, BarrierFailure):
                consumed = exc.output
            row.update(status='infrastructure_error', error_type=type(exc).__name__, error_detail=str(exc))
        finally:
            if process is not None and (not drained):
                if process.poll() is None:
                    process.kill()
                tail, stderr = process.communicate(timeout=STEP_TIMEOUT)
                held.update(returncode=process.returncode, stdout=(consumed + tail).decode(errors='replace'), stderr=stderr.decode(errors='replace'))
    return row

def criteria(arms):
    v = [arms[m] for m in MODES]
    return {'shared_effect_and_total_effect_counts': all((x['one_shared_effect_cases'] == 15 and x['new_effects'] == 21 for x in v)), 'concurrent_pair_results': [x['race_pairs_correct'] for x in v] == [0, 6, 12, 12], 'replay_and_parameter_conflict_results': [x['identical_race_replays'] for x in v] == [0, 0, 6, 6] and [x['changed_race_conflicts'] for x in v] == [0, 6, 6, 6], 'false_conflicts_and_storage_errors': [x['false_conflicts'] for x in v] == [0, 6, 0, 0] and [x['modeled_storage_errors'] for x in v] == [12, 0, 0, 0], 'primary_key_abort_counts': [x['receipt_pk_aborts'] for x in v] == [12, 12, 12, 0], 'identity_preserving_busy_retries': all(([x[k] for x in v] == [0, 0, 0, 13] for k in ('busy_attempts', 'completed_busy_retries'))), 'historical_replies_and_later_state': [x['historical_replays'] for x in v] == [0, 0, 2, 2] and all((x['later_states_preserved'] == 4 for x in v)) and ([x['later_pairs_correct'] for x in v] == [0, 2, 4, 4]), 'serial_and_distinct_controls': all((x['serial_pairs_correct'] == 3 and x['distinct_pairs_correct'] == 1 for x in v)), 'all_captures_coherent_and_current': all((x['coherent_final_states'] == x['final_epoch_current'] == x['consistent_observations'] == 16 for x in v)), 'all_process_and_barrier_coverage': all((x['verified_barriers'] == 13 and x['infrastructure_errors'] == 0 for x in v)) and [x['child_completions'] for x in v] == [36, 36, 36, 49]}

def summarize(records, cases):
    pairs = [(r['case_id'], r['mode']) for r in records]
    wanted = {(c['case_id'], m) for c in cases for m in MODES}
    if len(pairs) != len(wanted) or set(pairs) != wanted:
        raise ValueError('exactly one record per declared case/mode required')
    declared = {c['case_id']: c for c in cases}
    for row in records:
        if any((row[k] != v for k, v in declared[row['case_id']].items())):
            raise ValueError('raw case changed its declaration')
        if row['status'] == 'complete':
            if row['oracle'] != assess(row):
                raise ValueError('stored verdict differs from caller observations')
        elif row['status'] != 'infrastructure_error' or row['oracle'] is not None:
            raise ValueError('invalid record status')
    mapping = {'pairs_correct': 'pair_correct', 'race_pairs_correct': 'race_pair_correct', 'identical_race_replays': 'identical_race_replayed', 'changed_race_conflicts': 'changed_race_conflicted', 'completed_busy_retries': 'completed_busy_retry', 'one_shared_effect_cases': 'one_shared_effect', 'serial_pairs_correct': 'serial_pair_correct', 'distinct_pairs_correct': 'distinct_pair_correct', 'later_states_preserved': 'later_state_preserved', 'historical_replays': 'historical_replay_correct', 'later_pairs_correct': 'later_pair_correct', 'coherent_final_states': 'intrinsic_state_coherent', 'final_epoch_current': 'final_epoch_current', 'verified_barriers': 'barrier_verified', 'consistent_observations': 'observations_consistent'}
    arms = {}
    for mode in MODES:
        rows = [r for r in records if r['mode'] == mode]
        good = [r for r in rows if r['status'] == 'complete']

        def total(k):
            return sum(((r['oracle'] or {}).get(k, 0) for r in rows))
        arms[mode] = {'cases': len(rows), 'shared_cases': sum((r['schedule'] != 'distinct_overlap' for r in rows)), 'race_cases': sum((r['schedule'] in {'overlap', 'overlap_with_later'} for r in rows)), 'identical_race_cases': sum((r['schedule'] in {'overlap', 'overlap_with_later'} and PATTERNS[r['pattern']][0] == PATTERNS[r['pattern']][1] for r in rows)), 'changed_race_cases': sum((r['schedule'] in {'overlap', 'overlap_with_later'} and PATTERNS[r['pattern']][0] != PATTERNS[r['pattern']][1] for r in rows)), 'later_cases': sum((r['schedule'] == 'overlap_with_later' for r in rows)), 'serial_controls': sum((r['schedule'] == 'serial' for r in rows)), 'distinct_controls': sum((r['schedule'] == 'distinct_overlap' for r in rows)), 'child_completions': sum((len(r['attempts']) for r in good)), 'infrastructure_errors': len(rows) - len(good), **{k: total(k) for k in ('false_conflicts', 'modeled_storage_errors', 'receipt_pk_aborts', 'busy_attempts', 'new_effects')}, **{dst: total(src) for dst, src in mapping.items()}}
    return {'arms': arms, 'criteria': criteria(arms)}

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dataset', type=Path, required=True)
    parser.add_argument('--base-commit', required=True)
    parser.add_argument('--freeze-commit', required=True)
    parser.add_argument('--output-dir', type=Path, default=ROOT / 'experiments/results')
    args = parser.parse_args()
    if sys.version_info < (3, 11):
        raise RuntimeError('caller study requires Python 3.11+ numeric SQLite result codes')
    started = datetime.now(timezone.utc)
    cases = load_cases(args.dataset)
    records = [run_case(c, m) for c in cases for m in MODES]
    summary = summarize(records, cases)
    run_id = started.strftime('%Y-%m-%dT%H-%M-%S-%fZ-caller-v1')
    args.output_dir.mkdir(parents=True, exist_ok=True)
    raw = args.output_dir / (run_id + '.jsonl')
    metadata = {'started_at_utc': started.isoformat(), 'finished_at_utc': datetime.now(timezone.utc).isoformat(), 'python_version': platform.python_version(), 'sqlite_version': sqlite3.sqlite_version, 'platform': platform.platform(), 'base_commit': args.base_commit, 'freeze_commit': args.freeze_commit, 'command': [sys.executable, *sys.argv], 'dataset': str(args.dataset), 'dataset_sha256': sha(args.dataset.read_bytes()), 'source_sha256': {p: sha((ROOT / p).read_bytes()) for p in SOURCES}, 'results_file': raw.name, 'summary': summary, 'interpretation_limit': 'Sixteen developer-visible caller schedules per mode; fixed epoch and retained receipts; exact rollback and caller outcomes; no many-caller fairness, latency, network, retirement-during-resolution, external-effect, or crash claim.'}
    with raw.open('x', encoding='utf-8') as handle:
        for r in records:
            handle.write(json.dumps(r, ensure_ascii=False) + '\n')
    with (args.output_dir / (run_id + '-summary.json')).open('x', encoding='utf-8') as handle:
        json.dump(metadata, handle, indent=2, ensure_ascii=False)
        handle.write('\n')
    print(json.dumps(summary, indent=2))
    print('Saved ' + run_id)
    return int(any((a['infrastructure_errors'] for a in summary['arms'].values())))
if __name__ == '__main__':
    raise SystemExit(main())
