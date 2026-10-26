"""Experimental filesystem-identity gate for a trusted prepared executor."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from src.codeguardian import ALLOWED_OPERATIONS, Decision
from src.executor_gate import PreparedAction


def file_identity(path: Path) -> tuple[int, int] | None:
    try:
        stat = path.stat()
    except (FileNotFoundError, OSError):
        return None
    return stat.st_dev, stat.st_ino


class IdentityAwareGate:
    """Check both resolved path policy and existing protected file identity.

    This binds a decision to the prepared target's current device/inode on a
    fixed topology. It is not race-safe: a later replacement can invalidate a
    pathname or identity check before the executor opens it.
    """

    def __init__(self, fixture_root: Path):
        self.root = fixture_root.resolve()
        self.workspace = self.root / "workspace"
        self.protected = self.workspace / "protected"
        self.protected_ids = self._protected_file_ids()

    def _protected_file_ids(self) -> set[tuple[int, int]]:
        if not self.protected.exists():
            return set()
        return {
            identity
            for path in self.protected.rglob("*")
            if path.is_file() and (identity := file_identity(path)) is not None
        }

    def evaluate(self, prepared: PreparedAction) -> Decision:
        target = prepared.target
        operation = prepared.operation

        def result(decision: str, reason: str) -> Decision:
            path = target.relative_to(self.root).as_posix() if target.is_relative_to(self.root) else None
            return Decision(decision, reason, operation, path)

        if operation not in ALLOWED_OPERATIONS:
            return result("block", "operation_not_allowlisted")
        if operation in {"write", "create"} and not isinstance(prepared.content, str):
            return result("block", "write_requires_text_content")
        if not target.is_absolute() or not target.is_relative_to(self.root):
            return result("block", "target_not_prepared")
        if target == self.root:
            return result("block", "resolved_path_outside_allowlist")
        if target == self.protected or target.is_relative_to(self.protected):
            return result("block", "resolved_protected_path")
        if not target.is_relative_to(self.workspace):
            return result("block", "resolved_path_outside_allowlist")
        identity = file_identity(target)
        if identity is not None and identity in self.protected_ids:
            return result("block", "protected_file_identity")
        return result("allow", "resolved_target_and_identity_allowlisted")
