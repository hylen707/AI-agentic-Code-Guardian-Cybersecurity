"""One migration or publisher attempt with a role/stage-bound pipe barrier."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.publication_store import digest
from src.selection_store import MODES, STAGES, SelectionPublicationStore

VALUES = {"ascii": b"approved=version-b\n", "empty": b"", "unicode": "approved=안전 ✓\n".encode(),
          "revoke": None, "later": b"approved=version-d\n"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--mode", choices=MODES, required=True)
    parser.add_argument("--role", choices=("migrate", "publish"), required=True)
    parser.add_argument("--pause", choices=(*STAGES, "none"), default="none")
    parser.add_argument("--epoch", type=int, default=1)
    parser.add_argument("--key", default="inflight")
    parser.add_argument("--value", choices=VALUES, default="ascii")
    args = parser.parse_args()
    count = 0
    def event(kind, **fields):
        nonlocal count
        print(json.dumps({"seq": count, "kind": kind, **fields}), flush=True)
        count += 1
    def checkpoint(stage):
        event("checkpoint", stage=stage)
        if args.role == "migrate" and stage == args.pause:
            event("paused", stage=stage, role="migrate")
            command = json.loads(sys.stdin.readline())
            if command != {"command": "resume", "stage": stage, "role": "migrate"}:
                raise ValueError("exact role/stage-bound resume required")
            event("resumed", stage=stage, role="migrate")
    store = SelectionPublicationStore(args.root, args.mode)
    if args.role == "migrate":
        event("migration_started", target_epoch=2)
        result = store.migrate(2, checkpoint=checkpoint, event=event)
        event("migration_result", response=result)
    else:
        value = VALUES[args.value]
        event("publication_started", epoch=args.epoch, request_id=args.key,
              operation="revoke" if value is None else "update", payload_sha256=None if value is None else digest(value))
        result = store.publish_once(args.epoch, args.key, value, checkpoint=checkpoint, event=event)
        event("publication_result", response=result)
    event("completed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
