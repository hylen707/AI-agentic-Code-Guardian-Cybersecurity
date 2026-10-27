import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from experiments.run_content_comparison import ARMS, digest, inspect_descriptor, load_cases, run_case, summarize
from src.executor_gate import PreparedAction
from src.verified_content_reader import VerifiedContentReader


class VerifiedContentReaderTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.protected = self.root / "workspace/protected/sentinel.txt"
        self.protected.parent.mkdir(parents=True)
        self.protected.write_text("synthetic protected data", encoding="utf-8")
        self.target = self.root / "workspace/document.txt"
        self.target.write_bytes(b"approved=true\n")
        self.expected = digest(self.target.read_bytes())
        self.reader = VerifiedContentReader(self.root, {self.target: self.expected})
        self.action = PreparedAction("read", self.target)

    def test_returns_checked_value_after_live_content_changes(self):
        result = self.reader.read(self.action, after_validation=lambda: self.target.write_bytes(b"approved=oops\n"))
        self.assertEqual(result["content"], "approved=true\n")
        self.assertNotEqual(result["content"].encode(), self.target.read_bytes())
        self.assertEqual(result["inspected_sha256"], self.expected)

    def test_pre_capture_mismatch_releases_no_payload(self):
        inspected = []
        result = self.reader.read(self.action,
                                  after_identity_check=lambda: self.target.write_bytes(b"changed"),
                                  on_validation=lambda h, n: inspected.append((h, n)))
        self.assertEqual(result["status"], "blocked")
        self.assertNotIn("content", result)
        self.assertEqual(inspected, [(digest(b"changed"), 7)])

    def test_unicode_and_empty_values_are_valid_deliveries(self):
        for value in ("approved=안전 ✓\n", ""):
            with self.subTest(value=value):
                self.target.write_bytes(value.encode())
                reader = VerifiedContentReader(self.root, {self.target: digest(value.encode())})
                result = reader.read(self.action)
                self.assertEqual(result["status"], "executed")
                self.assertEqual(result["content"], value)

    def test_configuration_is_copied_and_read_only(self):
        policy = {self.target: self.expected}
        reader = VerifiedContentReader(self.root, policy)
        policy[self.target] = digest(b"changed")
        self.assertEqual(reader.read(self.action)["status"], "executed")
        with self.assertRaises(TypeError):
            reader.approved_sha256[self.target] = digest(b"changed")
        with self.assertRaises(ValueError):
            VerifiedContentReader(self.root, {self.target: "not-a-digest"})
        with self.assertRaises(ValueError):
            VerifiedContentReader(self.root, {Path("relative.txt"): self.expected})

    def test_unknown_version_and_write_do_not_open_target(self):
        with patch("src.descriptor_executor.os.open") as opened:
            result = self.reader.read(PreparedAction("read", self.root / "workspace/unknown.txt"))
            self.assertEqual(result["reason"], "no_trusted_content_version")
            result = self.reader.read(PreparedAction("write", self.target, "overwrite"))
            self.assertEqual(result["reason"], "read_only_interface")
            opened.assert_not_called()

    def test_content_digest_does_not_override_protected_identity(self):
        alias = self.root / "workspace/alias.txt"
        alias.hardlink_to(self.protected)
        reader = VerifiedContentReader(self.root, {alias: digest(self.protected.read_bytes())})
        inspected = []
        result = reader.read(PreparedAction("read", alias), on_validation=lambda h, n: inspected.append(h))
        self.assertEqual(result["reason"], "protected_descriptor_identity")
        self.assertEqual(inspected, [])
        self.assertNotIn("content", result)

    def test_invalid_utf8_is_error_not_policy_success(self):
        self.target.write_bytes(b"\xff")
        with self.assertRaises(UnicodeDecodeError):
            self.reader.read(self.action)

    def test_hook_failure_propagates_and_descriptor_is_closed(self):
        opened = []
        def fail():
            raise RuntimeError("injected checkpoint failure")
        with self.assertRaises(RuntimeError):
            self.reader.read(self.action, on_open=opened.append, after_validation=fail)
        with self.assertRaises(OSError):
            os.fstat(opened[0])

    def test_reread_gap_is_observed_on_the_same_inode(self):
        case = {"case_id": "counterexample", "fixture": "ascii", "timing": "after_validation", "mutation": "overwrite"}
        naive = run_case(case, "hash_then_reread")
        captured = run_case(case, "verified_buffer")
        self.assertTrue(naive["identity_continuity"])
        self.assertEqual(naive["inspected_sha256"], naive["approved_sha256"])
        self.assertTrue(naive["unapproved_delivery"])
        self.assertTrue(captured["approved_but_stale"])
        self.assertFalse(captured["unapproved_delivery"])

    def test_pread_inspection_handles_short_reads_without_moving_offset(self):
        fd = os.open(self.target, os.O_RDONLY)
        real_pread = os.pread
        try:
            os.lseek(fd, 4, os.SEEK_SET)
            with patch("experiments.run_content_comparison.os.pread", side_effect=lambda f, n, offset: real_pread(f, min(n, 2), offset)):
                self.assertEqual(inspect_descriptor(fd), self.target.read_bytes())
            self.assertEqual(os.lseek(fd, 0, os.SEEK_CUR), 4)
        finally:
            os.close(fd)

    def test_manifest_and_record_integrity_checks(self):
        case = {"case_id": "control", "fixture": "empty", "timing": "none", "mutation": "none"}
        path = self.root / "manifest.json"
        path.write_text(json.dumps({"schema_version": "content-eval-v1", "cases": [case, case]}))
        with self.assertRaises(ValueError):
            load_cases(path)
        rows = [run_case(case, arm) for arm in ARMS]
        for row in rows:
            self.assertEqual(row["status"], "delivered")
            self.assertTrue(row["approved_delivery"])
            self.assertEqual(row["delivered_bytes"], 0)
        with self.assertRaises(ValueError):
            summarize(rows[:-1], [case])
        with self.assertRaises(ValueError):
            summarize(rows + rows[:1], [case])
        rows[0]["fixture"] = "ascii"
        with self.assertRaises(ValueError):
            summarize(rows, [case])

    def test_read_error_remains_error_and_oracle_preserves_final_state(self):
        case = {"case_id": "read-error", "fixture": "ascii", "timing": "before_capture", "mutation": "overwrite"}
        with patch("experiments.run_content_comparison.inspect_descriptor", side_effect=OSError("injected read failure")):
            row = run_case(case, "hash_then_reread")
        self.assertEqual(row["status"], "infrastructure_error")
        self.assertEqual(row["final_sha256"], digest(b"approved=oops\n"))
        self.assertIsNone(row["delivered_sha256"])
        self.assertFalse(row["approved_delivery"])


if __name__ == "__main__":
    unittest.main()
