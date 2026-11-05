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

from experiments.run_caller_comparison import (
    ROOT, assess, load_cases, run_case, summarize,
)
from experiments.verify_caller_results import evaluate, manifest, recount
from src.caller_store import MODES, CallerPublicationStore
from src.publication_store import digest, recover_value


class CallerStoreTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory(prefix="codeguardian-caller-test-")
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.number = 0

    def store(self, mode="resolve_duplicate"):
        self.number += 1
        store = CallerPublicationStore(self.root / str(self.number), mode)
        store.initialize(b"approved=version-a\n")
        store.publish_request(1, "seed-a", b"approved=version-b\n")
        store.publish_request(1, "seed-b", None)
        store.retire(2)
        return store

    def race(self, store, first=b"B", second=b"B", later=False, event=lambda *a, **k: None):
        def rival(stage):
            if stage == "after_lookup":
                other = CallerPublicationStore(store.root, store.mode)
                self.assertEqual(other.publish_once("second", 2, "shared", second)["status"], "committed")
                if later:
                    other.publish_once("later", 2, "later", b"D")
        return store.publish_once("first", 2, "shared", first, checkpoint=rival, event=event)

    def test_unknown_mode_caller_epoch_key_and_payload_are_rejected(self):
        with self.assertRaises(ValueError):
            CallerPublicationStore(self.root, "unknown")
        store = self.store()
        before = store.inspect()
        for args in (("unknown", 2, "key", b"B"), ("first", True, "key", b"B"),
                     ("first", 2, "../bad", b"B"), ("first", 2, "key", "text")):
            with self.subTest(args=args), self.assertRaises(ValueError):
                store.publish_once(*args)
        self.assertEqual(store.inspect(), before)

    def test_empty_unicode_and_revocation_commit_atomically(self):
        for value in (b"", "안전 ✓".encode(), None):
            store = self.store()
            result = store.publish_once("first", 2, "new", value)
            observed = store.inspect()
            self.assertEqual(result["revision"], 4)
            self.assertEqual(observed["call_commits"][0]["caller"], "first")
            self.assertEqual(observed["effects"][-1]["revision"], 4)
            self.assertEqual(observed["receipts"][0]["payload"], value)
            self.assertEqual(recover_value(observed["state"])["content"], value)

    def test_serial_retry_returns_original_result_after_later_publication(self):
        for mode in MODES:
            store = self.store(mode)
            original = store.publish_once("first", 2, "same", b"B")
            store.publish_once("later", 2, "later", b"D")
            before = store.inspect()
            replay = store.publish_once("second", 2, "same", b"B")
            self.assertEqual(replay, {**original, "status": "replayed"})
            self.assertEqual(store.inspect(), before)

    def test_operation_change_and_unicode_normalization_are_conflicts(self):
        for a, b in ((b"", None), (None, b""), ("é".encode(), "e\u0301".encode())):
            store = self.store()
            store.publish_once("first", 2, "same", a)
            before = store.inspect()
            self.assertEqual(store.publish_once("second", 2, "same", b)["status"], "conflict")
            self.assertEqual(store.inspect(), before)

    def test_closed_and_future_epoch_do_not_mutate(self):
        for mode in MODES:
            store = self.store(mode)
            before = store.inspect()
            for epoch, status in ((1, "epoch_retired"), (3, "future_epoch")):
                self.assertEqual(store.publish_once("first", epoch, "new", b"B")["status"], status)
            self.assertEqual(store.inspect(), before)

    def test_duplicate_rolls_back_update_effect_and_actor_in_all_precheck_modes(self):
        for mode in MODES[:3]:
            store = self.store(mode)
            self.race(store, b"loser", b"winner", later=True)
            observed = store.inspect()
            self.assertEqual(observed["state"].content, b"D")
            self.assertEqual(observed["state"].revision, 5)
            self.assertEqual([c["caller"] for c in observed["call_commits"]], ["second", "later"])
            self.assertEqual(len(observed["effects"]), 4)
            self.assertEqual(len(observed["receipts"]), 2)

    def test_recognized_collision_preserves_numeric_error_and_full_rollback_marker(self):
        store = self.store("precheck_insert")
        events = []
        result = self.race(store, event=lambda kind, **fields: events.append((kind, fields)))
        self.assertEqual(result["status"], "storage_error")
        duplicate = next(fields for kind, fields in events if kind == "duplicate_receipt")
        self.assertEqual(duplicate, {"at": "receipt_insert", "sqlite_errorcode": 1555,
                                    "sqlite_errorname": "SQLITE_CONSTRAINT_PRIMARYKEY", "transaction_rolled_back": True})

    def test_constraint_label_misclassifies_an_identical_rival(self):
        store = self.store("constraint_conflict")
        self.assertEqual(self.race(store)["status"], "conflict")
        self.assertEqual(len(store.inspect()["call_commits"]), 1)

    def test_resolver_compares_exact_rival_operation_and_bytes(self):
        for first, second, status in ((b"", b"", "replayed"), (None, None, "replayed"),
                                      (b"", None, "conflict"), (None, b"", "conflict")):
            store = self.store()
            result = self.race(store, first, second)
            self.assertEqual(result["status"], status)
            self.assertEqual(result["revision"], 4 if status == "replayed" else None)

    def test_resolver_uses_historical_receipt_while_current_state_is_newer(self):
        for value in (b"B", None):
            store = self.store()
            result = self.race(store, value, value, later=True)
            self.assertEqual((result["status"], result["revision"]), ("replayed", 4))
            self.assertEqual(result["approved_sha256"], None if value is None else digest(value))
            self.assertEqual((store.snapshot().revision, store.snapshot().content), (5, b"D"))

    def test_distinct_ids_commit_both_intents_despite_identical_bytes(self):
        for mode in MODES:
            store = self.store(mode)
            for caller, key in (("first", "a"), ("second", "b")):
                self.assertEqual(store.publish_once(caller, 2, key, b"B")["status"], "committed")
            self.assertEqual(len(store.inspect()["call_commits"]), 2)
            self.assertEqual(store.snapshot().revision, 5)

    def test_real_writer_busy_has_no_effect_and_same_identity_can_retry(self):
        store = self.store("transactional_lookup")
        connection = store._connect()
        events = []
        try:
            connection.execute("BEGIN IMMEDIATE")
            before = store.inspect()
            result = store.publish_once("second", 2, "same", b"B", event=lambda kind, **fields: events.append((kind, fields)))
            self.assertEqual(result["status"], "busy")
            self.assertEqual(store.inspect(), before)
            self.assertEqual(events[0][1]["sqlite_errorcode"], 5)
        finally:
            connection.close()
        self.assertEqual(store.publish_once("second", 2, "same", b"B")["status"], "committed")
        self.assertEqual(store.publish_once("second", 2, "same", b"B")["status"], "replayed")
        self.assertEqual(len(store.inspect()["call_commits"]), 1)

    def test_other_begin_error_is_not_busy(self):
        store = self.store("transactional_lookup")
        error = sqlite3.OperationalError("injected locked error")
        error.sqlite_errorcode, error.sqlite_errorname = 6, "SQLITE_LOCKED"
        connection = Mock()
        connection.execute.side_effect = error
        with patch.object(store, "_writer_connection", return_value=connection):
            with self.assertRaises(sqlite3.OperationalError):
                store.publish_once("first", 2, "new", b"B")
        connection.close.assert_called_once()

    def test_other_receipt_constraint_is_not_a_parameter_conflict(self):
        store = self.store("constraint_conflict")
        before = store.inspect()
        with sqlite3.connect(store.database) as connection:
            connection.execute("CREATE TRIGGER fail_receipt BEFORE INSERT ON requests BEGIN SELECT RAISE(ABORT, 'injected'); END")
        with self.assertRaises(sqlite3.IntegrityError) as caught:
            store.publish_once("first", 2, "new", b"B")
        self.assertEqual(caught.exception.sqlite_errorcode, sqlite3.SQLITE_CONSTRAINT_TRIGGER)
        self.assertEqual(store.inspect(), before)

    def test_effect_failure_is_not_reclassified_as_receipt_collision(self):
        store = self.store()
        before = store.inspect()
        with sqlite3.connect(store.database) as connection:
            connection.execute("CREATE TRIGGER fail_effect BEFORE INSERT ON effects BEGIN SELECT RAISE(ABORT, 'effect'); END")
        with self.assertRaises(sqlite3.IntegrityError):
            store.publish_once("first", 2, "new", b"B")
        self.assertEqual(store.inspect(), before)

    def test_actor_observer_failure_rolls_back_publication_and_receipt(self):
        store = self.store()
        before = store.inspect()
        with sqlite3.connect(store.database) as connection:
            connection.execute("CREATE TRIGGER fail_actor BEFORE INSERT ON call_commits BEGIN SELECT RAISE(ABORT, 'actor'); END")
        with self.assertRaises(sqlite3.IntegrityError):
            store.publish_once("first", 2, "new", b"B")
        self.assertEqual(store.inspect(), before)

    def test_callback_failure_before_commit_releases_writer_and_rolls_back(self):
        for mode in MODES:
            store = self.store(mode)
            before = store.inspect()
            def fail(stage):
                if stage == "before_commit":
                    raise RuntimeError("injected")
            with self.assertRaises(RuntimeError):
                store.publish_once("first", 2, "new", b"B", checkpoint=fail)
            self.assertEqual(store.inspect(), before)
            self.assertEqual(store.publish_once("second", 2, "new", b"B")["status"], "committed")

    def test_postcommit_exception_preserves_receipt_for_retry(self):
        store = self.store()
        def fail(stage):
            if stage == "after_commit":
                raise RuntimeError("lost acknowledgment")
        with self.assertRaises(RuntimeError):
            store.publish_once("first", 2, "new", b"B", checkpoint=fail)
        self.assertEqual(store.publish_once("second", 2, "new", b"B")["status"], "replayed")
        self.assertEqual(len(store.inspect()["call_commits"]), 1)

    def test_missing_resolution_receipt_is_never_fabricated_success(self):
        store = self.store()
        def remove(kind, **fields):
            if kind == "duplicate_receipt":
                with sqlite3.connect(store.database) as connection:
                    connection.execute("DELETE FROM requests WHERE epoch=2 AND request_id='shared'")
        result = self.race(store, event=remove)
        self.assertEqual(result["status"], "storage_error")
        self.assertIsNone(result["revision"])
        self.assertEqual(len(store.inspect()["call_commits"]), 1)

    def test_wal_configuration_is_rejected(self):
        store = self.store("transactional_lookup")
        with sqlite3.connect(store.database) as connection:
            connection.execute("PRAGMA journal_mode=WAL")
        with self.assertRaises(ValueError):
            store.publish_once("first", 2, "new", b"B")

    def test_worker_rejects_resume_bound_to_another_caller(self):
        store = self.store()
        command = [sys.executable, str(ROOT / 'experiments/caller_worker.py'), '--root', str(store.root),
                   '--mode', store.mode, '--caller', 'first', '--key', 'new', '--intent', 'b', '--pause', 'after_lookup']
        completed = subprocess.run(command, input=json.dumps({'command': 'resume', 'stage': 'after_lookup', 'caller': 'second'}) + '\n',
                                   capture_output=True, text=True, timeout=10)
        self.assertNotEqual(completed.returncode, 0)
        self.assertIn('caller-bound resume', completed.stderr)
        self.assertFalse(store.inspect()['call_commits'])


class CallerEvidenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dataset = ROOT / 'experiments/tasks/caller-eval-v1/tasks.json'
        cls.cases = load_cases(cls.dataset)
        cls.rows = [run_case(c, mode) for c in cls.cases for mode in MODES]
        for row in cls.rows:
            if row['status'] != 'complete':
                raise AssertionError((row['case_id'], row['mode'], row['error_detail']))

    def sample(self, case='later-same_ascii', mode='resolve_duplicate'):
        return copy.deepcopy(next(r for r in self.rows if r['case_id'] == case and r['mode'] == mode))

    def test_all_declared_histories_have_matching_independent_reconstruction(self):
        for row in self.rows:
            with self.subTest(case=row['case_id'], mode=row['mode']):
                self.assertEqual(evaluate(row), row['oracle'])
        summary = summarize(self.rows, self.cases)
        self.assertEqual(recount(self.rows, manifest(self.dataset)), summary)
        self.assertTrue(all(summary['criteria'].values()))

    def test_winner_is_actual_committer_not_first_started(self):
        for mode, caller in (('resolve_duplicate', 'second'), ('transactional_lookup', 'first')):
            row = self.sample(mode=mode)
            self.assertEqual(row['final']['call_commits'][0]['caller'], caller)
            self.assertTrue(row['oracle']['pair_correct'])

    def test_known_negative_outcomes_remain_complete_with_one_effect(self):
        for mode, status in (('precheck_insert', 'storage_error'), ('constraint_conflict', 'conflict')):
            row = self.sample(mode=mode)
            self.assertEqual(row['logical_results']['first']['status'], status)
            self.assertTrue(row['oracle']['one_shared_effect'])
            self.assertFalse(row['oracle']['pair_correct'])
            self.assertEqual(evaluate(row), row['oracle'])

    @staticmethod
    def rewrite_reply(row, caller, **changes):
        attempt = [a for a in row['attempts'] if a['caller'] == caller][-1]
        attempt['response'].update(changes)
        next(e for e in attempt['events'] if e['kind'] == 'result')['response'] = attempt['response']
        attempt['stdout'] = ''.join(json.dumps(e) + '\n' for e in attempt['events'])
        row['logical_results'][caller] = attempt['response']
        for e in row['timeline']:
            if e['kind'] == 'attempt_completed' and e['caller'] == caller and e['attempt'] == attempt['attempt']:
                e['status'] = attempt['response']['status']

    def test_wrong_historical_revision_is_a_negative_business_result(self):
        row = self.sample()
        self.rewrite_reply(row, 'first', revision=5)
        self.assertFalse(assess(row)['pair_correct'])
        self.assertEqual(evaluate(row), assess(row))

    def test_false_identical_conflict_is_measured_not_called_infrastructure(self):
        row = self.sample()
        self.rewrite_reply(row, 'first', status='conflict', revision=None, approved_sha256=None)
        actual = assess(row)
        self.assertEqual(actual['false_conflicts'], 1)
        self.assertFalse(actual['pair_correct'])
        self.assertEqual(evaluate(row), actual)

    def test_changed_intent_cannot_be_claimed_as_a_successful_replay(self):
        row = self.sample('overlap-changed_bytes')
        self.rewrite_reply(row, 'first', status='replayed', revision=4, approved_sha256=row['final']['state']['approved_sha256'])
        self.assertFalse(assess(row)['pair_correct'])
        self.assertEqual(evaluate(row), assess(row))

    def test_missing_actor_trace_is_rejected_by_both_oracles(self):
        row = self.sample()
        row['attempts'][0]['events'].pop(2)
        for oracle in (assess, evaluate):
            with self.assertRaises(ValueError):
                oracle(row)

    def test_changed_retry_identity_and_command_are_rejected(self):
        for target in ('request', 'command'):
            row = self.sample(mode='transactional_lookup')
            attempt = row['attempts'][-1]
            if target == 'request':
                attempt['request']['request_id'] = 'changed'
            else:
                attempt['command'][9] = 'changed'
            for oracle in (assess, evaluate):
                with self.assertRaises(ValueError):
                    oracle(row)

    def test_forged_winner_cannot_override_observed_bytes(self):
        row = self.sample('overlap-changed_bytes')
        row['final']['call_commits'][0]['caller'] = 'first'
        for oracle in (assess, evaluate):
            with self.assertRaises(ValueError):
                oracle(row)

    def test_capture_cannot_rewrite_a_prior_prefix(self):
        row = self.sample(mode='transactional_lookup')
        row['after_first'] = copy.deepcopy(row['initial'])
        for oracle in (assess, evaluate):
            with self.assertRaises(ValueError):
                oracle(row)

    def test_later_acknowledgment_must_match_its_own_committed_effect(self):
        row = self.sample()
        self.rewrite_reply(row, 'later', revision=4)
        for oracle in (assess, evaluate):
            with self.assertRaises(ValueError):
                oracle(row)

    def test_missing_or_repeated_grid_record_and_forged_verdict_are_rejected(self):
        bad_sets = [self.rows[:-1], self.rows + [self.rows[0]]]
        changed = copy.deepcopy(self.rows)
        changed[0]['oracle']['pair_correct'] = True
        bad_sets.append(changed)
        for records in bad_sets:
            for counter in (summarize, recount):
                with self.assertRaises(ValueError):
                    counter(records, self.cases)

    def test_manifest_rejects_semantic_duplicate_with_a_fresh_id(self):
        data = json.loads(self.dataset.read_text())
        data['cases'][1] = {**data['cases'][0], 'case_id': 'new-id'}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'manifest.json'
            path.write_text(json.dumps(data))
            for loader in (load_cases, manifest):
                with self.assertRaises(ValueError):
                    loader(path)

    def test_independent_verifier_has_no_measured_module_imports(self):
        tree = ast.parse((ROOT / 'experiments/verify_caller_results.py').read_text())
        modules = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                modules.extend(n.name for n in node.names)
            elif isinstance(node, ast.ImportFrom):
                modules.append(node.module or '')
        self.assertFalse(any(m.startswith(('src', 'experiments')) for m in modules))


if __name__ == '__main__':
    unittest.main()
