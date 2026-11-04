"""Trusted sequential receipt retirement with a persistent epoch boundary.

Epoch assignment is trusted. The epoch is not an authenticated capability.
Observer effects are retained and never consulted for request deduplication.
"""
from __future__ import annotations

from pathlib import Path

from src.publication_store import Checkpoint, SQLitePublicationStore, StoredApproval, digest, sync_directory
from src.retry_store import validate_request

ARMS = ("retain_all", "forget_only", "split_fence", "atomic_fence")
MAX_EPOCH = 2**63 - 1


def validate_epoch(epoch: int) -> None:
    if type(epoch) is not int or not 1 <= epoch <= MAX_EPOCH:
        raise ValueError("positive SQLite-range integer epoch required")


def response(status: str, epoch: int, request_id: str, revision: int | None = None,
             approved_sha256: str | None = None) -> dict:
    return {"status": status, "epoch": epoch, "request_id": request_id,
            "revision": revision, "approved_sha256": approved_sha256}


class RetirementPublicationStore(SQLitePublicationStore):
    def __init__(self, root: Path, arm: str):
        super().__init__(root)
        if arm not in ARMS:
            raise ValueError("unknown retirement arm")
        self.arm = arm

    @staticmethod
    def _active_epoch(connection) -> int:
        row = connection.execute("SELECT active_epoch FROM namespace WHERE id=1").fetchone()
        if row is None:
            raise ValueError("missing active epoch")
        validate_epoch(row[0])
        return row[0]

    def initialize(self, content: bytes) -> None:
        if not isinstance(content, bytes):
            raise ValueError("initial payload bytes required")
        initial = StoredApproval(1, digest(content), content)
        self.root.mkdir(parents=True, exist_ok=True)
        if self.database.exists():
            raise FileExistsError("store already initialized")
        connection = self._connect(create=True)
        try:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute("CREATE TABLE publication (id INTEGER PRIMARY KEY CHECK(id=1), "
                               "revision INTEGER NOT NULL CHECK(revision>0), approved_sha256 TEXT, content BLOB NOT NULL)")
            connection.execute("INSERT INTO publication VALUES (1, ?, ?, ?)",
                               (initial.revision, initial.approved_sha256, initial.content))
            connection.execute("CREATE TABLE namespace (id INTEGER PRIMARY KEY CHECK(id=1), "
                               "active_epoch INTEGER NOT NULL CHECK(active_epoch>0))")
            connection.execute("INSERT INTO namespace VALUES (1, 1)")
            connection.execute("CREATE TABLE effects (revision INTEGER PRIMARY KEY, epoch INTEGER NOT NULL, "
                               "request_id TEXT NOT NULL, operation TEXT NOT NULL, approved_sha256 TEXT)")
            connection.execute("CREATE TABLE requests (epoch INTEGER NOT NULL, request_id TEXT NOT NULL, "
                               "operation TEXT NOT NULL, payload BLOB, revision INTEGER NOT NULL, approved_sha256 TEXT, "
                               "PRIMARY KEY(epoch, request_id))")
            connection.execute("COMMIT")
            sync_directory(self.root)
        finally:
            connection.close()

    def publish_request(self, epoch: int, request_id: str, content: bytes | None) -> dict:
        validate_epoch(epoch)
        operation = validate_request(request_id, content)
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            active = self._active_epoch(connection)
            if epoch > active:
                connection.execute("ROLLBACK")
                return response("future_epoch", epoch, request_id)
            prior = connection.execute("SELECT operation, payload, revision, approved_sha256 FROM requests "
                                       "WHERE epoch=? AND request_id=?", (epoch, request_id)).fetchone()
            if prior is not None:
                connection.execute("ROLLBACK")
                if prior[0] != operation or prior[1] != content:
                    return response("conflict", epoch, request_id)
                return response("replayed", epoch, request_id, prior[2], prior[3])
            if self.arm != "forget_only" and epoch < active:
                connection.execute("ROLLBACK")
                return response("epoch_retired", epoch, request_id)
            before = self._row(connection)
            after = StoredApproval(before.revision + 1, None if content is None else digest(content),
                                   before.content if content is None else content)
            connection.execute("UPDATE publication SET revision=?, approved_sha256=?, content=? WHERE id=1",
                               (after.revision, after.approved_sha256, after.content))
            connection.execute("INSERT INTO effects VALUES (?, ?, ?, ?, ?)",
                               (after.revision, epoch, request_id, operation, after.approved_sha256))
            connection.execute("INSERT INTO requests VALUES (?, ?, ?, ?, ?, ?)",
                               (epoch, request_id, operation, content, after.revision, after.approved_sha256))
            connection.execute("COMMIT")
            return response("committed", epoch, request_id, after.revision, after.approved_sha256)
        finally:
            connection.close()

    def retire(self, target_epoch: int, *, checkpoint: Checkpoint = lambda stage: None) -> dict:
        validate_epoch(target_epoch)
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            active = self._active_epoch(connection)
            if target_epoch == active:
                connection.execute("ROLLBACK")
                return {"status": "already_retired", "active_epoch": active}
            if target_epoch != active + 1:
                raise ValueError("retirement must target the current or next epoch")
            checkpoint("before_retire")
            if self.arm == "split_fence":
                connection.execute("DELETE FROM requests WHERE epoch<?", (target_epoch,))
                connection.execute("COMMIT")
                checkpoint("after_cleanup")
                connection.execute("BEGIN IMMEDIATE")
                connection.execute("UPDATE namespace SET active_epoch=? WHERE id=1", (target_epoch,))
                connection.execute("COMMIT")
            else:
                connection.execute("UPDATE namespace SET active_epoch=? WHERE id=1", (target_epoch,))
                if self.arm != "retain_all":
                    connection.execute("DELETE FROM requests WHERE epoch<?", (target_epoch,))
                checkpoint("after_cleanup")
                connection.execute("COMMIT")
            checkpoint("after_commit")
            return {"status": "retired", "active_epoch": target_epoch}
        finally:
            # os._exit in the worker bypasses this normal close/rollback path.
            connection.close()

    def inspect(self) -> dict:
        connection = self._connect()
        try:
            connection.execute("BEGIN")
            state, active = self._row(connection), self._active_epoch(connection)
            effects = [dict(zip(("revision", "epoch", "request_id", "operation", "approved_sha256"), row))
                       for row in connection.execute("SELECT revision, epoch, request_id, operation, approved_sha256 "
                                                     "FROM effects ORDER BY revision")]
            receipts = [dict(zip(("epoch", "request_id", "operation", "payload", "revision", "approved_sha256"), row))
                        for row in connection.execute("SELECT epoch, request_id, operation, payload, revision, approved_sha256 "
                                                      "FROM requests ORDER BY epoch, request_id")]
            connection.execute("COMMIT")
            return {"state": state, "active_epoch": active, "effects": effects, "receipts": receipts}
        finally:
            connection.close()
