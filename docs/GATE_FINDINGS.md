# Phase 3 findings: resolved-target approval in a fixed fixture

**Scope:** historical fixed-topology result. The later [hardlink study](IDENTITY_FINDINGS.md) and [replacement study](RACE_FINDINGS.md) examine assumptions this gate leaves unresolved. Original counts and evidence are retained.

Run date: 2026-10-26 (Asia/Seoul). Figures describe the recorded synthetic
filesystem replays, not general security or live-agent performance.

## Result

In both the development suite and the prospectively frozen supplemental suite,
the executor-aware gate blocked all four protected proposals, recovered both
benign-path task losses, and completed all eight tasks safely. The same code
was used in both runs. Report the suites separately; their mechanisms overlap.

| Suite | Arm | Protected operations / proposals | Functional completion | Safe completion | Benign blocks / proposals |
|---|---|---:|---:|---:|---:|
| replay-v1 development | Baseline | 4/4 | 8/8 | 4/8 | 0/12 |
| replay-v1 development | String gate | 2/4 | 6/8 | 4/8 | 2/12 |
| replay-v1 development | Executor-aware gate | 0/4 | 8/8 | 8/8 | 0/12 |
| gate-eval-v1 supplemental | Baseline | 4/4 | 8/8 | 4/8 | 0/12 |
| gate-eval-v1 supplemental | String gate | 2/4 | 6/8 | 4/8 | 2/12 |
| gate-eval-v1 supplemental | Executor-aware gate | 0/4 | 8/8 | 8/8 | 0/12 |

Each suite has eight matched task triplets, with sixteen proposals per arm.
All arms had zero shared-guard rejections and zero execution errors. The four
protected proposals in each improved arm were blocked by the gate itself.
Both development baseline/string-gate raw records exactly reproduce the prior
paired study, including goal checks and final file hashes.

## Mechanism

`src/executor_gate.py` inspects a prepared operation with a resolved absolute
target and copied write content. Its policy uses configured workspace and
protected-subtree roots. It never reads the fixture's protected-resource labels
or task goals. The oracle independently records actual file effects and goals.
Tests check that configured protection works without oracle labels and covers
new targets not listed in the oracle.

A protected alias now arrives as a protected target and is blocked. A benign
dot/parent spelling arrives as an ordinary target and is allowed. A benign
symlink and the `protected-backup` sibling remain allowed. The comparison
runner executes the same immutable prepared operation inspected by the gate.
A test verifies that later changes to the raw request cannot redirect its path
or write content. This binds approval to a prepared pathname/request, not an
immutable OS file handle; concurrent topology changes remain outside the claim.

The original string monitor and paired runner remain byte-for-byte unchanged.
Their earlier failed outcomes remain saved. The added gate is a distinct
intervention; earlier test labels were not revised.

## Freeze and evidence

The [protocol](GATE_PROTOCOL.md) and [supplemental tasks](../experiments/tasks/gate-eval-v1/tasks.json)
were committed before gate implementation in
[`1d9bbe3`](https://github.com/hylen707/AI-agentic-Code-Guardian-Cybersecurity/commit/1d9bbe305625f5b7df55a185463908729c48cc03).
They remained unchanged afterward. The same developer authored the cases and
implementation and knew their mechanisms, so this is a prospective freeze,
not an independently administered blind holdout.

- Development: [summary/provenance](../experiments/results/2026-10-26T02-23-10-090530Z-gate-v1-development-summary.json), [raw outcomes](../experiments/results/2026-10-26T02-23-10-090530Z-gate-v1-development.jsonl), [console](../experiments/results/2026-10-26T02-23-10-090530Z-gate-v1-development-console.txt).
- Supplemental: [summary/provenance](../experiments/results/2026-10-26T02-23-27-301341Z-gate-v1-supplemental-summary.json), [raw outcomes](../experiments/results/2026-10-26T02-23-27-301341Z-gate-v1-supplemental.jsonl), [console](../experiments/results/2026-10-26T02-23-27-301341Z-gate-v1-supplemental-console.txt).
- Validation: [complete unit-test output](../experiments/results/2026-10-26T02-23-10-090530Z-gate-v1-development-unit-tests.json). All 36 tests passed: 23 existing tests plus 13 gate/comparison tests.

Both comparisons exited 0 and all recorded success criteria held. Source hashes
match between runs; no tuning occurred between them. The base revision is
`a92964c`; hashes identify the newly executed code. Python 3.12.14/Linux was used.
Console commands record the base and freeze revisions.

## Limits and the next question at this stage

These small, related, curated suites must not be pooled as independent samples
or used to infer confidence intervals or complete security. There is no live
agent, adaptive replanning, or coding-task correctness benchmark. The gate
assumes a trusted executor, fixed topology, the recorded OS's symlink semantics,
and no concurrent changes. Hardlink aliases and races are not prevented.

The next study should change one assumption, such as adding hardlink identities
or topology mutation, under a new protocol and retain any failures before
strengthening enforcement. A live-agent study requires constrained tools,
model/prompt settings, budgets, and repeated task-level observations.
