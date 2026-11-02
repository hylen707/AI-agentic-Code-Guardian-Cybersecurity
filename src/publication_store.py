"""Small trusted-fixture stores for publication and process-restart recovery.

Individual split-file replacements are atomic; the pair is not a transaction.
SQLite couples payload and approval in one row. Neither design is a sandbox,
distributed publisher, or an experimentally established power-loss guarantee.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

Checkpoint = Callable[[str], None]


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


@dataclass(frozen=True)
class StoredApproval:
    revision: int
    approved_sha256: str | None
    content: bytes

    def __post_init__(self) -> None:
        if type(self.revision) is not int or self.revision < 1:
            raise ValueError("positive integer revision required")
        if self.approved_sha256 is not None and (
            not isinstance(self.approved_sha256, str)
            or not re.fullmatch(r"[0-9a-f]{64}", self.approved_sha256)
        ):
            raise ValueError("lowercase SHA-256 digest or revocation required")
        if not isinstance(self.content, bytes):
            raise ValueError("payload bytes required")


def recover_value(state: StoredApproval, *, verify: bool = True) -> dict:
    """Return the same captured bytes checked, including an empty payload."""
    if state.approved_sha256 is None:
        return {"status": "blocked", "reason": "approval_revoked",
                "revision": state.revision, "content": None}
    if verify and digest(state.content) != state.approved_sha256:
        return {"status": "blocked", "reason": "recovered_digest_mismatch",
                "revision": state.revision, "content": None}
    return {"status": "delivered", "reason": "verified_recovery" if verify else "unchecked_recovery",
            "revision": state.revision, "content": state.content}


def sync_directory(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def replace_file(path: Path, data: bytes) -> None:
    """Sync and replace one file, never claim atomicity across two paths."""
    fd, name = tempfile.mkstemp(prefix=".publication-", dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        sync_directory(path.parent)
    finally:
        temporary.unlink(missing_ok=True)


class SplitPublicationStore:
    """Trusted single-writer content and approval stored in separate files."""

    def __init__(self, root: Path):
        self.root = Path(root)
        self.payload = self.root / "payload.bin"
        self.approval = self.root / "approval.json"

    def initialize(self, content: bytes) -> None:
        state = StoredApproval(1, digest(content), content)
        self.root.mkdir(parents=True, exist_ok=True)
        if self.payload.exists() or self.approval.exists():
            raise FileExistsError("store already initialized")
        replace_file(self.payload, state.content)
        self._write_approval(state)

    def _write_approval(self, state: StoredApproval) -> None:
        data = json.dumps({"revision": state.revision,
                           "approved_sha256": state.approved_sha256}, sort_keys=True).encode("utf-8")
        replace_file(self.approval, data)

    def snapshot(self) -> StoredApproval:
        approval = json.loads(self.approval.read_text(encoding="utf-8"))
        if not isinstance(approval, dict) or set(approval) != {"revision", "approved_sha256"}:
            raise ValueError("invalid approval record")
        return StoredApproval(approval["revision"], approval["approved_sha256"], self.payload.read_bytes())

    def publish(self, content: bytes | None, *, checkpoint: Checkpoint = lambda stage: None) -> StoredApproval:
        before = self.snapshot()
        after = StoredApproval(before.revision + 1,
                               None if content is None else digest(content),
                               before.content if content is None else content)
        checkpoint("before_publish")
        if content is not None:
            replace_file(self.payload, content)
        checkpoint("after_stage")
        self._write_approval(after)
        checkpoint("after_commit")
        return after


class SQLitePublicationStore:
    """One row and explicit transaction for the payload/approval pair."""

    def __init__(self, root: Path):
        self.root = Path(root)
        self.database = self.root / "publication.sqlite3"

    def _connect(self, *, create: bool = False) -> sqlite3.Connection:
        name = str(self.database) if create else self.database.resolve().as_uri() + "?mode=rw"
        connection = sqlite3.connect(name, uri=not create, isolation_level=None, timeout=5)
        try:
            mode = connection.execute("PRAGMA journal_mode=DELETE").fetchone()[0]
            connection.execute("PRAGMA synchronous=FULL")
            level = connection.execute("PRAGMA synchronous").fetchone()[0]
            if mode.lower() != "delete" or level != 2:
                raise RuntimeError("required SQLite journal/synchronous settings unavailable")
            return connection
        except BaseException:
            connection.close()
            raise

    def initialize(self, content: bytes) -> None:
        state = StoredApproval(1, digest(content), content)
        self.root.mkdir(parents=True, exist_ok=True)
        if self.database.exists():
            raise FileExistsError("store already initialized")
        connection = self._connect(create=True)
        try:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute("CREATE TABLE publication (id INTEGER PRIMARY KEY CHECK (id=1), "
                               "revision INTEGER NOT NULL CHECK (revision>0), approved_sha256 TEXT, "
                               "content BLOB NOT NULL)")
            connection.execute("INSERT INTO publication VALUES (1, ?, ?, ?)",
                               (state.revision, state.approved_sha256, state.content))
            connection.execute("COMMIT")
            sync_directory(self.root)
        finally:
            connection.close()

    @staticmethod
    def _row(connection: sqlite3.Connection) -> StoredApproval:
        row = connection.execute("SELECT revision, approved_sha256, content FROM publication WHERE id=1").fetchone()
        if row is None:
            raise ValueError("missing publication state")
        return StoredApproval(*row)

    def snapshot(self) -> StoredApproval:
        connection = self._connect()
        try:
            return self._row(connection)
        finally:
            connection.close()

    def settings(self) -> dict:
        connection = self._connect()
        try:
            return {"journal_mode": connection.execute("PRAGMA journal_mode").fetchone()[0],
                    "synchronous": connection.execute("PRAGMA synchronous").fetchone()[0],
                    "integrity_check": connection.execute("PRAGMA integrity_check").fetchone()[0]}
        finally:
            connection.close()

    def publish(self, content: bytes | None, *, checkpoint: Checkpoint = lambda stage: None) -> StoredApproval:
        connection = self._connect()
        try:
            checkpoint("before_publish")
            connection.execute("BEGIN IMMEDIATE")
            before = self._row(connection)
            after = StoredApproval(before.revision + 1,
                                   None if content is None else digest(content),
                                   before.content if content is None else content)
            connection.execute("UPDATE publication SET revision=?, approved_sha256=?, content=? WHERE id=1",
                               (after.revision, after.approved_sha256, after.content))
            checkpoint("after_stage")
            connection.execute("COMMIT")
            checkpoint("after_commit")
            return after
        finally:
            # A live exception closes/rolls back an uncommitted transaction.
            # os._exit in the worker deliberately bypasses this cleanup.
            connection.close()
