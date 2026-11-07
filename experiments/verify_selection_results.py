"""Independently reconstruct source completeness, work completion and replays."""
from __future__ import annotations
import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
MODES = ('cached_selection', 'separate_refresh', 'transactional_selection', 'validated_selection')
STAGES = ('after_selection', 'after_refresh', 'before_commit', 'after_commit')
VALUES = {'ascii': 'approved=version-b\n', 'empty': '', 'unicode': 'approved=안전 ✓\n', 'revoke': None, 'later': 'approved=version-d\n'}
GRIDS = {'after_selection': ('ascii', 'empty', 'unicode', 'revoke'), 'after_refresh': ('ascii', 'empty', 'unicode', 'revoke'), 'before_commit': ('ascii', 'revoke'), 'after_commit': ('ascii', 'revoke'), 'publisher_first': ('ascii', 'empty', 'unicode', 'revoke'), 'migration_first': ('ascii', 'revoke'), 'current_epoch': ('ascii', 'empty', 'unicode', 'revoke'), 'publisher_first_later': ('ascii', 'revoke')}
COLUMNS = ['epoch', 'request_id', 'operation', 'payload_sha256', 'revision']
SOURCES = ('src/selection_store.py', 'experiments/selection_worker.py', 'experiments/run_selection_comparison.py', 'experiments/verify_selection_results.py', 'tests/test_selection_store.py', 'docs/SELECTION_PROTOCOL.md', 'src/compaction_store.py', 'src/publication_store.py', 'src/retry_store.py', 'src/retirement_store.py', 'src/overlap_store.py', 'experiments/run_overlap_comparison.py')
FIELDS = ('final_epoch_2', 'old_full_absent', 'coherent_final', 'current_history_correct', 'gap_lost_history', 'gap_old_committed', 'gap_old_denied', 'old_committed', 'old_replayed', 'current_completed', 'current_replayed', 'summary_rows', 'missing_summary_rows', 'complete_summary_coverage', 'busy_attempts', 'completed_pub_retry', 'old_denied', 'stale_migrations', 'completed_migration_retry', 'stale_untouched', 'prefix_original_supported', 'later_historical_supported', 'migration_first_denied', 'before_commit_denied', 'after_commit_denied', 'migration_witness_present', 'stale_commit_witness', 'publication_epochs_valid', 'verified_barriers', 'migration_completions', 'publisher_completions', 'later_completions', 'child_completions', 'false_history', 'followup_no_effect', 'publisher_result_correct', 'followup_result_correct', 'consistent_observations')

def digest(text):
    return None if text is None else hashlib.sha256(text.encode()).hexdigest()

def load_manifest(path):
    document = json.loads(path.read_text())
    if not isinstance(document, dict) or set(document) != {'schema_version', 'cases'} or document['schema_version'] != 'selection-eval-v1':
        raise ValueError('unsupported manifest')
    cases = document['cases']
    expected = {(schedule, value) for schedule, values in GRIDS.items() for value in values}
    if not isinstance(cases, list) or len(cases) != 24 or any((not isinstance(c, dict) or set(c) != {'case_id', 'schedule', 'value'} or (not all((isinstance(v, str) and v for v in c.values()))) for c in cases)) or (len({c['case_id'] for c in cases}) != 24) or ({(c['schedule'], c['value']) for c in cases} != expected):
        raise ValueError('manifest lost or repeated a semantic history')
    return cases

def incoming(row, role='inflight'):
    value = 'later' if role == 'later' else row['value']
    return {'epoch': 2 if role == 'inflight' and row['schedule'] == 'current_epoch' else 1, 'request_id': role, 'value': value, 'content_utf8': VALUES[value]}

def response(status, req, revision=None, approval=None):
    return {'status': status, 'epoch': req['epoch'], 'request_id': req['request_id'], 'revision': revision, 'approved_sha256': approval}

def receipt(req, revision):
    value = req['content_utf8']
    return {'epoch': req['epoch'], 'request_id': req['request_id'], 'operation': 'revoke' if value is None else 'update', 'payload_utf8': value, 'revision': revision, 'approved_sha256': digest(value)}

def shortened(full):
    return {'epoch': full['epoch'], 'request_id': full['request_id'], 'operation': full['operation'], 'payload_sha256': full['approved_sha256'], 'revision': full['revision']}

def audit_snapshot(row, snapshot):
    if snapshot['active_epoch'] not in (1, 2) or snapshot['summary_columns'] != COLUMNS:
        raise ValueError('namespace or compact schema differs')
    intents = [{'epoch': 1, 'request_id': 'seed-a', 'content_utf8': VALUES['ascii']}, {'epoch': 1, 'request_id': 'seed-b', 'content_utf8': None}]
    previous_epoch = 1
    for number, witness in enumerate(snapshot['publication_witnesses'], 4):
        key = witness['request_id']
        if key not in {'inflight', 'later'} or (key == 'later' and row['schedule'] != 'publisher_first_later'):
            raise ValueError('undeclared committing request')
        req = incoming(row, key)
        if set(witness) != {'revision', 'requested_epoch', 'active_epoch', 'request_id'} or witness['revision'] != number or witness['requested_epoch'] != req['epoch'] or (not previous_epoch <= witness['active_epoch'] <= snapshot['active_epoch']):
            raise ValueError('witness contradicts committed epoch/request history')
        previous_epoch = witness['active_epoch']
        intents.append(req)
    full = [receipt(req, n) for n, req in enumerate(intents, 2)]
    expected_effects = [{k: v for k, v in r.items() if k != 'payload_utf8'} for r in full]
    payload = 'approved=version-a\n'
    approval = digest(payload)
    for r in full:
        if r['payload_utf8'] is not None:
            payload = r['payload_utf8']
        approval = r['approved_sha256']
    state = {'revision': len(full) + 1, 'approved_sha256': approval, 'content_utf8': payload, 'content_sha256': digest(payload)}
    delivery = {'status': 'blocked' if approval is None else 'delivered', 'reason': 'approval_revoked' if approval is None else 'verified_recovery', 'revision': state['revision'], 'delivered_utf8': None if approval is None else payload}
    by_revision = {r['revision']: r for r in full}
    for field, compact in (('receipts', False), ('summaries', True)):
        records = snapshot[field]
        identities = [(r['epoch'], r['request_id']) for r in records]
        if identities != sorted(set(identities)):
            raise ValueError('unordered or repeated authority')
        for r in records:
            known = by_revision.get(r['revision'])
            if known is None or r != (shortened(known) if compact else known):
                raise ValueError('authority does not bind a real operation/value/effect')
    witness = snapshot['migration_witness']
    if witness is not None and (set(witness) != {'target_epoch', 'selected_revision', 'write_revision', 'selected_count', 'write_count'} or witness['target_epoch'] != 2 or (not 3 <= witness['selected_revision'] <= witness['write_revision'] <= state['revision'])):
        raise ValueError('invalid migration source witness')
    if set(snapshot) != {'state', 'active_epoch', 'effects', 'receipts', 'summaries', 'summary_columns', 'publication_witnesses', 'migration_witness', 'delivery', 'sqlite_settings'} or snapshot['state'] != state or snapshot['effects'] != expected_effects or (snapshot['delivery'] != delivery) or (snapshot['sqlite_settings'] != {'journal_mode': 'delete', 'synchronous': 2, 'integrity_check': 'ok'}):
        raise ValueError('snapshot differs from reconstructed durable current policy')
    return full

def selected_view(snapshot):
    return {'active_epoch': snapshot['active_epoch'], 'current_revision': snapshot['state']['revision'], 'receipts': [{**shortened(r), 'approved_sha256': r['approved_sha256']} for r in snapshot['receipts'] if r['epoch'] < 2]}

def trace(record, expected, flags, kind):
    command = record['command']
    if len(command) != 2 + 2 * len(flags) or Path(command[1]).name != 'selection_worker.py' or len(set(command[2::2])) != len(flags) or (dict(zip(command[2::2], command[3::2])) != flags):
        raise ValueError('saved actor command changed its identity or scope')
    numbered = [{'seq': n, **e} for n, e in enumerate(expected)]
    if record['returncode'] != 0 or record['stderr'] or record['events'] != numbered or ([json.loads(line) for line in record['stdout'].splitlines()] != numbered) or ([e['response'] for e in expected if e['kind'] == kind] != [record['response']]):
        raise ValueError('actor did not preserve a complete normal trace')

def publication_trace(row, record):
    req = incoming(row, record['role'])
    if record['request'] != req:
        raise ValueError('retry changed epoch, ID, operation or bytes')
    before, after, answer = (record['before'], record['after'], record['response'])
    audit_snapshot(row, before)
    audit_snapshot(row, after)
    if set(answer) != {'status', 'epoch', 'request_id', 'revision', 'approved_sha256'} or answer['epoch'] != req['epoch'] or answer['request_id'] != req['request_id'] or (answer['status'] not in {'committed', 'replayed', 'conflict', 'outcome_unavailable', 'future_epoch', 'busy'}):
        raise ValueError('invalid publication result shape')
    events = [{'kind': 'publication_started', 'epoch': req['epoch'], 'request_id': req['request_id'], 'operation': 'revoke' if req['content_utf8'] is None else 'update', 'payload_sha256': digest(req['content_utf8'])}]
    if answer['status'] == 'busy':
        events.append({'kind': 'writer_busy', 'at': 'begin_immediate', 'sqlite_errorcode': 5, 'sqlite_errorname': 'SQLITE_BUSY', 'busy_timeout_ms': 0})
        if after != before or answer != response('busy', req):
            raise ValueError('busy result created an effect or commitment')
    else:
        if any(((r['epoch'], r['request_id']) == (req['epoch'], req['request_id']) for r in before['receipts'] + before['summaries'])):
            raise ValueError('unexpected previously committed runtime key')
        decision = 'new' if req['epoch'] == before['active_epoch'] else 'outcome_unavailable' if req['epoch'] < before['active_epoch'] else 'future_epoch'
        events.append({'kind': 'publication_view', 'requested_epoch': req['epoch'], 'observed_epoch': before['active_epoch'], 'current_revision': before['state']['revision'], 'receipt_kind': 'none', 'decision': decision})
        if decision == 'new':
            events += [{'kind': 'checkpoint', 'stage': 'before_commit'}, {'kind': 'checkpoint', 'stage': 'after_commit'}]
            revision = before['state']['revision'] + 1
            w = {'revision': revision, 'requested_epoch': req['epoch'], 'active_epoch': before['active_epoch'], 'request_id': req['request_id']}
            if after['publication_witnesses'] != before['publication_witnesses'] + [w] or after['migration_witness'] != before['migration_witness'] or after['summaries'] != before['summaries'] or (after['receipts'] != sorted(before['receipts'] + [receipt(req, revision)], key=lambda r: (r['epoch'], r['request_id']))):
                raise ValueError('publisher did not extend state, effect and authority atomically')
        elif before != after:
            raise ValueError('closed/future publication changed state')
    events += [{'kind': 'publication_result', 'response': answer}, {'kind': 'completed'}]
    command = record['command']
    if len(command) < 4 or not command[3]:
        raise ValueError('missing fixture root')
    trace(record, events, {'--root': command[3], '--mode': row['mode'], '--role': 'publish', '--epoch': str(req['epoch']), '--key': req['request_id'], '--value': req['value']}, 'publication_result')

def migration_trace(row, record):
    before, after, pause = (record['before'], record['after'], record['pause'])
    audit_snapshot(row, before)
    audit_snapshot(row, after)
    if before['active_epoch'] != 1 or before['summaries'] or before['migration_witness'] is not None:
        raise ValueError('source namespace was already migrated')
    at_pause = record['pause_capture']
    if pause == 'none':
        if at_pause is not None:
            raise ValueError('undeclared pause snapshot')
    else:
        audit_snapshot(row, at_pause)
    first = selected_view(before)
    chosen = selected_view(at_pause) if row['mode'] == 'separate_refresh' and pause == 'after_selection' else first
    actual = selected_view(at_pause) if pause in {'after_selection', 'after_refresh', 'before_commit'} else first
    stale = row['mode'] == 'validated_selection' and chosen != actual
    e = [{'kind': 'migration_started', 'target_epoch': 2}]

    def checkpoint(stage):
        e.append({'kind': 'checkpoint', 'stage': stage})
        if pause == stage:
            e.append({'kind': 'paused', 'stage': stage, 'role': 'migrate'})
            e.append({'kind': 'resumed', 'stage': stage, 'role': 'migrate'})
    origin = 'transaction' if row['mode'] == 'transactional_selection' else 'read'
    e.append({'kind': 'selection', 'scope': 'initial', 'origin': origin, **first})
    checkpoint('after_selection')
    final_origin = 'transaction' if row['mode'] == 'transactional_selection' else 'read' if row['mode'] == 'separate_refresh' else 'cached'
    e.append({'kind': 'selection', 'scope': 'final', 'origin': final_origin, **chosen})
    checkpoint('after_refresh')
    e.append({'kind': 'validation', 'matched': chosen == actual, 'observed': actual})
    if stale:
        e.append({'kind': 'selection_changed', 'transaction_rolled_back': True})
        result = {'status': 'stale_selection', 'active_epoch': actual['active_epoch'], 'target_epoch': 2}
        if after != at_pause:
            raise ValueError('failed validation changed the fence or authority')
    else:
        checkpoint('before_commit')
        checkpoint('after_commit')
        result = {'status': 'migrated', 'active_epoch': 2, 'target_epoch': 2}
        source = at_pause if pause in {'after_selection', 'after_refresh', 'before_commit'} else before
        witness = {'target_epoch': 2, 'selected_revision': chosen['current_revision'], 'write_revision': actual['current_revision'], 'selected_count': len(chosen['receipts']), 'write_count': len(actual['receipts'])}
        model = {**source, 'active_epoch': 2, 'receipts': [], 'summaries': [{k: v for k, v in r.items() if k != 'approved_sha256'} for r in chosen['receipts']], 'migration_witness': witness}
        if after != model:
            raise ValueError('migration differs from selected source and actual effect history')
    if record['response'] != result:
        raise ValueError('incorrect migration retry/completion signal')
    e += [{'kind': 'migration_result', 'response': result}, {'kind': 'completed'}]
    command = record['command']
    if len(command) < 4 or not command[3]:
        raise ValueError('missing migration fixture')
    trace(record, e, {'--root': command[3], '--mode': row['mode'], '--role': 'migrate', '--pause': pause}, 'migration_result')

def evaluate(row):
    ms, ps = (row['migrations'], row['publications'])
    if not ms or not ps:
        raise ValueError('missing actor')
    commands = [r['command'] for r in ms + ps]
    if any((len(c) < 4 for c in commands)) or len({(c[0], c[1], c[3]) for c in commands}) != 1:
        raise ValueError('actors changed shared interpreter/worker/fixture')
    for r in ps:
        publication_trace(row, r)
    for r in ms:
        migration_trace(row, r)
    for field in ('initial', 'followup_before', 'followup_after'):
        audit_snapshot(row, row[field])
    initial = row['initial']
    if initial['active_epoch'] != 1 or initial['publication_witnesses'] or initial['migration_witness'] is not None or initial['summaries']:
        raise ValueError('wrong initial namespace')
    seeds = audit_snapshot(row, initial)
    if initial['receipts'] != sorted(seeds, key=lambda r: (r['epoch'], r['request_id'])):
        raise ValueError('initial full receipts missing')
    primary = [r for r in ps if r['role'] == 'inflight']
    later = [r for r in ps if r['role'] == 'later']
    busy = primary[0]['response']['status'] == 'busy'
    stale = ms[0]['response']['status'] == 'stale_selection'
    if [r['attempt'] for r in primary] != list(range(1, 2 + int(busy))) or [r['attempt'] for r in ms] != list(range(1, 2 + int(stale))) or len(later) != int(row['schedule'] == 'publisher_first_later') or (later and later[0]['attempt'] != 1):
        raise ValueError('lost/extra logical attempt or retry')
    pause = row['schedule'] if row['schedule'] in STAGES else 'none'
    if ms[0]['pause'] != pause or any((m['pause'] != 'none' for m in ms[1:])):
        raise ValueError('live barrier scope changed')
    journal = []
    current = initial

    def note(kind, **fields):
        journal.append({'seq': len(journal), 'kind': kind, **fields})

    def publish(record):
        nonlocal current
        if record['before'] != current:
            raise ValueError('publication changed a causal before-prefix')
        note('publication_requested', role=record['role'], attempt=record['attempt'])
        note('publication_completed', role=record['role'], attempt=record['attempt'], status=record['response']['status'])
        note('publication_observed', role=record['role'], attempt=record['attempt'])
        current = record['after']

    def migration(record, held=False):
        nonlocal current
        if record['before'] != current:
            raise ValueError('migration changed a causal before-prefix')
        note('migration_requested', attempt=record['attempt'], pause=record['pause'])
        if held:
            note('migration_paused', stage=pause)
            if pause == 'after_commit':
                current = record['after']
            publish(primary[0])
            if record['pause_capture'] != current:
                raise ValueError('pause snapshot changed without an actor')
            note('migration_pause_observed')
            note('migration_resumed', stage=pause)
        note('migration_completed', attempt=record['attempt'], status=record['response']['status'])
        note('migration_observed', attempt=record['attempt'])
        current = record['after']
    note('seeded')
    if row['schedule'] in {'publisher_first', 'publisher_first_later'}:
        publish(primary[0])
        if later:
            publish(later[0])
        migration(ms[0])
    elif pause != 'none':
        migration(ms[0], True)
        if stale:
            migration(ms[1])
        if busy:
            publish(primary[1])
    else:
        migration(ms[0])
        publish(primary[0])
    if row['followup_before'] != current:
        raise ValueError('final prefix differs from last completed actor')
    note('final_observed')
    note('followup_requested')
    note('followup_completed', status=row['followup_response']['status'])
    note('followup_observed')
    if row['timeline'] != journal:
        raise ValueError('controller order contradicts actor traces')
    req = incoming(row)
    result = row['followup_response']
    if row['followup_request'] != req or set(result) != {'status', 'epoch', 'request_id', 'revision', 'approved_sha256'} or result['epoch'] != req['epoch'] or (result['request_id'] != req['request_id']) or (result['status'] not in {'committed', 'replayed', 'conflict', 'outcome_unavailable', 'future_epoch'}):
        raise ValueError('follow-up identity or shape changed')
    final = row['followup_before']
    records = audit_snapshot(row, final)
    original = [r for r in records if r['request_id'] == 'inflight']
    if len(original) > 1:
        raise ValueError('same request identity committed twice')
    committed = bool(original)
    available = any(((r['epoch'], r['request_id']) == (req['epoch'], req['request_id']) for r in final['receipts'] + final['summaries']))
    expected = response('replayed', req, original[0]['revision'], original[0]['approved_sha256']) if committed else response('outcome_unavailable', req)
    supported = committed and available and (result == expected)
    old = req['epoch'] == 1
    refused = old and (not committed) and (primary[-1]['response'] == response('outcome_unavailable', req))
    expected_publisher = response('committed', req, original[0]['revision'], original[0]['approved_sha256']) if committed else response('outcome_unavailable', req)
    keys = {(r['epoch'], r['request_id'], r['revision']) for r in final['summaries']}
    missing = [r for r in records if r['epoch'] == 1 and (r['epoch'], r['request_id'], r['revision']) not in keys]
    gap = row['schedule'] in {'after_selection', 'after_refresh'}
    witness = final['migration_witness']
    stale_attempts = [m for m in ms if m['response']['status'] == 'stale_selection']
    return {'final_epoch_2': final['active_epoch'] == 2, 'old_full_absent': not any((r['epoch'] < 2 for r in final['receipts'])), 'coherent_final': final['state']['approved_sha256'] in (None, final['state']['content_sha256']), 'current_history_correct': True, 'gap_lost_history': gap and old and committed and (not available), 'gap_old_committed': gap and old and committed, 'gap_old_denied': gap and refused, 'old_committed': old and committed, 'old_replayed': old and supported, 'current_completed': not old and committed and (primary[-1]['response'] == expected_publisher), 'current_replayed': not old and supported, 'summary_rows': len(final['summaries']), 'missing_summary_rows': len(missing), 'complete_summary_coverage': not missing, 'busy_attempts': sum((p['response']['status'] == 'busy' for p in ps)), 'completed_pub_retry': busy and primary[-1]['response']['status'] != 'busy', 'old_denied': refused, 'stale_migrations': len(stale_attempts), 'completed_migration_retry': stale and ms[-1]['response']['status'] == 'migrated', 'stale_untouched': sum((m['after'] == m['pause_capture'] and m['after']['active_epoch'] == 1 and (len(m['after']['receipts']) == 3) and (m['after']['migration_witness'] is None) for m in stale_attempts)), 'prefix_original_supported': row['schedule'] in {'publisher_first', 'publisher_first_later'} and supported, 'later_historical_supported': row['schedule'] == 'publisher_first_later' and supported and (result['revision'] == 4) and (final['state']['revision'] == 5) and (final['state']['content_utf8'] == VALUES['later']), 'migration_first_denied': row['schedule'] == 'migration_first' and refused, 'before_commit_denied': row['schedule'] == 'before_commit' and refused, 'after_commit_denied': row['schedule'] == 'after_commit' and refused, 'migration_witness_present': witness is not None, 'stale_commit_witness': witness is not None and (witness['selected_revision'] != witness['write_revision'] or witness['selected_count'] != witness['write_count']), 'publication_epochs_valid': all((w['requested_epoch'] == w['active_epoch'] for w in final['publication_witnesses'])), 'verified_barriers': int(pause != 'none'), 'migration_completions': len(ms), 'publisher_completions': len(primary), 'later_completions': len(later), 'child_completions': len(ms) + len(ps), 'false_history': int(result['status'] in {'replayed', 'conflict'} and (not supported)), 'followup_no_effect': row['followup_after'] == final, 'publisher_result_correct': primary[-1]['response'] == expected_publisher, 'followup_result_correct': result == (expected if committed and available else response('outcome_unavailable', req)), 'consistent_observations': True}

def recount(records, cases):
    wanted = {(c['case_id'], m) for c in cases for m in MODES}
    if len(records) != 96 or {(r['case_id'], r['mode']) for r in records} != wanted:
        raise ValueError('missing, extra or repeated case/mode')
    declarations = {c['case_id']: c for c in cases}
    arms = {}
    for mode in MODES:
        rows = [r for r in records if r['mode'] == mode]
        good = []
        for row in rows:
            if any((row[k] != v for k, v in declarations[row['case_id']].items())):
                raise ValueError('raw declaration differs from manifest')
            if row['status'] == 'complete':
                actual = evaluate(row)
                if actual != row['oracle']:
                    raise ValueError('saved oracle disagrees with independent reconstruction')
                good.append(actual)
            elif row['status'] != 'infrastructure_error' or row['oracle'] is not None:
                raise ValueError('invalid raw execution status')
        arms[mode] = {'cases': len(rows), 'source_gap_cases': sum((r['schedule'] in {'after_selection', 'after_refresh'} for r in rows)), 'old_intent_cases': sum((r['schedule'] != 'current_epoch' for r in rows)), 'current_cases': sum((r['schedule'] == 'current_epoch' for r in rows)), 'infrastructure_errors': len(rows) - len(good), **{f: sum((v[f] for v in good)) for f in FIELDS}}

    def vector(field):
        return [arms[m][field] for m in MODES]
    criteria = {'current_state_and_closure': all((vector(f) == [24] * 4 for f in ('final_epoch_2', 'old_full_absent', 'coherent_final', 'current_history_correct'))), 'source_gap_losses_and_publication': vector('gap_lost_history') == [8, 4, 0, 0] and vector('gap_old_committed') == [8, 8, 0, 8] and (vector('gap_old_denied') == [0, 0, 8, 0]), 'actual_committed_history_replays': vector('old_committed') == [14, 14, 6, 14] and vector('old_replayed') == [6, 10, 6, 14] and (vector('current_replayed') == [4] * 4), 'summary_completeness': vector('summary_rows') == [56, 60, 56, 64] and vector('missing_summary_rows') == [8, 4, 0, 0] and (vector('complete_summary_coverage') == [16, 20, 24, 24]), 'publisher_contention_and_refusal': vector('busy_attempts') == vector('completed_pub_retry') == [2, 2, 10, 2] and vector('old_denied') == [6, 6, 14, 6], 'validated_retry_preserves_source': vector('stale_migrations') == vector('completed_migration_retry') == vector('stale_untouched') == [0, 0, 0, 8], 'ordering_and_historical_controls': vector('prefix_original_supported') == [6] * 4 and vector('later_historical_supported') == [2] * 4 and (vector('migration_first_denied') == vector('before_commit_denied') == vector('after_commit_denied') == [2] * 4) and (vector('current_completed') == [4] * 4), 'transactional_witnesses': vector('migration_witness_present') == vector('publication_epochs_valid') == [24] * 4 and vector('stale_commit_witness') == [8, 4, 0, 0], 'process_and_barrier_coverage': vector('verified_barriers') == [12] * 4 and vector('migration_completions') == [24, 24, 24, 32] and (vector('publisher_completions') == [26, 26, 34, 26]) and (vector('later_completions') == [2] * 4) and (vector('child_completions') == [52, 52, 60, 60]), 'supported_evidence_and_no_unexpected_errors': vector('false_history') == [0] * 4 and vector('followup_no_effect') == vector('publisher_result_correct') == vector('followup_result_correct') == vector('consistent_observations') == [24] * 4 and (vector('infrastructure_errors') == [0] * 4)}
    return {'arms': arms, 'criteria': criteria}

def verify(summary_path, dataset):
    metadata = json.loads(summary_path.read_text())
    if metadata['dataset_sha256'] != hashlib.sha256(dataset.read_bytes()).hexdigest():
        raise ValueError('dataset hash changed')
    hashes = {p: hashlib.sha256((ROOT / p).read_bytes()).hexdigest() for p in SOURCES}
    if metadata['source_sha256'] != hashes:
        raise ValueError('source bytes or source hash set changed')
    name = metadata['results_file']
    if Path(name).name != name or not name.endswith('-selection-v1.jsonl'):
        raise ValueError('invalid raw artifact filename')
    raw = summary_path.parent / name
    records = [json.loads(line) for line in raw.read_text().splitlines()]
    actual = recount(records, load_manifest(dataset))
    if actual != metadata['summary']:
        raise ValueError('summary counters differ from raw observations')
    return {'verified_at_utc': datetime.now(timezone.utc).isoformat(), 'summary_file': summary_path.name, 'raw_file': name, 'records': len(records), 'source_hashes_checked': len(hashes), 'summary_sha256': hashlib.sha256(summary_path.read_bytes()).hexdigest(), 'raw_sha256': hashlib.sha256(raw.read_bytes()).hexdigest(), 'independent_summary': actual, 'all_criteria_passed': all(actual['criteria'].values()), 'scope': 'Independent stdlib reconstruction; no measured module imports; actual committed-history denominators; trusted observers and supplied labels, not external attestation.'}

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--summary', type=Path, required=True)
    parser.add_argument('--dataset', type=Path, required=True)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    report = verify(args.summary, args.dataset)
    encoded = json.dumps(report, indent=2, sort_keys=True) + '\n'
    if args.output:
        with args.output.open('x', encoding='utf-8') as handle:
            handle.write(encoded)
    print(encoded, end='')
    return int(not report['all_criteria_passed'])
if __name__ == '__main__':
    raise SystemExit(main())
