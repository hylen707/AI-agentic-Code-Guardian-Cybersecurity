"""Deterministic pathname-replacement experiment; no concurrent race-rate claim."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.descriptor_executor import DescriptorExecutor, content_io, identity
from src.executor_gate import PreparedAction
from src.identity_gate import IdentityAwareGate

ARMS = ("baseline", "identity_path", "descriptor_bound")
ORIGINAL = "ordinary fixture content\n"
PROTECTED = "synthetic protected fixture\n"
REPLACEMENT = "different ordinary fixture\n"
UPDATED = "authorized update\n"


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def load_cases(path: Path) -> list[dict]:
    data = json.loads(path.read_text())
    if data.get("schema_version") != "race-eval-v1":
        raise ValueError("unsupported case schema")
    cases = data.get("cases")
    if not isinstance(cases, list) or not cases:
        raise ValueError("nonempty cases required")
    seen = set()
    valid = {("none", "none"), ("before_check", "protected_hardlink"),
             ("after_check", "protected_hardlink"), ("after_check", "protected_parent"),
             ("after_check", "ordinary_file")}
    for case in cases:
        if (not isinstance(case, dict) or set(case) != {"case_id", "operation", "timing", "replacement"}
                or not isinstance(case["case_id"], str) or not case["case_id"]
                or case["case_id"] in seen or case["operation"] not in {"read", "write"}
                or (case["timing"], case["replacement"]) not in valid):
            raise ValueError("invalid or duplicate case")
        seen.add(case["case_id"])
    return cases


def run_case(case: dict, arm: str) -> dict:
    if arm not in ARMS:
        raise ValueError("unknown arm")
    record = {**case, "arm": arm, "status": "pending", "reason": None,
              "attack_schedule": case["replacement"].startswith("protected_"),
              "original_eligible": case["timing"] != "before_check",
              "protected_open": False, "protected_io_attempt": False,
              "protected_content_operation": False, "original_completion": False,
              "opened_identity": None, "io_identity": None, "events": []}
    with tempfile.TemporaryDirectory(prefix="codeguardian-race-") as directory:
        root = Path(directory)
        target = root / "workspace/ordinary/item.txt"
        protected = root / "workspace/protected/item.txt"
        witness = root / "oracle/original.txt"
        try:
            for file, content in ((target, ORIGINAL), (protected, PROTECTED)):
                file.parent.mkdir(parents=True, exist_ok=True)
                file.write_text(content)
            witness.parent.mkdir()
            witness.hardlink_to(target)
            original_id = identity(witness.stat())
            # The oracle holds its own protected descriptor; gates never see it.
            with protected.open("rb") as oracle_handle:
                protected_id = identity(os.fstat(oracle_handle.fileno()))
                record.update(original_identity=original_id, protected_identity=protected_id)
                prepared = PreparedAction(case["operation"], target.resolve(), UPDATED)
                gate = IdentityAwareGate(root) if arm == "identity_path" else None
                executor = DescriptorExecutor(root) if arm == "descriptor_bound" else None

                def replace() -> None:
                    kind = case["replacement"]
                    if kind == "protected_parent":
                        target.parent.rename(root / "workspace/displaced")
                        target.parent.symlink_to(protected.parent, target_is_directory=True)
                    elif kind != "none":
                        target.unlink()
                        if kind == "protected_hardlink":
                            target.hardlink_to(protected)
                        else:
                            target.write_text(REPLACEMENT)
                    record["events"].append("replacement:" + kind)

                def on_open(fd: int) -> None:
                    observed = identity(os.fstat(fd))
                    record["opened_identity"] = observed
                    record["protected_open"] = observed == protected_id
                    record["events"].append("opened")

                def before_io(fd: int) -> None:
                    observed = identity(os.fstat(fd))
                    record["io_identity"] = observed
                    record["protected_io_attempt"] = observed == protected_id
                    record["events"].append("content_io_attempt")

                def after_check() -> None:
                    record["events"].append("authorization_boundary")
                    if case["timing"] == "after_check":
                        replace()

                if case["timing"] == "before_check":
                    replace()
                if executor:
                    outcome = executor.execute(prepared, after_check=after_check,
                                               on_open=on_open, before_io=before_io)
                else:
                    decision = gate.evaluate(prepared) if gate else None
                    if decision and decision.decision == "block":
                        outcome = {"status": "blocked", "reason": decision.reason}
                    else:
                        after_check()
                        flags = os.O_RDONLY if case["operation"] == "read" else os.O_WRONLY
                        fd = os.open(prepared.target, flags | os.O_CLOEXEC)
                        try:
                            on_open(fd)
                            before_io(fd)
                            content = content_io(fd, prepared.operation, prepared.content)
                            outcome = {"status": "executed", "reason": "pathname_open", "content": content}
                        finally:
                            os.close(fd)
                record.update(status=outcome["status"], reason=outcome["reason"])
                executed = outcome["status"] == "executed"
                record["protected_content_operation"] = executed and record["protected_io_attempt"]
                returned = outcome.get("content")
                if returned is not None:
                    record["read_sha256"] = digest(returned.encode())
                original_bytes = witness.read_bytes()
                protected_bytes = protected.read_bytes()
                record["original_completion"] = bool(
                    record["original_eligible"] and executed and record["io_identity"] == original_id
                    and (returned == ORIGINAL if case["operation"] == "read" else original_bytes == UPDATED.encode()))
                record["original_final_sha256"] = digest(original_bytes)
                record["protected_final_sha256"] = digest(protected_bytes)
                record["protected_changed"] = protected_bytes != PROTECTED.encode()
        except (OSError, ValueError, RuntimeError, UnicodeError) as exc:
            record.update(status="infrastructure_error", reason=type(exc).__name__)
    return record


def summarize(records: list[dict], cases: list[dict]) -> dict:
    expected = {(c["case_id"], arm) for c in cases for arm in ARMS}
    actual = [(r["case_id"], r["arm"]) for r in records]
    if len(actual) != len(expected) or set(actual) != expected:
        raise ValueError("one record per declared case and arm required")
    arms = {}
    for arm in ARMS:
        rows = [r for r in records if r["arm"] == arm]
        arms[arm] = {
            "cases": len(rows),
            "attack_schedules": sum(r["attack_schedule"] for r in rows),
            "protected_content_operations": sum(r["protected_content_operation"] for r in rows),
            "protected_io_attempts": sum(r["protected_io_attempt"] for r in rows),
            "protected_opens": sum(r["protected_open"] for r in rows),
            "original_eligible_cases": sum(r["original_eligible"] for r in rows),
            "original_completions": sum(r["original_completion"] for r in rows),
            "benign_cases": sum(not r["attack_schedule"] for r in rows),
            "benign_blocks": sum(r["status"] == "blocked" and not r["attack_schedule"] for r in rows),
            "gate_blocks": sum(r["status"] == "blocked" for r in rows),
            "infrastructure_errors": sum(r["status"] == "infrastructure_error" for r in rows),
        }
    bound = arms["descriptor_bound"]
    return {"arms": arms, "criteria": {
        "descriptor_zero_protected_content_io": bound["protected_io_attempts"] == 0,
        "descriptor_preserves_original_object": bound["original_completions"] == bound["original_eligible_cases"],
        "descriptor_zero_benign_blocks": bound["benign_blocks"] == 0,
        "descriptor_two_metadata_only_protected_opens": bound["protected_opens"] == 2 and bound["gate_blocks"] == 2,
        "identity_path_four_after_check_failures": arms["identity_path"]["protected_content_operations"] == 4,
        "baseline_six_protected_content_operations": arms["baseline"]["protected_content_operations"] == 6,
        "no_infrastructure_errors": all(a["infrastructure_errors"] == 0 for a in arms.values()),
    }}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--base-commit", required=True)
    parser.add_argument("--freeze-commit", required=True)
    parser.add_argument("--output-dir", type=Path, default=ROOT / "experiments/results")
    args = parser.parse_args()
    started = datetime.now(timezone.utc)
    cases = load_cases(args.dataset)
    records = [run_case(case, arm) for case in cases for arm in ARMS]
    summary = summarize(records, cases)
    run_id = started.strftime("%Y-%m-%dT%H-%M-%S-%fZ-race-v1")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    raw = args.output_dir / (run_id + ".jsonl")
    sources = ["src/descriptor_executor.py", "src/identity_gate.py", "src/executor_gate.py",
               "src/codeguardian.py", "experiments/run_race_comparison.py",
               "tests/test_descriptor_executor.py", "docs/RACE_PROTOCOL.md"]
    metadata = {"started_at_utc": started.isoformat(), "finished_at_utc": datetime.now(timezone.utc).isoformat(),
                "python_version": platform.python_version(), "platform": platform.platform(),
                "base_commit": args.base_commit, "freeze_commit": args.freeze_commit,
                "dataset_sha256": digest(args.dataset.read_bytes()),
                "source_sha256": {p: digest((ROOT / p).read_bytes()) for p in sources},
                "command": [sys.executable, *sys.argv], "results_file": raw.name, "summary": summary,
                "interpretation_limit": "Ten deterministic schedules, not concurrent win rates or live-agent completion; protected opens differ from protected content I/O."}
    with raw.open("x") as handle:
        for record in records:
            handle.write(json.dumps(record) + "\n")
    with (args.output_dir / (run_id + "-summary.json")).open("x") as handle:
        json.dump(metadata, handle, indent=2)
        handle.write("\n")
    print(json.dumps(summary, indent=2))
    print(f"Saved {run_id}")
    return int(not summary["criteria"]["no_infrastructure_errors"])


if __name__ == "__main__":
    raise SystemExit(main())
