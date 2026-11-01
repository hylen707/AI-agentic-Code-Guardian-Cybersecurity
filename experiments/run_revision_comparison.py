"""Deterministic approval/publication schedules with a receipt-time oracle."""
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

from src.descriptor_executor import identity
from src.executor_gate import PreparedAction
from src.revision_authority import Approval, RevisionAuthority, VersionedValue
from src.verified_content_reader import VerifiedContentReader

ARMS = ("snapshot_only", "recheck_then_release", "coordinated_release")
VERSION_A = "approved=version-a\n"
VERSION_B = "approved=version-b\n"


def digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def load_cases(path: Path) -> list[dict]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or data.get("schema_version") != "revision-eval-v1":
        raise ValueError("unsupported revision schema")
    cases = data.get("cases")
    if not isinstance(cases, list) or not cases:
        raise ValueError("nonempty cases required")
    valid = {("none", "none"), ("before_capture", "update"), ("before_capture", "revoke"),
             ("after_capture", "update"), ("after_capture", "revoke"), ("after_capture", "aba"),
             ("after_recheck", "update"), ("after_recheck", "revoke")}
    seen = set()
    for case in cases:
        if (not isinstance(case, dict) or set(case) != {"case_id", "fixture", "timing", "transition"}
                or not all(isinstance(v, str) for v in case.values())
                or not case["case_id"] or case["case_id"] in seen
                or case["fixture"] not in {"ascii", "empty"}
                or (case["timing"], case["transition"]) not in valid
                or (case["fixture"] == "empty" and case["transition"] != "none")):
            raise ValueError("invalid or duplicate revision case")
        seen.add(case["case_id"])
    return cases


def assess_journal(journal: list[dict]) -> dict:
    """Use ordered commits and actual receipts, not policy decisions or finality."""
    current = None
    receipts = []
    publications = 0
    for seq, event in enumerate(journal):
        if event.get("seq") != seq:
            raise ValueError("journal sequence must be contiguous")
        kind = event["kind"]
        if kind not in {"initial", "publication", "receipt", "publication_attempt",
                        "publication_deferred", "release_boundary", "snapshot", "captured"}:
            raise ValueError("unknown journal event")
        if kind in {"initial", "publication"}:
            expected_revision = 1 if current is None else current["revision"] + 1
            if (kind == "initial") != (current is None) or event["revision"] != expected_revision:
                raise ValueError("nonmonotonic approval history")
            content = event["approved_content"]
            if event["sha256"] != (None if content is None else digest(content)):
                raise ValueError("published digest does not match declared bytes")
            current = event
            publications += kind == "publication"
        elif kind == "receipt":
            if current is None:
                raise ValueError("receipt without initial authority state")
            if event["sha256"] != digest(event["content"]):
                raise ValueError("receipt digest inconsistent with payload")
            valid = (current["approved_content"] is not None
                     and event["revision"] == current["revision"]
                     and event["content"] == current["approved_content"])
            receipts.append({"seq": seq, "revision": event["revision"],
                             "content": event["content"], "valid_at_receipt": valid,
                             "active_revision": current["revision"], "active_sha256": current["sha256"]})
    if current is None or len(receipts) > 1:
        raise ValueError("one initial state and at most one receipt required")
    late_obsolete = sum(r["valid_at_receipt"] and
                        (r["revision"] != current["revision"] or r["content"] != current["approved_content"])
                        for r in receipts)
    return {"receipts": len(receipts), "valid_receipts": sum(r["valid_at_receipt"] for r in receipts),
            "invalid_receipts": sum(not r["valid_at_receipt"] for r in receipts),
            "valid_then_obsolete": late_obsolete, "committed_publications": publications,
            "final_revision": current["revision"], "final_approved_sha256": current["sha256"],
            "receipt_assessments": receipts}


def run_case(case: dict, arm: str) -> dict:
    if arm not in ARMS:
        raise ValueError("unknown release arm")
    journal = []
    record = {**case, "arm": arm, "status": "pending", "reason": None,
              "journal": journal, "deferred_publications": 0,
              "candidate_revision": None, "candidate_sha256": None,
              "identity_continuity": False, "final_file_sha256": None}

    def event(kind: str, **fields) -> None:
        journal.append({"seq": len(journal), "kind": kind, **fields})

    with tempfile.TemporaryDirectory(prefix="codeguardian-revision-") as directory:
        root = Path(directory)
        target = root / "workspace/document.txt"
        alias = root / "publisher/document.txt"
        protected = root / "workspace/protected/sentinel.txt"
        initial = VERSION_A if case["fixture"] == "ascii" else ""
        transitions = {"none": [], "update": [VERSION_B], "revoke": [None], "aba": [VERSION_B, VERSION_A]}[case["transition"]]
        record["requested_publications"] = len(transitions)
        try:
            protected.parent.mkdir(parents=True)
            protected.write_text("synthetic protected sentinel\n", encoding="utf-8")
            target.write_text(initial, encoding="utf-8")
            alias.parent.mkdir()
            alias.hardlink_to(target)
            with target.open("rb") as oracle_handle:
                original_id = identity(os.fstat(oracle_handle.fileno()))
                record["original_identity"] = original_id

                def on_commit(state: Approval) -> None:
                    content = target.read_text(encoding="utf-8") if state.sha256 is not None else None
                    if content is not None and digest(content) != state.sha256:
                        raise ValueError("publication bytes do not match authority digest")
                    event("publication", revision=state.revision, sha256=state.sha256, approved_content=content)

                authority = RevisionAuthority(digest(initial), on_commit)
                event("initial", revision=1, sha256=digest(initial), approved_content=initial)
                pending = []

                def attempt(index: int, value: str | None) -> bool:
                    event("publication_attempt", request_id=index)

                    def publish_bytes() -> None:
                        if value is not None:
                            alias.write_text(value, encoding="utf-8")
                        if identity(alias.stat()) != original_id or identity(target.stat()) != original_id:
                            raise ValueError("publisher replaced the file identity")

                    done = authority.try_publish(None if value is None else digest(value), publish_bytes)
                    if not done:
                        record["deferred_publications"] += 1
                        event("publication_deferred", request_id=index)
                    return done

                def publish_transition() -> None:
                    for index, value in enumerate(transitions):
                        if not attempt(index, value):
                            pending.extend(list(enumerate(transitions))[index:])
                            break

                def boundary() -> None:
                    event("release_boundary")
                    if case["timing"] == "after_recheck":
                        publish_transition()

                def receive(value: VersionedValue) -> None:
                    # Trusted sink: the append itself is the defined receipt.
                    event("receipt", revision=value.revision, content=value.content, sha256=digest(value.content))

                if case["timing"] == "before_capture":
                    publish_transition()
                state = authority.snapshot()
                event("snapshot", revision=state.revision, sha256=state.sha256)
                if state.sha256 is None:
                    outcome = {"status": "blocked", "reason": "approval_revoked_before_capture"}
                else:
                    reader = VerifiedContentReader(root, {target: state.sha256})
                    captured = reader.read(PreparedAction("read", target))
                    if captured["status"] != "executed":
                        # These fixtures have matching capture bytes; a failure is not a release-policy benefit.
                        raise RuntimeError("unexpected capture denial")
                    value = VersionedValue(state.revision, captured["content"])
                    record.update(candidate_revision=value.revision, candidate_sha256=digest(value.content))
                    event("captured", revision=value.revision, sha256=digest(value.content))
                    if case["timing"] == "after_capture":
                        publish_transition()
                    if arm == "snapshot_only":
                        boundary()
                        receive(value)
                        outcome = {"status": "released", "reason": "snapshot_approval_only"}
                    elif arm == "recheck_then_release":
                        checked = authority.check(value)
                        if checked["status"] == "blocked":
                            outcome = checked
                        else:
                            boundary()
                            receive(value)
                            outcome = {"status": "released", "reason": "separate_final_check"}
                    else:
                        outcome = authority.release(value, receive, after_check=boundary)
                record.update(outcome)
                for index, value in pending:
                    if not attempt(index, value):
                        raise RuntimeError("publication still busy after release")
                final_bytes = oracle_handle.read()
                final_id = identity(os.fstat(oracle_handle.fileno()))
                record.update(final_identity=final_id, final_file_sha256=hashlib.sha256(final_bytes).hexdigest(),
                              identity_continuity=original_id == final_id == identity(target.stat()) == identity(alias.stat()))
                if not record["identity_continuity"]:
                    raise ValueError("file identity changed")
                observed = assess_journal(journal)
                if observed["committed_publications"] != len(transitions):
                    raise ValueError("a requested publication did not commit")
                if (record["status"] == "released") != (observed["receipts"] == 1):
                    raise ValueError("release status does not match actual receipt")
                record["oracle"] = observed
        except (OSError, ValueError, RuntimeError, UnicodeError) as exc:
            record.update(status="infrastructure_error", reason=type(exc).__name__)
            # Keep partial histories and actual receipt effects, including callback failures.
            try:
                record["oracle"] = assess_journal(journal)
            except ValueError:
                record["oracle"] = None
    return record


def summarize(records: list[dict], cases: list[dict]) -> dict:
    expected = {(c["case_id"], arm) for c in cases for arm in ARMS}
    actual = [(r["case_id"], r["arm"]) for r in records]
    if len(actual) != len(expected) or set(actual) != expected:
        raise ValueError("one record per declared revision case and arm required")
    declared = {c["case_id"]: c for c in cases}
    for row in records:
        if any(row[key] != value for key, value in declared[row["case_id"]].items()):
            raise ValueError("record does not match declared case")
        if row.get("oracle") is not None:
            if row["oracle"] != assess_journal(row["journal"]):
                raise ValueError("stored assessment disagrees with receipt journal")
        elif row["status"] != "infrastructure_error":
            raise ValueError("non-error record requires a receipt assessment")
    arms = {}
    for arm in ARMS:
        rows = [r for r in records if r["arm"] == arm]
        def total(key):
            return sum((r.get("oracle") or {}).get(key, 0) for r in rows)
        arms[arm] = {
            "cases": len(rows), "post_capture_transition_cases": sum(r["timing"] in {"after_capture", "after_recheck"} for r in rows),
            "receipts": total("receipts"), "valid_receipts": total("valid_receipts"),
            "invalid_receipts": total("invalid_receipts"), "valid_then_obsolete": total("valid_then_obsolete"),
            "denials": sum(r["status"] == "blocked" for r in rows),
            "controls": sum(r["transition"] == "none" for r in rows),
            "valid_control_receipts": sum((r.get("oracle") or {}).get("valid_receipts", 0) for r in rows if r["transition"] == "none"),
            "early_update_valid_receipts": sum((r.get("oracle") or {}).get("valid_receipts", 0) for r in rows if r["timing"] == "before_capture" and r["transition"] == "update"),
            "deferred_publications": sum(r["deferred_publications"] for r in rows),
            "requested_publications": sum(r["requested_publications"] for r in rows),
            "committed_publications": total("committed_publications"),
            "identity_continuity_cases": sum(r["identity_continuity"] for r in rows),
            "infrastructure_errors": sum(r["status"] == "infrastructure_error" for r in rows),
        }
    return {"arms": arms, "criteria": {
        "snapshot_five_invalid_receipts": arms["snapshot_only"]["invalid_receipts"] == 5,
        "recheck_two_invalid_receipts": arms["recheck_then_release"]["invalid_receipts"] == 2,
        "coordinated_zero_invalid_receipts": arms["coordinated_release"]["invalid_receipts"] == 0,
        "coordinated_five_valid_receipts": arms["coordinated_release"]["valid_receipts"] == 5,
        "coordinated_two_deferred_publications": arms["coordinated_release"]["deferred_publications"] == 2,
        "coordinated_two_valid_then_obsolete_receipts": arms["coordinated_release"]["valid_then_obsolete"] == 2,
        "all_controls_and_early_updates_succeed": all(a["valid_control_receipts"] == 2 and a["early_update_valid_receipts"] == 1 for a in arms.values()),
        "every_requested_publication_commits": all(a["committed_publications"] == a["requested_publications"] for a in arms.values()),
        "stable_identity_and_no_infrastructure_errors": all(a["identity_continuity_cases"] == len(cases) and a["infrastructure_errors"] == 0 for a in arms.values()),
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
    run_id = started.strftime("%Y-%m-%dT%H-%M-%S-%fZ-revision-v1")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    raw = args.output_dir / (run_id + ".jsonl")
    sources = ["src/revision_authority.py", "src/verified_content_reader.py", "src/descriptor_executor.py",
               "src/executor_gate.py", "src/codeguardian.py", "experiments/run_revision_comparison.py",
               "tests/test_revision_authority.py", "docs/REVISION_PROTOCOL.md"]
    metadata = {
        "started_at_utc": started.isoformat(), "finished_at_utc": datetime.now(timezone.utc).isoformat(),
        "python_version": platform.python_version(), "platform": platform.platform(),
        "base_commit": args.base_commit, "freeze_commit": args.freeze_commit,
        "dataset_sha256": hashlib.sha256(args.dataset.read_bytes()).hexdigest(),
        "source_sha256": {p: hashlib.sha256((ROOT / p).read_bytes()).hexdigest() for p in sources},
        "command": [sys.executable, *sys.argv], "results_file": raw.name, "summary": summary,
        "interpretation_limit": "Nine deterministic in-process histories; current means committed approval at trusted receipt, not request-time revocation, perpetual freshness, or live-agent safety.",
    }
    with raw.open("x", encoding="utf-8") as handle:
        for row in records:
            handle.write(json.dumps(row) + "\n")
    with (args.output_dir / (run_id + "-summary.json")).open("x", encoding="utf-8") as handle:
        json.dump(metadata, handle, indent=2)
        handle.write("\n")
    print(json.dumps(summary, indent=2))
    print(f"Saved {run_id}")
    return int(any(a["infrastructure_errors"] for a in summary["arms"].values()))


if __name__ == "__main__":
    raise SystemExit(main())
