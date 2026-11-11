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
from experiments.run_restart_comparison import ROOT, SOURCES, assess, load_cases, run_case, summarize
from experiments.verify_restart_results import evaluate, load_manifest, recount, verify
from src.restart_store import MODES, RestartPublicationStore

DATASET = ROOT/"experiments/tasks/restart-eval-v1/tasks.json"


def case(budget=2,schedule="after_stale",pattern="updates"):
    return dict(case_id="unit",budget=budget,schedule=schedule,pattern=pattern)


class RestartStoreTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory(prefix="codeguardian-restart-unit-")
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.serial = 0

    def store(self,mode="reserved_reconcile",budget=1):
        self.serial+=1
        store = RestartPublicationStore(self.root/str(self.serial),mode,budget)
        store.initialize(b"approved=version-a\n")
        store.publish(1,"seed-a",b"approved=version-b\n")
        store.publish(1,"seed-b",None)
        return store

    @staticmethod
    def fail_at(target):
        def checkpoint(stage):
            if stage==target:
                raise RuntimeError("injected "+stage)
        return checkpoint

    def test_invalid_mode_budget_and_generation(self):
        for mode,budget in (("bad",1),("reserved_reconcile",True),("reserved_reconcile",0),("reserved_reconcile",2**63)):
            with self.assertRaises(ValueError):
                RestartPublicationStore(self.root,mode,budget)
        store = self.store()
        for generation in (True,0,1.5,2**63):
            with self.assertRaises(ValueError):
                store.run_job(generation)
        self.assertFalse(store.inspect()["admissions"])

    def test_restart_cannot_change_fixed_budget_or_policy(self):
        store = self.store()
        before = store.inspect()
        for mode,budget in (("reserved_reconcile",2),("post_accounting",1)):
            changed = RestartPublicationStore(store.root,mode,budget)
            with self.assertRaises(ValueError):
                changed.run_job(2)
        self.assertEqual(store.inspect(),before)

    def test_reserved_admission_survives_exit_before_selection(self):
        store = self.store()
        with self.assertRaises(RuntimeError):
            store.run_job(1,checkpoint=self.fail_at("after_admission"))
        reopened = RestartPublicationStore(store.root,"reserved_reconcile",1)
        result = reopened.run_job(2)
        self.assertEqual(result["status"],"budget_exhausted")
        observed = reopened.inspect()
        self.assertEqual((observed["active_epoch"],observed["job"]["used"],len(observed["admissions"])),(1,1,1))
        self.assertEqual(len(observed["receipts"]),2)

    def test_volatile_admission_is_regranted_after_restart(self):
        store = self.store("volatile_budget")
        with self.assertRaises(RuntimeError):
            store.run_job(1,checkpoint=self.fail_at("after_admission"))
        reopened = RestartPublicationStore(store.root,"volatile_budget",1)
        self.assertEqual(reopened.run_job(2)["status"],"completed")
        self.assertEqual(len(reopened.inspect()["admissions"]),2)
        self.assertEqual(reopened.inspect()["job"]["used"],0)

    def test_post_accounting_loses_charge_before_accounting(self):
        store = self.store("post_accounting")
        with self.assertRaises(RuntimeError):
            store.run_job(1,checkpoint=self.fail_at("after_admission"))
        self.assertEqual(store.inspect()["job"]["used"],0)
        reopened = RestartPublicationStore(store.root,"post_accounting",1)
        self.assertEqual(reopened.run_job(2)["status"],"completed")
        self.assertEqual((len(reopened.inspect()["admissions"]),reopened.inspect()["job"]["used"]),(2,1))

    def test_limit_first_misreports_committed_target_after_lost_result(self):
        store = self.store("reserved_limit_first")
        with self.assertRaises(RuntimeError):
            store.run_job(1,checkpoint=self.fail_at("after_commit"))
        reopened = RestartPublicationStore(store.root,"reserved_limit_first",1)
        result = reopened.run_job(2)
        self.assertEqual((result["status"],result["active_epoch"]),("budget_exhausted",2))
        self.assertEqual(len(reopened.inspect()["summaries"]),2)

    def test_reconciliation_recovers_commit_without_another_admission(self):
        store = self.store()
        with self.assertRaises(RuntimeError):
            store.run_job(1,checkpoint=self.fail_at("after_commit"))
        reopened = RestartPublicationStore(store.root,"reserved_reconcile",1)
        self.assertEqual(reopened.run_job(2)["status"],"completed")
        self.assertEqual(len(reopened.inspect()["admissions"]),1)

    def test_completion_does_not_consult_observers(self):
        store = self.store()
        store.run_job(1)
        connection = store._connect()
        try:
            connection.execute("DROP TABLE attempt_admissions")
            connection.execute("DROP TABLE migration_witness")
        finally:
            connection.close()
        reopened = RestartPublicationStore(store.root,"reserved_reconcile",1)
        self.assertEqual(reopened.run_job(2)["status"],"completed")

    def test_before_commit_failure_rolls_back_but_keeps_reservation(self):
        store = self.store()
        with self.assertRaises(RuntimeError):
            store.run_job(1,checkpoint=self.fail_at("before_commit"))
        observed = store.inspect()
        self.assertEqual(observed["active_epoch"],1)
        self.assertIsNone(observed["migration_witness"])
        self.assertEqual(observed["job"]["used"],1)
        self.assertEqual(store.publish_once(1,"later",b"B")["status"],"committed")

    def test_repeated_staleness_preserves_all_receipts_within_budget(self):
        store = self.store(budget=2)
        serial = 0
        def checkpoint(stage):
            nonlocal serial
            if stage=="after_selection":
                serial+=1
                store.publish_once(1,"item-"+str(serial),None)
        result = store.run_job(1,checkpoint=checkpoint)
        self.assertEqual(result["status"],"budget_exhausted")
        observed = store.inspect()
        self.assertEqual((len(observed["admissions"]),len(observed["receipts"]),observed["state"].revision),(2,4,5))
        before = store.inspect()
        self.assertEqual(store.publish(1,"item-1",None)["revision"],4)
        self.assertEqual(store.inspect(),before)

    def test_admission_writer_busy_remains_an_error(self):
        store = self.store()
        connection = store._probe_connection()
        connection.execute("BEGIN IMMEDIATE")
        try:
            with self.assertRaises(sqlite3.OperationalError) as caught:
                store.run_job(1)
            self.assertEqual(caught.exception.sqlite_errorcode,5)
        finally:
            connection.close()
        self.assertFalse(store.inspect()["admissions"])

    def test_worker_rejects_resume_from_another_generation(self):
        store = self.store()
        command = [sys.executable,str(ROOT/"experiments/restart_worker.py"),"--root",str(store.root),"--mode","reserved_reconcile","--budget","1","--generation","2","--cut","none"]
        process = subprocess.Popen(command,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
        try:
            prefix = wait_for_pause(process,"after_selection",5)
            pause = json.loads(prefix.splitlines()[-1])
            self.assertEqual(pause["generation"],2)
            binding = {k:v for k,v in pause.items() if k not in ("seq","kind")};binding["generation"]=1
            _,errors = process.communicate(input=(json.dumps({"command":"resume",**binding})+"\n").encode(),timeout=5)
            self.assertNotEqual(process.returncode,0)
            self.assertIn(b"exact generation",errors)
        finally:
            if process.poll() is None:
                process.kill();process.communicate(timeout=5)
        self.assertEqual(store.inspect()["active_epoch"],1)
        self.assertEqual(store.inspect()["job"]["used"],1)


class RestartEvidenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cases = load_cases(DATASET)
        cls.rows = {}
        choices = (("volatile_budget",2,"after_stale"),("post_accounting",2,"after_stale"),
                   ("reserved_limit_first",1,"after_commit"),("reserved_reconcile",1,"after_commit"),
                   ("reserved_reconcile",1,"after_admission"),("reserved_reconcile",2,"before_commit"),
                   ("volatile_budget",2,"after_accounting"),("post_accounting",2,"after_accounting"))
        for mode,budget,schedule in choices:
            declaration = next(c for c in cls.cases if c["budget"]==budget and c["schedule"]==schedule and c["pattern"]=="updates")
            row = run_case(declaration,mode)
            if row["status"]!="complete":
                raise AssertionError(row["error_detail"])
            cls.rows[(mode,budget,schedule)] = row

    def sample(self,key=("volatile_budget",2,"after_stale")):
        return copy.deepcopy(self.rows[key])

    def rejected(self,row):
        for check in (assess,evaluate):
            with self.subTest(check=check.__module__),self.assertRaises((ValueError,KeyError,TypeError)):
                check(row)

    def test_oracle_and_independent_replay_agree(self):
        for row in self.rows.values():
            self.assertEqual(assess(row),evaluate(row))

    def test_two_resets_allow_more_admissions_than_budget(self):
        for mode in ("volatile_budget","post_accounting"):
            row = self.sample((mode,2,"after_stale"))
            self.assertEqual((row["oracle"]["admissions"],row["oracle"]["excess_admissions"]),(4,2))
            self.assertEqual(row["oracle"]["marked_exits"],2)

    def test_false_exhaustion_is_separate_from_actual_closure(self):
        row = self.sample(("reserved_limit_first",1,"after_commit"))
        self.assertTrue(row["oracle"]["actual_completed"])
        self.assertFalse(row["oracle"]["reported_completed"])
        self.assertTrue(row["oracle"]["false_exhausted"])
        self.assertEqual(row["oracle"]["missing_authority"],0)

    def test_conservative_charge_prevents_unperformed_second_exit(self):
        row = run_case(case(1,"after_stale"),"reserved_reconcile")
        self.assertEqual(row["status"],"complete")
        self.assertEqual(len(row["invocations"]),2)
        self.assertEqual(row["invocations"][-1]["cut"],"after_stale")
        self.assertEqual(row["oracle"]["marked_exits"],1)
        self.assertEqual(row["oracle"]["admissions"],1)

    def test_accounted_charge_survives_only_in_durable_mode(self):
        volatile = self.sample(("volatile_budget",2,"after_accounting"))
        durable = self.sample(("post_accounting",2,"after_accounting"))
        self.assertEqual((volatile["oracle"]["admissions"],durable["oracle"]["admissions"]),(3,2))

    def test_wrong_generation_resume_is_rejected_even_with_valid_json(self):
        row = self.sample()
        row["invocations"][0]["barriers"][0]["resume"]["generation"] = 2
        self.rejected(row)

    def test_wrong_exit_code_is_not_a_planned_cut(self):
        row = self.sample();row["invocations"][0]["returncode"]=1
        self.rejected(row)

    def test_unmarked_exit_cannot_match_a_cut(self):
        row = self.sample();child=row["invocations"][0]
        child["events"] = [e for e in child["events"] if e["kind"]!="planned_exit"]
        child["stdout"] = ''.join(json.dumps(e)+'\n' for e in child["events"])
        self.rejected(row)

    def test_changed_admission_counter_is_rejected(self):
        row = self.sample();row["invocations"][1]["before"]["admissions"][0]["persisted_after"]=1
        self.rejected(row)

    def test_changed_job_binding_is_rejected(self):
        row = self.sample();row["stop"]["job"]["budget"]=3
        self.rejected(row)

    def test_hidden_extra_invocation_is_rejected(self):
        row = self.sample();row["invocations"].append(copy.deepcopy(row["invocations"][-1]))
        self.rejected(row)

    def test_missing_publisher_is_rejected(self):
        row = self.sample();row["publishers"].pop()
        self.rejected(row)

    def test_changed_publisher_epoch_is_rejected(self):
        row = self.sample();row["publishers"][0]["request"]["epoch"]=2
        self.rejected(row)

    def test_wrong_historical_reply_is_counted_as_failure(self):
        row = self.sample();row["queries"][2]["original_response"]["revision"]=999
        left,right = assess(row),evaluate(row)
        self.assertEqual(left,right)
        self.assertEqual(right["false_history"],1)
        self.assertFalse(right["query_results_correct"])

    def test_changed_intent_success_is_false_history(self):
        row = self.sample();row["queries"][2]["changed_response"]=row["queries"][2]["original_response"]
        self.assertEqual(assess(row),evaluate(row))
        self.assertEqual(evaluate(row)["false_history"],1)

    def test_duplicate_manifest_semantics_are_rejected(self):
        data = json.loads(DATASET.read_text());data["cases"][1]["pattern"]="updates"
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/"tasks.json";path.write_text(json.dumps(data))
            for load in (load_cases,load_manifest):
                with self.assertRaises(ValueError):
                    load(path)

    def test_boolean_manifest_budget_is_rejected(self):
        data = json.loads(DATASET.read_text());data["cases"][0]["budget"]=True
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/"tasks.json";path.write_text(json.dumps(data))
            for load in (load_cases,load_manifest):
                with self.assertRaises(ValueError):
                    load(path)

    def failed_grid(self):
        return [{**c,"mode":m,"status":"infrastructure_error","oracle":None} for c in self.cases for m in MODES]

    def test_failed_runs_remain_visible_and_fail_all_criteria(self):
        records = self.failed_grid()
        left,right = summarize(records,self.cases),recount(records,self.cases)
        self.assertEqual(left,right)
        self.assertFalse(any(right["criteria"].values()))
        self.assertEqual([a["infrastructure_errors"] for a in right["arms"].values()],[28]*4)

    def test_missing_case_record_is_rejected(self):
        for count in (summarize,recount):
            with self.assertRaises(ValueError):
                count(self.failed_grid()[:-1],self.cases)

    def test_forged_oracle_is_rejected(self):
        row = self.sample();row["oracle"]["admissions"]=2
        records = [row if (r["case_id"],r["mode"])==(row["case_id"],row["mode"]) else r for r in self.failed_grid()]
        for count in (summarize,recount):
            with self.assertRaises(ValueError):
                count(records,self.cases)

    def test_consistent_wrong_reply_still_fails_scientific_criteria(self):
        row = self.sample();row["queries"][2]["original_response"]["revision"]=999;row["oracle"]=assess(row)
        records = [row if (r["case_id"],r["mode"])==(row["case_id"],row["mode"]) else r for r in self.failed_grid()]
        result = recount(records,self.cases)
        self.assertFalse(result["criteria"]["supported_evidence_and_no_unexpected_errors"])
        self.assertEqual(result["arms"]["volatile_budget"]["false_history"],1)

    def test_source_hashes_dataset_and_counter_mutations_are_rejected(self):
        records = self.failed_grid()
        with tempfile.TemporaryDirectory() as directory:
            folder=Path(directory);raw=folder/"unit-restart-v1.jsonl";raw.write_text(''.join(json.dumps(r)+'\n' for r in records))
            original=dict(dataset_sha256=hashlib.sha256(DATASET.read_bytes()).hexdigest(),source_sha256={p:hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in SOURCES},base_commit='a'*40,freeze_commit='b'*40,results_file=raw.name,summary=recount(records,self.cases))
            path=folder/"summary.json";path.write_text(json.dumps(original));self.assertFalse(verify(path,DATASET)["all_criteria_passed"])
            for mutation in ("source","dataset","counter"):
                changed=copy.deepcopy(original)
                if mutation=="source":changed["source_sha256"][SOURCES[0]]='0'*64
                elif mutation=="dataset":changed["dataset_sha256"]='0'*64
                else:changed["summary"]["arms"]["volatile_budget"]["admissions"]+=1
                path.write_text(json.dumps(changed))
                with self.assertRaises(ValueError):verify(path,DATASET)

    def test_verifier_imports_only_standard_library(self):
        tree=ast.parse((ROOT/"experiments/verify_restart_results.py").read_text());modules=[]
        for node in ast.walk(tree):
            if isinstance(node,ast.ImportFrom):modules.append(node.module.split('.')[0])
            elif isinstance(node,ast.Import):modules.extend(a.name.split('.')[0] for a in node.names)
        self.assertFalse(set(modules)-set(sys.stdlib_module_names)-{'__future__'})

    def test_process_start_failure_is_retained_as_infrastructure(self):
        with patch("experiments.run_restart_comparison.subprocess.Popen",side_effect=OSError("injected start failure")):
            row=run_case(case(1,"quiet_control"),"reserved_reconcile")
        self.assertEqual(row["status"],"infrastructure_error")
        self.assertEqual(row["error_phase"],"invocation_start")
        self.assertEqual(row["error_type"],"OSError")
        self.assertIsNone(row["oracle"])


if __name__=="__main__":
    unittest.main()
