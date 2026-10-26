# Experiment guide

The repository separates policy conformance, task replay, and deterministic object-continuity studies. Choose the command corresponding to the claim being examined. All filesystem targets are disposable synthetic fixtures; earlier datasets and raw outcomes are preserved.

## Environment and validation

Use Python 3.10+ and the standard library. Filesystem studies require hardlink/symlink support as specified by their protocols; the latest descriptor study is evaluated on Linux. Missing capabilities must fail visibly rather than skip an attack case.

```bash
python -m unittest discover -s tests -v
```

The latest recorded run passed 55 tests. Unit tests include injected failures and regression checks; they are separate from experiment sample counts.

## Phase 5: deterministic pathname replacement

```bash
python experiments/run_race_comparison.py --dataset experiments/tasks/race-eval-v1/tasks.json --base-commit 1829252dfc7421511f9d6c4aa1d49a0eb9f57ec0 --freeze-commit d0ddc20aac99365adb85bc48ef53539c8028a127
```

Ten cases run in `baseline`, `identity_path`, and `descriptor_bound` arms. The controller fixes replacement timing; there are no concurrent threads or race-win-rate measurements. The [protocol](../docs/RACE_PROTOCOL.md) defines six attack schedules and eight original-object-eligible cases, with overlap. Protected opens are distinct from protected content operations.

The recorded result is 6/6 → 4/6 → 0/6 protected content operations and 2/8 → 2/8 → 8/8 original-object completion. The descriptor arm makes two protected opens for metadata and denies both before content I/O. See [findings](../docs/RACE_FINDINGS.md), [raw records](results/2026-10-26T08-23-21-637204Z-race-v1.jsonl), and [summary/provenance](results/2026-10-26T08-23-21-637204Z-race-v1-summary.json).

## Phase 4: hardlink identity

```bash
python experiments/run_identity_comparison.py --dataset experiments/tasks/identity-eval-v1/tasks.json --base-commit 174330958da6ec22e85972d5b4cf5f760852878f --freeze-commit 8e0910d86636c9cd4264b9c1f3e70da4c7b8b39f
```

Six tasks run in four arms on fixed topology. The identity gate prevents both protected hardlink operations missed by the resolved gate, with 0/3 protected operations and 6/6 safe completions. The [findings](../docs/IDENTITY_FINDINGS.md) retain that result within its fixed-topology scope; Phase 5 tests a different assumption.

## Phase 3: resolved-target approval

```bash
python experiments/run_comparison.py --dataset experiments/tasks/replay-v1/tasks.json --suite-role development --base-commit a92964c53f2c86bd1fb2403c8225763fa69201bf --freeze-commit 1d9bbe305625f5b7df55a185463908729c48cc03
python experiments/run_comparison.py --dataset experiments/tasks/gate-eval-v1/tasks.json --suite-role supplemental --base-commit a92964c53f2c86bd1fb2403c8225763fa69201bf --freeze-commit 1d9bbe305625f5b7df55a185463908729c48cc03
```

Report development and supplemental suites separately. Each has eight tasks and three arms. The supplemental protocol was frozen before implementation, but cases were visible during development and are not an independent holdout. [Findings](../docs/GATE_FINDINGS.md) link both raw runs and their unchanged source hashes.

## Phase 2: paired replay

```bash
python experiments/run_replay.py --dataset experiments/tasks/replay-v1/tasks.json --base-commit 0ffa15a655c3c2569ff0556945ffd83aac1d9efe
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

For comparison runners, exit 0 means clean experiment execution, not that every scientific criterion held. Inspect the summary's criteria and raw rows. Per-case infrastructure failures cause a nonzero outcome; setup/schema failures also fail explicitly. The policy runner instead exits nonzero for decision mismatches or monitor errors. Record the runner's actual output rather than assuming a shared exit-code taxonomy.

Keep earlier inputs, protocols, and raw runs unchanged. When a hypothesis or case changes, use a new version. Preserve negative results and error traces. Living findings can add interpretation or follow-up links without changing the original measurements. These artifacts support bounded mechanism claims, not deployed security or live-agent effectiveness.
