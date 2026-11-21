# Phase 21: deleting recovery results must not reopen their request space

[Documentation index](README.md) · [Frozen protocol](RETENTION_PROTOCOL.md) · [Evidence map](EVIDENCE.md)

## Question and result

Phase 20 preserves the original outcome of an interrupted recovery request by retaining its receipt. That contract requires a retention boundary: removing the result must not let an old logical request acquire authority again. Phase 21 introduces a separate recovery epoch and a capacity of two results per epoch.

Across **32 cases per arm, 96 records**, committed grants under a retired recovery epoch are **34 → 4 → 0** for erase-only, cached admission and transactional admission. Both guarded arms correctly reject all **376/376** post-retirement probes, yet cached admission still grants authority four times to requests admitted before retirement and committed afterward. Quiet retry correctness therefore misses the in-flight boundary. The transactional arm retains at most two result rows, rejects retired requests without state changes, and preserves current results and publication history.

All **554 tests** pass, including 37 added regressions. Independent reconstruction passes all six criteria. Every arm closes all 32 targets; closure and total grant counts do not establish valid admission.

## Contract: deliberate unavailability and bounded results

Requests use the exact `(recovery_epoch, request_id, expected_token, owner)` tuple. A durable singleton names the current recovery epoch. Trusted advancement compares an expected epoch, increments it and removes older result rows in one transaction. The recovery epoch is independent of the publication target epoch and the authority token.

Only current-epoch requests are admissible. A retired epoch returns `retired`, including for an ID never used; a later epoch returns `future_epoch`. Neither response binds an ID or issues authority. Within the current epoch, first durable decisions, including conflict or target-completed outcomes, bind ID, inputs and historical result. Same intent replays; changed intent conflicts. Existing-result lookup precedes the two-row capacity check. An unrecorded ID at capacity receives `capacity_exhausted` without a decision or grant.

Retirement intentionally ends result retrieval. This refines Phase 20's retained-result contract; it does not claim that deleted results remain available. The same text ID in a new recovery epoch is a distinct request. Historical result fields never restore an old authority token. A lost advancement reply is answered by a later epoch conflict/current epoch, not by a promise to reproduce the original advancement result.

The bound concerns **logical application result rows** plus one epoch counter. Evaluation retains append-only grants, decisions and retirement witnesses. Those observer records never admit requests or answer the API. Neither total database size nor reclaimed SQLite file bytes are bounded by this result.

## Prospective design and controls

The [protocol](RETENTION_PROTOCOL.md) and [manifest](../experiments/tasks/retention-eval-v1/tasks.json) were frozen at [`81dbcb2`](https://github.com/hylen707/AI-agentic-Code-Guardian-Cybersecurity/commit/81dbcb23b64ed3001abb4f68057d7cfe9a64a943), whose parent is Phase 20 main `fa5d7075f1896069672e24e6ca116de0a90c0666`, before the new mechanism and harness were implemented. Inherited publication, fencing and recovery-result sources remain byte-identical to that base.

| Arm | Admission treatment | Shared behavior |
|---|---|---|
| `erase_only` | Admits old epochs after deletion; rejects future epochs. | Atomic advancement/deletion; namespaced atomic decision/result storage; capacity two per epoch; unchanged transactional migration fence. |
| `cached_floor` | Checks the epoch in a separate read snapshot before acquiring the writer. | Same. |
| `atomic_floor` | Checks the epoch while holding the writer through result lookup, decision, grant and result commit. | Same. |

Sixteen histories cross ASCII/revoked and Unicode/empty publication fixtures. They exercise lost advancement/recovery replies, rollback, in-flight admission, writer contention, repeated epochs, capacity, future epochs, closed targets and conflicts that later become applicable. Process generation, role, exact typed inputs and checkpoint are bound to each live continuation or marked code-73 exit. Exits occur at application boundaries; the parent and OS survive.

After each frozen history, one additional advancement retires its current results. Probes cover actual original decisions, changed intent carrying current authority, and a never-used old ID. Two fresh current requests then fill the new epoch; original, changed and overflow queries repeat before and after target closure. Original and changed publication intents provide independent preservation controls.

## Independently recounted outcomes

| Measure, per arm | Erase only | Cached floor | Atomic floor |
|---|---:|---:|---:|
| Cases / records | 32 | 32 | 32 |
| Decisions committed in a retired epoch | 130 | 4 | **0** |
| Grants committed in a retired epoch | 34 | 4 | **0** |
| Rebound logical IDs: later decision under the same epoch/ID | 98 | 2 | **0** |
| Correct retired queries / actual queries | 0/400 | 376/376 | **376/376** |
| Retired queries changing durable state | 108 | 0 | **0** |
| Maximum observed live result rows | 10 | 2 | **2** |
| Snapshots exceeding two rows / observed snapshots | 756/1,170 | 0/1,146 | **0/1,146** |
| Snapshots containing retired results | 952 | 16 | **0** |
| Fresh current requests / failures | 64 / 0 | 64 / 0 | 64 / **0** |
| Current result/conflict/overflow queries / failures | 320 / 0 | 320 / 0 | 320 / **0** |
| Explicit overflow queries / failures | 64 / 0 | 64 / 0 | 64 / **0** |
| Busy responses | 6 | 6 | 10 |
| Lifetime grants, including 32 initial grants | 188 | 166 | 166 |
| Committed epoch advancements | 68 | 68 | 68 |
| Target closure | 32/32 | 32/32 | **32/32** |
| Publication original replay / changed conflict | 64/64 each | 64/64 each | **64/64 each** |
| Infrastructure / caller / transport-response errors | 0 / 0 / 0 | 0 / 0 / 0 | **0 / 0 / 0** |

Retired-query denominators derive from first decisions actually committed during the frozen histories, plus one never-used ID per case, queried twice. Erase-only has 84 original epoch/ID instances; the guarded arms have 78. Extra weak-arm decisions change that denominator; no intended ID is silently counted as a committed original. Snapshot counts are repeated coherent observations, not independent cases or race probabilities. The maximum is a maximum across records, not a sum of case maxima.

Cached and atomic admission have the same lifetime grant count and the same successful retired-query totals. They differ in which request epoch was allowed to obtain those grants. Cached admission's observed two-row maximum also coexists with sixteen snapshots containing retired results. Neither aggregate is a substitute for admission-time validity.

## Counterexamples and the intervention

**Unused request crosses retirement.** In `stale_admission_unused`, A accepts recovery epoch 1 and pauses. Cached admission releases its read snapshot; B advances to 2 and deletes old results. A acquires the writer and grants token 2 under epoch 1. Its observer witness records active recovery epoch 2 at commit. Transactional admission instead holds the writer while paused, so B receives busy. A commits while epoch 1 remains current; B's scheduled retry then retires it.

**A deleted conflict can become a grant.** In `conflict_retirement`, an ID first asks for token 2 while token 1 is current and records a conflict. Another ID legitimately grants token 2. After deletion, erase-only re-evaluates the first ID and grants token 3. The first decision's identity has been reopened. In the strong arm, the old epoch is rejected before lookup or target-completed handling; a new epoch is required for a new intention.

**Late delivery is not a late decision.** In `reply_after_retirement`, A commits a valid grant/result in epoch 1 and pauses after commit. B retires epoch 1; A then returns its already-committed result. All arms may deliver that historical answer. It does not create another decision or restore authority, and the verifier does not misclassify it as a retired grant.

The row-bound argument follows the write boundary. Initially no result rows exist. Transactional admission inserts only in the current recovery epoch and only when its count is below two. Advancement serializes on the same writer, monotonically increments the epoch and deletes older results. Lookup/denial creates no row. Thus the specified API preserves current-epoch membership and the two-row bound; the tests and frozen histories check this implementation within their stated scope. The four additional busy responses in the strong arm are the visible ordering cost. They are deferred operations, not permanent advancement failures.

## Verification and reproduction

The retained JSONL is losslessly gzip-compressed. Metadata hashes the compressed archive; verification decompresses it before reconstructing every record. Fresh runs accept either `.jsonl` or `.jsonl.gz` output paths.

The independent stdlib verifier imports no mechanism or runner. It reconstructs writer ownership, separate versus transactional admission, lookup/capacity, decision/result commits, advancement/deletion, rollback, live bindings and every boundary snapshot. It checks source/raw/manifest hashes and the prospective Git freeze. Mutations cover booleans on integer wire fields, changed roles/order, missing markers, altered grants/results/fences, missing probes and self-consistently recorded wrong replies. Such replies remain outcome failures even when raw and decoded records agree.

The retained run uses Python 3.12.14 on Linux. There are **516 child processes**, **30 marked exits**, **60 live barriers** and **2,400 parent API queries**, including the final advancement of each fixture. All 486 normal child terminations are observed; there are no infrastructure errors. Phase 18–20 retained evidence also verifies unchanged. The retained full-suite output reports 554 passing tests and exit status zero.

```bash
python -m unittest discover -s tests -v
python experiments/run_retention_comparison.py \
  --output /tmp/codeguardian-retention-v1.jsonl.gz \
  --base-commit fa5d7075f1896069672e24e6ca116de0a90c0666 \
  --freeze-commit 81dbcb23b64ed3001abb4f68057d7cfe9a64a943
python experiments/verify_retention_results.py /tmp/codeguardian-retention-v1.metadata.json
```

| Artifact | Content |
|---|---|
| [Raw histories](../experiments/results/2026-11-21-retention-v1.jsonl.gz) | All 96 records, exact commands, raw/decoded streams, exits, snapshots and probes. |
| [Metadata](../experiments/results/2026-11-21-retention-v1.metadata.json) | Base/freeze identities, source/raw hashes and controller counts. |
| [Independent verification](../experiments/results/2026-11-21-retention-v1-verification.json) | Reconstructed counts and six criteria. |
| [Full test output](../experiments/results/2026-11-21-retention-v1-tests.txt) | All 554 tests and captured console output. |
| [Execution record](../experiments/results/2026-11-21-retention-v1-execution.json) | Commands, observed exit codes and elapsed times; temporary verification outputs are identified as such. |

## Limits and next boundary

This is one fixed target, trusted explicit recovery/advancement, one reusable authority slot, capacity two, at most two overlapping children and controller-granted writer order. It establishes neither authentication, arbitrary-history correctness, fairness, automatic failure detection, host/power-loss durability, storage-byte reclamation nor a lifetime-work bound. A hostile administrator could retire useful results; authorization of that administrator is outside the mechanism. Reference reconstruction may share conceptual assumptions with the implementation.

The next boundary is systematic exploration of a small state space: generate permitted request/retirement interleavings and check current-result membership, admission validity and reply linearization beyond the hand-written histories. This would broaden schedule coverage, not create a general fairness or production-security proof.
