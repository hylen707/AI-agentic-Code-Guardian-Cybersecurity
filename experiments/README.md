# Experiment guide

The repository separates policy conformance, task replay, and deterministic object-continuity studies. Choose the command corresponding to the claim being examined. All filesystem targets are disposable synthetic fixtures; earlier datasets and raw outcomes are preserved.

[Documentation index](../docs/README.md) · [Claims and raw evidence](../docs/EVIDENCE.md) · [Threat model and limits](../docs/LIMITATIONS.md)

## Environment and validation

Use Python 3.10+ and the standard library on Linux. The full suite exercises hardlinks, symlinks, FIFOs, and `pread`; missing capabilities must fail visibly rather than skip an attack case. No model/API credentials, third-party Python packages, or external datasets are needed. Run commands from the repository root after cloning as shown in the [quick start](../README.md#quick-reproduction).

```bash
python -m unittest discover -s tests -v
```

The latest recorded run passed 67 tests. Unit tests include injected failures and regression checks; they are separate from experiment sample counts.

The commands below run the currently checked-out code. `--base-commit "$(git rev-parse HEAD)"` records that checkout's starting revision; the runner also hashes its executed source files. Use a clean checkout for an auditable rerun. Historical starting revisions and commands remain in the linked summaries. Neither `--base-commit` nor `--freeze-commit` checks out, downloads, or verifies a revision: both are caller-supplied provenance labels. The freeze value identifies the historical prospective design, not the current implementation.

## Phase 6: approved content on a stable inode

```bash
python experiments/run_content_comparison.py --dataset experiments/tasks/content-eval-v1/tasks.json --base-commit "$(git rev-parse HEAD)" --freeze-commit ce3fd6d245a2013090f7bd8c6367d08895132723
```

Eight cases run in `identity_only`, `hash_then_reread`, and `verified_buffer` arms. Five schedules change ordinary-file bytes through a hardlink; three controls use unchanged ASCII, Unicode, and empty content. Linux `pread` supports the diagnostic inspection/reread comparator without moving its descriptor offset.

Observed unapproved deliveries are 5/5 → 3/5 → 0/5; approved-version deliveries are 3/8 → 3/8 → 6/8. Both digest arms deny two pre-capture mutations after inspection. The buffer returns three approved but stale values. These are content-delivery measures under a new rule, not protected-resource access counts or live-agent completion. See the [protocol](../docs/CONTENT_PROTOCOL.md), [findings](../docs/CONTENT_FINDINGS.md), and [summary/provenance](results/2026-10-27T12-21-15-144558Z-content-v1-summary.json).

## Phase 5: deterministic pathname replacement

```bash
python experiments/run_race_comparison.py --dataset experiments/tasks/race-eval-v1/tasks.json --base-commit "$(git rev-parse HEAD)" --freeze-commit d0ddc20aac99365adb85bc48ef53539c8028a127
```

Ten cases run in `baseline`, `identity_path`, and `descriptor_bound` arms. The controller fixes replacement timing; there are no concurrent threads or race-win-rate measurements. The [protocol](../docs/RACE_PROTOCOL.md) defines six attack schedules and eight original-object-eligible cases, with overlap. Protected opens are distinct from protected content operations.

The recorded result is 6/6 → 4/6 → 0/6 protected content operations and 2/8 → 2/8 → 8/8 original-object completion. The descriptor arm makes two protected opens for metadata and denies both before content I/O. See [findings](../docs/RACE_FINDINGS.md), [raw records](results/2026-10-26T08-23-21-637204Z-race-v1.jsonl), and [summary/provenance](results/2026-10-26T08-23-21-637204Z-race-v1-summary.json).

## Phase 4: hardlink identity

```bash
python experiments/run_identity_comparison.py --dataset experiments/tasks/identity-eval-v1/tasks.json --base-commit "$(git rev-parse HEAD)" --freeze-commit 8e0910d86636c9cd4264b9c1f3e70da4c7b8b39f
```

Six tasks run in four arms on fixed topology. The identity gate prevents both protected hardlink operations missed by the resolved gate, with 0/3 protected operations and 6/6 safe completions. The [findings](../docs/IDENTITY_FINDINGS.md) retain that result within its fixed-topology scope; Phase 5 tests a different assumption.

## Phase 3: resolved-target approval

```bash
python experiments/run_comparison.py --dataset experiments/tasks/replay-v1/tasks.json --suite-role development --base-commit "$(git rev-parse HEAD)" --freeze-commit 1d9bbe305625f5b7df55a185463908729c48cc03
python experiments/run_comparison.py --dataset experiments/tasks/gate-eval-v1/tasks.json --suite-role supplemental --base-commit "$(git rev-parse HEAD)" --freeze-commit 1d9bbe305625f5b7df55a185463908729c48cc03
```

Report development and supplemental suites separately. Each has eight tasks and three arms. The supplemental protocol was frozen before implementation, but cases were visible during development and are not an independent holdout. [Findings](../docs/GATE_FINDINGS.md) link both raw runs and their unchanged source hashes.

## Phase 2: paired replay

```bash
python experiments/run_replay.py --dataset experiments/tasks/replay-v1/tasks.json --base-commit "$(git rev-parse HEAD)"
```

Eight tasks compare baseline execution with the unchanged string gate. Protected operations fall from four to two, functional completion from 8/8 to 6/8, and safe completion remains 4/8. [Findings](../docs/REPLAY_FINDINGS.md) explain why fewer protected operations did not produce more safe completions.

## Phase 1: policy conformance

```bash
python experiments/run_dataset.py --dataset experiments/cases/v1/actions.jsonl
python experiments/run_dataset.py --dataset experiments/cases/v2/actions.jsonl
python experiments/run_dataset.py --dataset experiments/cases/v3/actions.jsonl
```

| Dataset | Legitimate | Risky | Invalid | Total |
|---|---:|---:|---:|---:|
| v1 | 8 | 8 | 4 | 20 |
| v2 | 8 | 9 | 4 | 21 |
| v3 | 16 | 19 | 10 | 45 |

V2 retains v1 and adds one regression case; v3 retains v2 and adds 24 cases. These overlapping versions are not independent samples. The [v3 design note](cases/v3/README.md) preserves label rationale and limitations. The [verification record](results/2026-10-25T16-05-40Z-verification.json) records 20/20, 21/21, and 45/45 matches with zero mismatches or monitor errors.

Only each case's `input` is passed to the checker. `expected_decision`, class, and rationale remain evaluation metadata. Policy labels describe a conservative string policy; they do not establish actual resource safety.

## Reading and preserving artifacts

Runners write timestamped raw JSONL and summary JSON under `experiments/results/`; filesystem comparisons use unique microsecond timestamps and exclusive creation. `--output-dir` selects a different output directory. Filenames use UTC, while narrative dates use Asia/Seoul. Base commits identify the starting revision; source hashes identify the exact files executed, including newly added code. Freeze commits identify the prospective design.

### Expected output and checks

Filesystem comparison commands print a JSON summary and the saved run identifier; the policy runner prints text metrics and output paths. Open the matching `*-summary.json`, then the raw filename specified by its `results_file` field. Expect the following grids; policy versions and related suites remain separate.

| Run | Expected raw rows | Headline check in `summary` |
|---|---:|---|
| Policy v1 / v2 / v3 | 20 / 21 / 45 | `matched_cases` equals `total_cases`; zero `mismatched_cases` and `monitor_errors` |
| Paired replay | 16 = 8 tasks × 2 arms | `arms.monitored`: 2 risk events, 6 functional and 4 safe completions |
| Resolved development / supplemental | 24 each = 8 tasks × 3 arms | Each `arms.executor_aware`: 0 risk events, 8 functional and 8 safe completions |
| Identity | 24 = 6 tasks × 4 arms | `arms.identity_gate`: 0 risk events, 6 safe completions |
| Replacement | 30 = 10 cases × 3 arms | `arms.descriptor_bound`: 0 protected content operations, 2 protected opens, 8 original completions |
| Content | 24 = 8 cases × 3 arms | `arms.verified_buffer`: 0 unapproved deliveries, 6 approved deliveries, 2 content blocks, 3 approved but stale values |

For filesystem studies, require zero execution/infrastructure errors and inspect every declared criterion as well as controls and legitimate completion. A zero protection-failure count produced by broken execution is not a successful result. Raw IDs must cover each declared case/arm pair exactly once; the [evidence map](../docs/EVIDENCE.md) gives the historical files for comparison.

### Provenance and historical reproduction

For a current-code rerun, compare outcome counts and criteria with the historical summary, then check dataset and source hashes. Timestamps, fixture paths, device/inode numbers, commands, and platform fields can differ; byte-for-byte equality of raw runs is not expected. A changed source hash identifies a difference to explain, not an automatically equivalent experiment. Early policy summaries have less provenance; use their separate [verification record](results/2026-10-25T16-05-40Z-verification.json).

To inspect a historical implementation, use a separate checkout at its implementation revision and verify all source/task hashes against the recorded summary before attributing a rerun to it. A summary's historical `base_commit` may precede files added during that study, so checking out that base alone is insufficient. Frozen protocols and recorded source hashes remain the evidence for what was specified and executed. Append `--output-dir /tmp/codeguardian-reproduction` to a filesystem comparison command to keep its rerun outside the retained evidence directory. The policy runner has no output-directory option and writes to `experiments/results/`; its filenames have second precision, so avoid repeating the same version within one second.

For comparison runners, exit 0 means clean experiment execution, not that every scientific criterion held. Inspect the summary's criteria and raw rows. Per-case infrastructure failures cause a nonzero outcome; setup/schema failures also fail explicitly. The policy runner instead exits nonzero for decision mismatches or monitor errors. Record the runner's actual output rather than assuming a shared exit-code taxonomy.

Keep earlier inputs, protocols, and raw runs unchanged. When a hypothesis or case changes, use a new version. Preserve negative results and error traces. Living findings can add interpretation or follow-up links without changing the original measurements. These artifacts support bounded mechanism claims, not deployed security or live-agent effectiveness.
