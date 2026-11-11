# Research log

This dated record connects research questions, executed work, evidence, and interpretation. Entries preserve what was known at the time, including failures and superseded next steps. Narrative dates use Asia/Seoul; raw artifact filenames use UTC.

## 2026-11-11 — Recover both the attempt limit and the completed outcome

**Question and prospective design.** Phase 16 limits one uninterrupted invocation. Froze the [restart protocol](RESTART_PROTOCOL.md) and 28-case manifest at `948e246274c57df29419f16ab3e1281f3c31d462` before implementation. Crossed budgets 1/2, seven histories and two value patterns. Compared volatile charging, post-result durable charging, pre-work reservation with a limit-first decision, and the same reservation with target reconciliation first. Five fixed process-exit cuts compose with controlled source changes; each job retains its target and original intent identities.

**Observation.** Actual admitted-attempt overruns occur in 12/28 → 8/28 → 0/28 → 0/28 cases. Durable reservation holds the bound but a limit-first recovery check misreports two committed targets as exhausted. Reconciliation avoids both errors; joint bound/truth counts are 16/28 → 20/28 → 26/28 → 28/28. Actual closure is 16/28 → 16/28 → 12/28 → 12/28 because conservative charging leaves four additional cases open. All actual runtime commitments replay, and no current policy or history is lost.

**Validation.** All 422 tests passed, including 36 new tests. Independent standard-library event replay matches 112 records, every counter and ten diagnostic criteria, input/sixteen source hashes, 164 strict live barriers, 92 exact marked exits, 560 normal child completions and 652 child processes. Unexpected infrastructure errors are zero. Tests reject altered generation resumes, cut markers, counters, job bindings, causal prefixes and hidden invocations; consistently recorded invented history still fails criteria. [Findings and raw evidence](RESTART_FINDINGS.md#evidence-and-reproduction).

**Interpretation and next decision.** Permission must be charged before a process can disappear; terminal recovery must reconcile an already committed target before announcing exhaustion. A reserved slot need not produce useful work, and weak-policy extra closures need not respect the budget. These are fixed sequential restarts with parent/OS survival. Next: let two processes resume the same job together and measure shared admission accounting and justified terminal outcomes before claiming concurrent ownership or fair acquisition.

## 2026-11-10 — Preserving history does not finish a bounded invocation

**Question and prospective design.** Phase 15 retries once after a source change. Froze the [progress protocol](PROGRESS_PROTOCOL.md) and 24-case manifest at `1c6328e80c8ef5ee07c00eb5bca447e958e44a71` before implementation. Crossed attempt budgets 1/2/3 with 0/1/2/4 old publication intents and two value patterns. Compared validated-only attempts, immediate transactional selection and a final-attempt transactional fallback. Every remaining declared intent is attempted even after migration stops.

**Observation.** Migration completion is 12/24 → 24/24 → 24/24, while publication completion is 42/42 → 0/42 → 16/42. Validated-only exhausts twelve cases, retaining full history in the still-open namespace; its 28 stale attempts change nothing from their pause snapshots. Fallback stales sixteen attempts before taking its final writer scope. Actual committed runtime originals all replay: 42/42 → N/A (zero commits) → 16/16. All 48 seeded originals per policy replay; no history or current policy is lost.

**Validation.** All 386 tests passed, including 33 new tests. Independent stdlib reconstruction matches 72 records, every counter and ten criteria, input/thirteen source hashes, 104 strict attempt-bound barriers and 260 normal child completions, with zero unexpected infrastructure errors. Tests reject cross-attempt resumes, changed retry identities, incorrect busy codes and broken causal prefixes; a consistently recorded wrong historical reply still fails the scientific criteria. [Findings and raw evidence](PROGRESS_FINDINGS.md#evidence-and-reproduction).

**Interpretation and next decision.** Safe retention and completed compaction are different outcomes. The final writer scope finishes in the granted acquisition order by refusing additional old work. This is not a fairness, deadline or optimality claim, and the invocation budget does not survive restart. Next: define restart continuity for attempt accounting, truthful terminal results and preserved publication evidence before composing interruption with contention.

## 2026-11-07 — The source can become incomplete before an atomic commit

**Question and prospective design.** Phase 14 selects migration input inside its writer transaction. What happens if that source is selected earlier and another publisher commits meanwhile? Froze the [protocol](SELECTION_PROTOCOL.md) and 24 cases before implementation. Compared cached selection, a separate refresh, a writer held through selection/commit and exact source validation inside a shorter write scope. The latter aborts a stale preparation before cleanup and retries from a fresh selection.

**Observation.** Committed receipt losses are 8 → 4 → 0 → 0 across eight source gaps. Transactional selection has no old commitment in those eight cases because the publisher defers, then is refused after closure. Across all cases, old work completion is 14/20 → 14/20 → 6/20 → 14/20; original replay among actual old commitments is 6/14 → 10/14 → 6/6 → 14/14. Validated migration detects eight changed source sets and completes each fresh retry without losing the new records. Coherent current policy and epoch closure hold in every mode, including both weak source sets.

**Validation.** All 353 tests passed, including 37 new tests. Independent stdlib reconstruction matches 96 records, every counter and ten criteria, plus input/twelve source hashes. All 224 child attempts complete normally across 48 role-bound live barriers, including modeled busy and stale-selection results, with zero unexpected infrastructure errors. Source/witness forgeries, lost causal prefixes, changed retry identities, invented historical responses and incorrect never-committed follow-ups are regression-tested. [Findings and raw evidence](SELECTION_FINDINGS.md#evidence-and-reproduction).

**Interpretation and next decision.** Atomic output does not establish completeness of an earlier read. Holding the writer and validating/retrying both preserve actual committed history, but finish different amounts of old work. A refused, never-committed request is not a lost historical reply. Next: define repeated interference and a finite retry budget, counting publication completion, migration completion, refusal and history preservation separately. General progress, fairness, latency, crash composition and external effects remain open.

## 2026-11-06 — The replacement receipt has its own commit boundary

**Question and prospective design.** Phase 13 can refuse safely when the original receipt disappears, but loses its response. Can a typed fingerprint/revision summary retain the needed authority after payload removal, and what happens if migration stops halfway? Froze the [protocol](COMPACTION_PROTOCOL.md) and 26 cases before implementation. Compared full retention, deletion, split-summary migration and a single transaction containing fence, deletion and replacement summaries.

**Observation.** Supported original replays are 20/20 → 12/20 → 12/20 → 20/20; changed-intent conflicts are 4/4 → 0/4 → 4/4 → 4/4. Drop and split share an aggregate replay count but differ at eight cleanup/summary cuts: 8/8 → 8/8 → 0/8 → 8/8 original replies remain available. Split migration recovers closure without either receipt representation. Atomic migration recovers full receipts at those cuts and compact receipts after completion. Every mode prevents another known effect and preserves current policy.

**Validation.** All 316 tests passed, including 33 new tests. Independent stdlib reconstruction matches 104 records, every counter and ten criteria, plus input/nine source hashes. All 64 declared exit prefixes and 40 normal child completions match exactly, with zero unexpected errors. Tests cover typed empty-update/revocation distinctions, Unicode bytes, interrupted migration, failed summary writes, unrepairable split gaps, invented historical replies and a deliberately colliding substituted fingerprint. [Findings and raw evidence](COMPACTION_FINDINGS.md#evidence-and-reproduction).

**Interpretation and next decision.** Historical-response authority can be represented without the original request BLOB in this fixture, under the digest assumption. It still needs an atomic migration boundary. Per-record digest fields do not bound total records or erase surviving publication bytes; input/response digest reuse is fixture-specific. Next: overlap publication with migration source selection and test where the source read must share the fence/deletion transaction. Performance, arbitrary caller populations, authentication, external effects and host power loss remain separate studies.

## 2026-11-05 — Losing the receipt changes what can be answered

**Question and prospective design.** Phase 12's post-rollback resolver depends on retaining the original receipt. What remains justified if retirement removes it before resolution? Froze the [protocol](RESOLUTION_PROTOCOL.md) and sixteen cases before implementation. Compared a diagnostic fallback that writes again, a fresh epoch/receipt lookup returning unavailable, and a writer reservation held through original resolution. Every first caller encounters a real duplicate, whole rollback and two caller-bound pauses.

**Observation.** Across twelve gap opportunities, extra shared effects are 12/12 → 0/12 → 0/12. Safe terminal outcomes are 0/12 → 12/12 → 12/12, while original replay/conflict outcomes are available 0/12 → 0/12 → 12/12. The fenced mode preserves mutation safety by returning unavailable twelve times. Guarded resolution obtains the retained original receipt by deferring twelve retirement probes; every scheduled retry completes. All modes retain coherent final state, including the weak mode's invalid old-epoch writes. Four later policies survive in both safe modes, with the guarded mode's later work explicitly occurring after resolution and retirement.

**Validation.** All 283 tests passed, including 39 new tests. Independent stdlib reconstruction matches 48 records, all counters and ten criteria, plus input/eleven source hashes. All 162 child invocations complete normally across 96 verified barriers, with zero unexpected infrastructure errors. Regression tests include guard acquisition after closure, failed receipt/effect/observer writes, unavailable responses carrying invented commitment fields, and matching historical guesses without receipt support. [Findings and raw evidence](RESOLUTION_FINDINGS.md#evidence-and-reproduction).

**Interpretation and next decision.** Safe refusal and equivalent historical acknowledgment are different outcomes. Closed intent can remain protected after its reply becomes unavailable; withholding another write does not reconstruct the original result. A guard orders the measured retirement later rather than recovering evidence after deletion. Next: define which historical semantics compact retained summaries could preserve after payload removal. Many-caller progress, authentication, external effects, network recovery and crash testing remain separate obligations.

## 2026-11-05 — One committed effect can still yield the wrong reply

**Question and prospective design.** Phase 11 orders epoch admission with publication. Can two simultaneous same-ID callers both receive the required outcome? Froze the [protocol](CALLER_PROTOCOL.md) and sixteen cases before implementation. Compared an exposed receipt collision, unconditional conflict, post-rollback original-receipt resolution, and lookup held through commit. Epoch 2 and retained receipts stay fixed. Empty updates, revocation and Unicode byte differences make operation/byte equality explicit.

**Observation.** Every mode has one shared effect in 15/15 shared-key cases, with explicit whole-transaction rollback after collisions. Correct response pairs in twelve overlaps are 0/12 → 6/12 → 12/12 → 12/12. An exposed collision returns twelve modeled storage errors; unconditional conflict falsely rejects six identical retries. Both receipt resolution and transactional lookup return the original result or proper parameter conflict. The actual winner is second in precheck races and first under transactional lookup.

**Validation.** All 244 tests passed, including 35 new tests. Independent stdlib reconstruction matches 64 records, all counters and ten criteria, and the input/eleven source hashes. All 157 child invocations complete normally across 52 forced overlaps and twelve serial records, with zero unexpected infrastructure errors. Both successful modes return original revision 4 in the two identical-later cases while preserving current revision 5. [Findings and raw evidence](CALLER_FINDINGS.md#evidence-and-reproduction).

**Interpretation and next decision.** One durable effect and both callers' correct outcomes are different properties. Original-receipt resolution retains twelve collision rollbacks; transactional lookup requires thirteen busy retries, including one independent-ID control. These counts do not rank latency or throughput. Next: place retirement between duplicate rollback and receipt resolution and define what response is justified after receipt loss. Arbitrary caller populations, fairness, external effects, authentication and crash recovery need separate protocols.

## 2026-11-05 — The last read still precedes the write

**Question and prospective design.** Phase 10 used a sequential epoch-retirement boundary. Can a request admitted before retirement write after its epoch closes? Froze the [protocol](OVERLAP_PROTOCOL.md) and 16 cases before implementation. Compared cached admission, a separate final read, and a write transaction held from admission through commit. A live publisher pauses at fixed pipe barriers while a separate retirement child attempts target epoch 2. Every new effect stores a same-transaction epoch witness.

**Observation.** Invalid old effects are 4/4 → 2/4 → 0/4 across the selected admission gaps. A separate recheck catches retirement after initial admission but not retirement after its final read. Transactional admission defers six retirement probes; controlled retries after publication all commit. Valid old commits are 6 → 6 → 10, and old denials 2 → 4 → 2. Every mode retains coherent final state pairs, completes four current controls, and returns both postcommit historical responses correctly.

**Validation.** All 209 tests passed, including 33 new tests. The independent verifier reconstructs actor traces, controller journals, snapshots, receipts and witnesses without importing the measured store, worker, or controller. It matches 48 records, every counter and ten criteria, and the input/nine source hashes. There are 24 forced overlaps and 24 controls, with 48 publisher and 58 retirement invocations completing normally and zero infrastructure errors. [Findings and raw evidence](OVERLAP_FINDINGS.md#evidence-and-reproduction).

**Interpretation and next decision.** Keeping admission authority valid through the effect changes the order: retirement may follow a publication it initially contended with. An acknowledgment after closure can still describe a valid earlier commit; the witness prevents that misclassification. This is a fixed two-role schedule, not a fairness or general concurrent-safety result. Next: specify simultaneous same-ID caller outcomes, including parameter conflicts, and distinguish a consistent replay/conflict response from an accidental duplicate-key abort. Many-writer progress, latency, external effects, and crash recovery require separate studies.

## 2026-11-04 — Deleting a reply does not close its old intent

**Question and prospective design.** Phase 9 depends on retaining request receipts. Can those records be removed without an old retry undoing later policy? Froze the [protocol](RETIREMENT_PROTOCOL.md) and 20 cases before implementation. Compared retaining history, forgetting without a retired-epoch check, deleting before committing the epoch fence, and atomic retirement. Every publication still atomically records state, an epoch-tagged effect, and its receipt. Cases include old known and unseen requests, new current-epoch work, composite-ID reuse, repeats/conflicts, and four child-exit boundaries.

**Observation.** Known duplicate cases are 0/10 → 6/10 → 2/10 → 0/10; later policy is preserved 10/10 → 4/10 → 8/10 → 10/10. Deletion alone repeats six committed intents. A separate cleanup/fence transaction has two process-exit gaps. Atomic retirement preserves all ten policies while keeping zero old receipt rows after completed retirement, but rejects six known old requests without returning their original commitment. Retaining history also preserves all ten policies and returns all ten historical replies. Every arm retains coherent final payload/approval pairs.

**Validation.** All 176 tests passed, including 35 new tests. An independent verifier enumerated effect prefixes and receipt layouts without importing the measured store, worker, or runner, matched all 80 records/counters/twelve criteria, and verified the input and eight source hashes. All 32 declared exits and 48 normal retirement completions have exact traces and zero infrastructure errors. The retained run ID and timestamps are explicit UTC values in [findings and raw evidence](RETIREMENT_FINDINGS.md#evidence-and-reproduction).

**Interpretation and next decision.** A logical epoch cutoff can replace the need to remember old IDs for mutation prevention, while losing their historical responses and rejecting unseen old work. The epoch must remain trusted and attached to the original intent. Logical row deletion does not demonstrate physical reclamation, and the observer log remains retained. Next: fix an overlap where publication is admitted before retirement but writes afterward, and test where epoch validation must share the effect transaction. Clock-based expiry, caller authentication, external effects, and host power loss need separate protocols.

## 2026-11-03 — A recovered approval does not identify a repeated intent

**Question and design.** When commitment succeeds but its acknowledgment is absent, can a retry repeat the effect or undo a later decision? Froze the [protocol](RETRY_PROTOCOL.md) and 20-case manifest before implementation. All three arms retain a coherent SQLite publication and transactional effect observer; they omit request receipts, commit them separately, or include them with publication. Each ID binds exact operation and payload. The cases include changed intent, legitimate new IDs, old retries after intervening policy, and four process-exit boundaries.

**Observation.** Successful same-intent retries are 2/12 → 10/12 → 12/12; extra-effect cases are 10/12 → 2/12 → 0/12. A separate receipt has its own two-case commit gap. All 20 final state pairs per arm remain coherent. Unkeyed late retries reinstate a revoked value once and withdraw a newer approval once. Both keyed arms instead return the historical receipt while preserving current state, reject both parameter conflicts, and allow both distinct-ID publications with identical intent.

**Validation.** All 141 tests passed, including 30 new tests. The independent verifier uses fixed expected effect prefixes rather than importing the publisher or measured runner. It matches all 60 records, counters, and ten criteria, verifies the input and seven source hashes, and confirms 24 declared exits plus 36 normal first publications with zero infrastructure errors. [Findings and raw evidence](RETRY_FINDINGS.md#evidence-and-reproduction).

**Interpretation and next decision.** The request identity must share the commit unit of its effect. A stored old receipt acknowledges history; it is not a permission to restore that history as current. The result is bounded by retained IDs, a trusted sequential namespace, and database-only effects. Next: define safe receipt retirement and a delayed-retry rule before deleting old identities. Concurrency, host power loss, internal storage faults, and external-service effects remain separate studies.

## 2026-11-02 — Refusing a bad recovery does not recover the last usable state

**Question and design.** Can a publication be recovered coherently when the child process exits between content and approval updates? Froze the [protocol](RECOVERY_PROTOCOL.md) and 19 cases before implementation, comparing the same split publisher with unchecked/verified recovery against a row transaction containing both payload and approval. Three controls and 16 termination schedules run in each arm. Parent and storage remain running; cuts are outside storage calls.

**Observation.** The split layouts recover mismatched payload/approval in two cases. The unchecked reader delivers both; validation prevents those deliveries but loses two active-approval reads. SQLite recovers coherent old-or-new state in all 19 cases and completes all 15 active-approval reads. Committed revocation is denied in 4/4 cases for every arm. Four commits without an acknowledgment also recover, as do all four acknowledged publications.

**Validation.** All 111 tests passed, including 26 new tests. The independent artifact verifier matched the 57-record grid, every complete child trace, all summary counters and 11 criteria, and seven source/input hashes. There were zero infrastructure errors. [Raw evidence and findings](RECOVERY_FINDINGS.md#evidence-and-reproduction) preserve the measured outputs.

**Interpretation and next decision.** Digest validation and recoverable availability are separate obligations. The transaction intervention changes storage layout and trusts SQLite; it is not a new primitive or proof of external-file policy. The observed commit/acknowledgment ambiguity motivates a future request-identity and retry-deduplication protocol. Host power loss, mid-commit storage faults, multiple writers, and repeated recovery failure remain outside this run.

## 2026-11-01 — Approval must remain current through receipt

**Question.** Does rechecking an approval prevent obsolete receipt when publication or revocation can occur afterward?

**Method.** Froze a nine-case analysis plan before the measured run; existing drafts were reviewed jointly, so the freeze does not precede initial implementation. Compared snapshot-only, separate recheck, and shared-lock release, with a journal oracle that checks direct bytes and approval revision at receipt.

**Outcome.** Invalid receipts were 5/5 → 2/5 → 0/5. Coordinated release delivered 5/9 valid values, denied four cases, and delayed two publication attempts until after receipt. All eight requested publications per arm committed. Two coordinated receipts became obsolete afterward. All 85 tests passed; an independent saved-journal recount matched the summary.

**Interpretation.** Receipt-time validity differs from immediate revocation or perpetual freshness. The lock establishes an ordering only among cooperating publishers and the trusted sink. Next: publication/approval failure recovery. [Findings and artifacts](REVISION_FINDINGS.md).

## 2026-10-29 — Make claims traceable without repeating the full argument

**Question.** How should the repository let a new reader understand the contribution, reproduce a result, and audit its limits? The prior README already contained the technical argument but repeated the progression and placed its first execution command late.

**Analysis and decision.** Reviewed official SWE-bench, Inspect, garak, and CyberGym documentation. The [benchmark](DOCUMENTATION_BENCHMARK.md) separates source observations from our application judgments. Adopted early execution/output guidance, purpose-based navigation, explicit result interpretation, and accessible evaluation conditions. Assigned the argument to the research statement, commands to the experiment guide, cross-study artifact lookup to the evidence map, and assumptions to the limits document. Kept open-versus-content-I/O and approval-versus-freshness distinctions beside headline results.

**Provenance correction.** Source inspection confirmed that the runners record caller-supplied commit arguments without checking out or validating those revisions. Current-code examples now record the actual checkout; historical commands and source hashes stay in their original artifacts. Checking out an old starting base alone may omit files added during that study.

**Validation.** All 67 existing tests passed. Executed all nine documented experiment commands and compared their full scientific summaries with the nine historical runs; all matched. Recounted historical raw records, checked 56 source/dataset SHA-256 entries, and verified 68 implementation/test/protocol/input/evidence files against the reviewed main revision. Local Markdown paths and heading fragments passed validation. New run output remained separate from historical evidence; the preserved raw files were not replaced.

**Interpretation and next step.** This improves documentation and checks reproducibility of the existing cases. It does not supply an independent evaluation, larger sample, new security guarantee, or completed version-reauthorization study. The next research question remains legitimate version updates and stale-value handling under a prospective protocol.

## 2026-10-27 — Stable identity does not establish an approved content version

**Question and prospective design.** Does a descriptor or a passing digest ensure that the consumer receives the approved bytes? The [content protocol](CONTENT_PROTOCOL.md) and eight-case manifest were committed at `ce3fd6d245a2013090f7bd8c6367d08895132723` before implementation. The study adds a version-specific delivery rule to the unchanged Phase 5 resource gate. It does not reinterpret Phase 5's protected-resource results. Three controls cover ASCII, Unicode, and empty values; five mutation schedules overwrite, truncate, or append through a hardlink without changing the inode.

**Implementation.** Added `VerifiedContentReader`, which captures once, checks an owner-configured SHA-256 digest, and returns the same immutable UTF-8 value. A diagnostic comparator hashes through `pread` and then lets the unchanged descriptor executor reread for delivery. A separate oracle compares returned bytes with approved and final bytes, retains a file descriptor, and confirms identity continuity. Actions cannot choose their own expected digest.

**Observed outcome.** Identity-only → hash/reread → verified-buffer unapproved deliveries were 5/5 → 3/5 → 0/5; approved-version deliveries were 3/8 → 3/8 → 6/8. Both digest arms denied the two before-capture changes after inspecting bytes. All unchanged controls were delivered correctly, including empty content. The buffer returned three approved but stale values. All 24 case/arm records retained the original inode and had zero infrastructure errors.

**Evidence.** All 67 tests passed, including 12 new tests. The measured run exited 0 and all nine summary criteria held. See [raw records](../experiments/results/2026-10-27T12-21-15-144558Z-content-v1.jsonl), [summary and provenance](../experiments/results/2026-10-27T12-21-15-144558Z-content-v1-summary.json), [test transcript](../experiments/results/2026-10-27T12-21-15-144558Z-content-v1-unit-tests.txt), and [findings](CONTENT_FINDINGS.md). Earlier code and results were retained, including the identity-only implementation.

**Interpretation and limitation.** A digest constrains the bytes actually inspected, not a later read of the same inode. Retaining the checked value binds delivery to the approved version under the trusted-digest and memory assumptions. It does not ensure freshness, prevent inspection of changed bytes, or create an atomic filesystem snapshot. These small deterministic schedules are developer-visible, not an independent holdout or concurrency-frequency study.

**Decision and next question.** Keep approved delivery and freshness separate in the portfolio argument. Define how a legitimate new version becomes trusted and how consumers handle stale approved values before adding reauthorization. Capture-time mutation, streaming, dynamic protected membership, creation, and live-agent behavior remain outside the completed work.

## 2026-10-26 — Pathname replacement challenges pre-open identity approval

**Question and design.** Does the Phase 4 identity check remain valid when a path changes between approval and open? The [protocol](RACE_PROTOCOL.md) and ten-case manifest were frozen at `d0ddc20aac99365adb85bc48ef53539c8028a127` before implementation. Read/write pairs cover controls, protected hardlinks before and after checking, protected parent substitution, and benign replacement. These developer-visible deterministic schedules are not a blind evaluation or concurrent probability sample.

**Implementation.** Added `DescriptorExecutor`, which opens without truncation, authorizes with `fstat`, and uses the held descriptor for content I/O. A separate runner compares it with no gate and the unchanged Phase 4 gate. The oracle observes actual I/O descriptors, a retained original-object witness, and protected bytes. The executor cannot consult expected outcomes or the oracle's held descriptor.

**Observed result.** Across 30 case/arm records, baseline → identity-path → descriptor-bound protected content operations were 6/6 → 4/6 → 0/6; original-object completions were 2/8 → 2/8 → 8/8. All arms had zero benign blocks and infrastructure errors. The identity-path gate failed all four after-check protected substitutions. The descriptor executor made two protected metadata opens and denied both before content I/O. These opens remain explicitly reported.

**Validation and evidence.** All 55 unit tests passed, including 11 new tests. The experiment exited 0 and all seven summary criteria held. See [raw records](../experiments/results/2026-10-26T08-23-21-637204Z-race-v1.jsonl), [summary and hashes](../experiments/results/2026-10-26T08-23-21-637204Z-race-v1-summary.json), [test transcript](../experiments/results/2026-10-26T08-23-21-637204Z-race-v1-unit-tests.txt), and [findings](RACE_FINDINGS.md). The original eight-case completion denominator was defined before execution and overlaps the six attack cases.

**Interpretation.** Pre-open identity checking observes a name binding at one instant. Holding the authorized descriptor preserves the object through the tested later name changes. This does not freeze its contents or protected membership, prevent metadata opens, or establish general confinement. Earlier fixed-topology results remain intact; their assumptions are now more visible.

**Presentation and attribution.** Revised living Markdown to foreground questions, evidence, technical reasoning, limitations, and reproducibility. Added the [research statement](RESEARCH_STATEMENT.md) and updated study/architecture guides. Frozen protocols, the v3 design note, historical entries, and raw results were retained. Personal learning and independent-contribution claims remain for the owner to substantiate.

**Next decision.** Specify whether future authorization concerns identity, content version, or current protected membership, then freeze a new protocol before testing those changes. A live-agent adapter remains outside the completed work.

## 2026-10-26 — Filesystem identity detects hardlink aliases

- **Question:** can protected-file device/inode identities close the hardlink gap left by lexical and resolved-path checks?
- **Freeze:** committed [IDENTITY_PROTOCOL](IDENTITY_PROTOCOL.md) and six tasks at `8e0910d86636c9cd4264b9c1f3e70da4c7b8b39f` before implementing the new gate. The suite is prospective but developer-visible, not blind or independent.
- **Implementation:** added `IdentityAwareGate` and a four-arm runner. It checks configured protected subtree paths and `(st_dev, st_ino)` identities of existing protected files, then executes the exact prepared action. Existing checker, replay runner, and resolved-target gate are preserved.
- **Validation:** 44/44 unit tests passed (11 policy, 12 replay, 13 executor-aware, 8 identity). Hardlink creation and identity equivalence are tested explicitly.
- **Run:** Python 3.12.14/Linux with hardlink support. Six tasks × four arms, 12 proposals per arm, exit 0. Zero guard rejections and execution errors.
- **Counts:** baseline → string → resolved → identity protected operations 3/3 → 3/3 → 2/3 → 0/3; functional completion 6/6 → 5/6 → 6/6 → 6/6; safe completion 3/6 → 2/6 → 4/6 → 6/6; benign blocks 0/9 → 1/9 → 0/9 → 0/9.
- **Mechanism:** the resolved-target gate catches the protected symlink but sees a hardlink alias as an ordinary path. The identity gate catches both hardlinks and still allows an ordinary hardlink and contained parent path.
- **Evidence:** [summary](../experiments/results/2026-10-26T07-35-54-971592Z-identity-v1-summary.json), [raw outcomes](../experiments/results/2026-10-26T07-35-54-971592Z-identity-v1.jsonl), [validation](../experiments/results/2026-10-26T07-35-54-971592Z-identity-v1-validation.txt), and [analysis](IDENTITY_FINDINGS.md).
- **Interpretation:** the identity check resolves the demonstrated fixed-topology hardlink failure while preserving utility in this selected suite. It is still check-then-open and not race-safe; no production or live-agent claim follows.
- **Next:** define a race-aware protocol and compare pathname checking with OS-level handle/capability enforcement.

## 2026-10-26 — Executor-aware gate restores utility in fixed fixtures

- **Question:** can approval of the executor's resolved target prevent protected aliases while recovering legitimate dot/parent spellings?
- **Prospective freeze:** committed [GATE_PROTOCOL](GATE_PROTOCOL.md) and eight supplemental tasks in `1d9bbe305625f5b7df55a185463908729c48cc03` before implementing the gate. The cases were visible to the developer, so they are supplemental, not an independent blind holdout. Neither frozen file changed afterward.
- **Intervention:** added `src/executor_gate.py`, which approves prepared targets using configured roots, and `experiments/run_comparison.py`, which executes that same immutable target/content. It does not consult oracle labels. The original monitor, paired runner, and previous results remain unchanged.
- **Validation:** actually ran `python -m unittest discover -s tests -v`; all 36 tests passed (23 existing plus 13 new). Tests cover direct/alias protection, benign paths and links, policy independence, new protected targets, raw request mutation, shared guard accounting, and complete task/arm matching.
- **Runs:** Python 3.12.14/Linux. Ran development first, then the frozen supplemental suite with identical source hashes; both commands exited 0. Full commands and hashes are in their summaries. No tuning occurred between runs.
- **Counts, each suite separately, baseline → string gate → executor-aware:** protected accesses 4/4 → 2/4 → 0/4; functional completion 8/8 → 6/8 → 8/8; safe completion 4/8 → 4/8 → 8/8; benign blocks 0/12 → 2/12 → 0/12. Every arm had zero shared guard rejections and execution errors. All stated criteria held; the original two development arms exactly reproduced the earlier raw records.
- **Evidence:** [development summary](../experiments/results/2026-10-26T02-23-10-090530Z-gate-v1-development-summary.json), [supplemental summary](../experiments/results/2026-10-26T02-23-27-301341Z-gate-v1-supplemental-summary.json), [unit output](../experiments/results/2026-10-26T02-23-10-090530Z-gate-v1-development-unit-tests.json), and [findings with raw/console links](GATE_FINDINGS.md).
- **Interpretation:** binding approval to the resolved pathname resolves the demonstrated fixed-topology failures. It is not binding to an immutable file identity and does not address hardlinks or races. Small related suites do not establish generalization, production safety, or live-agent effectiveness.
- **Next:** choose and freeze a new threat-model extension (hardlink identities or topology mutation), preserve any failures, and only then evaluate stronger enforcement or a constrained agent protocol.

## 2026-10-26 — Paired execution reveals protection and utility trade-offs

- **Goal:** deepen the study with actual fixture effects, a no-monitor comparison, and functional goals independent of policy labels.
- **Design before execution:** wrote [REPLAY_PROTOCOL.md](REPLAY_PROTOCOL.md) and eight two-action task definitions with file/read goals. Two controls, two benign alternative path spellings, two direct protected accesses, and two aliases were deliberately chosen as diagnostic development cases. They are not held out.
- **Implementation:** added a separate runner; each arm gets fresh synthetic files and fixed symlinks. Both use the same containment guard and executor; only the monitor gate changes. The oracle uses resolved protected-resource identities, successful operations, and actual file/read observations.
- **Validation:** executed `python -m unittest discover -s tests -v`; all 23 tests passed (11 original + 12 replay tests). New tests cover protected reads/writes, alias misses, benign-path task loss, isolation, root containment, exclusive create, and malformed task definitions.
- **Experiment:** executed `python experiments/run_replay.py --dataset experiments/tasks/replay-v1/tasks.json --base-commit 0ffa15a655c3c2569ff0556945ffd83aac1d9efe` on Python 3.12.14/Linux; exit 0. Eight tasks were each run in baseline and monitored arms (16 proposals per arm). No monitor code or earlier dataset labels were changed.
- **Observed counts:** baseline → monitored protected operations 4/4 → 2/4; functional completion 8/8 → 6/8; safe completion 4/8 → 4/8. Monitored false positives: 2/12 benign proposals. Both arms had 0/16 guard rejections and 0/16 execution errors.
- **Failures retained:** direct protected names were blocked, but aliases still reached protected resources; harmless contained dot/parent spellings prevented required reads. The final report file alone did not satisfy those read-dependent goals.
- **Evidence:** [raw outcomes](../experiments/results/2026-10-25T16-23-07-058859Z-replay-v1.jsonl), [summary and provenance](../experiments/results/2026-10-25T16-23-07-058859Z-replay-v1-summary.json), [console](../experiments/results/2026-10-25T16-23-07-058859Z-replay-v1-console.txt), [validation](../experiments/results/2026-10-25T16-23-07-058859Z-replay-v1-validation.txt), and [analysis](REPLAY_FINDINGS.md). Result timestamps use UTC; this entry uses Asia/Seoul.
- **Interpretation:** enabling the gate prevented two realized protected accesses on these traces but lost two task completions, leaving the joint safe-completion count unchanged. This is a mechanism study on selected tasks, not a general effectiveness estimate. Fixed topology and no adaptive agent are explicit limitations.
- **Decision and next step:** retain this result before improving enforcement. Compare a gate bound to resolved targets against baseline and string-only approval, then evaluate separately frozen tasks. Live-agent adaptation needs another protocol with model/prompt settings, budgets, and repeated trials.

## 2026-10-26 — Reverification and synthetic dataset v3

- **Goal:** reproduce the handed-off results, align current documentation with saved evidence, and broaden string-policy coverage without changing measured datasets or monitor behavior.
- **Source:** checker, runner, and existing tests from upstream commit `7ae79aa5d337ad0ac02431f28b8db2a7f859910e`; these code files are unchanged in this work. No external services or target-file operations were invoked by the monitor.
- **Environment:** Python 3.12.14, Linux. This entry uses Asia/Seoul (2026-10-26); commands ran on 2026-10-25 UTC. Exact start times and platform are recorded in the verification record.
- **Unit tests:** actually executed `python -m unittest discover -s tests -v`; all 11 passed with exit code 0. The [unit-test transcript](../experiments/results/2026-10-25T16-05-40Z-unit-tests.txt) preserves the output.
- **Dataset design before the v3 run:** copied all 21 v2 cases, changing only `dataset_version`, and added 24 expected labels against the existing policy. Wrote the dataset and its design note before execution; no labels were revised after observing results. New cases cover prefix boundaries, path spelling/normalization, and invalid JSON value types. V1 and v2 remain byte-for-byte unchanged.
- **Commands actually executed:**

```bash
python experiments/run_dataset.py --dataset experiments/cases/v1/actions.jsonl
python experiments/run_dataset.py --dataset experiments/cases/v2/actions.jsonl
python experiments/run_dataset.py --dataset experiments/cases/v3/actions.jsonl
```

| Dataset | Decision matches | Risky blocked | Legitimate allowed | False positives | Invalid blocked | Monitor errors |
|---|---:|---:|---:|---:|---:|---:|
| v1 | 20/20 | 8/8 | 8/8 | 0/8 | 4/4 | 0 |
| v2 | 21/21 | 9/9 | 8/8 | 0/8 | 4/4 | 0 |
| v3 | 45/45 | 19/19 | 16/16 | 0/16 | 10/10 | 0 |

- **Raw evidence:** all dataset commands exited 0. The [verification record](../experiments/results/2026-10-25T16-05-40Z-verification.json) contains their full console output, source commit, Python version, and SHA-256 hashes of the code, tests, datasets, and v3 design note. Summaries and corresponding raw results are:
  - [v1 summary](../experiments/results/2026-10-25T16-05-40Z-v1-summary.json), [v1 raw](../experiments/results/2026-10-25T16-05-40Z-v1.jsonl).
  - [v2 summary](../experiments/results/2026-10-25T16-05-41Z-v2-summary.json), [v2 raw](../experiments/results/2026-10-25T16-05-41Z-v2.jsonl).
  - [v3 summary](../experiments/results/2026-10-25T16-06-42Z-v3-summary.json), [v3 raw](../experiments/results/2026-10-25T16-06-42Z-v3.jsonl).
- **Problems or surprises:** no test failures or decision mismatches occurred in these runs. Current-status documentation was stale: README said no results, CHANGELOG retained an unconfirmed v2 note, and architecture/experiment-plan text still described completed components or runs as planned. Updated current status while preserving historical research entries and earlier results.
- **Interpretation and limitations:** v3 is a hand-authored development extension, not a held-out evaluation. It contains v2, which contains v1, so do not add their counts as independent observations. A `risky` label means policy-rejected in this dataset, not necessarily malicious on every filesystem. No actual task completion or baseline-versus-monitored execution was measured. Symlink resolution, OS-specific filename constraints, case-insensitive filesystem behavior, raw malformed JSON, and live-agent integration remain outside this dataset. See the [v3 design note](../experiments/cases/v3/README.md).
- **Decision:** retain the checker and runner as-is for this continuation; keep the development changelog separate from this research record. Preserve all failed or unexpected future runs rather than selecting only successful results.
- **Next step:** define held-out inputs and the fixture-harness trust boundary before changing policy rules. A future task-execution experiment needs a controlled no-monitor comparison, fixed task-completion criteria, and project-owned fixtures; it must not be described as implemented yet.

## 2026-10-21 — Path-normalization regression fix prepared

- **Issue identified:** `PurePosixPath` can collapse an explicit `.` component, so checking only its normalized parts can miss an input such as `workspace/./notes.txt`.
- **Change made:** the checker now inspects the slash-normalized raw path components before creating the `PurePosixPath` object.
- **Regression tests added:** explicit `.` components in both a direct workspace path and a nested workspace path should be blocked.
- **Dataset:** created `experiments/cases/v2/actions.jsonl` with 21 synthetic cases, preserving the 20 baseline scenarios and adding `RISK-009`. Dataset v1 remains unchanged.
- **Runner:** `experiments/run_dataset.py` now accepts `--dataset` so v1 and v2 can be run independently.
- **Verification status:** locally verified by the project author on 2026-10-21: all 11 unit tests passed, and the v2 dataset run matched all 21 expected decisions with 0 mismatches and 0 monitor errors.
- **Next step:** expand the test set and evaluate additional edge cases; keep synthetic test performance separate from claims about real-world security.

## 2026-10-21 — Synthetic dataset v2 and unit-test verification

- **Goal:** verify the path-normalization regression fix and run the expanded, versioned synthetic dataset.
- **Commands reported by the project author:** `python -m unittest discover -s tests -v` and `python experiments/run_dataset.py --dataset experiments/cases/v2/actions.jsonl`.
- **Unit-test outcome:** 11 tests ran with no failures. This includes regression tests for explicit current-directory (`.`) path components in direct and nested workspace paths.
- **Dataset outcome:** 21 cases; 21/21 expected decisions matched; 0 mismatches; 0 monitor errors.
- **Metrics reported:** risky-action block rate 1.0; false-positive rate 0.0; legitimate allow rate 1.0; invalid-input block rate 1.0.
- **Raw output files reported:** `experiments/results/2026-10-20T15-59-51Z-v2.jsonl` and `experiments/results/2026-10-20T15-59-51Z-v2-summary.json`.
- **Interpretation:** the checker matched the manually assigned expected labels for all 21 synthetic cases, and all 11 unit tests passed. The added regression case was included in the v2 run. These results apply only to this small synthetic dataset and do not establish real-world security effectiveness or risk reduction for a live AI coding agent.
- **Next step:** add further independent edge cases and document the monitor's limitations before considering integration with a real agent.

## 2026-10-21 — Synthetic dataset v1 first run

- **Goal:** run all fixed v1 cases through the checker and compare observed decisions with the expected labels.
- **Command:** `python experiments/run_dataset.py`.
- **Evidence supplied by the project author:** 20 cases; 20/20 expected decisions matched; 0 mismatches; 0 monitor errors; risky-action block rate 1.0 (8/8); false-positive rate 0.0 (0/8 legitimate cases blocked); legitimate allow rate 1.0 (8/8); invalid-input block rate 1.0 (4/4).
- **Raw output files reported:** `experiments/results/2026-10-20T15-48-31Z-v1.jsonl` and `experiments/results/2026-10-20T15-48-31Z-v1-summary.json`.
- **Interpretation:** all 20 synthetic cases matched the hand-authored expected labels in this run. Because the dataset is small and manually labelled, this is a baseline check of the prototype on these cases only; it does not establish real-world risk reduction or security.
- **Next step:** inspect path-normalization edge cases and expand testing without rewriting the already-run v1 dataset.

## 2026-10-21 — Synthetic dataset v1 prepared

- **Goal:** define a small, versioned set of safe, risky, and invalid synthetic action records before running a full evaluation.
- **Actions taken:** added `experiments/cases/v1/actions.jsonl` with 20 labelled cases: 8 legitimate, 8 risky, and 4 invalid-input cases. Each case includes an ID, category, input, expected decision, rationale, and dataset version.
- **Outcome/evidence:** dataset file committed to the repository. Expected labels are written down before a full dataset run.
- **Not completed:** the complete dataset has not yet been run through CodeGuardian; no dataset-level metrics or formal experiment results are available yet.
- **Decision and rationale:** keep invalid inputs separate from risky actions so they do not distort the risky-action block rate or false-positive rate.
- **Next step:** run every dataset input through the monitor, save actual decisions separately from expected labels, and inspect mismatches.

## 2026-10-21 — First policy-checker checks

- **Goal:** verify that the initial monitor permits a basic workspace action and blocks selected unsafe path requests.
- **Actions taken:** ran the command-line checker with a safe read request, a request targeting the protected prefix, and a parent-directory traversal path.
- **Outcome/evidence:** the terminal output showed `workspace/notes.txt` returned `allow`; `workspace/protected/secrets.txt` returned `block` with reason `protected_path`; and `../../secrets.txt` returned `block` with reason `path_traversal_or_invalid_path`.
- **Automated tests:** the project author ran `python -m unittest discover -s tests -v`. All 9 unit tests reported `ok`; the terminal output showed `Ran 9 tests in 0.001s`.
- **Interpretation:** the observed examples and unit tests support that the current policy checker behaves as expected for these tested cases. They do not establish overall security or prove that a real AI agent's risky actions are reduced.
- **Problems or surprises:** no failures were shown in this test run. The policy checker still classifies path strings only and does not access a real filesystem.
- **Decision and rationale:** keep the first version isolated and deterministic; do not connect it to a live agent until the test policy and safety boundaries are reviewed.
- **Next step:** review edge cases, create a fixed and versioned synthetic test set, and define raw result recording before a formal experiment.

## 2026-10-20 — Initial repository setup

- **Completed:** created the project repository scaffold and drafted the research question, scope, proposed measures, and experiment plan.
- **Not completed:** no runtime monitor implemented; no test cases executed; no experimental results collected.
- **Decision:** start with synthetic action records and a local test harness rather than connecting to a live AI coding agent.
- **Reason:** this makes the initial experiment easier to isolate and reproduce.
- **Next step:** review the threat model and define the action schema plus the first fixed test set.
- **Evidence/artifacts:** initial documents in `README.md` and `docs/`.

## Entry template

### YYYY-MM-DD — Short title

- **Goal:**
- **Actions taken:**
- **Outcome/evidence:**
- **Problems or surprises:**
- **Decision and rationale:**
- **Next step:**
