import copy
import json
import sqlite3
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from experiments.run_retirement_comparison import assess, capture, load_cases, run_case, summarize, validate_capture, validate_trace
from experiments.verify_retirement_results import evaluate, trace
from src.publication_store import recover_value
from src.retirement_store import ARMS, MAX_EPOCH, RetirementPublicationStore, validate_epoch


class RetirementStoreTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix="codeguardian-retirement-test-")
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.number = 0

    def store(self, arm="atomic_fence", operation="update"):
        self.number += 1
        store = RetirementPublicationStore(self.root / str(self.number), arm)
        store.initialize(b"approved=version-a\n")
        update = operation == "update"
        store.publish_request(1, "request-1", b"approved=version-b\n" if update else None)
        store.publish_request(1, "request-2", None if update else b"approved=version-c\n")
        return store

    @staticmethod
    def case(scenario="late_known", operation="update", cut="none", value="ascii"):
        return {"case_id": "test-case", "scenario": scenario, "operation": operation, "value": value, "cut": cut}

    @staticmethod
    def fail_at(target):
        def fail(stage):
            if stage == target:
                raise RuntimeError("injected " + stage)
        return fail

    def test_epoch_type_range_and_boolean_are_explicit(self):
        for epoch in (None, True, False, 0, -1, 1.0, "1", MAX_EPOCH + 1):
            with self.subTest(epoch=epoch), self.assertRaises(ValueError):
                validate_epoch(epoch)
        validate_epoch(1)
        validate_epoch(MAX_EPOCH)

    def test_unknown_arm_and_missing_store_are_explicit_errors(self):
        with self.assertRaises(ValueError):
            RetirementPublicationStore(self.root, "unknown")
        missing = RetirementPublicationStore(self.root / "missing", "atomic_fence")
        with self.assertRaises(sqlite3.OperationalError):
            missing.publish_request(1, "one", b"B")
        self.assertFalse(missing.database.exists())

    def test_existing_store_cannot_be_reinitialized(self):
        store = self.store()
        before = store.inspect()
        with self.assertRaises(FileExistsError):
            store.initialize(b"other")
        self.assertEqual(store.inspect(), before)

    def test_future_epoch_is_rejected_without_any_new_effect(self):
        for arm in ARMS:
            store = self.store(arm)
            before = store.inspect()
            answer = store.publish_request(2, "future", b"B")
            self.assertEqual(answer["status"], "future_epoch")
            self.assertIsNone(answer["revision"])
            self.assertEqual(store.inspect(), before)

    def test_retirement_changes_receipts_and_epoch_but_preserves_publication(self):
        for arm in ARMS:
            store = self.store(arm)
            before = store.inspect()
            store.retire(2)
            after = RetirementPublicationStore(store.root, arm).inspect()
            self.assertEqual(after["active_epoch"], 2)
            self.assertEqual(after["state"], before["state"])
            self.assertEqual(after["effects"], before["effects"])
            self.assertEqual(len(after["receipts"]), 2 if arm == "retain_all" else 0)

    def test_retained_old_reply_does_not_reauthorize_its_value(self):
        store = self.store("retain_all")
        store.retire(2)
        before = store.inspect()
        result = store.publish_request(1, "request-1", b"approved=version-b\n")
        self.assertEqual((result["status"], result["revision"]), ("replayed", 2))
        self.assertEqual(store.inspect(), before)
        self.assertEqual(recover_value(store.snapshot())["reason"], "approval_revoked")

    def test_compaction_rejects_old_known_request_without_a_commitment(self):
        store = self.store()
        store.retire(2)
        before = store.inspect()
        result = store.publish_request(1, "request-1", b"approved=version-b\n")
        self.assertEqual(result["status"], "epoch_retired")
        self.assertIsNone(result["revision"])
        self.assertIsNone(result["approved_sha256"])
        self.assertEqual(store.inspect(), before)

    def test_forgetting_reinstates_a_revoked_value_as_a_new_effect(self):
        store = self.store("forget_only")
        store.retire(2)
        result = store.publish_request(1, "request-1", b"approved=version-b\n")
        self.assertEqual((result["status"], result["revision"]), ("committed", 4))
        self.assertEqual(recover_value(store.snapshot())["content"], b"approved=version-b\n")
        self.assertEqual(len(store.inspect()["effects"]), 3)

    def test_unseen_closed_epoch_is_rejected_even_when_no_id_was_stored(self):
        for arm in ("retain_all", "split_fence", "atomic_fence"):
            store = self.store(arm)
            store.retire(2)
            before = store.inspect()
            self.assertEqual(store.publish_request(1, "never-seen", b"new")["status"], "epoch_retired")
            self.assertEqual(store.inspect(), before)

    def test_literal_id_reuse_in_new_epoch_is_a_distinct_intent(self):
        for arm in ARMS:
            store = self.store(arm)
            store.retire(2)
            result = store.publish_request(2, "request-1", b"different")
            self.assertEqual((result["status"], result["revision"]), ("committed", 4))
            self.assertEqual(store.inspect()["effects"][-1]["epoch"], 2)

    def test_current_retry_retains_one_effect_after_reopen(self):
        store = self.store()
        store.retire(2)
        first = store.publish_request(2, "current", b"B")
        before = store.inspect()
        result = RetirementPublicationStore(store.root, store.arm).publish_request(2, "current", b"B")
        self.assertEqual(result, {**first, "status": "replayed"})
        self.assertEqual(store.inspect(), before)

    def test_current_empty_update_and_revocation_conflict(self):
        store = self.store()
        store.retire(2)
        store.publish_request(2, "current", b"")
        before = store.inspect()
        self.assertEqual(store.publish_request(2, "current", None)["status"], "conflict")
        self.assertEqual(store.inspect(), before)
        self.assertEqual(recover_value(store.snapshot())["content"], b"")

    def test_old_changed_intent_is_conflict_if_retained_and_retired_if_removed(self):
        for arm, expected in (("retain_all", "conflict"), ("atomic_fence", "epoch_retired")):
            store = self.store(arm)
            store.retire(2)
            before = store.inspect()
            self.assertEqual(store.publish_request(1, "request-1", b"different")["status"], expected)
            self.assertEqual(store.inspect(), before)

    def test_retirement_retry_does_not_advance_or_delete_current_receipts(self):
        store = self.store()
        store.retire(2)
        store.publish_request(2, "current", b"C")
        before = store.inspect()
        self.assertEqual(store.retire(2), {"status": "already_retired", "active_epoch": 2})
        self.assertEqual(store.inspect(), before)
        for target in (1, 4):
            with self.subTest(target=target), self.assertRaises(ValueError):
                store.retire(target)
        self.assertEqual(store.inspect(), before)

    def test_next_retirement_cannot_reopen_an_older_namespace(self):
        store = self.store()
        store.retire(2)
        store.publish_request(2, "current", b"C")
        store.retire(3)
        before = store.inspect()
        self.assertEqual(store.publish_request(2, "current", b"C")["status"], "epoch_retired")
        self.assertEqual(store.publish_request(1, "request-1", b"approved=version-b\n")["status"], "epoch_retired")
        self.assertEqual(store.inspect(), before)
        self.assertEqual(store.publish_request(3, "current", b"D")["status"], "committed")

    def test_missing_epoch_metadata_cannot_fall_back_to_epoch_one(self):
        store = self.store()
        with sqlite3.connect(store.database) as connection:
            connection.execute("DELETE FROM namespace")
        with self.assertRaises(ValueError):
            store.publish_request(1, "new", b"B")
        with self.assertRaises(ValueError):
            store.retire(2)

    def test_invalid_epoch_and_request_input_do_not_mutate_the_store(self):
        store = self.store()
        before = store.inspect()
        for epoch, key, payload in ((True, "valid", b"B"), (1, "../bad", b"B"), (1, "valid", "text")):
            with self.subTest(epoch=epoch, key=key), self.assertRaises(ValueError):
                store.publish_request(epoch, key, payload)
        with self.assertRaises(ValueError):
            store.retire(MAX_EPOCH + 1)
        self.assertEqual(store.inspect(), before)

    def test_after_cleanup_exception_exposes_split_gap_but_rolls_back_atomic(self):
        for arm, remaining in (("split_fence", 0), ("atomic_fence", 2)):
            store = self.store(arm)
            with self.assertRaises(RuntimeError):
                store.retire(2, checkpoint=self.fail_at("after_cleanup"))
            after = RetirementPublicationStore(store.root, arm).inspect()
            self.assertEqual(after["active_epoch"], 1)
            self.assertEqual(len(after["receipts"]), remaining)

    def test_postcommit_exception_does_not_roll_back_the_fence(self):
        store = self.store()
        with self.assertRaises(RuntimeError):
            store.retire(2, checkpoint=self.fail_at("after_commit"))
        self.assertEqual(store.inspect()["active_epoch"], 2)
        self.assertEqual(store.publish_request(1, "request-1", b"approved=version-b\n")["status"], "epoch_retired")
        self.assertEqual(store.retire(2)["status"], "already_retired")

    def test_epoch_write_failure_retains_or_exposes_prior_cleanup(self):
        for arm, receipt_count in (("split_fence", 0), ("atomic_fence", 2)):
            store = self.store(arm)
            with sqlite3.connect(store.database) as connection:
                connection.execute("CREATE TRIGGER reject_epoch BEFORE UPDATE ON namespace "
                                   "BEGIN SELECT RAISE(ABORT, 'injected epoch failure'); END")
            with self.assertRaises(sqlite3.IntegrityError):
                store.retire(2)
            self.assertEqual(store.inspect()["active_epoch"], 1)
            self.assertEqual(len(store.inspect()["receipts"]), receipt_count)

    def test_cleanup_failure_rolls_back_the_staged_atomic_fence(self):
        store = self.store()
        before = store.inspect()
        with sqlite3.connect(store.database) as connection:
            connection.execute("CREATE TRIGGER reject_cleanup BEFORE DELETE ON requests "
                               "BEGIN SELECT RAISE(ABORT, 'injected cleanup failure'); END")
        with self.assertRaises(sqlite3.IntegrityError):
            store.retire(2)
        self.assertEqual(store.inspect(), before)

    def test_new_receipt_failure_rolls_back_its_state_and_effect(self):
        store = self.store()
        store.retire(2)
        before = store.inspect()
        with sqlite3.connect(store.database) as connection:
            connection.execute("CREATE TRIGGER reject_receipt BEFORE INSERT ON requests "
                               "BEGIN SELECT RAISE(ABORT, 'injected receipt failure'); END")
        with self.assertRaises(sqlite3.IntegrityError):
            store.publish_request(2, "new", b"C")
        self.assertEqual(store.inspect(), before)

    def test_receipt_bytes_must_match_the_observed_effect(self):
        store = self.store()
        observed = capture(store)
        observed["receipts"][0]["payload_utf8"] = "forged"
        with self.assertRaises(ValueError):
            validate_capture(observed)

    def test_real_cleanup_exit_separates_split_gap_from_rolled_back_cleanup(self):
        for arm, extra in (("retain_all", 0), ("forget_only", 0), ("split_fence", 1), ("atomic_fence", 0)):
            row = run_case(self.case(cut="after_cleanup"), arm)
            self.assertEqual(row["status"], "complete")
            self.assertEqual(row["worker_returncode"], 73)
            self.assertEqual(row["oracle"]["known_extra_effects"], extra)
            self.assertEqual(evaluate(row), row["oracle"])

    def test_real_committed_retirement_has_safe_rejection_but_no_old_reply(self):
        row = run_case(self.case(cut="after_commit"), "atomic_fence")
        self.assertEqual(row["status"], "complete")
        self.assertTrue(row["oracle"]["known_closed_denial"])
        self.assertFalse(row["oracle"]["historical_reply"])
        self.assertEqual(row["attempts"][0]["response"]["status"], "epoch_retired")
        self.assertEqual(evaluate(row), row["oracle"])

    def test_real_before_retire_exit_preserves_the_original_receipts(self):
        row = run_case(self.case(operation="revoke", cut="before_retire"), "atomic_fence")
        self.assertEqual(row["status"], "complete")
        self.assertEqual(len(row["recovered"]["receipts"]), 2)
        self.assertTrue(row["oracle"]["historical_reply"])
        self.assertEqual(evaluate(row), row["oracle"])

    def test_real_after_ack_exit_recovers_the_retirement_target(self):
        row = run_case(self.case(cut="after_ack"), "split_fence")
        self.assertEqual(row["status"], "complete")
        self.assertEqual(row["recovered"]["active_epoch"], 2)
        self.assertTrue(row["oracle"]["known_policy_preserved"])
        trace(row)

    def test_new_epoch_same_id_is_not_counted_as_an_old_duplicate(self):
        row = run_case(self.case("new_epoch_same_id"), "atomic_fence")
        self.assertEqual(row["status"], "complete")
        self.assertTrue(row["oracle"]["new_current_success"])
        self.assertEqual(row["oracle"]["known_extra_effects"], 0)
        self.assertEqual(row["attempts"][0]["after"]["effects"][-1]["epoch"], 2)
        self.assertEqual(evaluate(row), row["oracle"])

    def test_retired_label_cannot_hide_an_actual_reapplied_effect(self):
        row = run_case(self.case(), "forget_only")
        row["attempts"][0]["response"].update(status="epoch_retired", revision=None, approved_sha256=None)
        for oracle in (assess, evaluate):
            verdict = oracle(row)
            self.assertTrue(verdict["known_duplicate_case"])
            self.assertFalse(verdict["contract_satisfied"])
            self.assertFalse(verdict["known_closed_denial"])

    def test_output_different_from_captured_bytes_is_rejected(self):
        row = run_case(self.case("current_single", value="unicode"), "atomic_fence")
        self.assertEqual(row["status"], "complete")
        row["attempts"][0]["after"]["delivery"]["delivered_utf8"] = "forged"
        for oracle in (assess, evaluate):
            with self.assertRaises(ValueError):
                oracle(row)

    def test_exit_code_alone_does_not_prove_retirement_boundary_coverage(self):
        row = run_case(self.case(cut="after_ack"), "atomic_fence")
        row["worker_events"] = [e for e in row["worker_events"] if e["kind"] != "acknowledged"]
        for check in (validate_trace, trace):
            with self.assertRaises(ValueError):
                check(row)

    def test_unrelated_child_failure_is_an_infrastructure_error(self):
        with patch("experiments.run_retirement_comparison.subprocess.run", return_value=subprocess.CompletedProcess([], 1, "", "failed")):
            row = run_case(self.case(), "atomic_fence")
        self.assertEqual(row["status"], "infrastructure_error")
        self.assertEqual(row["error_phase"], "trace_validation")
        self.assertIsNone(row["oracle"])

    def test_timeout_is_retained_as_an_error_without_a_security_verdict(self):
        with patch("experiments.run_retirement_comparison.subprocess.run", side_effect=subprocess.TimeoutExpired([], 15, output=b"partial", stderr=b"timeout")):
            row = run_case(self.case(), "atomic_fence")
        self.assertEqual(row["status"], "infrastructure_error")
        self.assertEqual(row["worker_stdout"], "partial")
        self.assertIsNone(row["oracle"])

    def test_manifest_rejects_repeated_semantics_or_changed_matrix(self):
        root = Path(__file__).resolve().parents[1]
        manifest = json.loads((root / "experiments/tasks/retirement-eval-v1/tasks.json").read_text())
        path = self.root / "cases.json"
        for mutation in ("repeat", "missing", "unknown"):
            value = copy.deepcopy(manifest)
            if mutation == "repeat":
                value["cases"][1] = {**value["cases"][0], "case_id": "another"}
            elif mutation == "missing":
                value["cases"].pop()
            else:
                value["cases"][0]["cut"] = "inside_commit"
            path.write_text(json.dumps(value))
            with self.assertRaises(ValueError):
                load_cases(path)

    def test_summary_rejects_missing_pairs_and_forged_outcomes(self):
        case = self.case()
        rows = [run_case(case, arm) for arm in ARMS]
        with self.assertRaises(ValueError):
            summarize(rows[:-1], [case])
        rows[0]["oracle"]["known_policy_preserved"] = False
        with self.assertRaises(ValueError):
            summarize(rows, [case])


if __name__ == "__main__":
    unittest.main()
