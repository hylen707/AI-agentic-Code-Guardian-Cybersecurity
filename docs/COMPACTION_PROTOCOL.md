# Phase 14 protocol: compact historical receipts and interrupted migration

**Status:** commit this protocol and the 26-case manifest before implementing the Phase 14 store, worker, controller, tests or verifier. Cases are developer-visible. Earlier implementations, frozen designs, inputs and measured artifacts retain their bytes.

## Question and retained evidence

Phase 13 prevents another old effect after receipt loss, but may lose its original response. Can a compact authoritative receipt preserve replay/conflict semantics after removing the old request payload BLOB, including interruption during migration?

The original request is scoped by `(epoch, request_id)` and binds operation and exact bytes. An identical known request should return `replayed` with its original revision/approval digest; changed intent should return `conflict` without a commitment. A missing record below the active epoch returns `outcome_unavailable`, without another effect or invented history. This does not imply that the request never committed. A new epoch is a newly authorized namespace even if its literal ID repeats. A previously unseen closed-epoch ID must not execute.

A full receipt contains epoch, ID, operation, payload, revision and approval digest. The compact representation contains **epoch, ID, operation, payload SHA-256 and original revision**, with no payload column. For an update, the payload digest also supplies its original approval digest; for revocation it is null and the approval is null. The explicit operation distinguishes an empty update from revocation. Strings are encoded as UTF-8 and compared without normalization. Application resolution may consult full or compact receipts, never the trusted effect observer.

This changes equality evidence from retained byte comparison to typed digest comparison. Correct equivalence is conditional on SHA-256 collision/second-preimage resistance and trusted stored metadata. The chosen cases do not demonstrate cryptographic security, prove a mathematically minimal schema, or establish equivalence for arbitrary colliding inputs. A regression diagnostic may substitute a deliberately colliding fingerprint to expose this assumption; that is not a SHA-256 attack or part of the measured grid.

## Four modes and migration boundary

All modes use checked SQLite rollback-journal `DELETE` and `synchronous=FULL`. Publication state, effect and full receipt commit together. Retirement targets the next trusted epoch. The migration first prepares the old full receipts in process memory while holding its transaction; this transient copy does not survive a child process exit.

1. **`retain_full`** advances the epoch but keeps old full receipts. It retains the original byte-comparison authority and its payload storage cost.
2. **`drop_receipts`** atomically advances the epoch and deletes old full receipts, with no replacement. The fence prevents re-execution but removes historical-response evidence after completed retirement.
3. **`split_summary`** first commits the epoch advance and full-receipt deletion. It then writes the precomputed compact receipts in a second transaction. A process exit after cleanup, or before the second transaction commits, can lose original outcomes while still preserving the fence and coherent current state.
4. **`atomic_summary`** advances the epoch, deletes old full receipts and inserts their compact replacements in one transaction. Recovery should expose either old full receipts or new summaries, with the fence matching that layout.

Common checkpoints are `before_change`, `after_fence_cleanup`, `after_summary` and `after_commit`, in that order. `retain_full` performs its configured no-deletion action at the cleanup boundary; `drop_receipts` performs no summary insertion. In the split mode only, the first commit precedes `after_fence_cleanup`; its second commit follows `after_summary`. In other modes the sole commit follows `after_summary`. All stages remain explicit in every trace, including configured no-op steps.

The child calls `os._exit(73)` at a selected checkpoint after flushing the exact event prefix. `normal` completes, returns the expected result and exits 0. Unexpected exit codes, timeouts, exceptions, missing markers or malformed traces are infrastructure failures, never successful protection. The parent and kernel survive, then reopen a fresh store and issue the follow-up. No failure is injected inside a storage syscall or SQLite commit.

## Fixture and 26 cases

Every disposable fixture starts at revision 1 with `approved=version-a\n`. Epoch-1 ID `original` commits the case's original intent at revision 2. ID `later-policy` then commits an opposing policy at revision 3: revocation after an update, or `approved=version-c\n` after an original revocation. This ensures that a historical receipt must not restore its old policy as current. Both receipts exist before the child retires to epoch 2.

| Original value | Bytes or operation |
|---|---|
| `ascii` | `approved=version-b\n` |
| `empty` | Empty update, not revocation |
| `unicode` | `approved=안전 ✓\n` |
| `revoke` | Revocation; no incoming bytes |

Twenty same-intent cases form the product of these four original values and five child cuts (`before_change`, `after_fence_cleanup`, `after_summary`, `after_commit`, `normal`). After reopening, the parent repeats epoch-1 ID `original` with the original intent.

Six additional normal-completion controls are separate:

| Scenario | Original intent | Follow-up |
|---|---|---|
| `changed_bytes` | ASCII B | Same old ID with version C |
| `update_to_revoke` | Empty update | Same old ID with revocation |
| `revoke_to_update` | Revocation | Same old ID with empty update |
| `unicode_bytes` | `approved=é\n`, U+00E9 | Same old ID with U+0065 U+0301 encoding |
| `new_epoch` | ASCII B | Epoch 2, literal ID `original`, new version D |
| `unseen_old` | ASCII B | Epoch 1, unseen ID `unseen`, version B |

There are **26 cases × four modes = 104 records**. Each has one retirement child. Sixteen cuts per mode terminate at the declared checkpoint, and ten complete normally: **64 declared child exits plus 40 normal completions**, 104 child invocations total. The follow-up is one direct parent-side store call after the child has stopped; there are no overlapping publishers or scheduling sleeps.

## Recovery layouts and prospective denominators

Before migration, all modes have two epoch-1 full receipts and no summaries. Current publication/effect history must remain unchanged during retirement. The expected recovered namespace and representation are:

| Cut | Retain full | Drop receipts | Split summary | Atomic summary |
|---|---|---|---|---|
| `before_change` | Epoch 1, two full | Epoch 1, two full | Epoch 1, two full | Epoch 1, two full |
| `after_fence_cleanup` | Epoch 1, two full | Epoch 1, two full | Epoch 2, neither representation | Epoch 1, two full |
| `after_summary` | Epoch 1, two full | Epoch 1, two full | Epoch 2, neither representation | Epoch 1, two full |
| `after_commit` / `normal` | Epoch 2, two full | Epoch 2, neither representation | Epoch 2, two summaries | Epoch 2, two summaries |

An exact original outcome requires both correct fields and an authoritative full or compact receipt available at resolution. A coincidentally correct guess from current state or observer history does not qualify. Whole current-state coherence, one request effect, and original-response availability remain separate measures.

Report ten criteria in mode order `retain_full`, `drop_receipts`, `split_summary`, `atomic_summary`:

1. **Mutation safety:** no extra effect in any of 24 known-original follow-ups per mode; preserve revision-3 current policy in all 25 non-new-epoch cases; all 26 final states intrinsically coherent.
2. **Repeated original results / twenty:** correct original replays **20/20, 12/20, 12/20, 20/20**. Unavailable outcomes across 24 known follow-ups are **0, 12, 8, 0**, with no commitment fields or new effect.
3. **Changed intent / four:** supported original parameter conflicts **4/4, 0/4, 4/4, 4/4**. A safe unavailable response is not counted as conflict classification.
4. **Migration gap / eight same-intent cuts after cleanup or summary:** original results remain available **8/8, 8/8, 0/8, 8/8**. Aggregate replay totals alone conceal the different loss windows.
5. **Completed migration representation / fourteen after-commit or normal captures:** retaining mode has two old full receipts each; dropping mode has neither; split and atomic modes have two compact receipts each and no old full receipt payload BLOBs. All compact rows bind the original operation, digest and revision and have no payload column.
6. **Independent intent controls:** the one new-epoch ID reuse commits a legitimate revision 4; the one unseen old ID is refused without an effect, in every mode.
7. **Recovered epoch/layout:** final epochs at 2 are **14, 14, 22, 14**; epochs at 1 are **12, 12, 4, 12**; every recovered layout matches the declared cut. The split gap retains closure while losing the reply evidence.
8. **Completed known-original outcomes / twelve:** supported replay/conflict results after completed retirement are **12/12, 0/12, 12/12, 12/12**.
9. **Fault coverage:** sixteen exact marked exits and ten normal child completions per mode, with all 104 expected commands/return codes/complete stdout/stderr/event prefixes preserved.
10. **Evidence and errors:** zero fabricated or unsupported historical responses, all captures/summary counters consistent, and zero unexpected infrastructure errors. The intentional unavailable results remain negative availability evidence.

The twenty repeated cases, four changed-intent controls, eight migration-gap cases, twelve completed-known cases and fourteen completed captures overlap. They are fixed developer-visible histories, not independent samples or production failure probabilities. Preserve disagreements and unexpected errors rather than converting them into successful denials or editing measured labels.

## Oracle, artifacts and provenance

Save an initial capture, a consistent reopened capture before follow-up, and a final capture. Each reads publication, active epoch, effects, full receipts, compact receipts, summary column schema and actual verified delivery in one read transaction. Count old full receipt rows and their payload bytes separately from compact receipt rows. The oracle reconstructs actual effects and authoritative receipt contents from the fixture and follow-up, then checks response support, current delivery, extra effects and expected recovery layout. A structurally valid but unexpected recovery layout is a failed layout criterion, not evidence of success.

An independent stdlib verifier must reconstruct the fixed grid, all child traces, captures, receipt-supported outcomes, counters and ten criteria without importing stores, worker or measured controller. Save uniquely named raw JSONL, summary/environment/command, console, complete test transcript and independent verification with exclusive creation. Record input hash and nine source hashes: the new store, worker, controller, verifier, tests and this protocol, plus unchanged publication, retry and retirement stores. Base/freeze labels are supplied metadata, not source authentication; hashes identify actual local bytes. A clean runner exit means no unexpected infrastructure error, not success of all scientific criteria. The verifier also fails on unmet criteria.

## Limits and next boundary

The compact representation has bounded digest/operation/revision fields per record, but retains one keyed record per request. This does not bound record count, observer history or total database size. Removing receipt payload BLOBs is not physical disk reclamation, secure erasure or privacy protection; current publication and other evidence may still contain those bytes. No performance or memory benchmark is claimed.

SHA-256 comparison replaces exact retained-byte comparison under a stated cryptographic assumption. Stored fields and epoch assignment are trusted; hashes do not authenticate callers, encrypt content or grant new authority. The parent, OS and filesystem survive selected application-level exits. No concurrent migration/publisher, repeated recovery failure, network, external-service effect, WAL, host power loss or failure inside commit is tested. Retrying a completed but evidence-losing split migration cannot reconstruct vanished receipts from the observer.

## Technical basis

Primary sources consulted 2026-11-06 (Asia/Seoul):

- [SQLite transaction control](https://sqlite.org/lang_transaction.html): transaction scope and rollback/recovery boundaries.
- [Python hashlib](https://docs.python.org/3/library/hashlib.html): SHA-256 over byte strings and digest representation.
- [NIST hash functions](https://csrc.nist.gov/projects/hash-functions): collision and second-preimage resistance are cryptographic assumptions, not mathematical injectivity.
- [Amazon Builders' Library: Making retries safe with idempotent APIs](https://aws.amazon.com/builders-library/making-retries-safe-with-idempotent-APIs/): intent-bound original responses and retention limits.

The mechanisms are established. The contribution is a reproducible comparison of representation, migration atomicity, historical-response availability and preserved current policy.
