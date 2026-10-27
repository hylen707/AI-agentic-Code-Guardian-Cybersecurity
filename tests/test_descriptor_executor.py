import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from experiments.run_race_comparison import ARMS, load_cases, run_case, summarize
from src.descriptor_executor import DescriptorExecutor, content_io
from src.executor_gate import PreparedAction


class DescriptorExecutorTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.protected = self.root / "workspace/protected/secret.txt"
        self.protected.parent.mkdir(parents=True)
        self.protected.write_text("synthetic secret")
        self.ordinary = self.root / "workspace/note.txt"
        self.ordinary.write_text("ordinary")
        self.executor = DescriptorExecutor(self.root)

    def test_denied_write_does_not_truncate_and_closes_descriptor(self):
        alias = self.root / "workspace/alias.txt"
        alias.hardlink_to(self.protected)
        opened = []
        result = self.executor.execute(PreparedAction("write", alias, "changed"), on_open=opened.append)
        self.assertEqual(result["status"], "blocked")
        self.assertEqual(self.protected.read_text(), "synthetic secret")
        with self.assertRaises(OSError):
            os.fstat(opened[0])

    def test_post_authorization_parent_swap_keeps_original(self):
        case = {"case_id": "parent", "operation": "write", "timing": "after_check", "replacement": "protected_parent"}
        bound = run_case(case, "descriptor_bound")
        path = run_case(case, "identity_path")
        self.assertTrue(bound["original_completion"])
        self.assertFalse(bound["protected_changed"])
        self.assertTrue(path["protected_content_operation"])
        self.assertTrue(path["protected_changed"])

    def test_metadata_failure_cannot_allow_io_and_closes(self):
        opened = []
        with patch("src.descriptor_executor.os.fstat", side_effect=OSError("metadata unavailable")):
            with self.assertRaises(OSError):
                self.executor.execute(PreparedAction("write", self.ordinary, "changed"), on_open=opened.append)
        self.assertEqual(self.ordinary.read_text(), "ordinary")
        with self.assertRaises(OSError):
            os.fstat(opened[0])

    def test_hook_failure_closes_descriptor_without_io(self):
        opened = []
        def fail():
            raise RuntimeError("injected failure")
        with self.assertRaises(RuntimeError):
            self.executor.execute(PreparedAction("write", self.ordinary, "changed"),
                                  on_open=opened.append, after_check=fail)
        self.assertEqual(self.ordinary.read_text(), "ordinary")
        with self.assertRaises(OSError):
            os.fstat(opened[0])

    def test_unsupported_and_unprepared_requests_never_open(self):
        with patch("src.descriptor_executor.os.open") as opened:
            for action in (PreparedAction("create", self.ordinary, "x"),
                           PreparedAction("read", Path("workspace/note.txt")),
                           PreparedAction("read", self.root / "workspace/../outside"),
                           PreparedAction("write", self.ordinary, None),
                           PreparedAction("read", self.protected)):
                self.assertEqual(self.executor.execute(action)["status"], "blocked")
            opened.assert_not_called()

    def test_special_file_is_denied(self):
        fifo = self.root / "workspace/pipe"
        os.mkfifo(fifo)
        result = self.executor.execute(PreparedAction("read", fifo))
        self.assertEqual(result["reason"], "not_regular_file")

    def test_missing_protected_root_is_setup_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(ValueError):
                DescriptorExecutor(Path(directory))

    def test_short_writes_and_empty_write(self):
        fd = os.open(self.ordinary, os.O_WRONLY)
        real_write = os.write
        try:
            with patch("src.descriptor_executor.os.write", side_effect=lambda handle, data: real_write(handle, data[:2])):
                content_io(fd, "write", "longer text")
        finally:
            os.close(fd)
        self.assertEqual(self.ordinary.read_text(), "longer text")
        self.executor.execute(PreparedAction("write", self.ordinary, ""))
        self.assertEqual(self.ordinary.read_bytes(), b"")

    def test_successful_descriptor_is_closed(self):
        opened = []
        result = self.executor.execute(PreparedAction("read", self.ordinary), on_open=opened.append)
        self.assertEqual(result["content"], "ordinary")
        with self.assertRaises(OSError):
            os.fstat(opened[0])

    def test_manifest_and_missing_records_fail_explicitly(self):
        file = self.root / "manifest.json"
        case = {"case_id": "same", "operation": "read", "timing": "none", "replacement": "none"}
        file.write_text(json.dumps({"schema_version": "race-eval-v1", "cases": [case, case]}))
        with self.assertRaises(ValueError):
            load_cases(file)
        rows = [run_case(case, arm) for arm in ARMS]
        with self.assertRaises(ValueError):
            summarize(rows[:-1], [case])
        with self.assertRaises(ValueError):
            summarize(rows + rows[:1], [case])

    def test_oracle_preserves_io_attempt_on_execution_failure(self):
        case = {"case_id": "failure", "operation": "write", "timing": "after_check", "replacement": "protected_hardlink"}
        with patch("experiments.run_race_comparison.content_io", side_effect=OSError("injected")):
            row = run_case(case, "identity_path")
        self.assertEqual(row["status"], "infrastructure_error")
        self.assertTrue(row["protected_io_attempt"])
        self.assertFalse(row["protected_content_operation"])


if __name__ == "__main__":
    unittest.main()
