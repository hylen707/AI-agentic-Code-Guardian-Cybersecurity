"""One logical caller attempt with a caller-bound pipe barrier."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.caller_store import CALLERS, MODES, CallerPublicationStore
from src.publication_store import digest

PAYLOADS = {"b": b"approved=version-b\n", "c": b"approved=version-c\n", "later": b"approved=version-d\n",
            "empty": b"", "unicode": "approved=안전 ✓\n".encode(), "revoke": None,
            "nfc": "approved=é\n".encode(), "nfd": "approved=e\u0301\n".encode()}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--mode", choices=MODES, required=True)
    parser.add_argument("--caller", choices=CALLERS, required=True)
    parser.add_argument("--key", required=True)
    parser.add_argument("--epoch", type=int, default=2)
    parser.add_argument("--intent", choices=PAYLOADS, required=True)
    parser.add_argument("--pause", choices=("none", "after_lookup"), default="none")
    args = parser.parse_args()
    events = []

    def event(kind: str, **fields):
        row = {"seq": len(events), "kind": kind, **fields}
        events.append(row)
        print(json.dumps(row), flush=True)

    def checkpoint(stage: str):
        event("checkpoint", stage=stage)
        if stage == args.pause:
            event("paused", stage=stage, caller=args.caller)
            command = json.loads(sys.stdin.readline())
            if command != {"command": "resume", "stage": stage, "caller": args.caller}:
                raise ValueError("exact caller-bound resume command required")
            event("resumed", stage=stage, caller=args.caller)

    content = PAYLOADS[args.intent]
    event("attempt_started", caller=args.caller, epoch=args.epoch, request_id=args.key,
          operation="revoke" if content is None else "update", payload_sha256=None if content is None else digest(content))
    result = CallerPublicationStore(args.root, args.mode).publish_once(args.caller, args.epoch, args.key, content,
                                                                    event=event, checkpoint=checkpoint)
    event("result", response=result)
    event("completed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
