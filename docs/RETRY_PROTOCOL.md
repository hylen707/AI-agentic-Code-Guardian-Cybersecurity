# Phase 9 protocol: bind a retry to its committed intent

**Status:** freeze this protocol and the 20-case manifest before implementing the Phase 9 publisher, worker, runner, tests, or verifier. Cases are developer-visible, not a blind evaluation. Earlier evidence and implementations remain unchanged.

## Question and contract

Phase 8 recovers a coherent content/approval pair after publisher exit. A caller still cannot infer rollback from a missing acknowledgment. Does retrying the same logical publication create another revision, or even undo a later update or revocation?

The contract binds one request ID to one operation and exact payload bytes in one trusted store namespace. A first request commits one publication effect and returns its revision and approved digest/revocation. Retrying that ID with the same intent returns the original commitment receipt without another effect. Reusing it with different bytes or a different operation returns a conflict and changes no state. A different ID denotes a new intent even when the payload is identical. A retained receipt describes a historical commitment; it never reauthorizes that value against the current revision.

This is a bounded single-writer request-idempotency contract, not general exactly-once execution, authenticated authorization, or a distributed delivery guarantee. Callers must preserve and reuse their ID. Requests with different IDs are intentionally not deduplicated by content.

## Arms and common storage

All arms use a SQLite row containing payload, revision, and approval, with verified rollback-journal `DELETE` mode and `synchronous=FULL`. Initialization commits revision 1 with `approved=version-a\n`. Every actual publication increments the revision and adds an observer effect row **in the same transaction**. The observer log labels effects with request IDs but is never consulted for deduplication. It exposes repeated mutations independently of a returned status label.

1. **`unkeyed`** commits the coherent state/effect transaction for every call. It does not consult or write an idempotency receipt. This retains Phase 8's state coupling while omitting request identity enforcement.
2. **`split_receipt`** checks a request receipt and rejects parameter conflicts or replays its original result when present. On a new request, it first commits state/effect, then commits the receipt in a **second transaction in the same database**. Keeping the database and settings constant isolates the transaction boundary.
3. **`atomic_receipt`** uses the same identity/parameter rule, but inserts the receipt inside the state/effect transaction before committing. An interrupted uncommitted transaction exposes none of them; a committed one exposes all of them.

Receipt binding stores the operation and exact payload (including empty bytes); revocation has a distinct operation and no requested payload. A receipt retains the original revision and digest/revocation. `committed` and `replayed` responses share these semantic fields. `conflict` returns no commitment revision. A replay returns an old receipt without writing the current publication row. SQLite, the store process, its namespace, and the observer are trusted. The fixture does not model another service or an external side effect.

## Twenty cases and actual process exits

Every case starts with a fresh store. The first request uses ID `request-1`. Updates use `approved=version-b\n`, except empty and Unicode single-publication controls. Revocations retain the current payload and clear the approved digest. Parent-side calls reopen the store for each attempt.

| Group | Cases per arm | Follow-up |
|---|---:|---|
| Single publication | 4 | ASCII, empty, Unicode (`approved=안전 ✓\n`) update; one revocation |
| Same ID and intent after acknowledgment | 2 | Retry the ASCII update or revocation |
| Same ID, changed intent | 2 | After an ASCII update, retry with version-C bytes or revocation |
| Different ID, identical intent | 2 | Repeat update or revocation with `request-2`; must create a new revision |
| Late retry after another intent | 2 | Update B, then revoke with ID 2, then retry ID 1; or revoke, then update C with ID 2, then retry ID 1 |
| Terminated publisher and same-ID retry | 8 | Update/revoke at each of four cuts below |
| **Total** | **20** | **60 case/arm records** |

The child emits flushed JSON checkpoints, a commitment acknowledgment after the publish call returns, and a normal completion event. At a selected cut it calls `os._exit(73)`, skipping Python cleanup. The parent requires the exact event prefix and return code, not merely a failed process. Twelve cases per arm end normally; eight terminate at the declared cut. The full grid therefore has 24 planned terminations and 36 normal first publications.

| Cut | Meaning | Expected logical first publication |
|---|---|---|
| `before_commit` | State/effect changes staged; atomic arm also stages its receipt; transaction not committed | Not committed; retry may apply once |
| `after_state_commit` | State/effect commit returned; split receipt not yet written | Already committed; retry must not repeat it |
| `after_record_commit` | Split receipt transaction returned; other arms reach the same return barrier without a second transaction | Already committed; no acknowledgment yet |
| `after_ack` | Child emitted its commitment receipt | Already committed; acknowledgment observed |

The two after-state-commit split cases intentionally expose a committed effect with no receipt. For the atomic arm the state-commit and record-commit checkpoints bracket no additional storage mutation. These are logical comparison barriers, not identical internal instruction offsets.

## Oracle, denominators, and hypotheses

The runner records direct state bytes and revision, actual verified delivery/denial, the complete committed effect and receipt rows, child traces, and every follow-up request/response plus resulting snapshot. An ideal request-ID model derives expected revisions, operations, response fields, and effects from the declared schedule. It does not use the arm's `committed`/`replayed` label as proof of successful deduplication. A separate verifier reconstructs the frozen grid and oracle without importing the store or measured runner.

The denominator sets overlap. They are selected schedules, not independent random samples or production failure rates.

- **Same-intent retry cases / 12:** eight terminated attempts, two acknowledged repeats, and two late retries. Expected successful retry contracts: **2/12, 10/12, 12/12**. A success requires the expected final state/effects and the original semantic commitment response; a precommit retry legitimately creates its first effect.
- **Cases with an extra effect for ID 1 / 12 retries:** **10, 2, 0**. Count actual observer rows for ID 1, not only the revision number or response status.
- **After-state-commit gaps / 2:** duplicate effects **2/2, 2/2, 0/2**. Missing first receipts at those cuts: split **2/2**, atomic **0/2**.
- **Changed-intent conflicts / 2:** correct conflict and no state/effect change **0/2, 2/2, 2/2**.
- **New IDs with identical intent / 2:** all arms must apply both requests and reach revision 3; **2/2** each.
- **Late retry / 2:** preserve the intervening publication and return the original receipt **0/2, 2/2, 2/2**. The unkeyed hypotheses include one reinstated revoked value and one withdrawn newer approval. Keyed arms must show neither.
- **Single-publication controls / 4:** all arms succeed **4/4**, including actual empty/Unicode delivery and revocation denial.
- **Intrinsic payload/approval coherence / all 20 final snapshots:** **20/20** each, distinct from correct request semantics. Coherent state alone cannot detect a duplicated or superseded intent.
- **Process coverage / 8 terminations per arm:** exact declared traces, all controls completed, zero infrastructure errors. An arbitrary process exception, timeout, malformed store, or failed recovery is not successful protection.

The summary must expose these counts and ten criteria: unkeyed ten duplicate retry cases; split two gap duplicates; atomic twelve successful retries with zero duplicates; keyed conflict rejection; distinct-ID completion; keyed late-state preservation; unkeyed reauthorization and withdrawal counterexamples; four successful single controls per arm; twenty coherent final states per arm; complete declared process coverage with zero errors. The split/atomic first-receipt gap counts must also be reported and independently checked.

## Evidence and limits

Freeze the protocol/manifest commit before implementation. Record source and input hashes, versions, platform, command, base/freeze labels, SQLite settings and integrity checks, raw JSONL, summary, full tests, and independent verification. Preserve negative outcomes. Unique output files use exclusive creation. A clean runner exit means no infrastructure error; scientific criteria are checked separately and by the verifier.

The parent, kernel, filesystem, and SQLite library survive. Cuts are outside storage calls and SQLite commit internals; no host power loss, torn write, recovery-time failure, or durability theorem is established. There is one sequential publisher per fixture, no tenant identity, no authentication, no hostile database mutation, and no external service side effect. IDs and receipts remain indefinitely in a small trusted store; eviction, expiration, capacity, schema migration, multiple writers, and request races are untested. The retained receipt is a historical acknowledgment, not a current access capability. This study is not integrated into the earlier executor or a live coding task.

## Technical basis

Official sources consulted 2026-11-03 (Asia/Seoul):

- [Amazon Builders' Library: Making retries safe with idempotent APIs](https://aws.amazon.com/builders-library/making-retries-safe-with-idempotent-APIs/): caller request identities, parameter mismatch, atomic effect/identity recording, and semantically equivalent replies.
- [SQLite atomic commit](https://sqlite.org/atomiccommit.html): one transaction's commit unit and rollback-journal assumptions.
- [Python `os._exit`](https://docs.python.org/3/library/os.html#os._exit): terminating without normal cleanup.

These are established mechanisms. The contribution is the observed distinction between coherent recovered authorization and safely repeated publication intent under a declared fault model.
