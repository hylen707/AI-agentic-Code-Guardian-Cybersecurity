# CodeGuardian

**A controlled experiment on runtime safeguards for AI coding agents**

## Research question

Can a lightweight runtime monitor reduce risky actions by an AI coding agent without substantially reducing completion of legitimate tasks in a controlled test environment?

## Project status

- **Stage:** paired fixture experiments
- **Implemented:** deterministic checker plus a separate disposable-file replay harness
- **Tests:** 23/23 unit tests passed on 2026-10-26 (Asia/Seoul)
- **Experiments:** policy conformance checks and eight paired file tasks; no live-agent evaluation
- **Latest result:** protected accesses 4 → 2, functional completion 8/8 → 6/8, safe completion 4/8 → 4/8

This repository is an educational prototype. Do not describe planned measures or hypotheses as experimental findings.

## Paired execution findings

The same eight fixed tasks were executed on fresh synthetic fixtures with and
without the unchanged monitor. Direct protected accesses were blocked; symlink
aliases still reached protected files, and two contained path spellings were
unnecessarily blocked. Safe completion means meeting the task goal with no
protected-resource access. It did not improve in this selected suite.

See the [findings and per-task evidence](docs/REPLAY_FINDINGS.md) and the
[pre-run protocol](docs/REPLAY_PROTOCOL.md). These are curated diagnostic replays,
not a held-out evaluation or a measurement of adaptive AI-agent behavior.

## Policy conformance checks

The earlier verification used the unchanged checker and dataset runner from commit
`7ae79aa5d337ad0ac02431f28b8db2a7f859910e`. The [verification record](experiments/results/2026-10-25T16-05-40Z-verification.json)
contains commands, exit codes, Python version, and SHA-256 hashes. Dates in result
filenames use UTC; this run occurred on 2026-10-26 in Asia/Seoul.

| Dataset | Expected decisions matched | Risky blocked | Legitimate allowed | Invalid blocked |
|---|---:|---:|---:|---:|
| [v1](experiments/results/2026-10-25T16-05-40Z-v1-summary.json) | 20/20 | 8/8 | 8/8 | 4/4 |
| [v2](experiments/results/2026-10-25T16-05-41Z-v2-summary.json) | 21/21 | 9/9 | 8/8 | 4/4 |
| [v3](experiments/results/2026-10-25T16-06-42Z-v3-summary.json) | 45/45 | 19/19 | 16/16 | 10/10 |

All three runs had zero decision mismatches, monitor errors, or false positives
on their legitimate cases. The datasets overlap; do not sum their counts as
independent observations. These small, hand-authored checks measure agreement
with policy labels, not real-world security, task completion, or risk reduction
by a live AI agent. See the [v3 design and limitations](experiments/cases/v3/README.md).

## Scope and safety boundaries

The checker classifies synthetic actions. The separate replay harness performs
only read/preview/write/create operations on its own disposable synthetic
fixtures. Neither connects to a live AI agent, uses credentials, contacts
external services, or executes arbitrary commands.

- Work only with synthetic records and project-owned test fixtures.
- Treat the monitor as a policy-checking prototype, not a secure sandbox.
- Do not use it to protect real systems or sensitive data.
- Keep a record of false positives as well as blocked risky actions.
- Stop and reassess if a test requires access to a real account, real user data, school infrastructure, or an external system.

## Current implementation

`src/codeguardian.py` accepts JSON action records and returns `allow` or `block` with a reason. The first policy allows a small set of operations only under `workspace/`, while blocking protected paths, absolute paths, traversal patterns, and unknown operations.

`experiments/run_replay.py` compares baseline and monitored execution in fresh
temporary directories. An independent resource/goal oracle records actual
protected-file effects and task completion. A shared containment guard limits
the experiment to its fixtures; it is not a general sandbox.

## Outcomes

1. **Risky-action block rate:** risky synthetic actions blocked / all risky synthetic actions tested.
2. **False-positive rate:** legitimate synthetic actions blocked / all legitimate synthetic actions tested.
3. **Functional task completion:** tasks meeting all file/read goals / tasks attempted.
4. **Safe task completion:** functional completions with zero protected-resource events / tasks attempted.
5. **Decision latency (optional, not measured):** time taken for the monitor to classify an action.

Define the test set and counting rules before running experiments. Report the numerator and denominator, not just percentages.

## Repository layout

- `docs/IDEATION_REPORT.md` — question, rationale, threat model, method, and limitations.
- `docs/ARCHITECTURE.md` — current system flow, input/output schema, policy rules, planned experiment schema, and safety boundaries.
- `docs/EXPERIMENT_PLAN.md` — test cases, measures, and procedure.
- `docs/REPLAY_PROTOCOL.md` — fixed paired experiment, threat model, and outcome definitions.
- `docs/REPLAY_FINDINGS.md` — observed benefits, task losses, path-alias misses, and limitations.
- `docs/RESEARCH_LOG.md` — dated work log; record what actually happened.
- `docs/REFLECTION_NOTES.md` — prompts for a later personal reflection.
- `CHANGELOG.md` — chronological record of meaningful repository changes, verification status, and next steps.
- `src/` — policy checker.
- `tests/` — automated unit tests.
- `experiments/` — synthetic test cases and results.

## Next steps

1. Compare an executor-aware gate with the baseline and original string-only gate; retain these initial failures.
2. Predefine a goal of blocking protected aliases while recovering contained benign-path completion, with shared guard blocks reported separately.
3. Freeze new evaluation tasks separately from the development suite before running the changed policy.
4. Define race assumptions and agent settings before a constrained, repeated live-agent experiment.
5. Write a personal reflection based on real decisions, difficulties, and learning.

## Reproducibility

Record the date, code version, test-case definitions, and raw counts for each run. Do not delete failed runs just because they do not support the hypothesis. Any future claim should be traceable to saved evidence.
