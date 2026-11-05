# Experiment guide

The repository separates policy conformance, task replay, and deterministic object-continuity studies. Choose the command corresponding to the claim being examined. All filesystem targets are disposable synthetic fixtures; earlier datasets and raw outcomes are preserved.

[Documentation index](../docs/README.md) · [Claims and raw evidence](../docs/EVIDENCE.md) · [Threat model and limits](../docs/LIMITATIONS.md)

## Environment and validation

Use Python 3.11+ and the standard library on Linux for the current full suite and latest experiment, including an available `sqlite3` extension and file/directory fsync support. The full suite exercises hardlinks, symlinks, FIFOs, and `pread`; missing capabilities must fail visibly rather than skip an attack case. No model/API credentials, third-party Python packages, or external datasets are needed. Run commands from the repository root after cloning as shown in the [quick start](../README.md#quick-reproduction).

```bash
python -m unittest discover -s tests -v
```

The historical Phase 6–11 runs passed 67, 85, 111, 141, 176 and 209 tests; the current Phase 12 run passes 244. The latest controller uses pipe selectors and numeric SQLite error metadata; older standalone runners retain their recorded requirements. Unit tests include injected failures and regression checks; they are separate from experiment sample counts.

The commands below run the currently checked-out code. `--base-commit "$(git rev-parse HEAD)"` records that checkout's starting revision; the runner also hashes its executed source files. Use a clean checkout for an auditable rerun. Historical starting revisions and commands remain in the linked summaries. Neither `--base-commit` nor `--freeze-commit` checks out, downloads, or verifies a revision: both are caller-supplied provenance labels. The freeze value identifies the historical prospective design, not the current implementation.

## Phase 12: simultaneous same-ID callers

```bash
python experiments/run_caller_comparison.py --dataset experiments/tasks/caller-eval-v1/tasks.json --base-commit "$(git rev-parse HEAD)" --freeze-commit 628df4caa665e0724eba498769bf754bc1725522
```

Sixteen cases run in `precheck_insert`, `constraint_conflict`, `resolve_duplicate` and `transactional_lookup`: 64 records. There are 52 forced overlaps with a live first caller paused after receipt lookup and twelve serial records. In precheck races the second caller commits first; transactional lookup holds the writer and defers that second caller. Every busy retry preserves caller/epoch/key/bytes. Optional independent later work commits before the losing caller's final result. No sleep arranges the schedule.

Expect correct caller pairs in twelve shared overlaps **0/12 → 6/12 → 12/12 → 12/12**. Identical replay across six cases is 0/6 → 0/6 → 6/6 → 6/6; changed-intent conflict is 0/6 → 6/6 → 6/6 → 6/6. Modeled final storage errors (12 → 0 → 0 → 0) and false identical conflicts (0 → 6 → 0 → 0) remain negative outcomes, separate from unexpected infrastructure errors.

All modes must retain one shared effect in 15/15 shared cases, both distinct-key effects, all three serial response pairs, and all four later states. Successful historical replays in two identical-later cases return revision 4 while current revision 5 remains intact. Receipt-key code-1555 aborts and explicit whole rollbacks are 12 → 12 → 12 → 0. Numeric code-5 busy attempts and completed retries are 0 → 0 → 0 → 13, including the distinct-ID overlap. Require all ten criteria, exact actor/controller traces and 157 normal child invocations with zero unexpected errors.

Audit the retained run:

```bash
python experiments/verify_caller_results.py --summary experiments/results/2026-11-05T01-18-48-550840Z-caller-v1-summary.json --dataset experiments/tasks/caller-eval-v1/tasks.json
```

For a fresh run, substitute its printed summary filename. The independent verifier uses only the standard library to reconstruct the actual committing caller, causal snapshots, original receipts, delivery, both final responses and every counter; it also checks the input and eleven source hashes. Historical verification requires matching source versions. It exits nonzero on infrastructure errors or unmet scientific criteria. `--output /tmp/codeguardian-caller-verification.json` exclusively creates a report; `--output-dir /tmp/codeguardian-caller` keeps new controller output separate from retained evidence.

Python 3.11+ on Linux is required. This study fixes epoch 2 and retains receipts during challenged calls. It does not compose retirement with duplicate resolution, inject crashes, measure latency/fairness, or establish many-caller or network semantics. A clean controller exit alone does not establish correct caller outcomes. [Protocol](../docs/CALLER_PROTOCOL.md) · [Findings and raw evidence](../docs/CALLER_FINDINGS.md).

## Phase 11: publication and retirement overlap

```bash
python experiments/run_overlap_comparison.py --dataset experiments/tasks/overlap-eval-v1/tasks.json --base-commit "$(git rev-parse HEAD)" --freeze-commit db733eef02c79176e2fbd2e241c3bce20410ae19
```

Sixteen cases run in `cached_admission`, `separate_recheck`, and `transactional_admission` modes: 48 records, including 24 forced overlaps with a live publisher paused while a retirement child runs, and 24 ordering/current controls. Pipe messages fix the schedule; no sleep is used to arrange it. All 48 publisher and 58 retirement invocations complete normally, 106 child invocations total. No crash injection is used.

Expect invalid old effects 4/4 → 2/4 → 0/4 across four admission-gap opportunities; valid old commits 6 → 6 → 10 across twelve old cases; and old denials 2 → 4 → 2. Retirement deferrals are 2 → 2 → 6, each exact numeric SQLite code 5 at BEGIN with checked zero busy timeout. Every deferred attempt is retried after publisher completion and commits. This changes ordering; it does not promise immediate retirement or fairness.

All modes must complete four current-epoch value/revocation controls, return two valid historical commitments after retirement, retain 16/16 coherent final states, and close every final epoch to 2. A commit witness validates the epoch at the effect, independently of the later response. Require all ten criteria, complete actor/controller traces, and zero infrastructure errors.

Audit the retained run:

```bash
python experiments/verify_overlap_results.py --summary experiments/results/2026-11-05T00-16-36-716146Z-overlap-v1-summary.json --dataset experiments/tasks/overlap-eval-v1/tasks.json
```

For a fresh run, substitute its printed summary filename. The independent verifier rebuilds actor traces, barrier/controller ordering, current state, receipts, witnesses, and counters, then checks the input and nine source hashes. Historical verification requires those matching source versions. It exits nonzero on infrastructure errors or unmet criteria. `--output /tmp/codeguardian-overlap-verification.json` creates a new report; `--output-dir /tmp/codeguardian-overlap` keeps new controller output outside retained evidence.

Use Python 3.11+ on Linux. The study fixes two trusted roles in rollback-journal mode; it does not estimate random race probability, latency, starvation, many-writer histories, WAL behavior, authentication, or crash recovery. The controller's deadlines detect broken execution, not service latency. [Protocol](../docs/OVERLAP_PROTOCOL.md) · [Findings and raw evidence](../docs/OVERLAP_FINDINGS.md).

## Phase 10: receipt retirement and trusted epochs

```bash
python experiments/run_retirement_comparison.py --dataset experiments/tasks/retirement-eval-v1/tasks.json --base-commit "$(git rev-parse HEAD)" --freeze-commit b6e1c712648f7f0225fe236238badddf30b9e41d
```

Twenty cases run in `retain_all`, `forget_only`, `split_fence`, and `atomic_fence`: 80 records, 32 declared child exits, and 48 normal retirement completions. Each fixture first commits an epoch-1 publication and an opposing later policy. The child retires to target epoch 2; the parent reopens before each delayed or current request.

Expect extra effects for known epoch-1 IDs 0/10 → 6/10 → 2/10 → 0/10 and preserved later-policy cases 10/10 → 4/10 → 8/10 → 10/10. Original historical replies are returned 10 → 4 → 2 → 4 times. Both compact fenced arms reject six known requests after completed retirement without returning a commitment revision. Sixteen captures per arm recover completed retirement before follow-up requests: the retaining arm has two old receipt rows each, other arms zero. This is a logical row count, not a storage-reclamation measurement.

All arms must complete three new active-epoch intents, handle two current repeats and two conflicts, and reject the future-epoch request. Retaining/fenced designs reject two previously unseen old requests; forgetting applies both. Require all twelve criteria, expected recovery layouts, exact traces, and zero infrastructure errors. All final content/approval pairs remain coherent even in the wrong-intent cases.

Audit the retained run:

```bash
python experiments/verify_retirement_results.py --summary experiments/results/2026-11-04T15-09-50-473480Z-retirement-v1-summary.json --dataset experiments/tasks/retirement-eval-v1/tasks.json
```

For a new run, substitute its printed summary filename. The verifier independently reconstructs effect prefixes, receipt layouts, current delivery, historical reply or rejection, counters, and criteria, then checks the input and eight source hashes. Historical verification requires matching those source versions. It exits nonzero on infrastructure errors or unmet criteria. `--output /tmp/codeguardian-retirement-verification.json` creates a new verification report; `--output-dir /tmp/codeguardian-retirement` keeps fresh runner output outside retained evidence.

Epochs are trusted logical namespaces preserved on retries; this is not authentication or a wall-clock TTL. Rejection of unseen old work and loss of historical replies are explicit costs. The observer history grows, so deleting receipt rows does not bound the full database. Phase 10 leaves overlapping publication/retirement to the Phase 11 comparison above. Physical reclamation and host power loss remain untested. [Protocol](../docs/RETIREMENT_PROTOCOL.md) · [Findings and raw evidence](../docs/RETIREMENT_FINDINGS.md).

## Phase 9: request retries and historical receipts

```bash
python experiments/run_retry_comparison.py --dataset experiments/tasks/retry-eval-v1/tasks.json --base-commit "$(git rev-parse HEAD)" --freeze-commit 1b7152561029c22f9bc04ba7568937b01a3fe2e2
```

Twenty cases run in `unkeyed`, `split_receipt`, and `atomic_receipt` arms: 60 records, 24 declared child-process exits, and 36 normally completed first publications. All arms commit a coherent payload/approval row and effect observer together. The intervention changes whether request receipts are absent, separately committed, or included in that transaction.

Expect successful same-intent retries 2/12 → 10/12 → 12/12 and retry cases with extra effects 10/12 → 2/12 → 0/12. The split arm's two failures occur after state commit but before receipt commit. Both keyed arms must reject both changed-intent requests, preserve both intervening publications on late retry, and apply both new IDs with identical intent. All arms must pass four single-publication controls and retain 20/20 coherent final pairs. Require all ten criteria and zero infrastructure errors; coherence alone does not establish correct intent.

Audit the retained run:

```bash
python experiments/verify_retry_results.py --summary experiments/results/2026-11-03T02-27-20-879552Z-retry-v1-summary.json --dataset experiments/tasks/retry-eval-v1/tasks.json
```

Substitute a fresh run's printed summary filename to audit it. The independent verifier enumerates expected committed effect prefixes without importing the store or runner, checks actual current delivery and historical response fields, recounts all counters, and verifies the input and seven source hashes. It exits nonzero on infrastructure errors or unmet criteria. Historical verification requires matching source versions. `--output /tmp/codeguardian-retry-verification.json` writes a report only to a new file; `--output-dir /tmp/codeguardian-retry` keeps fresh runner outputs separate from retained evidence.

A replayed receipt is historical and never restores its old approval. A different ID denotes a new intent. One trusted sequential namespace, indefinite receipt retention, one database effect domain, and process-exit checkpoints bound the claim; no general exactly-once execution, receipt eviction, host power loss, or concurrent-request guarantee is established. [Protocol](../docs/RETRY_PROTOCOL.md) · [Findings and raw evidence](../docs/RETRY_FINDINGS.md).

## Phase 8: content and approval after publisher termination

```bash
python experiments/run_recovery_comparison.py --dataset experiments/tasks/recovery-eval-v1/tasks.json --base-commit "$(git rev-parse HEAD)" --freeze-commit b9f4d344f6589a0069b39f02bc9552517b06cacd
```

Nineteen cases run in `split_unchecked`, `split_verified`, and `sqlite_atomic` arms, producing 57 records. The parent observes 48 declared child-process exits and nine normal controls. It requires both the expected return code and event prefix; a random failure or timeout cannot count as a valid fault injection.

Expect recovered state coherence 17/19 → 17/19 → 19/19; invalid deliveries across two after-stage update gaps 2/2 → 0/2 → 0/2; and valid deliveries across 15 active-approval cases 13/15 → 13/15 → 15/15. All arms must deny four committed revocations, recover four acknowledged publications and four committed-but-unacknowledged publications, and deliver all three unchanged controls. These denominators overlap. Require all 11 criteria and zero infrastructure errors, separately from exit status.

Audit the retained run using the independent verifier:

```bash
python experiments/verify_recovery_results.py --summary experiments/results/2026-11-02T10-48-45-510158Z-recovery-v1-summary.json --dataset experiments/tasks/recovery-eval-v1/tasks.json
```

For a fresh run, substitute its printed summary filename. To save a verification report, add `--output /tmp/codeguardian-recovery-verification.json` with a new filename; exclusive creation prevents overwriting a previous report. The verifier reconstructs counters from raw observations and verifies the fixed matrix, event order, source/input hashes, and criteria. It exits nonzero on infrastructure errors or unmet criteria. Full historical source-hash verification requires the implementation matching the six recorded source files, including tests and verifier.

`--output-dir /tmp/codeguardian-recovery` keeps new experiment outputs outside retained evidence. The fixture stores use a single trusted writer, and SQLite stores the payload itself alongside approval. This is not policy for an external mutable file. The child calls `os._exit` at application checkpoints while the OS and parent survive; power loss and faults inside storage operations are untested. [Protocol](../docs/RECOVERY_PROTOCOL.md) · [Findings and raw evidence](../docs/RECOVERY_FINDINGS.md).

## Phase 6: approved content on a stable inode

```bash
python experiments/run_content_comparison.py --dataset experiments/tasks/content-eval-v1/tasks.json --base-commit "$(git rev-parse HEAD)" --freeze-commit ce3fd6d245a2013090f7bd8c6367d08895132723
```

Eight cases run in `identity_only`, `hash_then_reread`, and `verified_buffer` arms. Five schedules change ordinary-file bytes through a hardlink; three controls use unchanged ASCII, Unicode, and empty content. Linux `pread` supports the diagnostic inspection/reread comparator without moving its descriptor offset.

Observed unapproved deliveries are 5/5 → 3/5 → 0/5; approved-version deliveries are 3/8 → 3/8 → 6/8. Both digest arms deny two pre-capture mutations after inspection. The buffer returns three approved but stale values. These are content-delivery measures under a new rule, not protected-resource access counts or live-agent completion. See the [protocol](../docs/CONTENT_PROTOCOL.md), [findings](../docs/CONTENT_FINDINGS.md), and [summary/provenance](results/2026-10-27T12-21-15-144558Z-content-v1-summary.json).

## Phase 5: deterministic pathname replacement

```bash
python experiments/run_race_comparison.py --dataset experiments/tasks/race-eval-v1/tasks.json --base-commit "$(git rev-parse HEAD)" --freeze-commit d0ddc20aac99365adb85bc48ef53539c8028a127
```

Ten cases run in `baseline`, `identity_path`, and `descriptor_bound` arms. The controller fixes replacement timing; there are no concurrent threads or race-win-rate measurements. The [protocol](../docs/RACE_PROTOCOL.md) defines six attack schedules and eight original-object-eligible cases, with overlap. Protected opens are distinct from protected content operations.

The recorded result is 6/6 → 4/6 → 0/6 protected content operations and 2/8 → 2/8 → 8/8 original-object completion. The descriptor arm makes two protected opens for metadata and denies both before content I/O. See [findings](../docs/RACE_FINDINGS.md), [raw records](results/2026-10-26T08-23-21-637204Z-race-v1.jsonl), and [summary/provenance](results/2026-10-26T08-23-21-637204Z-race-v1-summary.json).

## Phase 4: hardlink identity

```bash
python experiments/run_identity_comparison.py --dataset experiments/tasks/identity-eval-v1/tasks.json --base-commit "$(git rev-parse HEAD)" --freeze-commit 8e0910d86636c9cd4264b9c1f3e70da4c7b8b39f
```

Six tasks run in four arms on fixed topology. The identity gate prevents both protected hardlink operations missed by the resolved gate, with 0/3 protected operations and 6/6 safe completions. The [findings](../docs/IDENTITY_FINDINGS.md) retain that result within its fixed-topology scope; Phase 5 tests a different assumption.

## Phase 3: resolved-target approval

```bash
python experiments/run_comparison.py --dataset experiments/tasks/replay-v1/tasks.json --suite-role development --base-commit "$(git rev-parse HEAD)" --freeze-commit 1d9bbe305625f5b7df55a185463908729c48cc03
python experiments/run_comparison.py --dataset experiments/tasks/gate-eval-v1/tasks.json --suite-role supplemental --base-commit "$(git rev-parse HEAD)" --freeze-commit 1d9bbe305625f5b7df55a185463908729c48cc03
```

Report development and supplemental suites separately. Each has eight tasks and three arms. The supplemental protocol was frozen before implementation, but cases were visible during development and are not an independent holdout. [Findings](../docs/GATE_FINDINGS.md) link both raw runs and their unchanged source hashes.

## Phase 2: paired replay

```bash
python experiments/run_replay.py --dataset experiments/tasks/replay-v1/tasks.json --base-commit "$(git rev-parse HEAD)"
```

Eight tasks compare baseline execution with the unchanged string gate. Protected operations fall from four to two, functional completion from 8/8 to 6/8, and safe completion remains 4/8. [Findings](../docs/REPLAY_FINDINGS.md) explain why fewer protected operations did not produce more safe completions.

## Phase 1: policy conformance

```bash
python experiments/run_dataset.py --dataset experiments/cases/v1/actions.jsonl
python experiments/run_dataset.py --dataset experiments/cases/v2/actions.jsonl
python experiments/run_dataset.py --dataset experiments/cases/v3/actions.jsonl
```

| Dataset | Legitimate | Risky | Invalid | Total |
|---|---:|---:|---:|---:|
| v1 | 8 | 8 | 4 | 20 |
| v2 | 8 | 9 | 4 | 21 |
| v3 | 16 | 19 | 10 | 45 |

V2 retains v1 and adds one regression case; v3 retains v2 and adds 24 cases. These overlapping versions are not independent samples. The [v3 design note](cases/v3/README.md) preserves label rationale and limitations. The [verification record](results/2026-10-25T16-05-40Z-verification.json) records 20/20, 21/21, and 45/45 matches with zero mismatches or monitor errors.

Only each case's `input` is passed to the checker. `expected_decision`, class, and rationale remain evaluation metadata. Policy labels describe a conservative string policy; they do not establish actual resource safety.

## Reading and preserving artifacts

Runners write timestamped raw JSONL and summary JSON under `experiments/results/`; filesystem comparisons use unique microsecond timestamps and exclusive creation. `--output-dir` selects a different output directory. Filenames use UTC, while narrative dates use Asia/Seoul. Base commits identify the starting revision; source hashes identify the exact files executed, including newly added code. Freeze commits identify the prospective design.

### Expected output and checks

Comparison runners print a JSON summary and the saved run identifier; the policy runner prints text metrics and output paths. Open the matching `*-summary.json`, then the raw filename specified by its `results_file` field. Expect the following grids; policy versions and related suites remain separate.

| Run | Expected raw rows | Headline check in `summary` |
|---|---:|---|
| Policy v1 / v2 / v3 | 20 / 21 / 45 | `matched_cases` equals `total_cases`; zero `mismatched_cases` and `monitor_errors` |
| Paired replay | 16 = 8 tasks × 2 arms | `arms.monitored`: 2 risk events, 6 functional and 4 safe completions |
| Resolved development / supplemental | 24 each = 8 tasks × 3 arms | Each `arms.executor_aware`: 0 risk events, 8 functional and 8 safe completions |
| Identity | 24 = 6 tasks × 4 arms | `arms.identity_gate`: 0 risk events, 6 safe completions |
| Replacement | 30 = 10 cases × 3 arms | `arms.descriptor_bound`: 0 protected content operations, 2 protected opens, 8 original completions |
| Content | 24 = 8 cases × 3 arms | `arms.verified_buffer`: 0 unapproved deliveries, 6 approved deliveries, 2 content blocks, 3 approved but stale values |
| Revisions | 27 = 9 cases × 3 arms | `arms.coordinated_release`: 0 invalid receipts, 5 valid receipts, 2 deferred publications |
| Recovery | 57 = 19 cases × 3 arms | `arms.sqlite_atomic`: 19 coherent states, 15 valid deliveries, 0 invalid deliveries, 4 revocation denials |
| Request retry | 60 = 20 cases × 3 arms | `arms.atomic_receipt`: 12 successful retries, 0 duplicate retry cases, 2 correct conflicts, 2 preserved late states |
| Receipt retirement | 80 = 20 cases × 4 arms | `arms.atomic_fence`: 0 known duplicates, 10 preserved policies, 6 closed-epoch denials, 0 old receipt rows after commit |
| Admission overlap | 48 = 16 cases × 3 modes | `arms.transactional_admission`: 0 invalid old effects, 10 valid old commits, 6 deferrals/retries, 4 current successes |

For filesystem studies, require zero execution/infrastructure errors and inspect every declared criterion as well as controls and legitimate completion. A zero protection-failure count produced by broken execution is not a successful result. Raw IDs must cover each declared case/arm pair exactly once; the [evidence map](../docs/EVIDENCE.md) gives the historical files for comparison.

### Provenance and historical reproduction

For a current-code rerun, compare outcome counts and criteria with the historical summary, then check dataset and source hashes. Timestamps, fixture paths, device/inode numbers, commands, and platform fields can differ; byte-for-byte equality of raw runs is not expected. A changed source hash identifies a difference to explain, not an automatically equivalent experiment. Early policy summaries have less provenance; use their separate [verification record](results/2026-10-25T16-05-40Z-verification.json).

To inspect a historical implementation, use a separate checkout at its implementation revision and verify all source/task hashes against the recorded summary before attributing a rerun to it. A summary's historical `base_commit` may precede files added during that study, so checking out that base alone is insufficient. Frozen protocols and recorded source hashes remain the evidence for what was specified and executed. Append `--output-dir /tmp/codeguardian-reproduction` to a filesystem comparison command to keep its rerun outside the retained evidence directory. The policy runner has no output-directory option and writes to `experiments/results/`; its filenames have second precision, so avoid repeating the same version within one second.

For comparison runners, exit 0 means clean experiment execution, not that every scientific criterion held. Inspect the summary's criteria and raw rows. Per-case infrastructure failures cause a nonzero outcome; setup/schema failures also fail explicitly. The policy runner instead exits nonzero for decision mismatches or monitor errors. Record the runner's actual output rather than assuming a shared exit-code taxonomy.

Keep earlier inputs, protocols, and raw runs unchanged. When a hypothesis or case changes, use a new version. Preserve negative results and error traces. Living findings can add interpretation or follow-up links without changing the original measurements. These artifacts support bounded mechanism claims, not deployed security or live-agent effectiveness.

## Phase 7: approval updates and revocation

```bash
python experiments/run_revision_comparison.py --dataset experiments/tasks/revision-eval-v1/tasks.json --base-commit "$(git rev-parse HEAD)" --freeze-commit 85c6e23898da60b39dc7450da0f4b9a721ac7374
```

Nine cases run in `snapshot_only`, `recheck_then_release`, and `coordinated_release` arms: 27 raw journal records. Expect invalid receipts 5/5 → 2/5 → 0/5 across five post-capture transitions, valid receipts 3/9 → 3/9 → 5/9, and denials 1 → 4 → 4. Coordinated release defers two publication attempts; all eight requested publications per arm eventually commit. Two valid coordinated receipts become obsolete afterward. Require all nine summary criteria and zero infrastructure errors. The Phase 7 test run passed 85 tests.

The [analysis plan](../docs/REVISION_PROTOCOL.md) was frozen before the recorded measurement, after draft implementation existed. [Findings](../docs/REVISION_FINDINGS.md) link raw records, source hashes, and artifact verification. Use `--output-dir` for a separate rerun directory. No distributed coordination, immediate revocation, or crash rollback is claimed.
