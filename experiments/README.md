# Experiments

Store versioned synthetic test cases, raw outputs, and analysis here.

## Three-arm gate comparison

The original baseline/string-gate runs are reused unchanged; the added arm
approves a prepared resolved target and executes that exact request. See
[GATE_PROTOCOL](../docs/GATE_PROTOCOL.md) and [GATE_FINDINGS](../docs/GATE_FINDINGS.md).

```bash
python experiments/run_comparison.py --dataset experiments/tasks/replay-v1/tasks.json --suite-role development --base-commit a92964c53f2c86bd1fb2403c8225763fa69201bf --freeze-commit 1d9bbe305625f5b7df55a185463908729c48cc03
python experiments/run_comparison.py --dataset experiments/tasks/gate-eval-v1/tasks.json --suite-role supplemental --base-commit a92964c53f2c86bd1fb2403c8225763fa69201bf --freeze-commit 1d9bbe305625f5b7df55a185463908729c48cc03
```

Report development and supplemental outcomes separately. The latter was frozen
before implementation but was visible to the developer; it is not a blind
holdout. Summary JSON contains per-arm counts, matched task outcomes, criteria,
source/dataset hashes, and provenance. Exit 0 denotes clean experiment execution,
not necessarily successful policy criteria; inspect `summary.criteria`.
Exit 1 means guard/execution problems, and exit 2 a setup/oracle problem.
Results use unique timestamped filenames and preserve earlier runs.

## Paired file-task replay

The next phase executes eight fixed tasks with and without the monitor on fresh,
disposable synthetic fixtures. See the [protocol](../docs/REPLAY_PROTOCOL.md),
[task definitions](tasks/replay-v1/tasks.json), and [findings](../docs/REPLAY_FINDINGS.md).

```bash
python experiments/run_replay.py --dataset experiments/tasks/replay-v1/tasks.json --base-commit 0ffa15a655c3c2569ff0556945ffd83aac1d9efe
```

Use Python 3.10+ on a filesystem with symlink support. Fixture setup failures
are explicit; alias cases are not silently skipped. The optional `--base-commit`
records the starting revision; saved hashes identify the exact executed files.
`--output-dir` selects a result directory (default `experiments/results`).

The runner writes unique microsecond-timestamped raw JSONL and summary JSON
without overwriting earlier runs. Each raw row is one task/arm outcome with
action traces, resolved targets, file/read goal checks, and final file hashes.
The summary includes paired outcomes and provenance. Exit 0 means the experiment
ran without guard rejections or execution errors, not that all hypotheses held.
Exit 1 records those per-action problems; exit 2 reports a setup/oracle error.

The first run observed protected operations 4 → 2, functional task completion
8/8 → 6/8, and safe completion 4/8 → 4/8. False positives were 2/12 benign
proposals in the monitored arm; two protected alias operations were missed.
These selected fixed replays do not measure live-agent adaptation or provide
independent generalization evidence.

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
