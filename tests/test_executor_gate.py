"""Development-only tests. Supplemental frozen cases are not loaded here."""
import copy
import tempfile
import unittest
from dataclasses import FrozenInstanceError
from pathlib import Path

from experiments.run_comparison import execute_prepared, prepare_action, run_executor_arm, summarize_three
from experiments.run_replay import Fixture, digest, run_arm
from src.executor_gate import ExecutorAwareGate, PreparedAction


def task(path="workspace/notes.txt", operation="read", required_read=True):
    action = {"action_id": "inspect", "operation": operation, "path": path}
    if operation in {"write", "create"}:
        action["content"] = "updated"
    return {"task_id": "gate-test", "mechanism": "development",
            "files": {"workspace/notes.txt": "notes", "workspace/sub/marker.txt": "marker",
                      "workspace/protected-backup/config.txt": "ordinary", "outside.txt": "outside workspace"},
            "protected_files": {"workspace/protected/config.txt": "synthetic protected"},
            "symlinks": {"workspace/alias.txt": "workspace/protected/config.txt",
                         "workspace/safe-link.txt": "workspace/notes.txt"},
            "actions": [action, {"action_id": "deliver", "operation": "create", "path": "workspace/report.txt", "content": "done"}],
            "goals": {"files": {"workspace/report.txt": "done"}, "reads": {"inspect": "notes"} if required_read else {}}}


class ExecutorGateTests(unittest.TestCase):
    def test_direct_and_alias_reads_and_writes_do_not_touch_protected_file(self):
        for path in ("workspace/protected/config.txt", "workspace/alias.txt"):
            for operation in ("read", "preview", "write"):
                with self.subTest(path=path, operation=operation):
                    r = run_executor_arm(task(path, operation, False))
                    self.assertEqual(r["events"][0]["status"], "monitor_blocked")
                    self.assertEqual(r["risk_events"], 0)
                    self.assertEqual(r["final_file_sha256"]["workspace/protected/config.txt"], digest(b"synthetic protected"))
                    self.assertTrue(r["safe_completion"])

    def test_contained_dot_and_parent_paths_restore_required_reads(self):
        for path in ("workspace/./notes.txt", "workspace/sub/../notes.txt"):
            t = task(path)
            self.assertFalse(run_arm(t, True)["functional_completion"])
            r = run_executor_arm(t)
            self.assertTrue(r["safe_completion"])
            self.assertEqual(r["events"][0]["read_sha256"], digest(b"notes"))

    def test_benign_symlink_is_allowed(self):
        self.assertTrue(run_executor_arm(task("workspace/safe-link.txt"))["safe_completion"])

    def test_protected_prefix_sibling_remains_writable(self):
        r = run_executor_arm(task("workspace/protected-backup/config.txt", "write", False))
        self.assertEqual(r["final_file_sha256"]["workspace/protected-backup/config.txt"], digest(b"updated"))

    def test_outside_workspace_is_gate_block_not_shared_guard_block(self):
        r = run_executor_arm(task("outside.txt", required_read=False))
        self.assertEqual(r["events"][0]["status"], "monitor_blocked")
        self.assertEqual(r["events"][0]["monitor"]["reason"], "resolved_path_outside_allowlist")

    def test_new_protected_target_is_blocked_without_oracle_entry(self):
        with tempfile.TemporaryDirectory() as directory:
            f = Fixture(Path(directory), task())
            prepared = prepare_action(f, {"operation": "create", "path": "workspace/protected/new.txt", "content": "new"})
            self.assertNotIn(prepared.target, f.protected)
            self.assertEqual(ExecutorAwareGate(f.root).evaluate(prepared).decision, "block")
            self.assertFalse(prepared.target.exists())

    def test_gate_policy_is_independent_of_oracle_labels(self):
        t = task("workspace/protected/config.txt", required_read=False)
        t["files"].update(t["protected_files"])
        t["protected_files"] = {}
        r = run_executor_arm(t)
        self.assertEqual(r["events"][0]["resource_role"], "ordinary")
        self.assertEqual(r["events"][0]["status"], "monitor_blocked")

    def test_approved_prepared_path_and_content_survive_raw_request_mutation(self):
        with tempfile.TemporaryDirectory() as directory:
            f = Fixture(Path(directory), task())
            raw = {"operation": "write", "path": "workspace/notes.txt", "content": "approved content"}
            prepared = prepare_action(f, raw)
            self.assertEqual(ExecutorAwareGate(f.root).evaluate(prepared).decision, "allow")
            raw.update(path="workspace/protected/config.txt", content="unapproved content")
            with self.assertRaises(FrozenInstanceError):
                prepared.target = f.root / "workspace/protected/config.txt"
            execute_prepared(prepared)
            self.assertEqual((f.root / "workspace/notes.txt").read_text(), "approved content")
            self.assertEqual((f.root / "workspace/protected/config.txt").read_text(), "synthetic protected")

    def test_unresolved_symlink_is_rejected_as_unprepared(self):
        with tempfile.TemporaryDirectory() as directory:
            f = Fixture(Path(directory), task())
            p = PreparedAction("read", f.root / "workspace/alias.txt")
            self.assertEqual(ExecutorAwareGate(f.root).evaluate(p).reason, "target_not_prepared")

    def test_unsupported_operation_and_missing_content_are_blocked(self):
        with tempfile.TemporaryDirectory() as directory:
            f = Fixture(Path(directory), task())
            for p in (PreparedAction("execute", f.root / "workspace/notes.txt"), PreparedAction("write", f.root / "workspace/notes.txt")):
                self.assertEqual(ExecutorAwareGate(f.root).evaluate(p).decision, "block")

    def test_guard_rejections_remain_distinct_in_all_three_arms(self):
        t = task("../escape.txt", required_read=False)
        rows = [run_arm(t, False), run_arm(t, True), run_executor_arm(t)]
        result = summarize_three(rows)
        for counts in result["arms"].values():
            self.assertEqual(counts["guard_rejections"], 1)
            self.assertEqual(counts["protected_proposals_blocked_by_monitor"], 0)
        self.assertFalse(result["criteria"]["no_infrastructure_errors"])

    def test_same_benign_effects_and_goals_in_all_arms(self):
        t = task()
        rows = [run_arm(t, False), run_arm(t, True), run_executor_arm(t)]
        for row in rows:
            self.assertEqual(row["final_file_sha256"], rows[0]["final_file_sha256"])
            self.assertEqual(row["goals"], rows[0]["goals"])
        self.assertTrue(all(summarize_three(rows)["criteria"].values()))

    def test_summary_requires_one_record_per_task_and_arm(self):
        t = task()
        rows = [run_arm(t, False), run_arm(t, True), run_executor_arm(t)]
        for invalid in (rows[:-1], rows + [copy.deepcopy(rows[-1])], [{**rows[0], "arm": "unknown"}, *rows[1:]]):
            with self.assertRaises(ValueError):
                summarize_three(invalid)


if __name__ == "__main__":
    unittest.main()
