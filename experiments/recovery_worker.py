"""Publish only trusted fixture values, exiting at a declared application cut."""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.publication_store import SQLitePublicationStore, SplitPublicationStore

ARMS = ("split_unchecked", "split_verified", "sqlite_atomic")
CUTS = ("none", "before_publish", "after_stage", "after_commit", "after_ack")
EXIT_AT_CUT = 73
UPDATED = b"approved=version-b\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--arm", choices=ARMS, required=True)
    parser.add_argument("--transition", choices=("none", "update", "revoke"), required=True)
    parser.add_argument("--cut", choices=CUTS, required=True)
    args = parser.parse_args()
    if (args.transition == "none") != (args.cut == "none"):
        raise ValueError("controls have no cut; publications require a cut")
    journal = []

    def event(kind: str, **fields) -> None:
        row = {"seq": len(journal), "kind": kind, **fields}
        journal.append(row)
        print(json.dumps(row), flush=True)

    def checkpoint(stage: str) -> None:
        event("checkpoint", stage=stage)
        if stage == args.cut:
            os._exit(EXIT_AT_CUT)

    store_type = SQLitePublicationStore if args.arm == "sqlite_atomic" else SplitPublicationStore
    store = store_type(args.root)
    if args.transition == "none":
        event("control")
    else:
        result = store.publish(UPDATED if args.transition == "update" else None, checkpoint=checkpoint)
        event("acknowledged", revision=result.revision, approved_sha256=result.approved_sha256)
        checkpoint("after_ack")
    event("completed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
