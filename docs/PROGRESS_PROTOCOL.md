# Phase 16 protocol: bounded migration progress under repeated publication

**Status:** publish this protocol and the 24-case manifest before implementing the Phase 16 store wrapper, worker, controller, tests or independent verifier. Cases are developer-visible. Preserve all earlier implementation, frozen inputs and measured artifacts byte for byte.

## Question and separate obligations

Phase 15 validates a candidate source inside the writer and retries once after one intervening publisher. That establishes neither progress under repeated changes nor a retry bound. This study gives one migration invocation a finite **attempt budget**, injects a distinct old-epoch publication after each available candidate selection, and distinguishes migration completion, useful publication completion, and preservation of actual committed history.

An exhausted migration is a normal, explicit result, not a successful migration and not an infrastructure failure. Epoch 1 must remain open with full receipts when all attempts roll back. Closed-epoch requests that never committed may return `outcome_unavailable`; that response is neither a historical loss nor publication completion. Replay claims must identify an actual original commit. Observer history measures those distinctions but never answers application requests.

## Three policies and unchanged storage

Reuse the unmodified Phase 15 literal source validation and transactional source selection, compact representation, atomic fence/deletion/summary commit, publication admission and transaction witnesses. A new wrapper chooses an existing selection scope for an explicitly numbered attempt. Budget and attempt numbers are positive integers, attempt cannot exceed budget, and booleans are invalid. The controller owns a finite loop; the budget is per invocation, not durable across restarts.

| Policy | Attempt selection scope | Stop rule |
|---|---|---|
| `validated_budget` | Literal `validated_selection` on every attempt | Stop on `migrated`; after the Bth `stale_selection`, return `budget_exhausted` |
| `transactional_first` | `transactional_selection` from the first attempt | Stop on `migrated`; no speculative retry |
| `validated_fallback` | `validated_selection` on attempts 1 through B-1, `transactional_selection` on attempt B | Stop on `migrated`; the last attempt holds its writer from selection through commit |

For B=1 the fallback policy immediately uses the transactional scope. The fallback holds a writer only after successfully acquiring it; this schedule gives migration that acquisition opportunity. It is not a starvation-freedom result. Other correct policies, including a fresh source read only after acquiring the writer, are not excluded or ranked by this comparison.

Checked `journal_mode=DELETE`, `synchronous=FULL`, and zero runtime busy timeout apply. Only numeric SQLite error 5 at a publisher's `BEGIN IMMEDIATE` is a modeled busy response. A migration BEGIN failure, COMMIT busy, unknown error, child failure or malformed trace remains an infrastructure error. There is no sleep-based schedule, elapsed-time benchmark, crash injection or hidden cleanup migration.

## Fixture, finite histories and exact scheduling

Trusted setup starts with A at revision 1, publishes B as epoch-1 `seed-a` at revision 2, then revokes as `seed-b` at revision 3. Migration targets epoch 2. The manifest is the Cartesian product of B in {1,2,3}, N in {0,1,2,4}, and two value patterns: **updates** cycles ASCII B, empty update, Unicode `approved=안전 ✓\n`, ASCII B; **revocations** always supplies `None`. There are 24 cases per policy and 72 case/policy records. Each policy receives the same **42 distinct epoch-1 runtime intents** across its 24 cases, IDs `item-1` through `item-N`. Empty update and revocation remain distinct. Every retry retains epoch, ID and original bytes.

For each allowed migration attempt:

1. Start a fresh migration child; record its numbered policy plan and source selection. Pause at `after_selection` using a live pipe barrier bound to migration role, attempt, budget and stage.
2. If any declared publisher intent remains unattempted, run exactly one publisher child to completion while migration is paused. Validated selection leaves its read transaction closed, so the publisher commits. Transactional selection holds the writer, so this publisher returns numeric busy without an effect.
3. Capture the database while paused, resume the exact migration attempt, and retain its result, complete trace and post-attempt snapshot. A stale attempt must equal the pause snapshot: no fence, deletion, summary, or migration-witness change.
4. If the publisher was busy, retry that same intent once after the migration child releases its writer. This retry is refused after closure. A second busy result is unexpected infrastructure failure.
5. Stop after a migrated result or after the declared attempt budget is used. Only stale-selection results permit another migration attempt.

After migration stops, run every remaining declared old-epoch intent once. If migration exhausted, these requests commit in the still-open namespace; if migration completed, they are refused. Do not silently drop remaining intents, change their epoch or run a post-budget migration. Preserve a stop snapshot **before** draining remaining intents, a final snapshot after draining, and a replay snapshot.

Finally query both seeds and every declared runtime identity with its exact original intent and a changed intent. A committed identity must replay its original revision/approval and reject the changed intent as a conflict. A never-committed identity in the closed namespace must return `outcome_unavailable` for both queries and must not acquire a new effect. All queries together must leave the final database unchanged. The application reads only full or compact receipts, never the observer effect/witness history. This also checks that old acknowledgments do not restore the current policy.

## Prospective denominators and expected observations

With these deliberately arranged barriers, validated-only migration finishes iff N<B. It completes in N+1 attempts then; otherwise it exhausts in B attempts and remains at epoch 1. Transactional-first finishes in one attempt. Fallback finishes within B attempts, allowing at most B-1 intervening publications before taking its final writer scope. These are predictions for the finite schedules, not universal progress guarantees.

| Measure across 24 cases | `validated_budget` | `transactional_first` | `validated_fallback` |
|---|---:|---:|---:|
| Migration completed / exhausted | 12 / 12 | 24 / 0 | 24 / 0 |
| Migration attempts / live barriers | 40 | 24 | 40 |
| Stale rollbacks, unchanged from pause | 28 | 0 | 16 |
| Runtime intents committed / refused | 42 / 0 | 0 / 42 | 16 / 26 |
| Busy publisher attempts, same-identity completed retries | 0 | 18 | 12 |
| Runtime original replays: compact / full | 8 / 34 | 0 / 0 | 16 / 0 |
| Final summary rows / full receipt rows, including seeds | 32 / 58 | 48 / 0 | 64 / 0 |
| Publisher children / all children | 42 / 82 | 60 / 84 | 54 / 94 |

There are **104 live barriers and 260 normal child completions** overall. Each policy receives 48 seed replay opportunities plus 42 runtime opportunities. Actual committed runtime history is the denominator for runtime preservation: 42, 0, and 16 respectively. Report transactional-first's 0/0 runtime replay opportunities as not applicable, not as 42 successful publications. Count full receipts retained after exhaustion as valid historical authority, not completed compaction. Missing authority, invented replies, changed-intent success, duplicate effects, and unexpected infrastructure errors are expected to be zero.

## Evidence and ten acceptance criteria

Retain raw per-case JSONL: initial/stop/final/replay snapshots; every child command, request, before/pause/after snapshot, stdout, stderr, return code, numbered event stream and response; controller causal journal; migration terminal result; exact and changed-intent query replies; and recomputed per-case metrics. Include input/source SHA-256, base/freeze commit IDs, command, Python/SQLite/platform versions and UTC start/finish metadata. Keep failures as records with their error phase; never omit them or replace them with modeled refusals.

The controller oracle and a separate standard-library verifier reconstruct snapshots, causal ordering, request identities, strategy selection, transaction witnesses, every child event and all ten criteria. The verifier must not import the measured store, worker, controller or their oracle. It rejects altered manifests, provenance hashes, missing/duplicate records, incorrect counters and unsupported trace claims. It recomputes scientific criteria even for internally consistent but unfavorable observations.

1. Exact 24-case coverage per policy, finite attempt limits and correct terminal results.
2. Completed/exhausted totals and B/N-specific progress boundary, including B=1 and N=0 controls.
3. The 42 equal declared runtime intents per policy are all attempted; commit/refusal counts remain separate.
4. Actual committed originals all replay, changed intents conflict, never-committed closed identities remain unavailable, and all query operations are inert.
5. Every committed effect retains exactly one authoritative full or compact receipt; row counts distinguish open exhaustion from closed migration.
6. All stale rollbacks preserve their pause snapshots and occur only under literal validation.
7. Numeric publisher busy responses preserve state and retain identical retry intent; the later refusal is counted explicitly.
8. Current state/delivery, requested/active epoch witnesses and complete migration source witnesses agree with actual commit history.
9. Exact child and strict live-barrier counts, complete normal exits, and causal continuity of all before/after snapshots.
10. No false historical claims, duplicate effects, unsupported results or unexpected infrastructure errors; provenance and independent recomputation agree.

## Interpretation and sources

This studies a bounded application retry policy under controller-arranged finite contention. It does not establish throughput, wall-clock deadlines, scheduler fairness, eventual acquisition, many simultaneous callers, multiple compactors, restart-persistent budgets, crash-plus-contention composition, hostile storage, production deployment or general effectiveness. Budget exhaustion is safe retention with unfinished migration; locking trades additional old-epoch publication completion for closure in the tested order. The observer remains trusted measurement infrastructure. SHA-256 compact summaries inherit Phase 14's cryptographic and trusted-metadata assumptions; no physical erasure or universal minimal schema is claimed.

SQLite documents single-writer transaction behavior and the possibility that `BEGIN IMMEDIATE` fails with busy. The experiment checks the configured journal and error site rather than treating every storage failure as useful deferral: [transaction control](https://sqlite.org/lang_transaction.html), [isolation](https://sqlite.org/isolation.html). Prior evidence: [selection findings](SELECTION_FINDINGS.md), [compaction findings](COMPACTION_FINDINGS.md).
