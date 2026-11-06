# Phase 14 findings: compact historical authority must survive migration

**Status:** completed 2026-11-06 (Asia/Seoul). Twenty-six developer-visible cases across four modes produced 104 records. The protocol and manifest were [committed before implementation](https://github.com/hylen707/AI-agentic-Code-Guardian-Cybersecurity/commit/89902786509e97cfe8d4f24f02cde0457acda0e8). Earlier source, frozen designs, inputs and measured artifacts preserve their bytes.

## Result

A typed receipt summary can preserve the selected original replay/conflict outcomes after old request payload BLOBs are removed, under a SHA-256 comparison assumption. Its migration must preserve the source authority through interruption. Retained full and atomic-summary modes return all twenty original replays. Drop and split modes each return twelve, but lose evidence at different boundaries. Split migration loses all eight replies after its committed cleanup or uncommitted summary insertion; atomic migration recovers the old full receipts at those cuts.

| Outcome and denominator | Retain full | Drop receipts | Split summary | Atomic summary |
|---|---:|---:|---:|---:|
| Supported original replays / 20 repeats | 20/20 | 12/20 | 12/20 | 20/20 |
| Supported changed-intent conflicts / 4 | 4/4 | 0/4 | 4/4 | 4/4 |
| Unavailable outcomes / 24 known follow-ups | 0 | 12 | 8 | 0 |
| Original replies in cleanup/summary gaps / 8 | 8/8 | 8/8 | 0/8 | 8/8 |
| Supported completed known outcomes / 12 | 12/12 | 0/12 | 12/12 | 12/12 |
| Known requests without another effect / 24 | 24/24 | 24/24 | 24/24 | 24/24 |
| Current policy preserved / 25 non-new-epoch cases | 25/25 | 25/25 | 25/25 | 25/25 |
| Correct new-epoch ID reuse / 1 | 1/1 | 1/1 | 1/1 | 1/1 |
| Unseen old request refused / 1 | 1/1 | 1/1 | 1/1 | 1/1 |
| Old full rows across 14 completed captures | 28 | 0 | 0 | 0 |
| Compact rows across 14 completed captures | 0 | 0 | 28 | 28 |
| Completed captures without old receipt payload rows / 14 | 0/14 | 14/14 | 14/14 | 14/14 |
| Recovered epoch 2 cases | 14 | 14 | 22 | 14 |
| Recovered epoch 1 cases | 12 | 12 | 4 | 12 |
| Exact recovery layouts / 26 | 26/26 | 26/26 | 26/26 | 26/26 |
| Intrinsically coherent final states / 26 | 26/26 | 26/26 | 26/26 | 26/26 |
| Declared child exits / normal completions | 16 / 10 | 16 / 10 | 16 / 10 | 16 / 10 |
| Unsupported or fabricated historical responses | 0 | 0 | 0 | 0 |
| Unexpected infrastructure errors | 0 | 0 | 0 | 0 |

The denominator groups overlap. Twenty repeats include four value/operation types and five cuts. Four changed-intent controls join those repeats in the 24 known-original cases. Fourteen completed captures include twelve known originals and the two independent namespace controls. Counts describe fixed histories, not production probabilities or a pooled security score.

## What the compact record retains

The full record binds epoch, ID, operation, original payload, original revision and approval digest. The compact record keeps **epoch, ID, operation, payload SHA-256 and original revision**, with no payload column. For this publication fixture an update's input digest is also its original approval digest, so the response can reuse that field. Revocation has an explicit operation and null digest. Empty update has its own update tag and SHA-256 of empty bytes. NFC and NFD encodings remain distinct; no normalization is applied.

This does not prove a universal minimum schema. Other APIs may need separate input and result metadata. Full receipts compare retained bytes; summaries compare a typed fingerprint under collision/second-preimage resistance and trusted storage assumptions. A unit diagnostic substitutes a matching comparison digest for different bytes, demonstrating how a false match would break that assumption. It is not a real SHA-256 collision and does not enter the measurement grid. Hashes neither authenticate callers nor encrypt retained history.

Application resolution reads full or compact authority, never the effect observer. A missing closed-epoch record returns unavailable with no commitment fields. A coincidentally correct historical guess without such authority is counted as unsupported. Historical replay returns revision 2 while current delivery continues to enforce the opposing revision-3 policy.

## Equal totals conceal different commit boundaries

Each fixture commits `original` at epoch 1/revision 2, then an opposing `later-policy` at revision 3. After an update the later policy revokes; after an original revocation the later policy approves C. Retirement targets epoch 2. The child visits four checkpoints and either exits at a declared cut or completes normally. The parent then reopens before one follow-up.

| Recovery position | Retain full | Drop receipts | Split summary | Atomic summary |
|---|---|---|---|---|
| Before change | Epoch 1, full | Epoch 1, full | Epoch 1, full | Epoch 1, full |
| After cleanup / after summary, before final commit | Epoch 1, full | Epoch 1, full | Epoch 2, neither | Epoch 1, full |
| After completed retirement | Epoch 2, full | Epoch 2, neither | Epoch 2, compact | Epoch 2, compact |

The drop transaction rolls back at the two middle cuts, recovering full records. Its eight repeated-request losses happen after completed deletion; four completed changed-intent controls also become unavailable. Split migration first commits the fence and full-record deletion, then inserts its process-memory summaries in a second transaction. Exiting after cleanup, or before that second commit, recovers closure without the original evidence in eight repeated cases. Completed split migration classifies all four parameter changes correctly.

Atomic migration prepares source receipts under its write transaction, then couples fence, deletion and summary insertion in one commit. At every selected precommit exit it recovers full authority; after completion it recovers compact authority. The result concerns these application-level cuts and trusted SQLite recovery, not host power loss or failure inside commit. Retrying an evidence-losing completed split target cannot reconstruct missing records from the observer.

## Mutation safety is separate from response availability

All four modes prevent an extra effect in all 24 known-original follow-ups. Current publication remains unchanged in all 25 cases that do not introduce a new epoch. The legitimate epoch-2 request reuses the literal ID, commits revision 4 and remains separate from the old namespace. The unseen old ID is refused without an effect. Thus missing original outcomes can coexist with coherent current policy and correct duplicate prevention.

The summary representation preserves one keyed record per old request. Completed summary captures have two compact rows and no old full request payload rows, while retaining mode has two full rows. This is a logical representation count. Current publication still contains a payload, and other evidence may contain those same bytes. No physical reclamation, secure erasure, privacy, total-database bound, memory saving or performance result is claimed.

## Validation and provenance

All **316 tests passed**, including **33 new tests**. Tests cover compact historical responses, operation/Unicode distinctions, long payload removal from the receipt table, surviving publication bytes, rollback of atomic migration, permanent split gaps, failed summary/namespace writes, postcommit exceptions, namespace reuse, successive compaction and conflicting full/compact authority. Evidence tests reject wrong exit codes, absent markers, stderr failures, forged fingerprints, invented historical replies, unscheduled authority rewrites and missing/repeated cases. A structurally valid unexpected loss layout remains a failed scientific verdict, rather than being called successful protection.

The independent verifier imports no store, worker or measured controller. Using only the stdlib, it reconstructs all 104 records, child traces, full/compact authority, response support, current delivery, recovery layouts and counters. It matches **all ten criteria**, checks the input and **nine source hashes**, and confirms **64 declared exit prefixes plus 40 normal child completions**, with zero unexpected infrastructure errors. The expected unavailable outcomes remain visible.

The run used Python **3.12.14**, SQLite **3.53.1**, Linux, rollback-journal `DELETE` and `synchronous=FULL`. The current full suite uses Python 3.11+ on Linux. `os._exit(73)` bypasses normal cleanup while parent, filesystem and kernel survive. Random failures and timeouts cannot qualify as the intended cut. Unique artifact names and exclusive creation preserve earlier output. Supplied commit labels and trusted local observers are not external attestation.

## Evidence and reproduction

- [Frozen protocol](COMPACTION_PROTOCOL.md), [26-case manifest](../experiments/tasks/compaction-eval-v1/tasks.json), [freeze commit](https://github.com/hylen707/AI-agentic-Code-Guardian-Cybersecurity/commit/89902786509e97cfe8d4f24f02cde0457acda0e8).
- [104 raw child/recovery/follow-up records](../experiments/results/2026-11-06T00-57-33-721168Z-compaction-v1.jsonl).
- [Summary, environment, command and hashes](../experiments/results/2026-11-06T00-57-33-721168Z-compaction-v1-summary.json).
- [Independent verification](../experiments/results/2026-11-06T00-57-33-721168Z-compaction-v1-verification.json).
- [Complete test transcript](../experiments/results/2026-11-06T00-57-33-721168Z-compaction-v1-unit-tests.txt) and [experiment console](../experiments/results/2026-11-06T00-57-33-721168Z-compaction-v1-console.txt).
- [Store](../src/compaction_store.py), [worker](../experiments/compaction_worker.py), [controller](../experiments/run_compaction_comparison.py), [verifier](../experiments/verify_compaction_results.py), [tests](../tests/test_compaction_store.py).

```bash
python -m unittest discover -s tests -v
python experiments/run_compaction_comparison.py --dataset experiments/tasks/compaction-eval-v1/tasks.json --base-commit "$(git rev-parse HEAD)" --freeze-commit 89902786509e97cfe8d4f24f02cde0457acda0e8
python experiments/verify_compaction_results.py --summary experiments/results/2026-11-06T00-57-33-721168Z-compaction-v1-summary.json --dataset experiments/tasks/compaction-eval-v1/tasks.json
```

For fresh measurements, substitute the printed summary filename. Base/freeze arguments do not check out or verify revisions; recorded hashes identify actual local source bytes. A clean controller exit means no unexpected infrastructure error. The independent verifier additionally fails on unmet scientific criteria and requires matching source versions for historical verification. [Experiment guide](../experiments/README.md#phase-14-compact-receipts-and-migration-recovery).

## Limits and next question

The experiment uses trusted logical epochs, one sequential migration child and one follow-up after it stops. It does not test concurrent publishers/compactors, arbitrary caller populations, authentication, timer expiry, repeated recovery failure, WAL, network partitions, external effects, failures inside storage calls or host power loss. Digest-based equivalence is conditional, and retained summaries still grow with request count.

The next question is publication overlapping migration source selection. A final transaction cannot repair a source set captured before an intervening publication. A new live-process protocol must locate that source read relative to the fence and deletion before extending this migration claim.

## Technical basis

The [protocol's primary references](COMPACTION_PROTOCOL.md#technical-basis) document SQLite transactions, Python SHA-256, NIST hash assumptions and intent-bound idempotent replies. Those established mechanisms motivate the comparison; the retained records above support its empirical counts.
