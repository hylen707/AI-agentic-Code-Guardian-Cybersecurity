"""One process generation with marked exits and generation-bound resumes."""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.restart_store import CUTS, MODES, RestartPublicationStore

EXIT_CODE = 73


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--mode", choices=MODES, required=True)
    parser.add_argument("--budget", type=int, required=True)
    parser.add_argument("--generation", type=int, required=True)
    parser.add_argument("--cut", choices=(*CUTS, "none"), required=True)
    args = parser.parse_args()
    sequence, attempt = 0, None
    def event(kind, **fields):
        nonlocal sequence, attempt
        if kind == "admitted":
            attempt = fields["attempt_number"]
        print(json.dumps({"seq": sequence, "kind": kind, **fields}), flush=True)
        sequence += 1
    def checkpoint(stage):
        event("checkpoint", stage=stage)
        if stage == args.cut:
            event("planned_exit", stage=stage, code=EXIT_CODE)
            os._exit(EXIT_CODE)
        if stage == "after_selection":
            binding = {"role": "migrate", "stage": stage, "generation": args.generation, "attempt_number": attempt, "budget": args.budget}
            event("paused", **binding)
            if json.loads(sys.stdin.readline()) != {"command": "resume", **binding}:
                raise ValueError("exact generation, attempt, budget, role and stage resume required")
            event("resumed", **binding)
    event("invocation_started", policy=args.mode, budget=args.budget, generation=args.generation, cut=args.cut, target_epoch=2)
    store = RestartPublicationStore(args.root, args.mode, args.budget)
    result = store.run_job(args.generation, checkpoint=checkpoint, event=event)
    event("migration_result", response=result)
    event("completed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
