"""Deterministic two-process continuation of the restart study (standard library)."""
from __future__ import annotations

import argparse
import hashlib
import json
import multiprocessing
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from src.restart_store import RestartPublicationStore
from src.resumption_store import ResumptionPublicationStore

SCHEDULES = ("admission_overtaken", "selection_overtaken", "writer_collision", "both_selected")
MODES = ("restart_baseline", "reconciled_resumption")
SOURCES = tuple(sorted(str(p.relative_to(ROOT)) for p in (ROOT/"src").glob("*.py"))) + (
    "experiments/run_resumption_comparison.py", "experiments/verify_resumption_results.py")


def worker(root, mode, budget, generation, pause, pipe):
    events = []
    def event(kind, **fields):
        events.append(dict(kind=kind, **fields))
    def checkpoint(stage):
        if stage == pause:
            pipe.send(dict(kind="pause", stage=stage, generation=generation))
            if not pipe.poll(10) or pipe.recv() != dict(command="resume", stage=stage, generation=generation):
                raise RuntimeError("missing exact caller resume")
    cls = RestartPublicationStore if mode == MODES[0] else ResumptionPublicationStore
    try:
        result = cls(Path(root), "reserved_reconcile", budget).run_job(generation, checkpoint=checkpoint, event=event)
        pipe.send(dict(kind="result", response=result, events=events))
    except Exception as error:
        pipe.send(dict(kind="error", error_type=type(error).__name__, detail=str(error),
                       sqlite_errorcode=getattr(error, "sqlite_errorcode", None), events=events))
    finally:
        pipe.close()


def receive(pipe):
    if not pipe.poll(10):
        raise TimeoutError("caller did not reach scheduled boundary")
    return pipe.recv()


def run_case(schedule, budget, mode):
    if schedule not in SCHEDULES or mode not in MODES or type(budget) is not int or budget not in (1, 2):
        raise ValueError("unknown declared case")
    if schedule == "both_selected" and budget == 1:
        raise ValueError("two admitted selections require two slots")
    context = multiprocessing.get_context("spawn")
    children = []
    def start(root, generation, pause=None):
        parent, child = context.Pipe()
        process = context.Process(target=worker, args=(str(root), mode, budget, generation, pause, child))
        process.start(); child.close()
        children.append((process, parent))
        return process, parent
    def finish(process, pipe):
        message = receive(pipe)
        process.join(10)
        if process.exitcode != 0 or message["kind"] not in ("result", "error"):
            raise RuntimeError("caller failed outside recorded outcome")
        return message
    try:
        with tempfile.TemporaryDirectory(prefix="codeguardian-resumption-") as directory:
            root = Path(directory)/"store"
            store = RestartPublicationStore(root, "reserved_reconcile", budget)
            store.initialize(b"approved=A\n")
            original = store.publish_once(1, "seed", b"approved=B\n")
            stage = dict(admission_overtaken="after_admission", selection_overtaken="after_selection",
                         writer_collision="before_commit", both_selected="after_selection")[schedule]
            a, pa = start(root, 1, stage)
            boundary_a = receive(pa)
            if boundary_a != dict(kind="pause", stage=stage, generation=1):
                raise RuntimeError("first caller missed boundary")
            b, pb = start(root, 2, "after_selection" if schedule == "both_selected" else None)
            boundary_b = None
            if schedule == "both_selected":
                boundary_b = receive(pb)
                if boundary_b != dict(kind="pause", stage="after_selection", generation=2):
                    raise RuntimeError("second caller missed selection")
                pa.send(dict(command="resume", stage=stage, generation=1))
                result_a = finish(a, pa)
                pb.send(dict(command="resume", stage="after_selection", generation=2))
                result_b = finish(b, pb)
            else:
                result_b = finish(b, pb)
                pa.send(dict(command="resume", stage=stage, generation=1))
                result_a = finish(a, pa)
            # Both original responses remain in evidence. Follow-up calls test convergence.
            followups = []
            for generation in (3, 4):
                process, pipe = start(root, generation)
                followups.append(finish(process, pipe))
            state = store.inspect()
            replay = store.publish_once(1, "seed", b"approved=B\n")
            conflict = store.publish_once(1, "seed", b"changed\n")
            return dict(schedule=schedule, budget=budget, mode=mode, boundary_a=boundary_a,
                        boundary_b=boundary_b, callers=[result_a, result_b], followups=followups,
                        active_epoch=state["active_epoch"], job=state["job"], admissions=state["admissions"],
                        effects=state["effects"], summaries=state["summaries"],
                        migration_witness=state["migration_witness"], original=original, replay=replay, conflict=conflict)
    finally:
        for process, pipe in children:
            if process.is_alive():
                process.kill()
            process.join(5); pipe.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    rows = [run_case(s, b, m) for s in SCHEDULES for b in (1, 2)
            if not (s == "both_selected" and b == 1) for m in MODES]
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(''.join(json.dumps(row, sort_keys=True)+'\n' for row in rows))
    metadata = dict(base_commit=subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
                    source_sha256={p: hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in SOURCES},
                    records=len(rows), results_sha256=hashlib.sha256(args.output.read_bytes()).hexdigest())
    args.output.with_suffix(".metadata.json").write_text(json.dumps(metadata, indent=2)+'\n')
    print(json.dumps(metadata))


if __name__ == "__main__":
    main()
