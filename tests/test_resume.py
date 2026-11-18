import ast
import copy
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from experiments.run_resume_comparison import DATASET, ROOT, SOURCES, Peer, load_cases, measure, run_case, summarize
from experiments.verify_resume_results import evaluate, load_manifest, recount, verify


class ResumeEvidenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cases=load_cases()
        cls.rows={}
        names=('admission_finish-b1-updates','admission_finish-b2-updates','exit_before_commit-b1-updates',
               'exit_after_commit-b1-updates','exit_stale-b2-revocations','both_selected_source_exit-b2-updates','busy_reserved_exit-b2-revocations')
        for name in names:
            case=next(c for c in cls.cases if c['case_id']==name)
            for mode in ('restart_baseline','reconciled_resumption'):
                row=run_case(case,mode)
                if row['status']!='complete':raise AssertionError(row.get('error_detail'))
                cls.rows[(name,mode)]=row

    def sample(self,name='exit_before_commit-b1-updates',mode='reconciled_resumption'):
        return copy.deepcopy(self.rows[(name,mode)])

    def declaration(self,row):
        return next(c for c in self.cases if c['case_id']==row['case_id'])

    def reject(self,row):
        with self.assertRaises((ValueError,KeyError,TypeError)):
            evaluate(row,self.declaration(row))

    def test_independent_reconstruction_matches_controller(self):
        for row in self.rows.values():
            self.assertEqual(evaluate(row,self.declaration(row)),measure(row))

    def test_exhaustion_is_observation_before_live_peer_finishes(self):
        row=self.sample('admission_finish-b1-updates')
        self.assertEqual(row['measures']['exhausted_while_peer_live'],1)
        self.assertEqual(row['measures']['exhausted_then_closed'],1)
        self.assertTrue(row['measures']['actual_completed'])
        self.assertEqual(row['measures']['response_violations'],0)

    def test_before_commit_exit_rolls_back_without_refunding(self):
        row=self.sample();m=row['measures']
        self.assertFalse(m['actual_completed']);self.assertEqual(m['admissions'],1)
        self.assertIsNone(row['final']['migration_witness'])
        self.assertEqual(len(row['final']['receipts']),3)
        self.assertEqual(m['planned_exits'],1)

    def test_after_commit_exit_keeps_target_and_receipts(self):
        row=self.sample('exit_after_commit-b1-updates')
        self.assertTrue(row['measures']['actual_completed'])
        self.assertEqual(row['measures']['admissions'],1)
        self.assertEqual(len(row['final']['summaries']),2)
        self.assertEqual(row['final']['receipts'],[])

    def test_contention_after_reservation_can_leave_no_closure_slot(self):
        row=self.sample('busy_reserved_exit-b2-revocations')
        self.assertEqual(row['measures']['admissions'],2)
        self.assertEqual(row['measures']['retry_later'],1)
        self.assertFalse(row['measures']['actual_completed'])
        self.assertEqual(row['measures']['missing_authority'],0)

    def test_publisher_can_stale_the_only_remaining_admitted_attempt(self):
        row=self.sample('both_selected_source_exit-b2-updates')
        self.assertFalse(row['measures']['actual_completed'])
        self.assertEqual(row['measures']['admissions'],2)
        self.assertEqual(row['measures']['publications'],1)
        self.assertEqual(row['measures']['query_failures'],0)

    def test_baseline_overtaken_result_remains_recorded_error(self):
        row=self.sample('admission_finish-b2-updates','restart_baseline')
        self.assertEqual(row['measures']['caller_errors'],1)
        self.assertEqual(row['measures']['normal_children'],4)

    def test_wrong_generation_resume_is_rejected(self):
        row=self.sample();next(s for s in row['steps'] if s['action']['op']=='resume')['command']['generation']=999
        self.reject(row)

    def test_wrong_attempt_resume_is_rejected(self):
        row=self.sample();next(s for s in row['steps'] if s['action']['op']=='resume')['command']['attempt_number']=999
        self.reject(row)

    def test_wrong_exit_code_is_rejected(self):
        row=self.sample();next(s for s in row['steps'] if s.get('returncode')==73)['returncode']=1
        self.reject(row)

    def test_unmarked_exit_is_rejected(self):
        row=self.sample();s=next(s for s in row['steps'] if s.get('returncode')==73)
        s['events']=[e for e in s['events'] if e['kind']!='planned_exit'];s['stdout']=''.join(json.dumps(e)+'\n' for e in s['events'])
        self.reject(row)

    def test_raw_stream_cannot_hide_recorded_event(self):
        row=self.sample();row['steps'][0]['stdout']=''
        self.reject(row)

    def test_wrong_reservation_is_rejected(self):
        row=self.sample();row['final']['job']['used']=0
        self.reject(row)

    def test_commit_after_rollback_is_rejected(self):
        row=self.sample();row['final']['active_epoch']=2
        self.reject(row)

    def test_reordered_source_publication_is_rejected(self):
        row=self.sample();row['steps'][-2],row['steps'][-3]=row['steps'][-3],row['steps'][-2]
        self.reject(row)

    def test_forged_source_request_is_rejected(self):
        row=self.sample();s=next(s for s in row['steps'] if s['action']['op']=='publish');s['request']={**s['request'],'epoch':2}
        self.reject(row)

    def test_consistent_false_answer_still_counts_as_failure(self):
        row=self.sample();step=next(s for s in row['steps'] if s['action']==dict(op='start',generation=3,pauses=[]))
        event=next(e for e in step['events'] if e['kind']=='caller_result')
        event['response']['status']='completed';event['response']['active_epoch']=2
        step['stdout']=''.join(json.dumps(e)+'\n' for e in step['events']);row['measures']=measure(row)
        self.assertEqual(evaluate(row,self.declaration(row))['response_violations'],1)

    def test_consistent_wrong_history_still_counts_as_failure(self):
        row=self.sample();row['queries'][0]['original']['revision']=999;row['measures']=measure(row)
        self.assertEqual(evaluate(row,self.declaration(row))['query_failures'],1)

    def test_duplicate_or_missing_case_rejected(self):
        failed=self.failed_grid()
        for rows in (failed[:-1],failed+[failed[0]]):
            for count in (summarize,recount):
                with self.assertRaises(ValueError):count(rows,self.cases)

    def failed_grid(self):
        return [{**c,'mode':m,'status':'infrastructure_error','measures':None,'error_type':'OSError'} for c in self.cases for m in ('restart_baseline','reconciled_resumption')]

    def test_infrastructure_failures_keep_denominators(self):
        rows=self.failed_grid();left,right=summarize(rows,self.cases),recount(rows,self.cases)
        self.assertEqual(left,right)
        self.assertEqual(right['reconciled_resumption'],dict(cases=32,infrastructure_errors=32))

    def test_process_start_failure_is_retained(self):
        with patch('experiments.run_resume_comparison.subprocess.Popen',side_effect=OSError('injected')):
            row=run_case(self.cases[0],'reconciled_resumption')
        self.assertEqual(row['status'],'infrastructure_error')
        self.assertEqual((row['error_phase'],row['error_type']),('start','OSError'))

    def test_boolean_budget_and_semantic_duplicate_rejected(self):
        original=json.loads(DATASET.read_text())
        for mutation in ('boolean','duplicate'):
            data=copy.deepcopy(original)
            if mutation=='boolean':data['cases'][0]['budget']=True
            else:data['cases'][1]['pattern']='updates'
            with tempfile.TemporaryDirectory() as directory:
                p=Path(directory)/'tasks.json';p.write_text(json.dumps(data))
                with self.assertRaises(ValueError):load_manifest(p)

    def test_worker_rejects_wrong_live_resume(self):
        from src.restart_store import RestartPublicationStore
        with tempfile.TemporaryDirectory() as directory:
            store=RestartPublicationStore(Path(directory)/'store','reserved_reconcile',1)
            store.initialize(b'A')
            peer=Peer(store.root,'reconciled_resumption',1,dict(generation=1,pauses=['after_selection']))
            try:
                first=peer.boundary();self.assertEqual(first['events'][-1]['kind'],'paused')
                command={'command':'continue',**peer.pause};command['generation']=999
                peer.process.stdin.write((json.dumps(command)+'\n').encode());peer.process.stdin.flush()
                result=peer.boundary()
                error=next(e for e in result['events'] if e['kind']=='caller_error')
                self.assertEqual(error['error_type'],'ValueError')
                self.assertEqual(store.inspect()['active_epoch'],1)
                self.assertEqual(store.inspect()['job']['used'],1)
            finally:peer.close()

    def test_provenance_raw_and_summary_mutations_are_rejected(self):
        rows=self.failed_grid()
        base='9f7621a4d92964cbeb35d9d5c6b4f0b09603b0d2'
        freeze='f87c4a11609b02a8660b4be7358cb1fc70880cec'
        with tempfile.TemporaryDirectory() as directory:
            raw=Path(directory)/'unit.jsonl';raw.write_text(''.join(json.dumps(r)+'\n' for r in rows))
            original=dict(base_commit=base,freeze_commit=freeze,results_file=raw.name,results_sha256=hashlib.sha256(raw.read_bytes()).hexdigest(),
                          dataset_sha256=hashlib.sha256(DATASET.read_bytes()).hexdigest(),source_sha256={p:hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in SOURCES},summary=recount(rows,self.cases))
            path=Path(directory)/'metadata.json';path.write_text(json.dumps(original))
            self.assertFalse(verify(path)['all_criteria_passed'])
            for mutation in ('source','raw','dataset','summary','freeze'):
                changed=copy.deepcopy(original)
                if mutation=='source':changed['source_sha256'][SOURCES[0]]='0'*64
                elif mutation=='raw':changed['results_sha256']='0'*64
                elif mutation=='dataset':changed['dataset_sha256']='0'*64
                elif mutation=='summary':changed['summary']['reconciled_resumption']['cases']=31
                else:changed['freeze_commit']=base
                path.write_text(json.dumps(changed))
                with self.assertRaises(ValueError):verify(path)

    def test_verifier_imports_only_standard_library(self):
        tree=ast.parse((ROOT/'experiments/verify_resume_results.py').read_text());names=[]
        for node in ast.walk(tree):
            if isinstance(node,ast.Import):names += [n.name.split('.')[0] for n in node.names]
            if isinstance(node,ast.ImportFrom):names += [node.module.split('.')[0]]
        self.assertFalse(set(names)-set(sys.stdlib_module_names)-{'__future__'})


if __name__=='__main__':unittest.main()
