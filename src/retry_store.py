"""Trusted sequential fixture publisher with three request-retry contracts.

The effect observer is written atomically with publication, but is never used
to decide whether a request is a retry. Receipts are retained indefinitely.
"""
from __future__ import annotations

import re
from pathlib import Path

from src.publication_store import Checkpoint, SQLitePublicationStore, StoredApproval, digest, sync_directory

ARMS = ("unkeyed", "split_receipt", "atomic_receipt")


def validate_request(request_id: str, content: bytes | None) -> str:
    if not isinstance(request_id, str) or not re.fullmatch(r"[A-Za-z0-9_.-]{1,80}", request_id):
        raise ValueError("bounded ASCII request ID required")
    if content is not None and not isinstance(content, bytes):
        raise ValueError("payload must be bytes or revocation")
    return "revoke" if content is None else "update"


def receipt(status: str, request_id: str, revision: int | None, approved_sha256: str | None) -> dict:
    return {"status": status, "request_id": request_id, "revision": revision,
            "approved_sha256": approved_sha256}


class RetryPublicationStore(SQLitePublicationStore):
    def __init__(self, root: Path, arm: str):
        super().__init__(root)
        if arm not in ARMS:
            raise ValueError("unknown retry arm")
        self.arm = arm

    def initialize(self, content: bytes) -> None:
        state = StoredApproval(1, digest(content), content)
        self.root.mkdir(parents=True, exist_ok=True)
        if self.database.exists():
            raise FileExistsError("store already initialized")
        connection = self._connect(create=True)
        try:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute("CREATE TABLE publication (id INTEGER PRIMARY KEY CHECK(id=1), "
                               "revision INTEGER NOT NULL CHECK(revision>0), approved_sha256 TEXT, content BLOB NOT NULL)")
            connection.execute("INSERT INTO publication VALUES (1, ?, ?, ?)",
                               (state.revision, state.approved_sha256, state.content))
            connection.execute("CREATE TABLE effects (revision INTEGER PRIMARY KEY, request_id TEXT NOT NULL, "
                               "operation TEXT NOT NULL, approved_sha256 TEXT)")
            connection.execute("CREATE TABLE requests (request_id TEXT PRIMARY KEY, operation TEXT NOT NULL, "
                               "payload BLOB, revision INTEGER NOT NULL, approved_sha256 TEXT)")
            connection.execute("COMMIT")
            sync_directory(self.root)
        finally:
            connection.close()

    def publish_request(self, request_id: str, content: bytes | None, *,
                        checkpoint: Checkpoint = lambda stage: None) -> dict:
        operation = validate_request(request_id, content)
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            if self.arm != "unkeyed":
                prior = connection.execute("SELECT operation, payload, revision, approved_sha256 FROM requests "
                                           "WHERE request_id=?", (request_id,)).fetchone()
                if prior is not None:
                    connection.execute("ROLLBACK")
                    if prior[0] != operation or prior[1] != content:
                        return receipt("conflict", request_id, None, None)
                    return receipt("replayed", request_id, prior[2], prior[3])
            before = self._row(connection)
            after = StoredApproval(before.revision + 1, None if content is None else digest(content),
                                   before.content if content is None else content)
            connection.execute("UPDATE publication SET revision=?, approved_sha256=?, content=? WHERE id=1",
                               (after.revision, after.approved_sha256, after.content))
            connection.execute("INSERT INTO effects VALUES (?, ?, ?, ?)",
                               (after.revision, request_id, operation, after.approved_sha256))
            parameters = (request_id, operation, content, after.revision, after.approved_sha256)
            if self.arm == "atomic_receipt":
                connection.execute("INSERT INTO requests VALUES (?, ?, ?, ?, ?)", parameters)
            checkpoint("before_commit")
            connection.execute("COMMIT")
            checkpoint("after_state_commit")
            if self.arm == "split_receipt":
                connection.execute("BEGIN IMMEDIATE")
                connection.execute("INSERT INTO requests VALUES (?, ?, ?, ?, ?)", parameters)
                connection.execute("COMMIT")
            checkpoint("after_record_commit")
            return receipt("committed", request_id, after.revision, after.approved_sha256)
        finally:
            # Live exceptions close/rollback open transactions; child os._exit
            # bypasses this cleanup, as in the earlier process-exit study.
            connection.close()

    def inspect(self) -> dict:
        """Capture all observer tables in one read transaction, without writes."""
        connection = self._connect()
        try:
            connection.execute("BEGIN")
            state = self._row(connection)
            effects = [dict(zip(("revision", "request_id", "operation", "approved_sha256"), row))
                       for row in connection.execute("SELECT revision, request_id, operation, approved_sha256 "
                                                     "FROM effects ORDER BY revision")]
            requests = [dict(zip(("request_id", "operation", "payload", "revision", "approved_sha256"), row))
                        for row in connection.execute("SELECT request_id, operation, payload, revision, approved_sha256 "
                                                      "FROM requests ORDER BY request_id")]
            connection.execute("COMMIT")
            return {"state": state, "effects": effects, "receipts": requests}
        finally:
            connection.close()
