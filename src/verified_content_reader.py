"""Deliver a captured UTF-8 value only if it matches a trusted version digest.

This checks delivery, not whether unapproved bytes were read for inspection.
It reuses the Phase 5 resource gate without changing its implementation.
"""
from __future__ import annotations

import hashlib
import re
from collections.abc import Callable, Mapping
from pathlib import Path
from types import MappingProxyType

from src.descriptor_executor import DescriptorExecutor
from src.executor_gate import PreparedAction


class VerifiedContentReader:
    """Capture once, validate the captured value, and return that same value.

    The owner supplies approved digests; actions cannot select their own digest.
    Hooks are trusted experiment instrumentation. Content and policy are small
    and static in this prototype; no streaming or freshness guarantee is made.
    """

    def __init__(self, root: Path, approved_sha256: Mapping[Path, str]):
        copied = dict(approved_sha256)
        for path, expected in copied.items():
            if (not isinstance(path, Path) or not path.is_absolute() or ".." in path.parts
                    or not isinstance(expected, str) or not re.fullmatch(r"[0-9a-f]{64}", expected)):
                raise ValueError("absolute target and lowercase SHA-256 digest required")
        self.approved_sha256 = MappingProxyType(copied)
        self.executor = DescriptorExecutor(root)

    def read(
        self,
        action: PreparedAction,
        *,
        after_identity_check: Callable[[], None] = lambda: None,
        after_validation: Callable[[], None] = lambda: None,
        on_open: Callable[[int], None] = lambda fd: None,
        before_io: Callable[[int], None] = lambda fd: None,
        on_validation: Callable[[str, int], None] = lambda digest, size: None,
    ) -> dict:
        if action.operation != "read":
            return {"status": "blocked", "reason": "read_only_interface"}
        expected = self.approved_sha256.get(action.target)
        if expected is None:
            return {"status": "blocked", "reason": "no_trusted_content_version"}
        outcome = self.executor.execute(action, after_check=after_identity_check,
                                        on_open=on_open, before_io=before_io)
        if outcome["status"] != "executed":
            return outcome
        captured = outcome["content"]
        encoded = captured.encode("utf-8")
        actual = hashlib.sha256(encoded).hexdigest()
        on_validation(actual, len(encoded))
        if actual != expected:
            # Do not return any captured payload on a failed version check.
            return {"status": "blocked", "reason": "content_version_mismatch",
                    "inspected_sha256": actual, "inspected_bytes": len(encoded)}
        after_validation()
        return {"status": "executed", "reason": "verified_captured_content",
                "content": captured, "inspected_sha256": actual, "inspected_bytes": len(encoded)}
