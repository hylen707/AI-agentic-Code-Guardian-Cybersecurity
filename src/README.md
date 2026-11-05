# Source guide

The source directory contains resource-authorization mechanisms, version-specific readers, revision ordering, persistent publication, request-retry, epoch-retirement, and overlapping-admission prototypes. Earlier implementations remain unchanged so their measured outcomes can be reproduced.

| Module | What it authorizes | How to evaluate it |
|---|---|---|
| `codeguardian.py` | Operation and path spelling | Policy datasets and paired replay |
| `executor_gate.py` | Prepared resolved pathname and content | Three-arm fixed-topology comparison |
| `identity_gate.py` | Prepared path plus current file identity | Hardlink comparison and replacement study |
| `descriptor_executor.py` | Held regular-file descriptor for read/write | Deterministic replacement comparison |
| `verified_content_reader.py` | Captured UTF-8 value matching a trusted version digest | Same-inode content mutation comparison |

The first three return a policy decision. The descriptor executor owns open, authorization, content I/O, and close to preserve the binding it checks. It opens without truncation, checks `fstat`, and uses the same descriptor after approval. It can open a protected object for metadata inspection before denying content I/O; it does not enforce a no-open policy.

The content reader composes that executor without changing it. It captures once, validates the captured value against an owner-configured digest, and returns that same value. A failed check returns no payload, although inspection reads have already occurred. A successful value may be stale relative to the live file. Actions cannot select their own approved digest.

## Local validation

From the repository root:

```bash
python -m unittest discover -s tests -v
```

To classify an action without executing it:

```bash
echo '{"operation":"read","path":"workspace/notes.txt"}' | python src/codeguardian.py
```

Use the [experiment guide](../experiments/README.md) for measured comparisons. The current code uses the Python standard library; the descriptor study is evaluated on Linux with hardlinks and symlinks. These modules assume trusted fixture preparation and are not a general sandbox or a live-agent integration. See the [architecture](../docs/ARCHITECTURE.md) for trust boundaries and the [research statement](../docs/RESEARCH_STATEMENT.md) for the argument.

## Revision-aware receipt

`revision_authority.py` adds one-resource approval snapshots, monotonic updates/revocation, separate checking, and coordinated release to a trusted in-process sink. It composes the existing captured-value reader in the experiment harness; it does not change earlier implementations. Busy publications require caller retries. See [Phase 7 findings](../docs/REVISION_FINDINGS.md).

## Persistent publication stores

`publication_store.py` contains split-file and single-row SQLite stores for the Phase 8 fixture experiment. Individual split replacements use file and directory fsync; the SQLite store verifies rollback-journal `DELETE` mode and `synchronous=FULL`. Both capture a recovered state before delivery, and the verified interface returns exactly the captured bytes checked. A diagnostic unchecked arm omits that digest check.

The worker terminates at declared boundaries without normal cleanup. These stores are independent from the earlier execution gate; they do not provide general filesystem confinement, distributed publication, or power-loss validation. See the [recovery findings](../docs/RECOVERY_FINDINGS.md).

## Request identity and retry receipts

`retry_store.py` reuses the SQLite store's checked connection settings and recovered-state reader. Every publication commits state and an observer effect row together. The three arms omit request deduplication, record a receipt in a separate transaction, or include it in that same transaction. Keyed requests bind ID, operation, and exact bytes; changed intent conflicts, a new ID creates a new revision, and a retry returns the original receipt without restoring its old state.

These are trusted sequential fixture stores with indefinite receipt retention. They do not authenticate request IDs or coordinate an external side effect. The recorded Phase 9 suite passed 141 tests. See the [retry findings](../docs/RETRY_FINDINGS.md) and [experiment guide](../experiments/README.md).

## Epoch retirement

`retirement_store.py` adds a trusted monotonic active epoch and composite `(epoch, request_id)` receipts. Publication still commits state, effect, and receipt together. Four arms retain history, forget without a lower-epoch check, delete before committing the fence, or couple deletion and fence. A retained old receipt can be replayed; a compacted closed epoch must reject without restoring its old effect. A new epoch intentionally denotes a new request namespace.

This is a sequential logical cutoff with no timer or caller authentication. Old unseen work is also rejected. Logical receipt counts do not measure physical reclamation, and observer history remains retained. The recorded Phase 10 suite passed 176 tests. See the [retirement findings](../docs/RETIREMENT_FINDINGS.md) and [reproduction guide](../experiments/README.md).

## Overlapping epoch admission

`overlap_store.py` compares a cached check, a separate final read, and admission held inside `BEGIN IMMEDIATE` through publication. The state, effect, receipt, and commit witness share the write transaction. The witness records the epoch actually observed there; it lets the oracle distinguish a late write from a valid earlier commit even if the response comes after retirement.

The separate retirement child uses a checked zero busy timeout and exact numeric SQLite code 5 for deferral. The pipe controller retries after the publisher releases its transaction. This is a fixed two-role research harness, with no many-writer fairness or latency claim. The current full suite passes 209 tests and requires Python 3.11+ on Linux. See the [overlap findings](../docs/OVERLAP_FINDINGS.md) and [experiment guide](../experiments/README.md).
