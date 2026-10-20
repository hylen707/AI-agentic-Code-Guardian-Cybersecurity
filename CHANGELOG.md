# Changelog and Project Journal

This file records **observable project changes** in reverse chronological order. It complements `docs/RESEARCH_LOG.md`, which is for fuller dated work notes, decisions, questions, and reflections.

Do not record a planned feature as completed, and do not describe a test as passing unless it has actually been run and its output checked.

## [Unreleased]

### 2026-10-21 — Architecture and implementation documentation
- Added `docs/ARCHITECTURE.md` to describe the current decision pipeline, input/output schema, policy rules, planned experiment data format, metrics, and safety boundaries.
- Added this `CHANGELOG.md` as a concise project change journal.
- Clarified in the architecture document which parts exist today and which remain planned.
- **Verification status:** documentation change only; no test execution or experiment is claimed by this entry.

### 2026-10-21 — First CodeGuardian prototype
- Added `src/codeguardian.py`, a deterministic policy checker for synthetic JSON action records.
- Added `tests/test_codeguardian.py` with unit-test cases for representative allowed and blocked inputs.
- Updated `src/README.md` with local run instructions and a command-line example.
- Updated the root `README.md` to describe the prototype, research question, proposed metrics, safety boundaries, and next steps.
- **Verification status:** test cases were written, but their local execution has not yet been recorded. No formal experiment has been run, and there are no experimental findings to report.

### 2026-10-20 — Project planning and repository scaffold
- Established the CodeGuardian project around the research question of whether a lightweight monitor can block risky actions by an AI coding agent while preserving legitimate task completion in a controlled test environment.
- Drafted planning and documentation files, including the ideation report, experiment plan, research log, reflection prompts, and initial repository guidance.
- Set the initial scope to synthetic cases and a controlled prototype rather than a live agent or real system.
- **Verification status:** planning and scaffolding only; no experimental result was established.

## Journal entry template

Copy this template for future entries. Keep entries specific and evidence-based.

```markdown
### YYYY-MM-DD — Short change title
- **Changed:** files, rules, or behavior that actually changed.
- **Reason:** the problem or question motivating the change.
- **Evidence:** commit, test command/output, dataset version, or observation.
- **Outcome:** what was learned; write “not yet evaluated” if no evidence exists.
- **Next:** the next concrete action.
```

## Logging conventions

- Use dates in ISO format: `YYYY-MM-DD`.
- Prefer one entry per meaningful change or work session.
- Include commit links or hashes when useful.
- Keep code changes, test evidence, experiment results, and personal reflections distinct.
- Preserve failed or unexpected outcomes; do not rewrite history to make progress appear smoother.
