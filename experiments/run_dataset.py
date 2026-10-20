"""Run the versioned synthetic CodeGuardian dataset and report metrics.

This evaluates only the deterministic checker against synthetic proposals. It does
not measure real-world security or connect to an AI coding agent.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATASET = ROOT / "experiments" / "cases" / "v1" / "actions.jsonl"
MONITOR = ROOT / "src" / "codeguardian.py"
RESULTS_DIR = ROOT / "experiments" / "results"


def load_cases(path: Path) -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                case = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid dataset JSON on line {line_number}: {exc}") from exc
            required = {"case_id", "class", "input", "expected_decision"}
            missing = required - case.keys()
            if missing:
                raise ValueError(
                    f"Dataset line {line_number} is missing fields: {', '.join(sorted(missing))}"
                )
            cases.append(case)
    if not cases:
        raise ValueError("Dataset contains no cases.")
    return cases


def evaluate_case(case: dict[str, Any]) -> dict[str, Any]:
    payload = json.dumps(case["input"], ensure_ascii=False) + "\n"
    try:
        completed = subprocess.run(
            [sys.executable, str(MONITOR)],
            input=payload,
            text=True,
            capture_output=True,
            check=False,
            timeout=5,
            cwd=ROOT,
        )
    except subprocess.TimeoutExpired:
        observed = None
        error = "monitor_timed_out"
    else:
        error = None
        if completed.returncode != 0:
            error = f"monitor_exit_code_{completed.returncode}: {completed.stderr.strip()}"
            observed = None
        else:
            try:
                output_lines = [line for line in completed.stdout.splitlines() if line.strip()]
                if len(output_lines) != 1:
                    raise ValueError(f"expected 1 output line, received {len(output_lines)}")
                observed = json.loads(output_lines[0])
            except (json.JSONDecodeError, ValueError) as exc:
                error = f"invalid_monitor_output: {exc}"
                observed = None

    observed_decision = observed.get("decision") if isinstance(observed, dict) else None
    result = {
        "case_id": case["case_id"],
        "dataset_version": case.get("dataset_version", "unspecified"),
        "class": case["class"],
        "category": case.get("category"),
        "expected_decision": case["expected_decision"],
        "observed_decision": observed_decision,
        "observed_reason": observed.get("reason") if isinstance(observed, dict) else None,
        "match": observed_decision == case["expected_decision"],
        "monitor_output": observed,
    }
    if error:
        result["error"] = error
        result["match"] = False
    return result


def rate(numerator: int, denominator: int) -> float | None:
    return round(numerator / denominator, 4) if denominator else None


def summarize(results: list[dict[str, Any]]) -> dict[str, Any]:
    def group(name: str) -> list[dict[str, Any]]:
        return [result for result in results if result["class"] == name]

    legitimate = group("legitimate")
    risky = group("risky")
    invalid = group("invalid_input")
    errors = [result for result in results if result.get("error")]

    return {
        "total_cases": len(results),
        "matched_cases": sum(result["match"] for result in results),
        "mismatched_cases": sum(not result["match"] for result in results),
        "monitor_errors": len(errors),
        "legitimate_cases": len(legitimate),
        "legitimate_allowed": sum(r["observed_decision"] == "allow" for r in legitimate),
        "false_positive_rate": rate(
            sum(r["observed_decision"] == "block" for r in legitimate), len(legitimate)
        ),
        "legitimate_allow_rate": rate(
            sum(r["observed_decision"] == "allow" for r in legitimate), len(legitimate)
        ),
        "risky_cases": len(risky),
        "risky_cases_blocked": sum(r["observed_decision"] == "block" for r in risky),
        "risky_action_block_rate": rate(
            sum(r["observed_decision"] == "block" for r in risky), len(risky)
        ),
        "invalid_input_cases": len(invalid),
        "invalid_input_cases_blocked": sum(
            r["observed_decision"] == "block" for r in invalid
        ),
        "invalid_input_block_rate": rate(
            sum(r["observed_decision"] == "block" for r in invalid), len(invalid)
        ),
        "mismatches": [
            {
                "case_id": r["case_id"],
                "expected": r["expected_decision"],
                "observed": r["observed_decision"],
                "error": r.get("error"),
            }
            for r in results
            if not r["match"]
        ],
        "interpretation_limit": (
            "Synthetic dataset results describe this prototype on these cases only; "
            "they do not establish real-world risk reduction or security."
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Evaluate CodeGuardian against a versioned synthetic JSONL dataset."
    )
    parser.add_argument(
        "--dataset",
        type=Path,
        default=DEFAULT_DATASET,
        help="Path to a dataset JSONL file (default: experiments/cases/v1/actions.jsonl).",
    )
    args = parser.parse_args()
    dataset_path = args.dataset if args.dataset.is_absolute() else ROOT / args.dataset

    try:
        cases = load_cases(dataset_path)
    except (OSError, ValueError) as exc:
        print(f"Dataset error: {exc}", file=sys.stderr)
        return 2

    version = str(cases[0].get("dataset_version", dataset_path.parent.name))
    version_tag = "".join(char for char in version if char.isalnum() or char in "-_")
    if not version_tag:
        version_tag = "custom"

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    run_id = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%SZ")
    raw_path = RESULTS_DIR / f"{run_id}-{version_tag}.jsonl"
    summary_path = RESULTS_DIR / f"{run_id}-{version_tag}-summary.json"

    results = [evaluate_case(case) for case in cases]
    summary = {
        "run_id_utc": run_id,
        "dataset": str(dataset_path.relative_to(ROOT)) if dataset_path.is_relative_to(ROOT) else str(dataset_path),
        "monitor": "src/codeguardian.py",
        "results_file": raw_path.name,
        "summary": summarize(results),
    }

    with raw_path.open("w", encoding="utf-8") as handle:
        for result in results:
            handle.write(json.dumps(result, ensure_ascii=False) + "\n")
    with summary_path.open("w", encoding="utf-8") as handle:
        json.dump(summary, handle, ensure_ascii=False, indent=2)
        handle.write("\n")

    metrics = summary["summary"]
    print(f"Dataset cases: {metrics['total_cases']}")
    print(f"Matched expected decisions: {metrics['matched_cases']}/{metrics['total_cases']}")
    print(f"Mismatches: {metrics['mismatched_cases']}")
    print(f"Monitor errors: {metrics['monitor_errors']}")
    print(f"Risky-action block rate: {metrics['risky_action_block_rate']}")
    print(f"False-positive rate: {metrics['false_positive_rate']}")
    print(f"Legitimate allow rate: {metrics['legitimate_allow_rate']}")
    print(f"Invalid-input block rate: {metrics['invalid_input_block_rate']}")
    print(f"Raw results: {raw_path.relative_to(ROOT)}")
    print(f"Summary: {summary_path.relative_to(ROOT)}")
    print("Reminder: these are synthetic prototype results, not real-world security evidence.")
    return 1 if metrics["mismatched_cases"] or metrics["monitor_errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
