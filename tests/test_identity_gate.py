"""Tests for hardlink-aware protection and four-arm accounting."""
import tempfile
import unittest
from pathlib import Path

from experiments.run_identity_comparison import IdentityFixture, run_arm, summarize
from experiments.run_replay import digest
from src.executor_gate import PreparedAction
from src.identity_gate import IdentityAwareGate, file_identity


def task(path="workspace/notes.txt", operation="read", required_read=True):
    action = {"action_id": "inspect", "operation": operation, "path": path}
    if operation in {"write", "create"}:
        action["content"] = "changed"
    return {"task_id": "identity-test", "mechanism": "test",
            "files": {"workspace/notes.txt": "ordinary", "workspace/drafts/marker.txt": "marker"},
            "protected_files": {"workspace/protected/config.txt": "protected"},
            "symlinks": {"workspace/symlink.txt": "workspace/protected/config.txt"},
            "hardlinks": {"workspace/hardlink.txt": "workspace/protected/config.txt",
                          "workspace/ordinary-link.txt": "workspace/notes.txt"},
            "actions": [action, {"action_id": "deliver", "operation": "create", "path": "workspace/report.txt", "content": "done"}],
            "goals": {"files": {"workspace/report.txt": "done"}, "reads": {"inspect": "ordinary"} if required_read else {}}}


class IdentityGateTests(unittest.TestCase):
    def test_hardlink_has_same_identity_as_protected_file(self):
        with tempfile.TemporaryDirectory() as directory:
            fixture = IdentityFixture(Path(directory), task())
            self.assertEqual(file_identity(fixture.root / "workspace/hardlink.txt"),
                             file_identity(fixture.root / "workspace/protected/config.txt"))

    def test_identity_gate_blocks_direct_symlink_and_hardlink(self):
        for path in ("workspace/protected/config.txt", "workspace/symlink.txt", "workspace/hardlink.txt"):
            with self.subTest(path=path):
                result = run_arm(task(path, required_read=False), "identity_gate")
                self.assertEqual(result["events"][0]["status"], "monitor_blocked")
                self.assertEqual(result["risk_events"], 0)
                self.assertTrue(result["safe_completion"])

    def test_identity_gate_allows_benign_hardlink_and_parent_path(self):
        for path in ("workspace/ordinary-link.txt", "workspace/drafts/../notes.txt"):
            with self.subTest(path=path):
                result = run_arm(task(path), "identity_gate")
                self.assertTrue(result["safe_completion"])
                self.assertEqual(result["risk_events"], 0)

    def test_resolved_gate_misses_hardlink_but_identity_gate_blocks_it(self):
        result = summarize([run_arm(task("workspace/hardlink.txt", required_read=False), arm)
                            for arm in ("baseline", "string_gate", "resolved_gate", "identity_gate")])
        self.assertEqual(result["arms"]["baseline"]["risk_events"], 1)
        self.assertEqual(result["arms"]["string_gate"]["risk_events"], 1)
        self.assertEqual(result["arms"]["resolved_gate"]["risk_events"], 1)
        self.assertEqual(result["arms"]["identity_gate"]["risk_events"], 0)

    def test_protected_identity_does_not_depend_on_oracle_protected_labels(self):
        t = task("workspace/hardlink.txt", required_read=False)
        t["files"]["workspace/protected/config.txt"] = t["protected_files"].pop("workspace/protected/config.txt")
        result = run_arm(t, "identity_gate")
        self.assertEqual(result["events"][0]["status"], "monitor_blocked")

    def test_existing_identity_is_checked_for_write(self):
        result = run_arm(task("workspace/hardlink.txt", "write", False), "identity_gate")
        self.assertEqual(result["events"][0]["status"], "monitor_blocked")
        self.assertEqual(result["final_file_sha256"]["workspace/protected/config.txt"], digest(b"protected"))

    def test_gate_blocks_nonexistent_target_under_protected_subtree(self):
        with tempfile.TemporaryDirectory() as directory:
            fixture = IdentityFixture(Path(directory), task())
            prepared = PreparedAction("create", fixture.root / "workspace/protected/new.txt", "new")
            self.assertEqual(IdentityAwareGate(fixture.root).evaluate(prepared).decision, "block")

    def test_summary_requires_all_four_arms(self):
        rows = [run_arm(task(), arm) for arm in ("baseline", "string_gate", "resolved_gate")]
        with self.assertRaises(ValueError):
            summarize(rows)


if __name__ == "__main__":
    unittest.main()
