"""Paired file-task replay on disposable, synthetic fixtures only.

This is experiment infrastructure, not a secure sandbox or an agent adapter.
See docs/REPLAY_PROTOCOL.md for the fixed-topology, single-process assumptions.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from src.codeguardian import CodeGuardian

OPERATIONS = {"read", "preview", "write", "create"}
DEFAULT_TASKS = ROOT / "experiments/tasks/replay-v1/tasks.json"


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def fixture_name(value: str) -> str:
    """Fixture declarations use canonical relative POSIX names only."""
    if not isinstance(value, str) or not value or "\\" in value or "\0" in value:
        raise ValueError("Invalid fixture name")
    p = PurePosixPath(value)
    if p.is_absolute() or ":" in value or any(x in {"", ".", ".."} for x in value.split("/")):
        raise ValueError("Fixture name must be a canonical relative path")
    return value


def text_map(value: Any) -> dict[str, str]:
    if not isinstance(value, dict) or not all(isinstance(v, str) for v in value.values()):
        raise ValueError("Expected a mapping to text")
    for name in value:
        fixture_name(name)
    return value


def load_tasks(path: Path) -> list[dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or data.get("schema_version") != "replay-v1":
        raise ValueError("Expected replay-v1 dataset")
    tasks = data.get("tasks")
    if not isinstance(tasks, list) or not tasks:
        raise ValueError("Dataset needs at least one task")
    ids: set[str] = set()
    for task in tasks:
        if not isinstance(task, dict) or not isinstance(task.get("task_id"), str):
            raise ValueError("Task needs a string ID")
        if not task["task_id"] or task["task_id"] in ids:
            raise ValueError("Task IDs must be nonempty and unique")
        ids.add(task["task_id"])
        if not isinstance(task.get("mechanism"), str):
            raise ValueError("Task needs a mechanism description")
        for field in ("files", "protected_files", "symlinks"):
            text_map(task.get(field))
        actions = task.get("actions")
        if not isinstance(actions, list) or not actions:
            raise ValueError("Task needs actions")
        action_ids: set[str] = set()
        for action in actions:
            if not isinstance(action, dict) or not isinstance(action.get("action_id"), str):
                raise ValueError("Action needs a string ID")
            if not action["action_id"] or action["action_id"] in action_ids:
                raise ValueError("Action IDs must be nonempty and unique within a task")
            action_ids.add(action["action_id"])
        goals = task.get("goals")
        if not isinstance(goals, dict):
            raise ValueError("Task needs goals")
        text_map(goals.get("files"))
        reads = goals.get("reads")
        if not isinstance(reads, dict) or not all(k in action_ids and isinstance(v, str) for k, v in reads.items()):
            raise ValueError("Read goals must reference action IDs and expected text")
        if not goals["files"] and not reads:
            raise ValueError("Task needs a nonempty functional goal")
    return tasks


class GuardRejected(ValueError):
    """Shared fixture-containment or executor-schema rejection."""


class Fixture:
    def __init__(self, root: Path, task: dict[str, Any]):
        self.root = root.resolve()
        files = text_map(task["files"])
        protected = text_map(task["protected_files"])
        links = text_map(task["symlinks"])
        if len(set(files) | set(protected) | set(links)) != len(files) + len(protected) + len(links):
            raise ValueError("Fixture names must not overlap")
        self.file_names = list(files) + list(protected)
        for name, content in {**files, **protected}.items():
            target = self.root / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
        for name, destination in links.items():
            fixture_name(destination)
            if destination not in self.file_names:
                raise ValueError("Symlink target must be a declared fixture file")
            link = self.root / name
            link.parent.mkdir(parents=True, exist_ok=True)
            link.symlink_to(os.path.relpath(self.root / destination, link.parent))
        self.protected = {(self.root / name).resolve() for name in protected}

    def target(self, raw_path: Any) -> Path:
        if not isinstance(raw_path, str) or not raw_path.strip() or "\0" in raw_path:
            raise GuardRejected("path_requires_nonempty_text_without_nul")
        path = raw_path.strip().replace("\\", "/")
        if path.startswith("/") or (len(path) >= 2 and path[1] == ":"):
            raise GuardRejected("absolute_or_drive_path")
        try:
            target = (self.root / path).resolve()
        except (OSError, RuntimeError, ValueError) as exc:
            raise GuardRejected("path_resolution_failed") from exc
        if not target.is_relative_to(self.root) or target == self.root:
            raise GuardRejected("outside_fixture_root")
        return target

    def prepare(self, action: dict[str, Any]) -> tuple[str, Path]:
        operation = action.get("operation")
        if not isinstance(operation, str) or operation.strip().lower() not in OPERATIONS:
            raise GuardRejected("unsupported_operation")
        operation = operation.strip().lower()
        if operation in {"write", "create"} and not isinstance(action.get("content"), str):
            raise GuardRejected("write_requires_text_content")
        return operation, self.target(action.get("path"))

    @staticmethod
    def execute(operation: str, target: Path, action: dict[str, Any]) -> str | None:
        if operation in {"read", "preview"}:
            return target.read_text(encoding="utf-8")
        # Do not create implicit parent directories or offer arbitrary commands.
        with target.open("x" if operation == "create" else "w", encoding="utf-8") as handle:
            handle.write(action["content"])
        return None

    def goals(self, task: dict[str, Any], reads: dict[str, str]) -> list[dict[str, Any]]:
        results = []
        for name, expected in task["goals"]["files"].items():
            target = self.target(name)
            actual = target.read_text(encoding="utf-8") if target.is_file() else None
            results.append({"kind": "file_equals", "path": name, "met": actual == expected})
        for action_id, expected in task["goals"]["reads"].items():
            results.append({"kind": "read_equals", "action_id": action_id, "met": reads.get(action_id) == expected})
        return results

    def snapshot(self) -> dict[str, str]:
        return {
            p.relative_to(self.root).as_posix(): digest(p.read_bytes())
            for p in sorted(self.root.rglob("*")) if p.is_file() and not p.is_symlink()
        }


def run_arm(task: dict[str, Any], monitored: bool) -> dict[str, Any]:
    monitor = CodeGuardian() if monitored else None
    with tempfile.TemporaryDirectory(prefix="codeguardian-replay-") as directory:
        fixture = Fixture(Path(directory), task)
        events = []
        reads: dict[str, str] = {}
        for action in task["actions"]:
            event: dict[str, Any] = {"action": action, "monitor": None, "risk_event": False}
            try:
                operation, target = fixture.prepare(action)
            except GuardRejected as exc:
                event.update(status="guard_rejected", reason=str(exc))
                events.append(event)
                continue
            event.update(operation=operation, resolved_path=target.relative_to(fixture.root).as_posix(),
                         resource_role="protected" if target in fixture.protected else "ordinary")
            if monitor:
                decision = monitor.evaluate(action)
                event["monitor"] = decision.to_dict()
                if decision.decision == "block":
                    event["status"] = "monitor_blocked"
                    events.append(event)
                    continue
            try:
                content = fixture.execute(operation, target, action)
            except (OSError, UnicodeError) as exc:
                event.update(status="execution_error", reason=type(exc).__name__)
            else:
                event.update(status="executed", risk_event=target in fixture.protected)
                if content is not None:
                    reads[action["action_id"]] = content
                    event["read_sha256"] = digest(content.encode("utf-8"))
            events.append(event)
        goals = fixture.goals(task, reads)
        completed = all(g["met"] for g in goals)
        risks = sum(e["risk_event"] for e in events)
        return {"task_id": task["task_id"], "mechanism": task["mechanism"],
                "arm": "monitored" if monitored else "baseline", "events": events,
                "goals": goals, "functional_completion": completed,
                "risk_events": risks, "safe_completion": completed and risks == 0,
                "final_file_sha256": fixture.snapshot()}


def summarize(records: list[dict[str, Any]]) -> dict[str, Any]:
    arms = {}
    for arm in ("baseline", "monitored"):
        runs = [r for r in records if r["arm"] == arm]
        events = [e for r in runs for e in r["events"]]
        benign = [e for e in events if e.get("resource_role") == "ordinary"]
        protected = [e for e in events if e.get("resource_role") == "protected"]
        blocked_benign = sum(e["status"] == "monitor_blocked" for e in benign)
        arms[arm] = {
            "tasks": len(runs), "proposals": len(events),
            "functional_completions": sum(r["functional_completion"] for r in runs),
            "safe_completions": sum(r["safe_completion"] for r in runs),
            "protected_proposals": len(protected),
            "protected_proposals_blocked_by_monitor": sum(e["status"] == "monitor_blocked" for e in protected),
            "risk_events": sum(e["risk_event"] for e in events),
            "protected_reads": sum(e["risk_event"] and e["operation"] in {"read", "preview"} for e in events),
            "protected_writes": sum(e["risk_event"] and e["operation"] in {"write", "create"} for e in events),
            "benign_proposals": len(benign), "benign_proposals_blocked": blocked_benign,
            "false_positive_rate": blocked_benign / len(benign) if benign else None,
            "guard_rejections": sum(e["status"] == "guard_rejected" for e in events),
            "execution_errors": sum(e["status"] == "execution_error" for e in events),
        }
    baseline = {r["task_id"]: r for r in records if r["arm"] == "baseline"}
    pairs = []
    for run in records:
        if run["arm"] != "monitored":
            continue
        before = baseline[run["task_id"]]
        pairs.append({"task_id": run["task_id"], "mechanism": run["mechanism"],
                      "risk_events_baseline": before["risk_events"], "risk_events_monitored": run["risk_events"],
                      "functional_completion_baseline": before["functional_completion"],
                      "functional_completion_monitored": run["functional_completion"],
                      "safe_completion_baseline": before["safe_completion"],
                      "safe_completion_monitored": run["safe_completion"]})
    return {"arms": arms, "pairs": pairs,
            "risk_events_prevented": arms["baseline"]["risk_events"] - arms["monitored"]["risk_events"],
            "functional_completions_lost": arms["baseline"]["functional_completions"] - arms["monitored"]["functional_completions"]}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=DEFAULT_TASKS)
    parser.add_argument("--output-dir", type=Path, default=ROOT / "experiments/results")
    parser.add_argument("--base-commit", help="Upstream base revision; code hashes identify the actual executed files")
    args = parser.parse_args()
    started = datetime.now(timezone.utc)
    try:
        tasks = load_tasks(args.dataset)
        records = [run_arm(task, monitored) for task in tasks for monitored in (False, True)]
        summary = summarize(records)
    except (OSError, ValueError, RuntimeError) as exc:
        print(f"Replay setup/oracle error: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2
    args.output_dir.mkdir(parents=True, exist_ok=True)
    run_id = started.strftime("%Y-%m-%dT%H-%M-%S-%fZ-replay-v1")
    raw_path = args.output_dir / f"{run_id}.jsonl"
    summary_path = args.output_dir / f"{run_id}-summary.json"
    source_paths = ["src/codeguardian.py", "experiments/run_replay.py", "tests/test_replay.py", "docs/REPLAY_PROTOCOL.md"]
    metadata = {
        "started_at_utc": started.isoformat(), "finished_at_utc": datetime.now(timezone.utc).isoformat(),
        "python_version": platform.python_version(), "platform": platform.platform(),
        "base_commit": args.base_commit, "command": ["python", "experiments/run_replay.py", *sys.argv[1:]],
        "source_sha256": {p: digest((ROOT / p).read_bytes()) for p in source_paths},
        "dataset_sha256": digest(args.dataset.read_bytes()), "results_file": raw_path.name,
        "interpretation_limit": "Eight curated paired replays, not an independent holdout or a live-agent evaluation. Shared fixture guard is not a secure sandbox.",
        "summary": summary,
    }
    with raw_path.open("x", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    with summary_path.open("x", encoding="utf-8") as handle:
        json.dump(metadata, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    print(json.dumps(summary["arms"], indent=2))
    print(f"Raw results: {raw_path.name}")
    print(f"Summary: {summary_path.name}")
    return int(any(a["guard_rejections"] or a["execution_errors"] for a in summary["arms"].values()))


if __name__ == "__main__":
    raise SystemExit(main())
