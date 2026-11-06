# Authorization across objects, versions, and retries

[Documentation index](README.md) · [Claims and artifacts](EVIDENCE.md) · [Threat model and limits](LIMITATIONS.md)

## Abstract

CodeGuardian studies whether authorization remains valid for the resource, value and publication intent that actually takes effect. Fourteen synthetic stages trace pathname approval through held objects, approved bytes, revision ordering, recovery, request identity, retirement and historical-response evidence. Earlier results separate object continuity from immutable content, coherent storage from safe retries, and mutation safety from both callers' correct outcomes. The latest comparison replaces old full receipts with typed SHA-256 summaries and tests interrupted migration. Correct original replays across twenty selected histories are twenty, twelve, twelve and twenty for retained, dropped, split-summary and atomic-summary modes. Drop and split have the same aggregate total but different loss windows: split migration loses all eight replies after cleanup or uncommitted summary insertion, while atomic migration preserves them. All modes preserve later policy and prevent another known-request effect. Compact equivalence is conditional on the hash assumption; logical payload removal is not physical erasure or bounded total storage. The contribution is a reproducible progression of assumptions, counterexamples, interventions and costs with separate measures for protection, evidence availability and useful completion. No general concurrent-safety or exactly-once guarantee is established.

## The central argument

A policy decision concerns a representation of a resource. Execution concerns an operating-system object. Protection requires the relationship between those two to survive until the operation occurs.

Let `R(p, t)` denote the object reached by pathname `p` at time `t`, and let `P` be the fixed set of protected file identities. A pathname gate can establish `R(p, t_check) ∉ P`. That observation does not imply `R(p, t_use) ∉ P` when names can change. Phase 5 constructs the missing step directly: the gate approves an ordinary object, the fixture controller changes the name binding, and the later open reaches a protected object.

For an open descriptor `d`, the proposed invariant is narrower: authorization and content I/O refer to the same held object. If `identity(d) ∉ P` at authorization, `P` remains fixed, and the trusted executor retains exclusive control of `d`, subsequent name replacement cannot redirect that descriptor to another object. The executor must avoid reopening the pathname and must defer truncation until after approval. This argument follows established descriptor semantics; the experiment tests the implementation in selected schedules rather than proving all possible executions. See the technical sources in the [protocol](RACE_PROTOCOL.md#technical-basis).

Object continuity does not imply content-version continuity. Let `C(d, t)` be a value read through descriptor `d`. A digest check of `C(d, t1)` cannot authorize `C(d, t2)` if a writer changes the bytes between those reads. Phase 6 keeps the inode constant and exposes exactly that failure. A verified buffer instead checks `H(b) = h*` for the captured value `b` and returns that same value. This conditional argument assumes a trustworthy approved digest, collision resistance, and trusted process memory.

Returning `b` does not imply that `b` equals the current file contents. The Phase 5 and Phase 6 results separate three properties:

| Property | What the experiment establishes within scope | Remaining distinction |
|---|---|---|
| Object continuity | A held descriptor survives the tested name substitutions. | The object's contents can still change. |
| Approved-version delivery | A validated captured value is the value returned. | Inspection may already have read unapproved bytes. |
| Freshness | Not guaranteed; three approved payloads are stale. | Reauthorization or a different consistency contract is needed. |

## Evidence that changed the design

The [policy dataset](../experiments/cases/v3/README.md) initially provided 45/45 expected-label matches. Its oracle described the checker itself. The [paired replay](REPLAY_FINDINGS.md) then asked about resource effects and required reads: the string gate prevented two protected operations, missed two aliases, and lost two legitimate completions. Safe completion stayed at 4/8. This negative result exposed the gap between a passing policy test and useful protection.

The [resolved-target intervention](GATE_FINDINGS.md) recovered legitimate completion and blocked symlink-mediated protected access in two separately reported eight-task suites. The [identity study](IDENTITY_FINDINGS.md) then changed one assumption: two paths could name the same file through hardlinks. The resolved gate missed both protected hardlinks, while identity checking blocked them. That success depended on topology remaining fixed.

The [replacement study](RACE_FINDINGS.md) challenged that dependency. All four after-check protected substitutions bypassed the identity-path arm. The descriptor arm retained the initial ordinary object through the same substitutions and through benign replacements. Ordinary controls rule out blanket refusal as the explanation for its zero protected content operations. Before-check substitutions distinguish identity authorization from merely holding whichever file was opened.

The [content-version study](CONTENT_FINDINGS.md) then changed bytes without replacing the inode. Identity-only reads returned five unapproved versions; hash/reread returned three; a verified buffer returned none. Both digest arms denied the two changes that preceded capture. All eight cases remained in the delivery denominator: the buffer delivered an approved version in 6/8 cases and an approved but stale version in three. This makes its benefit and limitation visible together. The new delivery rule does not retroactively change the earlier resource-protection oracle.

## Contribution and research judgment

This repository contributes an inspectable experimental progression: a failed assumption, a bounded intervention, and a follow-up that tests the intervention's remaining dependency. It also contributes raw traces, task-level or object-level oracles, prospective protocol freezes, and separate accounting for policy blocks and infrastructure errors.

The security mechanisms themselves are established systems concepts. The project does not claim a new sandbox primitive, a novel discovery of TOCTOU, or an independently evaluated defense against AI agents. Its value lies in making the reasoning testable and in revising claims when the threat model changes.

## Validity and open questions

All cases are curated and visible during development. Related cases are not independent samples. The schedules deterministically arrange check/use ordering; they do not measure concurrent race probability. No confidence interval or population security rate is justified. The arms share controlled fixtures and the earlier descriptor executor; Phase 6 deliberately changes whether the checked value is retained or reread. Its mutations occur before capture or after validation, not during a capture.

Phase 7 defines approval at receipt, Phase 8 measures process-exit recovery, Phase 9 measures retained request identities, Phase 10 measures logical retirement, Phase 11 fixes a publisher/retirer overlap, Phase 12 fixes same-ID caller outcomes under retained receipts, Phase 13 places retirement around duplicate resolution, and Phase 14 tests compact historical summaries and interrupted migration. Concurrent publication during migration source selection, many-caller histories, fairness, authenticated epochs, wall-clock expiry, power-loss testing, and changes during capture remain future studies. Dynamic protected membership and creation remain separate obligations. Agent integration requires a distinct protocol with model/prompt versions, constrained tools, budgets, repeated task trials, and independent task-correctness assessment.

## Attribution and interpretation

The repository owner directs the project. The commits, logs, and artifacts document what was produced and tested; they do not establish which concepts the owner developed independently or what the owner personally learned.

A portfolio or application account should identify the owner's actual decisions, revisions, explanations, and independent work. [Reflection notes](REFLECTION_NOTES.md) provide evidence-linked prompts without supplying an invented personal narrative. No institutional affiliation, external review, publication, or deployment impact is claimed.

## Extension: approval revisions and a receipt boundary

Phase 7 asks whether a validated value remains authorized after a trusted update or revocation. Separate rechecking still permits two invalid receipts in five post-capture transitions; holding the publication lock through trusted receipt yields zero. This orders receipt before two deferred commits rather than promising request-time revocation. Two valid values are obsolete at final observation. The A-to-B-to-A case rejects an old revision despite identical bytes, making the revision-specific policy explicit. [Findings](REVISION_FINDINGS.md) retain the 27 journals and the pre-measurement, post-draft freeze qualification.

## Extension: recovery requires a coupled state

Phase 8 separates delivery protection from recovery availability. After a child publisher exits between a payload replacement and approval replacement, both split arms recover an inconsistent pair in two of 19 cases. Digest verification prevents delivery of those mismatches, yet yields only 13/15 valid reads. Storing the approved bytes and revision in one SQLite transaction yields 19/19 coherent states and 15/15 valid reads. Both designs enforce all four committed revocations.

The comparison uses known process-exit boundaries and a parent-side restart observer. Four postcommit cuts recover the new state even without an acknowledgment, exposing a separate retry question. The intervention is an established transaction primitive applied to a different storage layout, not a new crash-safety theorem or a power-loss test. The [findings](RECOVERY_FINDINGS.md) link the pre-implementation protocol, 57 raw observations, and independent artifact recount.

## Extension: a publication must retain its request identity

Phase 9 asks what survives an uncertain response. The three arms all retain coherent content/approval state in 20/20 cases. Without request identity enforcement, ten of twelve same-intent retries create an extra effect; a late retry can even undo a later revocation or update. Separately recording an ID-bound receipt prevents ordinary repeats but leaves two process-exit gaps. Inserting that receipt with the publication prevents all selected duplicates and satisfies 12/12 retry contracts. New IDs with identical payload still create legitimate new revisions, and changed intent under an existing ID conflicts.

The binding is between an ID and its operation/bytes, not between matching payload hashes and presumed intent. A historical receipt proves which revision that request committed within this fixture; it does not authorize that revision as current. Retrying the old request returns the original receipt while the current row continues to enforce the intervening publication. [Findings](RETRY_FINDINGS.md) retain all 60 observations, the pre-implementation freeze, and an independent effect-prefix recount.

This is an established idempotency pattern in one database effect domain. Retained receipts, a trusted namespace, and sequential callers are assumptions. Deleting an ID record or using a fresh ID changes the contract. Phase 10 tests logical retirement; wall-clock expiry still requires a separate protocol.

## Extension: closing intent survives the removal of its receipt

Phase 10 separates a stored reply from the rule that old intent can no longer mutate state. A request is scoped by `(epoch, ID)`. The store rejects future epochs, replays a matching retained receipt, and otherwise rejects a missing receipt below the active epoch. A new active-epoch ID is a new trusted intent, including a literal ID used in an older epoch. The rule also rejects previously unseen old requests, making the cutoff cost explicit.

Deleting receipts without the lower-epoch rule repeats six of ten old known requests. Deleting them before committing the fence leaves two interruption gaps. Coupling the fence and deletion preserves later policy in all ten known-request cases, as does keeping all historical receipts. Every arm retains intrinsically coherent content/approval pairs, so coherence alone again misses the wrong intent. The atomic design removes the two old receipt rows after each completed retirement but loses their historical replies in six selected cases, returning a safe rejection instead.

The counterexample is conditional on trusted callers preserving the assigned epoch. A caller allowed to relabel an old request as a new authorized intent is outside that contract. This is logical retirement in one sequential database namespace, with retained observer history, not a timer or evidence of bounded total storage. [Findings](RETIREMENT_FINDINGS.md) retain the pre-implementation freeze, all 80 observations, and an independent prefix/layout recount. Phase 11 tests whether epoch validation remains valid through a publication already in progress when retirement overlaps it.

## Extension: validity belongs to the effect's transaction

Phase 11 asks whether another final read can protect a later write. After the publisher's initial read, a separate recheck detects a completed retirement. After that recheck, retirement can still commit before the write begins; two of four selected opportunities remain invalid. Holding `BEGIN IMMEDIATE` from admission through commit prevents those late effects by ordering publication before retirement. This imposes a cost: six retirement probes return numeric `SQLITE_BUSY` and require the controller's later retry.

The commit witness records the requested epoch and active epoch in the same transaction as its effect. All modes retain coherent final content/approval pairs, including the invalid late writes. Conversely, an old request's response can arrive after the epoch closes while its earlier effect remains valid. The two after-commit controls per mode demonstrate this ordering. Retirement closes new writes in a namespace; it does not withdraw already committed values.

The [findings](OVERLAP_FINDINGS.md) retain 48 records, 24 forced overlaps, complete traces for 106 child invocations, and an independent actor/witness recount. Fixed barriers demonstrate these histories without estimating a race probability or fairness. Phase 12 below tests simultaneous same-ID outcomes. Conditional writes and many-publisher schedules remain separate questions.

## Extension: one effect still needs two correct outcomes

Phase 12 makes caller-visible idempotency an explicit obligation. A unique receipt key and whole-transaction rollback leave one shared effect in all fifteen shared-key cases per mode. That state result alone conceals twelve final storage errors in `precheck_insert` and six false identical conflicts in `constraint_conflict`. In the twelve overlap opportunities, correct response pairs are 0/12, 6/12, 12/12 and 12/12 across precheck errors, unconditional conflicts, receipt resolution and transactional lookup.

The successful post-rollback resolver reads the original receipt and compares operation and exact bytes. It does not infer a replay from the latest publication. The transactional design serializes lookup and mutation, then requires thirteen identity-preserving busy retries, including the distinct-key control. The resolver retains twelve collision rollbacks. Both are valid interventions in this experiment; the result does not imply that locking is the only correct design or rank their performance.

The actual winning caller differs between these interventions. Atomically stored caller rows, effect history and original receipt bytes establish the response oracle. Four later-publication contexts preserve current state at revision 5, while the two identical-later cases in each successful mode return the original revision 4. The [findings](CALLER_FINDINGS.md) retain 64 records, 157 complete child invocations and an independent reconstruction of ten criteria. Epoch 2 and retained receipts are assumptions. Phase 13 below tests retirement between collision rollback and receipt resolution.

## Extension: closure can preserve safety while losing an answer

Phase 13 exposes the receipt-retention assumption in post-rollback resolution. The second caller commits shared revision 4, then the first encounters the real duplicate and rolls back. Retirement can remove the original receipt before the next lookup. A diagnostic fallback that writes again under cached admission creates an extra old-epoch effect in all twelve selected gaps, even though final content/approval remains coherent. Four such retries also overwrite an independent later policy.

The fenced resolver instead reads epoch and receipt together and returns unavailable after closure, with no commitment fields or new effect. It satisfies safe terminal handling in 12/12 gaps but provides the exact original outcome in 0/12. That distinction is a cost of evidence removal: safe refusal does not imply the original request never committed, and a guessed matching revision cannot establish a supported replay.

Guarded resolution reserves the writer after collision rollback and before the measured retirement attempt. It obtains the original receipt and resolves all twelve outcomes, while deferring twelve retirements until the caller releases its reservation. Every controlled retry completes. Retirement winning before reservation acquisition still requires the unavailable fallback; the guarded comparison does not establish uninterrupted protection across the earlier gap or rank performance.

The [findings](RESOLUTION_FINDINGS.md) retain 48 records, 96 verified barriers, 162 complete child invocations and independent reconstruction of all ten criteria. Phase 14 below tests compact retained receipt summaries after old payload removal under a new protocol. Measurement observers remain separate from application authority.

## Extension: preserving evidence requires migrating it atomically

Phase 14 asks what a historical reply actually needs to retain. In this fixture a compact receipt stores epoch, ID, operation, payload SHA-256 and original revision. It removes the request payload BLOB while retaining the fields needed for a replay or parameter conflict, under the stated hash assumption. An update's input digest doubles as its original approval digest; this relationship is specific to the fixture and does not establish a universal minimum representation.

Across twenty repeated requests, retained full, dropped, split-summary and atomic-summary modes return the original outcome 20, 12, 12 and 20 times. Drop and split therefore look equivalent under that aggregate but fail at different boundaries. In eight selected cleanup/summary cuts, the dropping transaction rolls back to full receipts while split migration has already committed deletion and loses every reply. Atomic migration recovers the old full representation at those cuts, then uses compact authority after completion. Completed split migration also resolves correctly; its loss concerns interrupted migration, not fingerprint classification.

The fence keeps every mode from repeating a known effect, and current publication remains valid even when the reply evidence is lost. This separates recovery of current policy from recovery of historical authority. The [findings](COMPACTION_FINDINGS.md) retain 104 records, 64 declared exits, 40 normal completions and an independent recount of ten criteria. The compact design does not erase all old bytes or bound total retained records, and its digest comparison is conditional rather than mathematically injective.

The next question is whether source selection remains complete when another publication overlaps migration. One atomic final transaction cannot repair a source set captured before an intervening commit. That ordering needs a separate live-process protocol before extending this sequential migration claim.
