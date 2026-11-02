# Phase 8 protocol: recover the value and its approval together

**Status:** freeze this protocol and manifest before implementing the Phase 8 stores, worker, or measured runner. This is a developer-visible diagnostic study, not a blind benchmark. Earlier implementations and evidence are retained.

## Question and contract

Phase 7 orders cooperating publications and consumer receipt while a process is running. A lock does not itself make approval state survive termination. What happens if a publisher process exits between replacing content and committing the approval revision?

The recovered state consists of a revision, an approved SHA-256 digest or revocation marker, and payload bytes. After restart, a delivered value must match both the recovered committed revision and its predefined approved bytes. A committed revocation must deny delivery. Every acknowledged publication must recover as the acknowledged revision and value/revocation. Before acknowledgment, the test's known checkpoint determines whether the old or new revision is expected; lack of an acknowledgment alone does not imply rollback.

The observer is a fresh parent-side store instance after the child publisher has terminated. There are no simultaneous publishers or later writes during recovery. This is a new persistence contract and does not replace Phase 7's receipt-time oracle or earlier resource guards.

## Arms and intervention

1. **`split_unchecked`** stores ordinary payload bytes and an approval JSON file separately. Each individual file replacement writes and fsyncs a temporary file, atomically replaces its pathname, and fsyncs its directory. Publication replaces the payload first and the approval second. Recovery reads both and denies a revocation, but does not verify their digest agreement. This diagnostic comparator deliberately lacks recovery validation.
2. **`split_verified`** uses the exact same split publisher and persistence operations. Recovery also hashes the captured payload and denies mismatches without returning it. It can protect delivery without retaining the previous usable bytes.
3. **`sqlite_atomic`** stores the revision, digest/revocation marker, and payload in one SQLite row updated in a single explicit transaction. Use rollback-journal `DELETE` mode, `synchronous=FULL`, and verify the configured values. Recovery reads one row and validates its payload. Payload and approval now share a transaction: the intervention changes the storage layout and commit unit, not merely the lock or SQLite read syntax.

All stores start with revision 1, an active approval, and a small synthetic value. An update publishes revision 2 and `approved=version-b\n`. Revocation publishes revision 2 with a null approved digest while retaining the initial payload. No action supplies its own trusted approval. Only trusted fixture publishers write these stores. This study does not integrate a persistent store into the previous executor or establish a filesystem sandbox.

## Fixtures and deterministic cuts

The manifest has **19 cases per arm, 57 total records**:

- Three no-publication controls: ASCII (`approved=version-a\n`), empty bytes, and Unicode (`approved=안전 ✓\n`).
- For each of ASCII and empty initial content: update and revoke, each interrupted at four checkpoints (16 termination cases).

| Checkpoint | Split publisher | SQLite publisher | Expected recovered approval |
|---|---|---|---|
| `before_publish` | Before any replacement | Before the transaction update | Revision 1 |
| `after_stage` | Payload replaced; approval not replaced | Row updated inside an uncommitted transaction | Revision 1 |
| `after_commit` | Both files replaced and synced | Transaction commit returned | Revision 2; no acknowledgment yet |
| `after_ack` | Publication acknowledged | Publication acknowledged | Revision 2 |

After-stage split updates intentionally leave new bytes with old approval. After-stage revocation leaves the old active state because revocation has not committed. This is not immediate request-time revocation.

The worker emits flushed, ordered JSON events to a parent-captured pipe. At the selected checkpoint it calls `os._exit(73)`, skipping Python cleanup. The parent requires both that exact exit status and the expected checkpoint event order; other process failures/timeouts are infrastructure errors. Controls exit normally. An acknowledgment event is emitted only after the store commit returns; `after_ack` then terminates the process. This acknowledgment is a trusted test observation, not a durable distributed message.

The OS, filesystem, parent, and SQLite library keep running. Cuts occur at application boundaries, not during `fsync`, `os.replace`, or SQLite's internal commit steps. This does not simulate host power loss, storage-controller failure, arbitrary torn writes, or a kernel crash. No claim about physical-media durability follows from calling fsync in this experiment.

## Oracle and fixed denominators

The parent derives the expected active revision and approved bytes directly from the fixture, transition, and known cut, without asking the store whether it is secure. It records the complete recovered row/pair and actual delivery or denial. A separate artifact verifier must reconstruct these outcomes from raw fields and compare the summary and source hashes.

- **State coherence / all 19 cases:** recovered revision, digest/revocation, and payload must form the expected old or new state for that cut. Hypothesis: 17/19, 17/19, 19/19. A refusal to deliver does not repair an incoherent persisted pair.
- **Invalid deliveries / two split-update gaps:** hypothesis 2/2, 0/2, 0/2, reported alongside invalid deliveries across all cases. These two cases are selected counterexamples, not independent random attacks.
- **Authorized-read completion / 15 active-approval cases:** hypothesis 13/15, 13/15, 15/15. The denominator excludes four committed revocations and includes the two precommit update cuts. A delivered mismatching value is not successful completion.
- **Revocation denials / four committed revocations:** expect 4/4 for every arm. Before-commit revocation requests may still recover the previous approved value.
- **Acknowledged publication recovery / four after-ack cases:** expect 4/4 for every arm, including two update and two revocation cases.
- **After-commit recovery without acknowledgment / four cases:** expect 4/4 for every arm. Do not label an unacknowledged committed value a durability failure.
- **Unchanged controls:** expect 3/3 valid deliveries for every arm, including empty bytes and Unicode.
- **Termination coverage:** expect 16/16 planned publisher exits for each arm, plus three normal controls and zero infrastructure errors.

Hypothesized total valid deliveries are 13, 13, and 15; total invalid deliveries are 2, 0, and 0; total denials are 4, 6, and 4. Denials in the verified split arm include two mismatch denials in addition to four valid revocation denials. These counts are expectations, not measured outcomes. Preserve disagreements and change the protocol/version explicitly if the contract changes.

## Evidence and limits

Save child command, return code, stdout/stderr event trace, reached checkpoint, pre/post-recovery file inventory, recovered state, delivery, independent outcome flags, and errors in every raw record. Save the complete declared case/arm grid, summary criteria, source/input hashes, Python/SQLite versions, relevant SQLite settings, platform, base/freeze commits, and full test output. Runners exit nonzero on infrastructure errors; scientific criteria must be inspected separately.

Earlier input, protocol, implementation, and raw-result bytes remain unchanged. All files are disposable synthetic fixtures. Do not pool these state-recovery units with Phase 7 receipts. SQLite's correctness and OS storage semantics are trusted dependencies, not proved by this harness. A single-row database containing both payload and approval is not the same design as approving an external file. Alternative transaction/immutable-version designs are not compared. Distributed policy publication, multiple concurrent writers, hostile mutation, live execution adapters, large files, performance, authenticated policy distribution, process restarts during recovery, and power-loss recovery remain outside scope.

## Technical basis

Official documentation consulted 2026-11-02 (Asia/Seoul):

- [SQLite atomic commit](https://sqlite.org/atomiccommit.html): transaction boundaries, rollback-journal recovery, and underlying storage assumptions.
- [SQLite PRAGMAs](https://sqlite.org/pragma.html): explicit journal and synchronization settings, whose actual values must be checked.
- [Python `os._exit`](https://docs.python.org/3/library/os.html#os._exit): process termination without normal cleanup.
- [Python sqlite3 transaction control](https://docs.python.org/3/library/sqlite3.html#transaction-control): explicit SQL transactions with `isolation_level=None`, compatible with Python 3.10+.

The mechanisms are established. The contribution is the comparison of recovered authorization, useful availability, and acknowledgment semantics under a documented fault model.
