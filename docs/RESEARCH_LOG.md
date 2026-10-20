# Research Log

Record dated entries as work happens. Keep failed attempts and changes in direction. Distinguish manual checks, unit tests, and formal experiments.

## 2026-10-21 — First policy-checker checks

- **Goal:** verify that the initial monitor permits a basic workspace action and blocks selected unsafe path requests.
- **Actions taken:** ran the command-line checker with a safe read request, a request targeting the protected prefix, and a parent-directory traversal path.
- **Outcome/evidence:** the terminal output showed `workspace/notes.txt` returned `allow`; `workspace/protected/secrets.txt` returned `block` with reason `protected_path`; and `../../secrets.txt` returned `block` with reason `path_traversal_or_invalid_path`.
- **Automated tests:** the project author ran `python -m unittest discover -s tests -v`. All 9 unit tests reported `ok`; the terminal output showed `Ran 9 tests in 0.001s`.
- **Interpretation:** the observed examples and unit tests support that the current policy checker behaves as expected for these tested cases. They do not establish overall security or prove that a real AI agent's risky actions are reduced.
- **Problems or surprises:** no failures were shown in this test run. The policy checker still classifies path strings only and does not access a real filesystem.
- **Decision and rationale:** keep the first version isolated and deterministic; do not connect it to a live agent until the test policy and safety boundaries are reviewed.
- **Next step:** review edge cases, create a fixed and versioned synthetic test set, and define raw result recording before a formal experiment.

## 2026-10-20 — Initial repository setup

- **Completed:** created the project repository scaffold and drafted the research question, scope, proposed measures, and experiment plan.
- **Not completed:** no runtime monitor implemented; no test cases executed; no experimental results collected.
- **Decision:** start with synthetic action records and a local test harness rather than connecting to a live AI coding agent.
- **Reason:** this makes the initial experiment easier to isolate, review, and reproduce.
- **Next step:** review the threat model and define the action schema plus the first fixed test set.
- **Evidence/artifacts:** initial documents in `README.md` and `docs/`.

## Entry template

### YYYY-MM-DD — Short title

- **Goal:**
- **Actions taken:**
- **Outcome/evidence:**
- **Problems or surprises:**
- **Decision and rationale:**
- **Next step:**
