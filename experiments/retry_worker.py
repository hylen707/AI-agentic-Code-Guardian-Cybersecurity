"""Publish one trusted request, with an exact application-checkpoint exit."""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.retry_store import ARMS, RetryPublicationStore

CUTS = ("before_commit", "after_state_commit", "after_record_commit", "after_ack")
VALUES = {"ascii": b"approved=version-b\n", "empty": b"", "unicode": "approved=안전 ✓\n".encode("utf-8")}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--arm", choices=ARMS, required=True)
    parser.add_argument("--operation", choices=("update", "revoke"), required=True)
    parser.add_argument("--value", choices=VALUES, required=True)
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

    store = RetryPublicationStore(args.root, args.arm)
    response = store.publish_request("request-1", None if args.operation == "revoke" else VALUES[args.value],
                                     checkpoint=checkpoint)
    event("acknowledged", response=response)
    checkpoint("after_ack")
    event("completed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
