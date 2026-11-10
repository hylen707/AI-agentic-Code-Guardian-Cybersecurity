"""Finite invocation budgets over the unchanged receipt-selection scopes."""
from __future__ import annotations

from pathlib import Path

from src.publication_store import Checkpoint
from src.selection_store import Event, SelectionPublicationStore

MODES = ("validated_budget", "transactional_first", "validated_fallback")


def selection_scope(mode: str, budget: int, attempt: int) -> str:
    if mode not in MODES:
        raise ValueError("unknown progress policy")
    if type(budget) is not int or type(attempt) is not int or not 1 <= attempt <= budget:
        raise ValueError("positive integer attempt within invocation budget required")
    locked = mode == "transactional_first" or (mode == "validated_fallback" and attempt == budget)
    return "transactional_selection" if locked else "validated_selection"


class ProgressPublicationStore(SelectionPublicationStore):
    def __init__(self, root: Path, mode: str, budget: int):
        selection_scope(mode, budget, 1)
        super().__init__(root, "validated_selection")
        self.progress_mode, self.budget = mode, budget

    def migrate_attempt(self, attempt: int, *, checkpoint: Checkpoint = lambda stage: None,
                        event: Event = lambda kind, **fields: None):
        scope = selection_scope(self.progress_mode, self.budget, attempt)
        self.selection_mode = scope
        event("attempt_plan", policy=self.progress_mode, budget=self.budget, attempt=attempt, selection_scope=scope)
        return self.migrate(2, checkpoint=checkpoint, event=event)


def publication_value(pattern: str, index: int) -> bytes | None:
    if pattern not in ("updates", "revocations") or type(index) is not int or index < 1:
        raise ValueError("declared value pattern and positive intent index required")
    values = (b"approved=version-b\n", b"", "approved=안전 ✓\n".encode())
    return None if pattern == "revocations" else values[(index-1) % len(values)]
