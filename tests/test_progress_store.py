import ast
import copy
import hashlib
import json
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from experiments.run_overlap_comparison import wait_for_pause
from experiments.run_progress_comparison import ROOT, SOURCES, assess, load_cases, run_case, summarize
from experiments.verify_progress_results import evaluate, load_manifest, recount, verify
from src.progress_store import MODES, ProgressPublicationStore, publication_value, selection_scope


DATASET = ROOT/"experiments/tasks/progress-eval-v1/tasks.json"


def declaration(budget=3, publications=4, pattern="updates"):
    return dict(case_id=f"b{budget}-n{publications}-{pattern}", budget=budget, publications=publications, pattern=pattern)


class ProgressStoreTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory(prefix="codeguardian-progress-unit-")
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.serial = 0

    def store(self, mode="validated_budget", budget=3):
        self.serial += 1
        store = ProgressPublicationStore(self.root/str(self.serial), mode, budget)
        store.initialize(b"approved=version-a\n")
        store.publish(1, "seed-a", b"approved=version-b\n")
        store.publish(1, "seed-b", None)
        return store

    def intervene(self, store, attempt, value=b"new\n"):
        answers = []
        def checkpoint(stage):
            if stage == "after_selection":
                answers.append(store.publish_once(1, "item-"+str(attempt), value))
        return store.migrate_attempt(attempt, checkpoint=checkpoint), answers[0]

    def test_invalid_policy_and_noninteger_budgets(self):
        for mode, budget in (("unknown", 1), ("validated_budget", True), ("validated_budget", 0), ("validated_budget", 1.5)):
            with self.subTest(mode=mode, budget=budget), self.assertRaises(ValueError):
                ProgressPublicationStore(self.root, mode, budget)

    def test_attempt_outside_budget_has_no_effect(self):
        store = self.store(budget=2)
        before = store.inspect()
        for number in (0, 3, True, 1.0):
            with self.assertRaises(ValueError):
                store.migrate_attempt(number)
        self.assertEqual(store.inspect(), before)

    def test_repeated_stale_attempts_leave_namespace_open(self):
        store = self.store()
        for number in range(1, 4):
            answer, published = self.intervene(store, number)
            self.assertEqual((answer["status"], published["status"]), ("stale_selection", "committed"))
            current = store.inspect()
            self.assertEqual(current["active_epoch"], 1)
            self.assertEqual(len(current["receipts"]), number+2)
            self.assertFalse(current["summaries"])
            self.assertIsNone(current["migration_witness"])

    def test_fallback_last_attempt_defers_publisher_and_preserves_earlier_commits(self):
        store = self.store("validated_fallback")
        for number in (1, 2):
            self.assertEqual(self.intervene(store, number)[0]["status"], "stale_selection")
        answer, pub = self.intervene(store, 3)
        self.assertEqual((answer["status"], pub["status"]), ("migrated", "busy"))
        self.assertEqual(store.publish_once(1, "item-3", b"new\n")["status"], "outcome_unavailable")
        self.assertEqual(len(store.inspect()["summaries"]), 4)
        self.assertEqual(store.publish(1, "item-1", b"new\n")["revision"], 4)

    def test_one_attempt_fallback_locks_immediately(self):
        store = self.store("validated_fallback", 1)
        answer, pub = self.intervene(store, 1)
        self.assertEqual((answer["status"], pub["status"]), ("migrated", "busy"))
        self.assertFalse(store.inspect()["publication_witnesses"])

    def test_repeated_revocation_still_invalidates_source(self):
        store = self.store()
        for number in (1, 2, 3):
            answer, pub = self.intervene(store, number, None)
            self.assertEqual(answer["status"], "stale_selection")
            self.assertEqual(pub["revision"], number+3)
        self.assertIsNone(store.inspect()["state"].approved_sha256)

    def test_quiet_retry_compacts_all_earlier_receipts(self):
        store = self.store()
        self.intervene(store, 1, b"")
        self.intervene(store, 2, "approved=안전 ✓\n".encode())
        self.assertEqual(store.migrate_attempt(3)["status"], "migrated")
        self.assertEqual(len(store.inspect()["summaries"]), 4)
        self.assertEqual(store.publish(1, "item-1", b"")["revision"], 4)

    def test_old_replay_never_restores_current_policy(self):
        store = self.store()
        self.intervene(store, 1, b"")
        self.intervene(store, 2, None)
        store.migrate_attempt(3)
        before = store.inspect()
        self.assertEqual(store.publish(1, "item-1", b"")["status"], "replayed")
        self.assertEqual(store.publish(1, "item-1", None)["status"], "conflict")
        self.assertEqual(store.inspect(), before)
        self.assertIsNone(before["state"].approved_sha256)

    def test_migration_begin_contention_is_an_error(self):
        store = self.store("transactional_first")
        holder = store._probe_connection()
        holder.execute("BEGIN IMMEDIATE")
        try:
            with self.assertRaises(sqlite3.OperationalError) as caught:
                store.migrate_attempt(1)
            self.assertEqual(caught.exception.sqlite_errorcode, sqlite3.SQLITE_BUSY)
        finally:
            holder.close()
        self.assertEqual(store.inspect()["active_epoch"], 1)

    def test_failure_before_commit_rolls_back_and_releases_writer(self):
        store = self.store("transactional_first")
        before = store.inspect()
        def fail(stage):
            if stage == "before_commit":
                raise RuntimeError("injected before commit")
        with self.assertRaises(RuntimeError):
            store.migrate_attempt(1, checkpoint=fail)
        self.assertEqual(store.inspect(), before)
        self.assertEqual(store.publish_once(1, "after-error", b"B")["status"], "committed")

    def test_worker_rejects_resume_bound_to_another_attempt(self):
        store = self.store("validated_fallback", 2)
        command = [sys.executable, str(ROOT/"experiments/progress_worker.py"), "--root", str(store.root),
                   "--mode", "validated_fallback", "--budget", "2", "--role", "migrate", "--attempt", "2"]
        process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        try:
            prefix = wait_for_pause(process, "after_selection", 5)
            pause = json.loads(prefix.splitlines()[-1])
            self.assertEqual((pause["attempt"], pause["budget"]), (2, 2))
            _, errors = process.communicate(input=b'{"command":"resume","stage":"after_selection","role":"migrate","attempt":1,"budget":2}\n', timeout=5)
            self.assertNotEqual(process.returncode, 0)
            self.assertIn(b"exact stage, role, attempt and budget", errors)
        finally:
            if process.poll() is None:
                process.kill()
                process.communicate(timeout=5)
        self.assertEqual(store.inspect()["active_epoch"], 1)
        self.assertEqual(store.publish_once(1, "after-worker", b"B")["status"], "committed")

    def test_empty_update_and_revocation_are_different_intents(self):
        self.assertEqual(publication_value("updates", 2), b"")
        self.assertIsNone(publication_value("revocations", 2))
        for args in (("unknown", 1), ("updates", 0), ("updates", True)):
            with self.assertRaises(ValueError):
                publication_value(*args)


class ProgressEvidenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cases = load_cases(DATASET)
        cls.rows = {}
        samples = (("validated_budget", declaration()), ("validated_fallback", declaration()),
                   ("transactional_first", declaration(1, 4, "revocations")),
                   ("validated_budget", declaration(3, 2, "revocations")), ("validated_fallback", declaration(1, 1, "revocations")))
        for mode, case in samples:
            row = run_case(case, mode)
            if row["status"] != "complete":
                raise AssertionError(row["error_detail"])
            cls.rows[(mode, case["case_id"])] = row

    def sample(self, mode="validated_budget"):
        return copy.deepcopy(self.rows[(mode, declaration()["case_id"])])

    def assert_rejected(self, row):
        for check in (assess, evaluate):
            with self.subTest(check=check.__module__), self.assertRaises((ValueError, KeyError, TypeError)):
                check(row)

    def test_controller_and_independent_metrics_agree(self):
        for row in self.rows.values():
            self.assertEqual(assess(row), evaluate(row))

    def test_exhaustion_drains_remaining_requests_without_hidden_migration(self):
        row = self.sample()
        self.assertEqual(row["terminal"]["status"], "budget_exhausted")
        self.assertEqual(len(row["migrations"]), 3)
        self.assertEqual(len(row["stop"]["receipts"]), 5)
        self.assertEqual(len(row["final"]["receipts"]), 6)
        self.assertEqual(row["publishers"][-1]["phase"], "drain")

    def test_quiet_boundary_completes_on_n_plus_one(self):
        row = self.rows[("validated_budget", declaration(3, 2, "revocations")["case_id"])]
        self.assertEqual(row["terminal"]["status"], "completed")
        self.assertEqual(len(row["migrations"]), 3)
        self.assertEqual(row["oracle"]["compact_replays"], 2)
        self.assertEqual(row["oracle"]["full_replays"], 0)

    def test_fallback_budget_one_refusal_is_not_history_loss(self):
        row = self.rows[("validated_fallback", declaration(1, 1, "revocations")["case_id"])]
        self.assertEqual(row["oracle"]["committed"], 0)
        self.assertEqual(row["oracle"]["refused"], 1)
        self.assertEqual(row["oracle"]["missing_authority"], 0)
        self.assertEqual(row["oracle"]["unavailable_pairs"], 1)

    def test_wrong_historical_reply_is_counted_as_failure(self):
        row = self.sample()
        row["queries"][2]["original_response"]["revision"] += 1
        left, right = assess(row), evaluate(row)
        self.assertEqual(left, right)
        self.assertFalse(left["query_results_correct"])
        self.assertEqual(left["false_history"], 1)

    def test_changed_intent_success_is_counted_as_false_history(self):
        row = self.sample()
        row["queries"][2]["changed_response"] = row["queries"][2]["original_response"]
        self.assertEqual(assess(row), evaluate(row))
        self.assertEqual(evaluate(row)["false_history"], 1)

    def test_missing_barrier_cannot_be_repaired_by_matching_stdout(self):
        row = self.sample()
        m = row["migrations"][0]
        m["events"] = [e for e in m["events"] if e["kind"] != "paused"]
        m["stdout"] = "\n".join(json.dumps(e) for e in m["events"])+"\n"
        self.assert_rejected(row)

    def test_changed_busy_retry_identity_is_rejected(self):
        row = self.sample("validated_fallback")
        retry = next(p for p in row["publishers"] if p["phase"] == "after_busy")
        retry["request"]["epoch"] = 2
        self.assert_rejected(row)

    def test_numeric_error_code_is_required(self):
        row = self.sample("validated_fallback")
        p = next(p for p in row["publishers"] if p["response"]["status"] == "busy")
        next(e for e in p["events"] if e["kind"] == "writer_busy")["sqlite_errorcode"] = 6
        p["stdout"] = "\n".join(json.dumps(e) for e in p["events"])+"\n"
        self.assert_rejected(row)

    def test_changed_causal_prefix_is_rejected(self):
        row = self.sample()
        row["migrations"][1]["before"] = row["initial"]
        self.assert_rejected(row)

    def test_wrong_selection_scope_is_rejected(self):
        row = self.sample("validated_fallback")
        row["migrations"][-1]["selection_scope"] = "validated_selection"
        self.assert_rejected(row)

    def test_nonzero_child_exit_is_never_modeled_exhaustion(self):
        row = self.sample()
        row["migrations"][0]["returncode"] = 1
        self.assert_rejected(row)

    def test_manifest_duplicate_semantic_history_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/"tasks.json"
            data = json.loads(DATASET.read_text())
            data["cases"][1].update(budget=1, publications=0, pattern="updates")
            path.write_text(json.dumps(data))
            for load in (load_cases, load_manifest):
                with self.assertRaises(ValueError):
                    load(path)

    def test_boolean_budget_in_manifest_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/"tasks.json"
            data = json.loads(DATASET.read_text())
            data["cases"][0]["budget"] = True
            path.write_text(json.dumps(data))
            for load in (load_cases, load_manifest):
                with self.assertRaises(ValueError):
                    load(path)

    def test_missing_case_is_rejected(self):
        for summarize_it in (summarize, recount):
            with self.assertRaises(ValueError):
                summarize_it([], self.cases)

    def test_all_failed_records_remain_visible_and_fail_criteria(self):
        records = [{**c, "mode": m, "status": "infrastructure_error", "oracle": None} for c in self.cases for m in MODES]
        left, right = summarize(records, self.cases), recount(records, self.cases)
        self.assertEqual(left, right)
        self.assertFalse(any(right["criteria"].values()))
        self.assertEqual([a["infrastructure_errors"] for a in right["arms"].values()], [24]*3)

    def test_forged_oracle_is_rejected(self):
        records = [{**c, "mode": m, "status": "infrastructure_error", "oracle": None} for c in self.cases for m in MODES]
        replacement = self.sample()
        replacement["oracle"]["committed"] = 0
        records = [replacement if r["case_id"] == replacement["case_id"] and r["mode"] == replacement["mode"] else r for r in records]
        for summarize_it in (summarize, recount):
            with self.assertRaises(ValueError):
                summarize_it(records, self.cases)

    def test_consistently_recorded_bad_reply_still_fails_scientific_criteria(self):
        records = [{**c, "mode": m, "status": "infrastructure_error", "oracle": None} for c in self.cases for m in MODES]
        replacement = self.sample()
        replacement["queries"][2]["original_response"]["revision"] = 999
        replacement["oracle"] = assess(replacement)
        records = [replacement if r["case_id"] == replacement["case_id"] and r["mode"] == replacement["mode"] else r for r in records]
        result = recount(records, self.cases)
        self.assertFalse(result["criteria"]["supported_evidence_and_provenance"])
        self.assertEqual(result["arms"]["validated_budget"]["false_history"], 1)

    def test_provenance_hash_and_summary_counter_changes_are_rejected(self):
        records = [{**c, "mode": m, "status": "infrastructure_error", "oracle": None} for c in self.cases for m in MODES]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            raw = root/"unit-progress-v1.jsonl"
            raw.write_text("".join(json.dumps(r)+"\n" for r in records))
            original = {"dataset_sha256": hashlib.sha256(DATASET.read_bytes()).hexdigest(),
                        "source_sha256": {p: hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in SOURCES},
                        "base_commit": "a"*40, "freeze_commit": "b"*40, "results_file": raw.name, "summary": recount(records, self.cases)}
            path = root/"summary.json"
            path.write_text(json.dumps(original))
            self.assertFalse(verify(path, DATASET)["all_criteria_passed"])
            for kind in ("dataset", "source", "counter"):
                changed = copy.deepcopy(original)
                if kind == "dataset":
                    changed["dataset_sha256"] = "0"*64
                elif kind == "source":
                    changed["source_sha256"][SOURCES[0]] = "0"*64
                else:
                    changed["summary"]["arms"]["validated_budget"]["completed"] += 1
                path.write_text(json.dumps(changed))
                with self.assertRaises(ValueError):
                    verify(path, DATASET)

    def test_verifier_has_no_measured_module_imports(self):
        tree = ast.parse((ROOT/"experiments/verify_progress_results.py").read_text())
        imports = []
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                imports.append(node.module.split(".")[0])
            elif isinstance(node, ast.Import):
                imports.extend(a.name.split(".")[0] for a in node.names)
        self.assertFalse(set(imports)-set(sys.stdlib_module_names)-{"__future__"})

    def test_controller_retains_process_failure_as_infrastructure_record(self):
        with patch("experiments.run_progress_comparison.subprocess.Popen", side_effect=OSError("injected process start failure")):
            row = run_case(declaration(1, 0), "validated_budget")
        self.assertEqual(row["status"], "infrastructure_error")
        self.assertEqual(row["error_phase"], "migration_start")
        self.assertEqual(row["error_type"], "OSError")
        self.assertIsNone(row["oracle"])


if __name__ == "__main__":
    unittest.main()
