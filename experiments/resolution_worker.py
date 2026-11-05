"""One caller or retirement probe for the receipt-resolution comparison."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.publication_store import digest
from src.resolution_store import CALLERS, MODES, ResolutionPublicationStore

PAYLOADS = {
    "b": b"approved=version-b\n", "c": b"approved=version-c\n", "later": b"approved=version-d\n",
    "empty": b"", "revoke": None, "unicode": "approved=안전 ✓\n".encode(),
    "nfc": "approved=é\n".encode(), "nfd": "approved=e\u0301\n".encode(),
}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--mode", choices=MODES, required=True)
    parser.add_argument("--role", choices=("caller", "retire"), required=True)
    parser.add_argument("--caller", choices=CALLERS, default="first")
    parser.add_argument("--epoch", type=int, default=2)
    parser.add_argument("--key", default="shared-request")
    parser.add_argument("--intent", choices=PAYLOADS, default="b")
    parser.add_argument("--pauses", choices=("both", "none"), default="none")
    parser.add_argument("--target", type=int, default=3)
    args = parser.parse_args()
    count = 0

    def event(kind, **fields):
        nonlocal count
        print(json.dumps({"seq": count, "kind": kind, **fields}), flush=True)
        count += 1

    def checkpoint(stage):
        event("checkpoint", stage=stage)
        if args.pauses == "both" and stage in {"after_precheck", "before_resolution"}:
            event("paused", stage=stage, caller=args.caller)
            command = json.loads(sys.stdin.readline())
            if command != {"command": "resume", "stage": stage, "caller": args.caller}:
                raise ValueError("exact caller-bound resume required")
            event("resumed", stage=stage, caller=args.caller)

    store = ResolutionPublicationStore(args.root, args.mode)
    if args.role == "retire":
        event("retirement_started", target_epoch=args.target)
        result = store.try_retire(args.target)
        event("retirement_result", response=result)
    else:
        content = PAYLOADS[args.intent]
        event("caller_started", caller=args.caller, epoch=args.epoch, request_id=args.key,
              operation="revoke" if content is None else "update", payload_sha256=None if content is None else digest(content))
        result = store.publish(args.caller, args.epoch, args.key, content, checkpoint=checkpoint, event=event)
        event("caller_result", response=result)
    event("completed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
