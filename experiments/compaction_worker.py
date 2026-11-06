"""One receipt-migration child with a declared application-level exit cut."""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.compaction_store import MODES, STAGES, CompactionPublicationStore

EXIT_CODE = 73


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--mode", choices=MODES, required=True)
    parser.add_argument("--cut", choices=(*STAGES, "normal"), required=True)
    args = parser.parse_args()
    count = 0

    def event(kind, **fields):
        nonlocal count
        print(json.dumps({"seq": count, "kind": kind, **fields}), flush=True)
        count += 1

    def checkpoint(stage):
        event("checkpoint", stage=stage)
        if stage == args.cut:
            event("declared_exit", stage=stage, exit_code=EXIT_CODE)
            os._exit(EXIT_CODE)

    event("compaction_started", target_epoch=2)
    result = CompactionPublicationStore(args.root, args.mode).compact_to(2, checkpoint=checkpoint)
    event("compaction_result", response=result)
    event("completed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
