# Experiments

Store versioned synthetic test cases, raw outputs, and analysis here.

## Current dataset

- `cases/v1/actions.jsonl` — version 1 of the synthetic action dataset.
- **Cases:** 20 total: 8 legitimate, 8 risky, and 4 invalid-input cases.
- Each JSONL line is a separate case with a stable `case_id`, `dataset_version`, `class`, `category`, `input`, `expected_decision`, and `rationale`.
- The `input` field is the synthetic JSON record intended for the monitor. The other fields are dataset metadata and should not be passed to the monitor as part of the action.

## Suggested next files

- `results/YYYY-MM-DD-run-01.jsonl` — actual decisions and reasons from one run.
- `analysis.md` — metric calculations, summary tables, mismatches, and error analysis.

Dataset v1 has been created but **has not yet been run as a complete dataset**. Do not treat expected labels as observed results. No formal experiment results are recorded yet.

Use only synthetic records. Do not store secrets, personal information, or data copied from real users. If a case or expected label changes, document why and create a new version instead of silently editing a measured dataset.
