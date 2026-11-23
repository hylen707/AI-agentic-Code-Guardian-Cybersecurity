import ast
import copy
import gzip
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from experiments.generate_histories import generate,load_grammar,resolve
from experiments.run_exploration import DATASET,ROOT,SOURCES,INHERITED,MODES,run_case,measure,summarize
from experiments.verify_exploration import declarations,load_manifest,evaluate,recount,verify,initial_spec,apply_spec,linearize

BASE='aba4945d9b866a865c3dd49b6e9bf6a0dcb73505'
FREEZE='72ec18deca46756349e3cad33a640432058f3d6b'


def request(epoch=1,key='request-α',token=1,owner=2):return dict(recovery_epoch=epoch,request_id=key,expected_token=token,owner=owner)
def call(name,role,r,start=1,end=2,answer=None):return dict(id=name,role=role,request=r,start=start,end=end,answer=answer)


class AbstractHistoryTests(unittest.TestCase):
 def test_completed_call_and_exact_response_are_required(self):
  a=call('a','replace',request());state,answer=apply_spec(initial_spec(),a);a['answer']=answer
  self.assertIsNotNone(linearize([a],state));bad=copy.deepcopy(a);bad['answer']['outcome']['lease']['token']=True
  self.assertIsNone(linearize([bad],state))

 def test_pending_effect_can_be_included_or_omitted(self):
  a=call('a','replace',request(),end=None);state,_=apply_spec(initial_spec(),a)
  self.assertIsNotNone(linearize([a],state));self.assertIsNotNone(linearize([a],initial_spec()))

 def test_crashed_effect_can_be_present_without_a_reply(self):
  a=call('a','replace',request(),end=2);state,_=apply_spec(initial_spec(),a)
  self.assertIsNotNone(linearize([a],state));self.assertIsNotNone(linearize([a],initial_spec()))

 def test_completed_real_time_order_cannot_be_reversed(self):
  a=call('a','replace',request(),1,2);s,a['answer']=apply_spec(initial_spec(),a)
  b=call('b','advance',dict(expected_epoch=1),3,4);s,b['answer']=apply_spec(s,b)
  self.assertIsNotNone(linearize([a,b],s))
  # A reply demanding retirement is possible only if B precedes A; intervals forbid it.
  a['answer']=dict(status='retired',recovery_epoch=1,request_id='request-α',active_recovery_epoch=2)
  state,_=apply_spec(initial_spec(),b)
  self.assertIsNone(linearize([a,b],state))

 def test_overlapping_late_reply_can_describe_pre_retirement_effect(self):
  a=call('a','replace',request(),1,8);s,a['answer']=apply_spec(initial_spec(),a)
  b=call('b','advance',dict(expected_epoch=1),3,4);s,b['answer']=apply_spec(s,b)
  self.assertIsNotNone(linearize([a,b],s));self.assertEqual(s['results'],[])

 def test_retired_row_is_not_a_legal_abstract_state(self):
  a=call('a','advance',dict(expected_epoch=1));s,a['answer']=apply_spec(initial_spec(),a)
  bad=copy.deepcopy(s);bad['results']=[dict(**request(),outcome=dict(status='conflict',lease=dict(owner=1,token=1)))]
  self.assertIsNone(linearize([a],bad))

 def test_first_conflict_remains_bound_even_when_token_advances(self):
  s=initial_spec();a=call('a','replace',request(token=2));s,first=apply_spec(s,a)
  s,_=apply_spec(s,call('b','replace',request(key='slot-b')));s,again=apply_spec(s,a)
  self.assertEqual(first['outcome'],again['outcome']);self.assertEqual(again['status'],'replayed')

 def test_capacity_lookup_and_current_epoch_reuse(self):
  s=initial_spec();a=call('a','replace',request());s,first=apply_spec(s,a)
  s,_=apply_spec(s,call('b','replace',request(key='slot-b',token=2)))
  unchanged,overflow=apply_spec(s,call('c','replace',request(key='slot-c',token=3)))
  self.assertEqual(overflow['status'],'capacity_exhausted');self.assertEqual(unchanged,s)
  s,again=apply_spec(s,a);self.assertEqual(again['outcome'],first['outcome'])
  s,_=apply_spec(s,call('advance','advance',dict(expected_epoch=1)))
  s,new=apply_spec(s,call('new','replace',request(epoch=2,token=3)));self.assertEqual(new['status'],'recorded');self.assertEqual(len(s['results']),1)

 def test_busy_is_exact_and_has_no_effect(self):
  a=call('a','replace',request(),answer=dict(status='busy',recovery_epoch=1,request_id='request-α',sqlite_errorcode=5))
  self.assertIsNotNone(linearize([a],initial_spec()));a['answer']['sqlite_errorcode']=True
  self.assertIsNone(linearize([a],initial_spec()))


class GeneratedHistoryEvidenceTests(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  cls.g=load_grammar();cls.cases=generate(cls.g);cls.rows={}
  names=('s-000','s-060','s-600','s-023','o-0-3-0-0','o-0-3-0-1','o-0-3-3-0','o-0-5-0-1','o-7-0-2-1')
  for c in cls.cases:
   if c['case_id'] not in names:continue
   for mode in MODES:
    row=run_case(c,mode,cls.g)
    if row['status']!='complete':raise AssertionError(row.get('error_detail'))
    cls.rows[(c['case_id'],mode)]=row
 def sample(self,name='o-0-3-0-0',mode='atomic_floor'):return copy.deepcopy(self.rows[(name,mode)])
 def declaration(self,row):return next(c for c in self.cases if c['case_id']==row['case_id'])
 def reject(self,row):
  with self.assertRaises((ValueError,KeyError,TypeError)):evaluate(row,self.declaration(row),self.g)

 def test_independent_grammar_has_complete_exact_grid(self):
  self.assertEqual(load_manifest(),self.g);self.assertEqual(declarations(self.g),self.cases)
  self.assertEqual(sum(c['family']=='sequence' for c in self.cases),512);self.assertEqual(sum(c['family']=='overlap' for c in self.cases),612)
  self.assertEqual(len({c['case_id'] for c in self.cases}),1124)

 def test_reference_reconstruction_matches_controller_counts(self):
  for row in self.rows.values():self.assertEqual(evaluate(row,self.declaration(row),self.g)[0],measure(row))

 def test_cached_pivot_fails_abstract_contract_without_trace_error(self):
  weak=self.sample(mode='cached_floor');counts,stats=evaluate(weak,self.declaration(weak),self.g)
  self.assertEqual(counts['transport_response_errors'],0);self.assertGreater(counts['retired_grants'],0);self.assertIsNotNone(stats['first_failure'])
  safe=self.sample();self.assertIsNone(evaluate(safe,self.declaration(safe),self.g)[1]['first_failure'])

 def test_sequential_generation_finds_reopened_epoch(self):
  weak=self.sample('s-600','erase_only');self.assertIsNotNone(evaluate(weak,self.declaration(weak),self.g)[1]['first_failure'])
  safe=self.sample('s-600');self.assertIsNone(evaluate(safe,self.declaration(safe),self.g)[1]['first_failure'])

 def test_reply_after_retirement_remains_prefix_consistent(self):
  row=self.sample('o-0-3-3-0');counts,stats=evaluate(row,self.declaration(row),self.g)
  self.assertEqual(counts['retired_decisions'],0);self.assertIsNone(stats['first_failure'])

 def test_unreached_pivot_does_not_fabricate_exit_or_overlap(self):
  row=self.sample('o-7-0-2-1');self.assertEqual(row['measures']['unreached_pivots'],1)
  self.assertEqual(len(row['steps']),2);self.assertEqual(row['measures']['planned_exits'],0)
  row['steps'].append(copy.deepcopy(row['steps'][0]));self.reject(row)

 def test_live_resume_types_role_and_request_binding(self):
  for k,v in (('generation',True),('recovery_epoch',True),('expected_token',True),('role','advance')):
   row=self.sample();row['steps'][2]['command'][k]=v;self.reject(row)
  row=self.sample();row['steps'][2]['action']['generation']=True;self.reject(row)

 def test_advancer_expected_epoch_binding_is_exact(self):
  row=self.sample('o-0-5-0-1');row['steps'][2]['command']['expected_epoch']=True;self.reject(row)

 def test_pair_inputs_are_fixed_before_either_child_runs(self):
  row=self.sample();row['steps'][1]['action']['request']['expected_epoch']=99;self.reject(row)
  row=self.sample();row['steps'][0],row['steps'][1]=row['steps'][1],row['steps'][0];self.reject(row)

 def test_raw_exit_code_and_missing_marker_are_rejected(self):
  for mutation in ('raw','code','marker'):
   row=self.sample('o-0-5-0-1');step=next(s for s in row['steps'] if s.get('returncode')==73)
   if mutation=='raw':step['stdout']=''
   elif mutation=='code':step['returncode']=1
   else:
    step['events']=[e for e in step['events'] if e['kind']!='planned_exit'];step['stdout']=''.join(json.dumps(e)+'\n' for e in step['events'])
   self.reject(row)

 def test_snapshot_floor_results_and_grants_cannot_be_forged(self):
  for mutation in ('floor','result','grant'):
   row=self.sample()
   if mutation=='floor':row['final']['active_recovery_epoch']=999
   elif mutation=='result':row['final']['retained_results'].append(dict(**request(),outcome={}))
   else:row['final']['grants'][0]['owner']=999
   self.reject(row)

 def test_consistent_wrong_reply_fails_both_reply_and_abstract_checks(self):
  row=self.sample('s-000');q=row['prefix'][1];q['response']['outcome']['lease']['token']=999
  next(e for e in q['events'] if e['kind']=='caller_result')['response']=copy.deepcopy(q['response']);row['measures']=measure(row)
  counts,stats=evaluate(row,self.declaration(row),self.g)
  self.assertEqual(counts['transport_response_errors'],1);self.assertIsNotNone(stats['first_failure'])

 def test_consistent_wrong_publication_reply_remains_failure(self):
  row=self.sample();row['publication_queries'][0]['original']['revision']=999;row['measures']=measure(row)
  self.assertEqual(evaluate(row,self.declaration(row),self.g)[0]['publication_failures'],1)

 def failed_grid(self):return [{**c,'mode':m,'status':'infrastructure_error','measures':None,'error_type':'OSError'} for c in self.cases for m in MODES]

 def test_failed_rows_keep_declared_denominators(self):
  rows=self.failed_grid();arms,checks=recount(rows,self.g);self.assertEqual(arms,summarize(rows,self.cases));self.assertEqual(arms['atomic_floor']['overlap']['infrastructure_errors'],612)
  self.assertEqual(checks['atomic_floor']['overlap']['checked_prefixes'],0)
  for bad in (rows[:-1],rows+[rows[0]]):
   with self.assertRaises(ValueError):recount(bad,self.g)
   with self.assertRaises(ValueError):summarize(bad,self.cases)

 def test_process_start_failure_is_retained(self):
  c=self.declaration(self.sample())
  with patch('experiments.run_retention_comparison.subprocess.Popen',side_effect=OSError('injected')):row=run_case(c,'atomic_floor',self.g)
  self.assertEqual(row['status'],'infrastructure_error');self.assertEqual(row['error_phase'],'start')

 def test_manifest_bounds_pairs_and_booleans_are_checked(self):
  for key,value in (('sequence_depth',True),('capacity',True),('pairs',self.g['pairs'][:-1]),('finishes',['exit','continue'])):
   g=copy.deepcopy(self.g);g[key]=value
   with tempfile.TemporaryDirectory() as d:
    p=Path(d)/'grammar.json';p.write_text(json.dumps(g))
    with self.assertRaises(ValueError):load_manifest(p)

 def test_source_reference_archive_freeze_and_summary_mutations(self):
  rows=self.failed_grid()
  with tempfile.TemporaryDirectory() as d:
   raw=Path(d)/'raw.jsonl.gz';raw.write_bytes(gzip.compress(''.join(json.dumps(r)+'\n' for r in rows).encode(),mtime=0));arms,_=recount(rows,self.g)
   meta=dict(base_commit=BASE,freeze_commit=FREEZE,results_file=raw.name,results_sha256=hashlib.sha256(raw.read_bytes()).hexdigest(),dataset_sha256=hashlib.sha256(DATASET.read_bytes()).hexdigest(),source_sha256={n:hashlib.sha256((ROOT/n).read_bytes()).hexdigest() for n in SOURCES},summary=arms)
   p=Path(d)/'metadata.json';p.write_text(json.dumps(meta));self.assertFalse(verify(p)['all_criteria_passed'])
   for mutation in ('source','reference','raw','dataset','summary','freeze','path'):
    changed=copy.deepcopy(meta)
    if mutation=='source':changed['source_sha256'][SOURCES[0]]='0'*64
    elif mutation=='reference':changed['source_sha256'].pop('experiments/verify_retention_results.py')
    elif mutation=='raw':changed['results_sha256']='0'*64
    elif mutation=='dataset':changed['dataset_sha256']='0'*64
    elif mutation=='summary':changed['summary']['atomic_floor']['sequence']['cases']=511
    elif mutation=='freeze':changed['freeze_commit']=BASE
    else:changed['results_file']='../raw.jsonl.gz'
    p.write_text(json.dumps(changed))
    with self.assertRaises(ValueError):verify(p)

 def test_verifier_and_transitive_reference_have_no_mechanism_imports(self):
  for path,allowed in (('experiments/verify_exploration.py',{'experiments.verify_retention_results'}),('experiments/verify_retention_results.py',set())):
   for node in ast.walk(ast.parse((ROOT/path).read_text())):
    names=[a.name for a in node.names] if isinstance(node,ast.Import) else [node.module] if isinstance(node,ast.ImportFrom) else []
    for name in names:self.assertTrue(name in allowed or name.split('.')[0] in sys.stdlib_module_names or name=='__future__',name)


if __name__=='__main__':unittest.main()
