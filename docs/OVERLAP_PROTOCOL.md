# Phase 11 protocol: keep epoch admission valid through publication

**Status:** freeze this protocol and the 16-case manifest before implementing the Phase 11 store, worker, controller, tests, or verifier. Cases are developer-visible, not a blind benchmark. Earlier code, frozen plans, inputs, and measured artifacts retain their bytes.

## Question and effect-time contract

Phase 10 retires a logical epoch safely under sequential publication. What happens when a request passes admission in epoch 1, retirement closes that epoch, and the request then writes? Can a separate final recheck prevent the same gap? What ordering is imposed by checking inside the publication transaction?

A new publication's request epoch must equal the active epoch **in the transaction that commits its effect**. A request from an already closed epoch must not create a new effect. A publication committed before retirement may remain the current value after retirement; closing the namespace does not revoke or undo already committed policy. A commitment response may arrive after retirement and still describe a valid earlier effect. This is not request-time revocation or current permission at acknowledgment.

One publisher process and one retirement process operate on the same trusted SQLite fixture. Requests preserve their trusted epoch/ID/operation/bytes. Retirement always advances to epoch 2 and removes older receipts in one transaction, keeping Phase 10's atomic retirement fixed. The intervention changes the scope of the publisher's admission check, not the retirement algorithm or database layout.

## Three publisher arms

All arms commit publication state, the epoch-tagged effect observer, and the request receipt in one write transaction. All compare exact operation/payload when a receipt is found and reject a future or retired epoch at an actual admission check. The selected new request ID is `inflight`, absent from the seed receipts.

1. **`cached_admission`** reads admission in a short read transaction and closes it. Later publication reuses that decision and starts a write transaction without enforcing a new epoch check. Its final-decision event explicitly identifies a cached decision.
2. **`separate_recheck`** performs the same initial admission, then another fresh short read transaction before publication. That read also closes before the write transaction starts. Retirement can occur after this last check.
3. **`transactional_admission`** starts `BEGIN IMMEDIATE` before admission and retains that write transaction through the final check, state/effect/receipt write, and commit. A competing retirement cannot obtain its write transaction while that scope remains open.

The first two arms are deliberately weaker diagnostic comparators. They do not claim that Phase 10's existing transactional publisher fails its original sequential contract.

Every new publication also inserts a **commit witness** recording its revision, requested epoch, and active epoch read inside the same write transaction. All arms take this observer reading; the weak arms do not use it to gate publication. The witness is trusted instrumentation, not an external audit service. It lets the oracle distinguish an old effect committed before the fence from one committed after it, independently of the reported allow/reject label or final epoch.

## Deterministic two-process controller

The parent uses pipes to pause/resume the publisher and starts a separate retirement child while the publisher remains alive. There are no sleep-based interleavings or race-win-rate measurements. Checkpoints and a strict JSON resume command define the happens-before schedule; deadlines detect broken execution only.

Retirement makes a nonblocking `BEGIN IMMEDIATE` attempt with checked `busy_timeout=0`. Only SQLite numeric **`SQLITE_BUSY` (5) raised by that BEGIN** is a valid deferred attempt. Other errors or child failures are infrastructure errors. A busy attempt is retried only after the controller observes publisher completion. The retry must commit retirement. This is an orchestrated retry, not a general fairness or bounded-latency guarantee.

Use **Python 3.11+ on Linux**: numeric `sqlite_errorcode`/`sqlite_errorname` classify contention, and selectors wait on pipe readability. The earlier experiments retain their recorded compatibility and sources. SQLite uses checked rollback-journal `DELETE` and `synchronous=FULL`.

The parent saves both child commands, complete stdout/stderr/parsed traces and return codes, each retirement attempt/result, a sequenced controller journal, a consistent capture before publication, a capture at each pause after the retirement probe, and a final capture. Captures include state, current verified delivery, active epoch, effects, receipts, and commit witnesses in one read transaction. The observer witness table is added during trusted setup; initialization is outside the challenged schedules.

## Sixteen cases per arm

Each fixture starts at revision 1 with `approved=version-a\n`, then uses the unchanged Phase 10 publisher for two epoch-1 seed effects. Update-oriented cases approve B under seed ID 1 and revoke under ID 2; revocation-oriented cases revoke and then approve C. The test request uses fresh ID `inflight`. Only its publication has a commit witness.

Twelve epoch-1 cases combine update/revocation with six schedules:

| Schedule | Controlled order and expected distinction |
|---|---|
| `retire_first` | Retirement commits before the publisher starts; every arm must reject the old request |
| `publication_first` | Publisher completes before retirement starts; every arm commits a valid epoch-1 effect |
| `after_admission` | Pause after the initial check. Weak arms hold no write transaction: retirement commits. Cached admission then writes too late; a separate recheck rejects. Transactional admission holds the writer and defers retirement |
| `after_final_check` | Pause after the last decision, before weak-arm BEGIN. Both weak arms admit a late old effect; transactional admission defers retirement |
| `before_commit` | Pause with state/effect/receipt/witness staged inside the write transaction. All arms defer retirement and commit publication first |
| `after_commit` | Pause after publication COMMIT but before its response. Retirement commits, then the historical publication acknowledgment is returned; the earlier effect remains valid |

Four current-epoch controls first retire to epoch 2, then publish without a pause: ASCII B, empty, Unicode (`approved=안전 ✓\n`) updates and one revocation. These demonstrate useful current-epoch publication, not just denial of all old work.

The manifest therefore has **16 cases per arm, 48 records**. Eight schedules per arm pause a live publisher: **24 forced-overlap records**, plus 24 serial/current controls. Every publisher exits normally. Expected retirement child invocations are **18, 18, 22** in arm order, including **2, 2, 6** busy attempts. Across all arms there are 48 publisher invocations and 58 retirement invocations, 106 child invocations total; no crash injection is used.

## Oracle and fixed denominators

The oracle reconstructs seed and requested bytes, checks actual effect/receipt/witness rows and delivered value, validates both process traces and controller order, and compares the witness's active epoch with the requested epoch. Missing or inconsistent instrumentation cannot count as successful denial. An independent verifier must reproduce the raw assessments and summary without importing the store, worker, or measured controller.

- **Invalid old effects / four admission-gap opportunities:** hypotheses **4/4, 2/4, 0/4**. Across all twelve old-epoch cases, invalid counts remain 4, 2, 0. Two opportunities are after admission and two after the final decision.
- **Invalid effects by pause:** after-admission **2, 0, 0**; after-final-check **2, 2, 0**. Other schedules must produce none.
- **Valid old commits / twelve old cases:** **6, 6, 10**. Correct old-epoch denials: **2, 4, 2**. The transactional arm orders more work before retirement instead of promising that the retirement request immediately wins.
- **Retirement deferrals and completed retries:** **2/2, 2/2, 6/6** busy cases, all numeric code 5 at BEGIN; all retries occur after publisher completion and commit target 2. Busy is not a successful retirement or a policy denial.
- **Current-epoch controls:** **4/4** successful publications for every arm, including actual empty/Unicode delivery and revocation denial.
- **Postcommit historical replies / two cases:** **2/2** each. A delayed response does not make its earlier effect invalid. The commit witness must show epoch 1 while the capture before response already shows epoch 2.
- **Retired receipt recreation / all cases:** **4, 2, 0** cases recreate an epoch-1 receipt below active epoch 2, matching the late-effect failures.
- **Final closure / sixteen cases:** every retirement eventually commits in the declared schedule and the final active epoch is 2. Expected attempt counts are 18, 18, 22.
- **Intrinsic state coherence / sixteen cases:** **16/16** each, distinct from valid epoch admission.
- **Coverage:** eight verified pause/resume barriers, sixteen normal publisher completions, all declared retirement child completions, and zero infrastructure errors per arm.

The denominator sets overlap. They are curated schedules, not independent random samples or production probability estimates. Report **ten criteria**: invalid effect counts; invalid counts at each gap; writer deferrals/completed retries; valid old commit/denial counts; all four current controls; both postcommit historical replies; recreated retired-receipt counts; all scheduled retirements committed with expected attempt counts; coherent states and consistent witnesses; complete process/barrier/controller coverage with zero errors. Preserve disagreements and failures rather than revising the frozen labels.

## Evidence, trust, and limits

Commit this protocol and manifest before implementation. Save raw JSONL, summary, test transcript, independent verification, source/input hashes, versions/platform/command, checked SQLite settings and busy timeout, base/freeze provenance labels, and uniquely named exclusive-create outputs. A clean controller exit means no infrastructure error; the verifier also fails on unmet scientific criteria.

The store, epoch assignment, fixture controller, observer and process channels are trusted. There is one publishing role and one retiring role per fixture, with fixed barriers and one database effect domain. This does not evaluate arbitrary many-writer histories, starvation, throughput, lock-wait latency, fairness, WAL mode, network partitions, hostile epoch relabeling, authentication, wall-clock TTL, host power loss, or crashes during commit/recovery. Logical epoch retirement leaves already committed values intact. No distributed or general exactly-once claim follows.

## Technical basis

Official sources consulted 2026-11-05 (Asia/Seoul):

- [SQLite transaction control](https://sqlite.org/lang_transaction.html): read/write scopes, `BEGIN IMMEDIATE`, and competing writers.
- [SQLite rollback-mode locking](https://sqlite.org/lockingv3.html): writer reservation and concurrent readers.
- [SQLite result codes](https://sqlite.org/rescode.html): numeric `SQLITE_BUSY` and contention classification.
- [Python 3.11 sqlite3 changes](https://docs.python.org/3.11/whatsnew/3.11.html#sqlite3): numeric SQLite error metadata.
- [Python selectors](https://docs.python.org/3.12/library/selectors.html): pipe-readiness waits on Unix.

These are established mechanisms. The contribution is the observed difference between rechecking a condition and keeping its database authority valid through the effect, together with the retirement deferral that buys that ordering.
