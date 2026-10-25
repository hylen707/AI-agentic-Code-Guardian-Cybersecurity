# Research Log

Record dated entries as work happens. Keep failed attempts and changes in direction. Distinguish manual checks, unit tests, and formal experiments.

## 2026-10-26 — Paired execution reveals protection and utility trade-offs

- **Goal:** deepen the study with actual fixture effects, a no-monitor comparison, and functional goals independent of policy labels.
- **Design before execution:** wrote [REPLAY_PROTOCOL.md](REPLAY_PROTOCOL.md) and eight two-action task definitions with file/read goals. Two controls, two benign alternative path spellings, two direct protected accesses, and two aliases were deliberately chosen as diagnostic development cases. They are not held out.
- **Implementation:** added a separate runner; each arm gets fresh synthetic files and fixed symlinks. Both use the same containment guard and executor; only the monitor gate changes. The oracle uses resolved protected-resource identities, successful operations, and actual file/read observations.
- **Validation:** executed `python -m unittest discover -s tests -v`; all 23 tests passed (11 original + 12 replay tests). New tests cover protected reads/writes, alias misses, benign-path task loss, isolation, root containment, exclusive create, and malformed task definitions.
- **Experiment:** executed `python experiments/run_replay.py --dataset experiments/tasks/replay-v1/tasks.json --base-commit 0ffa15a655c3c2569ff0556945ffd83aac1d9efe` on Python 3.12.14/Linux; exit 0. Eight tasks were each run in baseline and monitored arms (16 proposals per arm). No monitor code or earlier dataset labels were changed.
- **Observed counts:** baseline → monitored protected operations 4/4 → 2/4; functional completion 8/8 → 6/8; safe completion 4/8 → 4/8. Monitored false positives: 2/12 benign proposals. Both arms had 0/16 guard rejections and 0/16 execution errors.
- **Failures retained:** direct protected names were blocked, but aliases still reached protected resources; harmless contained dot/parent spellings prevented required reads. The final report file alone did not satisfy those read-dependent goals.
- **Evidence:** [raw outcomes](../experiments/results/2026-10-25T16-23-07-058859Z-replay-v1.jsonl), [summary and provenance](../experiments/results/2026-10-25T16-23-07-058859Z-replay-v1-summary.json), [console](../experiments/results/2026-10-25T16-23-07-058859Z-replay-v1-console.txt), [validation](../experiments/results/2026-10-25T16-23-07-058859Z-replay-v1-validation.txt), and [analysis](REPLAY_FINDINGS.md). Result timestamps use UTC; this entry uses Asia/Seoul.
- **Interpretation:** enabling the gate prevented two realized protected accesses on these traces but lost two task completions, leaving the joint safe-completion count unchanged. This is a mechanism study on selected tasks, not a general effectiveness estimate. Fixed topology and no adaptive agent are explicit limitations.
- **Decision and next step:** retain this result before improving enforcement. Compare a gate bound to resolved targets against baseline and string-only approval, then evaluate separately frozen tasks. Live-agent adaptation needs another protocol with model/prompt settings, budgets, and repeated trials.

## 2026-10-26 — Reverification and synthetic dataset v3

- **Goal:** reproduce the handed-off results, align current documentation with saved evidence, and broaden string-policy coverage without changing measured datasets or monitor behavior.
- **Source:** checker, runner, and existing tests from upstream commit `7ae79aa5d337ad0ac02431f28b8db2a7f859910e`; these code files are unchanged in this work. No external services or target-file operations were invoked by the monitor.
- **Environment:** Python 3.12.14, Linux; executed in the ChatGPT workspace. This entry uses Asia/Seoul (2026-10-26); commands ran on 2026-10-25 UTC. Exact start times and platform are recorded in the verification record.
- **Unit tests:** actually executed `python -m unittest discover -s tests -v`; all 11 passed with exit code 0. The [unit-test transcript](../experiments/results/2026-10-25T16-05-40Z-unit-tests.txt) preserves the output.
- **Dataset design before the v3 run:** copied all 21 v2 cases, changing only `dataset_version`, and added 24 expected labels against the existing policy. Wrote the dataset and its design note before execution; no labels were revised after observing results. New cases cover prefix boundaries, path spelling/normalization, and invalid JSON value types. V1 and v2 remain byte-for-byte unchanged.
- **Commands actually executed:**

```bash
python experiments/run_dataset.py --dataset experiments/cases/v1/actions.jsonl
python experiments/run_dataset.py --dataset experiments/cases/v2/actions.jsonl
python experiments/run_dataset.py --dataset experiments/cases/v3/actions.jsonl
```

| Dataset | Decision matches | Risky blocked | Legitimate allowed | False positives | Invalid blocked | Monitor errors |
|---|---:|---:|---:|---:|---:|---:|
| v1 | 20/20 | 8/8 | 8/8 | 0/8 | 4/4 | 0 |
| v2 | 21/21 | 9/9 | 8/8 | 0/8 | 4/4 | 0 |
| v3 | 45/45 | 19/19 | 16/16 | 0/16 | 10/10 | 0 |

- **Raw evidence:** all dataset commands exited 0. The [verification record](../experiments/results/2026-10-25T16-05-40Z-verification.json) contains their full console output, source commit, Python version, and SHA-256 hashes of the code, tests, datasets, and v3 design note. Summaries and corresponding raw results are:
  - [v1 summary](../experiments/results/2026-10-25T16-05-40Z-v1-summary.json), [v1 raw](../experiments/results/2026-10-25T16-05-40Z-v1.jsonl).
  - [v2 summary](../experiments/results/2026-10-25T16-05-41Z-v2-summary.json), [v2 raw](../experiments/results/2026-10-25T16-05-41Z-v2.jsonl).
  - [v3 summary](../experiments/results/2026-10-25T16-06-42Z-v3-summary.json), [v3 raw](../experiments/results/2026-10-25T16-06-42Z-v3.jsonl).
- **Problems or surprises:** no test failures or decision mismatches occurred in these runs. Current-status documentation was stale: README said no results, CHANGELOG retained an unconfirmed v2 note, and architecture/experiment-plan text still described completed components or runs as planned. Updated current status while preserving historical research entries and earlier results.
- **Interpretation and limitations:** v3 is a hand-authored development extension, not a held-out evaluation. It contains v2, which contains v1, so do not add their counts as independent observations. A `risky` label means policy-rejected in this dataset, not necessarily malicious on every filesystem. No actual task completion or baseline-versus-monitored execution was measured. Symlink resolution, OS-specific filename constraints, case-insensitive filesystem behavior, raw malformed JSON, and live-agent integration remain outside this dataset. See the [v3 design note](../experiments/cases/v3/README.md).
- **Decision:** retain the checker and runner as-is for this continuation; keep the development changelog separate from this research record. Preserve all failed or unexpected future runs rather than selecting only successful results.
- **Next step:** define held-out inputs and the fixture-harness trust boundary before changing policy rules. A future task-execution experiment needs a controlled no-monitor comparison, fixed task-completion criteria, and project-owned fixtures; it must not be described as implemented yet.

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
