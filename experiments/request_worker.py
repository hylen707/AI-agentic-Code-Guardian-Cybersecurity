"""One exact recovery request, with typed live commands and marked exits."""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))
from src.reclamation.store import positive
from src.recovery_requests.store import MODES,RecoveryRequestStore,validate_request


def main():
    p=argparse.ArgumentParser();p.add_argument('--root',type=Path,required=True);p.add_argument('--mode',choices=MODES,required=True)
    p.add_argument('--generation',type=int,required=True);p.add_argument('--request',required=True);p.add_argument('--pauses',required=True)
    a=p.parse_args();positive(a.generation);request=json.loads(a.request);validate_request(request)
    pauses=[] if not a.pauses else a.pauses.split(',')
    if len(set(pauses))!=len(pauses) or any(s not in ('after_lookup','before_decision_commit','after_decision_commit','before_reply') for s in pauses):raise ValueError('unique declared stages required')
    seq=0
    def event(kind,**fields):
        nonlocal seq
        print(json.dumps(dict(seq=seq,kind=kind,**fields)),flush=True);seq+=1
    def checkpoint(stage):
        event('checkpoint',stage=stage)
        if stage not in pauses:return
        binding=dict(generation=a.generation,**request,stage=stage,role='replace')
        event('paused',**binding);command=json.loads(sys.stdin.readline())
        if not isinstance(command,dict) or set(command)!=set(binding)|{'command'} or command['command'] not in ('continue','exit') or any(type(command[k]) is not type(v) or command[k]!=v for k,v in binding.items()):raise ValueError('exact typed request resume binding required')
        event('resumed',action=command['command'],**binding)
        if command['command']=='exit':event('planned_exit',stage=stage,code=73);os._exit(73)
    event('invocation_started',generation=a.generation,mode=a.mode,request=request,pauses=pauses)
    try:event('caller_result',response=RecoveryRequestStore(a.root,a.mode).replace_once(request,checkpoint=checkpoint,event=event))
    except Exception as error:event('caller_error',error_type=type(error).__name__,detail=str(error),sqlite_errorcode=getattr(error,'sqlite_errorcode',None))
    event('worker_completed')


if __name__=='__main__':main()
