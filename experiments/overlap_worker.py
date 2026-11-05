"""Two child roles with a strict publisher pause/resume protocol."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.overlap_store import MODES, OverlapPublicationStore

STAGES = ("after_admission", "after_final_check", "before_commit", "after_commit")
VALUES = {"ascii": b"approved=version-b\n", "empty": b"", "unicode": "approved=안전 ✓\n".encode()}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--role", choices=("publish", "retire"), required=True)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--mode", choices=MODES, required=True)
    parser.add_argument("--epoch", type=int, default=1)
    parser.add_argument("--operation", choices=("update", "revoke"), default="update")
    parser.add_argument("--value", choices=VALUES, default="ascii")
    parser.add_argument("--pause", choices=("none", *STAGES), default="none")
    args = parser.parse_args()
    events = []

    def event(kind: str, **fields) -> None:
        row = {"seq": len(events), "kind": kind, **fields}
        events.append(row)
        print(json.dumps(row), flush=True)

    store = OverlapPublicationStore(args.root, args.mode)
    if args.role == "retire":
        event("retirement_started", target_epoch=2)
        event("retirement_result", response=store.try_retire(2))
    else:
        def checkpoint(stage: str) -> None:
            event("checkpoint", stage=stage)
            if stage == args.pause:
                event("paused", stage=stage)
                command = json.loads(sys.stdin.readline())
                if command != {"command": "resume", "stage": stage}:
                    raise ValueError("exact resume command required")
                event("resumed", stage=stage)

        value = None if args.operation == "revoke" else VALUES[args.value]
        answer = store.publish_overlap(args.epoch, "inflight", value, checkpoint=checkpoint, event=event)
        event("publication_result", response=answer)
    event("completed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
