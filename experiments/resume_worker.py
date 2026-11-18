"""One bound caller generation, with live pauses and marked application exits."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from src.restart_store import RestartPublicationStore
from src.resumption_store import ResumptionPublicationStore

MODES = ("restart_baseline", "reconciled_resumption")
STAGES = ("after_admission", "after_selection", "after_refresh", "after_stale", "before_commit", "after_commit", "after_accounting")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--mode", choices=MODES, required=True)
    parser.add_argument("--budget", type=int, required=True)
    parser.add_argument("--generation", type=int, required=True)
    parser.add_argument("--pauses", required=True)
    args = parser.parse_args()
    pauses = [] if not args.pauses else args.pauses.split(',')
    if len(set(pauses)) != len(pauses) or any(p not in STAGES for p in pauses):
        raise ValueError("unique declared pause stages required")
    sequence, attempt = 0, None
    def event(kind, **fields):
        nonlocal sequence, attempt
        if kind == "admitted":
            attempt = fields["attempt_number"]
        print(json.dumps(dict(seq=sequence, kind=kind, **fields)), flush=True)
        sequence += 1
    def checkpoint(stage):
        event("checkpoint", stage=stage)
        if stage not in pauses:
            return
        binding = dict(generation=args.generation, attempt_number=attempt, budget=args.budget, stage=stage, role="migrate")
        event("paused", **binding)
        command = json.loads(sys.stdin.readline())
        if command not in ({"command":"continue", **binding}, {"command":"exit", **binding}):
            raise ValueError("exact generation, attempt, budget, stage and role required")
        event("resumed", action=command["command"], **binding)
        if command["command"] == "exit":
            event("planned_exit", stage=stage, code=73)
            os._exit(73)
    event("invocation_started", generation=args.generation, mode=args.mode, budget=args.budget, target_epoch=2, pauses=pauses)
    cls = RestartPublicationStore if args.mode == MODES[0] else ResumptionPublicationStore
    try:
        answer = cls(args.root, "reserved_reconcile", args.budget).run_job(args.generation, checkpoint=checkpoint, event=event)
        event("caller_result", response=answer)
    except Exception as error:
        event("caller_error", error_type=type(error).__name__, detail=str(error), sqlite_errorcode=getattr(error,"sqlite_errorcode",None))
    event("worker_completed")


if __name__ == "__main__":
    main()
