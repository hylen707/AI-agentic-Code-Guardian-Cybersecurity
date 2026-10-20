# CodeGuardian

**A controlled experiment on runtime safeguards for AI coding agents**

## Research question

Can a lightweight runtime monitor reduce risky actions by an AI coding agent without substantially reducing completion of legitimate tasks in a controlled test environment?

## Project status

**Stage:** early implementation  
**Implemented:** deterministic policy checker for synthetic action records  
**Tests:** unit tests added; run them locally before recording test status  
**Experiments:** formal evaluation not yet run  
**Results:** no experimental findings yet

This repository is an educational prototype. Do not describe planned measures or hypotheses as experimental findings.

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
- `docs/EXPERIMENT_PLAN.md` — test cases, measures, and procedure.
- `docs/RESEARCH_LOG.md` — dated work log; record what actually happened.
- `docs/REFLECTION_NOTES.md` — prompts for a later personal reflection.
- `src/` — policy checker.
- `tests/` — automated unit tests.
- `experiments/` — synthetic test cases and results.

## Next steps

1. Run the unit tests locally and record the actual outcome.
2. Review the test set and expected labels before formal evaluation.
3. Add versioned synthetic cases and a result-export format.
4. Run baseline and monitored tests; save raw results.
5. Analyze trade-offs and document limitations.
6. Write a personal reflection based on real decisions, difficulties, and learning.

## Reproducibility

Record the date, code version, test-case definitions, and raw counts for each run. Do not delete failed runs just because they do not support the hypothesis. Any future claim should be traceable to saved evidence.
