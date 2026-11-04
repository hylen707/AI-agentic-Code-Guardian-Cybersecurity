"""Retire a trusted fixture epoch, exiting at one declared application cut."""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.retirement_store import ARMS, RetirementPublicationStore

CUTS = ("before_retire", "after_cleanup", "after_commit", "after_ack")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--arm", choices=ARMS, required=True)
    parser.add_argument("--cut", choices=("none", *CUTS), required=True)
    args = parser.parse_args()
    events = []

    def event(kind: str, **fields) -> None:
        row = {"seq": len(events), "kind": kind, **fields}
        events.append(row)
        print(json.dumps(row), flush=True)

    def checkpoint(stage: str) -> None:
        event("checkpoint", stage=stage)
        if stage == args.cut:
            os._exit(73)

    result = RetirementPublicationStore(args.root, args.arm).retire(2, checkpoint=checkpoint)
    event("acknowledged", response=result)
    checkpoint("after_ack")
    event("completed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
