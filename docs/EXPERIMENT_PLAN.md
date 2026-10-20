# Experiment Plan

**Status:** synthetic dataset v1 created; full dataset run and formal evaluation are not yet completed.

## Objective

Evaluate the trade-off between blocking risky synthetic actions and allowing legitimate synthetic tasks to complete.

## Test environment

Use a local test harness operating on synthetic records only. The current CodeGuardian prototype classifies proposed actions and does not execute file operations. No network access, credentials, personal files, school infrastructure, or real agent integration is needed for this first evaluation.

## Versioned test set

The initial frozen dataset is `experiments/cases/v1/actions.jsonl`.

- 8 legitimate cases expected to be allowed.
- 8 risky cases expected to be blocked.
- 4 invalid-input cases expected to be blocked; report these separately from the risky-action block rate and false-positive rate.

Each line contains metadata plus an `input` value. Only the `input` value should be sent to the monitor. The expected decision is a pre-defined label, not an observed result. If the dataset changes, create a new version and explain the change.

## Procedure

1. Review dataset v1 and its expected labels before running it.
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
