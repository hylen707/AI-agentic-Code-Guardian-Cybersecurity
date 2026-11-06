import ast
import copy
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from experiments.run_compaction_comparison import ROOT, assess, load_cases, run_case, summarize
from experiments.verify_compaction_results import evaluate, load_manifest, recount
from src.compaction_store import MODES, CompactionPublicationStore
from src.publication_store import digest


class CompactionStoreTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory(prefix='codeguardian-compaction-test-')
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.number = 0

    def store(self, mode='atomic_summary', value=b'B'):
        self.number += 1
        store = CompactionPublicationStore(self.root / str(self.number), mode)
        store.initialize(b'approved=version-a\n')
        store.publish(1, 'original', value)
        store.publish(1, 'later-policy', b'C' if value is None else None)
        return store

    @staticmethod
    def fail_at(target):
        def fail(stage):
            if stage == target:
                raise RuntimeError('injected at '+stage)
        return fail

    def test_invalid_mode_epoch_id_payload_and_skipped_target_are_rejected(self):
        with self.assertRaises(ValueError):
            CompactionPublicationStore(self.root, 'unknown')
        store = self.store()
        before = store.inspect()
        for args in ((True, 'new', b'B'), (1, '../bad', b'B'), (1, 'new', 'text')):
            with self.subTest(args=args), self.assertRaises(ValueError):
                store.publish(*args)
        for target in (True, 0, 3):
            with self.subTest(target=target), self.assertRaises(ValueError):
                store.compact_to(target)
        self.assertEqual(store.inspect(), before)

    def test_compact_summary_replays_original_without_restoring_later_policy(self):
        for value in (b'B', b'', '안전 ✓'.encode(), None):
            store = self.store(value=value)
            before = store.snapshot()
            store.compact_to(2)
            result = store.publish(1, 'original', value)
            self.assertEqual(result, {'status': 'replayed', 'epoch': 1, 'request_id': 'original',
                                      'revision': 2, 'approved_sha256': None if value is None else digest(value)})
            self.assertEqual(store.snapshot(), before)
            self.assertEqual(len(store.inspect()['effects']), 2)

    def test_typed_fingerprints_separate_empty_update_and_revocation(self):
        for a, b in ((b'', None), (None, b'')):
            store = self.store(value=a)
            store.compact_to(2)
            original = next(r for r in store.inspect()['summaries'] if r['request_id'] == 'original')
            self.assertEqual(original['operation'], 'revoke' if a is None else 'update')
            self.assertEqual(original['payload_sha256'], None if a is None else digest(a))
            self.assertEqual(store.publish(1, 'original', b)['status'], 'conflict')

    def test_unicode_normalization_does_not_change_intent_comparison(self):
        store = self.store(value='é'.encode())
        store.compact_to(2)
        before = store.inspect()
        self.assertEqual(store.publish(1, 'original', 'e\u0301'.encode())['status'], 'conflict')
        self.assertEqual(store.inspect(), before)

    def test_completed_summary_has_no_payload_column_or_old_payload_rows(self):
        store = self.store(value=b'X'*65536)
        self.assertGreater(sum(len(r['payload'] or b'') for r in store.inspect()['receipts']), 0)
        store.compact_to(2)
        observed = store.inspect()
        self.assertFalse(observed['receipts'])
        self.assertEqual(observed['summary_columns'], ['epoch', 'request_id', 'operation', 'payload_sha256', 'revision'])
        self.assertEqual(len(observed['summaries']), 2)
        for row in observed['summaries']:
            self.assertEqual(len(row['payload_sha256']), 64) if row['operation'] == 'update' else self.assertIsNone(row['payload_sha256'])

    def test_receipt_payload_removal_does_not_erase_current_publication_bytes(self):
        store = self.store(value=b'old request bytes')
        store.compact_to(2)
        self.assertFalse(store.inspect()['receipts'])
        self.assertEqual(store.snapshot().content, b'old request bytes')
        self.assertIsNone(store.snapshot().approved_sha256)

    def test_retaining_full_receipts_keeps_exact_byte_authority(self):
        store = self.store('retain_full')
        store.compact_to(2)
        self.assertEqual(len(store.inspect()['receipts']), 2)
        self.assertFalse(store.inspect()['summaries'])
        self.assertEqual(store.publish(1, 'original', b'B')['status'], 'replayed')
        self.assertEqual(store.publish(1, 'original', b'C')['status'], 'conflict')

    def test_dropping_receipts_preserves_fence_but_loses_original_answer(self):
        store = self.store('drop_receipts')
        store.compact_to(2)
        before = store.inspect()
        self.assertEqual(store.publish(1, 'original', b'B')['status'], 'outcome_unavailable')
        self.assertEqual(store.publish(1, 'original', b'C')['status'], 'outcome_unavailable')
        self.assertEqual(store.inspect(), before)

    def test_atomic_precommit_failures_restore_old_fence_and_full_receipts(self):
        for stage in ('before_change', 'after_fence_cleanup', 'after_summary'):
            store = self.store()
            before = store.inspect()
            with self.subTest(stage=stage), self.assertRaises(RuntimeError):
                store.compact_to(2, checkpoint=self.fail_at(stage))
            self.assertEqual(store.inspect(), before)
            self.assertEqual(store.publish(1, 'original', b'B')['status'], 'replayed')

    def test_split_gap_cannot_be_repaired_by_retrying_completed_target(self):
        for stage in ('after_fence_cleanup', 'after_summary'):
            store = self.store('split_summary')
            with self.assertRaises(RuntimeError):
                store.compact_to(2, checkpoint=self.fail_at(stage))
            observed = store.inspect()
            self.assertEqual(observed['active_epoch'], 2)
            self.assertFalse(observed['receipts'])
            self.assertFalse(observed['summaries'])
            self.assertEqual(len(observed['effects']), 2)
            self.assertEqual(store.compact_to(2)['status'], 'already_compacted')
            self.assertEqual(store.publish(1, 'original', b'B')['status'], 'outcome_unavailable')
            self.assertEqual(store.inspect(), observed)

    def test_postcommit_exception_keeps_compact_original_for_retry(self):
        store = self.store()
        with self.assertRaises(RuntimeError):
            store.compact_to(2, checkpoint=self.fail_at('after_commit'))
        self.assertEqual(store.inspect()['active_epoch'], 2)
        self.assertFalse(store.inspect()['receipts'])
        self.assertEqual(store.publish(1, 'original', b'B')['revision'], 2)

    def test_summary_insert_failure_is_not_a_successful_migration(self):
        for mode in ('split_summary', 'atomic_summary'):
            store = self.store(mode)
            with sqlite3.connect(store.database) as connection:
                connection.execute("CREATE TRIGGER reject_summary BEFORE INSERT ON summaries BEGIN SELECT RAISE(ABORT, 'summary'); END")
            with self.assertRaises(sqlite3.IntegrityError):
                store.compact_to(2)
            observed = store.inspect()
            self.assertFalse(observed['summaries'])
            self.assertEqual(observed['active_epoch'], 2 if mode == 'split_summary' else 1)
            self.assertEqual(len(observed['receipts']), 0 if mode == 'split_summary' else 2)

    def test_namespace_write_failure_rolls_back_cleanup(self):
        store = self.store()
        before = store.inspect()
        with sqlite3.connect(store.database) as connection:
            connection.execute("CREATE TRIGGER fail_namespace BEFORE UPDATE ON namespace BEGIN SELECT RAISE(ABORT, 'epoch'); END")
        with self.assertRaises(sqlite3.IntegrityError):
            store.compact_to(2)
        self.assertEqual(store.inspect(), before)

    def test_new_epoch_reuses_literal_id_and_retries_without_an_extra_effect(self):
        for mode in MODES:
            store = self.store(mode)
            store.compact_to(2)
            result = store.publish(2, 'original', b'D')
            self.assertEqual((result['status'], result['revision']), ('committed', 4))
            self.assertEqual(store.publish(2, 'original', b'D'), {**result, 'status': 'replayed'})
            self.assertEqual(len(store.inspect()['effects']), 3)

    def test_unseen_closed_epoch_and_future_epoch_are_refused_without_effect(self):
        store = self.store()
        store.compact_to(2)
        before = store.inspect()
        self.assertEqual(store.publish(1, 'unseen', b'B')['status'], 'outcome_unavailable')
        self.assertEqual(store.publish(3, 'future', b'B')['status'], 'future_epoch')
        self.assertEqual(store.inspect(), before)

    def test_second_compaction_preserves_older_summaries_and_composite_ids(self):
        store = self.store()
        store.compact_to(2)
        store.publish(2, 'original', b'D')
        store.compact_to(3)
        self.assertEqual(len(store.inspect()['summaries']), 3)
        self.assertEqual(store.publish(1, 'original', b'B')['revision'], 2)
        self.assertEqual(store.publish(2, 'original', b'D')['revision'], 4)
        self.assertFalse(store.inspect()['receipts'])

    def test_new_publication_failure_cannot_leave_an_effect_without_its_receipt(self):
        store = self.store()
        store.compact_to(2)
        before = store.inspect()
        with sqlite3.connect(store.database) as connection:
            connection.execute("CREATE TRIGGER reject_request BEFORE INSERT ON requests BEGIN SELECT RAISE(ABORT, 'receipt'); END")
        with self.assertRaises(sqlite3.IntegrityError):
            store.publish(2, 'new', b'D')
        self.assertEqual(store.inspect(), before)

    def test_ambiguous_full_and_compact_authority_is_not_silently_accepted(self):
        store = self.store()
        with sqlite3.connect(store.database) as connection:
            connection.execute('INSERT INTO summaries VALUES (1,?,?,?,2)', ('original', 'update', digest(b'B')))
        with self.assertRaises(ValueError):
            store.publish(1, 'original', b'B')

    def test_deliberately_colliding_fingerprint_exposes_the_comparison_assumption(self):
        store = self.store()
        store.compact_to(2)
        # A substituted comparison digest models a collision; this is not an
        # actual SHA-256 collision or a case in the measurement manifest.
        with patch('src.compaction_store.intent_fingerprint', return_value=digest(b'B')):
            self.assertEqual(store.publish(1, 'original', b'different')['status'], 'replayed')
        full = self.store('retain_full')
        full.compact_to(2)
        with patch('src.compaction_store.intent_fingerprint', return_value=digest(b'B')):
            self.assertEqual(full.publish(1, 'original', b'different')['status'], 'conflict')


class CompactionEvidenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dataset = ROOT/'experiments/tasks/compaction-eval-v1/tasks.json'
        cls.cases = load_cases(cls.dataset)
        cls.rows = [run_case(c, m) for c in cls.cases for m in MODES]
        for row in cls.rows:
            if row['status'] != 'complete':
                raise AssertionError((row['case_id'], row['mode'], row['error_detail']))

    def sample(self, name='normal-ascii', mode='atomic_summary'):
        return copy.deepcopy(next(r for r in self.rows if r['case_id'] == name and r['mode'] == mode))

    def test_entire_grid_matches_independent_reconstruction_and_ten_criteria(self):
        for row in self.rows:
            with self.subTest(case=row['case_id'], mode=row['mode']):
                self.assertEqual(evaluate(row), row['oracle'])
        actual = summarize(self.rows, self.cases)
        self.assertEqual(actual, recount(self.rows, load_manifest(self.dataset)))
        self.assertTrue(all(actual['criteria'].values()))

    def test_equal_replay_totals_hide_different_loss_windows(self):
        summary = summarize(self.rows, self.cases)['arms']
        self.assertEqual(summary['drop_receipts']['repeat_supported'], 12)
        self.assertEqual(summary['split_summary']['repeat_supported'], 12)
        self.assertEqual(summary['drop_receipts']['gap_supported'], 8)
        self.assertEqual(summary['split_summary']['gap_supported'], 0)

    def test_split_gap_preserves_current_policy_while_losing_original_reply(self):
        row = self.sample('after_summary-ascii', 'split_summary')
        self.assertEqual(row['recovered']['active_epoch'], 2)
        self.assertFalse(row['recovered']['receipts'])
        self.assertFalse(row['recovered']['summaries'])
        self.assertTrue(row['oracle']['current_policy_preserved'])
        self.assertTrue(row['oracle']['known_no_extra'])
        self.assertFalse(row['oracle']['repeat_supported'])

    def test_wrong_exit_code_missing_marker_and_stderr_are_not_valid_faults(self):
        for mutation in ('code', 'marker', 'stderr'):
            row = self.sample('after_summary-ascii')
            if mutation == 'code':
                row['child']['returncode'] = 74
            elif mutation == 'marker':
                row['child']['events'].pop()
            else:
                row['child']['stderr'] = 'unexpected failure'
            for oracle in (assess, evaluate):
                with self.assertRaises(ValueError):
                    oracle(row)

    def test_matching_historical_guess_without_authority_is_not_supported(self):
        row = self.sample(mode='drop_receipts')
        row['followup_response'].update(status='replayed', revision=2, approved_sha256=digest(b'approved=version-b\n'))
        actual = assess(row)
        self.assertFalse(actual['repeat_supported'])
        self.assertEqual(actual['false_history'], 1)
        self.assertEqual(actual, evaluate(row))

    def test_wrong_historical_revision_is_a_negative_business_result(self):
        row = self.sample()
        row['followup_response']['revision'] = 3
        self.assertFalse(assess(row)['repeat_supported'])
        self.assertEqual(assess(row), evaluate(row))

    def test_unavailable_result_must_not_contain_a_commitment(self):
        row = self.sample(mode='drop_receipts')
        row['followup_response']['revision'] = 2
        self.assertFalse(assess(row)['unavailable_known'])
        self.assertEqual(assess(row), evaluate(row))

    def test_compact_fingerprint_cannot_be_forged_to_another_value(self):
        row = self.sample()
        row['recovered']['summaries'][0]['payload_sha256'] = '0'*64
        for oracle in (assess, evaluate):
            with self.assertRaises(ValueError):
                oracle(row)

    def test_followup_cannot_rewrite_historical_authority_without_migration(self):
        row = self.sample()
        row['final']['summaries'].pop()
        for oracle in (assess, evaluate):
            with self.assertRaises(ValueError):
                oracle(row)

    def test_valid_but_unexpected_loss_layout_is_a_failed_criterion(self):
        row = self.sample()
        row['recovered']['summaries'] = []
        row['final']['summaries'] = []
        row['followup_response'].update(status='outcome_unavailable', revision=None, approved_sha256=None)
        actual = assess(row)
        self.assertFalse(actual['layout_matches'])
        self.assertFalse(actual['repeat_supported'])
        self.assertTrue(actual['unavailable_known'])
        self.assertEqual(actual, evaluate(row))

    def test_an_entire_failed_mode_stays_visible_with_zero_observed_counters(self):
        rows = copy.deepcopy(self.rows)
        for row in rows:
            if row['mode'] == 'atomic_summary':
                row.update(status='infrastructure_error', oracle=None)
        actual = summarize(rows, self.cases)
        self.assertEqual(actual, recount(rows, self.cases))
        self.assertEqual(actual['arms']['atomic_summary']['infrastructure_errors'], 26)
        self.assertFalse(all(actual['criteria'].values()))

    def test_grid_repeats_omissions_and_forged_verdicts_are_rejected(self):
        forged = copy.deepcopy(self.rows)
        forged[0]['oracle']['repeat_supported'] = False
        for rows in (self.rows[:-1], self.rows+[self.rows[0]], forged):
            for counter in (summarize, recount):
                with self.assertRaises(ValueError):
                    counter(rows, self.cases)

    def test_semantic_manifest_repeat_with_new_id_is_rejected(self):
        data = json.loads(self.dataset.read_text())
        data['cases'][1] = {**data['cases'][0], 'case_id': 'new-name'}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'manifest.json'
            path.write_text(json.dumps(data))
            for loader in (load_cases, load_manifest):
                with self.assertRaises(ValueError):
                    loader(path)

    def test_independent_verifier_imports_no_measured_modules(self):
        tree = ast.parse((ROOT/'experiments/verify_compaction_results.py').read_text())
        names = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names.extend(n.name for n in node.names)
            elif isinstance(node, ast.ImportFrom):
                names.append(node.module or '')
        self.assertFalse(any(n.startswith(('src', 'experiments')) for n in names))


if __name__ == '__main__':
    unittest.main()
