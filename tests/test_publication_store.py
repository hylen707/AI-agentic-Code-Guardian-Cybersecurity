import copy
import hashlib
import json
import sqlite3
import subprocess
import tempfile
import unittest
from dataclasses import FrozenInstanceError
from pathlib import Path
from unittest.mock import patch

from experiments.run_recovery_comparison import ARMS, assess_recovery, load_cases, run_case, summarize, validate_worker_trace
from experiments.verify_recovery_results import evaluate, verify_trace
from src.publication_store import SQLitePublicationStore, SplitPublicationStore, StoredApproval, digest, recover_value, replace_file


class PublicationStoreTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix="codeguardian-publication-test-")
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)

    @staticmethod
    def fail(stage):
        if stage == "after_stage":
            raise RuntimeError("injected before commit")

    def test_approval_is_immutable_and_rejects_invalid_types(self):
        state = StoredApproval(1, digest(b"A"), b"A")
        with self.assertRaises(FrozenInstanceError):
            state.revision = 2
        for args in ((True, digest(b"A"), b"A"), (0, None, b""), (1, "invalid", b"A"), (1, None, "text")):
            with self.subTest(args=args), self.assertRaises(ValueError):
                StoredApproval(*args)

    def test_empty_and_unicode_are_actual_deliveries(self):
        for content in (b"", "안전 ✓".encode("utf-8")):
            with self.subTest(content=content):
                result = recover_value(StoredApproval(1, digest(content), content))
                self.assertEqual(result["status"], "delivered")
                self.assertEqual(result["content"], content)

    def test_mismatch_denies_without_a_payload(self):
        state = StoredApproval(1, digest(b"A"), b"B")
        self.assertEqual(recover_value(state)["reason"], "recovered_digest_mismatch")
        self.assertIsNone(recover_value(state)["content"])
        self.assertEqual(recover_value(state, verify=False)["content"], b"B")

    def test_revocation_denies_even_unchecked_recovery(self):
        state = StoredApproval(2, None, b"A")
        for verify in (True, False):
            self.assertEqual(recover_value(state, verify=verify)["reason"], "approval_revoked")
            self.assertIsNone(recover_value(state, verify=verify)["content"])

    def test_split_state_survives_new_instance(self):
        SplitPublicationStore(self.root).initialize(b"A")
        self.assertEqual(SplitPublicationStore(self.root).snapshot(), StoredApproval(1, digest(b"A"), b"A"))

    def test_split_update_then_revoke_has_monotonic_revisions(self):
        store = SplitPublicationStore(self.root)
        store.initialize(b"A")
        store.publish(b"B")
        revoked = store.publish(None)
        self.assertEqual(revoked, StoredApproval(3, None, b"B"))
        self.assertEqual(SplitPublicationStore(self.root).snapshot(), revoked)

    def test_split_after_stage_exception_leaves_incoherent_pair(self):
        store = SplitPublicationStore(self.root)
        store.initialize(b"A")
        with self.assertRaises(RuntimeError):
            store.publish(b"B", checkpoint=self.fail)
        state = SplitPublicationStore(self.root).snapshot()
        self.assertEqual(state, StoredApproval(1, digest(b"A"), b"B"))
        self.assertEqual(recover_value(state)["status"], "blocked")

    def test_split_metadata_failure_is_not_a_successful_publish(self):
        store = SplitPublicationStore(self.root)
        store.initialize(b"A")
        with patch.object(store, "_write_approval", side_effect=OSError("injected write failure")):
            with self.assertRaises(OSError):
                store.publish(b"B")
        self.assertEqual(store.snapshot().revision, 1)
        self.assertEqual(store.snapshot().content, b"B")

    def test_failed_individual_replace_retains_existing_file(self):
        path = self.root / "one-file"
        path.write_bytes(b"A")
        with patch("src.publication_store.os.replace", side_effect=OSError("injected replacement failure")):
            with self.assertRaises(OSError):
                replace_file(path, b"B")
        self.assertEqual(path.read_bytes(), b"A")
        self.assertEqual(sorted(p.name for p in self.root.iterdir()), ["one-file"])

    def test_reinitialization_cannot_erase_an_existing_store(self):
        for cls in (SplitPublicationStore, SQLitePublicationStore):
            with self.subTest(store=cls.__name__):
                store = cls(self.root / cls.__name__)
                store.initialize(b"A")
                with self.assertRaises(FileExistsError):
                    store.initialize(b"B")
                self.assertEqual(store.snapshot().content, b"A")

    def test_missing_store_is_an_error_not_empty_approved_content(self):
        with self.assertRaises(FileNotFoundError):
            SplitPublicationStore(self.root).snapshot()
        with self.assertRaises(sqlite3.OperationalError):
            SQLitePublicationStore(self.root).snapshot()
        self.assertFalse((self.root / "publication.sqlite3").exists())

    def test_split_malformed_metadata_is_not_a_policy_denial(self):
        store = SplitPublicationStore(self.root)
        store.initialize(b"A")
        for text in ('{', '{}', '{"revision":true,"approved_sha256":null}'):
            store.approval.write_text(text)
            with self.assertRaises(ValueError):
                store.snapshot()

    def test_sqlite_required_settings_and_state_are_checked(self):
        store = SQLitePublicationStore(self.root)
        store.initialize(b"")
        self.assertEqual(store.settings(), {"journal_mode": "delete", "synchronous": 2, "integrity_check": "ok"})
        self.assertEqual(store.snapshot(), StoredApproval(1, digest(b""), b""))

    def test_sqlite_update_and_revocation_are_persisted_together(self):
        store = SQLitePublicationStore(self.root)
        store.initialize(b"A")
        store.publish(b"B")
        self.assertEqual(SQLitePublicationStore(self.root).snapshot(), StoredApproval(2, digest(b"B"), b"B"))
        store.publish(None)
        self.assertEqual(SQLitePublicationStore(self.root).snapshot(), StoredApproval(3, None, b"B"))

    def test_sqlite_after_stage_exception_rolls_back_without_relabeling(self):
        store = SQLitePublicationStore(self.root)
        store.initialize(b"A")
        with self.assertRaises(RuntimeError):
            store.publish(b"B", checkpoint=self.fail)
        self.assertEqual(SQLitePublicationStore(self.root).snapshot(), StoredApproval(1, digest(b"A"), b"A"))

    def test_sqlite_after_commit_exception_does_not_imply_rollback(self):
        store = SQLitePublicationStore(self.root)
        store.initialize(b"A")
        def fail(stage):
            if stage == "after_commit":
                raise RuntimeError("injected after commit")
        with self.assertRaises(RuntimeError):
            store.publish(b"B", checkpoint=fail)
        self.assertEqual(SQLitePublicationStore(self.root).snapshot(), StoredApproval(2, digest(b"B"), b"B"))

    def test_sqlite_payload_corruption_is_not_authorized_by_revision_alone(self):
        store = SQLitePublicationStore(self.root)
        store.initialize(b"A")
        with sqlite3.connect(store.database) as connection:
            connection.execute("UPDATE publication SET content=? WHERE id=1", (b"B",))
        recovered = recover_value(SQLitePublicationStore(self.root).snapshot())
        self.assertEqual(recovered["reason"], "recovered_digest_mismatch")
        self.assertIsNone(recovered["content"])

    def test_sqlite_missing_row_is_an_explicit_error(self):
        store = SQLitePublicationStore(self.root)
        store.initialize(b"A")
        with sqlite3.connect(store.database) as connection:
            connection.execute("DELETE FROM publication")
        with self.assertRaises(ValueError):
            store.snapshot()

    def test_actual_child_exit_exposes_the_split_update_gap(self):
        case = {"case_id": "gap", "fixture": "ascii", "transition": "update", "cut": "after_stage"}
        row = run_case(case, "split_unchecked")
        self.assertEqual(row["status"], "complete")
        self.assertEqual(row["worker_returncode"], 73)
        self.assertTrue(row["oracle"]["invalid_delivery"])
        self.assertFalse(row["oracle"]["state_coherent"])
        self.assertEqual(evaluate(row), row["oracle"])
        verify_trace(row)

    def test_verified_denial_and_transactional_recovery_differ_in_availability(self):
        case = {"case_id": "gap", "fixture": "empty", "transition": "update", "cut": "after_stage"}
        verified, atomic = (run_case(case, arm) for arm in ("split_verified", "sqlite_atomic"))
        self.assertEqual(verified["status"], "complete")
        self.assertEqual(atomic["status"], "complete")
        self.assertEqual(verified["recovery"]["reason"], "recovered_digest_mismatch")
        self.assertEqual(atomic["recovery"]["delivered_utf8"], "")
        self.assertTrue(atomic["oracle"]["state_coherent"])

    def test_acknowledged_revocation_survives_actual_child_exit(self):
        case = {"case_id": "revoke", "fixture": "ascii", "transition": "revoke", "cut": "after_ack"}
        row = run_case(case, "sqlite_atomic")
        self.assertEqual(row["status"], "complete")
        self.assertTrue(row["oracle"]["acknowledged_recovered"])
        self.assertTrue(row["oracle"]["revocation_denied"])

    def test_an_unrelated_process_failure_is_an_infrastructure_error(self):
        case = {"case_id": "failed", "fixture": "ascii", "transition": "update", "cut": "after_stage"}
        with patch("experiments.run_recovery_comparison.subprocess.run",
                   return_value=subprocess.CompletedProcess([], 1, "", "worker failed")):
            row = run_case(case, "split_verified")
        self.assertEqual(row["status"], "infrastructure_error")
        self.assertEqual(row["error_phase"], "trace_validation")
        self.assertIsNone(row["oracle"])
        self.assertIsNone(row["recovery"])

    def test_exit_code_without_checkpoint_coverage_is_rejected(self):
        case = {"case_id": "partial", "fixture": "ascii", "transition": "update", "cut": "after_stage"}
        with self.assertRaises(ValueError):
            validate_worker_trace(case, 73, [{"seq": 0, "kind": "checkpoint", "stage": "before_publish"}])

    def test_manifest_rejects_unknown_and_repeated_semantic_cases(self):
        case = {"case_id": "one", "fixture": "ascii", "transition": "none", "cut": "none"}
        path = self.root / "cases.json"
        for cases in ([case, {**case, "case_id": "two"}], [{**case, "cut": "after_ack"}], [{**case, "fixture": "unknown"}]):
            path.write_text(json.dumps({"schema_version": "recovery-eval-v1", "cases": cases}))
            with self.assertRaises(ValueError):
                load_cases(path)

    def test_summary_rejects_missing_pairs_or_forged_assessment(self):
        case = {"case_id": "control", "fixture": "empty", "transition": "none", "cut": "none"}
        rows = [run_case(case, arm) for arm in ARMS]
        for row in rows:
            self.assertEqual(row["status"], "complete")
        with self.assertRaises(ValueError):
            summarize(rows[:-1], [case])
        with self.assertRaises(ValueError):
            summarize(rows + rows[:1], [case])
        rows[0]["oracle"]["valid_delivery"] = False
        with self.assertRaises(ValueError):
            summarize(rows, [case])

    def test_oracles_reject_a_delivery_different_from_the_observed_capture(self):
        case = {"case_id": "fake", "fixture": "ascii", "transition": "none", "cut": "none"}
        payload = "approved=version-a\n"
        row = {**case, "observed_state": {"revision": 1, "approved_sha256": digest(payload.encode()),
                                         "content_utf8": payload, "content_sha256": digest(payload.encode())},
               "recovery": {"status": "delivered", "reason": "verified_recovery", "revision": 1,
                            "delivered_utf8": "different"}}
        for oracle in (assess_recovery, evaluate):
            with self.assertRaises(ValueError):
                oracle(row)


if __name__ == "__main__":
    unittest.main()
