"""Two-caller responses over Phase 17's unchanged durable admission ledger."""
from __future__ import annotations

import sqlite3

from src.restart_store import RestartPublicationStore


class ResumptionPublicationStore(RestartPublicationStore):
    """Keep reservations conservative; classify contention as nonterminal.

    A budget_exhausted response describes admission at its snapshot. Another
    already admitted caller may still finish. retry_later makes no state claim.
    """

    def run_job(self, generation: int, *, checkpoint=lambda stage: None,
                event=lambda kind, **fields: None):
        if type(generation) is not int or not 1 <= generation <= 2**63 - 1:
            raise ValueError("positive SQLite-range process generation required")
        if self.restart_mode != "reserved_reconcile":
            raise ValueError("simultaneous resumption requires durable reconciled admission")
        try:
            while True:
                admission = self._admit(generation, event)
                if "status" in admission:
                    return admission
                checkpoint("after_admission")
                answer = self.migrate(2, checkpoint=checkpoint, event=event)
                if answer["status"] not in ("migrated", "already_migrated", "stale_selection"):
                    raise ValueError("unexpected live migration result")
                event("attempt_result", response=answer)
                if answer["status"] == "stale_selection":
                    checkpoint("after_stale")
                self._account(event)
                checkpoint("after_accounting")
                # Re-read the durable job and target even for an overtaken caller.
                # The next admission checks completion before charging any slot.
        except sqlite3.OperationalError as error:
            if getattr(error, "sqlite_errorcode", None) != sqlite3.SQLITE_BUSY:
                raise
            event("resumption_busy", sqlite_errorcode=error.sqlite_errorcode)
            return {"status": "retry_later", "reason": "writer_busy", "budget": self.budget}
