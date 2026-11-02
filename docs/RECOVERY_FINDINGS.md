# Phase 8 findings: fail-closed recovery is not state recovery

**Study:** 19 cases in each of three arms, 57 case/arm records. Measured 2026-11-02 (Asia/Seoul).

## Question and result

Phase 7 coordinates approval changes and receipt while one process runs. It does not make a two-step publication recoverable after that process exits. Phase 8 compares separately persisted payload/approval, validation of that recovered pair, and a transaction containing both. The recovery reader starts only after the child publisher has terminated.

| Outcome | Split, unchecked | Split, verified | SQLite, one transaction |
|---|---:|---:|---:|
| Coherent recovered states / all cases | 17/19 | 17/19 | 19/19 |
| Invalid deliveries / two update-gap cases | 2/2 | 0/2 | 0/2 |
| Valid deliveries / active-approval cases | 13/15 | 13/15 | 15/15 |
| All deliveries / all cases | 15/19 | 13/19 | 15/19 |
| Denials / all cases | 4/19 | 6/19 | 4/19 |
| Digest-mismatch denials | 0 | 2 | 0 |
| Committed revocations correctly denied | 4/4 | 4/4 | 4/4 |
| Acknowledged publications recovered | 4/4 | 4/4 | 4/4 |
| Committed, unacknowledged publications recovered | 4/4 | 4/4 | 4/4 |
| ASCII, empty, and Unicode controls delivered | 3/3 | 3/3 | 3/3 |
| Declared termination boundaries reached | 16/16 | 16/16 | 16/16 |
| Infrastructure errors | 0 | 0 | 0 |

The denominators overlap and have different purposes. The 15 active-approval cases exclude four committed revocations, and include both precommit update gaps. All 19 cases remain in state coherence and total outcomes. These deterministic cases do not estimate a general failure probability or a population availability rate.

## What breaks, and what the interventions change

The split publisher replaces and syncs the payload first, then separately replaces and syncs the approval JSON. Every individual replacement can complete correctly while the pair remains inconsistent. Exiting after the first step leaves version-B bytes with the revision-1 approval of version A. The ASCII and empty-initial-value cases both expose this gap.

The unchecked recovery arm delivers those mismatches. The verified arm runs the exact same publisher and instead hashes the captured bytes before returning them. It rejects the two mismatches without returning a payload, but the previous usable content has already been replaced. Its state-coherence result remains 17/19: refusal to deliver is not repair of the stored pair. Inspection still reads the rejected bytes.

SQLite changes the commit unit. The payload, approval digest or revocation marker, and revision occupy one row updated in one explicit transaction. At the before-commit cut, reopening recovers revision 1 and its original payload; at the after-commit cuts, it recovers revision 2. This yields 19/19 coherent states and 15/15 authorized reads in the selected cases. The intervention changes data placement and transaction boundaries, not just a gate condition. SQLite atomic commit is an established mechanism, and the database is a trusted dependency.

The unchecked comparator deliberately omits digest validation. Its two invalid deliveries are not evidence that Phase 6's verified reader or Phase 7's authority fails its original contract. The comparison with verified split recovery is the important availability distinction: both verified designs prevent the observed invalid deliveries, but only the transactional layout retains a usable old-or-new state in the two gaps.

## Commit, acknowledgment, and revocation

The child emits an acknowledgment only after publication returns. Terminating immediately afterward preserves the acknowledged update or revocation in 4/4 cases per arm. Terminating after commit but before acknowledgment also recovers the committed state in 4/4 cases. This shows why an absent response cannot establish that an operation was rolled back. It does not implement exactly-once requests or safe retries.

Before-commit revocation cuts recover the previous active approval; the revocation request has not committed. After-commit revocations deny delivery in all four eligible cases. This is committed-policy recovery, not immediate request-time revocation or withdrawal of information already delivered.

## Fault model and validation

There are three unchanged controls and 16 publication/termination schedules per arm. A real child process calls `os._exit(73)` at a named application boundary, bypassing Python cleanup. The parent validates the exact flushed event prefix and exit code before evaluating recovery. The 48 planned termination records and nine normal control records contain zero infrastructure errors.

The parent, OS, and storage system keep running. No cut is injected during a filesystem call, fsync, or SQLite's internal commit. The result does not establish power-loss durability, arbitrary torn-write recovery, or recovery from a kernel failure. Individual split files use file and directory synchronization; SQLite uses verified `journal_mode=DELETE` and `synchronous=FULL`. All 19 SQLite recovery checks report `integrity_check=ok`.

All **111 unit tests passed**, including 26 new tests for restart persistence, mismatch denial, revocation, empty/Unicode values, malformed/missing state, actual child exits, rejected false fault coverage, exception boundaries, and forged assessments. The tests remain separate from the 57 experimental records.

The independent artifact verifier imports neither the stores nor the measured runner. It rebuilds the fixed case/arm grid, expected revisions and bytes, trace coverage, delivery classifications, counters, and criteria from raw observations. The recount matches all summary counts and all 11 prespecified criteria; the manifest hash and six recorded source hashes match.

## Evidence and reproduction

The [protocol](RECOVERY_PROTOCOL.md) and [19-case manifest](../experiments/tasks/recovery-eval-v1/tasks.json) were committed before Phase 8 implementation and measurement at [`b9f4d34`](https://github.com/hylen707/AI-agentic-Code-Guardian-Cybersecurity/commit/b9f4d344f6589a0069b39f02bc9552517b06cacd). The cases were visible during development. Earlier implementation, protocols, cases, and raw evidence retain their original bytes.

- [Raw process traces and recovery observations](../experiments/results/2026-11-02T10-48-45-510158Z-recovery-v1.jsonl)
- [Summary, source/input hashes, Python/SQLite versions, platform, and command](../experiments/results/2026-11-02T10-48-45-510158Z-recovery-v1-summary.json)
- [Independent verification and recount](../experiments/results/2026-11-02T10-48-45-510158Z-recovery-v1-verification.json)
- [Full 111-test transcript](../experiments/results/2026-11-02T10-48-45-510158Z-recovery-v1-unit-tests.txt)
- [Experiment console](../experiments/results/2026-11-02T10-48-45-510158Z-recovery-v1-console.txt)

```bash
python -m unittest discover -s tests -v
python experiments/run_recovery_comparison.py --dataset experiments/tasks/recovery-eval-v1/tasks.json --base-commit "$(git rev-parse HEAD)" --freeze-commit b9f4d344f6589a0069b39f02bc9552517b06cacd
python experiments/verify_recovery_results.py --summary experiments/results/2026-11-02T10-48-45-510158Z-recovery-v1-summary.json --dataset experiments/tasks/recovery-eval-v1/tasks.json
```

The verifier command above audits the retained run. To audit a fresh run, pass its printed summary filename. A later change to one of the six recorded source files requires the matching historical implementation for full source-hash verification. The runner's clean exit is separate from scientific criteria; the verifier exits nonzero when the criteria fail or infrastructure errors exist.

## Limits and next question

This is a trusted, single-writer fixture-store study. It is not integrated with the earlier path/identity gate or a live executor. Storing approved bytes in the same database is different from maintaining policy for a mutable external file. Other designs, such as immutable version objects with an atomic selector, are not compared. Multiple writers, hostile changes, failed recovery attempts, large values, distributed publication, and storage-device faults remain untested.

The next question is how a caller retries after a commit whose acknowledgment was lost. A request identity and deduplication rule must distinguish retry from a legitimate new approval before any exactly-once claim. Crash cuts inside storage operations and replayed failures during recovery require their own fault models.
