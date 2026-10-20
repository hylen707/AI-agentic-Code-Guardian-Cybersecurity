# Changelog and Project Journal

This file records observable project changes in reverse chronological order. It complements `docs/RESEARCH_LOG.md`, which keeps fuller dated work notes, decisions, questions, and reflections.

Do not record a planned feature as completed, and do not describe a test as passing unless it has actually been run and its output checked.

## 2026-10-21 — First full synthetic dataset run

- The project author ran `python experiments/run_dataset.py` against dataset v1.
- **Reported output:** 20/20 expected decisions matched; 0 mismatches; 0 monitor errors; risky-action block rate 1.0 (8/8); false-positive rate 0.0 (0/8); legitimate allow rate 1.0 (8/8); invalid-input block rate 1.0 (4/4).
- The author reported generated raw and summary result files under `experiments/results/` with run timestamp `2026-10-20T15-48-31Z`.
- **Interpretation limit:** these results cover only 20 hand-authored synthetic cases and do not demonstrate security or reduced risk for a live AI coding agent.
- **Next:** review edge cases and broaden tests; keep v1 unchanged as the record of this run.

## 2026-10-21 — Synthetic dataset v1 added

- Added `experiments/cases/v1/actions.jsonl` with 20 synthetic cases: 8 legitimate, 8 risky, and 4 invalid-input cases.
- Added stable case IDs, categories, expected decisions, rationales, and a dataset version to each record.
- Updated the experiment guide and plan to define how to run the dataset and report metrics.
- **Verification status:** dataset file created; the complete dataset has not yet been run. Expected decisions are labels, not observed outputs.

## 2026-10-21 — Initial checks and architecture documentation

- **Manual checks (terminal output shared by the project author):** a read request for `workspace/notes.txt` returned `allow`; a read request for `workspace/protected/secrets.txt` returned `block` with reason `protected_path`; and `../../secrets.txt` returned `block` with reason `path_traversal_or_invalid_path`.
- **Automated tests:** the project author ran `python -m unittest discover -s tests -v`; all 9 listed unit tests reported `ok`.
- Added/updated `docs/ARCHITECTURE.md` and recorded the observed checks in `docs/RESEARCH_LOG.md`.
- **Not established:** no formal experiment with a live AI agent has been run. These tests do not prove that risky behavior by an actual AI agent is reduced.

## 2026-10-21 — First CodeGuardian prototype

- Added `src/codeguardian.py`, a deterministic policy checker for synthetic JSON action records.
- Added `tests/test_codeguardian.py` with unit-test cases for representative allowed and blocked inputs.
- Updated `src/README.md` with local run instructions and a command-line example.
- Updated the root `README.md` to describe the prototype, research question, proposed metrics, safety boundaries, and next steps.
- **Verification status at the time of the initial code commit:** test cases had been written, but their local execution had not yet been recorded. The subsequent test run is documented in the newer entry above.

## 2026-10-20 — Project planning and repository scaffold

- Established the CodeGuardian project around the research question of whether a lightweight monitor can block risky actions by an AI coding agent while preserving legitimate task completion in a controlled test environment.
- Drafted planning and documentation files, including the ideation report, experiment plan, research log, reflection prompts, and initial repository guidance.
- Set the initial scope to synthetic cases and a controlled prototype rather than a live agent or real system.
- **Verification status:** planning and scaffolding only; no experimental result was established.

## Journal entry template

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
