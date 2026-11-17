import copy
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from experiments.run_resumption_comparison import run_case
from experiments.verify_resumption_results import evaluate
from src.resumption_store import ResumptionPublicationStore


class ResumptionStoreTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory(); self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)/"store"
        self.store = ResumptionPublicationStore(self.root, "reserved_reconcile", 2)
        self.store.initialize(b"A")

    def test_other_caller_completes_between_admission_and_selection(self):
        def checkpoint(stage):
            if stage == "after_admission":
                peer = ResumptionPublicationStore(self.root, "reserved_reconcile", 2)
                self.assertEqual(peer.run_job(2)["status"], "completed")
        self.assertEqual(self.store.run_job(1, checkpoint=checkpoint)["status"], "completed")
        self.assertEqual(self.store.inspect()["job"]["used"], 2)

    def test_writer_contention_is_nonterminal_and_does_not_spend_slot(self):
        connection = self.store._connect(); connection.execute("BEGIN IMMEDIATE")
        try:
            self.assertEqual(self.store.run_job(1)["status"], "retry_later")
        finally:
            connection.close()
        self.assertEqual(self.store.inspect()["job"]["used"], 0)
        self.assertEqual(self.store.run_job(2)["status"], "completed")

    def test_contention_after_reservation_preserves_the_spent_slot(self):
        connections = []
        def checkpoint(stage):
            if stage == "after_selection":
                connection = self.store._connect()
                connection.execute("BEGIN IMMEDIATE")
                connections.append(connection)
        try:
            self.assertEqual(self.store.run_job(1, checkpoint=checkpoint)["status"], "retry_later")
        finally:
            for connection in connections:
                connection.close()
        self.assertEqual(self.store.inspect()["job"]["used"], 1)
        self.assertEqual(self.store.run_job(2)["status"], "completed")
        self.assertEqual(self.store.inspect()["job"]["used"], 2)

    def test_non_busy_storage_errors_are_not_hidden(self):
        with patch.object(self.store, "_admit", side_effect=sqlite3.OperationalError("disk failure")):
            with self.assertRaises(sqlite3.OperationalError):
                self.store.run_job(1)

    def test_crash_after_commit_is_reconciled_without_extra_admission(self):
        def checkpoint(stage):
            if stage == "after_commit":
                raise RuntimeError("interruption")
        with self.assertRaises(RuntimeError):
            self.store.run_job(1, checkpoint=checkpoint)
        reopened = ResumptionPublicationStore(self.root, "reserved_reconcile", 2)
        self.assertEqual(reopened.run_job(2)["status"], "completed")
        self.assertEqual(len(reopened.inspect()["admissions"]), 1)

    def test_invalid_generation_and_unsupported_policy_are_rejected(self):
        for generation in (True, 0, 2**63):
            with self.assertRaises(ValueError):
                self.store.run_job(generation)
        weak = ResumptionPublicationStore(self.root, "volatile_budget", 2)
        with self.assertRaises(ValueError):
            weak.run_job(1)


class ResumptionEvidenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rows = [run_case(s, b, m) for s in ("admission_overtaken", "selection_overtaken", "writer_collision", "both_selected")
                    for b in (1, 2) if not (s == "both_selected" and b == 1)
                    for m in ("restart_baseline", "reconciled_resumption")]

    def test_independent_checks_retain_baseline_errors(self):
        summary = evaluate(self.rows)
        self.assertEqual(summary["restart_baseline"]["caller_errors"], 3)
        self.assertEqual(summary["reconciled_resumption"]["caller_errors"], 0)
        self.assertEqual(summary["reconciled_resumption"]["retry_later"], 2)
        self.assertEqual(summary["reconciled_resumption"]["converged_cases"], 7)

    def test_missing_duplicate_or_forged_case_is_rejected(self):
        for rows in (self.rows[:-1], self.rows+[self.rows[0]]):
            with self.assertRaises(ValueError):
                evaluate(rows)
        mutations = (
            lambda r: r["job"].update(used=99),
            lambda r: r["admissions"][0].update(persisted_after=0),
            lambda r: r["followups"][0]["response"].update(status="budget_exhausted"),
            lambda r: r["replay"].update(revision=999),
            lambda r: r["summaries"].clear(),
            lambda r: r["effects"].append(r["effects"][0]),
            lambda r: r["migration_witness"].update(write_count=0),
            lambda r: r["boundary_a"].update(generation=99),
        )
        for mutate in mutations:
            rows = copy.deepcopy(self.rows); mutate(rows[0])
            with self.assertRaises(ValueError):
                evaluate(rows)
