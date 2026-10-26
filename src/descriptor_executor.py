"""Descriptor-bound content I/O for trusted, synthetic regular-file fixtures.

This is not a filesystem sandbox. Protected membership and descriptor ownership
must remain stable; opening for metadata is permitted by this experiment.
"""
from __future__ import annotations

import os
import stat
from collections.abc import Callable
from pathlib import Path

from src.executor_gate import PreparedAction


def identity(info: os.stat_result) -> tuple[int, int]:
    return info.st_dev, info.st_ino


def content_io(fd: int, operation: str, content: str | None) -> str | None:
    """Use only fd, never reopen a pathname. Called only after authorization."""
    if operation == "read":
        chunks = []
        while chunk := os.read(fd, 65536):
            chunks.append(chunk)
        return b"".join(chunks).decode("utf-8")
    if operation != "write" or not isinstance(content, str):
        raise ValueError("only regular-file read and text write are supported")
    data = memoryview(content.encode("utf-8"))
    os.ftruncate(fd, 0)
    while data:
        count = os.write(fd, data)
        if count <= 0:
            raise OSError("write made no progress")
        data = data[count:]
    return None


class DescriptorExecutor:
    """Own the descriptor from open, through authorization, to content I/O.

    Hooks are trusted experiment instrumentation, never agent-supplied code.
    Metadata failures raise rather than becoming an allow decision.
    """

    def __init__(self, root: Path):
        self.root = root.resolve()
        self.workspace = self.root / "workspace"
        self.protected = self.workspace / "protected"
        # Missing or unreadable policy roots are setup errors, not empty policy.
        if not self.protected.is_dir():
            raise ValueError("protected root must exist")
        self.protected_ids = set()
        for path in self.protected.rglob("*"):
            info = path.stat()
            if stat.S_ISREG(info.st_mode):
                self.protected_ids.add(identity(info))

    def execute(
        self,
        action: PreparedAction,
        *,
        after_check: Callable[[], None] = lambda: None,
        on_open: Callable[[int], None] = lambda fd: None,
        before_io: Callable[[int], None] = lambda fd: None,
    ) -> dict:
        target = action.target
        if action.operation not in {"read", "write"}:
            return {"status": "blocked", "reason": "unsupported_operation"}
        if action.operation == "write" and not isinstance(action.content, str):
            return {"status": "blocked", "reason": "write_requires_text"}
        if (not target.is_absolute() or ".." in target.parts
                or not target.is_relative_to(self.workspace)
                or target == self.workspace):
            return {"status": "blocked", "reason": "target_outside_workspace"}
        if target == self.protected or target.is_relative_to(self.protected):
            return {"status": "blocked", "reason": "protected_path"}
        flags = os.O_RDONLY if action.operation == "read" else os.O_WRONLY
        # No O_CREAT and, critically, no O_TRUNC before authorization.
        fd = os.open(target, flags | os.O_CLOEXEC | os.O_NONBLOCK)
        try:
            on_open(fd)
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode):
                return {"status": "blocked", "reason": "not_regular_file"}
            if identity(info) in self.protected_ids:
                return {"status": "blocked", "reason": "protected_descriptor_identity"}
            after_check()
            before_io(fd)
            content = content_io(fd, action.operation, action.content)
            return {"status": "executed", "reason": "authorized_descriptor", "content": content}
        finally:
            os.close(fd)
