"""Compare restart authorization after publisher termination at fixed cuts."""
from __future__ import annotations

import argparse
import hashlib
import json
import platform
import sqlite3
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.publication_store import SQLitePublicationStore, SplitPublicationStore, recover_value

ARMS = ("split_unchecked", "split_verified", "sqlite_atomic")
FIXTURES = {"ascii": "approved=version-a\n", "empty": "", "unicode": "approved=안전 ✓\n"}
CUTS = ("before_publish", "after_stage", "after_commit", "after_ack")


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def load_cases(path: Path) -> list[dict]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or set(data) != {"schema_version", "cases"} or data["schema_version"] != "recovery-eval-v1":
        raise ValueError("unsupported recovery manifest")
    cases = data["cases"]
    if not isinstance(cases, list) or not cases:
        raise ValueError("nonempty cases required")
    ids, settings = set(), set()
    for case in cases:
        if (not isinstance(case, dict) or set(case) != {"case_id", "fixture", "transition", "cut"}
                or not all(isinstance(v, str) for v in case.values()) or not case["case_id"]
                or case["case_id"] in ids or case["fixture"] not in FIXTURES):
            raise ValueError("invalid or duplicate case")
        signature = (case["fixture"], case["transition"], case["cut"])
        valid = ((case["transition"] == "none" and case["cut"] == "none")
                 or (case["fixture"] in {"ascii", "empty"} and case["transition"] in {"update", "revoke"}
                     and case["cut"] in CUTS))
        if not valid or signature in settings:
            raise ValueError("invalid or repeated schedule")
        ids.add(case["case_id"])
        settings.add(signature)
    return cases


def expected_state(case: dict) -> dict:
    initial = FIXTURES[case["fixture"]]
    committed = case["transition"] != "none" and case["cut"] in {"after_commit", "after_ack"}
    content = "approved=version-b\n" if committed and case["transition"] == "update" else initial
    revoked = committed and case["transition"] == "revoke"
    return {"revision": 2 if committed else 1,
            "approved_sha256": None if revoked else sha(content.encode("utf-8")),
            "content_utf8": content, "content_sha256": sha(content.encode("utf-8"))}


def validate_worker_trace(case: dict, returncode: int, events: list[dict]) -> None:
    """A random child failure is not a successfully injected fault."""
    if case["transition"] == "none":
        expected = [{"seq": 0, "kind": "control"}, {"seq": 1, "kind": "completed"}]
        status = 0
    else:
        expected = []
        for stage in CUTS:
            if stage == "after_ack":
                expected.append({"seq": len(expected), "kind": "acknowledged", "revision": 2,
                                 "approved_sha256": None if case["transition"] == "revoke" else sha(b"approved=version-b\n")})
            expected.append({"seq": len(expected), "kind": "checkpoint", "stage": stage})
            if stage == case["cut"]:
                break
        status = 73
    if returncode != status or events != expected:
        raise ValueError("publisher did not reach exactly the declared termination boundary")


def assess_recovery(row: dict) -> dict:
    """Oracle uses declared bytes/revision and actual recovered output."""
    expected = expected_state(row)
    observed, recovery = row["observed_state"], row["recovery"]
    if (not isinstance(observed, dict) or set(observed) != set(expected)
            or type(observed["revision"]) is not int
            or not isinstance(observed["content_utf8"], str)
            or observed["content_sha256"] != sha(observed["content_utf8"].encode("utf-8"))):
        raise ValueError("invalid recovered-state observation")
    if recovery["status"] not in {"delivered", "blocked"}:
        raise ValueError("unknown recovery outcome")
    delivered = recovery["status"] == "delivered"
    payload = recovery["delivered_utf8"]
    if (delivered and not isinstance(payload, str)) or (not delivered and payload is not None):
        raise ValueError("delivery and payload presence disagree")
    if recovery["revision"] != observed["revision"] or (delivered and payload != observed["content_utf8"]):
        raise ValueError("recovery output differs from the captured state")
    active = expected["approved_sha256"] is not None
    valid = (delivered and active and recovery["revision"] == expected["revision"]
             and payload == expected["content_utf8"])
    coherent = observed == expected
    return {"state_coherent": coherent, "active_approval_case": active,
            "valid_delivery": valid, "invalid_delivery": delivered and not valid,
            "revocation_denied": not active and recovery["status"] == "blocked"
                                  and recovery["reason"] == "approval_revoked",
            "acknowledged_recovered": row["cut"] == "after_ack" and coherent,
            "committed_without_ack_recovered": row["cut"] == "after_commit" and coherent}


def inventory(root: Path) -> list[dict]:
    return [{"name": p.name, "bytes": p.stat().st_size, "sha256": sha(p.read_bytes())}
            for p in sorted(root.iterdir()) if p.is_file()]


def run_case(case: dict, arm: str) -> dict:
    if arm not in ARMS:
        raise ValueError("unknown store arm")
    row = {**case, "arm": arm, "status": "pending", "error_phase": "setup", "error_type": None,
           "worker_returncode": None, "worker_stdout": "", "worker_stderr": "", "worker_events": [],
           "observed_state": None, "recovery": None, "oracle": None,
           "inventory_before": None, "inventory_after_exit": None, "inventory_after_recovery": None,
           "sqlite_settings": None}
    with tempfile.TemporaryDirectory(prefix="codeguardian-recovery-") as directory:
        root = Path(directory)
        store_type = SQLitePublicationStore if arm == "sqlite_atomic" else SplitPublicationStore
        try:
            store_type(root).initialize(FIXTURES[case["fixture"]].encode("utf-8"))
            row["inventory_before"] = inventory(root)
            command = [sys.executable, str(ROOT / "experiments/recovery_worker.py"), "--root", str(root),
                       "--arm", arm, "--transition", case["transition"], "--cut", case["cut"]]
            row["worker_command"] = command
            row["error_phase"] = "publisher"
            child = subprocess.run(command, capture_output=True, text=True, timeout=15)
            row.update(worker_returncode=child.returncode, worker_stdout=child.stdout, worker_stderr=child.stderr)
            row["inventory_after_exit"] = inventory(root)
            row["error_phase"] = "trace_validation"
            events = [json.loads(line) for line in child.stdout.splitlines()]
            row["worker_events"] = events
            validate_worker_trace(case, child.returncode, events)
            if child.stderr:
                raise ValueError("unexpected publisher stderr")
            row["error_phase"] = "recovery"
            reopened = store_type(root)
            state = reopened.snapshot()
            row["observed_state"] = {"revision": state.revision, "approved_sha256": state.approved_sha256,
                                     "content_utf8": state.content.decode("utf-8"), "content_sha256": sha(state.content)}
            outcome = recover_value(state, verify=arm != "split_unchecked")
            content = outcome.pop("content")
            row["recovery"] = {**outcome, "delivered_utf8": None if content is None else content.decode("utf-8")}
            row["inventory_after_recovery"] = inventory(root)
            if arm == "sqlite_atomic":
                row["sqlite_settings"] = reopened.settings()
                if row["sqlite_settings"] != {"journal_mode": "delete", "synchronous": 2, "integrity_check": "ok"}:
                    raise RuntimeError("unexpected SQLite settings or integrity result")
            row["error_phase"] = "oracle"
            row["oracle"] = assess_recovery(row)
            row.update(status="complete", error_phase=None)
        except (OSError, ValueError, RuntimeError, UnicodeError, sqlite3.Error, subprocess.SubprocessError) as exc:
            row.update(status="infrastructure_error", error_type=type(exc).__name__)
            if isinstance(exc, subprocess.TimeoutExpired):
                row["worker_stdout"] = (exc.stdout or b"").decode("utf-8", errors="replace") if isinstance(exc.stdout, bytes) else exc.stdout or ""
                row["worker_stderr"] = (exc.stderr or b"").decode("utf-8", errors="replace") if isinstance(exc.stderr, bytes) else exc.stderr or ""
    return row


def summarize(records: list[dict], cases: list[dict]) -> dict:
    expected = {(case["case_id"], arm) for case in cases for arm in ARMS}
    actual = [(row["case_id"], row["arm"]) for row in records]
    if len(actual) != len(expected) or set(actual) != expected:
        raise ValueError("exactly one record per declared case/arm required")
    declared = {case["case_id"]: case for case in cases}
    for row in records:
        if any(row[k] != value for k, value in declared[row["case_id"]].items()):
            raise ValueError("record changed a declared schedule")
        if row["status"] == "complete":
            validate_worker_trace(row, row["worker_returncode"], row["worker_events"])
            if row["oracle"] != assess_recovery(row):
                raise ValueError("stored assessment disagrees with raw observations")
        elif row["status"] != "infrastructure_error" or row.get("oracle") is not None:
            raise ValueError("unknown run status")
    arms = {}
    for arm in ARMS:
        rows = [row for row in records if row["arm"] == arm]
        def count(key: str) -> int:
            return sum(bool((row.get("oracle") or {}).get(key)) for row in rows)
        arms[arm] = {
            "cases": len(rows), "termination_cases": sum(row["cut"] != "none" for row in rows),
            "verified_terminations": sum(row["status"] == "complete" and row["cut"] != "none" for row in rows),
            "coherent_states": count("state_coherent"),
            "active_approval_cases": sum(expected_state(row)["approved_sha256"] is not None for row in rows),
            "valid_deliveries": count("valid_delivery"), "invalid_deliveries": count("invalid_delivery"),
            "update_gap_cases": sum(row["transition"] == "update" and row["cut"] == "after_stage" for row in rows),
            "invalid_gap_deliveries": sum(bool((row.get("oracle") or {}).get("invalid_delivery"))
                                          for row in rows if row["transition"] == "update" and row["cut"] == "after_stage"),
            "denials": sum(row["status"] == "complete" and (row.get("recovery") or {}).get("status") == "blocked" for row in rows),
            "mismatch_denials": sum(row["status"] == "complete" and (row.get("recovery") or {}).get("reason") == "recovered_digest_mismatch" for row in rows),
            "committed_revocations": sum(expected_state(row)["approved_sha256"] is None for row in rows),
            "revocation_denials": count("revocation_denied"),
            "acknowledged_cases": sum(row["cut"] == "after_ack" for row in rows),
            "acknowledged_recovered": count("acknowledged_recovered"),
            "committed_without_ack_cases": sum(row["cut"] == "after_commit" for row in rows),
            "committed_without_ack_recovered": count("committed_without_ack_recovered"),
            "controls": sum(row["transition"] == "none" for row in rows),
            "valid_control_deliveries": sum(bool((row.get("oracle") or {}).get("valid_delivery")) for row in rows if row["transition"] == "none"),
            "infrastructure_errors": sum(row["status"] == "infrastructure_error" for row in rows),
        }
    unchecked, verified, atomic = (arms[arm] for arm in ARMS)
    return {"arms": arms, "criteria": {
        "unchecked_two_invalid_gap_deliveries": unchecked["invalid_gap_deliveries"] == unchecked["invalid_deliveries"] == 2,
        "verified_zero_invalid_and_two_mismatch_denials": verified["invalid_deliveries"] == 0 and verified["mismatch_denials"] == 2,
        "atomic_zero_invalid_and_fifteen_valid_deliveries": atomic["invalid_deliveries"] == 0 and atomic["valid_deliveries"] == 15,
        "split_seventeen_coherent_states": unchecked["coherent_states"] == verified["coherent_states"] == 17,
        "atomic_nineteen_coherent_states": atomic["coherent_states"] == 19,
        "split_thirteen_valid_deliveries": unchecked["valid_deliveries"] == verified["valid_deliveries"] == 13,
        "all_committed_revocations_denied": all(a["committed_revocations"] == a["revocation_denials"] == 4 for a in arms.values()),
        "all_acknowledged_publications_recovered": all(a["acknowledged_cases"] == a["acknowledged_recovered"] == 4 for a in arms.values()),
        "unacknowledged_commits_also_recovered": all(a["committed_without_ack_cases"] == a["committed_without_ack_recovered"] == 4 for a in arms.values()),
        "all_three_controls_delivered": all(a["controls"] == a["valid_control_deliveries"] == 3 for a in arms.values()),
        "all_declared_cuts_reached_without_infrastructure_error": all(a["termination_cases"] == a["verified_terminations"] == 16 and a["infrastructure_errors"] == 0 for a in arms.values()),
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
    run_id = started.strftime("%Y-%m-%dT%H-%M-%S-%fZ-recovery-v1")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    raw = args.output_dir / (run_id + ".jsonl")
    sources = ["src/publication_store.py", "experiments/recovery_worker.py", "experiments/run_recovery_comparison.py",
               "experiments/verify_recovery_results.py", "tests/test_publication_store.py", "docs/RECOVERY_PROTOCOL.md"]
    metadata = {"started_at_utc": started.isoformat(), "finished_at_utc": datetime.now(timezone.utc).isoformat(),
                "python_version": platform.python_version(), "sqlite_version": sqlite3.sqlite_version,
                "platform": platform.platform(), "base_commit": args.base_commit, "freeze_commit": args.freeze_commit,
                "dataset": str(args.dataset), "dataset_sha256": sha(args.dataset.read_bytes()),
                "source_sha256": {p: sha((ROOT / p).read_bytes()) for p in sources},
                "command": [sys.executable, *sys.argv], "results_file": raw.name, "summary": summary,
                "interpretation_limit": "Nineteen developer-visible process-exit schedules per arm; no host crash, power loss, mid-syscall cut, distributed coordination, or live-agent claim."}
    with raw.open("x", encoding="utf-8") as handle:
        for row in records:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    with (args.output_dir / (run_id + "-summary.json")).open("x", encoding="utf-8") as handle:
        json.dump(metadata, handle, indent=2, ensure_ascii=False)
        handle.write("\n")
    print(json.dumps(summary, indent=2))
    print(f"Saved {run_id}")
    return int(any(a["infrastructure_errors"] for a in summary["arms"].values()))


if __name__ == "__main__":
    raise SystemExit(main())
