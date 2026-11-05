# Phase 12 protocol: one request effect and two correct caller outcomes

**Status:** freeze this protocol and the 16-case manifest before implementing the Phase 12 store, worker, controller, tests, or verifier. Cases are developer-visible. Earlier implementations, plans, inputs, and measured artifacts retain their bytes.

## Question and caller contract

Phase 11 holds epoch admission valid through publication. This study fixes the active epoch at 2 and asks what two callers using the same request identity observe. Does a unique receipt key plus rollback establish correct caller-visible idempotency, or merely prevent an extra state change?

For a fresh `(epoch, request_id)`, one caller commits one publication and its receipt. The caller that commits first defines the stored operation and exact bytes. A same-intent concurrent or repeated call must return the original commitment revision/digest with `replayed`; changed intent under that key must return `conflict` with no commitment revision and no mutation. The caller that starts first need not win. A different ID is a separate intent even with identical bytes. A later independent publication must remain current when an old request's receipt is returned.

`storage_error` and `busy` are not correct final replay/conflict outcomes. A busy attempt may be retried with the same caller identity and request bytes, and only its eventual logical outcome is evaluated as that caller's result. This is a trusted local caller contract with retained receipts, not authentication or general exactly-once distributed execution.

## Four modes and common storage

All modes use the unchanged epoch-store schema with checked SQLite rollback-journal `DELETE` and `synchronous=FULL`. A publication writes state, its effect, request receipt, and an observer row identifying the committing caller in one transaction. Receipts are keyed by `(epoch, ID)` and bind operation and exact bytes. Publication always rereads the current state inside the write transaction before incrementing its revision.

1. **`precheck_insert`** reads the receipt in a short transaction and closes it. A missing receipt leads to a later write transaction. If a rival has inserted that receipt meanwhile, the known receipt-key primary-key error is explicitly rolled back and returned as `storage_error`.
2. **`constraint_conflict`** uses the same precheck/write path but labels every such primary-key collision `conflict`, without comparing the rival's parameters. This may reject an identical retry incorrectly.
3. **`resolve_duplicate`** uses the same precheck/write path. On that collision it explicitly rolls back, opens a fresh read transaction, and resolves the **original request receipt**, returning replay or parameter conflict. It must not construct a reply from the latest publication row. A missing receipt during resolution is an error, not proof that the request completed.
4. **`transactional_lookup`** obtains `BEGIN IMMEDIATE` before looking up the receipt and retains it through a new commit. Another caller receives a nonblocking `busy` result while that writer is held; the controller retries after the holder completes, preserving the request identity. The new lookup then finds the original receipt or correctly treats a different key as new.

Every write attempt uses checked zero busy timeout; only numeric **`SQLITE_BUSY` (5) at BEGIN** is a modeled deferral. Only numeric **`SQLITE_CONSTRAINT_PRIMARYKEY` (1555) from the receipt INSERT** is a modeled duplicate collision. Other constraint/storage failures are infrastructure errors and must never be relabeled as replay, conflict, or successful protection.

Every modeled collision explicitly rolls back the whole tentative publication, including earlier UPDATE/effect INSERT statements. SQLite's default statement-level `ABORT` does not by itself undo those earlier statements. The one-effect hypothesis below depends on this explicit transaction rollback, not uniqueness alone.

The modeled `storage_error` is an intended negative caller outcome from a recognized collision, with a normal child exit and retained numeric details. Unexpected process, storage, or trace failures remain separate infrastructure errors. Both must remain visible.

## Fixtures, payloads, and sixteen cases

Each fresh fixture starts at revision 1 with `approved=version-a\n`, approves B under seed ID 1 at revision 2, revokes under seed ID 2 at revision 3, then atomically retires to epoch 2. The shared test key is `shared-request`, absent from the retained receipts. The two logical callers are `first` and `second`; these names identify start order, not priority. Optional independent work uses caller/key `later` and `approved=version-d\n`.

| Pattern | First intent | Second intent | Relationship |
|---|---|---|---|
| `same_ascii` | `approved=version-b\n` | Same bytes | Replay required |
| `same_empty` | Empty update | Empty update | Replay required |
| `same_unicode` | `approved=안전 ✓\n` | Same bytes | Replay required |
| `same_revoke` | Revocation | Revocation | Replay required |
| `changed_bytes` | Version B | Version C | Conflict required |
| `update_to_revoke` | Empty update | Revocation | Different operations |
| `revoke_to_update` | Revocation | Empty update | Different operations |
| `changed_unicode_bytes` | `approved=é\n`, U+00E9 | `approved=é\n`, U+0065 U+0301 | Exact bytes differ; no normalization |

| Schedule group | Cases per mode | Order |
|---|---:|---|
| `overlap` | 8 | Every pattern; first pauses after its missing-receipt lookup, second attempts, then first resumes |
| `overlap_with_later` | 4 | Same ASCII, same revocation, changed bytes, empty-update/revocation; an independent later publication commits after the shared winner but before the losing caller's final outcome |
| `serial` | 3 | Same ASCII, same empty, changed bytes; first completes before second starts |
| `distinct_overlap` | 1 | Both ASCII B but second uses ID `other-request`; two legitimate effects must commit |
| **Total** | **16** | **64 case/mode records** |

There are twelve shared-key overlap opportunities per mode: six identical and six changed-intent cases. Three serial shared-key cases and one distinct-key overlap remain separate controls. Fifteen cases per mode should have exactly one shared request effect. The distinct-key control should have two effects.

## Real-process controller and winner ordering

Use Python 3.11+ on Linux, numeric SQLite error metadata, and the previously validated pipe-barrier helper from Phase 11. Every process attempt has a command, return code, complete stdout/stderr/parsed events, requested caller/epoch/key/payload digest, and result. The controller saves a sequenced journal, a consistent initial capture, a capture while the first caller is paused, any independent-later capture, and a final capture. Each capture reads state, namespace, effects, receipts, and caller-commit observer rows in one read transaction.

In the three precheck modes, the first caller releases its read transaction before pausing. The second wins the shared request and commits revision 4. The first then collides on the receipt key and rolls back its tentative next revision. With independent later work, revision 5 commits before that loser resumes; receipt resolution must still use revision 4.

In transactional lookup, the first caller holds the writer at the pause. The second gets code 5 with no effect. The controller resumes the first, which commits revision 4, performs any independent later work, then retries the second with the same inputs. The first now wins instead of the second. Both winner orders are valid; observer rows identify the actual committing caller, and the oracle binds responses to that commit rather than assuming start order wins.

The distinct-key overlap follows the same ordering but commits both identities: revisions 4 and 5. Serial controls use no pause or busy retry. No sleep arranges the schedules. Deadlines and strict caller-bound resume messages detect broken execution; they do not measure service latency.

Expected process invocations per mode are **36, 36, 36, 49**: two logical caller attempts in each case, four optional later writers, and thirteen extra busy retries in transactional lookup. All **157 child invocations** should exit normally. There are **52 live pause/resume records** (thirteen per mode), plus twelve serial records. No crash injection is part of this comparison.

## Oracle, denominators, and hypotheses

The oracle checks direct state/effect/receipt observations and the atomically written committing-caller rows. It derives the winner's stored intent and commitment, then checks both logical caller outcomes. It separately counts exact publication effects, complete rollback, false conflicts, recognized storage-error responses, numeric contention, and historical replies. An independent verifier must reconstruct the grid, actor/controller traces, captures, caller outcomes, and all counters without importing stores, worker, or measured controller.

- **Correct caller pairs / twelve shared overlap cases:** **0/12, 6/12, 12/12, 12/12**. One state effect is insufficient if the other caller receives a storage error or false conflict.
- **Identical overlap replay / six:** **0/6, 0/6, 6/6, 6/6**. **Changed-intent conflict / six:** **0/6, 6/6, 6/6, 6/6**.
- **False identical conflicts:** **0, 6, 0, 0**. **Modeled final storage-error responses:** **12, 0, 0, 0**. These are negative application outcomes, not successful blocks.
- **Receipt primary-key collision/rollback attempts:** **12, 12, 12, 0**, all exact numeric code 1555 at the receipt INSERT. All tentative losing updates must be absent from durable state/effect/caller rows.
- **Busy attempts and completed identity-preserving retries:** **0, 0, 0, 13**, all code 5 at BEGIN. This includes the distinct-key overlap, exposing serialization cost even for independent intent.
- **One shared effect / fifteen shared cases:** **15/15 each**; **distinct-key completion / one case:** both legitimate effects in every mode. Total new durable effects, including optional later work, are **21 per mode** across the sixteen cases.
- **Serial caller pairs / three:** **3/3 each**, including ordinary replay and changed-parameter conflict.
- **Independent later state / four:** **4/4 preserved** in all modes. **Original historical replay / two identical-later cases:** **0/2, 0/2, 2/2, 2/2**, returning shared revision 4 while the current state is revision 5. Changed-intent later contexts must conflict without rolling back the new state.
- **Intrinsic coherence and active epoch / sixteen:** coherent captures and final epoch 2 for every mode, independently of response correctness.
- **Coverage:** thirteen verified pauses per mode, expected child invocation counts, both logical caller results retained, and zero unexpected infrastructure errors.

Report **ten criteria**: exact shared-effect/new-effect counts; shared-overlap pair correctness; identical replay/changed conflict; false-conflict/storage-error counts; primary-key abort/rollback counts; busy and completed retry counts; historical replay with preserved later state; serial/distinct controls; coherent captures and epoch closure; complete process/barrier/journal coverage with zero unexpected errors. Denominator groups overlap and are selected histories, not random samples or production failure rates. Preserve disagreements rather than modifying measured labels.

## Provenance and limits

Commit the protocol/manifest before implementation. Save raw JSONL, summary, full test output, independent verification, unique exclusive-create artifacts, source/input hashes, environment/command/settings, and caller-supplied base/freeze labels. Record all reused source dependencies, including the Phase 11 barrier helper and its imported store modules. A clean controller exit means no unexpected infrastructure error; it does not imply correct caller outcomes. The verifier also fails on unmet scientific criteria.

The epoch stays at 2 during the challenged calls and receipts are retained. Retirement during duplicate resolution, arbitrary caller populations, starvation, fairness, latency, WAL, authentication, hostile payloads, network partitions, external effects, crash recovery, and power loss remain outside scope. The observer is trusted instrumentation. The database unique key plus explicit rollback is a tested local mechanism, not a complete caller contract or a general exactly-once guarantee. Other duplicate-resolution designs are not ruled out.

## Technical basis

Official sources consulted 2026-11-05 (Asia/Seoul):

- [SQLite conflict resolution](https://sqlite.org/lang_conflict.html): statement-level `ABORT` versus explicit whole-transaction rollback.
- [SQLite result codes](https://sqlite.org/rescode.html): `SQLITE_CONSTRAINT_PRIMARYKEY` 1555 and `SQLITE_BUSY` 5.
- [SQLite transaction control](https://sqlite.org/lang_transaction.html): writer admission and transaction boundaries.
- [Amazon Builders' Library: Making retries safe with idempotent APIs](https://aws.amazon.com/builders-library/making-retries-safe-with-idempotent-APIs/): original request results and changed-parameter handling.

These mechanisms are established. The contribution is the reproducible distinction between one durable effect, correctly classified conflicts, equivalent historical replies, and the costs of rollback or serialization under a declared concurrent schedule.
