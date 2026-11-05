"""Request-key races: rollback safety and caller-visible result semantics."""
from __future__ import annotations

import sqlite3
from collections.abc import Callable
from pathlib import Path

from src.overlap_store import OverlapPublicationStore
from src.publication_store import Checkpoint, StoredApproval, digest
from src.retirement_store import RetirementPublicationStore, response, validate_epoch
from src.retry_store import validate_request

MODES = ("precheck_insert", "constraint_conflict", "resolve_duplicate", "transactional_lookup")
CALLERS = ("first", "second", "later")
Event = Callable[..., None]


class CallerPublicationStore(RetirementPublicationStore):
    def __init__(self, root: Path, mode: str):
        super().__init__(root, "atomic_fence")
        if mode not in MODES:
            raise ValueError("unknown caller mode")
        self.mode = mode

    def initialize(self, content: bytes) -> None:
        super().initialize(content)
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute("CREATE TABLE call_commits (revision INTEGER PRIMARY KEY, caller TEXT NOT NULL, "
                               "epoch INTEGER NOT NULL, request_id TEXT NOT NULL, operation TEXT NOT NULL, approved_sha256 TEXT)")
            connection.execute("COMMIT")
        finally:
            connection.close()

    def _writer_connection(self):
        # Reuse Phase 11's checked zero-timeout connection, without invoking
        # its admission policy or adding its observer schema.
        return OverlapPublicationStore._probe_connection(self)

    def _lookup(self, connection, epoch, key, content) -> dict:
        active = self._active_epoch(connection)
        current = self._row(connection).revision
        prior = connection.execute("SELECT operation, payload, revision, approved_sha256 FROM requests "
                                   "WHERE epoch=? AND request_id=?", (epoch, key)).fetchone()
        if epoch > active:
            answer = response("future_epoch", epoch, key)
        elif prior is not None:
            same = prior[0] == ("revoke" if content is None else "update") and prior[1] == content
            answer = response("replayed", epoch, key, prior[2], prior[3]) if same else response("conflict", epoch, key)
        elif epoch < active:
            answer = response("epoch_retired", epoch, key)
        else:
            answer = None
        return {"observed_epoch": active, "current_revision": current, "receipt_seen": prior is not None,
                "receipt_revision": None if prior is None else prior[2], "decision": "missing" if answer is None else answer["status"],
                "response": answer}

    def _read_lookup(self, epoch, key, content) -> dict:
        connection = self._connect()
        try:
            connection.execute("BEGIN")
            return self._lookup(connection, epoch, key, content)
        finally:
            connection.close()

    @staticmethod
    def _begin(connection, epoch, key, event) -> dict | None:
        try:
            connection.execute("BEGIN IMMEDIATE")
        except sqlite3.OperationalError as exc:
            if getattr(exc, "sqlite_errorcode", None) != sqlite3.SQLITE_BUSY:
                raise
            event("writer_busy", at="begin_immediate", sqlite_errorcode=exc.sqlite_errorcode,
                  sqlite_errorname=exc.sqlite_errorname, busy_timeout_ms=0)
            return response("busy", epoch, key)
        return None

    def publish_once(self, caller: str, epoch: int, key: str, content: bytes | None, *,
                     checkpoint: Checkpoint = lambda stage: None,
                     event: Event = lambda kind, **fields: None) -> dict:
        if caller not in CALLERS:
            raise ValueError("known fixture caller required")
        validate_epoch(epoch)
        operation = validate_request(key, content)
        connection = None
        try:
            if self.mode == "transactional_lookup":
                connection = self._writer_connection()
                busy = self._begin(connection, epoch, key, event)
                if busy is not None:
                    return busy
                lookup = self._lookup(connection, epoch, key, content)
                origin = "transaction"
            else:
                lookup = self._read_lookup(epoch, key, content)
                origin = "read"
            event("lookup", scope="initial", origin=origin, **{k: v for k, v in lookup.items() if k != "response"})
            if lookup["response"] is not None:
                return lookup["response"]
            checkpoint("after_lookup")
            if connection is None:
                connection = self._writer_connection()
                busy = self._begin(connection, epoch, key, event)
                if busy is not None:
                    return busy
            before = self._row(connection)
            after = StoredApproval(before.revision + 1, None if content is None else digest(content),
                                   before.content if content is None else content)
            connection.execute("UPDATE publication SET revision=?, approved_sha256=?, content=? WHERE id=1",
                               (after.revision, after.approved_sha256, after.content))
            connection.execute("INSERT INTO effects VALUES (?, ?, ?, ?, ?)",
                               (after.revision, epoch, key, operation, after.approved_sha256))
            try:
                connection.execute("INSERT INTO requests VALUES (?, ?, ?, ?, ?, ?)",
                                   (epoch, key, operation, content, after.revision, after.approved_sha256))
            except sqlite3.IntegrityError as exc:
                if getattr(exc, "sqlite_errorcode", None) != sqlite3.SQLITE_CONSTRAINT_PRIMARYKEY:
                    raise
                connection.execute("ROLLBACK")
                connection.close()
                connection = None
                event("duplicate_receipt", at="receipt_insert", sqlite_errorcode=exc.sqlite_errorcode,
                      sqlite_errorname=exc.sqlite_errorname, transaction_rolled_back=True)
                if self.mode == "constraint_conflict":
                    return response("conflict", epoch, key)
                if self.mode == "resolve_duplicate":
                    resolved = self._read_lookup(epoch, key, content)
                    event("lookup", scope="resolution", origin="read", **{k: v for k, v in resolved.items() if k != "response"})
                    return resolved["response"] if resolved["response"] is not None else response("storage_error", epoch, key)
                return response("storage_error", epoch, key)
            connection.execute("INSERT INTO call_commits VALUES (?, ?, ?, ?, ?, ?)",
                               (after.revision, caller, epoch, key, operation, after.approved_sha256))
            checkpoint("before_commit")
            connection.execute("COMMIT")
            checkpoint("after_commit")
            return response("committed", epoch, key, after.revision, after.approved_sha256)
        finally:
            if connection is not None:
                connection.close()

    def inspect(self) -> dict:
        connection = self._connect()
        try:
            connection.execute("BEGIN")
            state, active = self._row(connection), self._active_epoch(connection)
            effects = [dict(zip(("revision", "epoch", "request_id", "operation", "approved_sha256"), row))
                       for row in connection.execute("SELECT revision, epoch, request_id, operation, approved_sha256 FROM effects ORDER BY revision")]
            receipts = [dict(zip(("epoch", "request_id", "operation", "payload", "revision", "approved_sha256"), row))
                        for row in connection.execute("SELECT epoch, request_id, operation, payload, revision, approved_sha256 FROM requests ORDER BY epoch, request_id")]
            commits = [dict(zip(("revision", "caller", "epoch", "request_id", "operation", "approved_sha256"), row))
                       for row in connection.execute("SELECT revision, caller, epoch, request_id, operation, approved_sha256 FROM call_commits ORDER BY revision")]
            connection.execute("COMMIT")
            return {"state": state, "active_epoch": active, "effects": effects, "receipts": receipts, "call_commits": commits}
        finally:
            connection.close()
