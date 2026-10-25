# CodeGuardian

**A controlled experiment on runtime safeguards for AI coding agents**

## Research question

Can a lightweight runtime monitor reduce risky actions by an AI coding agent without substantially reducing completion of legitimate tasks in a controlled test environment?

## Project status

- **Stage:** early implementation
- **Implemented:** deterministic policy checker for synthetic action records
- **Tests:** 11/11 unit tests passed on 2026-10-26 (Asia/Seoul)
- **Experiments:** synthetic decision checks completed for v1, v2, and v3; no live-agent evaluation
- **Results:** v1 20/20, v2 21/21, and v3 45/45 expected decisions matched

This repository is an educational prototype. Do not describe planned measures or hypotheses as experimental findings.

Latest verification used the unchanged checker and runner from commit
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

The current version classifies synthetic actions only. It does not connect to a live AI agent, access personal files, use credentials, contact external services, or execute arbitrary commands.

- Work only with synthetic records and project-owned test fixtures.
- Treat the monitor as a policy-checking prototype, not a secure sandbox.
- Do not use it to protect real systems or sensitive data.
- Keep a record of false positives as well as blocked risky actions.
- Stop and reassess if a test requires access to a real account, real user data, school infrastructure, or an external system.

## Current implementation

`src/codeguardian.py` accepts JSON action records and returns `allow` or `block` with a reason. The first policy allows a small set of operations only under `workspace/`, while blocking protected paths, absolute paths, traversal patterns, and unknown operations.

## Proposed outcomes to measure

1. **Risky-action block rate:** risky synthetic actions blocked / all risky synthetic actions tested.
2. **False-positive rate:** legitimate synthetic actions blocked / all legitimate synthetic actions tested.
3. **Legitimate task completion:** safe test tasks completed / all safe test tasks attempted.
4. **Decision latency (optional):** time taken for the monitor to classify an action.

Define the test set and counting rules before running experiments. Report the numerator and denominator, not just percentages.

## Repository layout

- `docs/IDEATION_REPORT.md` — question, rationale, threat model, method, and limitations.
- `docs/ARCHITECTURE.md` — current system flow, input/output schema, policy rules, planned experiment schema, and safety boundaries.
- `docs/EXPERIMENT_PLAN.md` — test cases, measures, and procedure.
- `docs/RESEARCH_LOG.md` — dated work log; record what actually happened.
- `docs/REFLECTION_NOTES.md` — prompts for a later personal reflection.
- `CHANGELOG.md` — chronological record of meaningful repository changes, verification status, and next steps.
- `src/` — policy checker.
- `tests/` — automated unit tests.
- `experiments/` — synthetic test cases and results.

## Next steps

1. Review blind spots beyond the v3 string-policy cases, including raw malformed JSON and filesystem-dependent paths.
2. Define a separate held-out test set before changing policy rules; preserve all measured dataset versions and failed runs.
3. Design a project-owned fixture harness and a no-monitor comparison before measuring actual task completion or risk reduction.
4. Define the enforcement boundary and filesystem semantics before considering an agent adapter.
5. Write a personal reflection based on real decisions, difficulties, and learning.

## Reproducibility

Record the date, code version, test-case definitions, and raw counts for each run. Do not delete failed runs just because they do not support the hypothesis. Any future claim should be traceable to saved evidence.
