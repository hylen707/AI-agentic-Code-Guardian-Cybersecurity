# Phase 7 protocol: approval at the consumer receipt boundary

**Status:** prospective protocol. Freeze this document and the nine-case manifest before implementation or execution. Earlier code, protocols, and evidence remain unchanged.

## Question and selected contract

When a trusted owner updates or revokes an approved content version, can a previously verified value still be delivered? Does a separate final approval check suffice, or must approval changes and consumer receipt share a synchronization boundary?

The contract is explicit: at the instant the trusted in-memory consumer records receipt, the payload must carry the currently committed approval revision, that revision must not be revoked, and its bytes must match the current approved digest. Revisions increase monotonically on every committed update or revocation, including a return to identical bytes. A previously captured revision is not silently relabeled as a new approval. This is a revision-specific rule, stricter than content equality alone.

The study does not promise immediate revocation at request time. A requested update that cannot obtain the coordination lock is pending, not yet committed. The experiment must expose any resulting delay in publication order. Consumer receipt is a trusted list append, not a model action, network send, or later use of the value.

## Shared preparation and arms

Each fresh synthetic Linux fixture contains an ordinary file, a hardlink for a trusted publisher, and a protected sentinel required by the unchanged resource gate. The authority starts at revision 1 with a trusted digest. A candidate records the authority snapshot, then uses the unchanged Phase 6 `VerifiedContentReader` to capture bytes matching that snapshot. Revoked snapshots are denied before capture. Actions cannot supply revisions or trusted digests.

Compare three release mechanisms:

1. `snapshot_only`: deliver the verified candidate without checking the authority again. This adapts the Phase 6 static policy behavior to the newly defined dynamic contract.
2. `recheck_then_release`: compare the candidate revision and digest with the current authority, release that check's lock, then deliver. A scheduled publication may occur in that gap.
3. `coordinated_release`: hold one non-reentrant lock while checking the candidate and recording consumer receipt. Every trusted publication acquires that same lock. A publication attempt inside this interval returns busy and is retried after release; it must not be silently dropped.

Trusted publication writes a new synthetic value through the existing hardlink, then commits a new authority revision and emits a publication event. Revocation commits a null digest without changing bytes. This is a single-process coordination protocol, not an atomic filesystem/database transaction; failures are explicit infrastructure errors, not rollback guarantees.

## Cases and ordering

Nine cases run in each arm, producing 27 records:

| Case | Publication point | Effect |
|---|---|---|
| ASCII control | none | Revision 1 remains active |
| Empty control | none | Empty approved value is deliverable |
| Update before capture | before snapshot/capture | Capture the newly approved revision 2 |
| Revoke before capture | before snapshot/capture | No candidate may be captured |
| Update after capture | before final check | Existing candidate becomes obsolete |
| Revoke after capture | before final check | Existing candidate loses approval |
| Update after recheck | after final check, before receipt | Expose a separate check/release gap |
| Revoke after recheck | after final check, before receipt | Expose a separate check/release gap |
| A-to-B-to-A after capture | before final check | Bytes return to A at revision 3; revision-1 candidate is still obsolete |

ASCII version A is `approved=version-a\n`; version B is `approved=version-b\n`; the empty control is zero bytes. The `snapshot_only` arm visits the equivalent post-check scheduling point without doing a check. The other arms perform the check first. Scheduled publication uses a nonblocking lock attempt; only the coordinated arm is expected to defer it at that boundary. All deferred operations are retried after receipt, before final-state observation.

Schedules are deterministic and single-threaded in the measured comparison. A focused unit test may use another thread to test lock exclusion, but is not another experimental sample, a concurrency benchmark, or a measurement of race probability.

## Oracle and prespecified expectations

An ordered journal records the initial authority state, every committed publication, and every consumer receipt. The oracle replays that history and compares each receipt with the most recent preceding publication, using direct byte equality and revision equality. It does not use the gate's status as ground truth and does not substitute final-state comparison for receipt-time authorization. The journal and receiver are trusted instrumentation, not an independent implementation of the operating system or authority.

Report these counts without dropping denied cases:

- **Invalid receipts / five post-capture transition schedules:** expect 5/5, 2/5, and 0/5 for snapshot, recheck, and coordinated arms. The five include the A-to-B-to-A schedule.
- **Currently authorized receipts / all nine cases:** expect 3/9, 3/9, and 5/9.
- **All receipts / nine cases:** expect 8/9, 5/9, and 5/9. Expected denials are 1, 4, and 4 respectively. There are no automatic read retries.
- **Unchanged controls:** both controls must deliver correctly in every arm, including the empty value.
- **Legitimate early update:** every arm must deliver revision 2 when publication precedes snapshot/capture.
- **Deferred publication attempts:** expect zero, zero, and two. Every requested publication must eventually commit before final observation.
- **Valid at receipt but obsolete at final observation:** expect zero, zero, and two. This distinguishes receipt-time authorization from perpetual freshness or revocation of already delivered information.
- **Identity and errors:** file identities must remain stable in all 27 records. Setup, capture, publication, callback, oracle, and coordination errors remain separate from denials.

These expectations are hypotheses, not measured outcomes. Preserve disagreements before revisions. The content-equality-only oracle would accept the A-to-B-to-A payload, but the chosen revision-specific oracle must reject it. Report this semantic choice rather than calling identical bytes intrinsically unsafe.

## Evidence and limits

Save the complete journal and per-case outcomes, source/task hashes, base/freeze commits, environment, command, and full test output. Require one row per declared case/arm. Recount receipt outcomes from the recorded journal without using the live gate. Preserve inspection and candidate metadata even when release is denied. A clean runner exit is separate from passing scientific criteria.

Only trusted publishers participate in the lock protocol. Uncooperative writers, cross-process/distributed coordination, crash recovery, authenticated policy distribution, authority rollback, streaming release, long-running consumers, latency/fairness/starvation, and live agents are outside the claim. The sink must be short, trusted, and non-reentrant; it must not synchronously call authority methods while holding the lock. Holding the lock can delay updates and revocations. Content can become obsolete immediately after receipt.

## Technical basis

- Python documentation, [lock objects](https://docs.python.org/3/library/threading.html#lock-objects): mutual exclusion and nonblocking acquisition.
- Maurice P. Herlihy and Jeannette M. Wing, [Linearizability: A Correctness Condition for Concurrent Objects](https://www.cs.cmu.edu/~wing/publications/HerlihyWing90.pdf), ACM TOPLAS 12(3), July 1990, pp. 463–492: reasoning about operations through an explicit point of effect and ordered histories.

Sources consulted 2026-10-27 (Asia/Seoul). The study uses established synchronization ideas and a receipt-time invariant. It does not claim a general linearizability proof or a new concurrency primitive.
