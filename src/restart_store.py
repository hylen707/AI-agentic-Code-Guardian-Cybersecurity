"""Budget charging and outcome reconciliation for one restarting migration job."""
from __future__ import annotations

from pathlib import Path

from src.publication_store import Checkpoint
from src.selection_store import Event, SelectionPublicationStore

MODES = ("volatile_budget", "post_accounting", "reserved_limit_first", "reserved_reconcile")
CUTS = ("after_admission", "after_stale", "after_accounting", "before_commit", "after_commit")
JOB_COLUMNS = ("policy", "budget", "target_epoch", "used")
ADMISSION_COLUMNS = ("ordinal", "generation", "attempt_number", "persisted_before", "persisted_after")


class RestartPublicationStore(SelectionPublicationStore):
    def __init__(self, root: Path, mode: str, budget: int):
        if mode not in MODES or type(budget) is not int or not 1 <= budget <= 2**63-1:
            raise ValueError("declared policy and positive SQLite-range budget required")
        super().__init__(root, "validated_selection")
        self.restart_mode, self.budget, self.local_used = mode, budget, 0

    def initialize(self, content: bytes) -> None:
        super().initialize(content)
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute("CREATE TABLE restart_job (id INTEGER PRIMARY KEY CHECK(id=1), policy TEXT NOT NULL, "
                               "budget INTEGER NOT NULL CHECK(budget>0), target_epoch INTEGER NOT NULL CHECK(target_epoch=2), "
                               "used INTEGER NOT NULL CHECK(used>=0 AND used<=budget))")
            connection.execute("INSERT INTO restart_job VALUES (1,?,?,2,0)", (self.restart_mode, self.budget))
            connection.execute("CREATE TABLE attempt_admissions (ordinal INTEGER PRIMARY KEY, generation INTEGER NOT NULL, "
                               "attempt_number INTEGER NOT NULL, persisted_before INTEGER NOT NULL, persisted_after INTEGER NOT NULL)")
            connection.execute("COMMIT")
        finally:
            connection.close()

    def _job(self, connection):
        row = connection.execute("SELECT policy,budget,target_epoch,used FROM restart_job WHERE id=1").fetchone()
        if row is None or row[:3] != (self.restart_mode, self.budget, 2):
            raise ValueError("restart changed the fixed job policy, budget or target")
        if type(row[3]) is not int or not 0 <= row[3] <= self.budget:
            raise ValueError("invalid persisted admission counter")
        return dict(zip(JOB_COLUMNS, row))

    def _used(self, job):
        return self.local_used if self.restart_mode == "volatile_budget" else job["used"]

    def _admit(self, generation: int, event: Event):
        connection = self._probe_connection()
        try:
            connection.execute("BEGIN IMMEDIATE")
            job = self._job(connection)
            active, used = self._active_epoch(connection), self._used(job)
            event("budget_view", active_epoch=active, used=used, persisted_used=job["used"],
                  counter_source="memory" if self.restart_mode == "volatile_budget" else "durable")
            limited = used >= self.budget
            if self.restart_mode == "reserved_limit_first" and limited:
                return {"status": "budget_exhausted", "active_epoch": active, "used": used, "budget": self.budget}
            if active == 2:
                return {"status": "completed", "active_epoch": active, "used": used, "budget": self.budget}
            if active != 1:
                raise ValueError("unexpected job namespace")
            if limited:
                return {"status": "budget_exhausted", "active_epoch": active, "used": used, "budget": self.budget}
            after = job["used"]
            if self.restart_mode.startswith("reserved_"):
                after += 1
                connection.execute("UPDATE restart_job SET used=? WHERE id=1", (after,))
            if self.restart_mode == "volatile_budget":
                self.local_used += 1
            cursor = connection.execute("INSERT INTO attempt_admissions (generation,attempt_number,persisted_before,persisted_after) VALUES (?,?,?,?)",
                                        (generation, used+1, job["used"], after))
            admission = dict(zip(ADMISSION_COLUMNS, (cursor.lastrowid, generation, used+1, job["used"], after)))
            connection.execute("COMMIT")
            event("admitted", **admission)
            return admission
        finally:
            connection.close()

    def _account(self, event: Event):
        connection = self._probe_connection()
        try:
            connection.execute("BEGIN IMMEDIATE")
            job = self._job(connection)
            if self.restart_mode == "post_accounting":
                if job["used"] >= self.budget:
                    raise ValueError("post-accounting counter would exceed budget")
                connection.execute("UPDATE restart_job SET used=used+1 WHERE id=1")
                job["used"] += 1
            connection.execute("COMMIT")
            used = self._used(job)
            event("accounted", used=used, persisted_used=job["used"])
            return used
        finally:
            connection.close()

    def run_job(self, generation: int, *, checkpoint: Checkpoint = lambda stage: None,
                event: Event = lambda kind, **fields: None):
        if type(generation) is not int or not 1 <= generation <= 2**63-1:
            raise ValueError("positive SQLite-range process generation required")
        while True:
            admission = self._admit(generation, event)
            if "status" in admission:
                return admission
            checkpoint("after_admission")
            answer = self.migrate(2, checkpoint=checkpoint, event=event)
            if answer["status"] not in ("migrated", "stale_selection"):
                raise ValueError("unexpected live migration result")
            event("attempt_result", response=answer)
            if answer["status"] == "stale_selection":
                checkpoint("after_stale")
            used = self._account(event)
            checkpoint("after_accounting")
            if answer["status"] == "migrated":
                return {"status": "completed", "active_epoch": 2, "used": used, "budget": self.budget}

    def inspect(self):
        # Read all application and observer tables in one snapshot. Observer
        # rows never participate in run_job's admission or completion decisions.
        connection = self._connect()
        try:
            connection.execute("BEGIN")
            state = {"state": self._row(connection), "active_epoch": self._active_epoch(connection)}
            tables = (("effects", ("revision", "epoch", "request_id", "operation", "approved_sha256"), "revision"),
                      ("requests", ("epoch", "request_id", "operation", "payload", "revision", "approved_sha256"), "epoch,request_id"),
                      ("summaries", ("epoch", "request_id", "operation", "payload_sha256", "revision"), "epoch,request_id"),
                      ("publication_witnesses", ("revision", "requested_epoch", "active_epoch", "request_id"), "revision"),
                      ("attempt_admissions", ADMISSION_COLUMNS, "ordinal"))
            for table, columns, order in tables:
                rows = connection.execute("SELECT "+",".join(columns)+" FROM "+table+" ORDER BY "+order)
                state["receipts" if table == "requests" else "admissions" if table == "attempt_admissions" else table] = [dict(zip(columns, r)) for r in rows]
            columns = ("target_epoch", "selected_revision", "write_revision", "selected_count", "write_count")
            row = connection.execute("SELECT "+",".join(columns)+" FROM migration_witness WHERE id=1").fetchone()
            state["migration_witness"] = None if row is None else dict(zip(columns, row))
            state["summary_columns"] = [r[1] for r in connection.execute("PRAGMA table_info(summaries)")]
            state["job"] = self._job(connection)
            connection.execute("COMMIT")
            return state
        finally:
            connection.close()
