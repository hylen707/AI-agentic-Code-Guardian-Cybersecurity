# Phase 10 protocol: retire receipts without reviving old intent

**Status:** freeze this protocol and the 20-case manifest before implementing the Phase 10 store, worker, runner, tests, or verifier. This is a developer-visible mechanism study. Earlier code, protocols, inputs, and measured artifacts retain their bytes.

## Question and contract

Phase 9 prevents duplicate publication while request receipts remain stored. Can those receipts be removed without allowing a delayed request to undo a later update or revocation? What historical response is lost when the receipt is removed?

A request carries `(epoch, request_id, operation, exact payload)`. Epochs are positive server-managed integers. One trusted store begins at active epoch 1. Retirement to epoch 2 closes epoch 1 to **new mutations**. An existing historical receipt may still be replayed without changing current state; if it has been removed, the server must reject the old epoch without publishing. This also rejects previously unseen requests from the closed epoch. A future epoch must be rejected. The active epoch may accept new identities, including a literal ID used in another epoch.

Callers preserve the original epoch and ID on retries. The epoch is a namespace/freshness rule for cooperating trusted publishers, not an authenticated capability: relabeling an old request with a newly authorized epoch is outside this contract. Retiring a receipt trades historical response availability for a rule that older intent cannot mutate state. The caller is not instructed to automatically convert a rejected old request into a new intent.

This experiment advances an explicit logical epoch; it does not implement a wall-clock TTL, clock recovery, an authentication protocol, or a production retention policy.

## Shared storage and four arms

All arms use one SQLite database with verified `journal_mode=DELETE` and `synchronous=FULL`. Every publication atomically commits content/approval/revision, its epoch-tagged effect-observer row, and its receipt. The effect log is trusted fixture instrumentation and is never queried for deduplication or retirement. A read transaction captures all tables. Current delivery validates the captured content exactly as in Phase 8.

Request lookup uses the full `(epoch, ID)` key and compares operation and exact payload, distinguishing an empty update from revocation. A retained matching receipt returns its original commitment revision/digest; changed intent conflicts. Requests above the active epoch are rejected before lookup. For requests missing a receipt, the three fenced arms reject epochs below the active epoch; the deliberately weak forgetting arm omits that lower-bound check.

| Arm | Retirement implementation | Old matching receipt | Old request with no receipt |
|---|---|---|---|
| `retain_all` | Advance epoch in one transaction; retain all receipts | Replay original commitment | Reject once epoch is closed |
| `forget_only` | Delete older receipts and advance epoch in one transaction | Replay while still present | Treat as new; deliberately omits retired-epoch rejection |
| `split_fence` | Commit deletion first, then advance epoch in a second transaction | Replay while still present | Reject only after the epoch advance commits |
| `atomic_fence` | Delete older receipts and advance epoch in one transaction | Replay while still present | Reject after the coupled retirement commits |

Retirement targets the next epoch. Retrying an already completed target returns an acknowledgment without advancing again; backward or skipped targets are errors. Both compact fenced arms delete old receipt rows. The experiment counts retained logical rows; it does not measure reclaimed disk pages, memory consumption, or total database bounds. The observer history is intentionally retained and grows with actual effects.

## Fixtures and twenty schedules

Every case starts with revision 1 and `approved=version-a\n`, then two committed epoch-1 publications:

- Update-oriented fixture: ID `request-1` approves version B at revision 2; ID `request-2` revokes at revision 3.
- Revocation-oriented fixture: ID 1 revokes at revision 2; ID 2 approves version C at revision 3.

Thus each store has two original receipts and a later policy that an old ID-1 retry must preserve. The retirement worker targets epoch 2. Every parent follow-up reopens the store.

| Group | Cases per arm | Follow-up after retirement/recovery |
|---|---:|---|
| Known late request | 10 | Update/revocation fixture, each at normal completion or one of four cuts; retry original epoch-1 ID 1 |
| Active-epoch retry | 2 | New epoch-2 update/revocation ID, then same-ID repeat |
| Active-epoch conflict | 2 | New epoch-2 update, then changed bytes; empty update, then revocation under the same key |
| Active-epoch value controls | 2 | New epoch-2 empty or Unicode (`approved=안전 ✓\n`) update |
| Previously unseen old request | 2 | New ID in epoch 1, update/revocation; rejection is the explicit cutoff cost |
| Future epoch | 1 | Epoch-3 request while active epoch is 2 |
| ID reused in a new epoch | 1 | Epoch-2 ID `request-1` denotes a new intent despite its old literal ID |
| **Total** | **20** | **80 case/arm records** |

All non-late-request cases retire normally. Eight known-request cases per arm terminate the worker; twelve cases complete normally. The full grid contains **32 declared child-process exits and 48 normal retirement completions**. Seed publications and follow-up calls are operations within these cases, not extra independent samples.

## Process-exit boundaries

The child emits flushed ordered JSON events and calls `os._exit(73)` at the chosen cut, bypassing normal cleanup. The parent requires the exact event prefix and return code. Random failures, timeouts, malformed stores, or failed observations are infrastructure errors.

| Cut | Observed retirement expectation after child exit |
|---|---|
| `before_retire` | No retirement write; active epoch 1 and both original receipts |
| `after_cleanup` | `split_fence`: deletion committed, active epoch still 1, both receipts missing. Other arms: one transaction is uncommitted, so epoch 1 and both receipts recover |
| `after_commit` | Epoch 2 committed; `retain_all` has both old receipts, other arms have none; no acknowledgment yet |
| `after_ack` | Same committed layout; the child has emitted the retirement acknowledgment |
| Normal completion | Same committed layout; normal completion event and exit 0 |

The `after_cleanup` checkpoint in the retaining arm has no deletion but follows its staged epoch update. These are logical comparison barriers, not identical internal instructions. The reader does not automatically complete an interrupted two-transaction retirement before accepting a follow-up; that missing coupling is the split-arm counterexample.

The parent, kernel, filesystem, and SQLite library survive. No cut is inside a storage call, commit implementation, or recovery operation. This is not a host power-loss experiment or a proof of storage durability.

## Oracle, denominators, and hypotheses

Record the direct active epoch, current payload/approval/revision, actual verified delivery/denial, all effect and receipt rows, child command/return/events, and every follow-up request/response/resulting capture. The oracle models publication intent independently of a claimed `replayed` or `epoch_retired` label. An independent artifact verifier must reconstruct the frozen grid, effect prefixes, retirement layouts, response semantics, counters, criteria, and source/input hashes without importing the measured store or runner.

- **Known late requests / 10:** extra-effect cases in arm order are **0, 6, 2, 0**; preserved later-policy cases **10, 4, 8, 10**. Count effects for the exact epoch-1 ID, not a new-epoch reuse of the literal ID.
- **Historical replies / those 10:** original revision-2 commitment returned **10, 4, 2, 4** times. After a completed retirement, the compact fenced designs instead return `epoch_retired` without a commitment revision in **6/6** known cases. This is safe rejection with loss of historical response availability, not equivalent historical completion.
- **Known-request policy reversal:** forgotten old updates reinstate revoked B **0, 3, 1, 0** times; forgotten old revocations withdraw newer C **0, 3, 1, 0** times.
- **Deletion/fence gaps / all 20 recovery captures:** exactly **0, 0, 2, 0** captures have epoch 1 but neither original receipt. The split gap, rather than a wrong content hash, causes its extra effects.
- **Completed retirements / 16 recovery captures per arm:** each has active epoch 2. The retaining arm keeps two old receipt rows per capture (32 total); compact arms keep zero. No physical storage-reclamation claim follows.
- **New active-epoch intents / 3:** empty and Unicode updates plus new-epoch reuse of ID 1 must complete in every arm. New-epoch ID reuse is not an old-request duplicate.
- **Active-epoch repeats / 2** and **conflicts / 2:** all arms must preserve at-most-once effects and reject changed intent without mutation.
- **Previously unseen old requests / 2:** retaining and fenced designs reject **2/2** without mutation; forgetting applies both. The same closed-epoch rule rejects old unseen work, an explicit service-semantics trade-off.
- **Future requests / 1:** every arm rejects without effects.
- **Intrinsic final content/approval coherence / 20:** expect **20/20** in every arm, including states whose publication intent is wrong.
- **Process coverage / 8 exits and 12 normal completions per arm:** exact traces, expected recovery layouts, and zero infrastructure errors.

These sets overlap. Report **twelve criteria**: predicted duplicate counts; predicted preserved-policy counts; historical-reply/rejection trade-off; policy reversal counts; split-only cleanup gap; old-row retention counts after committed retirement; new active-intent completion; current retry correctness; current conflict correctness; unseen-old cutoff; future rejection; and all coherent states/exact process coverage/expected recovery layouts with no infrastructure errors. Preserve disagreements and negative results rather than changing measured labels.

## Provenance and limits

Commit the protocol and manifest before implementation. Save raw JSONL, summary, full test transcript, independent verification, unique exclusive-create outputs, source/input hashes, versions/platform/command, SQLite settings/integrity results, and caller-supplied base/freeze labels. The runner's clean exit means no infrastructure error; the verifier also fails on unmet scientific criteria.

There is one trusted sequential writer per small fixture store and one database effect domain. Epoch assignment and original request identity must be trusted and preserved. Authentication, tenant boundaries, malicious epoch relabeling, simultaneous requests, multiple resources, clock/TTL semantics, schema migration, physical reclamation, large-store performance, internal storage faults, recovery-time crashes, and live-task integration remain untested. The historical receipt remains an acknowledgment, not current permission. A single epoch counter does not make the entire instrumented database bounded.

## Technical basis

Official sources consulted 2026-11-04 (Asia/Seoul):

- [Amazon Builders' Library: Making retries safe with idempotent APIs](https://aws.amazon.com/builders-library/making-retries-safe-with-idempotent-APIs/): late requests, retained request knowledge, and service-specific retention decisions.
- [Stripe API v1 idempotent requests](https://docs.stripe.com/api/idempotent_requests): the documented scope of key retention and new-request behavior after pruning. This study does not test Stripe or prescribe its retention policy.
- [SQLite atomic commit](https://sqlite.org/atomiccommit.html): transaction boundaries and rollback-journal assumptions.

The local epoch rule is the explicit contract tested here. The contribution is a reproducible separation of forgetting, closing old intent, historical-response availability, and interruption-safe retirement, using established mechanisms.
