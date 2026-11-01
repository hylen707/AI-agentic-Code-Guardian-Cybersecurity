"""Coordinate committed approvals and a trusted in-process consumer receipt.

All publishers must participate. This is not distributed coordination, an
atomic filesystem transaction, or immediate revocation of delivered content.
"""
from __future__ import annotations

import hashlib
import re
from collections.abc import Callable
from dataclasses import dataclass
from threading import Lock


@dataclass(frozen=True)
class Approval:
    revision: int
    sha256: str | None


@dataclass(frozen=True)
class VersionedValue:
    revision: int
    content: str


def validate_digest(value: str | None) -> None:
    if value is not None and (not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value)):
        raise ValueError("approval must be a lowercase SHA-256 digest or revoked (None)")


class RevisionAuthority:
    """One resource, one monotonic approval revision, one receipt boundary.

    Publication and receiver callbacks run under a non-reentrant lock. They
    must be short and trusted, and must not synchronously call blocking
    authority methods. Exceptions propagate; no crash rollback is promised.
    """

    def __init__(self, initial_digest: str | None,
                 on_commit: Callable[[Approval], None] = lambda approval: None):
        validate_digest(initial_digest)
        self._lock = Lock()
        self._state = Approval(1, initial_digest)
        self._on_commit = on_commit

    def snapshot(self) -> Approval:
        with self._lock:
            return self._state

    def try_publish(self, new_digest: str | None,
                    publish: Callable[[], None] = lambda: None) -> bool:
        """Return False if busy, with no publication; caller owns retry policy."""
        validate_digest(new_digest)
        if not self._lock.acquire(blocking=False):
            return False
        try:
            publish()
            self._state = Approval(self._state.revision + 1, new_digest)
            self._on_commit(self._state)
            return True
        finally:
            self._lock.release()

    def _rejection(self, value: VersionedValue) -> str | None:
        if type(value.revision) is not int or value.revision < 1 or not isinstance(value.content, str):
            return "invalid_candidate"
        if self._state.sha256 is None:
            return "approval_revoked"
        if value.revision != self._state.revision:
            return "approval_revision_changed"
        if hashlib.sha256(value.content.encode("utf-8")).hexdigest() != self._state.sha256:
            return "payload_digest_mismatch"
        return None

    def check(self, value: VersionedValue) -> dict:
        """A standalone check is intentionally insufficient to bind later use."""
        with self._lock:
            reason = self._rejection(value)
            return {"status": "blocked" if reason else "allowed",
                    "reason": reason or "current_revision_matches"}

    def release(self, value: VersionedValue, receive: Callable[[VersionedValue], None],
                *, after_check: Callable[[], None] = lambda: None) -> dict:
        """Check and record trusted receipt before permitting a publication."""
        with self._lock:
            reason = self._rejection(value)
            if reason:
                return {"status": "blocked", "reason": reason}
            after_check()
            receive(value)
            return {"status": "released", "reason": "current_revision_received"}
