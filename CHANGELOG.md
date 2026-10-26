# Changelog and Project Journal

This file records observable project changes in reverse chronological order. It complements `docs/RESEARCH_LOG.md`, which keeps fuller dated work notes, decisions, questions, and reflections.

Do not record a planned feature as completed, and do not describe a test as passing unless it has actually been run and its output checked.

## 2026-10-26 — Executor-aware gate and three-arm comparison

- Froze the comparison protocol and eight supplemental tasks in `1d9bbe305625f5b7df55a185463908729c48cc03` before implementation; the same developer designed both, so no blind-holdout claim is made.
- Added a separate gate on prepared canonical targets and copied content. It uses configured roots, not fixture labels; execution uses the inspected immutable request.
- Added a three-arm runner and 13 tests; all 36 tests passed. Kept the original monitor, paired runner, protocols, datasets, and old results unchanged.
- **Observed in each suite separately:** protected operations 4 → 2 → 0; functional completion 8/8 → 6/8 → 8/8; safe completion 4/8 → 4/8 → 8/8; benign blocks 0/12 → 2/12 → 0/12. No guard or execution errors occurred. Original development arms reproduce the earlier raw records exactly.
- Saved raw traces, console and test outputs, hashes, and [findings](docs/GATE_FINDINGS.md). Code hashes match between development and supplemental runs.
- **Limit/next:** fixed-topology fixture evidence only. Study hardlinks or topology mutation under a new protocol before expanding enforcement claims or integrating an agent.

## 2026-10-26 — Paired fixture replay and observed policy limits

- Added a pre-run protocol, eight fixed file tasks, and a separate runner that executes baseline/monitored pairs on fresh disposable synthetic fixtures.
- Added an oracle based on resolved protected resources and file/read goals, reporting risk events, functional and safe completion, false positives, shared guard rejections, and execution errors.
- Added 12 replay tests; all 23 tests passed. The paired run exited 0 with zero guard rejections or execution errors.
- **Observed:** protected operations 4 → 2; functional completion 8/8 → 6/8; safe completion 4/8 → 4/8. Two benign-path false positives and two protected-alias misses remain documented.
- Preserved the string-only monitor, policy datasets, and prior results. Saved raw traces, hashes, environment, command, and the [findings report](docs/REPLAY_FINDINGS.md).
- **Next:** compare an executor-aware gate under explicit filesystem assumptions, then use newly frozen evaluation tasks before any live-agent study.

## 2026-10-26 — Reverification, dataset v3, and current documentation

- Re-ran the existing 11 unit tests and both frozen datasets against the unchanged checker and runner from `7ae79aa5d337ad0ac02431f28b8db2a7f859910e`: tests 11/11, v1 20/20, v2 21/21.
- Added v3 with all 21 v2 cases plus 24 predefined edge cases (45 total), a design note, and an explicit statement that these overlapping datasets are not independent holdout evidence.
- Ran v3: 45/45 expected decisions matched; 19/19 risky and 10/10 invalid-input cases blocked; 16/16 legitimate cases allowed; zero mismatches or monitor errors.
- Saved new raw outputs, summaries, the unit-test transcript, and a verification record containing commands, exit codes, Python version, source commit, and SHA-256 hashes. Earlier measured datasets and result files are preserved.
- Updated README, architecture, experiment plan, and experiment instructions to distinguish completed synthetic checks from planned task-execution and agent evaluations. This verification supersedes the older unconfirmed v2 status below; historical entries are retained.
- **Evidence:** [verification record](experiments/results/2026-10-25T16-05-40Z-verification.json) and [research entry](docs/RESEARCH_LOG.md#2026-10-26--reverification-and-synthetic-dataset-v3). Entry date is Asia/Seoul; result filenames use UTC.
- **Limit:** classification agreement on hand-authored cases does not establish filesystem enforcement, task completion, or risk reduction for a live AI agent.
- **Next:** define held-out cases and execution-harness semantics before changing policy or adding an agent adapter.

## 2026-10-21 — Path-normalization regression fix and dataset v2

- Updated path validation to reject explicit `.` components before path normalization.
- Added two unit tests for explicit current-directory path components.
- Added `experiments/cases/v2/actions.jsonl` with 21 synthetic cases, including `RISK-009`; preserved v1 as the baseline dataset.
- Updated the experiment runner to accept a `--dataset` path and updated experiment instructions.
- **Verification status:** changes are committed; updated unit tests and the v2 dataset run have not yet been confirmed by the project author.

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
