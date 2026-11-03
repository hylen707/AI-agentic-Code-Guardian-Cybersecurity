import copy
import json
import sqlite3
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from experiments.run_retry_comparison import assess, capture, load_cases, run_case, summarize, validate_capture, validate_trace
from experiments.verify_retry_results import evaluate, trace
from src.publication_store import digest, recover_value
from src.retry_store import ARMS, RetryPublicationStore, validate_request


class RetryStoreTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix="codeguardian-retry-test-")
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.number = 0

    def store(self, arm="atomic_receipt", initial=b"A"):
        self.number += 1
        store = RetryPublicationStore(self.root / str(self.number), arm)
        store.initialize(initial)
        return store

    @staticmethod
    def fail_at(target):
        def fail(stage):
            if stage == target:
                raise RuntimeError("injected " + stage)
        return fail

    @staticmethod
    def case(scenario="repeat", operation="update", cut="none"):
        return {"case_id": "test-case", "scenario": scenario, "operation": operation, "value": "ascii", "cut": cut}

    def test_request_identity_and_payload_types_are_validated(self):
        for key in (None, "", "../key", "한글", "x" * 81, True):
            with self.subTest(key=key), self.assertRaises(ValueError):
                validate_request(key, b"B")
        for payload in ("B", False, bytearray(b"B")):
            with self.subTest(payload=payload), self.assertRaises(ValueError):
                validate_request("request-1", payload)
        self.assertEqual(validate_request("valid_1.-", b""), "update")
        self.assertEqual(validate_request("valid_1.-", None), "revoke")

    def test_unknown_arm_is_not_silently_replaced(self):
        with self.assertRaises(ValueError):
            RetryPublicationStore(self.root, "unknown")

    def test_missing_or_existing_store_cannot_be_silently_created_or_reset(self):
        with self.assertRaises(sqlite3.OperationalError):
            RetryPublicationStore(self.root / "missing", "atomic_receipt").inspect()
        store = self.store()
        store.publish_request("one", b"B")
        with self.assertRaises(FileExistsError):
            store.initialize(b"C")
        self.assertEqual(store.snapshot().revision, 2)

    def test_retry_returns_the_original_receipt_across_reopen(self):
        for arm in ARMS[1:]:
            store = self.store(arm)
            first = store.publish_request("one", b"B")
            reopened = RetryPublicationStore(store.root, arm)
            second = reopened.publish_request("one", b"B")
            self.assertEqual(second, {**first, "status": "replayed"})
            self.assertEqual(len(reopened.inspect()["effects"]), 1)

    def test_unkeyed_retry_creates_another_coherent_revision(self):
        store = self.store("unkeyed")
        for _ in range(2):
            store.publish_request("one", b"B")
        self.assertEqual(store.snapshot().revision, 3)
        self.assertEqual(store.snapshot().approved_sha256, digest(b"B"))
        self.assertEqual(len(store.inspect()["effects"]), 2)
        self.assertEqual(store.inspect()["receipts"], [])

    def test_empty_update_and_revocation_are_different_intents(self):
        for arm in ARMS[1:]:
            store = self.store(arm)
            store.publish_request("one", b"")
            before = store.inspect()
            self.assertEqual(store.publish_request("one", None)["status"], "conflict")
            self.assertEqual(store.inspect(), before)
            self.assertEqual(recover_value(store.snapshot())["content"], b"")

    def test_changed_payload_is_a_conflict_without_effects(self):
        for arm in ARMS[1:]:
            store = self.store(arm)
            store.publish_request("one", b"B")
            before = store.inspect()
            response = store.publish_request("one", b"C")
            self.assertEqual(response["status"], "conflict")
            self.assertIsNone(response["revision"])
            self.assertEqual(store.inspect(), before)

    def test_revocation_key_cannot_be_reused_for_an_update(self):
        store = self.store()
        store.publish_request("one", None)
        self.assertEqual(store.publish_request("one", b"B")["status"], "conflict")
        self.assertIsNone(store.snapshot().approved_sha256)

    def test_exact_bytes_not_unicode_normalization_bind_intent(self):
        store = self.store()
        first = "é".encode("utf-8")
        second = "e\u0301".encode("utf-8")
        store.publish_request("one", first)
        self.assertEqual(store.publish_request("one", second)["status"], "conflict")
        self.assertEqual(store.snapshot().content, first)

    def test_distinct_keys_with_identical_payload_are_new_intents(self):
        for arm in ARMS:
            store = self.store(arm)
            store.publish_request("one", b"B")
            response = store.publish_request("two", b"B")
            self.assertEqual(response["revision"], 3)
            self.assertEqual([e["request_id"] for e in store.inspect()["effects"]], ["one", "two"])

    def test_distinct_revocation_is_a_new_revision(self):
        store = self.store()
        store.publish_request("one", None)
        store.publish_request("two", None)
        self.assertEqual(store.snapshot().revision, 3)
        self.assertEqual(len(store.inspect()["receipts"]), 2)

    def test_old_update_receipt_does_not_reauthorize_a_revoked_value(self):
        for arm in ARMS[1:]:
            store = self.store(arm)
            first = store.publish_request("one", b"B")
            store.publish_request("two", None)
            before = store.inspect()
            self.assertEqual(store.publish_request("one", b"B"), {**first, "status": "replayed"})
            self.assertEqual(store.inspect(), before)
            self.assertEqual(recover_value(store.snapshot())["reason"], "approval_revoked")

    def test_old_revocation_receipt_does_not_withdraw_a_new_approval(self):
        store = self.store()
        first = store.publish_request("one", None)
        store.publish_request("two", b"C")
        self.assertEqual(store.publish_request("one", None), {**first, "status": "replayed"})
        self.assertEqual(recover_value(store.snapshot())["content"], b"C")
        self.assertEqual(store.snapshot().revision, 3)

    def test_precommit_exception_rolls_back_state_effect_and_receipt(self):
        for arm in ARMS:
            store = self.store(arm)
            before = store.inspect()
            with self.assertRaises(RuntimeError):
                store.publish_request("one", b"B", checkpoint=self.fail_at("before_commit"))
            self.assertEqual(RetryPublicationStore(store.root, arm).inspect(), before)

    def test_split_postcommit_exception_leaves_an_unrecorded_effect(self):
        store = self.store("split_receipt")
        with self.assertRaises(RuntimeError):
            store.publish_request("one", b"B", checkpoint=self.fail_at("after_state_commit"))
        self.assertEqual(store.inspect()["receipts"], [])
        self.assertEqual(store.publish_request("one", b"B")["revision"], 3)
        self.assertEqual(len(store.inspect()["effects"]), 2)

    def test_atomic_postcommit_exception_retains_receipt_with_effect(self):
        store = self.store()
        with self.assertRaises(RuntimeError):
            store.publish_request("one", b"B", checkpoint=self.fail_at("after_state_commit"))
        response = RetryPublicationStore(store.root, store.arm).publish_request("one", b"B")
        self.assertEqual((response["status"], response["revision"]), ("replayed", 2))
        self.assertEqual(len(store.inspect()["effects"]), 1)

    def test_split_after_record_exception_has_an_idempotent_retry(self):
        store = self.store("split_receipt")
        with self.assertRaises(RuntimeError):
            store.publish_request("one", None, checkpoint=self.fail_at("after_record_commit"))
        self.assertEqual(store.publish_request("one", None)["status"], "replayed")
        self.assertEqual(store.snapshot().revision, 2)

    def test_receipt_write_failure_couples_or_separates_prior_effect(self):
        for arm, expected_revision in (("atomic_receipt", 1), ("split_receipt", 2)):
            store = self.store(arm)
            with sqlite3.connect(store.database) as connection:
                connection.execute("CREATE TRIGGER reject_receipt BEFORE INSERT ON requests "
                                   "BEGIN SELECT RAISE(ABORT, 'injected receipt failure'); END")
            with self.assertRaises(sqlite3.IntegrityError):
                store.publish_request("one", b"B")
            self.assertEqual(store.snapshot().revision, expected_revision)
            self.assertEqual(len(store.inspect()["effects"]), expected_revision - 1)
            self.assertEqual(store.inspect()["receipts"], [])

    def test_deleted_publication_is_an_explicit_store_error(self):
        store = self.store()
        with sqlite3.connect(store.database) as connection:
            connection.execute("DELETE FROM publication")
        with self.assertRaises(ValueError):
            store.publish_request("one", b"B")

    def test_missing_audit_row_cannot_count_as_successful_deduplication(self):
        store = self.store()
        store.publish_request("one", b"B")
        with sqlite3.connect(store.database) as connection:
            connection.execute("DELETE FROM effects")
        with self.assertRaises(ValueError):
            validate_capture(capture(store))

    def test_real_precommit_exit_retries_its_first_effect_once(self):
        row = run_case(self.case("crash", cut="before_commit"), "atomic_receipt")
        self.assertEqual(row["status"], "complete")
        self.assertEqual(row["worker_returncode"], 73)
        self.assertEqual(row["initial_recovery"]["effects"], [])
        self.assertTrue(row["oracle"]["retry_contract_satisfied"])
        self.assertEqual(evaluate(row), row["oracle"])

    def test_real_commit_gap_distinguishes_split_and_atomic_receipts(self):
        case = self.case("crash", "revoke", "after_state_commit")
        for arm, duplicates in (("split_receipt", 1), ("atomic_receipt", 0)):
            row = run_case(case, arm)
            self.assertEqual(row["status"], "complete")
            self.assertEqual(row["oracle"]["extra_request1_effects"], duplicates)
            self.assertEqual(evaluate(row), row["oracle"])
            trace(row)

    def test_real_after_ack_exit_does_not_require_another_mutation(self):
        row = run_case(self.case("crash", cut="after_ack"), "split_receipt")
        self.assertEqual(row["status"], "complete")
        self.assertEqual(row["attempts"][0]["response"]["status"], "replayed")
        self.assertTrue(row["oracle"]["retry_contract_satisfied"])

    def test_random_child_failure_is_an_infrastructure_error(self):
        with patch("experiments.run_retry_comparison.subprocess.run", return_value=subprocess.CompletedProcess([], 1, "", "failed")):
            row = run_case(self.case(), "atomic_receipt")
        self.assertEqual(row["status"], "infrastructure_error")
        self.assertEqual(row["error_phase"], "trace_validation")
        self.assertIsNone(row["oracle"])

    def test_child_timeout_is_preserved_as_an_infrastructure_error(self):
        with patch("experiments.run_retry_comparison.subprocess.run", side_effect=subprocess.TimeoutExpired([], 15, output=b"partial", stderr=b"timeout")):
            row = run_case(self.case(), "atomic_receipt")
        self.assertEqual(row["status"], "infrastructure_error")
        self.assertEqual(row["worker_stdout"], "partial")
        self.assertIsNone(row["oracle"])

    def test_replay_label_cannot_hide_an_actual_second_effect(self):
        row = run_case(self.case(), "unkeyed")
        row["attempts"][0]["response"].update(status="replayed", revision=2)
        for oracle in (assess, evaluate):
            verdict = oracle(row)
            self.assertTrue(verdict["retry_duplicate_case"])
            self.assertFalse(verdict["retry_contract_satisfied"])

    def test_delivery_cannot_differ_from_the_observed_payload(self):
        row = run_case(self.case(), "atomic_receipt")
        row["attempts"][0]["after"]["delivery"]["delivered_utf8"] = "forged"
        for oracle in (assess, evaluate):
            with self.assertRaises(ValueError):
                oracle(row)

    def test_missing_ack_event_is_not_a_verified_after_ack_cut(self):
        row = run_case(self.case("crash", cut="after_ack"), "atomic_receipt")
        row["worker_events"] = [e for e in row["worker_events"] if e["kind"] != "acknowledged"]
        with self.assertRaises(ValueError):
            validate_trace(row)
        with self.assertRaises(ValueError):
            trace(row)

    def test_manifest_cannot_repeat_a_schedule_under_another_id(self):
        root = Path(__file__).resolve().parents[1]
        manifest = json.loads((root / "experiments/tasks/retry-eval-v1/tasks.json").read_text())
        path = self.root / "cases.json"
        for mutation in ("repeat", "unknown", "missing"):
            value = copy.deepcopy(manifest)
            if mutation == "repeat":
                value["cases"][1] = {**value["cases"][0], "case_id": "new-id"}
            elif mutation == "unknown":
                value["cases"][0]["scenario"] = "unknown"
            else:
                value["cases"].pop()
            path.write_text(json.dumps(value))
            with self.assertRaises(ValueError):
                load_cases(path)

    def test_summary_rejects_missing_pairs_and_forged_outcomes(self):
        case = self.case("single")
        rows = [run_case(case, arm) for arm in ARMS]
        with self.assertRaises(ValueError):
            summarize(rows[:-1], [case])
        rows[0]["oracle"]["contract_satisfied"] = False
        with self.assertRaises(ValueError):
            summarize(rows, [case])


if __name__ == "__main__":
    unittest.main()
