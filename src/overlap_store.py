"""Publication admission scopes for a controlled two-process epoch study."""
from __future__ import annotations

import sqlite3
from collections.abc import Callable
from pathlib import Path

from src.publication_store import Checkpoint, StoredApproval, digest
from src.retirement_store import RetirementPublicationStore, response, validate_epoch
from src.retry_store import validate_request

MODES = ("cached_admission", "separate_recheck", "transactional_admission")
Event = Callable[..., None]


class OverlapPublicationStore(RetirementPublicationStore):
    def __init__(self, root: Path, mode: str):
        super().__init__(root, "atomic_fence")
        if mode not in MODES:
            raise ValueError("unknown overlap mode")
        self.mode = mode

    def initialize(self, content: bytes) -> None:
        super().initialize(content)
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute("CREATE TABLE commit_witnesses (revision INTEGER PRIMARY KEY, "
                               "requested_epoch INTEGER NOT NULL, active_epoch INTEGER NOT NULL, request_id TEXT NOT NULL)")
            connection.execute("COMMIT")
        finally:
            connection.close()

    def _decision(self, connection, epoch: int, key: str, content: bytes | None) -> dict:
        active = self._active_epoch(connection)
        if epoch > active:
            answer = response("future_epoch", epoch, key)
        else:
            prior = connection.execute("SELECT operation, payload, revision, approved_sha256 FROM requests "
                                       "WHERE epoch=? AND request_id=?", (epoch, key)).fetchone()
            if prior is not None:
                same = prior[0] == ("revoke" if content is None else "update") and prior[1] == content
                answer = response("replayed", epoch, key, prior[2], prior[3]) if same else response("conflict", epoch, key)
            elif epoch < active:
                answer = response("epoch_retired", epoch, key)
            else:
                answer = None
        return {"observed_epoch": active, "decision": "allowed" if answer is None else answer["status"], "response": answer}

    def _read_decision(self, epoch: int, key: str, content: bytes | None) -> dict:
        connection = self._connect()
        try:
            connection.execute("BEGIN")
            return self._decision(connection, epoch, key, content)
        finally:
            # The diagnostic read scopes end before a later write begins.
            connection.close()

    def _write(self, connection, epoch: int, key: str, content: bytes | None) -> dict:
        # All modes observe the epoch inside the write transaction. The weak
        # modes deliberately do not use this instrumentation reading as a gate.
        observed_epoch = self._active_epoch(connection)
        before = self._row(connection)
        after = StoredApproval(before.revision + 1, None if content is None else digest(content),
                               before.content if content is None else content)
        operation = "revoke" if content is None else "update"
        connection.execute("UPDATE publication SET revision=?, approved_sha256=?, content=? WHERE id=1",
                           (after.revision, after.approved_sha256, after.content))
        connection.execute("INSERT INTO effects VALUES (?, ?, ?, ?, ?)",
                           (after.revision, epoch, key, operation, after.approved_sha256))
        connection.execute("INSERT INTO requests VALUES (?, ?, ?, ?, ?, ?)",
                           (epoch, key, operation, content, after.revision, after.approved_sha256))
        connection.execute("INSERT INTO commit_witnesses VALUES (?, ?, ?, ?)",
                           (after.revision, epoch, observed_epoch, key))
        return response("committed", epoch, key, after.revision, after.approved_sha256)

    def publish_overlap(self, epoch: int, key: str, content: bytes | None, *,
                        checkpoint: Checkpoint = lambda stage: None,
                        event: Event = lambda kind, **fields: None) -> dict:
        validate_epoch(epoch)
        validate_request(key, content)
        connection = None
        try:
            if self.mode == "transactional_admission":
                connection = self._connect()
                connection.execute("BEGIN IMMEDIATE")
                admission = self._decision(connection, epoch, key, content)
                origin = "transaction"
            else:
                admission = self._read_decision(epoch, key, content)
                origin = "read"
            event("admission", origin=origin, observed_epoch=admission["observed_epoch"], decision=admission["decision"])
            if admission["response"] is not None:
                return admission["response"]
            checkpoint("after_admission")
            if self.mode == "cached_admission":
                final, origin = admission, "cached"
            elif connection is not None:
                final, origin = self._decision(connection, epoch, key, content), "transaction"
            else:
                final, origin = self._read_decision(epoch, key, content), "read"
            event("final_decision", origin=origin, observed_epoch=final["observed_epoch"], decision=final["decision"])
            checkpoint("after_final_check")
            if final["response"] is not None:
                return final["response"]
            if connection is None:
                connection = self._connect()
                connection.execute("BEGIN IMMEDIATE")
            answer = self._write(connection, epoch, key, content)
            checkpoint("before_commit")
            connection.execute("COMMIT")
            checkpoint("after_commit")
            return answer
        finally:
            if connection is not None:
                connection.close()

    def _probe_connection(self):
        connection = sqlite3.connect(self.database.resolve().as_uri() + "?mode=rw", uri=True,
                                     isolation_level=None, timeout=0)
        try:
            mode = connection.execute("PRAGMA journal_mode").fetchone()[0]
            connection.execute("PRAGMA synchronous=FULL")
            level = connection.execute("PRAGMA synchronous").fetchone()[0]
            timeout = connection.execute("PRAGMA busy_timeout").fetchone()[0]
            if mode != "delete" or level != 2 or timeout != 0:
                raise ValueError("nonblocking rollback-mode probe settings unavailable")
            return connection
        except BaseException:
            connection.close()
            raise

    def try_retire(self, target_epoch: int) -> dict:
        validate_epoch(target_epoch)
        connection = self._probe_connection()
        base = {"target_epoch": target_epoch, "busy_timeout_ms": 0, "sqlite_errorcode": None, "sqlite_errorname": None}
        try:
            try:
                connection.execute("BEGIN IMMEDIATE")
            except sqlite3.OperationalError as exc:
                # Only this precise BEGIN failure is measured as a deferral.
                if getattr(exc, "sqlite_errorcode", None) != sqlite3.SQLITE_BUSY:
                    raise
                return {**base, "status": "busy", "active_epoch": None,
                        "sqlite_errorcode": exc.sqlite_errorcode, "sqlite_errorname": exc.sqlite_errorname}
            active = self._active_epoch(connection)
            if target_epoch == active:
                connection.execute("ROLLBACK")
                return {**base, "status": "already_retired", "active_epoch": active}
            if target_epoch != active + 1:
                raise ValueError("retirement must target current or next epoch")
            connection.execute("UPDATE namespace SET active_epoch=? WHERE id=1", (target_epoch,))
            connection.execute("DELETE FROM requests WHERE epoch<?", (target_epoch,))
            connection.execute("COMMIT")
            return {**base, "status": "retired", "active_epoch": target_epoch}
        finally:
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
            witnesses = [dict(zip(("revision", "requested_epoch", "active_epoch", "request_id"), row))
                         for row in connection.execute("SELECT revision, requested_epoch, active_epoch, request_id FROM commit_witnesses ORDER BY revision")]
            connection.execute("COMMIT")
            return {"state": state, "active_epoch": active, "effects": effects, "receipts": receipts, "commit_witnesses": witnesses}
        finally:
            connection.close()
