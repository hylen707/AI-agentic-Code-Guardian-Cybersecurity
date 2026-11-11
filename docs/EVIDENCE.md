# Claims and evidence

This map connects the seventeen completed stages to their conditions, denominators, and retained artifacts. Counts describe the selected cases. The [evaluation standards](EXPERIMENT_PLAN.md) define the metrics; [threat model and limits](LIMITATIONS.md) bound their interpretation.

## Phases 1 and 2: labels versus resource effects

Phase 1 records 20/20, 21/21, and 45/45 expected-label matches for v1, v2, and v3. These versions are nested, not independent samples. Phase 2 then executes eight tasks in two fresh-fixture arms (16 task/arm records).

| Replay outcome | Baseline | String gate |
|---|---:|---:|
| Protected operations / protected proposals | 4/4 | 2/4 |
| Functional task completion | 8/8 | 6/8 |
| Safe task completion | 4/8 | 4/8 |

Two direct protected operations are blocked, two symlink aliases escape, and two benign path spellings lose legitimate completion. A passing label test therefore does not establish resource protection or an improvement in safely completed work. [Replay findings](REPLAY_FINDINGS.md) explain the task goals and negative result.

## Phases 3 and 4: resolved names and file identities

| Study | Compared arms | Protected operations | Safe completion |
|---|---|---|---|
| Phase 3 development: 8 tasks, 24 records | Baseline → string gate → resolved gate | 4/4 → 2/4 → 0/4 | 4/8 → 4/8 → 8/8 |
| Phase 3 supplemental: 8 tasks, 24 records | Baseline → string gate → resolved gate | 4/4 → 2/4 → 0/4 | 4/8 → 4/8 → 8/8 |
| Phase 4: 6 tasks, 24 records | Baseline → string gate → resolved gate → identity gate | 3/3 → 3/3 → 2/3 → 0/3 | 3/6 → 2/6 → 4/6 → 6/6 |

Phase 3 approves the resolved target under static topology; its two related suites stay separate. The supplemental cases were frozen before implementation but remained developer-visible. Phase 4 introduces hardlinks: different resolved names can share device/inode identity. Checking configured protected identities closes the two hardlink misses, while still depending on no later pathname replacement. [Gate findings](GATE_FINDINGS.md) · [Identity findings](IDENTITY_FINDINGS.md).

## Phase 5: preserve the authorized object

Ten deterministic replacement cases run in three arms (30 records). Six are attack schedules; eight are eligible for original-object completion. Those sets overlap and must not be added.

| Outcome | Baseline | Identity-path | Descriptor-bound |
|---|---:|---:|---:|
| Protected content operations / attack schedules | 6/6 | 4/6 | 0/6 |
| Protected opens / attack schedules | 6/6 | 4/6 | 2/6 |
| Original-object completion / eligible cases | 2/8 | 2/8 | 8/8 |
| Benign blocks / benign cases | 0/4 | 0/4 | 0/4 |
| Infrastructure errors | 0 | 0 | 0 |

Opening without truncation, authorizing with `fstat`, and retaining the same descriptor prevents the selected after-check redirections. The two before-check protected substitutions still cause metadata opens followed by denial. Zero protected content operations is not zero protected opens. These are selected orderings, not concurrent race win rates. [Replacement findings](RACE_FINDINGS.md).

## Phase 6: deliver the validated value

Eight cases run in three arms (24 records): three unchanged ASCII/Unicode/empty controls and five same-inode mutation schedules.

| Outcome | Identity-only | Hash/reread | Verified buffer |
|---|---:|---:|---:|
| Unapproved deliveries / mutation cases | 5/5 | 3/5 | 0/5 |
| Approved deliveries / all cases | 3/8 | 3/8 | 6/8 |
| All deliveries / all cases | 8/8 | 6/8 | 6/8 |
| Content-version denials / all cases | 0/8 | 2/8 | 2/8 |
| Approved control deliveries / controls | 3/3 | 3/3 | 3/3 |
| Approved but stale deliveries / all cases | 0/8 | 0/8 | 3/8 |
| Infrastructure errors | 0 | 0 | 0 |

Both digest arms inspect and deny two before-capture changes. Only the buffer retains the approved value through three after-validation changes; those three deliveries are stale relative to the final live bytes. The content rule permits inspection and does not promise freshness. The identity-only arm never implemented this new delivery rule. [Content findings](CONTENT_FINDINGS.md).

## Artifact index

Raw links contain case/arm records; summary links contain counts and, for filesystem studies, provenance and source hashes. The policy verification record supplies additional input/source checks for Phase 1.

| Stage/run | Manifest | Raw records | Summary |
|---|---|---|---|
| 1 · v1 | [Input](../experiments/cases/v1/actions.jsonl) | [JSONL](../experiments/results/2026-10-25T16-05-40Z-v1.jsonl) | [JSON](../experiments/results/2026-10-25T16-05-40Z-v1-summary.json) |
| 1 · v2 | [Input](../experiments/cases/v2/actions.jsonl) | [JSONL](../experiments/results/2026-10-25T16-05-41Z-v2.jsonl) | [JSON](../experiments/results/2026-10-25T16-05-41Z-v2-summary.json) |
| 1 · v3 | [Input](../experiments/cases/v3/actions.jsonl) | [JSONL](../experiments/results/2026-10-25T16-06-42Z-v3.jsonl) | [JSON](../experiments/results/2026-10-25T16-06-42Z-v3-summary.json) |
| 2 · replay | [Input](../experiments/tasks/replay-v1/tasks.json) | [JSONL](../experiments/results/2026-10-25T16-23-07-058859Z-replay-v1.jsonl) | [JSON](../experiments/results/2026-10-25T16-23-07-058859Z-replay-v1-summary.json) |
| 3 · development | [Input](../experiments/tasks/replay-v1/tasks.json) | [JSONL](../experiments/results/2026-10-26T02-23-10-090530Z-gate-v1-development.jsonl) | [JSON](../experiments/results/2026-10-26T02-23-10-090530Z-gate-v1-development-summary.json) |
| 3 · supplemental | [Input](../experiments/tasks/gate-eval-v1/tasks.json) | [JSONL](../experiments/results/2026-10-26T02-23-27-301341Z-gate-v1-supplemental.jsonl) | [JSON](../experiments/results/2026-10-26T02-23-27-301341Z-gate-v1-supplemental-summary.json) |
| 4 · identity | [Input](../experiments/tasks/identity-eval-v1/tasks.json) | [JSONL](../experiments/results/2026-10-26T07-35-54-971592Z-identity-v1.jsonl) | [JSON](../experiments/results/2026-10-26T07-35-54-971592Z-identity-v1-summary.json) |
| 5 · replacement | [Input](../experiments/tasks/race-eval-v1/tasks.json) | [JSONL](../experiments/results/2026-10-26T08-23-21-637204Z-race-v1.jsonl) | [JSON](../experiments/results/2026-10-26T08-23-21-637204Z-race-v1-summary.json) |
| 6 · content | [Input](../experiments/tasks/content-eval-v1/tasks.json) | [JSONL](../experiments/results/2026-10-27T12-21-15-144558Z-content-v1.jsonl) | [JSON](../experiments/results/2026-10-27T12-21-15-144558Z-content-v1-summary.json) |

[Phase 1 verification](../experiments/results/2026-10-25T16-05-40Z-verification.json) · [Phase 5 consistency check](../experiments/results/2026-10-26T08-23-21-637204Z-race-v1-verification.json) · [Phase 6 consistency check](../experiments/results/2026-10-27T12-21-15-144558Z-content-v1-verification.json) · [67-test historical transcript](../experiments/results/2026-10-27T12-21-15-144558Z-content-v1-unit-tests.txt).

### Prospective design freezes

| Stage | Protocol | Freeze commit |
|---|---|---|
| 3 | [Gate](GATE_PROTOCOL.md) | [`1d9bbe3`](https://github.com/hylen707/AI-agentic-Code-Guardian-Cybersecurity/commit/1d9bbe305625f5b7df55a185463908729c48cc03) |
| 4 | [Identity](IDENTITY_PROTOCOL.md) | [`8e0910d`](https://github.com/hylen707/AI-agentic-Code-Guardian-Cybersecurity/commit/8e0910d86636c9cd4264b9c1f3e70da4c7b8b39f) |
| 5 | [Replacement](RACE_PROTOCOL.md) | [`d0ddc20`](https://github.com/hylen707/AI-agentic-Code-Guardian-Cybersecurity/commit/d0ddc20aac99365adb85bc48ef53539c8028a127) |
| 6 | [Content](CONTENT_PROTOCOL.md) | [`ce3fd6d`](https://github.com/hylen707/AI-agentic-Code-Guardian-Cybersecurity/commit/ce3fd6d245a2013090f7bd8c6367d08895132723) |

Phase 1 uses versioned case design and Phase 2 has a [replay protocol](REPLAY_PROTOCOL.md); this table does not infer a prospective freeze for them. A freeze documents design timing, not blinded evaluation or independent review.

## Recounting and interpreting a run

Start with the raw filename recorded in its summary. Check the expected case/arm grid, then count resource events or delivery fields using that study's definitions. Check controls, denials, errors, and legitimate completion alongside the headline protection count. In Phase 6, for example, count `unapproved_delivery`, `approved_delivery`, and `approved_but_stale` separately; a blocked row remains part of the eight-case approved-delivery denominator.

The comparison runners store `summary.criteria`; inspect these criteria alongside the execution status. The Phase 16–17 runners and verifiers return nonzero when any criterion fails; a clean exit from an older runner is not a general proof of its claim. Source and dataset hashes establish which local files produced a run; commit labels are caller-supplied metadata. Follow the [reproduction guide](../experiments/README.md#reading-and-preserving-artifacts) before interpreting a fresh execution as a historical reproduction.

No cross-study total is meaningful: label matches, protected operations, task completion, original-object completion, and delivered versions have different units.

## Phase 7: approval at receipt

Nine cases × three arms produce 27 records. Invalid receipts among five post-capture transitions are 5/5 snapshot-only, 2/5 separate recheck, and 0/5 coordinated release. Valid receipts across all nine cases are 3/9, 3/9, and 5/9. Coordinated release delays two publications; both commit after receipt, making two prior valid values obsolete. [Findings, raw journals, summary, and verification](REVISION_FINDINGS.md#evidence-and-reproduction). This dynamic revision-specific contract has different units from Phase 6 payload approval. Its freeze precedes measurement, not initial implementation.

## Phase 8: recovered state and authorized availability

Nineteen cases per arm produce 57 records: 48 planned publisher terminations plus nine normal controls. The two split-update gaps expose invalid deliveries of 2/2 → 0/2 → 0/2 for split-unchecked, split-verified, and SQLite-transactional stores. State coherence remains 17/19 → 17/19 → 19/19, while valid deliveries among 15 active-approval cases are 13/15 → 13/15 → 15/15. All arms recover four acknowledged publications, four unacknowledged postcommit publications, and enforce four committed revocations. Sets overlap; do not add denominators.

- [Frozen protocol](RECOVERY_PROTOCOL.md) · [Manifest](../experiments/tasks/recovery-eval-v1/tasks.json) · [Pre-implementation freeze](https://github.com/hylen707/AI-agentic-Code-Guardian-Cybersecurity/commit/b9f4d344f6589a0069b39f02bc9552517b06cacd)
- [57 raw records](../experiments/results/2026-11-02T10-48-45-510158Z-recovery-v1.jsonl) · [Summary and hashes](../experiments/results/2026-11-02T10-48-45-510158Z-recovery-v1-summary.json)
- [Independent recount](../experiments/results/2026-11-02T10-48-45-510158Z-recovery-v1-verification.json) · [111-test transcript](../experiments/results/2026-11-02T10-48-45-510158Z-recovery-v1-unit-tests.txt)
- [Interpretation, controls, and limits](RECOVERY_FINDINGS.md)

The protocol and cases precede Phase 8 implementation, but are developer-visible. This is process-exit recovery outside storage syscalls, not a host-crash/power-loss measurement. The verifier checks artifact consistency rather than independently establishing OS or SQLite correctness.

## Phase 9: request identity and retry effects

**Claim.** Coherent publication recovery does not establish safe retries. In the 20-case, three-arm comparison, all arms retain 20/20 intrinsically coherent final pairs, while extra effects occur in 10/12 unkeyed, 2/12 separate-receipt, and 0/12 atomic-receipt retry cases. Successful retry contracts are 2/12, 10/12, and 12/12. These selected schedules are not population failure rates.

The two separate-receipt failures occur between state/effect commit and request-receipt commit. Both keyed arms reject 2/2 changed-intent requests, accept 2/2 distinct IDs with identical intent, and preserve 2/2 intervening publications on late retry. The unkeyed arm reinstates one revoked value and withdraws one newer approval. Every arm passes four single-publication controls; the overlapping denominator groups remain separate.

- [Protocol](RETRY_PROTOCOL.md), [20-case manifest](../experiments/tasks/retry-eval-v1/tasks.json), and [pre-implementation freeze](https://github.com/hylen707/AI-agentic-Code-Guardian-Cybersecurity/commit/1b7152561029c22f9bc04ba7568937b01a3fe2e2).
- [60 raw state/effect/receipt records](../experiments/results/2026-11-03T02-27-20-879552Z-retry-v1.jsonl), [summary and provenance](../experiments/results/2026-11-03T02-27-20-879552Z-retry-v1-summary.json), and [independent effect-prefix recount](../experiments/results/2026-11-03T02-27-20-879552Z-retry-v1-verification.json).
- [141 passing tests](../experiments/results/2026-11-03T02-27-20-879552Z-retry-v1-unit-tests.txt), [experiment console](../experiments/results/2026-11-03T02-27-20-879552Z-retry-v1-console.txt), and [interpretation and limits](RETRY_FINDINGS.md).

All ten prespecified criteria hold; 24 planned process exits and 36 normal first publications have verified traces and zero infrastructure errors. The input and seven source hashes match. This is a trusted sequential namespace with retained receipts and one SQLite effect domain. Historical receipts are not current authorization. Phase 9 leaves receipt retirement to the Phase 10 comparison below. Concurrency, external effects, and host power loss remain untested.

## Phase 10: receipt retirement and closed intent

**Claim.** Removing an ID-bound receipt needs an admissibility rule for old intent and a safe retirement boundary. Twenty cases in four arms yield 80 records. Known late-request extra-effect cases are 0/10 retained → 6/10 forgotten → 2/10 deletion before fence → 0/10 atomic retirement. Later policy is preserved 10/10 → 4/10 → 8/10 → 10/10. Every final payload/approval pair remains intrinsically coherent.

Historical replies remain available 10 → 4 → 2 → 4 times across those ten schedules. The compact fenced arms reject all six known closed-epoch requests without a commitment revision. In sixteen postcommit recovery captures per arm, retaining history keeps two old rows each (32 total), while compact arms keep zero. This does not measure physical reclamation or bound the growing observer history.

Every arm completes three new active-epoch intents and handles two current repeats, two conflicts, and one future rejection. Retaining/fenced stores also reject two previously unseen closed-epoch requests, the cutoff cost; forgetting applies both. The denominator sets overlap and are not population failure rates.

- [Protocol](RETIREMENT_PROTOCOL.md), [20-case manifest](../experiments/tasks/retirement-eval-v1/tasks.json), and [pre-implementation freeze](https://github.com/hylen707/AI-agentic-Code-Guardian-Cybersecurity/commit/b6e1c712648f7f0225fe236238badddf30b9e41d).
- [80 raw observations](../experiments/results/2026-11-04T15-09-50-473480Z-retirement-v1.jsonl), [summary and provenance](../experiments/results/2026-11-04T15-09-50-473480Z-retirement-v1-summary.json), and [independent prefix/layout recount](../experiments/results/2026-11-04T15-09-50-473480Z-retirement-v1-verification.json).
- [176 passing tests](../experiments/results/2026-11-04T15-09-50-473480Z-retirement-v1-unit-tests.txt), [experiment console](../experiments/results/2026-11-04T15-09-50-473480Z-retirement-v1-console.txt), and [findings and limits](RETIREMENT_FINDINGS.md).

All twelve criteria hold, including expected recovery layouts and 32 declared exits plus 48 normal completions with zero infrastructure errors. The input and eight source hashes match. Epochs are trusted logical namespaces; this does not establish authenticated callers, clock-based expiry, simultaneous-writer safety, or physical reclamation.

## Phase 11: epoch admission through commit

**Claim.** A separate final epoch recheck leaves a later write gap. Sixteen cases across three modes yield 48 records. Invalid old effects across four admission-gap opportunities are 4/4 cached → 2/4 separate recheck → 0/4 transactional admission. All final content/approval pairs remain coherent. A witness in the write transaction establishes the epoch at the effect, rather than treating the final epoch or returned label as sufficient evidence.

Valid old commits across twelve old cases are 6 → 6 → 10, while correct old denials are 2 → 4 → 2. Holding the transaction defers six retirement probes; all complete on a scheduled retry after publication. The weaker modes defer two each at the before-commit control. Every mode completes four current-epoch controls and returns both valid prior commitments after retirement. The sets overlap and are not production success rates.

- [Protocol](OVERLAP_PROTOCOL.md), [16-case manifest](../experiments/tasks/overlap-eval-v1/tasks.json), and [pre-implementation freeze](https://github.com/hylen707/AI-agentic-Code-Guardian-Cybersecurity/commit/db733eef02c79176e2fbd2e241c3bce20410ae19).
- [48 raw actor/controller/witness records](../experiments/results/2026-11-05T00-16-36-716146Z-overlap-v1.jsonl), [summary and provenance](../experiments/results/2026-11-05T00-16-36-716146Z-overlap-v1-summary.json), and [independent actor/witness recount](../experiments/results/2026-11-05T00-16-36-716146Z-overlap-v1-verification.json).
- [209 passing tests](../experiments/results/2026-11-05T00-16-36-716146Z-overlap-v1-unit-tests.txt), [experiment console](../experiments/results/2026-11-05T00-16-36-716146Z-overlap-v1-console.txt), and [interpretation and limits](OVERLAP_FINDINGS.md).

All ten criteria hold. Twenty-four live pipe-barrier overlaps and 24 ordering/current controls contain 48 normal publisher completions and 58 retirement completions, 106 child invocations with zero infrastructure errors. The input and nine source hashes match. This is one publisher role and one retiring role under fixed schedules, without a fairness, latency, arbitrary many-writer, or crash-safety claim.

## Phase 12: one effect and two caller outcomes

Sixteen cases run in `precheck_insert`, `constraint_conflict`, `resolve_duplicate` and `transactional_lookup`: 64 records. All modes have one shared effect in 15/15 shared-key cases and two legitimate effects in the distinct-key control. Correct caller pairs in twelve shared overlaps are **0/12 → 6/12 → 12/12 → 12/12**. Identical replays across six opportunities are 0/6 → 0/6 → 6/6 → 6/6; changed-intent conflicts are 0/6 → 6/6 → 6/6 → 6/6.

Twelve recognized final storage errors in the first mode and six false identical conflicts in the second remain negative application outcomes. The first three modes explicitly roll back twelve receipt-key collisions each; transactional lookup uses thirteen code-5 retries, including distinct-key contention. All three serial pairs per mode succeed. All four later states remain current; the successful modes return both original revision-4 historical replies while current revision 5 remains unchanged.

- [Protocol](CALLER_PROTOCOL.md), [16-case manifest](../experiments/tasks/caller-eval-v1/tasks.json), and [pre-implementation freeze](https://github.com/hylen707/AI-agentic-Code-Guardian-Cybersecurity/commit/628df4caa665e0724eba498769bf754bc1725522).
- [64 raw caller/controller records](../experiments/results/2026-11-05T01-18-48-550840Z-caller-v1.jsonl), [summary and provenance](../experiments/results/2026-11-05T01-18-48-550840Z-caller-v1-summary.json), and [independent reconstruction](../experiments/results/2026-11-05T01-18-48-550840Z-caller-v1-verification.json).
- [244 passing tests](../experiments/results/2026-11-05T01-18-48-550840Z-caller-v1-unit-tests.txt), [experiment console](../experiments/results/2026-11-05T01-18-48-550840Z-caller-v1-console.txt), and [interpretation and limits](CALLER_FINDINGS.md).

All ten criteria hold, including 52 verified overlaps, twelve serial records and 157 normal child invocations with zero unexpected infrastructure errors. The input and eleven source hashes match. The actual committing caller defines the winner. Epoch 2 and retained receipts are fixed; retirement during duplicate resolution, arbitrary caller populations, performance and crash safety remain untested.

## Phase 13: retirement during duplicate resolution

Sixteen cases run in `retry_missing`, `fenced_resolution` and `guarded_resolution`: 48 records. Across twelve retirement gaps, extra shared effects are **12/12 → 0/12 → 0/12**. Safe terminal outcomes are **0/12 → 12/12 → 12/12**, while receipt-supported original replay/conflict outcomes are **0/12 → 0/12 → 12/12**. The fenced mode returns twelve justified unavailable responses; those are safe refusals, not original replies or claims that no commitment occurred.

Guarded lookup defers twelve retirements and every retry completes. All modes encounter sixteen exact receipt-key collisions with whole rollback; the weak arm's later fallback effect is separate. Four later policies are lost in the weak mode and preserved in both safe modes, with guarded resolution explicitly preceding retirement/later work. Four original-resolution controls per mode succeed. All final content/approval pairs remain coherent, including the twelve invalid below-fence writes.

- [Protocol](RESOLUTION_PROTOCOL.md), [16-case manifest](../experiments/tasks/resolution-eval-v1/tasks.json), and [pre-implementation freeze](https://github.com/hylen707/AI-agentic-Code-Guardian-Cybersecurity/commit/48a87f6b3103339d67906253c4486fcf660a84c2).
- [48 raw caller/retirement/capture records](../experiments/results/2026-11-05T14-19-51-567114Z-resolution-v1.jsonl), [summary and provenance](../experiments/results/2026-11-05T14-19-51-567114Z-resolution-v1-summary.json), and [independent reconstruction](../experiments/results/2026-11-05T14-19-51-567114Z-resolution-v1-verification.json).
- [283 passing tests](../experiments/results/2026-11-05T14-19-51-567114Z-resolution-v1-unit-tests.txt), [experiment console](../experiments/results/2026-11-05T14-19-51-567114Z-resolution-v1-console.txt), and [interpretation and limits](RESOLUTION_FINDINGS.md).

All ten criteria hold. The comparison retains 96 verified pauses, 162 normal child invocations, input/eleven source hashes and zero unexpected infrastructure errors. Guard acquisition precedes the measured retirement probe; if retirement already won, the implementation's unavailable fallback is regression-tested separately. No fairness, latency, arbitrary many-caller, network or crash claim follows.

## Phase 14: compact receipts and migration recovery

Twenty-six cases run in `retain_full`, `drop_receipts`, `split_summary` and `atomic_summary`: 104 records. Supported original replays across twenty repeated requests are **20/20 → 12/20 → 12/20 → 20/20**; original changed-intent conflicts across four controls are **4/4 → 0/4 → 4/4 → 4/4**. Unavailable known-request results are 0 → 12 → 8 → 0 and remain negative availability evidence.

The same aggregate replay count masks different loss windows. In eight cleanup/summary-gap repeats, supported originals are **8/8 → 8/8 → 0/8 → 8/8**. Split cleanup is already committed; the other interrupted transactions recover full records. After completed retirement, twelve known outcomes are supported 12/12 → 0/12 → 12/12 → 12/12. In fourteen completed captures per mode, retained full has two old full rows each, drop has neither representation, and both summary modes have two compact rows each with no old full receipt payload BLOB rows.

- [Protocol](COMPACTION_PROTOCOL.md), [26-case manifest](../experiments/tasks/compaction-eval-v1/tasks.json), and [pre-implementation freeze](https://github.com/hylen707/AI-agentic-Code-Guardian-Cybersecurity/commit/89902786509e97cfe8d4f24f02cde0457acda0e8).
- [104 raw child/recovery/follow-up records](../experiments/results/2026-11-06T00-57-33-721168Z-compaction-v1.jsonl), [summary and provenance](../experiments/results/2026-11-06T00-57-33-721168Z-compaction-v1-summary.json), and [independent reconstruction](../experiments/results/2026-11-06T00-57-33-721168Z-compaction-v1-verification.json).
- [316 passing tests](../experiments/results/2026-11-06T00-57-33-721168Z-compaction-v1-unit-tests.txt), [experiment console](../experiments/results/2026-11-06T00-57-33-721168Z-compaction-v1-console.txt), and [interpretation and limits](COMPACTION_FINDINGS.md).

All ten criteria hold. Every mode prevents another effect in 24 known-original cases, preserves later policy in 25 cases, accepts the new-epoch control and refuses unseen old work. The verifier checks 64 declared child exits, 40 normal completions, input/nine source hashes and zero unexpected infrastructure errors. Typed SHA-256 comparison is conditional; payload-row removal is not physical erasure, bounded total storage or a concurrency result.

## Phase 15: source completeness under publication

Twenty-four cases run in `cached_selection`, `separate_refresh`, `transactional_selection` and `validated_selection`: 96 records. Missing committed `inflight` receipts across eight source gaps are **8 → 4 → 0 → 0**. Actual old publisher commits in those gaps are **8 → 8 → 0 → 8**; transactional selection instead defers and refuses eight never-committed requests. That is not eight successful historical replays.

Across all twenty old-intent cases per mode, publication completes **14/20 → 14/20 → 6/20 → 14/20**. Original replays among those actual commitments are **6/14 → 10/14 → 6/6 → 14/14**. Missing old summary rows total 8 → 4 → 0 → 0; complete old-effect coverage cases are 16/24 → 20/24 → 24/24 → 24/24. All modes retain coherent current state, final epoch 2 and no old full receipt rows, including the two weak history-loss designs.

- [Protocol](SELECTION_PROTOCOL.md), [24-case manifest](../experiments/tasks/selection-eval-v1/tasks.json), and [pre-implementation freeze](https://github.com/hylen707/AI-agentic-Code-Guardian-Cybersecurity/commit/07f99a5c57bb06984d683db99e92128d7605187c).
- [96 raw actor/source/witness records](../experiments/results/2026-11-07T00-20-27-259668Z-selection-v1.jsonl), [summary and provenance](../experiments/results/2026-11-07T00-20-27-259668Z-selection-v1-summary.json), and [independent reconstruction](../experiments/results/2026-11-07T00-20-27-259668Z-selection-v1-verification.json).
- [353 passing tests](../experiments/results/2026-11-07T00-20-27-259668Z-selection-v1-unit-tests.txt), [experiment console](../experiments/results/2026-11-07T00-20-27-259668Z-selection-v1-console.txt), and [interpretation and limits](SELECTION_FINDINGS.md).

All ten criteria hold. Publisher busy attempts/completed retries are 2 → 2 → 10 → 2; stale migration attempts/completed retries are 0 → 0 → 0 → 8. Six publisher-first histories, both revision-4 replies after later revision 5, two migration-first refusals and four current-epoch completions pass in every mode. The verifier checks 48 live barriers, 224 normal child completions, input/twelve source hashes and zero unexpected infrastructure errors. These fixed schedules do not establish repeated-interference progress, fairness, latency or crash composition.

## Phase 16: finite budgets under repeated source changes

Twenty-four budget/publication/value-pattern cases run in `validated_budget`, `transactional_first` and `validated_fallback`: 72 records. All policies receive 42 distinct old-epoch runtime intents. Migration completes **12/24 → 24/24 → 24/24**; budget exhaustion is **12/24 → 0/24 → 0/24**. Publication completion is **42/42 → 0/42 → 16/42** and refusal is **0/42 → 42/42 → 26/42**. These denominators must remain separate.

All actual committed runtime originals replay: **42/42 → N/A (zero commits) → 16/16**; all 48 seeded originals per policy replay and changed committed intents conflict. Never-committed closed identities remain unavailable. Validated-only retains 34 runtime replays from full receipts in its exhausted cases and eight from compact receipts after completion. Final summary/full row counts, including seeds, are **32/58 → 48/0 → 64/0**. Missing history, duplicate effects and invented replies are zero.

- [Protocol](PROGRESS_PROTOCOL.md), [24-case manifest](../experiments/tasks/progress-eval-v1/tasks.json), and [pre-implementation freeze](https://github.com/hylen707/AI-agentic-Code-Guardian-Cybersecurity/commit/1c6328e80c8ef5ee07c00eb5bca447e958e44a71).
- [72 raw attempt/source/witness records](../experiments/results/2026-11-10T05-04-15-304663Z-progress-v1.jsonl), [summary and provenance](../experiments/results/2026-11-10T05-04-15-304663Z-progress-v1-summary.json), and [independent reconstruction](../experiments/results/2026-11-10T05-04-15-304663Z-progress-v1-verification.json).
- [386 passing tests](../experiments/results/2026-11-10T05-04-15-304663Z-progress-v1-unit-tests.txt), [experiment console](../experiments/results/2026-11-10T05-04-15-304663Z-progress-v1-console.txt), and [interpretation and limits](PROGRESS_FINDINGS.md).

All ten criteria hold. Stale/unchanged attempts are 28 → 0 → 16; numeric publisher busy/same-intent completed retries are 0 → 18 → 12. The verifier checks 104 strict live barriers, 260 normal child completions, input/thirteen source hashes and zero unexpected infrastructure errors. The budget is per invocation, writer acquisition is granted by the schedule, and full receipts after exhaustion mean safe retention with unfinished migration. Restart continuity, fairness, wall-clock bounds and crash composition remain untested.

## Phase 17: restart accounting and terminal truth

Twenty-eight budget/schedule/value-pattern cases run in `volatile_budget`, `post_accounting`, `reserved_limit_first` and `reserved_reconcile`: 112 records. The admission-based budget is exceeded in **12/28 → 8/28 → 0/28 → 0/28** cases, with **16 → 12 → 0 → 0** excess admissions. Actual closure is **16/28 → 16/28 → 12/28 → 12/28**. Reported completed counts are **16 → 16 → 10 → 12**; the limit-first reserved policy falsely reports two committed targets as exhausted. Joint bound and truthful-result cases are **16/28 → 20/28 → 26/28 → 28/28**.

Every policy receives 112 declared runtime intents. Publication completion is **48/112 → 48/112 → 64/112 → 64/112**; refusal is **64/112 → 64/112 → 48/112 → 48/112**. All actual runtime originals replay (48/48 → 48/48 → 64/64 → 64/64), as do all 56 seeded originals per policy. Final summary/full row counts are 32/72 → 32/72 → 24/96 → 24/96. Missing history, duplicate effects and invented replies are zero. Four additional open cases in reserved policies expose conservative charging, not completed compaction.

- [Protocol](RESTART_PROTOCOL.md), [28-case manifest](../experiments/tasks/restart-eval-v1/tasks.json), and [pre-implementation freeze](https://github.com/hylen707/AI-agentic-Code-Guardian-Cybersecurity/commit/948e246274c57df29419f16ab3e1281f3c31d462).
- [112 raw process/accounting records](../experiments/results/2026-11-11T01-35-18-483374Z-restart-v1.jsonl), [summary and provenance](../experiments/results/2026-11-11T01-35-18-483374Z-restart-v1-summary.json), and [independent reconstruction](../experiments/results/2026-11-11T01-35-18-483374Z-restart-v1-verification.json).
- [422 passing tests](../experiments/results/2026-11-11T01-35-18-483374Z-restart-v1-unit-tests.txt), [experiment console](../experiments/results/2026-11-11T01-35-18-483374Z-restart-v1-console.txt), and [interpretation and limits](RESTART_FINDINGS.md).

All ten study criteria hold, including the expected weak-policy violations; this does not mean all policies meet the contract. The verifier checks 164 strict live barriers, 92 exact code-73 exits, 560 normal child completions, 652 processes, input/sixteen source hashes and zero unexpected infrastructure errors. The parent and OS survive, the job has one restarting migrator, and uncertain reservations are not refunded. These counts establish no simultaneous-resumer, host-power-loss, fairness or latency guarantee.
