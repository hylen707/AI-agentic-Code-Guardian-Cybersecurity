# Experiments

Store versioned synthetic test cases, raw outputs, and analysis here.

## Current datasets

- `cases/v1/actions.jsonl` — baseline synthetic action dataset: 20 cases (8 legitimate, 8 risky, 4 invalid-input).
- `cases/v2/actions.jsonl` — same 20 cases relabelled as dataset version v2 plus one regression case for an explicit `.` path component: 21 cases total (8 legitimate, 9 risky, 4 invalid-input).
- `cases/v3/actions.jsonl` — all 21 v2 cases plus 24 edge cases: 45 total (16 legitimate, 19 risky, 10 invalid-input). See [v3 design and limitations](cases/v3/README.md).
- Each JSONL line has a stable `case_id`, `dataset_version`, `class`, `category`, `input`, `expected_decision`, and `rationale`.
- The `input` field is the synthetic JSON record intended for the monitor. The other fields are dataset metadata and should not be passed to the monitor as part of the action.
- Keep v1 and v2 unchanged as historical datasets. Use v3 for broader string-policy checks. Versions overlap and must not be added as independent samples.

## Run the dataset

From the repository root, run the baseline dataset:

```bash
python experiments/run_dataset.py
```

Run v2 with the additional edge case:

```bash
python experiments/run_dataset.py --dataset experiments/cases/v2/actions.jsonl
```

Run the extended dataset:

```bash
python experiments/run_dataset.py --dataset experiments/cases/v3/actions.jsonl
```

The script invokes `src/codeguardian.py` separately for each case and writes two timestamped files under `experiments/results/`:

- `*-vN.jsonl` — one observed output per case, including expected and observed decisions, match status, and any execution/output error.
- `*-vN-summary.json` — aggregate metrics and any mismatches.

The runner does not change the versioned dataset. It exits with status 1 if any expected decision mismatches or monitor errors occur; otherwise it exits with status 0. The first run creates the results directory automatically.

## Verified run: 2026-10-26 (Asia/Seoul)

The unchanged checker and runner from commit `7ae79aa5d337ad0ac02431f28b8db2a7f859910e`
matched v1 20/20, v2 21/21, and v3 45/45 labels, with zero mismatches or monitor
errors. All 11 existing unit tests passed. Commands, exit codes, environment,
and code/dataset hashes are in the [verification record](results/2026-10-25T16-05-40Z-verification.json).
Its linked summaries contain raw category counts, and the corresponding JSONL
files preserve every observed decision. Result filenames use UTC, so their date
is 2026-10-25. Earlier result files remain unchanged.

## Metrics

- **Risky-action block rate:** risky cases observed as blocked / all risky cases.
- **False-positive rate:** legitimate cases observed as blocked / all legitimate cases.
- **Legitimate allow rate:** legitimate cases observed as allowed / all legitimate cases.
- **Invalid-input block rate:** invalid-input cases observed as blocked / all invalid-input cases.
- **Decision match:** observed decision equals the dataset's expected decision.

Rates are written as decimals from 0 to 1 (for example, `1.0` means 100%). A missing rate is recorded as `null` when its denominator is zero.

The expected labels are hypotheses for this small, hand-authored synthetic dataset, not independently verified ground truth. Results describe only how this prototype behaved on these cases. They do not prove real-world risk reduction, safe filesystem access, or security against a real AI coding agent.

Use only synthetic records. Do not store secrets, personal information, or data copied from real users. If a case or expected label changes, document why and create a new dataset version instead of silently editing a measured dataset.
