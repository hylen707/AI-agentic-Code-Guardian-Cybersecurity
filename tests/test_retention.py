import ast
import copy
import hashlib
import gzip
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch

from experiments.run_retention_comparison import DATASET,ROOT,SOURCES,Peer,load_cases,measure,run_case,summarize
from experiments.verify_retention_results import evaluate,load_manifest,recount,verify
from src.recovery_retention.store import CAPACITY,MODES,RecoveryRetentionStore

BASE='fa5d7075f1896069672e24e6ca116de0a90c0666'
FREEZE='81dbcb23b64ed3001abb4f68057d7cfe9a64a943'


class RecoveryRetentionStoreTests(unittest.TestCase):
 def setUp(self):
  d=tempfile.TemporaryDirectory();self.addCleanup(d.cleanup);self.root=Path(d.name);self.serial=0
 def store(self,mode='atomic_floor'):
  self.serial+=1;s=RecoveryRetentionStore(self.root/str(self.serial),mode);s.initialize(b'A');return s
 @staticmethod
 def req(epoch=1,key='a',expected=1,owner=2):return dict(recovery_epoch=epoch,request_id=key,expected_token=expected,owner=owner)

 def test_exact_request_types_reject_before_binding_or_grant(self):
  s=self.store();before=s.inspect();bad=[None,{},dict(self.req(),extra=1)]
  for k in ('recovery_epoch','expected_token','owner'):
   bad.extend({**self.req(),k:v} for v in (True,0,-1,2**63,1.0,'1'))
  bad.extend(self.req(key=v) for v in ('','x'*129,'bad\nkey','bad\x00key','\ud800',True))
  for r in bad:
   with self.assertRaises(ValueError):s.replace_once(r)
  self.assertEqual(s.inspect(),before)

 def test_advancement_types_and_expected_comparison_are_inert(self):
  s=self.store();before=s.inspect()
  for r in (None,{},dict(expected_epoch=1,extra=1),*[dict(expected_epoch=v) for v in (True,0,2**63,1.0)]):
   with self.assertRaises(ValueError):s.advance_epoch(r)
  self.assertEqual(s.advance_epoch(dict(expected_epoch=2)),dict(status='epoch_conflict',active_recovery_epoch=1));self.assertEqual(s.inspect(),before)

 def test_request_capture_survives_callback_mutation(self):
  s=self.store();r=self.req()
  def checkpoint(stage):
   if stage=='after_admission':r.update(recovery_epoch=99,owner=99)
  answer=s.replace_once(r,checkpoint=checkpoint)
  self.assertEqual(answer['recovery_epoch'],1);self.assertEqual(answer['outcome']['lease']['owner'],2)

 def test_capacity_counts_conflicts_and_lookup_precedes_overflow(self):
  s=self.store();a=self.req(expected=2);first=s.replace_once(a);s.replace_once(self.req(key='b'))
  before=s.inspect();self.assertEqual(s.replace_once(a)['outcome'],first['outcome']);self.assertEqual(first['outcome']['status'],'conflict')
  self.assertEqual(s.replace_once(self.req(key='b',owner=9))['status'],'request_conflict')
  self.assertEqual(s.replace_once(self.req(key='c',expected=2))['status'],'capacity_exhausted');self.assertEqual(s.inspect(),before)
  s.advance_epoch(dict(expected_epoch=1));self.assertEqual(s.replace_once(self.req(epoch=2,key='c',expected=2))['status'],'recorded')

 def test_retired_never_used_id_cannot_acquire_current_authority(self):
  s=self.store();s.advance_epoch(dict(expected_epoch=1));before=s.inspect()
  for r in (self.req(),self.req(key='never-used'),self.req(owner=99)):
   self.assertEqual(s.replace_once(r)['status'],'retired')
  self.assertEqual(s.inspect(),before)

 def test_new_epoch_reuses_text_id_without_restoring_old_token(self):
  s=self.store();a=self.req();old=s.replace_once(a);s.advance_epoch(dict(expected_epoch=1));new=s.replace_once(self.req(epoch=2,expected=2,owner=3))
  self.assertEqual(old['outcome']['lease']['token'],2);self.assertEqual(new['outcome']['lease']['token'],3)
  before=s.inspect();self.assertEqual(s.replace_once(a)['status'],'retired');self.assertEqual(s.inspect(),before)

 def test_future_request_does_not_create_or_bind_namespace(self):
  s=self.store();before=s.inspect();self.assertEqual(s.replace_once(self.req(epoch=2))['status'],'future_epoch');self.assertEqual(s.inspect(),before)
  s.advance_epoch(dict(expected_epoch=1));self.assertEqual(s.replace_once(self.req(epoch=2))['status'],'recorded')

 def test_epoch_check_precedes_closed_target_and_old_receipt_lookup(self):
  s=self.store();s.replace_once(self.req());s.migrate_once(dict(owner=2,token=2));s.advance_epoch(dict(expected_epoch=1));before=s.inspect()
  self.assertEqual(s.replace_once(self.req())['status'],'retired');self.assertEqual(s.inspect(),before)
  self.assertEqual(s.replace_once(self.req(epoch=2))['outcome'],dict(status='completed',active_epoch=2))

 def test_cached_admission_can_cross_atomic_retirement(self):
  s=self.store('cached_floor');rotations=[]
  def checkpoint(stage):
   if stage=='after_admission':rotations.append(s.advance_epoch(dict(expected_epoch=1)))
  s.replace_once(self.req(),checkpoint=checkpoint);state=s.inspect()
  self.assertEqual(rotations[0]['status'],'advanced');self.assertEqual(state['decisions'][0]['active_recovery_epoch'],2)
  self.assertEqual(state['retained_results'][0]['recovery_epoch'],1);self.assertEqual(state['lease']['token'],2)

 def test_atomic_admission_defers_retirement_until_request_commits(self):
  s=self.store();rotations=[]
  def checkpoint(stage):
   if stage=='after_admission':rotations.append(s.advance_epoch(dict(expected_epoch=1)))
  s.replace_once(self.req(),checkpoint=checkpoint);self.assertEqual(rotations,[dict(status='busy',sqlite_errorcode=5)])
  self.assertEqual(s.advance_epoch(dict(expected_epoch=1))['status'],'advanced');self.assertEqual(s.inspect()['retained_results'],[])

 def test_request_precommit_exception_rolls_back_all_authority(self):
  s=self.store();before=s.inspect()
  def checkpoint(stage):
   if stage=='before_decision_commit':raise RuntimeError('cut')
  with self.assertRaises(RuntimeError):s.replace_once(self.req(),checkpoint=checkpoint)
  self.assertEqual(s.inspect(),before)

 def test_retirement_precommit_exception_restores_floor_and_result(self):
  s=self.store();s.replace_once(self.req());before=s.inspect()
  def checkpoint(stage):
   if stage=='before_rotation_commit':raise RuntimeError('cut')
  with self.assertRaises(RuntimeError):s.advance_epoch(dict(expected_epoch=1),checkpoint=checkpoint)
  self.assertEqual(s.inspect(),before);self.assertEqual(s.replace_once(self.req())['status'],'replayed')

 def test_lost_advancement_reply_preserves_fence_but_not_original_reply(self):
  s=self.store();s.replace_once(self.req())
  def checkpoint(stage):
   if stage=='after_rotation_commit':raise RuntimeError('reply lost')
  with self.assertRaises(RuntimeError):s.advance_epoch(dict(expected_epoch=1),checkpoint=checkpoint)
  self.assertEqual(s.advance_epoch(dict(expected_epoch=1)),dict(status='epoch_conflict',active_recovery_epoch=2));self.assertEqual(s.inspect()['retained_results'],[])

 def test_committed_reply_delivered_after_retirement_remains_valid(self):
  s=self.store()
  def checkpoint(stage):
   if stage=='after_decision_commit':s.advance_epoch(dict(expected_epoch=1))
  answer=s.replace_once(self.req(),checkpoint=checkpoint)
  self.assertEqual(answer['status'],'recorded');self.assertEqual(answer['outcome']['lease']['token'],2)
  self.assertEqual(s.inspect()['retained_results'],[]);self.assertEqual(s.replace_once(self.req())['status'],'retired')

 def test_result_row_bound_across_repeated_epochs_and_old_ids(self):
  s=self.store();token=1
  for epoch in range(1,13):
   for name in ('a','b'):
    self.assertEqual(s.replace_once(self.req(epoch,name,token,epoch+1))['status'],'recorded');token+=1
   self.assertEqual(len(s.inspect()['retained_results']),CAPACITY)
   s.advance_epoch(dict(expected_epoch=epoch))
   for old in range(1,epoch+1):self.assertEqual(s.replace_once(self.req(old,'unused',token,99))['status'],'retired')
   self.assertEqual(s.inspect()['retained_results'],[])
  self.assertEqual(len(s.inspect()['grants']),25)

 def test_epoch_overflow_and_fixed_policy_mismatch_fail_closed(self):
  s=self.store();c=s._connect();c.execute('UPDATE retention_policy SET active_recovery_epoch=?',(2**63-1,));c.close();before=s.inspect()
  with self.assertRaises(ValueError):s.advance_epoch(dict(expected_epoch=2**63-1))
  self.assertEqual(s.inspect(),before)
  wrong=RecoveryRetentionStore(s.root,'cached_floor')
  with self.assertRaises(ValueError):wrong.replace_once(self.req())
  self.assertEqual(s.inspect(),before)

 def test_only_numeric_sqlite_busy_is_deferred(self):
  s=self.store();lock=s._connect();lock.execute('BEGIN IMMEDIATE');before=s.inspect()
  try:
   self.assertEqual(s.replace_once(self.req())['status'],'busy');self.assertEqual(s.advance_epoch(dict(expected_epoch=1))['status'],'busy')
   self.assertEqual(s.inspect(),before)
  finally:lock.close()
  class Broken:
   def execute(self,*a):raise sqlite3.OperationalError('database is locked')
   def close(self):pass
  with patch.object(s,'_probe_connection',return_value=Broken()):
   with self.assertRaises(sqlite3.OperationalError):s.replace_once(self.req())

 def test_live_resume_rejects_boolean_epoch_and_changed_role(self):
  for role,stage,badkey,badvalue in (('replace','after_admission','recovery_epoch',True),('replace','after_admission','generation',True),('advance','before_rotation_commit','expected_epoch',True),('advance','before_rotation_commit','role','replace')):
   s=self.store();r=self.req() if role=='replace' else dict(expected_epoch=1)
   peer=Peer(s.root,'atomic_floor',dict(generation=1,role=role,request=r,pauses=[stage]))
   try:
    first=peer.boundary();binding={k:v for k,v in first['events'][-1].items() if k not in ('seq','kind')};command=dict(command='continue',**binding);command[badkey]=badvalue
    peer.process.stdin.write((json.dumps(command)+'\n').encode());peer.process.stdin.flush();end=peer.boundary()
    error=next(e for e in end['events'] if e['kind']=='caller_error');self.assertEqual(error['error_type'],'ValueError')
    self.assertEqual(s.inspect()['decisions'],[]);self.assertEqual(s.inspect()['active_recovery_epoch'],1)
   finally:peer.close()


class RecoveryRetentionEvidenceTests(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  cls.cases=load_cases();cls.rows={}
  wanted=('quiet_retirement','exit_before_rotation','exit_after_rotation','stale_admission_unused','lookup_holds_writer','reply_after_retirement','decision_rollback_then_retire','conflict_retirement','capacity_and_reuse')
  for c in cls.cases:
   if c['pattern']!='ascii_revoked' or c['scenario'] not in wanted:continue
   for mode in MODES:
    row=run_case(c,mode)
    if row['status']!='complete':raise AssertionError(row.get('error_detail'))
    cls.rows[(c['case_id'],mode)]=row
 def sample(self,name='stale_admission_unused',mode='atomic_floor'):return copy.deepcopy(self.rows[(name+'-ascii_revoked',mode)])
 def declaration(self,row):return next(c for c in self.cases if c['case_id']==row['case_id'])
 def reject(self,row):
  with self.assertRaises((ValueError,KeyError,TypeError)):evaluate(row,self.declaration(row))

 def test_independent_reconstruction_matches_all_sampled_histories(self):
  for row in self.rows.values():self.assertEqual(evaluate(row,self.declaration(row)),measure(row))

 def test_cached_floor_is_not_authority_at_later_commit(self):
  weak=self.sample(mode='cached_floor');safe=self.sample()
  self.assertGreater(weak['measures']['retired_grants'],0);self.assertEqual(safe['measures']['retired_grants'],0)
  self.assertGreater(safe['measures']['busy'],0)

 def test_erase_only_can_rebind_conflict_as_grant(self):
  row=self.sample('conflict_retirement','erase_only');decisions=row['settled']['decisions'];first=decisions[0]
  later=next(d for d in decisions[1:] if d['request_id']==first['request_id'])
  self.assertEqual(first['outcome']['status'],'conflict');self.assertEqual(later['outcome']['status'],'reclaimed')

 def test_reply_after_retirement_is_not_a_retired_decision(self):
  row=self.sample('reply_after_retirement');self.assertEqual(row['measures']['retired_decisions'],0)
  final=next(s for s in row['steps'] if s['action']['op']=='resume')
  answer=next(e['response'] for e in final['events'] if e['kind']=='caller_result')
  self.assertEqual(answer['status'],'recorded');self.assertEqual(final['snapshot']['active_recovery_epoch'],2)

 def test_marked_precommit_exits_restore_request_and_rotation_state(self):
  for scenario in ('exit_before_rotation','decision_rollback_then_retire'):
   row=self.sample(scenario);cut=next(s for s in row['steps'] if s.get('returncode')==73)
   self.assertEqual(cut['snapshot']['active_recovery_epoch'],1)
   if scenario=='exit_before_rotation':self.assertEqual(len(cut['snapshot']['retained_results']),1)
   else:self.assertEqual(cut['snapshot']['decisions'],[]);self.assertEqual(cut['snapshot']['lease']['token'],1)

 def test_exact_live_epoch_role_and_generation_bindings(self):
  for k,v in (('recovery_epoch',True),('generation',True),('role','advance'),('expected_token',True)):
   row=self.sample();next(s for s in row['steps'] if s['action']['op']=='resume')['command'][k]=v;self.reject(row)

 def test_rotation_binding_rejects_boolean_expected_epoch(self):
  row=self.sample('exit_before_rotation');next(s for s in row['steps'] if s['action']['op']=='resume')['command']['expected_epoch']=True;self.reject(row)

 def test_parent_order_and_worker_input_mutations_rejected(self):
  row=self.sample();row['steps'][1],row['steps'][2]=row['steps'][2],row['steps'][1];self.reject(row)
  row=self.sample();row['steps'][0]['action']['request']['recovery_epoch']=2;self.reject(row)

 def test_raw_stream_exit_code_and_marker_mutations_rejected(self):
  for mutation in ('raw','code','marker'):
   row=self.sample('exit_before_rotation');step=next(s for s in row['steps'] if s.get('returncode')==73)
   if mutation=='raw':step['stdout']=''
   elif mutation=='code':step['returncode']=1
   else:
    step['events']=[e for e in step['events'] if e['kind']!='planned_exit'];step['stdout']=''.join(json.dumps(e)+'\n' for e in step['events'])
   self.reject(row)

 def test_floor_grant_retirement_and_result_mutations_rejected(self):
  for mutation in ('floor','grant','retirement','result','decision'):
   row=self.sample()
   if mutation=='floor':row['final']['active_recovery_epoch']=999
   elif mutation=='grant':row['final']['grants'][0]['token']=999
   elif mutation=='retirement':row['final']['retirements'][0]['removed_receipts']=999
   elif mutation=='result':row['final']['retained_results'][0]['recovery_epoch']=1
   else:row['final']['decisions'][0]['active_recovery_epoch']=999
   self.reject(row)

 def test_missing_probes_and_changed_causal_prefix_rejected(self):
  row=self.sample();row['retired_probes'].pop();self.reject(row)
  row=self.sample();row['retired_probes'][0]['before']['active_recovery_epoch']=999;self.reject(row)

 def test_consistent_wrong_retired_reply_remains_outcome_failure(self):
  row=self.sample();q=row['retired_probes'][0];q['response']['status']='request_conflict'
  next(e for e in q['events'] if e['kind']=='caller_result')['response']=copy.deepcopy(q['response'])
  row['measures']=measure(row);counts=evaluate(row,self.declaration(row))
  self.assertEqual(counts['correct_retired_queries'],counts['retired_queries']-1);self.assertEqual(counts['transport_response_errors'],1)

 def test_consistent_wrong_current_and_publication_replies_remain_failures(self):
  row=self.sample();q=row['current_probes'][0];q['response']['outcome']['lease']['token']=999
  next(e for e in q['events'] if e['kind']=='caller_result')['response']=copy.deepcopy(q['response']);row['publication_queries'][0]['original']['revision']=999
  row['measures']=measure(row);counts=evaluate(row,self.declaration(row))
  self.assertEqual(counts['current_query_failures'],1);self.assertEqual(counts['publication_failures'],1)

 def failed_grid(self):return [{**c,'mode':m,'status':'infrastructure_error','measures':None,'error_type':'OSError'} for c in self.cases for m in MODES]

 def test_failed_rows_remain_in_full_denominator(self):
  rows=self.failed_grid();self.assertEqual(summarize(rows,self.cases),recount(rows,self.cases));self.assertEqual(recount(rows,self.cases)['atomic_floor']['infrastructure_errors'],32)
  for bad in (rows[:-1],rows+[rows[0]]):
   for count in (summarize,recount):
    with self.assertRaises(ValueError):count(bad,self.cases)

 def test_process_start_failure_is_retained(self):
  with patch('experiments.run_retention_comparison.subprocess.Popen',side_effect=OSError('injected')):row=run_case(self.cases[0],'atomic_floor')
  self.assertEqual(row['status'],'infrastructure_error');self.assertEqual(row['error_phase'],'start')

 def test_manifest_boolean_epoch_capacity_and_duplicate_case_rejected(self):
  original=json.loads(DATASET.read_text())
  for mutation in ('epoch','capacity','duplicate'):
   doc=copy.deepcopy(original)
   if mutation=='epoch':doc['cases'][0]['steps'][0]['request']['recovery_epoch']=True
   elif mutation=='capacity':doc['capacity']=True
   else:doc['cases'][1]['pattern']='ascii_revoked'
   with tempfile.TemporaryDirectory() as directory:
    p=Path(directory)/'tasks.json';p.write_text(json.dumps(doc))
    with self.assertRaises(ValueError):load_manifest(p)

 def test_source_raw_freeze_summary_and_path_mutations_rejected(self):
  rows=self.failed_grid()
  with tempfile.TemporaryDirectory() as directory:
   raw=Path(directory)/'raw.jsonl';raw.write_text(''.join(json.dumps(r)+'\n' for r in rows))
   original=dict(base_commit=BASE,freeze_commit=FREEZE,results_file=raw.name,results_sha256=hashlib.sha256(raw.read_bytes()).hexdigest(),dataset_sha256=hashlib.sha256(DATASET.read_bytes()).hexdigest(),source_sha256={n:hashlib.sha256((ROOT/n).read_bytes()).hexdigest() for n in SOURCES},summary=recount(rows,self.cases))
   p=Path(directory)/'meta.json';p.write_text(json.dumps(original));self.assertFalse(verify(p)['all_criteria_passed'])
   for mutation in ('source','raw','dataset','summary','freeze','path'):
    changed=copy.deepcopy(original)
    if mutation=='source':changed['source_sha256'][SOURCES[0]]='0'*64
    elif mutation=='raw':changed['results_sha256']='0'*64
    elif mutation=='dataset':changed['dataset_sha256']='0'*64
    elif mutation=='summary':changed['summary']['atomic_floor']['cases']=31
    elif mutation=='path':changed['results_file']='../'+raw.name
    else:changed['freeze_commit']=changed['base_commit']
    p.write_text(json.dumps(changed))
    with self.assertRaises(ValueError):verify(p)

 def test_lossless_gzip_evidence_and_compressed_identity(self):
  rows=self.failed_grid()
  with tempfile.TemporaryDirectory() as directory:
   raw=Path(directory)/'raw.jsonl.gz';serialized=''.join(json.dumps(r)+'\n' for r in rows).encode();raw.write_bytes(gzip.compress(serialized,mtime=0))
   self.assertEqual(gzip.decompress(raw.read_bytes()),serialized)
   meta=dict(base_commit=BASE,freeze_commit=FREEZE,results_file=raw.name,results_sha256=hashlib.sha256(raw.read_bytes()).hexdigest(),dataset_sha256=hashlib.sha256(DATASET.read_bytes()).hexdigest(),source_sha256={n:hashlib.sha256((ROOT/n).read_bytes()).hexdigest() for n in SOURCES},summary=recount(rows,self.cases))
   path=Path(directory)/'metadata.json';path.write_text(json.dumps(meta))
   self.assertEqual(verify(path)['summary'],meta['summary']);self.assertFalse(verify(path)['all_criteria_passed'])
   raw.write_bytes(raw.read_bytes()[:-1])
   with self.assertRaisesRegex(ValueError,'raw identity'):verify(path)

 def test_verifier_imports_only_standard_library(self):
  names=[]
  for n in ast.walk(ast.parse((ROOT/'experiments/verify_retention_results.py').read_text())):
   if isinstance(n,ast.Import):names.extend(a.name.split('.')[0] for a in n.names)
   elif isinstance(n,ast.ImportFrom):names.append(n.module.split('.')[0])
  self.assertFalse(set(names)-set(sys.stdlib_module_names)-{'__future__'})


if __name__=='__main__':unittest.main()
