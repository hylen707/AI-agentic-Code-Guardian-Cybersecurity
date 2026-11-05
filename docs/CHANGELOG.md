# Changelog

This record tracks implemented changes and their validation in reverse chronological order. The [research log](RESEARCH_LOG.md) records questions, decisions, and interpretation. Older entries retain what was known at the time.

Do not record a planned feature as completed, and do not describe a test as passing unless it has actually been run and its output checked.

## 2026-11-05 — Epoch admission under overlapping retirement

- Froze the overlap protocol and 16-case manifest at `db733eef02c79176e2fbd2e241c3bce20410ae19` before Phase 11 implementation and measurement.
- Added cached, separate-recheck, and transactional admission scopes, an atomic commit witness, publisher/retirer child roles, a strict pipe-barrier controller, an independent actor/witness verifier, and 33 regression tests. Earlier implementations and retained evidence remain unchanged.
- Recorded 48 case/mode observations: invalid old effects 4/4 → 2/4 → 0/4; valid old commits 6 → 6 → 10; old denials 2 → 4 → 2. The transactional mode defers six retirements and completes all scheduled retries. Every mode completes four current controls and both postcommit historical-response cases.
- All 209 tests passed. The independent verifier matched all counters and ten criteria, checked the input and nine source hashes, and confirmed 24 forced overlaps plus 24 controls, 106 normal child invocations, and zero infrastructure errors.
- Updated the overview, research argument, evidence index, study map, architecture, limits, and reproduction guide. The current full suite/latest study requires Python 3.11+ on Linux for numeric SQLite error metadata and pipe selectors. Fixed two-role schedules do not establish fairness, latency, many-writer histories, or crash safety. [Findings and evidence](OVERLAP_FINDINGS.md).

## 2026-11-04 — Receipt retirement and epoch boundaries

- Froze the retirement protocol and 20-case manifest at `b6e1c712648f7f0225fe236238badddf30b9e41d` before Phase 10 implementation and measurement.
- Added four SQLite retention/retirement arms, a child retirement worker, an ideal epoch/intent runner, an independent effect-prefix/layout verifier, and 35 regression tests. Earlier implementations and measured artifacts remain unchanged.
- Recorded 80 case/arm observations: known late-request duplicate cases 0/10 → 6/10 → 2/10 → 0/10; later policy preserved 10/10 → 4/10 → 8/10 → 10/10. Atomic retirement removes old receipts and rejects closed-epoch requests; six original historical replies become unavailable. The retaining arm preserves both later policy and all ten original replies.
- All 176 tests passed. The independent verifier matched every counter and twelve criteria, checked the manifest and eight source hashes, and confirmed 32 declared exits plus 48 normal retirements with zero infrastructure errors.
- Updated the overview, research argument, evidence index, study map, architecture, limits, and reproduction guide. The experiment uses trusted logical epochs and one sequential writer; clock-based expiry, caller authentication, physical reclamation, and simultaneous publication/retirement remain outside scope. [Findings and retained evidence](RETIREMENT_FINDINGS.md).

## 2026-11-03 — Request identity and atomic publication receipts

- Froze the retry protocol and 20-case manifest at `1b7152561029c22f9bc04ba7568937b01a3fe2e2` before Phase 9 implementation and measurement.
- Added a SQLite request publisher with unkeyed, separate-receipt, and atomic-receipt arms, a terminating child worker, an ideal request-model runner, an independent effect-prefix verifier, and 30 regression tests. Earlier storage code is reused unchanged.
- Recorded 60 case/arm observations: successful same-intent retries 2/12 → 10/12 → 12/12; retry cases with extra effects 10/12 → 2/12 → 0/12. All final state pairs remain coherent. Both keyed arms reject changed intent, accept new IDs with identical payload, and preserve later updates/revocations when returning old receipts.
- All 141 tests passed. The independent verifier matched every counter and all ten criteria, checked the manifest and seven source hashes, and found zero infrastructure errors across 24 declared exits and 36 normal first publications.
- Updated the overview, research argument, study map, architecture, limits, evidence map, and reproduction guide. Claims concern retained IDs and one trusted sequential database namespace; receipt retirement, simultaneous requests, external effects, and host power loss remain outside scope. [Findings and evidence](RETRY_FINDINGS.md).

## 2026-11-02 — Coupled publication and restart recovery

- Froze the recovery protocol and 19-case manifest at `b9f4d344f6589a0069b39f02bc9552517b06cacd` before Phase 8 implementation and measurement.
- Added split-file and single-row SQLite stores, a child publisher with declared process-exit cuts, a three-arm runner, an independent raw-artifact verifier, and 26 regression tests.
- Recorded 57 case/arm observations: coherent states 17/19 → 17/19 → 19/19; invalid deliveries in two update gaps 2/2 → 0/2 → 0/2; valid reads 13/15 → 13/15 → 15/15. Every arm recovered four acknowledged and four committed-but-unacknowledged publications and denied all four committed revocations.
- All 111 tests passed. The independent verifier matched all counters and 11 criteria, checked the manifest and six source hashes, and found zero infrastructure errors. Earlier implementation, protocols, inputs, and measured artifacts are retained unchanged.
- Updated the README, study map, architecture, evidence index, limits, and reproduction guide. Scope is deterministic process termination while the OS and parent survive; no power-loss or exactly-once retry claim is made. [Findings and evidence](RECOVERY_FINDINGS.md).

## 2026-11-01 — Approval revisions at consumer receipt

Added a revision authority and three-arm comparison of snapshot release, separate recheck, and coordinated receipt. Nine cases produced 27 records: invalid receipts 5/5 → 2/5 → 0/5; coordinated release yielded 5/9 valid receipts, four denials, and two deferred publications, both eventually committed. All 85 tests passed. The analysis plan was frozen before measurement, with draft implementation already present; no pre-implementation freeze is claimed. Earlier implementation, frozen protocols, inputs, and evidence are preserved. See [findings](REVISION_FINDINGS.md).

## 2026-10-29 — Evidence-led documentation structure

- Compared official SWE-bench, Inspect, garak, and CyberGym documentation; recorded observed patterns, application decisions, and source URLs in the [documentation benchmark](DOCUMENTATION_BENCHMARK.md).
- Replaced repeated README exposition with the research question, contribution, an early runnable example, representative bounded findings, an experimental structure diagram, and reading routes. Added a [docs index](README.md), [cross-study evidence map](EVIDENCE.md), and [threat model and validity limits](LIMITATIONS.md); retained the detailed research argument and findings.
- Updated current-code reproduction examples to record the checked-out revision, and explained that commit arguments are provenance labels rather than checkout validation. Added expected record grids, summary fields, output behavior, and historical-reproduction guidance.
- Validation: all 67 existing unit tests passed; all nine experiment commands ran successfully and their complete scientific summaries matched the nine historical summaries. Recomputed those historical summaries from raw records and verified 56 recorded source/dataset SHA-256 entries. Checked local Markdown paths and heading fragments with no failures.
- Verified 68 implementation, test, frozen-protocol, case, task, and historical-evidence files byte-for-byte against main at `2786dd9`. New run output was kept outside retained historical evidence. This is a documentation revision, with no new mechanism, dataset, or research phase.

## 2026-10-28 — Research exposition and documentation organization

- Expanded the main README to make the research question, experiment progression, evaluation standards, and supporting evidence easier to follow.
- Relocated this changelog from the repository root to `docs/CHANGELOG.md` and updated internal relative links. All older entries are preserved.
- This entry concerns documentation only; it does not claim a new experiment or a newly executed test run.

## 2026-10-27 — Approved content delivery under same-inode mutation

- Froze the [content protocol](CONTENT_PROTOCOL.md) and eight-case manifest at `ce3fd6d245a2013090f7bd8c6367d08895132723` before implementation, building on PR #4's `4b47ab21db9808646cfc4a0dfd1be308896bf227`.
- Added a verified-content reader that composes the unchanged descriptor executor, a diagnostic hash/reread comparator, a three-arm runner, and 12 tests. Trusted expected digests are copied from owner configuration; actions cannot supply them.
- Observed identity-only → hash/reread → verified-buffer unapproved deliveries of 5/5 → 3/5 → 0/5 and approved deliveries of 3/8 → 3/8 → 6/8. Both digest arms denied two pre-capture changes; the buffer returned three approved but stale values. All 24 rows retained inode identity, with zero infrastructure errors.
- All 67 tests passed. Saved raw records, source/task/configuration hashes, test output, and [findings](CONTENT_FINDINGS.md). Added the content-version argument and freshness trade-off to living research documents without altering earlier code, frozen plans, or results.
- Next: define legitimate version updates and stale-value handling before extending the claim. Capture-time mutation, streaming, policy distribution, and live-agent evaluation remain untested.

## 2026-10-26 — Descriptor binding and research presentation

- Froze the [replacement protocol](RACE_PROTOCOL.md) and ten-case manifest at `d0ddc20aac99365adb85bc48ef53539c8028a127` before implementation.
- Added a descriptor-owning executor for existing regular-file reads/writes, a three-arm deterministic replacement runner, and 11 tests. Preserved all earlier implementation files and measured datasets.
- Observed baseline → identity-path → descriptor-bound protected content operations of 6/6 → 4/6 → 0/6 and original-object completion of 2/8 → 2/8 → 8/8. All arms had zero benign blocks and infrastructure errors. The descriptor arm still opened two protected objects for metadata authorization.
- All 55 tests passed. Saved raw records, source/task hashes, test output, and [findings](RACE_FINDINGS.md). Counts describe fixed schedules, not concurrent win rates or live-agent tasks.
- Reworked living Markdown into an English research portfolio: a concise project overview, explicit technical argument, study map, architecture, reproduction guide, and evidence-linked reflection prompts. Updated prior findings with historical scope and follow-up links.
- Audited all pre-existing Markdown. Preserved three earlier frozen protocols and the v3 design note byte-for-byte; retained historical log entries and raw results. Their integrity takes precedence over cosmetic rewriting.
- Next: define object-state and policy-membership experiments before extending the descriptor claim; creation and general confinement remain unimplemented research obligations.

## 2026-10-26 — Filesystem-identity gate closes hardlink bypass

- Froze `IDENTITY_PROTOCOL.md` and six hardlink-focused tasks in commit `8e0910d86636c9cd4264b9c1f3e70da4c7b8b39f` before implementing the identity gate.
- Added `IdentityAwareGate`, a four-arm runner, hardlink fixture setup, and eight identity tests. The gate checks prepared target path plus `(st_dev, st_ino)` identities of configured protected files.
- **Observed:** baseline → string gate → resolved-target gate → identity gate protected operations 3/3 → 3/3 → 2/3 → 0/3; functional completion 6/6 → 5/6 → 6/6 → 6/6; safe completion 3/6 → 2/6 → 4/6 → 6/6; benign blocks 0/9 → 1/9 → 0/9 → 0/9.
- All 44 tests passed; the comparison exited 0 with zero guard rejections and execution errors. Source and task hashes are recorded in the [summary](../experiments/results/2026-10-26T07-35-54-971592Z-identity-v1-summary.json).
- **Limit/next:** `stat` check-to-open is not race-safe and does not validate handle-level enforcement. Define a race-aware protocol before the next intervention.

## 2026-10-26 — Executor-aware gate and three-arm comparison

- Froze the comparison protocol and eight supplemental tasks in `1d9bbe305625f5b7df55a185463908729c48cc03` before implementation; the same developer designed both, so no blind-holdout claim is made.
- Added a separate gate on prepared canonical targets and copied content. It uses configured roots, not fixture labels; execution uses the inspected immutable request.
- Added a three-arm runner and 13 tests; all 36 tests passed. Kept the original monitor, paired runner, protocols, datasets, and old results unchanged.
- **Observed in each suite separately:** protected operations 4 → 2 → 0; functional completion 8/8 → 6/8 → 8/8; safe completion 4/8 → 4/8 → 8/8; benign blocks 0/12 → 2/12 → 0/12. No guard or execution errors occurred. Original development arms reproduce the earlier raw records exactly.
- Saved raw traces, console and test outputs, hashes, and [findings](GATE_FINDINGS.md). Code hashes match between development and supplemental runs.
- **Limit/next:** fixed-topology fixture evidence only. Study hardlinks or topology mutation under a new protocol before expanding enforcement claims or integrating an agent.

## 2026-10-26 — Paired fixture replay and observed policy limits

- Added a pre-run protocol, eight fixed file tasks, and a separate runner that executes baseline/monitored pairs on fresh disposable synthetic fixtures.
- Added an oracle based on resolved protected resources and file/read goals, reporting risk events, functional and safe completion, false positives, shared guard rejections, and execution errors.
- Added 12 replay tests; all 23 tests passed. The paired run exited 0 with zero guard rejections or execution errors.
- **Observed:** protected operations 4 → 2; functional completion 8/8 → 6/8; safe completion 4/8 → 4/8. Two benign-path false positives and two protected-alias misses remain documented.
- Preserved the string-only monitor, policy datasets, and prior results. Saved raw traces, hashes, environment, command, and the [findings report](REPLAY_FINDINGS.md).
- **Next:** compare an executor-aware gate under explicit filesystem assumptions, then use newly frozen evaluation tasks before any live-agent study.

## 2026-10-26 — Reverification, dataset v3, and current documentation

- Re-ran the existing 11 unit tests and both frozen datasets against the unchanged checker and runner from `7ae79aa5d337ad0ac02431f28b8db2a7f859910e`: tests 11/11, v1 20/20, v2 21/21.
- Added v3 with all 21 v2 cases plus 24 predefined edge cases (45 total), a design note, and an explicit statement that these overlapping datasets are not independent holdout evidence.
- Ran v3: 45/45 expected decisions matched; 19/19 risky and 10/10 invalid-input cases blocked; 16/16 legitimate cases allowed; zero mismatches or monitor errors.
- Saved new raw outputs, summaries, the unit-test transcript, and a verification record containing commands, exit codes, Python version, source commit, and SHA-256 hashes. Earlier measured datasets and result files are preserved.
- Updated README, architecture, experiment plan, and experiment instructions to distinguish completed synthetic checks from planned task-execution and agent evaluations. This verification supersedes the older unconfirmed v2 status below; historical entries are retained.
- **Evidence:** [verification record](../experiments/results/2026-10-25T16-05-40Z-verification.json) and [research entry](RESEARCH_LOG.md#2026-10-26--reverification-and-synthetic-dataset-v3). Entry date is Asia/Seoul; result filenames use UTC.
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
