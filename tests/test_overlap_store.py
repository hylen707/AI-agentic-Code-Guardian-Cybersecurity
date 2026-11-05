import copy
import json
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from experiments.run_overlap_comparison import BarrierFailure, assess, load_cases, run_case, summarize, validate_retirement, wait_for_pause
from experiments.verify_overlap_results import evaluate
from src.overlap_store import MODES, OverlapPublicationStore
from src.publication_store import recover_value


class OverlapStoreTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix="codeguardian-overlap-test-")
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.number = 0

    def store(self, mode="transactional_admission"):
        self.number += 1
        store = OverlapPublicationStore(self.root / str(self.number), mode)
        store.initialize(b"approved=version-a\n")
        store.publish_request(1, "request-1", b"approved=version-b\n")
        store.publish_request(1, "request-2", None)
        return store

    @staticmethod
    def case(schedule="after_final_check", operation="update", value="ascii"):
        return {"case_id": "unit-case", "schedule": schedule, "operation": operation, "value": value}

    @staticmethod
    def fail_at(target):
        def fail(stage):
            if stage == target:
                raise RuntimeError("injected " + stage)
        return fail

    def assert_oracles_match(self, row):
        self.assertEqual(row["status"], "complete", row)
        self.assertEqual(evaluate(row), row["oracle"])

    def helper_process(self, code):
        child = subprocess.Popen([sys.executable, "-c", code], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        def cleanup():
            if child.poll() is None:
                child.kill()
            child.communicate(timeout=5)
        self.addCleanup(cleanup)
        return child

    def test_unknown_mode_and_invalid_request_do_not_silently_execute(self):
        with self.assertRaises(ValueError):
            OverlapPublicationStore(self.root, "unknown")
        store = self.store()
        before = store.inspect()
        for epoch, key, payload in ((True, "new", b"B"), (1, "../bad", b"B"), (1, "new", "text")):
            with self.subTest(epoch=epoch, key=key), self.assertRaises(ValueError):
                store.publish_overlap(epoch, key, payload)
        self.assertEqual(store.inspect(), before)

    def test_current_values_and_revocation_share_effect_and_witness(self):
        for value in (b"", "안전 ✓".encode(), None):
            store = self.store()
            store.try_retire(2)
            result = store.publish_overlap(2, "inflight", value)
            observed = store.inspect()
            self.assertEqual(result["revision"], 4)
            self.assertEqual(observed["commit_witnesses"], [{"revision": 4, "requested_epoch": 2, "active_epoch": 2, "request_id": "inflight"}])
            self.assertEqual(observed["effects"][-1]["revision"], 4)
            if value is None:
                self.assertEqual(recover_value(store.snapshot())["reason"], "approval_revoked")
            else:
                self.assertEqual(recover_value(store.snapshot())["content"], value)

    def test_matching_historical_receipt_has_no_new_witness_or_effect(self):
        for mode in MODES:
            store = self.store(mode)
            before = store.inspect()
            result = store.publish_overlap(1, "request-1", b"approved=version-b\n")
            self.assertEqual((result["status"], result["revision"]), ("replayed", 2))
            self.assertEqual(store.inspect(), before)

    def test_conflicting_receipt_has_no_effect(self):
        store = self.store()
        before = store.inspect()
        self.assertEqual(store.publish_overlap(1, "request-1", b"different")["status"], "conflict")
        self.assertEqual(store.inspect(), before)

    def test_closed_and_future_epochs_are_denied_without_witnesses(self):
        for mode in MODES:
            store = self.store(mode)
            store.try_retire(2)
            before = store.inspect()
            for epoch, expected in ((1, "epoch_retired"), (3, "future_epoch")):
                self.assertEqual(store.publish_overlap(epoch, "fresh", b"B")["status"], expected)
            self.assertEqual(store.inspect(), before)
            self.assertEqual(store.try_retire(2)["status"], "already_retired")

    def test_real_writer_contention_returns_numeric_busy_at_begin(self):
        store = self.store()
        connection = store._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            result = store.try_retire(2)
            self.assertEqual((result["status"], result["sqlite_errorcode"], result["sqlite_errorname"]), ("busy", 5, "SQLITE_BUSY"))
            self.assertEqual(result["busy_timeout_ms"], 0)
            self.assertIsNone(result["active_epoch"])
        finally:
            connection.close()
        self.assertEqual(store.try_retire(2)["status"], "retired")

    def test_nonbusy_begin_error_is_not_classified_as_deferral(self):
        store = self.store()
        error = sqlite3.OperationalError("injected nonbusy failure")
        error.sqlite_errorcode, error.sqlite_errorname = 6, "SQLITE_LOCKED"
        connection = Mock()
        connection.execute.side_effect = error
        with patch.object(store, "_probe_connection", return_value=connection):
            with self.assertRaises(sqlite3.OperationalError):
                store.try_retire(2)
        connection.close.assert_called_once()
        self.assertEqual(store.inspect()["active_epoch"], 1)

    def test_retirement_write_failure_is_not_a_busy_success(self):
        store = self.store()
        before = store.inspect()
        with sqlite3.connect(store.database) as connection:
            connection.execute("CREATE TRIGGER reject_retirement BEFORE UPDATE ON namespace "
                               "BEGIN SELECT RAISE(ABORT, 'injected retirement write failure'); END")
        with self.assertRaises(sqlite3.IntegrityError):
            store.try_retire(2)
        self.assertEqual(store.inspect(), before)

    def test_probe_rejects_a_different_journal_mode(self):
        store = self.store()
        with sqlite3.connect(store.database) as connection:
            self.assertEqual(connection.execute("PRAGMA journal_mode=WAL").fetchone()[0], "wal")
        with self.assertRaises(ValueError):
            store.try_retire(2)

    def test_precommit_exception_rolls_back_witness_with_publication(self):
        for mode in MODES:
            store = self.store(mode)
            before = store.inspect()
            with self.assertRaises(RuntimeError):
                store.publish_overlap(1, "inflight", b"B", checkpoint=self.fail_at("before_commit"))
            self.assertEqual(store.inspect(), before)

    def test_witness_insert_failure_cannot_leave_a_committed_effect(self):
        store = self.store()
        before = store.inspect()
        with sqlite3.connect(store.database) as connection:
            connection.execute("CREATE TRIGGER reject_witness BEFORE INSERT ON commit_witnesses "
                               "BEGIN SELECT RAISE(ABORT, 'injected witness failure'); END")
        with self.assertRaises(sqlite3.IntegrityError):
            store.publish_overlap(1, "inflight", b"B")
        self.assertEqual(store.inspect(), before)

    def test_callback_failure_releases_the_transactional_writer(self):
        store = self.store()
        with self.assertRaises(RuntimeError):
            store.publish_overlap(1, "inflight", b"B", checkpoint=self.fail_at("after_admission"))
        self.assertEqual(store.try_retire(2)["status"], "retired")

    def test_postcommit_callback_failure_keeps_an_earlier_valid_witness(self):
        store = self.store()
        with self.assertRaises(RuntimeError):
            store.publish_overlap(1, "inflight", b"B", checkpoint=self.fail_at("after_commit"))
        self.assertEqual(store.inspect()["commit_witnesses"][0]["active_epoch"], 1)
        store.try_retire(2)
        observed = store.inspect()
        self.assertEqual(observed["active_epoch"], 2)
        self.assertEqual(observed["commit_witnesses"][0]["active_epoch"], 1)
        self.assertEqual(observed["state"].revision, 4)

    def test_cached_admission_commits_after_the_retirement_fence(self):
        row = run_case(self.case("after_admission"), "cached_admission")
        self.assert_oracles_match(row)
        self.assertTrue(row["oracle"]["invalid_old_effect"])
        self.assertEqual(row["final"]["commit_witnesses"][0]["active_epoch"], 2)

    def test_separate_recheck_catches_retirement_after_initial_admission(self):
        row = run_case(self.case("after_admission"), "separate_recheck")
        self.assert_oracles_match(row)
        self.assertTrue(row["oracle"]["old_denial"])
        self.assertEqual(row["final"]["commit_witnesses"], [])

    def test_separate_final_check_still_has_a_write_gap(self):
        row = run_case(self.case(), "separate_recheck")
        self.assert_oracles_match(row)
        checks = [e for e in row["publisher"]["events"] if e["kind"] in {"admission", "final_decision"}]
        self.assertEqual([e["observed_epoch"] for e in checks], [1, 1])
        self.assertTrue(row["oracle"]["invalid_old_effect"])

    def test_transactional_admission_defers_then_retries_retirement(self):
        row = run_case(self.case(), "transactional_admission")
        self.assert_oracles_match(row)
        self.assertEqual([a["response"]["status"] for a in row["retirement_attempts"]], ["busy", "retired"])
        self.assertTrue(row["oracle"]["valid_old_commit"])
        self.assertEqual(row["final"]["commit_witnesses"][0]["active_epoch"], 1)

    def test_staged_publication_is_not_visible_to_the_pause_observer(self):
        for mode in MODES:
            row = run_case(self.case("before_commit", operation="revoke"), mode)
            self.assert_oracles_match(row)
            self.assertEqual(row["pause_capture"]["state"]["revision"], 3)
            self.assertEqual(row["pause_capture"]["commit_witnesses"], [])
            self.assertEqual(row["final"]["state"]["revision"], 4)
            self.assertTrue(row["oracle"]["retirement_deferred"])

    def test_response_after_retirement_can_describe_a_valid_prior_commit(self):
        for mode in MODES:
            row = run_case(self.case("after_commit"), mode)
            self.assert_oracles_match(row)
            self.assertEqual(row["pause_capture"]["active_epoch"], 2)
            self.assertEqual(row["pause_capture"]["commit_witnesses"][0]["active_epoch"], 1)
            self.assertTrue(row["oracle"]["postcommit_historical_reply"])
            self.assertFalse(row["oracle"]["invalid_old_effect"])

    def test_retirement_before_start_denies_the_old_publication(self):
        row = run_case(self.case("retire_first"), "transactional_admission")
        self.assert_oracles_match(row)
        self.assertEqual(row["publisher"]["response"]["status"], "epoch_retired")
        self.assertEqual(row["final"]["state"]["revision"], 3)

    def test_current_unicode_control_delivers_the_actual_value(self):
        row = run_case(self.case("current_epoch", value="unicode"), "transactional_admission")
        self.assert_oracles_match(row)
        self.assertEqual(row["final"]["delivery"]["delivered_utf8"], "approved=안전 ✓\n")
        self.assertTrue(row["oracle"]["new_current_success"])

    def test_busy_word_without_numeric_busy_code_is_not_accepted(self):
        row = run_case(self.case(), "transactional_admission")
        bad = copy.deepcopy(row["retirement_attempts"][0])
        bad["response"]["sqlite_errorcode"] = 6
        with self.assertRaises(ValueError):
            validate_retirement(bad)

    def test_false_denial_cannot_hide_a_committed_late_effect(self):
        row = run_case(self.case(), "cached_admission")
        row["publisher"]["response"].update(status="epoch_retired", revision=None, approved_sha256=None)
        for oracle in (assess, evaluate):
            with self.assertRaises(ValueError):
                oracle(row)

    def test_missing_witness_cannot_count_as_a_successful_denial(self):
        row = run_case(self.case(), "cached_admission")
        row["final"]["commit_witnesses"] = []
        for oracle in (assess, evaluate):
            with self.assertRaises(ValueError):
                oracle(row)

    def test_controller_order_is_checked_in_addition_to_child_labels(self):
        row = run_case(self.case(), "cached_admission")
        row["timeline"][1], row["timeline"][2] = row["timeline"][2], row["timeline"][1]
        for oracle in (assess, evaluate):
            with self.assertRaises(ValueError):
                oracle(row)

    def test_unrelated_retirement_child_failure_is_an_infrastructure_error(self):
        with patch("experiments.run_overlap_comparison.subprocess.run", return_value=subprocess.CompletedProcess([], 1, "", "failed")):
            row = run_case(self.case(), "transactional_admission")
        self.assertEqual(row["status"], "infrastructure_error")
        self.assertIsNone(row["oracle"])
        self.assertEqual(row["retirement_attempts"][0]["stderr"], "failed")

    def test_wrong_barrier_preserves_its_observed_bytes(self):
        child = self.helper_process("import json,sys; print(json.dumps({'kind':'paused','stage':'wrong'}),flush=True); sys.stdin.readline()")
        with self.assertRaises(BarrierFailure) as caught:
            wait_for_pause(child, "after_admission", timeout=3)
        self.assertIn(b'wrong', caught.exception.output)

    def test_malformed_barrier_is_an_error_with_retained_output(self):
        child = self.helper_process("print('not-json',flush=True)")
        with self.assertRaises(BarrierFailure) as caught:
            wait_for_pause(child, "after_admission", timeout=3)
        self.assertIn(b'not-json', caught.exception.output)

    def test_missing_barrier_has_a_deadline(self):
        child = self.helper_process("import sys; sys.stdin.readline()")
        with self.assertRaises(subprocess.TimeoutExpired):
            wait_for_pause(child, "after_admission", timeout=0.05)

    def test_controller_barrier_timeout_cleans_up_the_publisher(self):
        with patch("experiments.run_overlap_comparison.wait_for_pause", side_effect=subprocess.TimeoutExpired([], 15, output=b'partial')):
            row = run_case(self.case(), "transactional_admission")
        self.assertEqual(row["status"], "infrastructure_error")
        self.assertTrue(row["publisher"]["stdout"].startswith('partial'))
        self.assertIsNone(row["oracle"])

    def test_resume_command_must_match_the_held_stage(self):
        store = self.store()
        root = Path(__file__).resolve().parents[1]
        command = [sys.executable, str(root/'experiments/overlap_worker.py'), '--role', 'publish', '--root', str(store.root),
                   '--mode', store.mode, '--pause', 'after_admission']
        child = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        try:
            prefix = wait_for_pause(child, 'after_admission', timeout=5)
            tail, stderr = child.communicate(input=b'{"command":"resume","stage":"before_commit"}\n', timeout=5)
            self.assertNotEqual(child.returncode, 0)
            self.assertIn(b'exact resume command', stderr)
            self.assertEqual(store.inspect()["commit_witnesses"], [])
            self.assertEqual(store.try_retire(2)["status"], "retired")
        finally:
            if child.poll() is None:
                child.kill()
            child.communicate(timeout=5)

    def test_manifest_rejects_semantic_repeats_and_missing_cases(self):
        root = Path(__file__).resolve().parents[1]
        manifest = json.loads((root/'experiments/tasks/overlap-eval-v1/tasks.json').read_text())
        path = self.root/'cases.json'
        for mutation in ('repeat', 'missing', 'unknown'):
            value = copy.deepcopy(manifest)
            if mutation == 'repeat':
                value['cases'][1] = {**value['cases'][0], 'case_id':'different'}
            elif mutation == 'missing':
                value['cases'].pop()
            else:
                value['cases'][0]['schedule'] = 'sleep_guess'
            path.write_text(json.dumps(value))
            with self.assertRaises(ValueError):
                load_cases(path)

    def test_summary_rejects_missing_pairs_and_forged_verdicts(self):
        case = self.case()
        rows = [run_case(case, mode) for mode in MODES]
        with self.assertRaises(ValueError):
            summarize(rows[:-1], [case])
        rows[0]['oracle']['invalid_old_effect'] = False
        with self.assertRaises(ValueError):
            summarize(rows, [case])


if __name__ == '__main__':
    unittest.main()
