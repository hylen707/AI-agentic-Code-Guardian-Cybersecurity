"""Receipt migration source scopes under a cooperating concurrent publisher."""
from __future__ import annotations

import sqlite3
from collections.abc import Callable
from pathlib import Path

from src.compaction_store import CompactionPublicationStore, SUMMARY_COLUMNS, intent_fingerprint
from src.overlap_store import OverlapPublicationStore
from src.publication_store import Checkpoint, StoredApproval, digest
from src.retirement_store import response, validate_epoch
from src.retry_store import validate_request

MODES = ("cached_selection", "separate_refresh", "transactional_selection", "validated_selection")
STAGES = ("after_selection", "after_refresh", "before_commit", "after_commit")
Event = Callable[..., None]


class SelectionPublicationStore(CompactionPublicationStore):
    def __init__(self, root: Path, mode: str):
        super().__init__(root, "atomic_summary")
        if mode not in MODES:
            raise ValueError("unknown selection mode")
        self.selection_mode = mode

    def initialize(self, content: bytes) -> None:
        super().initialize(content)
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute("CREATE TABLE publication_witnesses (revision INTEGER PRIMARY KEY, "
                               "requested_epoch INTEGER NOT NULL, active_epoch INTEGER NOT NULL, request_id TEXT NOT NULL)")
            connection.execute("CREATE TABLE migration_witness (id INTEGER PRIMARY KEY CHECK(id=1), "
                               "target_epoch INTEGER NOT NULL, selected_revision INTEGER NOT NULL, write_revision INTEGER NOT NULL, "
                               "selected_count INTEGER NOT NULL, write_count INTEGER NOT NULL)")
            connection.execute("COMMIT")
        finally:
            connection.close()

    def _probe_connection(self):
        return OverlapPublicationStore._probe_connection(self)

    def _selection(self, connection, target):
        return {"active_epoch": self._active_epoch(connection), "current_revision": self._row(connection).revision,
                "rows": connection.execute("SELECT epoch,request_id,operation,payload,revision,approved_sha256 "
                                           "FROM requests WHERE epoch<? ORDER BY epoch,request_id", (target,)).fetchall()}

    def _read_selection(self, target):
        connection = self._probe_connection()
        try:
            connection.execute("BEGIN")
            return self._selection(connection, target)
        finally:
            connection.close()

    @staticmethod
    def describe(selection):
        receipts = [{"epoch": epoch, "request_id": key, "operation": operation,
                     "payload_sha256": intent_fingerprint(payload), "revision": revision, "approved_sha256": approved}
                    for epoch, key, operation, payload, revision, approved in selection["rows"]]
        return {"active_epoch": selection["active_epoch"], "current_revision": selection["current_revision"], "receipts": receipts}

    def migrate(self, target: int, *, checkpoint: Checkpoint = lambda stage: None,
                event: Event = lambda kind, **fields: None):
        validate_epoch(target)
        connection = None
        try:
            if self.selection_mode == "transactional_selection":
                connection = self._probe_connection()
                connection.execute("BEGIN IMMEDIATE")
                initial = self._selection(connection, target)
                origin = "transaction"
            else:
                initial, origin = self._read_selection(target), "read"
            if target == initial["active_epoch"]:
                return {"status": "already_migrated", "active_epoch": target, "target_epoch": target}
            if target != initial["active_epoch"] + 1:
                raise ValueError("migration must target current or next epoch")
            event("selection", scope="initial", origin=origin, **self.describe(initial))
            checkpoint("after_selection")
            if self.selection_mode == "separate_refresh":
                selected, origin = self._read_selection(target), "read"
            elif connection is not None:
                selected, origin = self._selection(connection, target), "transaction"
            else:
                selected, origin = initial, "cached"
            event("selection", scope="final", origin=origin, **self.describe(selected))
            checkpoint("after_refresh")
            if connection is None:
                connection = self._probe_connection()
                connection.execute("BEGIN IMMEDIATE")
            observed = self._selection(connection, target)
            matched = selected == observed
            event("validation", matched=matched, observed=self.describe(observed))
            if self.selection_mode == "validated_selection" and not matched:
                connection.execute("ROLLBACK")
                event("selection_changed", transaction_rolled_back=True)
                return {"status": "stale_selection", "active_epoch": observed["active_epoch"], "target_epoch": target}
            if observed["active_epoch"] != target - 1:
                raise ValueError("migration namespace changed before write")
            # All arms observe the complete current source for instrumentation.
            # Only validated selection uses that comparison as an admission gate.
            connection.execute("UPDATE namespace SET active_epoch=? WHERE id=1", (target,))
            connection.execute("DELETE FROM requests WHERE epoch<?", (target,))
            compact = [(epoch, key, op, intent_fingerprint(payload), revision)
                       for epoch, key, op, payload, revision, approved in selected["rows"]]
            connection.executemany("INSERT INTO summaries VALUES (?, ?, ?, ?, ?)", compact)
            connection.execute("INSERT INTO migration_witness VALUES (1,?,?,?,?,?)",
                               (target, selected["current_revision"], observed["current_revision"],
                                len(selected["rows"]), len(observed["rows"])))
            checkpoint("before_commit")
            connection.execute("COMMIT")
            checkpoint("after_commit")
            return {"status": "migrated", "active_epoch": target, "target_epoch": target}
        finally:
            if connection is not None:
                connection.close()

    def publish_once(self, epoch: int, key: str, content: bytes | None, *,
                     checkpoint: Checkpoint = lambda stage: None,
                     event: Event = lambda kind, **fields: None):
        validate_epoch(epoch)
        operation = validate_request(key, content)
        connection = self._probe_connection()
        try:
            try:
                connection.execute("BEGIN IMMEDIATE")
            except sqlite3.OperationalError as error:
                if getattr(error, "sqlite_errorcode", None) != sqlite3.SQLITE_BUSY:
                    raise
                event("writer_busy", at="begin_immediate", sqlite_errorcode=error.sqlite_errorcode,
                      sqlite_errorname=error.sqlite_errorname, busy_timeout_ms=0)
                return response("busy", epoch, key)
            active, before = self._active_epoch(connection), self._row(connection)
            full = connection.execute("SELECT operation,payload,revision,approved_sha256 FROM requests "
                                      "WHERE epoch=? AND request_id=?", (epoch, key)).fetchone()
            compact = connection.execute("SELECT operation,payload_sha256,revision FROM summaries "
                                         "WHERE epoch=? AND request_id=?", (epoch, key)).fetchone()
            if full is not None and compact is not None:
                raise ValueError("ambiguous historical authority")
            kind = "full" if full is not None else "compact" if compact is not None else "none"
            if epoch > active:
                result = response("future_epoch", epoch, key)
            elif full is not None:
                same = full[0] == operation and full[1] == content
                result = response("replayed", epoch, key, full[2], full[3]) if same else response("conflict", epoch, key)
            elif compact is not None:
                same = compact[0] == operation and compact[1] == intent_fingerprint(content)
                approved = compact[1] if compact[0] == "update" else None
                result = response("replayed", epoch, key, compact[2], approved) if same else response("conflict", epoch, key)
            elif epoch < active:
                result = response("outcome_unavailable", epoch, key)
            else:
                result = None
            event("publication_view", requested_epoch=epoch, observed_epoch=active, current_revision=before.revision,
                  receipt_kind=kind, decision="new" if result is None else result["status"])
            if result is not None:
                return result
            after = StoredApproval(before.revision + 1, None if content is None else digest(content),
                                   before.content if content is None else content)
            connection.execute("UPDATE publication SET revision=?,approved_sha256=?,content=? WHERE id=1",
                               (after.revision, after.approved_sha256, after.content))
            connection.execute("INSERT INTO effects VALUES (?,?,?,?,?)", (after.revision, epoch, key, operation, after.approved_sha256))
            connection.execute("INSERT INTO requests VALUES (?,?,?,?,?,?)", (epoch, key, operation, content, after.revision, after.approved_sha256))
            connection.execute("INSERT INTO publication_witnesses VALUES (?,?,?,?)", (after.revision, epoch, active, key))
            checkpoint("before_commit")
            connection.execute("COMMIT")
            checkpoint("after_commit")
            return response("committed", epoch, key, after.revision, after.approved_sha256)
        finally:
            connection.close()

    def inspect(self):
        connection = self._connect()
        try:
            connection.execute("BEGIN")
            result = {"state": self._row(connection), "active_epoch": self._active_epoch(connection)}
            tables = (
                ("effects", ("revision", "epoch", "request_id", "operation", "approved_sha256")),
                ("requests", ("epoch", "request_id", "operation", "payload", "revision", "approved_sha256")),
                ("summaries", SUMMARY_COLUMNS),
                ("publication_witnesses", ("revision", "requested_epoch", "active_epoch", "request_id")),
            )
            for table, columns in tables:
                order = "epoch,request_id" if table in {"requests", "summaries"} else "revision"
                rows = connection.execute("SELECT "+",".join(columns)+" FROM "+table+" ORDER BY "+order)
                result["receipts" if table == "requests" else table] = [dict(zip(columns, row)) for row in rows]
            columns = ("target_epoch", "selected_revision", "write_revision", "selected_count", "write_count")
            row = connection.execute("SELECT "+",".join(columns)+" FROM migration_witness WHERE id=1").fetchone()
            result["migration_witness"] = None if row is None else dict(zip(columns, row))
            result["summary_columns"] = [row[1] for row in connection.execute("PRAGMA table_info(summaries)")]
            connection.execute("COMMIT")
            return result
        finally:
            connection.close()
