"""Duplicate resolution across logical receipt retirement in one SQLite store."""
from __future__ import annotations

import sqlite3
from collections.abc import Callable
from pathlib import Path

from src.overlap_store import OverlapPublicationStore
from src.publication_store import Checkpoint, StoredApproval, digest
from src.retirement_store import RetirementPublicationStore, response, validate_epoch
from src.retry_store import validate_request

MODES = ("retry_missing", "fenced_resolution", "guarded_resolution")
CALLERS = ("first", "second", "later")
Event = Callable[..., None]


class ReceiptCollision(Exception):
    """Only a numeric primary-key error from the receipt INSERT enters here."""

    def __init__(self, error: sqlite3.IntegrityError):
        super().__init__(str(error))
        self.code = error.sqlite_errorcode
        self.name = error.sqlite_errorname


class ResolutionPublicationStore(RetirementPublicationStore):
    def __init__(self, root: Path, mode: str):
        super().__init__(root, "atomic_fence")
        if mode not in MODES:
            raise ValueError("unknown resolution mode")
        self.mode = mode

    def initialize(self, content: bytes) -> None:
        super().initialize(content)
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                "CREATE TABLE resolution_commits (revision INTEGER PRIMARY KEY, caller TEXT NOT NULL, "
                "epoch INTEGER NOT NULL, request_id TEXT NOT NULL, operation TEXT NOT NULL, "
                "approved_sha256 TEXT, active_epoch INTEGER NOT NULL)"
            )
            connection.execute("COMMIT")
        finally:
            connection.close()

    def _probe_connection(self):
        return OverlapPublicationStore._probe_connection(self)

    def try_retire(self, target_epoch: int) -> dict:
        return OverlapPublicationStore.try_retire(self, target_epoch)

    @staticmethod
    def _begin(connection, epoch, key, event):
        try:
            connection.execute("BEGIN IMMEDIATE")
        except sqlite3.OperationalError as error:
            if getattr(error, "sqlite_errorcode", None) != sqlite3.SQLITE_BUSY:
                raise
            event("writer_busy", at="begin_immediate", sqlite_errorcode=error.sqlite_errorcode,
                  sqlite_errorname=error.sqlite_errorname, busy_timeout_ms=0)
            return response("busy", epoch, key)
        return None

    def _view(self, connection, epoch, key, content):
        active = self._active_epoch(connection)
        current = self._row(connection).revision
        receipt = connection.execute(
            "SELECT operation, payload, revision, approved_sha256 FROM requests WHERE epoch=? AND request_id=?",
            (epoch, key),
        ).fetchone()
        if epoch > active:
            result = response("future_epoch", epoch, key)
        elif receipt is not None:
            same = receipt[0] == ("revoke" if content is None else "update") and receipt[1] == content
            result = response("replayed", epoch, key, receipt[2], receipt[3]) if same else response("conflict", epoch, key)
        elif epoch < active:
            result = response("outcome_unavailable", epoch, key)
        else:
            result = None
        return {"observed_epoch": active, "current_revision": current, "receipt_seen": receipt is not None,
                "receipt_revision": None if receipt is None else receipt[2],
                "decision": "missing" if result is None else result["status"], "response": result}

    def _read_view(self, epoch, key, content):
        connection = self._probe_connection()
        try:
            connection.execute("BEGIN")
            return self._view(connection, epoch, key, content)
        finally:
            connection.close()

    def _write(self, connection, caller, epoch, key, content, event):
        active = self._active_epoch(connection)
        before = self._row(connection)
        after = StoredApproval(before.revision + 1, None if content is None else digest(content),
                               before.content if content is None else content)
        operation = "revoke" if content is None else "update"
        event("write_view", revision=after.revision, requested_epoch=epoch, active_epoch=active)
        connection.execute("UPDATE publication SET revision=?, approved_sha256=?, content=? WHERE id=1",
                           (after.revision, after.approved_sha256, after.content))
        connection.execute("INSERT INTO effects VALUES (?, ?, ?, ?, ?)",
                           (after.revision, epoch, key, operation, after.approved_sha256))
        try:
            connection.execute("INSERT INTO requests VALUES (?, ?, ?, ?, ?, ?)",
                               (epoch, key, operation, content, after.revision, after.approved_sha256))
        except sqlite3.IntegrityError as error:
            if getattr(error, "sqlite_errorcode", None) != sqlite3.SQLITE_CONSTRAINT_PRIMARYKEY:
                raise
            raise ReceiptCollision(error) from error
        connection.execute("INSERT INTO resolution_commits VALUES (?, ?, ?, ?, ?, ?, ?)",
                           (after.revision, caller, epoch, key, operation, after.approved_sha256, active))
        return response("committed", epoch, key, after.revision, after.approved_sha256)

    def publish(self, caller: str, epoch: int, key: str, content: bytes | None, *,
                checkpoint: Checkpoint = lambda stage: None,
                event: Event = lambda kind, **fields: None) -> dict:
        if caller not in CALLERS:
            raise ValueError("known fixture caller required")
        validate_epoch(epoch)
        validate_request(key, content)
        initial = self._read_view(epoch, key, content)
        event("lookup", scope="initial", origin="read", **{k: v for k, v in initial.items() if k != "response"})
        if initial["response"] is not None:
            return initial["response"]
        checkpoint("after_precheck")
        connection = self._probe_connection()
        try:
            busy = self._begin(connection, epoch, key, event)
            if busy is not None:
                return busy
            try:
                result = self._write(connection, caller, epoch, key, content, event)
            except ReceiptCollision as error:
                connection.execute("ROLLBACK")
                connection.close()
                connection = None
                event("duplicate_receipt", at="receipt_insert", sqlite_errorcode=error.code,
                      sqlite_errorname=error.name, transaction_rolled_back=True)
            else:
                checkpoint("before_commit")
                connection.execute("COMMIT")
                checkpoint("after_commit")
                return result
            guarded = self.mode == "guarded_resolution"
            if guarded:
                connection = self._probe_connection()
                busy = self._begin(connection, epoch, key, event)
                if busy is not None:
                    return busy
            event("resolution_guard", held=guarded)
            checkpoint("before_resolution")
            view = self._view(connection, epoch, key, content) if guarded else self._read_view(epoch, key, content)
            event("lookup", scope="resolution", origin="transaction" if guarded else "read",
                  **{k: v for k, v in view.items() if k != "response"})
            if self.mode == "retry_missing" and not view["receipt_seen"]:
                # Diagnostic negative arm: old cached admission is reused even
                # when the new snapshot explicitly observes a closed epoch.
                event("unsafe_retry", requested_epoch=epoch, observed_epoch=view["observed_epoch"])
                connection = self._probe_connection()
                busy = self._begin(connection, epoch, key, event)
                if busy is not None:
                    return busy
                result = self._write(connection, caller, epoch, key, content, event)
                checkpoint("before_commit")
                connection.execute("COMMIT")
                checkpoint("after_commit")
                return result
            result = view["response"] or response("storage_error", epoch, key)
            if guarded:
                connection.execute("COMMIT")
                event("resolution_released")
            return result
        finally:
            if connection is not None:
                connection.close()

    def inspect(self) -> dict:
        connection = self._connect()
        try:
            connection.execute("BEGIN")
            observed = {"state": self._row(connection), "active_epoch": self._active_epoch(connection)}
            for name, columns in (
                ("effects", ("revision", "epoch", "request_id", "operation", "approved_sha256")),
                ("requests", ("epoch", "request_id", "operation", "payload", "revision", "approved_sha256")),
                ("resolution_commits", ("revision", "caller", "epoch", "request_id", "operation", "approved_sha256", "active_epoch")),
            ):
                order = "epoch, request_id" if name == "requests" else "revision"
                rows = connection.execute("SELECT " + ", ".join(columns) + " FROM " + name + " ORDER BY " + order)
                observed[{"requests": "receipts", "resolution_commits": "commits"}.get(name, name)] = [dict(zip(columns, r)) for r in rows]
            connection.execute("COMMIT")
            return observed
        finally:
            connection.close()
