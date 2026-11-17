"""Independent structural and outcome checks for the bounded resumption pilot."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def verify(path):
    path = Path(path)
    metadata = json.loads(path.with_suffix(".metadata.json").read_text())
    if hashlib.sha256(path.read_bytes()).hexdigest() != metadata["results_sha256"]:
        raise ValueError("raw result hash mismatch")
    sources = {str(p.relative_to(ROOT)) for p in (ROOT/"src").glob("*.py")}
    sources.update(("experiments/run_resumption_comparison.py", "experiments/verify_resumption_results.py"))
    if set(metadata["source_sha256"]) != sources:
        raise ValueError("incomplete source coverage")
    for name, digest in metadata["source_sha256"].items():
        if hashlib.sha256((ROOT/name).read_bytes()).hexdigest() != digest:
            raise ValueError("source hash mismatch: "+name)
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    return evaluate(rows, metadata["records"])


def evaluate(rows, declared_count=14):
    schedules = ("admission_overtaken", "selection_overtaken", "writer_collision", "both_selected")
    modes = ("restart_baseline", "reconciled_resumption")
    expected = {(s, b, m) for s in schedules for b in (1, 2) for m in modes
                if not (s == "both_selected" and b == 1)}
    keys = [(r["schedule"], r["budget"], r["mode"]) for r in rows]
    if len(rows) != declared_count or len(keys) != len(set(keys)) or set(keys) != expected:
        raise ValueError("case grid mismatch")
    summary = {m: dict(cases=0, caller_errors=0, retry_later=0, budget_snapshots=0,
                       converged_cases=0, excess_admissions=0, history_failures=0) for m in modes}
    for row in rows:
        schedule, budget, mode = row["schedule"], row["budget"], row["mode"]
        arm = summary[mode]; arm["cases"] += 1
        if row["boundary_a"] != dict(kind="pause", stage=dict(admission_overtaken="after_admission",
                selection_overtaken="after_selection", writer_collision="before_commit", both_selected="after_selection")[schedule], generation=1):
            raise ValueError("missing first caller barrier")
        expected_b = dict(kind="pause", stage="after_selection", generation=2) if schedule == "both_selected" else None
        if row["boundary_b"] != expected_b:
            raise ValueError("missing second caller barrier")
        admissions = row["admissions"]
        expected_admissions = 1 if budget == 1 or schedule == "writer_collision" else 2
        if len(admissions) != expected_admissions or row["job"] != dict(policy="reserved_reconcile", budget=budget, target_epoch=2, used=len(admissions)):
            raise ValueError("durable reservation mismatch")
        for number, admission in enumerate(admissions, 1):
            if admission != dict(ordinal=number, generation=number, attempt_number=number,
                                 persisted_before=number-1, persisted_after=number):
                raise ValueError("admission ledger mismatch")
        arm["excess_admissions"] += max(0, len(admissions)-budget)
        if len(row["callers"]) != 2 or len(row["followups"]) != 2:
            raise ValueError("missing caller outcome")
        expected_status = ["completed", "completed"]
        if budget == 1 and schedule != "writer_collision":
            expected_status[1] = "budget_exhausted"
        if schedule == "writer_collision":
            expected_status[1] = "error" if mode == modes[0] else "retry_later"
        if schedule == "admission_overtaken" and budget == 2 and mode == modes[0]:
            expected_status[0] = "error"
        for message, expected_outcome in zip(row["callers"], expected_status):
            if expected_outcome == "error":
                expected_type = "OperationalError" if schedule == "writer_collision" else "ValueError"
                if message["kind"] != "error" or message["error_type"] != expected_type:
                    raise ValueError("unexpected caller error")
                if expected_type == "OperationalError" and message["sqlite_errorcode"] != 5:
                    raise ValueError("error was not writer contention")
                arm["caller_errors"] += 1
            else:
                if message["kind"] != "result" or message["response"]["status"] != expected_outcome:
                    raise ValueError("unexpected caller result")
                result = message["response"]
                if result["budget"] != budget:
                    raise ValueError("response changed budget")
                if expected_outcome == "retry_later":
                    if result != dict(status="retry_later", reason="writer_busy", budget=budget):
                        raise ValueError("invalid retry answer")
                    arm["retry_later"] += 1
                elif expected_outcome == "budget_exhausted":
                    if result["active_epoch"] != 1 or result["used"] != budget:
                        raise ValueError("exhaustion snapshot mismatch")
                    arm["budget_snapshots"] += 1
                elif result["active_epoch"] != 2 or not 1 <= result["used"] <= budget:
                    raise ValueError("unjustified completion")
        for message in row["followups"]:
            if message["kind"] != "result" or message["response"] != dict(status="completed", active_epoch=2, used=len(admissions), budget=budget):
                raise ValueError("caller did not converge to durable target")
        if row["active_epoch"] != 2 or row["migration_witness"] != dict(target_epoch=2, selected_revision=2,
                write_revision=2, selected_count=1, write_count=1):
            raise ValueError("invalid migration closure")
        payload_digest = hashlib.sha256(b"approved=B\n").hexdigest()
        if row["effects"] != [dict(revision=2, epoch=1, request_id="seed", operation="update", approved_sha256=payload_digest)]:
            raise ValueError("unexpected publication effect")
        if row["summaries"] != [dict(epoch=1, request_id="seed", operation="update", payload_sha256=payload_digest, revision=2)]:
            raise ValueError("lost historical authority")
        expected_original = dict(status="committed", epoch=1, request_id="seed", revision=2, approved_sha256=payload_digest)
        if row["original"] != expected_original or row["replay"] != {**expected_original, "status":"replayed"} or row["conflict"]["status"] != "conflict":
            raise ValueError("historical response mismatch")
        arm["converged_cases"] += 1
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser(); parser.add_argument("results", type=Path)
    print(json.dumps(verify(parser.parse_args().results), indent=2))
