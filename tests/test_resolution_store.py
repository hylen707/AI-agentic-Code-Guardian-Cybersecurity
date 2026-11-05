import ast
import copy
import json
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from experiments.run_resolution_comparison import ROOT, assess, load_cases, run_case, summarize
from experiments.verify_resolution_results import evaluate, load_manifest, recount
from src.resolution_store import MODES, ResolutionPublicationStore


class ResolutionStoreTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory(prefix='codeguardian-resolution-test-')
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.number = 0

    def store(self, mode='fenced_resolution'):
        self.number += 1
        store = ResolutionPublicationStore(self.root / str(self.number), mode)
        store.initialize(b'approved=version-a\n')
        store.publish_request(1, 'seed-a', b'approved=version-b\n')
        store.publish_request(1, 'seed-b', None)
        store.retire(2)
        return store

    def race(self, store, first=b'B', second=b'B', later=False, retire=True, event=lambda *a, **k: None):
        attempts = []
        def checkpoint(stage):
            if stage == 'after_precheck':
                result = store.publish('second', 2, 'shared', second)
                self.assertEqual(result['status'], 'committed')
            elif stage == 'before_resolution' and retire:
                result = store.try_retire(3)
                attempts.append(result)
                if later and result['status'] == 'retired':
                    store.publish('later', 3, 'later', b'D')
        result = store.publish('first', 2, 'shared', first, checkpoint=checkpoint, event=event)
        if attempts and attempts[0]['status'] == 'busy':
            attempts.append(store.try_retire(3))
            if later:
                store.publish('later', 3, 'later', b'D')
        return result, attempts

    def test_invalid_mode_caller_epoch_key_and_payload_are_rejected(self):
        with self.assertRaises(ValueError):
            ResolutionPublicationStore(self.root, 'unknown')
        store = self.store()
        before = store.inspect()
        for args in (('unknown', 2, 'new', b'B'), ('first', True, 'new', b'B'),
                     ('first', 2, '../bad', b'B'), ('first', 2, 'new', 'text')):
            with self.subTest(args=args), self.assertRaises(ValueError):
                store.publish(*args)
        self.assertEqual(store.inspect(), before)

    def test_retained_serial_receipt_returns_original_revision_after_later_work(self):
        for mode in MODES:
            store = self.store(mode)
            original = store.publish('first', 2, 'shared', b'B')
            store.publish('later', 2, 'later', b'D')
            before = store.inspect()
            self.assertEqual(store.publish('second', 2, 'shared', b'B'), {**original, 'status': 'replayed'})
            self.assertEqual(store.inspect(), before)

    def test_empty_update_revocation_and_unicode_bytes_remain_distinct(self):
        for first, second in ((b'', None), (None, b''), ('é'.encode(), 'e\u0301'.encode())):
            store = self.store()
            store.publish('first', 2, 'shared', first)
            before = store.inspect()
            self.assertEqual(store.publish('second', 2, 'shared', second)['status'], 'conflict')
            self.assertEqual(store.inspect(), before)

    def test_weak_missing_receipt_retry_commits_original_epoch_below_fence(self):
        store = self.store('retry_missing')
        result, attempts = self.race(store, first=b'old', second=b'winner', later=True)
        observed = store.inspect()
        self.assertEqual((result['status'], result['revision']), ('committed', 6))
        self.assertEqual(observed['state'].content, b'old')
        self.assertEqual(observed['commits'][-1]['epoch'], 2)
        self.assertEqual(observed['commits'][-1]['active_epoch'], 3)
        self.assertEqual([r['epoch'] for r in observed['receipts']], [2, 3])
        self.assertEqual(attempts[0]['status'], 'retired')

    def test_fenced_missing_receipt_refuses_without_inventing_an_original_reply(self):
        store = self.store()
        result, _ = self.race(store, later=True)
        self.assertEqual(result, {'status': 'outcome_unavailable', 'epoch': 2, 'request_id': 'shared',
                                  'revision': None, 'approved_sha256': None})
        observed = store.inspect()
        self.assertEqual(observed['state'].content, b'D')
        self.assertEqual([c['caller'] for c in observed['commits']], ['second', 'later'])
        self.assertEqual([r['epoch'] for r in observed['receipts']], [3])

    def test_guarded_resolution_defers_retirement_then_replays_original(self):
        store = self.store('guarded_resolution')
        result, attempts = self.race(store, later=True)
        self.assertEqual((result['status'], result['revision']), ('replayed', 4))
        self.assertEqual([r['status'] for r in attempts], ['busy', 'retired'])
        self.assertEqual(attempts[0]['sqlite_errorcode'], 5)
        self.assertEqual(attempts[0]['busy_timeout_ms'], 0)
        self.assertEqual(store.inspect()['state'].content, b'D')
        self.assertEqual(store.inspect()['active_epoch'], 3)

    def test_retirement_winning_before_guard_acquisition_returns_unavailable(self):
        store = self.store('guarded_resolution')
        def retire_first(kind, **fields):
            if kind == 'duplicate_receipt':
                self.assertEqual(store.try_retire(3)['status'], 'retired')
        result, attempts = self.race(store, retire=False, event=retire_first)
        self.assertEqual(result['status'], 'outcome_unavailable')
        self.assertFalse(attempts)
        self.assertEqual(len(store.inspect()['commits']), 1)
        self.assertFalse(store.inspect()['receipts'])

    def test_guarded_changed_parameters_conflict_before_closure(self):
        store = self.store('guarded_resolution')
        result, _ = self.race(store, first=None, second=b'')
        self.assertEqual((result['status'], result['revision']), ('conflict', None))
        self.assertEqual(len(store.inspect()['commits']), 1)

    def test_all_collision_paths_record_numeric_error_and_whole_rollback(self):
        for mode in MODES:
            store = self.store(mode)
            events = []
            self.race(store, event=lambda kind, **fields: events.append((kind, fields)))
            collision = next(v for k, v in events if k == 'duplicate_receipt')
            self.assertEqual(collision, {'at': 'receipt_insert', 'sqlite_errorcode': 1555,
                                         'sqlite_errorname': 'SQLITE_CONSTRAINT_PRIMARYKEY', 'transaction_rolled_back': True})
            self.assertEqual(len([c for c in store.inspect()['commits'] if c['caller'] == 'first']), 1 if mode == 'retry_missing' else 0)

    def test_missing_current_epoch_evidence_is_not_fabricated_success(self):
        for mode in MODES[1:]:
            store = self.store(mode)
            def remove(kind, **fields):
                if kind == 'duplicate_receipt':
                    with sqlite3.connect(store.database) as connection:
                        connection.execute('DELETE FROM requests WHERE epoch=2')
            result, _ = self.race(store, retire=False, event=remove)
            self.assertEqual(result['status'], 'storage_error')
            self.assertIsNone(result['revision'])
            self.assertEqual(len(store.inspect()['commits']), 1)

    def test_other_receipt_constraint_is_not_a_modeled_collision(self):
        store = self.store()
        before = store.inspect()
        events = []
        with sqlite3.connect(store.database) as connection:
            connection.execute("CREATE TRIGGER reject_receipt BEFORE INSERT ON requests BEGIN SELECT RAISE(ABORT, 'receipt'); END")
        with self.assertRaises(sqlite3.IntegrityError) as caught:
            store.publish('first', 2, 'new', b'B', event=lambda kind, **fields: events.append(kind))
        self.assertEqual(caught.exception.sqlite_errorcode, sqlite3.SQLITE_CONSTRAINT_TRIGGER)
        self.assertNotIn('duplicate_receipt', events)
        self.assertEqual(store.inspect(), before)

    def test_primary_key_error_from_effect_insert_is_not_a_receipt_collision(self):
        store = self.store()
        before = store.inspect()
        events = []
        with sqlite3.connect(store.database) as connection:
            connection.execute('CREATE TRIGGER repeat_effect BEFORE INSERT ON effects BEGIN INSERT INTO effects '
                               'VALUES (NEW.revision, NEW.epoch, NEW.request_id, NEW.operation, NEW.approved_sha256); END')
        with self.assertRaises(sqlite3.IntegrityError) as caught:
            store.publish('first', 2, 'new', b'B', event=lambda kind, **fields: events.append(kind))
        self.assertEqual(caught.exception.sqlite_errorcode, sqlite3.SQLITE_CONSTRAINT_PRIMARYKEY)
        self.assertNotIn('duplicate_receipt', events)
        self.assertEqual(store.inspect(), before)

    def test_observer_failure_rolls_back_effect_receipt_and_publication(self):
        store = self.store()
        before = store.inspect()
        with sqlite3.connect(store.database) as connection:
            connection.execute("CREATE TRIGGER fail_observer BEFORE INSERT ON resolution_commits BEGIN SELECT RAISE(ABORT, 'observer'); END")
        with self.assertRaises(sqlite3.IntegrityError):
            store.publish('first', 2, 'new', b'B')
        self.assertEqual(store.inspect(), before)

    def test_failure_before_commit_rolls_back_all_new_rows(self):
        store = self.store()
        before = store.inspect()
        def fail(stage):
            if stage == 'before_commit':
                raise RuntimeError('injected')
        with self.assertRaises(RuntimeError):
            store.publish('first', 2, 'new', b'B', checkpoint=fail)
        self.assertEqual(store.inspect(), before)
        self.assertEqual(store.try_retire(3)['status'], 'retired')

    def test_resolution_callback_failure_releases_the_guard(self):
        store = self.store('guarded_resolution')
        def fail(stage):
            if stage == 'after_precheck':
                store.publish('second', 2, 'shared', b'B')
            elif stage == 'before_resolution':
                raise RuntimeError('injected guard failure')
        with self.assertRaises(RuntimeError):
            store.publish('first', 2, 'shared', b'B', checkpoint=fail)
        self.assertEqual([c['caller'] for c in store.inspect()['commits']], ['second'])
        self.assertEqual(store.try_retire(3)['status'], 'retired')

    def test_postcommit_failure_can_be_retried_without_another_effect(self):
        store = self.store()
        def fail(stage):
            if stage == 'after_commit':
                raise RuntimeError('lost response')
        with self.assertRaises(RuntimeError):
            store.publish('first', 2, 'new', b'B', checkpoint=fail)
        self.assertEqual(store.publish('second', 2, 'new', b'B')['status'], 'replayed')
        self.assertEqual(len(store.inspect()['commits']), 1)

    def test_unknown_begin_error_is_not_busy(self):
        store = self.store()
        error = sqlite3.OperationalError('injected locked failure')
        error.sqlite_errorcode, error.sqlite_errorname = 6, 'SQLITE_LOCKED'
        connection = Mock()
        connection.execute.side_effect = error
        with patch.object(store, '_probe_connection', return_value=connection):
            with self.assertRaises(sqlite3.OperationalError):
                store.publish('first', 2, 'new', b'B')
        connection.close.assert_called_once()

    def test_real_writer_contention_has_no_effect_and_retry_preserves_identity(self):
        store = self.store()
        connection = store._connect()
        try:
            connection.execute('BEGIN IMMEDIATE')
            before = store.inspect()
            self.assertEqual(store.publish('first', 2, 'new', b'B')['status'], 'busy')
            self.assertEqual(store.inspect(), before)
        finally:
            connection.close()
        self.assertEqual(store.publish('first', 2, 'new', b'B')['status'], 'committed')
        self.assertEqual(store.publish('first', 2, 'new', b'B')['status'], 'replayed')

    def test_wal_configuration_is_rejected(self):
        store = self.store()
        with sqlite3.connect(store.database) as connection:
            connection.execute('PRAGMA journal_mode=WAL')
        with self.assertRaises(ValueError):
            store.publish('first', 2, 'new', b'B')

    def test_initial_old_epoch_request_is_not_reexecuted_even_in_weak_mode(self):
        for mode in MODES:
            store = self.store(mode)
            store.try_retire(3)
            before = store.inspect()
            self.assertEqual(store.publish('first', 2, 'old', b'B')['status'], 'outcome_unavailable')
            self.assertEqual(store.inspect(), before)

    def test_future_epoch_is_denied_without_mutation(self):
        store = self.store()
        before = store.inspect()
        self.assertEqual(store.publish('first', 3, 'future', b'B')['status'], 'future_epoch')
        self.assertEqual(store.inspect(), before)

    def test_retirement_write_failure_is_not_reported_as_busy_or_success(self):
        store = self.store()
        before = store.inspect()
        with sqlite3.connect(store.database) as connection:
            connection.execute("CREATE TRIGGER fail_retirement BEFORE UPDATE ON namespace BEGIN SELECT RAISE(ABORT, 'retirement'); END")
        with self.assertRaises(sqlite3.IntegrityError):
            store.try_retire(3)
        self.assertEqual(store.inspect(), before)

    def test_worker_rejects_resume_for_another_caller(self):
        store = self.store()
        command = [sys.executable, str(ROOT / 'experiments/resolution_worker.py'), '--root', str(store.root),
                   '--mode', store.mode, '--role', 'caller', '--caller', 'first', '--pauses', 'both']
        child = subprocess.run(command, input=json.dumps({'command': 'resume', 'stage': 'after_precheck', 'caller': 'second'}) + '\n',
                               capture_output=True, text=True, timeout=10)
        self.assertNotEqual(child.returncode, 0)
        self.assertIn('caller-bound resume', child.stderr)
        self.assertFalse(store.inspect()['commits'])


class ResolutionEvidenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dataset = ROOT / 'experiments/tasks/resolution-eval-v1/tasks.json'
        cls.cases = load_cases(cls.dataset)
        cls.rows = [run_case(c, mode) for c in cls.cases for mode in MODES]
        for row in cls.rows:
            if row['status'] != 'complete':
                raise AssertionError((row['case_id'], row['mode'], row['error_detail']))

    def sample(self, case='retire_gap_later-same_ascii', mode='fenced_resolution'):
        return copy.deepcopy(next(r for r in self.rows if r['case_id'] == case and r['mode'] == mode))

    @staticmethod
    def rewrite_reply(row, **fields):
        record = row['callers'][0]
        record['response'].update(fields)
        next(e for e in record['events'] if e['kind'] == 'caller_result')['response'] = record['response']
        record['stdout'] = ''.join(json.dumps(e) + '\n' for e in record['events'])
        for e in row['timeline']:
            if e['kind'] == 'caller_completed' and e['caller'] == 'first':
                e['status'] = record['response']['status']

    def test_full_grid_matches_independent_reconstruction_and_ten_criteria(self):
        for row in self.rows:
            with self.subTest(case=row['case_id'], mode=row['mode']):
                self.assertEqual(evaluate(row), row['oracle'])
        actual = summarize(self.rows, self.cases)
        self.assertEqual(actual, recount(self.rows, load_manifest(self.dataset)))
        self.assertTrue(all(actual['criteria'].values()))

    def test_unavailable_is_safe_but_not_an_original_historical_outcome(self):
        row = self.sample()
        self.assertTrue(row['oracle']['safe_gap_resolution'])
        self.assertTrue(row['oracle']['unavailable_gap'])
        self.assertFalse(row['oracle']['original_gap_resolution'])
        self.assertTrue(row['oracle']['one_shared_effect'])

    def test_guard_orders_response_before_retirement_and_later_publication(self):
        row = self.sample(mode='guarded_resolution')
        self.assertEqual([r['response']['status'] for r in row['retirements']], ['busy', 'retired'])
        self.assertEqual(row['resolution_capture']['active_epoch'], 2)
        self.assertEqual(row['after_first']['state']['revision'], 4)
        self.assertEqual(row['later_capture']['state']['revision'], 5)
        self.assertEqual(row['callers'][0]['response']['revision'], 4)

    def test_weak_extra_effect_remains_complete_and_coherent_but_unsafe(self):
        row = self.sample(mode='retry_missing')
        self.assertTrue(row['oracle']['coherent_final'])
        self.assertTrue(row['oracle']['extra_gap_effect'])
        self.assertTrue(row['oracle']['invalid_old_commit'])
        self.assertFalse(row['oracle']['safe_gap_resolution'])
        self.assertFalse(row['oracle']['later_state_preserved'])

    def test_matching_historical_fields_without_receipt_are_not_justified_success(self):
        row = self.sample()
        winner = row['winner_capture']['commits'][0]
        self.rewrite_reply(row, status='replayed', revision=4, approved_sha256=winner['approved_sha256'])
        actual = assess(row)
        self.assertFalse(actual['safe_gap_resolution'])
        self.assertFalse(actual['original_gap_resolution'])
        self.assertEqual(evaluate(row), actual)

    def test_missing_receipt_cannot_justify_a_parameter_conflict(self):
        row = self.sample('retire_gap-changed_bytes')
        self.rewrite_reply(row, status='conflict')
        self.assertFalse(assess(row)['safe_gap_resolution'])
        self.assertFalse(assess(row)['original_gap_resolution'])
        self.assertEqual(evaluate(row), assess(row))

    def test_wrong_revision_with_available_receipt_is_a_negative_outcome(self):
        row = self.sample(mode='guarded_resolution')
        self.rewrite_reply(row, revision=5)
        self.assertFalse(assess(row)['safe_gap_resolution'])
        self.assertEqual(evaluate(row), assess(row))

    def test_unavailable_response_must_not_include_commitment_fields(self):
        row = self.sample()
        self.rewrite_reply(row, revision=4)
        self.assertFalse(assess(row)['unavailable_gap'])
        self.assertFalse(assess(row)['safe_gap_resolution'])
        self.assertEqual(evaluate(row), assess(row))

    def test_forged_commit_epoch_cannot_hide_a_below_fence_write(self):
        row = self.sample('retire_gap-same_ascii', 'retry_missing')
        row['final']['commits'][-1]['active_epoch'] = 2
        for oracle in (assess, evaluate):
            with self.assertRaises(ValueError):
                oracle(row)

    def test_missing_barrier_trace_is_rejected(self):
        row = self.sample()
        row['callers'][0]['events'].pop(2)
        for oracle in (assess, evaluate):
            with self.assertRaises(ValueError):
                oracle(row)

    def test_changed_retirement_target_is_rejected(self):
        row = self.sample()
        row['retirements'][0]['command'][-1] = '2'
        for oracle in (assess, evaluate):
            with self.assertRaises(ValueError):
                oracle(row)

    def test_capture_cannot_rewrite_an_earlier_committed_prefix(self):
        row = self.sample()
        row['after_first'] = copy.deepcopy(row['initial'])
        for oracle in (assess, evaluate):
            with self.assertRaises(ValueError):
                oracle(row)

    def test_an_entire_failed_mode_stays_visible_in_error_counts(self):
        rows = copy.deepcopy(self.rows)
        for row in rows:
            if row['mode'] == 'retry_missing':
                row.update(status='infrastructure_error', oracle=None, error_type='InjectedFailure')
        actual = summarize(rows, self.cases)
        self.assertEqual(actual, recount(rows, self.cases))
        self.assertEqual(actual['arms']['retry_missing']['infrastructure_errors'], 16)
        self.assertFalse(all(actual['criteria'].values()))

    def test_missing_repeated_grid_record_and_forged_oracle_are_rejected(self):
        changed = copy.deepcopy(self.rows)
        changed[0]['oracle']['safe_gap_resolution'] = True
        for records in (self.rows[:-1], self.rows + [self.rows[0]], changed):
            for counter in (summarize, recount):
                with self.assertRaises(ValueError):
                    counter(records, self.cases)

    def test_semantic_manifest_duplicate_is_rejected_despite_a_new_name(self):
        data = json.loads(self.dataset.read_text())
        data['cases'][1] = {**data['cases'][0], 'case_id': 'fresh-id'}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'manifest.json'
            path.write_text(json.dumps(data))
            for loader in (load_cases, load_manifest):
                with self.assertRaises(ValueError):
                    loader(path)

    def test_independent_verifier_does_not_import_measured_modules(self):
        tree = ast.parse((ROOT / 'experiments/verify_resolution_results.py').read_text())
        names = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names.extend(v.name for v in node.names)
            elif isinstance(node, ast.ImportFrom):
                names.append(node.module or '')
        self.assertFalse(any(n.startswith(('src', 'experiments')) for n in names))


if __name__ == '__main__':
    unittest.main()
