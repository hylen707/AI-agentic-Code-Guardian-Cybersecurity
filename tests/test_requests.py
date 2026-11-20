import ast
import copy
import hashlib
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch

from experiments.run_request_comparison import DATASET,ROOT,SOURCES,Peer,load_cases,measure,run_case,summarize
from experiments.verify_request_results import evaluate,load_manifest,recount,verify
from src.recovery_requests.store import MODES,RecoveryRequestStore


class RecoveryRequestStoreTests(unittest.TestCase):
    def setUp(self):
        folder=tempfile.TemporaryDirectory();self.addCleanup(folder.cleanup);self.root=Path(folder.name);self.serial=0
    def store(self,mode='atomic_receipt'):
        self.serial+=1;s=RecoveryRequestStore(self.root/str(self.serial),mode);s.initialize(b'A');return s
    @staticmethod
    def request(key='a',expected=1,owner=2):return dict(request_id=key,expected_token=expected,owner=owner)

    def test_exact_typed_request_validation_does_not_claim_id(self):
        s=self.store();before=s.inspect()
        bad=[None,{},dict(request_id='a',expected_token=1,owner=2,extra=True)]
        bad += [self.request(key=k) for k in ('','x'*129,'bad\nkey','bad\x00key','\ud800',True)]
        bad += [self.request(expected=v) for v in (True,0,2**63)] + [self.request(owner=v) for v in (True,0,2**63)]
        for req in bad:
            with self.assertRaises(ValueError):s.replace_once(req)
        self.assertEqual(s.inspect(),before)

    def test_request_inputs_are_captured_before_live_checkpoint(self):
        s=self.store();request=self.request()
        def checkpoint(stage):
            if stage=='after_lookup':request['owner']=99
        answer=s.replace_once(request,checkpoint=checkpoint)
        self.assertEqual(answer['outcome']['lease']['owner'],2)
        self.assertEqual(s.inspect()['recovery_receipts'][0]['owner'],2)

    def test_old_result_does_not_reactivate_old_authority(self):
        s=self.store();a=self.request();first=s.replace_once(a)
        s.replace_once(self.request('b',2,3));before=s.inspect();again=s.replace_once(a)
        self.assertEqual(again['outcome'],first['outcome']);self.assertEqual(again['status'],'replayed')
        self.assertEqual(s.inspect(),before);self.assertEqual(s.inspect()['lease']['token'],3)

    def test_original_conflict_remains_conflict_when_inputs_become_applicable(self):
        s=self.store();a=self.request(expected=2);first=s.replace_once(a)
        s.replace_once(self.request('b',1,3));before=s.inspect();again=s.replace_once(a)
        self.assertEqual(again['outcome'],first['outcome']);self.assertEqual(first['outcome']['status'],'conflict');self.assertEqual(s.inspect(),before)

    def test_lookup_precedes_closed_target_and_changed_intent(self):
        s=self.store();a=self.request();first=s.replace_once(a);s.migrate_once(dict(owner=2,token=2))
        before=s.inspect();self.assertEqual(s.replace_once(a)['outcome'],first['outcome'])
        self.assertEqual(s.replace_once(self.request(owner=9))['status'],'request_conflict');self.assertEqual(s.inspect(),before)
        new=s.replace_once(self.request('closed',1,4));self.assertEqual(new['outcome'],dict(status='completed',active_epoch=2))
        self.assertEqual(s.replace_once(self.request('closed',2,4))['status'],'request_conflict')

    def test_before_decision_failure_rolls_back_grant_and_receipt(self):
        s=self.store();before=s.inspect()
        def checkpoint(stage):
            if stage=='before_decision_commit':raise RuntimeError('cut')
        with self.assertRaises(RuntimeError):s.replace_once(self.request(),checkpoint=checkpoint)
        self.assertEqual(s.inspect(),before);self.assertEqual(s.replace_once(self.request())['status'],'recorded')

    def test_after_decision_failure_retains_original_result(self):
        s=self.store()
        def checkpoint(stage):
            if stage=='after_decision_commit':raise RuntimeError('reply lost')
        with self.assertRaises(RuntimeError):s.replace_once(self.request(),checkpoint=checkpoint)
        self.assertEqual(s.replace_once(self.request())['status'],'replayed');self.assertEqual(len(s.inspect()['grants']),2)

    def test_separate_receipt_can_bind_conflict_after_earlier_grant(self):
        s=self.store('separate_receipt');nested=[]
        def checkpoint(stage):
            if stage=='after_decision_commit':nested.append(s.replace_once(self.request()))
        answer=s.replace_once(self.request(),checkpoint=checkpoint);state=s.inspect()
        self.assertEqual(state['decisions'][0]['outcome']['status'],'reclaimed')
        self.assertEqual(answer['outcome']['status'],'conflict');self.assertEqual(nested[0]['outcome']['status'],'conflict')
        self.assertEqual(len(state['grants']),2)

    def test_atomic_lookup_defers_competitor_before_id_is_claimed(self):
        s=self.store();nested=[]
        def checkpoint(stage):
            if stage=='after_lookup':nested.append(s.replace_once(self.request(owner=9)))
        s.replace_once(self.request(),checkpoint=checkpoint)
        self.assertEqual(nested,[dict(status='busy',request_id='a',sqlite_errorcode=5)])
        self.assertEqual(len(s.inspect()['decisions']),1);self.assertEqual(s.replace_once(self.request(owner=9))['status'],'request_conflict')

    def test_receipt_replay_does_not_read_observer_decisions(self):
        s=self.store();first=s.replace_once(self.request());c=s._connect()
        try:c.execute('DROP TABLE decision_witnesses')
        finally:c.close()
        self.assertEqual(s.replace_once(self.request())['outcome'],first['outcome'])

    def test_fixed_mode_and_non_busy_storage_errors_are_not_hidden(self):
        s=self.store();s.replace_once(self.request())
        changed=RecoveryRequestStore(s.root,'current_only')
        with self.assertRaises(ValueError):changed.replace_once(self.request())
        with patch.object(s,'_probe_connection',side_effect=sqlite3.OperationalError('I/O')):
            with self.assertRaises(sqlite3.OperationalError):s.replace_once(self.request('other'))

    def test_wrong_boolean_live_resume_rolls_back_pending_request(self):
        s=self.store();action=dict(generation=1,request=self.request(),pauses=['after_lookup']);peer=Peer(s.root,'atomic_receipt',action)
        try:
            peer.boundary();command={'command':'continue',**peer.pause};command['expected_token']=True
            peer.process.stdin.write((json.dumps(command)+'\n').encode());peer.process.stdin.flush()
            answer=peer.boundary();self.assertTrue(any(e['kind']=='caller_error' for e in answer['events']))
            self.assertEqual(s.inspect()['lease']['token'],1);self.assertEqual(s.inspect()['decisions'],[])
        finally:peer.close()


class RecoveryRequestEvidenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cases=load_cases();cls.rows={}
        for case in cls.cases:
            if case['pattern']!='ascii_revoked' or case['scenario'] not in ('receipt_gap_same','receipt_gap_changed','later_replacement_after_loss','first_conflict_then_applicable','overlap_lookup_changed','exit_before_decision','target_closes_after_loss'):continue
            for mode in MODES:
                row=run_case(case,mode)
                if row['status']!='complete':raise AssertionError(row.get('error_detail'))
                cls.rows[(case['case_id'],mode)]=row
    def sample(self,name='receipt_gap_same-ascii_revoked',mode='atomic_receipt'):return copy.deepcopy(self.rows[(name,mode)])
    def declaration(self,row):return next(c for c in self.cases if c['case_id']==row['case_id'])
    def reject(self,row):
        with self.assertRaises((ValueError,KeyError,TypeError)):evaluate(row,self.declaration(row))

    def test_independent_transaction_reconstruction_matches_controller(self):
        for row in self.rows.values():self.assertEqual(evaluate(row,self.declaration(row)),measure(row))

    def test_wrong_history_can_exist_without_an_extra_grant(self):
        row=self.sample(mode='separate_receipt');m=row['measures']
        self.assertEqual(m['unjustified_grants'],0);self.assertGreater(m['false_history'],0)
        self.assertEqual(m['correct_original_queries'],0)

    def test_receipt_gap_accepts_changed_intent_in_weak_arm(self):
        row=self.sample('receipt_gap_changed-ascii_revoked','separate_receipt')
        self.assertEqual(row['measures']['unjustified_grants'],1)
        self.assertEqual(self.sample('receipt_gap_changed-ascii_revoked')['measures']['unjustified_grants'],0)

    def test_failed_first_decision_still_binds_request(self):
        weak=self.sample('first_conflict_then_applicable-ascii_revoked','current_only')
        safe=self.sample('first_conflict_then_applicable-ascii_revoked')
        self.assertEqual(weak['measures']['unjustified_grants'],1);self.assertEqual(safe['measures']['unjustified_grants'],0)

    def test_historical_grant_does_not_overwrite_later_current_token(self):
        row=self.sample('later_replacement_after_loss-ascii_revoked')
        original=next(p for p in row['probes'] if p['kind']=='original')
        self.assertEqual(original['response']['outcome']['lease']['token'],2)
        self.assertEqual(original['after']['lease']['token'],3);self.assertEqual(row['measures']['query_authority_changes'],0)

    def test_rollback_does_not_leave_a_canonical_witness(self):
        row=self.sample('exit_before_decision-ascii_revoked')
        cut=next(s for s in row['steps'] if s.get('returncode')==73)
        self.assertEqual(cut['snapshot']['decisions'],[]);self.assertEqual(cut['snapshot']['lease']['token'],1)
        self.assertEqual(len(row['settled']['decisions']),1)

    def test_lookup_before_target_closure_preserves_old_reply(self):
        row=self.sample('target_closes_after_loss-ascii_revoked')
        self.assertEqual(row['measures']['correct_original_queries'],row['measures']['original_queries'])
        self.assertTrue(all(p['response']['status']=='request_conflict' for p in row['probes'] if p['kind']=='changed'))

    def test_exact_resume_types_and_id_binding_are_checked(self):
        for key,value in (('generation',True),('expected_token',True),('owner',True),('request_id','other')):
            row=self.sample();next(s for s in row['steps'] if s['action']['op']=='resume')['command'][key]=value;self.reject(row)

    def test_changed_action_order_and_request_are_rejected(self):
        row=self.sample();row['steps'][1],row['steps'][2]=row['steps'][2],row['steps'][1];self.reject(row)
        row=self.sample();row['steps'][0]['action']['request']['owner']=999;self.reject(row)

    def test_changed_receipt_or_decision_witness_rejected(self):
        for mutation in ('receipt','decision','grant'):
            row=self.sample()
            if mutation=='receipt':row['final']['recovery_receipts'][0]['outcome']={'status':'completed','active_epoch':2}
            elif mutation=='decision':row['final']['decisions'][0]['effect_token']=999
            else:row['final']['grants'][0]['token']=999
            self.reject(row)

    def test_wrong_exit_code_missing_marker_or_raw_stream_rejected(self):
        for mutation in ('code','marker','raw'):
            row=self.sample('exit_before_decision-ascii_revoked');step=next(s for s in row['steps'] if s.get('returncode')==73)
            if mutation=='code':step['returncode']=1
            elif mutation=='raw':step['stdout']=''
            else:
                step['events']=[e for e in step['events'] if e['kind']!='planned_exit'];step['stdout']=''.join(json.dumps(e)+'\n' for e in step['events'])
            self.reject(row)

    def test_changed_probe_causal_prefix_rejected(self):
        row=self.sample();row['probes'][0]['before']['lease']['token']=999;self.reject(row)
        row=self.sample();row['probes'][0]['request']['owner']=999;self.reject(row)

    def test_consistent_wrong_historical_answer_remains_failure(self):
        row=self.sample();q=row['probes'][0];q['response']['outcome']['lease']['token']=999
        next(e for e in q['events'] if e['kind']=='caller_result')['response']=copy.deepcopy(q['response'])
        row['measures']=measure(row);counts=evaluate(row,self.declaration(row))
        self.assertEqual(counts['false_history'],1);self.assertEqual(counts['transport_response_errors'],1)

    def test_consistent_wrong_publication_history_remains_failure(self):
        row=self.sample();row['publication_queries'][0]['original']['revision']=999;row['measures']=measure(row)
        self.assertEqual(evaluate(row,self.declaration(row))['publication_failures'],1)

    def failed_grid(self):return [{**c,'mode':m,'status':'infrastructure_error','measures':None,'error_type':'OSError'} for c in self.cases for m in MODES]

    def test_failed_runs_retain_denominators_and_missing_rows_rejected(self):
        rows=self.failed_grid();self.assertEqual(summarize(rows,self.cases),recount(rows,self.cases));self.assertEqual(recount(rows,self.cases)['atomic_receipt']['infrastructure_errors'],24)
        for bad in (rows[:-1],rows+[rows[0]]):
            for count in (summarize,recount):
                with self.assertRaises(ValueError):count(bad,self.cases)

    def test_process_start_failure_is_retained(self):
        with patch('experiments.run_request_comparison.subprocess.Popen',side_effect=OSError('injected')):row=run_case(self.cases[0],'atomic_receipt')
        self.assertEqual(row['status'],'infrastructure_error');self.assertEqual(row['error_phase'],'start')

    def test_boolean_request_and_semantic_manifest_duplicate_rejected(self):
        original=json.loads(DATASET.read_text())
        for mutation in ('boolean','duplicate'):
            doc=copy.deepcopy(original)
            if mutation=='boolean':doc['cases'][0]['steps'][0]['request']['expected_token']=True
            else:doc['cases'][1]['pattern']='ascii_revoked'
            with tempfile.TemporaryDirectory() as directory:
                p=Path(directory)/'tasks.json';p.write_text(json.dumps(doc))
                with self.assertRaises(ValueError):load_manifest(p)

    def test_source_raw_freeze_and_summary_mutations_rejected(self):
        rows=self.failed_grid()
        with tempfile.TemporaryDirectory() as directory:
            raw=Path(directory)/'raw.jsonl';raw.write_text(''.join(json.dumps(r)+'\n' for r in rows))
            original=dict(base_commit='28d841f5eac844a2389cc3ff513fedde962e45ce',freeze_commit='d2ffbb5de6d9bec79a2a70273510ee338c9e28b9',
                          results_file=raw.name,results_sha256=hashlib.sha256(raw.read_bytes()).hexdigest(),dataset_sha256=hashlib.sha256(DATASET.read_bytes()).hexdigest(),
                          source_sha256={n:hashlib.sha256((ROOT/n).read_bytes()).hexdigest() for n in SOURCES},summary=recount(rows,self.cases))
            p=Path(directory)/'metadata.json';p.write_text(json.dumps(original));self.assertFalse(verify(p)['all_criteria_passed'])
            for mutation in ('source','raw','dataset','summary','freeze'):
                changed=copy.deepcopy(original)
                if mutation=='source':changed['source_sha256'][SOURCES[0]]='0'*64
                elif mutation=='raw':changed['results_sha256']='0'*64
                elif mutation=='dataset':changed['dataset_sha256']='0'*64
                elif mutation=='summary':changed['summary']['atomic_receipt']['cases']=23
                else:changed['freeze_commit']=changed['base_commit']
                p.write_text(json.dumps(changed))
                with self.assertRaises(ValueError):verify(p)

    def test_verifier_imports_only_standard_library(self):
        names=[]
        for n in ast.walk(ast.parse((ROOT/'experiments/verify_request_results.py').read_text())):
            if isinstance(n,ast.Import):names += [a.name.split('.')[0] for a in n.names]
            elif isinstance(n,ast.ImportFrom):names.append(n.module.split('.')[0])
        self.assertFalse(set(names)-set(sys.stdlib_module_names)-{'__future__'})


if __name__=='__main__':unittest.main()
