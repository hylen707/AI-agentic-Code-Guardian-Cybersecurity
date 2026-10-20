"""CodeGuardian: classify proposed synthetic actions without executing them.

This first version is a policy checker, not a sandbox and not an integration with
an AI agent. It reads JSON action records from stdin and emits JSON decisions.
It never opens, reads, writes, or executes the target paths/operations.
"""
from __future__ import annotations

import json
import sys
from dataclasses import asdict, dataclass
from pathlib import PurePosixPath
from typing import Any


ALLOWED_OPERATIONS = {"read", "write", "create", "preview"}
DEFAULT_ALLOWED_PREFIXES = ("workspace/",)
DEFAULT_PROTECTED_PREFIXES = ("workspace/protected/",)


@dataclass(frozen=True)
class Decision:
    decision: str
    reason: str
    operation: str | None
    path: str | None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class CodeGuardian:
    """Deterministic allow/block policy for synthetic action proposals."""

    def __init__(
        self,
        allowed_prefixes: tuple[str, ...] = DEFAULT_ALLOWED_PREFIXES,
        protected_prefixes: tuple[str, ...] = DEFAULT_PROTECTED_PREFIXES,
    ) -> None:
        self.allowed_prefixes = tuple(self._clean_prefix(p) for p in allowed_prefixes)
        self.protected_prefixes = tuple(self._clean_prefix(p) for p in protected_prefixes)

    @staticmethod
    def _clean_prefix(prefix: str) -> str:
        return prefix.strip("/")

    @staticmethod
    def _blocked(reason: str, operation: str | None, path: str | None) -> Decision:
        return Decision("block", reason, operation, path)

    def evaluate(self, action: Any) -> Decision:
        """Classify an untrusted action dictionary; do not perform the action."""
        if not isinstance(action, dict):
            return self._blocked("action_must_be_an_object", None, None)

        operation = action.get("operation")
        raw_path = action.get("path")

        if not isinstance(operation, str):
            return self._blocked("operation_must_be_a_string", None, None)
        operation = operation.strip().lower()

        if not isinstance(raw_path, str) or not raw_path.strip():
            return self._blocked("path_must_be_a_nonempty_string", operation, None)

        # Normalize separators for classification only. Never use this value to
        # access the filesystem in this first version.
        path = raw_path.strip().replace("\\", "/")

        if path.startswith("/") or (len(path) >= 2 and path[1] == ":"):
            return self._blocked("absolute_paths_are_not_allowed", operation, path)

        parts = PurePosixPath(path).parts
        if not parts or any(part in {".", ".."} for part in parts):
            return self._blocked("path_traversal_or_invalid_path", operation, path)

        normalized = str(PurePosixPath(path))
        if normalized in {"", "."}:
            return self._blocked("path_must_name_a_target", operation, normalized)

        if operation not in ALLOWED_OPERATIONS:
            return self._blocked("operation_not_allowlisted", operation, normalized)

        if any(
            normalized == prefix or normalized.startswith(prefix + "/")
            for prefix in self.protected_prefixes
        ):
            return self._blocked("protected_path", operation, normalized)

        if not any(
            normalized == prefix.rstrip("/") or normalized.startswith(prefix + "/")
            for prefix in self.allowed_prefixes
        ):
            return self._blocked("path_outside_allowlist", operation, normalized)

        return Decision("allow", "operation_and_path_allowlisted", operation, normalized)


def main() -> int:
    """Read one JSON action per line and print one JSON decision per line."""
    monitor = CodeGuardian()
    for line_number, line in enumerate(sys.stdin, start=1):
        if not line.strip():
            continue
        try:
            action = json.loads(line)
        except json.JSONDecodeError as exc:
            result = {
                "line": line_number,
                "decision": "block",
                "reason": f"invalid_json: {exc.msg}",
                "operation": None,
                "path": None,
            }
        else:
            result = monitor.evaluate(action).to_dict()
            result["line"] = line_number
        print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
