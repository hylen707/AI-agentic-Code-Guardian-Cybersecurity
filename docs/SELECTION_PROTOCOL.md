# Phase 15 protocol: complete receipt selection under concurrent publication

**Status:** commit this protocol and the 24-case manifest before implementing the Phase 15 store, worker, controller, tests or verifier. Cases are developer-visible. Earlier implementation, frozen designs, inputs and measured artifacts retain their bytes.

## Question and obligations

Phase 14 migrates a complete source set while holding its writer transaction. What if another publisher commits after a candidate set is read but before an otherwise atomic fence/deletion/summary commit? Atomic output alone cannot establish completeness of an earlier selection.

The new study compares receipt selection scopes while preserving the same typed compact representation. Publication is valid only in the active requested epoch; old requests retain their original epoch/ID/bytes on retry. A committed request should retain an authoritative original replay after migration. A request that never commits before closure may be refused. Those are different outcomes: do not count a refused, never-committed request as lost historical evidence, or count its refusal as useful publication completion. A missing closed-epoch receipt returns `outcome_unavailable` without claiming that no earlier commit occurred. The observer distinguishes these histories only for measurement and must not answer application requests.

Measure three properties separately: publication completion, preservation of receipts for actual committed requests, and current state coherence. A stale migration may preserve both current policy and the fence while deleting a legitimate request's only receipt.

## Four selection modes and shared storage

The unchanged Phase 14 schema stores state, effect history, full receipts, typed `(epoch, ID, operation, payload SHA-256, revision)` summaries and an active epoch. New trusted observer tables record each runtime publication's requested/active epoch with its effect, and each committed migration's target, selected/publication revisions and selected/observed old-receipt counts. These observer writes share their corresponding transaction and never supply application authority.

All modes atomically advance the epoch, delete every old full receipt and insert compact rows from their chosen source. Only source selection/validation differs:

1. **`cached_selection`** reads the full candidate set in a short read transaction, closes it, and reuses it through migration. A new old-epoch receipt committed after that selection can be deleted without a replacement summary.
2. **`separate_refresh`** performs another short read immediately before its final pause, closes it, then uses that refreshed set in a later write transaction. It catches an earlier intervening publication but still has a gap after the refresh.
3. **`transactional_selection`** obtains `BEGIN IMMEDIATE` before initial selection and holds it through migration commit. A concurrent old-epoch publication receives a nonblocking busy result; its same-identity retry after migration is refused because closure won. This preserves committed history by ordering the new work later, at a useful-completion cost.
4. **`validated_selection`** reads outside the writer like the cached mode, then rereads the full source snapshot inside `BEGIN IMMEDIATE` before any migration writes. It compares epoch, current revision and sorted full receipt tuples exactly. On any difference, it rolls back and returns `stale_selection` without changing the fence or authority. The controller retries migration from a fresh selection after the publisher completes. This is exact in-memory source validation, not a second fingerprint-hash assumption.

Every mode observes the actual current source in its write transaction for the migration witness. Weak modes do not use this instrumentation reading as a gate. Only validated selection aborts on a mismatch. The compact receipt still uses typed SHA-256 comparison under Phase 14's collision/second-preimage and trusted-metadata assumptions; no universal minimum schema or cryptographic proof is claimed.

Checked rollback-journal `DELETE`, `synchronous=FULL` and zero busy timeout apply to runtime write probes. Only numeric `SQLITE_BUSY` (5) at the publisher's `BEGIN IMMEDIATE` is a modeled deferral. Other storage errors, migration BEGIN contention, unknown codes, failed processes and invalid traces are infrastructure errors. A modeled busy or stale-selection result exits normally and remains visible. No fault injection or arbitrary busy error is a successful defense outcome.

## Fixture and 24 histories

Each fixture starts at revision 1 with `approved=version-a\n`. Trusted setup approves B under epoch-1 `seed-a` at revision 2, then revokes under `seed-b` at revision 3. The migration targets epoch 2. Runtime publisher ID `inflight` is initially absent. Values are ASCII `approved=version-b\n`, empty update, Unicode `approved=안전 ✓\n`, and revocation. Empty update and revocation remain distinct; no normalization is applied.

| Schedule | Cases per mode | Execution order |
|---|---:|---|
| `after_selection` | 4, all values | Pause migration after its initial selection has been recorded; try the old-epoch publisher; resume migration |
| `after_refresh` | 4, all values | Pause after the selected mode's final selection/refresh; try publisher; resume |
| `before_commit` | 2, ASCII/revocation | Pause with the migration transaction's changes uncommitted; publisher attempts |
| `after_commit` | 2, ASCII/revocation | Pause after migration committed and released its writer; publisher attempts |
| `publisher_first` | 4, all values | Old-epoch publisher completes before migration starts |
| `migration_first` | 2, ASCII/revocation | Migration completes, then old-epoch publisher attempts |
| `current_epoch` | 4, all values | Migration completes, then a new epoch-2 publisher commits |
| `publisher_first_later` | 2, ASCII/revocation | Old-epoch `inflight` commits revision 4, independent epoch-1 key `later` publishes D at revision 5, then migration starts |
| **Total** | **24** | **96 case/mode records** |

The four early and four late selection pauses are the **eight source-gap opportunities** per mode. They are distinct from the before/after-commit controls. There are twelve strict live pipe-barrier pauses per mode, **48 overall**, and twelve nonpaused ordering/current cases per mode. Pause/resume messages bind role and stage; no sleep arranges execution.

An unguarded publisher commits `inflight` at revision 4 while migration is paused. Cached selection omits it in all eight gaps; separate refresh includes it in the four early cases but misses it in the four late cases. Validated selection returns stale in both groups, with epoch 1 and all three full receipts preserved, then a new migration attempt selects all three. Transactional selection makes those eight first publisher attempts busy; after closure each unchanged old-epoch retry is refused without a new effect.

At `before_commit`, every mode holds its writer, producing two busy publisher attempts per mode; unchanged retries after closure are refused. At `after_commit` and `migration_first`, old work is refused immediately. The four new epoch-2 intents are independent authorized work, not relabeled retries. In `publisher_first_later`, the original receipt must return revision 4 while current policy remains D at revision 5.

## Controller, witnesses and exact coverage

Keep every migration attempt and publisher attempt, including their commands, inputs, return codes, complete stdout/stderr, parsed sequenced events and result. Keep the independent later child's trace where applicable. The controller saves a sequenced actor journal, initial capture, any before-migration publication/later capture, pause capture, capture after each migration attempt, final capture before follow-up and a capture after the original request is repeated through the application interface. Every capture reads all tables, current delivery and namespace consistently. A follow-up may not mutate state or historical authority.

Selection events record the source epoch, publication revision and complete typed source identity set. An inside-writer validation event records the actual set and comparison. Migration witnesses identify which set actually committed; publication witnesses identify actual old/current commits. The oracle uses actual durable effects to define committed-history denominators, not mode labels or caller start order.

Expected child invocations in mode order cached, separate, transactional, validated are:

| Role | Cached | Separate | Transactional | Validated |
|---|---:|---:|---:|---:|
| Migration attempts | 24 | 24 | 24 | 32 |
| Main publisher attempts, including busy retries | 26 | 26 | 34 | 26 |
| Independent later publishers | 2 | 2 | 2 | 2 |
| **Normal child completions** | **52** | **52** | **60** | **60** |

All **224 children** exit normally; modeled busy and stale-selection results are not infrastructure failures. At most two children are live at a time. The parent-side final replay occurs after all child work and must have no effect.

## Ten prospective criteria

Report the following separately, in mode order `cached_selection`, `separate_refresh`, `transactional_selection`, `validated_selection`:

1. **Current state and closure:** all 24 final epochs per mode are 2, all old full receipt rows are absent, current state/delivery reflects the actual durable publication history, and all final content/approval pairs are coherent. These properties alone do not establish complete history.
2. **Eight source gaps:** missing committed `inflight` receipt cases **8, 4, 0, 0**. Actual old publisher commits in these gaps are **8, 8, 0, 8**; correct never-committed refusals there are **0, 0, 8, 0**. Never report the transactional arm's 0/0 historical opportunity as an eight-case replay success.
3. **Actual committed-history outcomes:** old `inflight` commitments across all cases are **14, 14, 6, 14**; supported original replays are **6/14, 10/14, 6/6, 14/14**. Four current-epoch receipts per mode must replay correctly separately.
4. **Summary completeness:** final old summaries total **56, 60, 56, 64** rows across the 24 cases; missing old summary rows are **8, 4, 0, 0**; complete old-effect coverage cases are **16/24, 20/24, 24/24, 24/24**. The effect observer measures completeness but never repairs application history.
5. **Publisher contention and original identity:** busy attempts/completed retries **2, 2, 10, 2**, exact code 5 at BEGIN with checked zero timeout. Every retry keeps epoch, ID, operation and bytes. Total old work refusals are **6, 6, 14, 6**, separate from committed-history losses.
6. **Validated migration retry:** stale selections and completed migration retries **0, 0, 0, 8**. Each stale capture preserves epoch 1, all three old full receipts, current revision 4 and no committed migration witness. No cleanup may occur before source validation succeeds.
7. **Ordering and historical controls:** all six publisher-first cases per mode preserve the original commitment, including both original revision-4 replies after independent D revision 5. Two migration-first controls refuse old work, four current-epoch intents complete, and the two before/after-commit controls each behave as declared.
8. **Transactional witnesses:** 24 committed migration witnesses per mode; selected/observed source mismatch witnesses **8, 4, 0, 0**, matching actual omitted records. Every runtime publication witness has requested epoch equal to the active epoch observed in its transaction. No old-epoch write below the fence is allowed.
9. **Process/barrier coverage:** twelve verified live pauses per mode, exact role invocation/completion counts above, and all 224 complete child traces/journals. No crash cut is part of this experiment.
10. **Supported evidence and errors:** zero fabricated historical responses, parent replays have no effect, capture/journal/counter consistency holds, and zero unexpected infrastructure errors. Expected missing replies remain negative history-availability evidence, not successful denial.

These eligibility groups overlap and have different denominators. The cases are selected histories, not production rates, random race samples, performance rankings or a general concurrency theorem. Preserve failures and disagreements rather than changing measured labels.

## Provenance and independent verification

An independent stdlib verifier must reconstruct the fixed grid, source selections, literal validation outcomes, actor/controller traces, durable tables, witness epoch relations, current delivery, replay support, counters and ten criteria without importing stores, worker or measured controller. Save uniquely named raw JSONL, summary, full test transcript, console and independent report with exclusive creation. Hash the input and twelve sources: new store, worker, controller, verifier, tests and this protocol; unchanged compaction, publication, retry, retirement and overlap stores; and the unchanged overlap controller supplying the validated pipe helper.

Base/freeze arguments are supplied labels, not checkout or source authentication. Hashes identify local bytes; trusted observers and source labels do not provide external attestation. A clean controller exit means no unexpected infrastructure failure. The independent verifier additionally fails on unmet scientific criteria.

## Limits and technical basis

The store handles one migration, one trusted publisher role and optional independent later work on small synthetic fixtures. The literal validation retry is controller-scheduled; starvation, fairness, latency, throughput, arbitrary many-writer histories, authenticated epochs, WAL, network/external effects, faults during commit and power loss remain untested. Source selection may retain full payloads transiently; logical receipt compaction is not erasure or a total-space bound. Typed compact equality retains Phase 14's hash assumption. A pending old request refused after closure is a useful-completion cost even when it protects history.

Primary references consulted 2026-11-07 (Asia/Seoul): [SQLite transactions](https://sqlite.org/lang_transaction.html), [SQLite isolation](https://sqlite.org/isolation.html), [SQLite result codes](https://sqlite.org/rescode.html) and [NIST hash functions](https://csrc.nist.gov/projects/hash-functions). These established mechanisms motivate the comparison. The contribution is the reproducible distinction between an atomic migration commit, complete source selection, preservation of actual committed receipts and the progress cost of ordering publication after closure.
