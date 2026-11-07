import ast
import copy
import json
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from experiments.run_selection_comparison import ROOT, assess, load_cases, run_case, summarize
from experiments.verify_selection_results import evaluate, load_manifest, recount
from src.publication_store import digest
from src.selection_store import MODES, SelectionPublicationStore


class SelectionStoreTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory(prefix='codeguardian-selection-test-')
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.number = 0

    def store(self, mode='validated_selection'):
        self.number += 1
        store = SelectionPublicationStore(self.root/str(self.number), mode)
        store.initialize(b'approved=version-a\n')
        store.publish(1, 'seed-a', b'approved=version-b\n')
        store.publish(1, 'seed-b', None)
        return store

    def overlap(self, store, stage='after_refresh', value=b'B'):
        answers, events = [], []
        def checkpoint(current):
            if current == stage:
                answers.append(store.publish_once(1, 'inflight', value))
        result = store.migrate(2, checkpoint=checkpoint, event=lambda kind, **fields: events.append((kind, fields)))
        return result, answers, events

    @staticmethod
    def fail_at(target):
        def fail(stage):
            if stage == target:
                raise RuntimeError('injected '+stage)
        return fail

    def test_invalid_mode_epoch_key_payload_and_target_are_rejected(self):
        with self.assertRaises(ValueError):
            SelectionPublicationStore(self.root, 'unknown')
        store = self.store()
        before = store.inspect()
        for args in ((True,'new',b'B'),(1,'../bad',b'B'),(1,'new','text')):
            with self.subTest(args=args), self.assertRaises(ValueError):
                store.publish_once(*args)
        for target in (True,0,3):
            with self.assertRaises(ValueError):
                store.migrate(target)
        self.assertEqual(store.inspect(), before)

    def test_cached_selection_loses_late_receipt_but_preserves_current_value(self):
        store = self.store('cached_selection')
        result, answers, _ = self.overlap(store)
        observed = store.inspect()
        self.assertEqual(result['status'], 'migrated')
        self.assertEqual(answers[0]['status'], 'committed')
        self.assertEqual((observed['state'].revision, observed['state'].content), (4,b'B'))
        self.assertEqual(observed['migration_witness']['selected_count'], 2)
        self.assertEqual(observed['migration_witness']['write_count'], 3)
        self.assertEqual(len(observed['summaries']), 2)
        self.assertEqual(store.publish(1,'inflight',b'B')['status'], 'outcome_unavailable')

    def test_separate_refresh_handles_early_publication_but_has_a_later_gap(self):
        for stage, expected in (('after_selection','replayed'),('after_refresh','outcome_unavailable')):
            store = self.store('separate_refresh')
            self.overlap(store,stage)
            self.assertEqual(store.publish(1,'inflight',b'B')['status'], expected)

    def test_transactional_selection_defers_old_work_then_closure_refuses_it(self):
        store = self.store('transactional_selection')
        _, answers, _ = self.overlap(store,'after_selection')
        self.assertEqual(answers[0]['status'],'busy')
        self.assertEqual(store.publish_once(1,'inflight',b'B')['status'],'outcome_unavailable')
        observed = store.inspect()
        self.assertEqual(observed['state'].revision,3)
        self.assertFalse(observed['publication_witnesses'])
        self.assertEqual(len(observed['summaries']),2)

    def test_validated_selection_rolls_back_and_fresh_retry_preserves_new_receipt(self):
        for stage in ('after_selection','after_refresh'):
            store = self.store()
            result,answers,_ = self.overlap(store,stage)
            self.assertEqual(result['status'],'stale_selection')
            before = store.inspect()
            self.assertEqual(before['active_epoch'],1)
            self.assertEqual(before['state'].revision,4)
            self.assertEqual(len(before['receipts']),3)
            self.assertFalse(before['summaries'])
            self.assertIsNone(before['migration_witness'])
            self.assertEqual(store.migrate(2)['status'],'migrated')
            self.assertEqual(store.publish(1,'inflight',b'B'),{**answers[0],'status':'replayed'})
            self.assertEqual(store.snapshot(),before['state'])

    def test_literal_validation_detects_changed_identity_even_without_revision_change(self):
        store = self.store()
        def change_metadata(stage):
            if stage == 'after_refresh':
                # Unit-only source edit checks tuple comparison, not a claim
                # that storage metadata is attacker-controlled in the study.
                with sqlite3.connect(store.database) as connection:
                    connection.execute("UPDATE requests SET request_id='renamed' WHERE request_id='seed-a'")
        result = store.migrate(2,checkpoint=change_metadata)
        self.assertEqual(result['status'],'stale_selection')
        self.assertEqual(store.snapshot().revision,3)
        self.assertEqual(store.inspect()['active_epoch'],1)
        self.assertIsNone(store.inspect()['migration_witness'])

    def test_validation_events_observe_the_mismatch_without_repairing_weak_modes(self):
        for mode in ('cached_selection','separate_refresh','validated_selection'):
            store = self.store(mode)
            result,_,events = self.overlap(store)
            validation = next(fields for kind,fields in events if kind=='validation')
            self.assertFalse(validation['matched'])
            self.assertEqual(validation['observed']['current_revision'],4)
            self.assertEqual(len(validation['observed']['receipts']),3)
            self.assertEqual(result['status'],'stale_selection' if mode=='validated_selection' else 'migrated')

    def test_empty_unicode_and_revocation_receipts_survive_validated_retry(self):
        for value in (b'', '안전 ✓'.encode(), None):
            store = self.store()
            result,answers,_ = self.overlap(store,value=value)
            self.assertEqual(result['status'],'stale_selection')
            store.migrate(2)
            replay = store.publish(1,'inflight',value)
            self.assertEqual(replay,{**answers[0],'status':'replayed'})
            self.assertEqual(replay['approved_sha256'],None if value is None else digest(value))

    def test_distinct_ids_with_identical_bytes_are_not_merged_by_fingerprint(self):
        store = self.store()
        store.publish_once(1,'inflight',b'approved=version-b\n')
        store.migrate(2)
        summaries = store.inspect()['summaries']
        same = [r for r in summaries if r['payload_sha256']==digest(b'approved=version-b\n')]
        self.assertEqual({r['request_id'] for r in same},{'seed-a','inflight'})
        self.assertEqual(len(summaries),3)

    def test_original_reply_after_later_policy_does_not_restore_old_state(self):
        store = self.store()
        original = store.publish_once(1,'inflight',None)
        store.publish_once(1,'later',b'D')
        store.migrate(2)
        before = store.inspect()
        self.assertEqual(store.publish_once(1,'inflight',None),{**original,'status':'replayed'})
        self.assertEqual(store.inspect(),before)
        self.assertEqual((store.snapshot().revision,store.snapshot().content),(5,b'D'))

    def test_current_epoch_intent_completes_after_migration_and_retries_once(self):
        store = self.store()
        store.migrate(2)
        result = store.publish_once(2,'inflight',b'B')
        self.assertEqual((result['status'],result['revision']),('committed',4))
        self.assertEqual(store.publish_once(2,'inflight',b'B'),{**result,'status':'replayed'})
        self.assertEqual(len(store.inspect()['publication_witnesses']),1)

    def test_publication_witness_is_atomic_with_effect_and_receipt(self):
        store = self.store()
        before = store.inspect()
        with sqlite3.connect(store.database) as connection:
            connection.execute("CREATE TRIGGER reject_witness BEFORE INSERT ON publication_witnesses BEGIN SELECT RAISE(ABORT, 'witness'); END")
        with self.assertRaises(sqlite3.IntegrityError):
            store.publish_once(1,'inflight',b'B')
        self.assertEqual(store.inspect(),before)

    def test_migration_witness_failure_rolls_back_fence_cleanup_and_summaries(self):
        store = self.store()
        before = store.inspect()
        with sqlite3.connect(store.database) as connection:
            connection.execute("CREATE TRIGGER reject_migration BEFORE INSERT ON migration_witness BEGIN SELECT RAISE(ABORT, 'migration'); END")
        with self.assertRaises(sqlite3.IntegrityError):
            store.migrate(2)
        self.assertEqual(store.inspect(),before)

    def test_failure_before_migration_commit_restores_original_authority(self):
        for mode in MODES:
            store = self.store(mode)
            before = store.inspect()
            with self.assertRaises(RuntimeError):
                store.migrate(2,checkpoint=self.fail_at('before_commit'))
            self.assertEqual(store.inspect(),before)
            self.assertEqual(store.publish_once(1,'inflight',b'B')['status'],'committed')

    def test_after_commit_exception_preserves_migrated_authority(self):
        store = self.store()
        original = store.publish_once(1,'inflight',b'B')
        with self.assertRaises(RuntimeError):
            store.migrate(2,checkpoint=self.fail_at('after_commit'))
        self.assertEqual(store.inspect()['active_epoch'],2)
        self.assertEqual(store.publish(1,'inflight',b'B'),{**original,'status':'replayed'})
        self.assertEqual(store.migrate(2)['status'],'already_migrated')

    def test_failure_before_publication_commit_rolls_back_all_rows(self):
        store = self.store()
        before = store.inspect()
        with self.assertRaises(RuntimeError):
            store.publish_once(1,'inflight',b'B',checkpoint=self.fail_at('before_commit'))
        self.assertEqual(store.inspect(),before)

    def test_real_busy_begin_preserves_identity_and_has_no_effect(self):
        store = self.store()
        connection = store._connect()
        events = []
        try:
            connection.execute('BEGIN IMMEDIATE')
            result = store.publish_once(1,'inflight',b'B',event=lambda kind,**fields:events.append((kind,fields)))
            self.assertEqual(result,{'status':'busy','epoch':1,'request_id':'inflight','revision':None,'approved_sha256':None})
            self.assertEqual(events[0][1]['sqlite_errorcode'],5)
            self.assertEqual(events[0][1]['busy_timeout_ms'],0)
        finally:
            connection.close()
        self.assertEqual(store.publish_once(1,'inflight',b'B')['status'],'committed')
        self.assertEqual(len(store.inspect()['publication_witnesses']),1)

    def test_unknown_begin_error_is_not_a_busy_publisher(self):
        store = self.store()
        error = sqlite3.OperationalError('injected locked error')
        error.sqlite_errorcode,error.sqlite_errorname = 6,'SQLITE_LOCKED'
        connection = Mock()
        connection.execute.side_effect = error
        with patch.object(store,'_probe_connection',return_value=connection):
            with self.assertRaises(sqlite3.OperationalError):
                store.publish_once(1,'inflight',b'B')
        connection.close.assert_called_once()

    def test_migration_begin_contention_is_not_a_modeled_validation_retry(self):
        store = self.store('transactional_selection')
        connection = store._connect()
        try:
            connection.execute('BEGIN IMMEDIATE')
            with self.assertRaises(sqlite3.OperationalError) as caught:
                store.migrate(2)
            self.assertEqual(caught.exception.sqlite_errorcode,5)
        finally:
            connection.close()
        self.assertEqual(store.inspect()['active_epoch'],1)

    def test_wal_setting_is_rejected_before_source_selection(self):
        store = self.store()
        with sqlite3.connect(store.database) as connection:
            connection.execute('PRAGMA journal_mode=WAL')
        with self.assertRaises(ValueError):
            store.migrate(2)

    def test_worker_requires_exact_role_and_stage_on_resume(self):
        store = self.store('transactional_selection')
        command = [sys.executable,str(ROOT/'experiments/selection_worker.py'),'--root',str(store.root),
                   '--mode','transactional_selection','--role','migrate','--pause','after_selection']
        child = subprocess.run(command,input=json.dumps({'command':'resume','stage':'after_selection','role':'publish'})+'\n',capture_output=True,text=True,timeout=10)
        self.assertNotEqual(child.returncode,0)
        self.assertIn('role/stage-bound',child.stderr)
        self.assertEqual(store.inspect()['active_epoch'],1)


class SelectionEvidenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dataset=ROOT/'experiments/tasks/selection-eval-v1/tasks.json'
        cls.cases=load_cases(cls.dataset)
        cls.rows=[run_case(c,m) for c in cls.cases for m in MODES]
        for row in cls.rows:
            if row['status']!='complete':
                raise AssertionError((row['case_id'],row['mode'],row['error_detail']))

    def sample(self,name='after_refresh-ascii',mode='validated_selection'):
        return copy.deepcopy(next(r for r in self.rows if r['case_id']==name and r['mode']==mode))

    def test_full_grid_matches_independent_reconstruction_and_ten_criteria(self):
        for row in self.rows:
            with self.subTest(case=row['case_id'],mode=row['mode']):
                self.assertEqual(evaluate(row),row['oracle'])
        actual=summarize(self.rows,self.cases)
        self.assertEqual(actual,recount(self.rows,load_manifest(self.dataset)))
        self.assertTrue(all(actual['criteria'].values()))

    def test_missing_committed_history_differs_from_never_committed_refusal(self):
        lost=self.sample(mode='cached_selection')['oracle']
        refused=self.sample(mode='transactional_selection')['oracle']
        self.assertTrue(lost['old_committed'])
        self.assertTrue(lost['gap_lost_history'])
        self.assertFalse(lost['old_denied'])
        self.assertFalse(refused['old_committed'])
        self.assertFalse(refused['gap_lost_history'])
        self.assertTrue(refused['old_denied'])

    def test_validated_retry_preserves_publication_and_the_full_source(self):
        row=self.sample()
        self.assertEqual([m['response']['status'] for m in row['migrations']],['stale_selection','migrated'])
        failed=row['migrations'][0]['after']
        self.assertEqual(failed['active_epoch'],1)
        self.assertEqual(len(failed['receipts']),3)
        self.assertIsNone(failed['migration_witness'])
        self.assertEqual(row['followup_response']['revision'],4)

    def test_known_weak_failures_are_complete_and_coherent_negative_results(self):
        for mode in ('cached_selection','separate_refresh'):
            row=self.sample(mode=mode)
            self.assertTrue(row['oracle']['coherent_final'])
            self.assertTrue(row['oracle']['gap_lost_history'])
            self.assertFalse(row['oracle']['complete_summary_coverage'])
            self.assertEqual(row['followup_response']['status'],'outcome_unavailable')

    def test_matching_historical_guess_without_summary_is_unsupported(self):
        row=self.sample(mode='cached_selection')
        row['followup_response'].update(status='replayed',revision=4,approved_sha256=digest(b'approved=version-b\n'))
        next(e for e in row['timeline'] if e['kind']=='followup_completed')['status']='replayed'
        actual=assess(row)
        self.assertFalse(actual['old_replayed'])
        self.assertEqual(actual['false_history'],1)
        self.assertFalse(actual['followup_result_correct'])
        self.assertEqual(actual,evaluate(row))

    def test_wrong_never_committed_followup_is_still_a_failed_result(self):
        row=self.sample(mode='transactional_selection')
        row['followup_response']['status']='future_epoch'
        next(e for e in row['timeline'] if e['kind']=='followup_completed')['status']='future_epoch'
        self.assertFalse(assess(row)['followup_result_correct'])
        self.assertEqual(assess(row),evaluate(row))

    def test_unavailable_followup_cannot_include_commitment_fields(self):
        row=self.sample(mode='cached_selection')
        row['followup_response']['revision']=4
        self.assertFalse(assess(row)['followup_result_correct'])
        self.assertEqual(assess(row),evaluate(row))

    def test_wrong_primary_acknowledgment_is_a_negative_business_result(self):
        row=self.sample()
        record=row['publications'][0]
        record['response']['revision']=3
        next(e for e in record['events'] if e['kind']=='publication_result')['response']=record['response']
        record['stdout']=''.join(json.dumps(e)+'\n' for e in record['events'])
        self.assertFalse(assess(row)['publisher_result_correct'])
        self.assertEqual(assess(row),evaluate(row))

    def test_changed_retry_epoch_or_command_is_rejected(self):
        for field in ('request','command'):
            row=self.sample(mode='transactional_selection')
            record=row['publications'][-1]
            if field=='request':
                record['request']['epoch']=2
            else:
                record['command'][9]='2'
            for oracle in (assess,evaluate):
                with self.assertRaises(ValueError):
                    oracle(row)

    def test_validation_event_cannot_claim_an_unchanged_source(self):
        row=self.sample(mode='cached_selection')
        record=row['migrations'][0]
        next(e for e in record['events'] if e['kind']=='validation')['matched']=True
        record['stdout']=''.join(json.dumps(e)+'\n' for e in record['events'])
        for oracle in (assess,evaluate):
            with self.assertRaises(ValueError):
                oracle(row)

    def test_migration_witness_cannot_hide_a_missing_source_row(self):
        row=self.sample(mode='cached_selection')
        row['followup_before']['migration_witness']['selected_count']=3
        for oracle in (assess,evaluate):
            with self.assertRaises(ValueError):
                oracle(row)

    def test_missing_pause_trace_or_causal_prefix_is_rejected(self):
        for field in ('trace','prefix'):
            row=self.sample()
            if field=='trace':
                row['migrations'][0]['events'].pop(2)
            else:
                row['migrations'][1]['before']=copy.deepcopy(row['initial'])
            for oracle in (assess,evaluate):
                with self.assertRaises(ValueError):
                    oracle(row)

    def test_grid_repeats_omissions_and_forged_verdicts_are_rejected(self):
        changed=copy.deepcopy(self.rows)
        changed[0]['oracle']['gap_lost_history']=False
        for rows in (self.rows[:-1],self.rows+[self.rows[0]],changed):
            for counter in (summarize,recount):
                with self.assertRaises(ValueError):
                    counter(rows,self.cases)

    def test_an_entire_failed_mode_stays_visible_in_infrastructure_counts(self):
        rows=copy.deepcopy(self.rows)
        for row in rows:
            if row['mode']=='cached_selection':
                row.update(status='infrastructure_error',oracle=None)
        actual=summarize(rows,self.cases)
        self.assertEqual(actual,recount(rows,self.cases))
        self.assertEqual(actual['arms']['cached_selection']['infrastructure_errors'],24)
        self.assertFalse(all(actual['criteria'].values()))

    def test_manifest_rejects_semantic_duplicate_with_new_name(self):
        data=json.loads(self.dataset.read_text())
        data['cases'][1]={**data['cases'][0],'case_id':'different-name'}
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'manifest.json'
            path.write_text(json.dumps(data))
            for loader in (load_cases,load_manifest):
                with self.assertRaises(ValueError):
                    loader(path)

    def test_independent_verifier_has_no_measured_module_imports(self):
        tree=ast.parse((ROOT/'experiments/verify_selection_results.py').read_text())
        names=[]
        for node in ast.walk(tree):
            if isinstance(node,ast.Import):
                names.extend(n.name for n in node.names)
            elif isinstance(node,ast.ImportFrom):
                names.append(node.module or '')
        self.assertFalse(any(n.startswith(('src','experiments')) for n in names))


if __name__=='__main__':
    unittest.main()
