"""Typed historical receipt summaries with split or atomic migration."""
from __future__ import annotations

from pathlib import Path

from src.publication_store import Checkpoint, StoredApproval, digest
from src.retirement_store import RetirementPublicationStore, response, validate_epoch
from src.retry_store import validate_request

MODES = ("retain_full", "drop_receipts", "split_summary", "atomic_summary")
STAGES = ("before_change", "after_fence_cleanup", "after_summary", "after_commit")
SUMMARY_COLUMNS = ("epoch", "request_id", "operation", "payload_sha256", "revision")


def intent_fingerprint(content: bytes | None) -> str | None:
    return None if content is None else digest(content)


class CompactionPublicationStore(RetirementPublicationStore):
    def __init__(self, root: Path, mode: str):
        super().__init__(root, "atomic_fence")
        if mode not in MODES:
            raise ValueError("unknown compaction mode")
        self.mode = mode

    def initialize(self, content: bytes) -> None:
        super().initialize(content)
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                "CREATE TABLE summaries (epoch INTEGER NOT NULL, request_id TEXT NOT NULL, "
                "operation TEXT NOT NULL CHECK(operation IN ('update','revoke')), payload_sha256 TEXT, "
                "revision INTEGER NOT NULL CHECK(revision>0), PRIMARY KEY(epoch,request_id), "
                "CHECK((operation='update' AND payload_sha256 IS NOT NULL AND length(payload_sha256)=64) "
                "OR (operation='revoke' AND payload_sha256 IS NULL)))"
            )
            connection.execute("COMMIT")
        finally:
            connection.close()

    def publish(self, epoch: int, key: str, content: bytes | None) -> dict:
        validate_epoch(epoch)
        operation = validate_request(key, content)
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            active = self._active_epoch(connection)
            if epoch > active:
                return response("future_epoch", epoch, key)
            full = connection.execute(
                "SELECT operation, payload, revision, approved_sha256 FROM requests WHERE epoch=? AND request_id=?",
                (epoch, key),
            ).fetchone()
            compact = connection.execute(
                "SELECT operation, payload_sha256, revision FROM summaries WHERE epoch=? AND request_id=?",
                (epoch, key),
            ).fetchone()
            if full is not None and compact is not None:
                raise ValueError("ambiguous full and compact request authority")
            if full is not None:
                same = full[0] == operation and full[1] == content
                return response("replayed", epoch, key, full[2], full[3]) if same else response("conflict", epoch, key)
            if compact is not None:
                same = compact[0] == operation and compact[1] == intent_fingerprint(content)
                approved = compact[1] if compact[0] == "update" else None
                return response("replayed", epoch, key, compact[2], approved) if same else response("conflict", epoch, key)
            if epoch < active:
                return response("outcome_unavailable", epoch, key)
            before = self._row(connection)
            after = StoredApproval(before.revision + 1, None if content is None else digest(content),
                                   before.content if content is None else content)
            connection.execute("UPDATE publication SET revision=?, approved_sha256=?, content=? WHERE id=1",
                               (after.revision, after.approved_sha256, after.content))
            connection.execute("INSERT INTO effects VALUES (?, ?, ?, ?, ?)",
                               (after.revision, epoch, key, operation, after.approved_sha256))
            connection.execute("INSERT INTO requests VALUES (?, ?, ?, ?, ?, ?)",
                               (epoch, key, operation, content, after.revision, after.approved_sha256))
            connection.execute("COMMIT")
            return response("committed", epoch, key, after.revision, after.approved_sha256)
        finally:
            # Closing an unresolved read-only transaction releases it. Any write
            # exception rolls back; a returned historical receipt never commits.
            connection.close()

    def compact_to(self, target: int, *, checkpoint: Checkpoint = lambda stage: None) -> dict:
        validate_epoch(target)
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            active = self._active_epoch(connection)
            if target == active:
                return {"status": "already_compacted", "active_epoch": active}
            if target != active + 1:
                raise ValueError("compaction must target current or next epoch")
            full = connection.execute(
                "SELECT epoch, request_id, operation, payload, revision FROM requests WHERE epoch<? ORDER BY epoch,request_id",
                (target,),
            ).fetchall()
            prepared = [(epoch, key, operation, intent_fingerprint(payload), revision)
                        for epoch, key, operation, payload, revision in full]
            checkpoint("before_change")
            connection.execute("UPDATE namespace SET active_epoch=? WHERE id=1", (target,))
            if self.mode != "retain_full":
                connection.execute("DELETE FROM requests WHERE epoch<?", (target,))
            if self.mode == "split_summary":
                connection.execute("COMMIT")
            checkpoint("after_fence_cleanup")
            if self.mode == "split_summary":
                connection.execute("BEGIN IMMEDIATE")
            if self.mode in {"split_summary", "atomic_summary"}:
                connection.executemany("INSERT INTO summaries VALUES (?, ?, ?, ?, ?)", prepared)
            checkpoint("after_summary")
            connection.execute("COMMIT")
            checkpoint("after_commit")
            return {"status": "compacted", "active_epoch": target}
        finally:
            # Declared worker exits bypass this normal close path. Prepared
            # summaries are process memory and cannot repair a committed gap.
            connection.close()

    def inspect(self) -> dict:
        connection = self._connect()
        try:
            connection.execute("BEGIN")
            result = {"state": self._row(connection), "active_epoch": self._active_epoch(connection)}
            for table, columns in (
                ("effects", ("revision", "epoch", "request_id", "operation", "approved_sha256")),
                ("requests", ("epoch", "request_id", "operation", "payload", "revision", "approved_sha256")),
                ("summaries", SUMMARY_COLUMNS),
            ):
                order = "revision" if table == "effects" else "epoch, request_id"
                rows = connection.execute("SELECT " + ", ".join(columns) + " FROM " + table + " ORDER BY " + order)
                result["receipts" if table == "requests" else table] = [dict(zip(columns, row)) for row in rows]
            result["summary_columns"] = [row[1] for row in connection.execute("PRAGMA table_info(summaries)")]
            connection.execute("COMMIT")
            return result
        finally:
            connection.close()
