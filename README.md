# CodeGuardian

**A controlled experiment on runtime safeguards for AI coding agents.**

## Research question

Can a lightweight runtime monitor reduce risky actions proposed by an AI coding agent without substantially reducing completion of legitimate tasks in a controlled test environment?

## Project status

- **Stage:** project setup / ideation
- **Implementation:** not yet built
- **Experiments:** not yet run
- **Results:** none yet

This repository currently contains planning documents. Planned measures are not experimental findings; update the status only when work has actually been completed.

## Scope and safety boundaries

The first version will evaluate **synthetic action records** in a local test harness. It will not connect to a live AI agent, access personal files, use credentials, contact external services, or execute arbitrary commands.

- Use a project-owned temporary directory and harmless placeholder files.
- Classify proposed actions before any operation is allowed.
- Default to blocking actions that are not explicitly allowed.
- Record false positives as well as blocks.
- Do not test against school infrastructure, real accounts, or real user data.

## Proposed measures

1. **Risky-action block rate** = risky synthetic actions blocked / risky synthetic actions tested.
2. **False-positive rate** = legitimate synthetic actions blocked / legitimate synthetic actions tested.
3. **Legitimate task completion** = legitimate test tasks completed / legitimate tasks attempted.
4. **Decision latency (optional)** = time taken to classify an action.

Define test cases and counting rules before running experiments. Report raw counts as well as percentages.

## Repository structure

- `docs/IDEATION_REPORT.md` — rationale, research question, threat model, method, limitations.
- `docs/EXPERIMENT_PLAN.md` — test cases, procedure, and metric definitions.
- `docs/RESEARCH_LOG.md` — dated work log.
- `docs/REFLECTION_NOTES.md` — prompts for a later personal reflection.
- `src/` — implementation.
- `experiments/` — synthetic cases and results.

## Next steps

1. Review the scope and threat model.
2. Define a small action schema and freeze the first synthetic test set.
3. Implement a minimal rule-based policy checker.
4. Add deterministic tests for safe and risky synthetic proposals.
5. Run the same fixed test set and save raw outputs.
6. Analyze false positives, blocked actions, and limitations.

## Reproducibility

Record the date, code version, test-case version, and raw counts for every run. Preserve unexpected and failed outcomes. Do not claim general real-world effectiveness from a small synthetic evaluation.

Use commit messages that accurately describe the changes, such as `docs: define experiment plan`, `feat: add synthetic action policy engine`, or `test: add monitor evaluation cases`.
