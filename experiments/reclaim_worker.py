"""A caller with a fixed owner/token pair and exact live continuation bindings."""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))
from src.reclamation.store import MODES,ReclamationStore,positive


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--root',type=Path,required=True);p.add_argument('--mode',choices=MODES,required=True)
    p.add_argument('--generation',type=int,required=True);p.add_argument('--owner',type=int,required=True);p.add_argument('--token',type=int,required=True);p.add_argument('--pauses',required=True)
    a=p.parse_args();pauses=[] if not a.pauses else a.pauses.split(',');seq=0
    positive(a.generation)
    if len(set(pauses))!=len(pauses) or any(s not in ('before_selection','after_selection','after_fence','before_commit','after_commit') for s in pauses):raise ValueError('unique declared checkpoint stages required')
    lease=dict(owner=a.owner,token=a.token)
    def event(kind,**fields):
        nonlocal seq
        print(json.dumps(dict(seq=seq,kind=kind,**fields)),flush=True);seq+=1
    def checkpoint(stage):
        event('checkpoint',stage=stage)
        if stage not in pauses:return
        binding=dict(generation=a.generation,owner=a.owner,token=a.token,stage=stage,role='migrate')
        event('paused',**binding);command=json.loads(sys.stdin.readline())
        if not isinstance(command,dict) or set(command)!=set(binding)|{'command'} or command['command'] not in ('continue','exit') or any(type(command[k]) is not type(v) or command[k]!=v for k,v in binding.items()):raise ValueError('exact typed generation, owner, token, stage and role required')
        event('resumed',action=command['command'],**binding)
        if command['command']=='exit':
            event('planned_exit',stage=stage,code=73);os._exit(73)
    event('invocation_started',generation=a.generation,mode=a.mode,lease=lease,pauses=pauses,target_epoch=2)
    try:
        answer=ReclamationStore(a.root,a.mode).migrate_once(lease,checkpoint=checkpoint,event=event)
        event('caller_result',response=answer)
    except Exception as error:
        event('caller_error',error_type=type(error).__name__,detail=str(error),sqlite_errorcode=getattr(error,'sqlite_errorcode',None))
    event('worker_completed')


if __name__=='__main__':main()
