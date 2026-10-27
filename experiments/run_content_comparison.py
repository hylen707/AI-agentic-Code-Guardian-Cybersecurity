"""Compare content-version delivery under deterministic same-inode mutation."""
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

from src.descriptor_executor import DescriptorExecutor, identity
from src.executor_gate import PreparedAction
from src.verified_content_reader import VerifiedContentReader

ARMS = ("identity_only", "hash_then_reread", "verified_buffer")
FIXTURES = {"ascii": "approved=true\n", "unicode": "approved=안전 ✓\n", "empty": ""}


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class ContentMismatch(Exception):
    """Only an observed digest mismatch may become a comparator policy block."""


def inspect_descriptor(fd: int) -> bytes:
    chunks = []
    offset = 0
    while chunk := os.pread(fd, 65536, offset):
        chunks.append(chunk)
        offset += len(chunk)
    return b"".join(chunks)


def load_cases(path: Path) -> list[dict]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or data.get("schema_version") != "content-eval-v1":
        raise ValueError("unsupported content schema")
    cases = data.get("cases")
    if not isinstance(cases, list) or not cases:
        raise ValueError("nonempty cases required")
    seen = set()
    valid = {("none", "none"), ("before_capture", "overwrite"),
             ("before_capture", "truncate"), ("after_validation", "overwrite"),
             ("after_validation", "truncate"), ("after_validation", "append")}
    for case in cases:
        if (not isinstance(case, dict) or set(case) != {"case_id", "fixture", "timing", "mutation"}
                or not all(isinstance(v, str) for v in case.values())
                or not case["case_id"] or case["case_id"] in seen
                or case["fixture"] not in FIXTURES
                or (case["timing"], case["mutation"]) not in valid
                or (case["mutation"] != "none" and case["fixture"] != "ascii")):
            raise ValueError("invalid or duplicate content case")
        seen.add(case["case_id"])
    return cases


def run_case(case: dict, arm: str) -> dict:
    if arm not in ARMS:
        raise ValueError("unknown content arm")
    approved = FIXTURES[case["fixture"]].encode("utf-8")
    expected_digest = digest(approved)
    record = {**case, "arm": arm, "status": "pending", "reason": None,
              "approved_sha256": expected_digest, "approved_bytes": len(approved),
              "inspected_sha256": None, "inspected_bytes": None,
              "delivered_sha256": None, "delivered_bytes": None,
              "final_sha256": None, "final_bytes": None,
              "opened_identity": None, "io_identity": None, "final_identity": None,
              "approved_delivery": False, "unapproved_delivery": False,
              "approved_but_stale": False, "identity_continuity": False,
              "events": []}
    with tempfile.TemporaryDirectory(prefix="codeguardian-content-") as directory:
        root = Path(directory)
        target = root / "workspace/document.txt"
        alias = root / "controller/document-alias.txt"
        protected = root / "workspace/protected/sentinel.txt"
        try:
            protected.parent.mkdir(parents=True)
            protected.write_text("synthetic protected sentinel\n", encoding="utf-8")
            target.write_bytes(approved)
            alias.parent.mkdir()
            alias.hardlink_to(target)
            with target.open("rb") as oracle:
                original_id = identity(os.fstat(oracle.fileno()))
                record["original_identity"] = original_id
                action = PreparedAction("read", target.resolve())
                executor = DescriptorExecutor(root)
                reader = VerifiedContentReader(root, {action.target: expected_digest}) if arm == "verified_buffer" else None
                payload = None

                def mutate() -> None:
                    kind = case["mutation"]
                    if kind == "overwrite":
                        updated = b"approved=oops\n"
                        if len(updated) != len(approved):
                            raise ValueError("overwrite must retain byte length")
                        alias.write_bytes(updated)
                    elif kind == "truncate":
                        with alias.open("r+b") as handle:
                            handle.truncate(5)
                    elif kind == "append":
                        with alias.open("ab") as handle:
                            handle.write(b"late update\n")
                    else:
                        raise ValueError("unexpected mutation")
                    record["events"].append("mutation:" + kind)
                    if identity(alias.stat()) != original_id or identity(target.stat()) != original_id:
                        raise ValueError("mutation changed file identity")

                def after_identity() -> None:
                    record["events"].append("identity_authorized")
                    if case["timing"] == "before_capture":
                        mutate()

                def after_validation() -> None:
                    record["events"].append("content_checkpoint")
                    if case["timing"] == "after_validation":
                        mutate()

                def on_open(fd: int) -> None:
                    record["opened_identity"] = identity(os.fstat(fd))
                    record["events"].append("opened")

                def on_validation(observed: str, size: int) -> None:
                    record.update(inspected_sha256=observed, inspected_bytes=size)
                    record["events"].append("content_inspected")

                def before_io(fd: int) -> None:
                    record["io_identity"] = identity(os.fstat(fd))
                    if arm == "hash_then_reread":
                        inspected = inspect_descriptor(fd)
                        on_validation(digest(inspected), len(inspected))
                        if digest(inspected) != expected_digest:
                            raise ContentMismatch()
                        after_validation()
                    elif arm == "identity_only":
                        after_validation()
                    record["events"].append("payload_read_start")

                try:
                    if reader:
                        outcome = reader.read(action, after_identity_check=after_identity,
                                              after_validation=after_validation, on_open=on_open,
                                              before_io=before_io, on_validation=on_validation)
                    else:
                        outcome = executor.execute(action, after_check=after_identity,
                                                   on_open=on_open, before_io=before_io)
                except ContentMismatch:
                    outcome = {"status": "blocked", "reason": "content_version_mismatch"}
                except (OSError, ValueError, RuntimeError, UnicodeError) as exc:
                    outcome = {"status": "infrastructure_error", "reason": type(exc).__name__}
                record.update(status=outcome["status"], reason=outcome["reason"])
                if outcome["status"] == "executed":
                    payload = outcome["content"].encode("utf-8")
                    record.update(status="delivered", delivered_sha256=digest(payload),
                                  delivered_bytes=len(payload))
                    record["events"].append("payload_released")
                # Oracle inspection is separate from the evaluated consumer's receipt.
                final = oracle.read()
                final_id = identity(os.fstat(oracle.fileno()))
                record.update(final_identity=final_id, final_sha256=digest(final), final_bytes=len(final))
                record["identity_continuity"] = (
                    final_id == original_id == identity(target.stat()) == identity(alias.stat())
                    and record["opened_identity"] == original_id
                    and record["io_identity"] == original_id)
                record["approved_delivery"] = payload is not None and payload == approved
                record["unapproved_delivery"] = payload is not None and payload != approved
                record["approved_but_stale"] = payload is not None and payload == approved and payload != final
                if not record["identity_continuity"]:
                    record.update(status="infrastructure_error", reason="identity_continuity_failed")
        except (OSError, ValueError, RuntimeError, UnicodeError) as exc:
            record.update(status="infrastructure_error", reason=type(exc).__name__)
    return record


def summarize(records: list[dict], cases: list[dict]) -> dict:
    expected = {(c["case_id"], arm) for c in cases for arm in ARMS}
    actual = [(r["case_id"], r["arm"]) for r in records]
    if len(actual) != len(expected) or set(actual) != expected:
        raise ValueError("one record per declared content case and arm required")
    declared = {c["case_id"]: c for c in cases}
    for row in records:
        if any(row[key] != value for key, value in declared[row["case_id"]].items()):
            raise ValueError("record does not match declared case")
    arms = {}
    for arm in ARMS:
        rows = [r for r in records if r["arm"] == arm]
        arms[arm] = {
            "cases": len(rows), "mutation_cases": sum(r["mutation"] != "none" for r in rows),
            "deliveries": sum(r["status"] == "delivered" for r in rows),
            "approved_deliveries": sum(r["approved_delivery"] for r in rows),
            "unapproved_deliveries": sum(r["unapproved_delivery"] for r in rows),
            "content_blocks": sum(r["status"] == "blocked" and r["reason"] == "content_version_mismatch" for r in rows),
            "other_blocks": sum(r["status"] == "blocked" and r["reason"] != "content_version_mismatch" for r in rows),
            "controls": sum(r["mutation"] == "none" for r in rows),
            "approved_control_deliveries": sum(r["mutation"] == "none" and r["approved_delivery"] for r in rows),
            "approved_but_stale": sum(r["approved_but_stale"] for r in rows),
            "identity_continuity_cases": sum(r["identity_continuity"] for r in rows),
            "infrastructure_errors": sum(r["status"] == "infrastructure_error" for r in rows),
        }
    return {"arms": arms, "criteria": {
        "identity_only_five_unapproved_deliveries": arms["identity_only"]["unapproved_deliveries"] == 5,
        "reread_three_unapproved_deliveries": arms["hash_then_reread"]["unapproved_deliveries"] == 3,
        "buffer_zero_unapproved_deliveries": arms["verified_buffer"]["unapproved_deliveries"] == 0,
        "buffer_six_approved_deliveries": arms["verified_buffer"]["approved_deliveries"] == 6,
        "both_digest_arms_block_two_pre_capture_changes": all(arms[a]["content_blocks"] == 2 for a in ARMS[1:]),
        "all_controls_delivered_correctly": all(a["approved_control_deliveries"] == 3 for a in arms.values()),
        "buffer_three_approved_but_stale_deliveries": arms["verified_buffer"]["approved_but_stale"] == 3,
        "all_identities_stable": all(a["identity_continuity_cases"] == len(cases) for a in arms.values()),
        "no_infrastructure_errors_or_other_blocks": all(a["infrastructure_errors"] == a["other_blocks"] == 0 for a in arms.values()),
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
    run_id = started.strftime("%Y-%m-%dT%H-%M-%S-%fZ-content-v1")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    raw = args.output_dir / (run_id + ".jsonl")
    sources = ["src/verified_content_reader.py", "src/descriptor_executor.py", "src/executor_gate.py",
               "src/codeguardian.py", "experiments/run_content_comparison.py",
               "tests/test_verified_content_reader.py", "docs/CONTENT_PROTOCOL.md"]
    approved = {key: digest(value.encode("utf-8")) for key, value in FIXTURES.items()}
    metadata = {
        "started_at_utc": started.isoformat(), "finished_at_utc": datetime.now(timezone.utc).isoformat(),
        "python_version": platform.python_version(), "platform": platform.platform(),
        "base_commit": args.base_commit, "freeze_commit": args.freeze_commit,
        "dataset_sha256": digest(args.dataset.read_bytes()),
        "approved_fixture_sha256": approved,
        "configuration_sha256": digest(json.dumps(approved, sort_keys=True).encode()),
        "source_sha256": {p: digest((ROOT / p).read_bytes()) for p in sources},
        "command": [sys.executable, *sys.argv], "results_file": raw.name, "summary": summary,
        "interpretation_limit": "Eight deterministic same-inode cases; approved delivery is distinct from freshness, protected-resource access, and live-agent completion.",
    }
    with raw.open("x", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record) + "\n")
    with (args.output_dir / (run_id + "-summary.json")).open("x", encoding="utf-8") as handle:
        json.dump(metadata, handle, indent=2)
        handle.write("\n")
    print(json.dumps(summary, indent=2))
    print(f"Saved {run_id}")
    return int(any(a["infrastructure_errors"] or a["other_blocks"] for a in summary["arms"].values()))


if __name__ == "__main__":
    raise SystemExit(main())
