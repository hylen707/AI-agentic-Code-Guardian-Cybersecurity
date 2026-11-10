"""One numbered migration or publication attempt with an exact pipe barrier."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.progress_store import MODES, ProgressPublicationStore, publication_value
from src.publication_store import digest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--mode", choices=MODES, required=True)
    parser.add_argument("--budget", type=int, required=True)
    parser.add_argument("--role", choices=("migrate", "publish"), required=True)
    parser.add_argument("--attempt", type=int, default=1)
    parser.add_argument("--pattern", choices=("updates", "revocations"), default="updates")
    parser.add_argument("--index", type=int, default=1)
    args = parser.parse_args()
    sequence = 0

    def event(kind, **fields):
        nonlocal sequence
        print(json.dumps({"seq": sequence, "kind": kind, **fields}), flush=True)
        sequence += 1

    def checkpoint(stage):
        event("checkpoint", stage=stage)
        if args.role == "migrate" and stage == "after_selection":
            binding = {"stage": stage, "role": "migrate", "attempt": args.attempt, "budget": args.budget}
            event("paused", **binding)
            if json.loads(sys.stdin.readline()) != {"command": "resume", **binding}:
                raise ValueError("exact stage, role, attempt and budget resume required")
            event("resumed", **binding)

    store = ProgressPublicationStore(args.root, args.mode, args.budget)
    if args.role == "migrate":
        event("migration_started", target_epoch=2)
        answer = store.migrate_attempt(args.attempt, checkpoint=checkpoint, event=event)
        event("migration_result", response=answer)
    else:
        value = publication_value(args.pattern, args.index)
        key = "item-"+str(args.index)
        event("publication_started", epoch=1, request_id=key, operation="revoke" if value is None else "update",
              payload_sha256=None if value is None else digest(value))
        answer = store.publish_once(1, key, value, checkpoint=checkpoint, event=event)
        event("publication_result", response=answer)
    event("completed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
