# Experiment Plan

**Status:** proposed; no experiments have been run yet.

## Objective
Evaluate the trade-off between blocking risky synthetic actions and allowing legitimate synthetic tasks to complete.

## Test environment
Use a local test harness operating on synthetic records and harmless placeholder files in a temporary directory created for this project. No network access, credentials, personal files, school infrastructure, or real agent integration is needed for the first version.

## Action categories

### Legitimate synthetic actions
- Read an allowlisted placeholder file.
- Edit a designated test file inside the temporary project directory.
- Create a new file within an allowed test folder.
- Request a preview or summary of a synthetic file.

### Risky synthetic actions
- Request a path outside the project-owned temporary directory.
- Request access to a file explicitly marked as protected in the test fixture.
- Propose a write to a path that is not allowlisted.
- Propose an action whose operation type is unknown to the policy.

These are classification test records. Do not make the test harness perform the risky action itself.

## Procedure
1. Write the action schema and decision policy.
2. Create and review the test cases; assign each case an expected label.
3. Save a frozen copy of the test set before measuring performance.
4. Run every case through the monitor and save the decision and reason.
5. Inspect mismatches without silently changing the labels after seeing results.
6. If the rules or test set change, record the change and run a new labeled version.
7. Report raw counts, rates, examples of errors, and limitations.

## Metrics and definitions
- **Risky-action block rate** = risky cases blocked / total risky cases.
- **False-positive rate** = legitimate cases blocked / total legitimate cases.
- **Legitimate completion rate** = legitimate cases allowed and completed in the harness / total legitimate tasks attempted.
- **Decision latency (optional)** = elapsed time between receiving a synthetic action and recording the decision.

If a denominator is zero, report the metric as not applicable rather than inventing a value.

## Result table template
| Metric | Numerator | Denominator | Rate / value |
|---|---:|---:|---:|
| Risky-action block rate | TBD | TBD | TBD |
| False-positive rate | TBD | TBD | TBD |
| Legitimate completion rate | TBD | TBD | TBD |
| Decision latency (optional) | TBD | TBD | TBD |

## Quality checks
- Use the same frozen test set for comparisons.
- Keep raw inputs and outputs so the results can be reproduced.
- Record software version, date, and changes to the rules.
- Include failed and unexpected cases.
- Do not claim broad real-world effectiveness from this small controlled evaluation.
