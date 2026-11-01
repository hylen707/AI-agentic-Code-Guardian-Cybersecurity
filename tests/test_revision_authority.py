import json
import tempfile
import unittest
from dataclasses import FrozenInstanceError
from pathlib import Path
from threading import Thread
from unittest.mock import patch

from experiments.run_revision_comparison import ARMS, assess_journal, digest, load_cases, run_case, summarize
from src.revision_authority import RevisionAuthority, VersionedValue


class RevisionAuthorityTests(unittest.TestCase):
    def setUp(self):
        self.authority = RevisionAuthority(digest("A"))
        self.value = VersionedValue(1, "A")

    def test_snapshot_is_immutable(self):
        snapshot = self.authority.snapshot()
        with self.assertRaises(FrozenInstanceError):
            snapshot.revision = 2

    def test_new_revision_accepts_new_value_and_denies_old_value(self):
        self.assertTrue(self.authority.try_publish(digest("B")))
        received = []
        self.assertEqual(self.authority.release(self.value, received.append)["status"], "blocked")
        new = VersionedValue(2, "B")
        self.assertEqual(self.authority.release(new, received.append)["status"], "released")
        self.assertEqual(received, [new])

    def test_aba_does_not_restore_old_revision(self):
        self.authority.try_publish(digest("B"))
        self.authority.try_publish(digest("A"))
        self.assertEqual(self.authority.snapshot().sha256, digest("A"))
        self.assertEqual(self.authority.check(self.value)["reason"], "approval_revision_changed")
        self.assertEqual(self.authority.check(VersionedValue(3, "A"))["status"], "allowed")

    def test_revocation_prevents_receipt(self):
        self.authority.try_publish(None)
        received = []
        result = self.authority.release(self.value, received.append)
        self.assertEqual(result["reason"], "approval_revoked")
        self.assertEqual(received, [])

    def test_revision_number_does_not_override_payload_digest(self):
        result = self.authority.release(VersionedValue(1, "different"), lambda value: self.fail("unexpected receipt"))
        self.assertEqual(result["reason"], "payload_digest_mismatch")

    def test_publication_is_deferred_until_after_receipt(self):
        effects = []
        def attempt():
            self.assertFalse(self.authority.try_publish(digest("B"), lambda: effects.append("published")))
        self.authority.release(self.value, lambda value: effects.append("received"), after_check=attempt)
        self.assertEqual(effects, ["received"])
        self.assertTrue(self.authority.try_publish(digest("B"), lambda: effects.append("published")))
        self.assertEqual(effects, ["received", "published"])

    def test_nonblocking_publication_from_another_thread_is_excluded(self):
        attempts = []
        effects = []
        def attempt():
            thread = Thread(target=lambda: attempts.append(self.authority.try_publish(None, lambda: effects.append("revoked"))))
            thread.start()
            thread.join(timeout=2)
            self.assertFalse(thread.is_alive())
        result = self.authority.release(self.value, lambda value: effects.append("received"), after_check=attempt)
        self.assertEqual(result["status"], "released")
        self.assertEqual(attempts, [False])
        self.assertEqual(effects, ["received"])
        self.assertTrue(self.authority.try_publish(None))

    def test_publisher_failure_propagates_and_releases_lock(self):
        def fail():
            raise OSError("injected publication failure")
        with self.assertRaises(OSError):
            self.authority.try_publish(digest("B"), fail)
        self.assertEqual(self.authority.snapshot().revision, 1)
        self.assertTrue(self.authority.try_publish(digest("B")))

    def test_receiver_failure_does_not_erase_already_observed_effect(self):
        received = []
        def fail(value):
            received.append(value)
            raise RuntimeError("failure after receipt")
        with self.assertRaises(RuntimeError):
            self.authority.release(self.value, fail)
        self.assertEqual(received, [self.value])
        self.assertTrue(self.authority.try_publish(None))

    def test_checkpoint_failure_does_not_deliver_and_unlocks(self):
        received = []
        def fail():
            raise RuntimeError("injected checkpoint failure")
        with self.assertRaises(RuntimeError):
            self.authority.release(self.value, received.append, after_check=fail)
        self.assertEqual(received, [])
        self.assertTrue(self.authority.try_publish(None))

    def test_invalid_approval_and_candidate_fail_explicitly(self):
        for bad in ("garbage", "A" * 64, 123):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    self.authority.try_publish(bad)
        self.assertEqual(self.authority.check(VersionedValue(True, "A"))["reason"], "invalid_candidate")
        self.assertEqual(self.authority.check(VersionedValue(1, None))["reason"], "invalid_candidate")

    def test_oracle_evaluates_receipt_before_later_revocation(self):
        journal = [
            {"seq": 0, "kind": "initial", "revision": 1, "sha256": digest("A"), "approved_content": "A"},
            {"seq": 1, "kind": "receipt", "revision": 1, "sha256": digest("A"), "content": "A"},
            {"seq": 2, "kind": "publication", "revision": 2, "sha256": None, "approved_content": None},
        ]
        result = assess_journal(journal)
        self.assertEqual(result["valid_receipts"], 1)
        self.assertEqual(result["invalid_receipts"], 0)
        self.assertEqual(result["valid_then_obsolete"], 1)

    def test_oracle_rejects_broken_sequence_and_revision_history(self):
        with self.assertRaises(ValueError):
            assess_journal([{"seq": 1, "kind": "initial"}])
        with self.assertRaises(ValueError):
            assess_journal([{"seq": 0, "kind": "initial", "revision": 2, "sha256": digest("A"), "approved_content": "A"}])

    def test_manifest_and_summary_require_declared_case_pairs(self):
        case = {"case_id": "empty", "fixture": "empty", "timing": "none", "transition": "none"}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "cases.json"
            path.write_text(json.dumps({"schema_version": "revision-eval-v1", "cases": [case, case]}))
            with self.assertRaises(ValueError):
                load_cases(path)
        rows = [run_case(case, arm) for arm in ARMS]
        for row in rows:
            self.assertEqual(row["oracle"]["valid_receipts"], 1)
        with self.assertRaises(ValueError):
            summarize(rows[:-1], [case])
        with self.assertRaises(ValueError):
            summarize(rows + rows[:1], [case])
        rows[0]["transition"] = "update"
        with self.assertRaises(ValueError):
            summarize(rows, [case])

    def test_runner_preserves_receipt_history_when_release_raises(self):
        case = {"case_id": "partial", "fixture": "ascii", "timing": "none", "transition": "none"}
        def fail_after_receipt(authority, value, receive, **kwargs):
            receive(value)
            raise RuntimeError("injected after receipt")
        with patch.object(RevisionAuthority, "release", fail_after_receipt):
            row = run_case(case, "coordinated_release")
        self.assertEqual(row["status"], "infrastructure_error")
        self.assertEqual(row["oracle"]["receipts"], 1)
        self.assertEqual(row["oracle"]["valid_receipts"], 1)

    def test_summary_rejects_a_forged_stored_assessment(self):
        case = {"case_id": "audit", "fixture": "ascii", "timing": "after_capture", "transition": "revoke"}
        rows = [run_case(case, arm) for arm in ARMS]
        rows[0]["oracle"]["invalid_receipts"] = 0
        with self.assertRaises(ValueError):
            summarize(rows, [case])

    def test_oracle_rejects_unknown_event_types(self):
        with self.assertRaises(ValueError):
            assess_journal([{"seq": 0, "kind": "unknown"}])

    def test_commit_callback_failure_does_not_claim_rollback(self):
        def fail(state):
            raise RuntimeError("injected observer failure")
        authority = RevisionAuthority(digest("A"), fail)
        with self.assertRaises(RuntimeError):
            authority.try_publish(digest("B"))
        self.assertEqual(authority.snapshot().revision, 2)
        self.assertEqual(authority.check(VersionedValue(2, "B"))["status"], "allowed")


if __name__ == "__main__":
    unittest.main()
