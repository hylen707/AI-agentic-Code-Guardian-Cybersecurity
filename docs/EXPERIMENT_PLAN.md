# Experiment Plan

**Status:** policy checks, paired fixture study, and three-arm executor-aware comparison completed. Live-agent evaluation remains planned. Latest work: 2026-10-26 (Asia/Seoul); see [research log](RESEARCH_LOG.md).

## Objective

Evaluate the trade-off between blocking risky synthetic actions and allowing legitimate synthetic tasks to complete.

Phase 1 measures decision agreement and legitimate allow rate. Phase 2 now
measures actual fixture operations, functional goals, and safe completion using
a separate execution harness. Its [pre-run protocol](REPLAY_PROTOCOL.md) defines
the intervention and independent oracle; [findings](REPLAY_FINDINGS.md) record
both failures and benefits. The classification procedure below remains the
phase-1 method and must not be confused with task-execution outcomes.

Phase 3 adds an executor-aware gate and compares three arms under a
[separately frozen protocol](GATE_PROTOCOL.md). Development and supplemental
tasks are reported separately in [GATE_FINDINGS](GATE_FINDINGS.md); the latter
are not a blind or independent holdout. Earlier protocols and failures remain
unchanged. A later study must explicitly change the threat model before
evaluating hardlinks, concurrent mutation, or live-agent behavior.

## Test environment

Use a local test harness operating on synthetic records only. The current CodeGuardian prototype classifies proposed actions and does not execute file operations. No network access, credentials, personal files, school infrastructure, or real agent integration is needed for this first evaluation.

The phase-2 harness additionally uses disposable project-generated files and
static symlinks under a fresh temporary root for each arm. It does not use real
accounts or data. Shared containment failures and execution errors are reported
separately from monitor blocks; there were zero in the first paired run.

## Versioned test set

The initial frozen dataset is `experiments/cases/v1/actions.jsonl`.

- 8 legitimate cases expected to be allowed.
- 8 risky cases expected to be blocked.
- 4 invalid-input cases expected to be blocked; report these separately from the risky-action block rate and false-positive rate.

Each line contains metadata plus an `input` value. Only the `input` value should be sent to the monitor. The expected decision is a pre-defined label, not an observed result. If the dataset changes, create a new version and explain the change.

Subsequent versions preserve earlier scenarios: v2 has 21 cases (8 legitimate,
9 risky, 4 invalid-input); [v3](../experiments/cases/v3/README.md) has 45 cases
(16 legitimate, 19 risky, 10 invalid-input). V3's 24 new cases and their labels
were written before its first run, against the unchanged string policy.
These are overlapping development datasets, not independent holdout samples.

## Procedure

1. Review the selected versioned dataset and its expected labels before running it.
2. Run every case through the monitor and save the observed decision and reason in a separate results file.
3. Compare observed decisions with expected decisions without silently changing labels.
4. Record any mismatch, investigate it, and preserve the original run.
5. If policy rules or test cases change, record the change and run a new version.
6. Report raw counts, rates, examples of errors, and limitations.

## Metrics and definitions

- **Risky-action block rate** = risky cases blocked / total risky cases.
- **False-positive rate** = legitimate cases blocked / total legitimate cases.
- **Legitimate allow rate** = legitimate cases allowed / total legitimate cases. This is a policy-classification proxy, not proof that a real task completed.
- **Invalid-input block rate** = invalid-input cases blocked / total invalid-input cases.
- **Decision latency (optional)** = elapsed time between receiving a synthetic action and recording the decision.

If a denominator is zero, report the metric as not applicable. Save raw numerators and denominators for every rate.

## Result table template

The template below uses v1 denominators. Use the selected dataset's category
counts for a new run; completed results belong in saved summaries and the
research log.

| Metric | Numerator | Denominator | Rate / value |
|---|---:|---:|---:|
| Risky-action block rate | TBD | 8 | TBD |
| False-positive rate | TBD | 8 | TBD |
| Legitimate allow rate | TBD | 8 | TBD |
| Invalid-input block rate | TBD | 4 | TBD |
| Decision latency (optional) | TBD | TBD | TBD |

## Quality checks

- Use the same versioned dataset for repeated comparisons.
- Keep raw inputs and outputs so results can be reproduced.
- Record software version, date, and changes to the rules.
- Include failed and unexpected cases.
- Do not claim broad real-world effectiveness from this small controlled evaluation.
