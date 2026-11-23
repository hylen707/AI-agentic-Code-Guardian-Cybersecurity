"""Finite, versioned grammar for sequential and one-pivot recovery histories."""
from __future__ import annotations
import itertools
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
DATASET=ROOT/'experiments/tasks/exploration-eval-v1/grammar.json'
ALPHABET=('old_a','changed_a','current_a','current_b','current_c','future_a','advance','close')

def load_grammar(path=DATASET):
 g=json.loads(Path(path).read_text())
 if g['schema_version']!='exploration-eval-v1' or g['alphabet']!=list(ALPHABET) or type(g['sequence_depth']) is not int or g['sequence_depth']!=3 or type(g['overlap_prefix_depth']) is not int or g['overlap_prefix_depth']!=1 or type(g['capacity']) is not int or g['capacity']!=2:raise ValueError('fixed exploration bounds required')
 return g

def generate(g):
 cases=[]
 for indices in itertools.product(range(8),repeat=3):
  cases.append(dict(case_id='s-'+''.join(map(str,indices)),family='sequence',path=[g['alphabet'][i] for i in indices]))
 for seed,path in enumerate([[]]+[[v] for v in g['alphabet']]):
  for p,pair in enumerate(g['pairs']):
   stages=g['advance_checkpoints'] if pair['a']=='advance' else g['request_checkpoints']
   for k,pause in enumerate(stages):
    for f,finish in enumerate(g['finishes']):
     cases.append(dict(case_id=f'o-{seed}-{p}-{k}-{f}',family='overlap',path=path,pair=dict(pair),pause=pause,finish=finish))
 if len(cases)!=1124 or len({c['case_id'] for c in cases})!=1124:raise ValueError('complete 1124-history grammar required')
 return cases

def resolve(template,state,g):
 floor=state['active_recovery_epoch'];token=state['lease']['token']
 if template=='advance':return 'advance',dict(expected_epoch=floor)
 if template=='close':return 'close',{k:state['lease'][k] for k in ('owner','token')}
 epoch=1 if template in ('old_a','changed_a') else floor+1 if template=='future_a' else floor
 slot='b' if template=='current_b' else 'c' if template=='current_c' else 'a'
 return 'replace',dict(recovery_epoch=epoch,request_id=g['keys'][slot],expected_token=1 if template=='old_a' else token,owner=3 if template in ('changed_a','current_c') else 2)
