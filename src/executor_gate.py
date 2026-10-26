"""Experimental gate for a trusted executor with fixed filesystem topology.

Canonical paths are not immutable resource identities. This is not race-safe
or hardlink-aware enforcement; see docs/GATE_PROTOCOL.md.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from src.codeguardian import ALLOWED_OPERATIONS, Decision


@dataclass(frozen=True)
class PreparedAction:
    """Trusted executor output: the exact operation/target/content to execute."""

    operation: str
    target: Path
    content: str | None = None


class ExecutorAwareGate:
    def __init__(self, fixture_root: Path):
        self.root = fixture_root.resolve()
        self.workspace = self.root / "workspace"
        self.protected = self.workspace / "protected"

    def evaluate(self, prepared: PreparedAction) -> Decision:
        target = prepared.target
        operation = prepared.operation

        def result(decision: str, reason: str) -> Decision:
            # Keep host temporary paths out of the experiment record.
            path = target.relative_to(self.root).as_posix() if target.is_relative_to(self.root) else None
            return Decision(decision, reason, operation, path)

        if operation not in ALLOWED_OPERATIONS:
            return result("block", "operation_not_allowlisted")
        if operation in {"write", "create"} and not isinstance(prepared.content, str):
            return result("block", "write_requires_text_content")
        try:
            canonical = target.is_absolute() and target == target.resolve()
        except (OSError, RuntimeError, ValueError):
            canonical = False
        if not canonical:
            return result("block", "target_not_prepared")
        if target == self.protected or target.is_relative_to(self.protected):
            return result("block", "resolved_protected_path")
        if target != self.workspace and not target.is_relative_to(self.workspace):
            return result("block", "resolved_path_outside_allowlist")
        return result("allow", "resolved_target_allowlisted")
