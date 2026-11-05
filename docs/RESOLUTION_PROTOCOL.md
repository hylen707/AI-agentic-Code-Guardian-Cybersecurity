# Phase 13 protocol: receipt retirement during duplicate resolution

**Status:** commit this protocol and the sixteen-case manifest before implementing the Phase 13 store, worker, controller, tests or verifier. Cases are developer-visible. Earlier implementations, frozen designs, inputs and measured artifacts retain their bytes.

## Question and response contract

Phase 12 resolves a duplicate receipt after explicitly rolling back a failed publication, assuming that receipt remains stored. This comparison places atomic receipt retirement between that rollback and resolution. Can the store prevent another effect while honestly reporting whether the original outcome is available?

Requests preserve their original `(epoch, request_id)`, operation and exact bytes. The first actual shared-key commitment defines original intent. An identical request with an available receipt receives `replayed` with its original revision/digest; changed intent receives `conflict` without a commitment. If the receipt is missing below the active epoch, a safe resolver may return `outcome_unavailable` with no revision/digest and no new effect. That response says the original result cannot be reconstructed through the retained receipt interface. It does **not** say the request never committed, identify the stored parameters, or authorize the old intent again. The trusted effect observer is for measurement and must never supply an application response.

Measure three separate properties: one durable shared effect; safe terminal handling without an invented historical result; and availability of the exact original replay/conflict outcome. An unavailable result can satisfy the first two while failing the third. Report these costs separately.

## Three modes and transaction boundaries

All modes use checked SQLite rollback-journal `DELETE`, `synchronous=FULL`, and zero busy timeout for write probes. Publication, effect, receipt and an observer row identifying caller/requested epoch/active epoch commit together. The observer reads the active epoch in the actual write transaction. Receipts bind operation and exact bytes under composite epoch/ID keys.

Every first caller performs a short receipt precheck and pauses after it has closed. The second commits the shared key. The resumed first tentatively changes publication and inserts an effect, then encounters numeric receipt primary-key error 1555. It explicitly rolls back **the whole transaction**, closes the connection, and enters a resolution stage. Statement-level ABORT alone would not undo its preceding changes.

1. **`retry_missing`** reads the original receipt and epoch in a fresh read transaction. If found, it compares exact intent normally. If missing, the diagnostic fallback retries the original epoch/key publication without enforcing the newly observed fence. This deliberately weak cached-admission path can recreate an old receipt and effect after retirement. It must not relabel the request into a newly authorized epoch.
2. **`fenced_resolution`** reads epoch and receipt together in a fresh snapshot. An available receipt supplies the original replay/conflict result. A missing receipt below the active epoch produces `outcome_unavailable`, with no mutation or invented commitment. Missing current-epoch evidence after a recognized duplicate is `storage_error`, not successful replay.
3. **`guarded_resolution`** opens `BEGIN IMMEDIATE` **after the whole collision rollback and before the second pause**, then retains that reservation through lookup and decision. A retirement started at the pause receives code 5 and is retried after resolution releases the writer. If retirement has already won before the reservation is acquired, this mode uses the same missing/closed `outcome_unavailable` rule. The measured reservation ordering does not prove this entire earlier gap is protected.

Only numeric `SQLITE_CONSTRAINT_PRIMARYKEY` (1555) at the receipt INSERT is a modeled duplicate. Only numeric `SQLITE_BUSY` (5) at a write-probe BEGIN is modeled contention. Other constraints, storage failures, unknown codes, failed child processes and broken traces remain infrastructure errors. All collision paths retain the numeric event and full-rollback marker. The weak retry's extra effects are negative application evidence, not infrastructure failures or successful protection.

## Fixture and sixteen histories

Each disposable fixture starts at revision 1 with `approved=version-a\n`. Trusted setup approves B at revision 2, revokes at revision 3, and atomically retires epoch 1 to epoch 2, deleting its old receipts. Shared callers are `first` and `second`, both using epoch 2 and `shared-request`. Their names identify start order; the actual winner is recorded independently. The second caller wins revision 4 while first is paused after its missing-receipt precheck.

| Pattern | First intent | Second intent | Required original resolution |
|---|---|---|---|
| `same_ascii` | `approved=version-b\n` | Same bytes | Replay revision 4 |
| `same_empty` | Empty update | Empty update | Replay revision 4 |
| `same_unicode` | `approved=안전 ✓\n` | Same bytes | Replay revision 4 |
| `same_revoke` | Revocation | Revocation | Replay revision 4 with no approval |
| `changed_bytes` | Version B | Version C | Conflict |
| `update_to_revoke` | Empty update | Revocation | Conflict |
| `revoke_to_update` | Revocation | Empty update | Conflict |
| `changed_unicode_bytes` | `approved=é\n` (U+00E9) | `approved=é\n` (U+0065 U+0301) | Conflict; no normalization |

| Schedule | Cases per mode | Retirement ordering |
|---|---:|---|
| `retire_gap` | 8, every pattern | Attempt retirement to epoch 3 while first is paused before resolution |
| `retire_gap_later` | 4: same ASCII, same revocation, changed bytes, update-to-revoke | Same gap; after completed retirement, independent caller/key `later` publishes epoch-3 `approved=version-d\n` |
| `resolution_first` | 2: same ASCII, changed bytes | First completes receipt resolution, then retirement to epoch 3 |
| `retained` | 2: same empty, changed Unicode bytes | No challenged retirement; receipts stay at epoch 2 |
| **Total** | **16** | **48 case/mode records** |

All sixteen first callers encounter a real receipt collision and use two strict, caller-bound pipe barriers: `after_precheck` and `before_resolution`. Every mode therefore has 32 verified pauses; the comparison has **96 pause/resume barriers**. No sleep arranges execution.

In unguarded gap cases, retirement commits to epoch 3 before resolution; optional later publication commits revision 5 before first resumes. The weak retry then appends an epoch-2 effect at revision 5 or 6, potentially replacing later policy. The fenced mode makes no new effect and returns unavailable. In guarded gap cases, the reservation makes the first retirement probe busy; first resolves the still-retained original receipt, releases its transaction, and completes. The controller then retires and performs any later publication. This ordering difference is part of the intervention and must be explicit when comparing later-state preservation.

Fourteen cases per mode complete retirement to epoch 3; two retained controls finish at epoch 2. There are 36 caller invocations per mode (sixteen first, sixteen second, four later). Retirement invocations are **14, 14, 26**, including twelve guarded retries. Total normal child invocations are **50, 50, 62**, or **162** overall. At most two children are live simultaneously.

## Oracle and ten prospective criteria

Every record preserves caller and retirement commands, complete stdout/stderr, parsed sequenced events, numeric errors, responses, return codes, an ordered controller journal, and consistent captures at setup, after the winner, after the first retirement probe, after later work, after first completion, and final observation as applicable. Captures read publication, epoch, effects, receipts, committing-caller/epoch rows and actual verified delivery in one transaction. Causal prefixes may not be rewritten by a later snapshot.

The oracle reconstructs the actual earliest shared-key commitment from durable effects and actor rows. It compares response identity, exact bytes, original revision/digest, new effects below the fence, recreated old receipts and independent current delivery. Final coherence alone must not hide an unauthorized old effect. An independent stdlib verifier reconstructs these observations and counters without importing any store, worker or measured controller.

Report the following ten criteria in mode order `retry_missing`, `fenced_resolution`, `guarded_resolution`:

1. **Effects:** extra shared-effect gap cases **12, 0, 0**; one shared effect across all sixteen cases **4, 16, 16**; total new durable effects including later work **32, 20, 20**.
2. **Safe gap outcomes and availability loss:** safe terminal resolutions across twelve gaps **0/12, 12/12, 12/12**; unavailable results **0, 12, 0**, each justified by an observed missing receipt below the fence and with no new effect. Never count unavailable as an equivalent original reply.
3. **Original outcomes:** correct original gap replay/conflict **0/12, 0/12, 12/12**; split into identical historical replay **0/6, 0/6, 6/6** and changed-parameter conflict **0/6, 0/6, 6/6**.
4. **Later policy:** exact independent epoch-3 state preserved in four contexts **0/4, 4/4, 4/4**, while documenting that guarded resolution completes before that later work. No latency or throughput ranking follows.
5. **Controls:** all four resolution-first/retained cases per mode return the exact original replay or conflict without another shared effect, including empty and Unicode distinctions.
6. **Collision rollback:** sixteen exact code-1555 receipt failures and full-rollback events per mode, with no tentative pre-collision publication/effect/observer row surviving. A weak fallback's later committed effect is separate from the aborted transaction.
7. **Contention and retry:** busy retirement attempts and completed retries **0, 0, 12**, exact code 5 at BEGIN and zero timeout, preserving retirement target 3.
8. **Current namespace and coherence:** fourteen final epochs at 3 and two at 2 per mode; all sixteen final state pairs intrinsically coherent and all captures consistent, independently of authorization correctness.
9. **Closure evidence:** invalid epoch-2 commits observed at active epoch 3 and recreated below-fence receipt cases **12, 0, 0**. Final old-receipt absence in fourteen retired cases is **2/14, 14/14, 14/14**. Do not infer bounded physical storage from receipt row counts.
10. **Coverage and errors:** all 48 records complete, 32 verified barriers per mode, child completions **50, 50, 62**, all required actor/controller traces, and zero unexpected infrastructure errors. The expected weak failures remain present.

Eligibility sets overlap and are fixed developer-visible histories, not independent population samples. A clean controller exit means absence of unexpected infrastructure errors, not a correct application outcome. The independent verifier also fails on unmet scientific criteria. Preserve disagreements rather than editing measured labels.

## Provenance and limits

Commit protocol/manifest before new implementation. Preserve uniquely named raw JSONL, summary, console, complete test transcript and independent verification with exclusive file creation. Record executed environment/settings, input hash, supplied base/freeze labels and eleven source hashes: the new store, worker, controller, verifier, tests and this protocol; unchanged publication, retry, retirement and overlap stores; and the unchanged overlap controller providing the pipe-barrier helper. Commit labels do not check out or authenticate source; hashes identify actual local bytes. Trusted observers are not external attestation.

This compares receipt availability, logical closure and selected local scheduling. Epochs and callers are trusted; no timer, authentication, hostile identity relabeling, external side effect, network failure, crash, power loss, WAL, many-caller progress, starvation or performance claim is made. The gap before guarded resolution obtains its reservation remains outside the measured ordering and needs explicit fallback behavior. Receipt deletion is logical and observer history still grows. No general exactly-once guarantee or new database primitive is claimed.

## Technical basis

Primary sources consulted 2026-11-05 (Asia/Seoul):

- [SQLite ON CONFLICT](https://sqlite.org/lang_conflict.html): statement-level ABORT and whole-transaction rollback differ.
- [SQLite transaction control](https://sqlite.org/lang_transaction.html): immediate writer reservation and concurrent writer ordering.
- [SQLite result codes](https://sqlite.org/rescode.html): numeric primary-key and busy classification.
- [Amazon Builders' Library: Making retries safe with idempotent APIs](https://aws.amazon.com/builders-library/making-retries-safe-with-idempotent-APIs/): original request intent, equivalent replies and retention limits.

These established mechanisms motivate the comparison; experiment records must support its measured counts.
