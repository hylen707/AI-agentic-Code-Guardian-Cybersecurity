# Experiment Plan

**Status:** synthetic decision checks completed for v1, v2, and v3; baseline-versus-monitored task execution and live-agent evaluation remain planned. Latest verification: 2026-10-26 (Asia/Seoul); see [research log](RESEARCH_LOG.md).

## Objective

Evaluate the trade-off between blocking risky synthetic actions and allowing legitimate synthetic tasks to complete.

The current classification-only phase measures decision agreement and legitimate
allow rate. Actual task completion requires a separate execution harness and
has not been measured.

## Test environment

Use a local test harness operating on synthetic records only. The current CodeGuardian prototype classifies proposed actions and does not execute file operations. No network access, credentials, personal files, school infrastructure, or real agent integration is needed for this first evaluation.

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
