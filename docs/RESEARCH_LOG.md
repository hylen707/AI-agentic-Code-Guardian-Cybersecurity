# Research Log

Record dated entries as work happens. Keep failed attempts and changes in direction. Distinguish manual checks, unit tests, and formal experiments.

## 2026-10-21 — Path-normalization regression fix prepared

- **Issue identified:** `PurePosixPath` can collapse an explicit `.` component, so checking only its normalized parts can miss an input such as `workspace/./notes.txt`.
- **Change made:** the checker now inspects the slash-normalized raw path components before creating the `PurePosixPath` object.
- **Regression tests added:** explicit `.` components in both a direct workspace path and a nested workspace path should be blocked.
- **Dataset:** created `experiments/cases/v2/actions.jsonl` with 21 synthetic cases, preserving the 20 baseline scenarios and adding `RISK-009`. Dataset v1 remains unchanged.
- **Runner:** `experiments/run_dataset.py` now accepts `--dataset` so v1 and v2 can be run independently.
- **Verification status:** locally verified by the project author on 2026-10-21: all 11 unit tests passed, and the v2 dataset run matched all 21 expected decisions with 0 mismatches and 0 monitor errors.
- **Next step:** expand the test set and evaluate additional edge cases; keep synthetic test performance separate from claims about real-world security.

## 2026-10-21 — Synthetic dataset v2 and unit-test verification

- **Goal:** verify the path-normalization regression fix and run the expanded, versioned synthetic dataset.
- **Commands reported by the project author:** `python -m unittest discover -s tests -v` and `python experiments/run_dataset.py --dataset experiments/cases/v2/actions.jsonl`.
- **Unit-test outcome:** 11 tests ran with no failures. This includes regression tests for explicit current-directory (`.`) path components in direct and nested workspace paths.
- **Dataset outcome:** 21 cases; 21/21 expected decisions matched; 0 mismatches; 0 monitor errors.
- **Metrics reported:** risky-action block rate 1.0; false-positive rate 0.0; legitimate allow rate 1.0; invalid-input block rate 1.0.
- **Raw output files reported:** `experiments/results/2026-10-20T15-59-51Z-v2.jsonl` and `experiments/results/2026-10-20T15-59-51Z-v2-summary.json`.
- **Interpretation:** the checker matched the manually assigned expected labels for all 21 synthetic cases, and all 11 unit tests passed. The added regression case was included in the v2 run. These results apply only to this small synthetic dataset and do not establish real-world security effectiveness or risk reduction for a live AI coding agent.
- **Next step:** add further independent edge cases and document the monitor's limitations before considering integration with a real agent.

## 2026-10-21 — Synthetic dataset v1 first run

- **Goal:** run all fixed v1 cases through the checker and compare observed decisions with the expected labels.
- **Command:** `python experiments/run_dataset.py`.
- **Evidence supplied by the project author:** 20 cases; 20/20 expected decisions matched; 0 mismatches; 0 monitor errors; risky-action block rate 1.0 (8/8); false-positive rate 0.0 (0/8 legitimate cases blocked); legitimate allow rate 1.0 (8/8); invalid-input block rate 1.0 (4/4).
- **Raw output files reported:** `experiments/results/2026-10-20T15-48-31Z-v1.jsonl` and `experiments/results/2026-10-20T15-48-31Z-v1-summary.json`.
- **Interpretation:** all 20 synthetic cases matched the hand-authored expected labels in this run. Because the dataset is small and manually labelled, this is a baseline check of the prototype on these cases only; it does not establish real-world risk reduction or security.
- **Next step:** inspect path-normalization edge cases and expand testing without rewriting the already-run v1 dataset.

## 2026-10-21 — Synthetic dataset v1 prepared

- **Goal:** define a small, versioned set of safe, risky, and invalid synthetic action records before running a full evaluation.
- **Actions taken:** added `experiments/cases/v1/actions.jsonl` with 20 labelled cases: 8 legitimate, 8 risky, and 4 invalid-input cases. Each case includes an ID, category, input, expected decision, rationale, and dataset version.
- **Outcome/evidence:** dataset file committed to the repository. Expected labels are written down before a full dataset run.
- **Not completed:** the complete dataset has not yet been run through CodeGuardian; no dataset-level metrics or formal experiment results are available yet.
- **Decision and rationale:** keep invalid inputs separate from risky actions so they do not distort the risky-action block rate or false-positive rate.
- **Next step:** run every dataset input through the monitor, save actual decisions separately from expected labels, and inspect mismatches.

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
- **Reason:** this makes the initial experiment easier to isolate and reproduce.
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
