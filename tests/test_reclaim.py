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

from experiments.run_reclaim_comparison import DATASET,ROOT,SOURCES,Peer,load_cases,measure,run_case,summarize
from experiments.verify_reclaim_results import evaluate,load_manifest,recount,verify
from src.reclamation.store import MAX_INTEGER,MODES,ReclamationStore


class ReclamationStoreTests(unittest.TestCase):
    def setUp(self):
        folder=tempfile.TemporaryDirectory();self.addCleanup(folder.cleanup);self.root=Path(folder.name);self.serial=0

    def store(self,mode='transactional_fence'):
        self.serial+=1;store=ReclamationStore(self.root/str(self.serial),mode);store.initialize(b'A')
        store.publish_once(1,'seed',b'B');return store

    def test_invalid_inputs_preserve_authority(self):
        with self.assertRaises(ValueError):ReclamationStore(self.root,'bad')
        store=self.store();before=store.inspect()
        for value in (True,0,-1,2**63,1.5):
            with self.assertRaises(ValueError):store.replace(value,2)
            with self.assertRaises(ValueError):store.replace(1,value)
            with self.assertRaises(ValueError):store.migrate_once(dict(owner=1,token=value))
        for lease in ({},{'owner':1,'token':1,'other':0},None):
            with self.assertRaises(ValueError):store.migrate_once(lease)
        self.assertEqual(store.inspect(),before)

    def test_compare_and_swap_never_replays_a_new_grant(self):
        store=self.store();self.assertEqual(store.replace(1,2)['lease'],dict(owner=2,token=2))
        before=store.inspect();self.assertEqual(store.replace(1,3)['status'],'conflict');self.assertEqual(store.inspect(),before)
        self.assertEqual(len(before['grants']),2)

    def test_owner_reuse_does_not_restore_old_token(self):
        store=self.store();store.replace(1,2);store.replace(2,1)
        self.assertEqual(store.migrate_once(dict(owner=1,token=1))['status'],'stale_lease')
        self.assertEqual(store.inspect()['active_epoch'],1)
        self.assertEqual(store.migrate_once(dict(owner=1,token=3))['status'],'migrated')
        self.assertEqual(len(store.inspect()['grants']),3)

    def test_separate_check_is_obsolete_before_effect(self):
        store=self.store('separate_fence')
        def checkpoint(stage):
            if stage=='after_fence':self.assertEqual(store.replace(1,2)['status'],'reclaimed')
        store.migrate_once(dict(owner=1,token=1),checkpoint=checkpoint)
        self.assertFalse(store.inspect()['lease_effect']['authorized'])

    def test_transactional_check_postpones_replacement(self):
        store=self.store();busy=[]
        def checkpoint(stage):
            if stage=='after_fence':busy.append(store.replace(1,2))
        store.migrate_once(dict(owner=1,token=1),checkpoint=checkpoint)
        self.assertEqual(busy,[dict(status='busy',sqlite_errorcode=5)])
        self.assertTrue(store.inspect()['lease_effect']['authorized'])
        self.assertEqual(store.replace(1,2),dict(status='completed',active_epoch=2))
        self.assertEqual(len(store.inspect()['grants']),1)

    def test_before_commit_failure_rolls_back_and_can_be_replaced(self):
        store=self.store()
        def checkpoint(stage):
            if stage=='before_commit':raise RuntimeError('cut')
        with self.assertRaises(RuntimeError):store.migrate_once(dict(owner=1,token=1),checkpoint=checkpoint)
        state=store.inspect();self.assertEqual(state['active_epoch'],1);self.assertIsNone(state['lease_effect']);self.assertEqual(len(state['receipts']),1)
        store.replace(1,2);self.assertEqual(store.migrate_once(dict(owner=2,token=2))['status'],'migrated')

    def test_after_commit_failure_retains_completion_without_replacement(self):
        store=self.store()
        def checkpoint(stage):
            if stage=='after_commit':raise RuntimeError('lost reply')
        with self.assertRaises(RuntimeError):store.migrate_once(dict(owner=1,token=1),checkpoint=checkpoint)
        self.assertEqual(store.replace(1,2)['status'],'completed');self.assertEqual(len(store.inspect()['grants']),1)
        self.assertEqual(store.publish_once(1,'seed',b'B')['status'],'replayed')

    def test_fixed_policy_is_checked_even_after_completion(self):
        store=self.store();store.migrate_once(dict(owner=1,token=1))
        reopened=ReclamationStore(store.root,'cached_permission')
        with self.assertRaises(ValueError):reopened.migrate_once(dict(owner=1,token=1))

    def test_token_overflow_does_not_mutate(self):
        store=self.store();connection=store._connect()
        try:connection.execute('UPDATE reclaim_lease SET token=? WHERE id=1',(MAX_INTEGER,))
        finally:connection.close()
        before=store.inspect()
        with self.assertRaises(ValueError):store.replace(MAX_INTEGER,2)
        self.assertEqual(store.inspect(),before)

    def test_non_busy_storage_failure_is_not_hidden(self):
        store=self.store()
        with patch.object(store,'_probe_connection',side_effect=sqlite3.OperationalError('I/O')):
            with self.assertRaises(sqlite3.OperationalError):store.replace(1,2)

    def test_boolean_live_token_is_not_integer_token(self):
        store=self.store();peer=Peer(store.root,'transactional_fence',dict(generation=1,pauses=['after_selection']),dict(owner=1,token=1))
        try:
            peer.boundary();command={'command':'continue',**peer.pause};command['token']=True
            peer.process.stdin.write((json.dumps(command)+'\n').encode());peer.process.stdin.flush()
            result=peer.boundary();self.assertTrue(any(e['kind']=='caller_error' for e in result['events']))
            self.assertEqual(store.inspect()['active_epoch'],1)
        finally:peer.close()

    def test_wrong_live_token_resume_is_rejected(self):
        store=self.store();peer=Peer(store.root,'transactional_fence',dict(generation=1,pauses=['after_selection']),dict(owner=1,token=1))
        try:
            peer.boundary();command={'command':'continue',**peer.pause};command['token']=999
            peer.process.stdin.write((json.dumps(command)+'\n').encode());peer.process.stdin.flush()
            result=peer.boundary();error=next(e for e in result['events'] if e['kind']=='caller_error')
            self.assertEqual(error['error_type'],'ValueError');self.assertEqual(store.inspect()['active_epoch'],1)
        finally:peer.close()


class ReclamationEvidenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cases=load_cases();cls.rows={}
        for case in cls.cases:
            if case['pattern']!='updates' or case['scenario'] not in ('reclaim_after_fence','exit_before_commit','exit_after_commit','aba_owner','source_changed','stale_recovery_cas'):continue
            for mode in MODES:
                row=run_case(case,mode)
                if row['status']!='complete':raise AssertionError(row.get('error_detail'))
                cls.rows[(case['case_id'],mode)]=row

    def sample(self,name='reclaim_after_fence-updates',mode='transactional_fence'):return copy.deepcopy(self.rows[(name,mode)])
    def declaration(self,row):return next(c for c in self.cases if c['case_id']==row['case_id'])
    def reject(self,row):
        with self.assertRaises((ValueError,KeyError,TypeError)):evaluate(row,self.declaration(row))

    def test_independent_reconstruction_matches_controller(self):
        for row in self.rows.values():self.assertEqual(evaluate(row,self.declaration(row)),measure(row))

    def test_weak_counterexamples_remain_failures(self):
        for mode in ('cached_permission','separate_fence'):
            row=self.sample(mode=mode);self.assertEqual(evaluate(row,self.declaration(row))['invalid_effects'],1)
        self.assertEqual(self.sample()['measures']['invalid_effects'],0)

    def test_busy_recovery_is_not_a_committed_replacement(self):
        row=self.sample();self.assertEqual(row['measures']['recovery_busy'],1);self.assertEqual(row['measures']['reclaimed'],0)
        self.assertEqual(row['measures']['lifetime_grants'],1)

    def test_reusable_slot_is_not_a_lifetime_budget(self):
        row=self.sample('aba_owner-updates');self.assertEqual(row['measures']['lifetime_grants'],3)
        self.assertEqual(row['final']['lease']['token'],3);self.assertEqual(row['measures']['invalid_effects'],0)

    def test_wrong_generation_owner_token_bindings_rejected(self):
        for key in ('generation','owner','token','stage'):
            row=self.sample();step=next(s for s in row['steps'] if s['action']['op']=='resume');step['command'][key]='bad'
            self.reject(row)

    def test_boolean_recorded_token_is_not_exact_binding(self):
        row=self.sample();next(s for s in row['steps'] if s['action']['op']=='resume')['command']['token']=True
        self.reject(row)

    def test_changed_recovery_arguments_rejected(self):
        row=self.sample();next(s for s in row['steps'] if s['action']['op']=='reclaim')['action']['expected_token']=999;self.reject(row)

    def test_changed_causal_order_rejected(self):
        row=self.sample();row['steps'][1],row['steps'][2]=row['steps'][2],row['steps'][1];self.reject(row)

    def test_unmarked_exit_or_wrong_code_rejected(self):
        for mutation in ('code','marker'):
            row=self.sample('exit_before_commit-updates');s=next(s for s in row['steps'] if s.get('returncode')==73)
            if mutation=='code':s['returncode']=1
            else:
                s['events']=[e for e in s['events'] if e['kind']!='planned_exit'];s['stdout']=''.join(json.dumps(e)+'\n' for e in s['events'])
            self.reject(row)

    def test_forged_grant_and_effect_witness_rejected(self):
        for mutation in ('grant','witness'):
            row=self.sample()
            if mutation=='grant':row['final']['grants'][0]['token']=99
            else:row['final']['lease_effect']['current_token']=99
            self.reject(row)

    def test_raw_stream_and_source_request_changes_rejected(self):
        row=self.sample();row['steps'][0]['stdout']='';self.reject(row)
        row=self.sample('source_changed-updates');next(s for s in row['steps'] if s['action']['op']=='publish')['request']={};self.reject(row)

    def test_consistent_false_answer_is_still_failure(self):
        row=self.sample('aba_owner-updates');step=next(s for s in row['steps'] if s['action']['op']=='resume')
        answer=next(e for e in step['events'] if e['kind']=='caller_result');answer['response']=dict(status='completed',active_epoch=2)
        step['stdout']=''.join(json.dumps(e)+'\n' for e in step['events']);row['measures']=measure(row)
        self.assertEqual(evaluate(row,self.declaration(row))['response_violations'],1)

    def test_consistent_wrong_history_is_still_failure(self):
        row=self.sample();row['queries'][0]['original']['revision']=999;row['measures']=measure(row)
        self.assertEqual(evaluate(row,self.declaration(row))['query_failures'],1)

    def failed_grid(self):return [{**c,'mode':m,'status':'infrastructure_error','measures':None,'error_type':'OSError'} for c in self.cases for m in MODES]

    def test_infrastructure_failures_keep_full_denominators(self):
        rows=self.failed_grid();self.assertEqual(summarize(rows,self.cases),recount(rows,self.cases))
        self.assertEqual(recount(rows,self.cases)['transactional_fence']['infrastructure_errors'],20)

    def test_missing_duplicate_or_forged_count_rejected(self):
        rows=self.failed_grid()
        for count in (summarize,recount):
            for bad in (rows[:-1],rows+[rows[0]]):
                with self.assertRaises(ValueError):count(bad,self.cases)
        row=self.sample();row['measures']['reclaimed']=999;self.reject(row)

    def test_process_start_failure_is_retained(self):
        with patch('experiments.run_reclaim_comparison.subprocess.Popen',side_effect=OSError('injected')):row=run_case(self.cases[0],'transactional_fence')
        self.assertEqual(row['status'],'infrastructure_error');self.assertEqual(row['error_type'],'OSError')

    def test_boolean_recovery_and_duplicate_manifest_rejected(self):
        original=json.loads(DATASET.read_text())
        for mutation in ('boolean','duplicate'):
            doc=copy.deepcopy(original)
            if mutation=='duplicate':doc['cases'][1]['pattern']='updates'
            else:next(s for c in doc['cases'] for s in c['steps'] if s['op']=='reclaim')['expected_token']=True
            with tempfile.TemporaryDirectory() as directory:
                p=Path(directory)/'manifest.json';p.write_text(json.dumps(doc))
                with self.assertRaises(ValueError):load_manifest(p)

    def test_source_raw_freeze_and_summary_mutations_rejected(self):
        rows=self.failed_grid()
        with tempfile.TemporaryDirectory() as directory:
            raw=Path(directory)/'raw.jsonl';raw.write_text(''.join(json.dumps(r)+'\n' for r in rows))
            original=dict(base_commit='baf986b4fa701c38bd2407e114c87b0773b4cc51',freeze_commit='ea005ce0a6c26e01ba90a4271900663407acd5b0',
                          results_file=raw.name,results_sha256=hashlib.sha256(raw.read_bytes()).hexdigest(),dataset_sha256=hashlib.sha256(DATASET.read_bytes()).hexdigest(),
                          source_sha256={n:hashlib.sha256((ROOT/n).read_bytes()).hexdigest() for n in SOURCES},summary=recount(rows,self.cases))
            p=Path(directory)/'metadata.json';p.write_text(json.dumps(original));self.assertFalse(verify(p)['all_criteria_passed'])
            for mutation in ('source','raw','dataset','freeze','summary'):
                changed=copy.deepcopy(original)
                if mutation=='source':changed['source_sha256'][SOURCES[0]]='0'*64
                elif mutation=='raw':changed['results_sha256']='0'*64
                elif mutation=='dataset':changed['dataset_sha256']='0'*64
                elif mutation=='freeze':changed['freeze_commit']=changed['base_commit']
                else:changed['summary']['transactional_fence']['cases']=19
                p.write_text(json.dumps(changed))
                with self.assertRaises(ValueError):verify(p)

    def test_verifier_imports_only_standard_library(self):
        names=[]
        for node in ast.walk(ast.parse((ROOT/'experiments/verify_reclaim_results.py').read_text())):
            if isinstance(node,ast.Import):names += [a.name.split('.')[0] for a in node.names]
            elif isinstance(node,ast.ImportFrom):names.append(node.module.split('.')[0])
        self.assertFalse(set(names)-set(sys.stdlib_module_names)-{'__future__'})


if __name__=='__main__':unittest.main()
