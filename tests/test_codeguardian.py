import unittest

from src.codeguardian import CodeGuardian


class CodeGuardianTests(unittest.TestCase):
    def setUp(self):
        self.monitor = CodeGuardian()

    def test_allows_safe_read_inside_workspace(self):
        result = self.monitor.evaluate({"operation": "read", "path": "workspace/notes.txt"})
        self.assertEqual(result.decision, "allow")

    def test_allows_safe_create_inside_workspace(self):
        result = self.monitor.evaluate({"operation": "create", "path": "workspace/new.txt"})
        self.assertEqual(result.decision, "allow")

    def test_blocks_parent_directory_traversal(self):
        result = self.monitor.evaluate({"operation": "read", "path": "workspace/../secrets.txt"})
        self.assertEqual(result.decision, "block")
        self.assertEqual(result.reason, "path_traversal_or_invalid_path")

    def test_blocks_explicit_current_directory_component(self):
        # PurePosixPath normally collapses "."; check the raw components first.
        result = self.monitor.evaluate(
            {"operation": "read", "path": "workspace/./notes.txt"}
        )
        self.assertEqual(result.decision, "block")
        self.assertEqual(result.reason, "path_traversal_or_invalid_path")

    def test_blocks_current_directory_component_in_nested_path(self):
        result = self.monitor.evaluate(
            {"operation": "write", "path": "workspace/project/./draft.txt"}
        )
        self.assertEqual(result.decision, "block")
        self.assertEqual(result.reason, "path_traversal_or_invalid_path")

    def test_blocks_absolute_path(self):
        result = self.monitor.evaluate({"operation": "read", "path": "/etc/passwd"})
        self.assertEqual(result.decision, "block")
        self.assertEqual(result.reason, "absolute_paths_are_not_allowed")

    def test_blocks_protected_path(self):
        result = self.monitor.evaluate(
            {"operation": "write", "path": "workspace/protected/config.txt"}
        )
        self.assertEqual(result.decision, "block")
        self.assertEqual(result.reason, "protected_path")

    def test_blocks_unknown_operation(self):
        result = self.monitor.evaluate(
            {"operation": "execute", "path": "workspace/script.py"}
        )
        self.assertEqual(result.decision, "block")
        self.assertEqual(result.reason, "operation_not_allowlisted")

    def test_blocks_path_outside_allowlist(self):
        result = self.monitor.evaluate({"operation": "read", "path": "downloads/file.txt"})
        self.assertEqual(result.decision, "block")
        self.assertEqual(result.reason, "path_outside_allowlist")

    def test_blocks_non_object_input(self):
        result = self.monitor.evaluate(["read", "workspace/file.txt"])
        self.assertEqual(result.decision, "block")
        self.assertEqual(result.reason, "action_must_be_an_object")

    def test_blocks_missing_path(self):
        result = self.monitor.evaluate({"operation": "read"})
        self.assertEqual(result.decision, "block")
        self.assertEqual(result.reason, "path_must_be_a_nonempty_string")


if __name__ == "__main__":
    unittest.main()
