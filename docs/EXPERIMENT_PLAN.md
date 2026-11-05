# Study map and evaluation standards

**Status:** living overview through Phase 12, 2026-11-05 (Asia/Seoul). Frozen protocols govern their respective runs.

This document defines metrics and controls. Use the [evidence map](EVIDENCE.md) for per-study counts and raw artifacts, the [experiment guide](../experiments/README.md) for commands, and [threat model and limits](LIMITATIONS.md) for assumptions and validity threats.

## Questions, units, and evidence

| Stage | Unit and comparison | Outcome | Protocol or design | Findings |
|---|---|---|---|---|
| 1. Policy conformance | 20, 21, and 45 overlapping synthetic inputs | Agreement with expected policy labels | [v3 design](../experiments/cases/v3/README.md) | [Verification](../experiments/results/2026-10-25T16-05-40Z-verification.json) |
| 2. Paired replay | Eight tasks, baseline and string gate | Protected operations; functional and safe completion | [Replay protocol](REPLAY_PROTOCOL.md) | [Replay findings](REPLAY_FINDINGS.md) |
| 3. Resolved targets | Eight development and eight supplemental tasks, three arms; suites separate | Protected operations and task goals | [Gate protocol](GATE_PROTOCOL.md) | [Gate findings](GATE_FINDINGS.md) |
| 4. File identity | Six hardlink-focused tasks, four arms | Protected operations and task goals | [Identity protocol](IDENTITY_PROTOCOL.md) | [Identity findings](IDENTITY_FINDINGS.md) |
| 5. Descriptor binding | Ten deterministic replacement cases, three arms | Protected content I/O, protected opens, original-object completion | [Replacement protocol](RACE_PROTOCOL.md) | [Replacement findings](RACE_FINDINGS.md) |
| 6. Approved content | Eight same-inode mutation cases, three arms | Unapproved/approved deliveries, content denials, approved but stale values | [Content protocol](CONTENT_PROTOCOL.md) | [Content findings](CONTENT_FINDINGS.md) |
| 7. Approval revisions | Nine ordered histories, three arms | Current approval at receipt; deferred publication | [Revision plan](REVISION_PROTOCOL.md) | [Revision findings](REVISION_FINDINGS.md) |
| 8. Restart recovery | Nineteen cases, three arms; 48 child exits and 9 controls | Coherent recovered state, valid delivery, acknowledged commit recovery | [Recovery protocol](RECOVERY_PROTOCOL.md) | [Recovery findings](RECOVERY_FINDINGS.md) |
| 9. Request retries | Twenty cases, three arms; 24 child exits and 36 normal first requests | Duplicate effects, equivalent receipts, preserved later policy, conflicts and distinct intents | [Retry protocol](RETRY_PROTOCOL.md) | [Retry findings](RETRY_FINDINGS.md) |
| 10. Receipt retirement | Twenty cases, four arms; 32 child exits and 48 normal retirements | Old-epoch effects, historical replies, retained rows, current-intent controls | [Retirement protocol](RETIREMENT_PROTOCOL.md) | [Retirement findings](RETIREMENT_FINDINGS.md) |
| 11. Epoch admission overlap | Sixteen cases, three modes; 24 forced overlaps and 24 controls | Epoch at effect commit, writer contention, retry completion, historical responses | [Overlap protocol](OVERLAP_PROTOCOL.md) | [Overlap findings](OVERLAP_FINDINGS.md) |
| 12. Same-ID callers | Sixteen cases, four modes; 52 forced overlaps and twelve serial records | Both caller responses, exact request effects, rollback and busy retries | [Caller protocol](CALLER_PROTOCOL.md) | [Caller findings](CALLER_FINDINGS.md) |

These studies develop a mechanism argument. They do not estimate a population success rate, and their denominators should not be combined. A prospective freeze prevents silent post-result changes; it does not make developer-visible cases a blind holdout.

## Outcome definitions

**Policy agreement** compares the observed decision with a predefined label. It establishes conformance on those inputs, not resource protection.

**Functional completion** in Phases 2–4 requires all declared file/read goals. **Safe completion** additionally requires zero protected-resource events. A final report file alone is insufficient when a required read did not occur.

**Protected content operations** in Phase 5 count successful read/write operations through a descriptor whose identity matches the protected fixture. **Protected opens** are counted independently, even when the gate subsequently denies content I/O. Failed attempts remain in the trace and in the attempt count.

**Original-object completion** in Phase 5 requires the specified operation on the initial ordinary inode and the expected content outcome. Its eight-case denominator excludes the two before-check substitutions prospectively. It is a narrower measure than task completion, and overlaps with the six attack schedules.

**Approved-version delivery** in Phase 6 requires exact returned UTF-8 bytes equal to the trusted approved version. All eight cases remain in this denominator, including two mutations before capture that both digest arms deny. **Unapproved delivery** counts returned mismatches among five mutation schedules. **Approved but stale** means returned bytes match the approved version but differ from final live-file bytes. These are payload measures, not protected-resource access or agent-task measures. Inspection reads can occur even when delivery is denied.

**Benign blocks** count denials on each protocol's ordinary cases. Infrastructure failures, shared-guard rejections, and policy denials are distinct categories. An error must not improve an apparent protection rate by disappearing from the record.

## Experimental controls

Every compared arm receives a fresh fixture. Within a study, proposals, initial bytes, schedules, and goals are fixed across arms. The intervention changes the approval/execution mechanism; the oracle observes resource identity and effects independently of the decision label. Synthetic fixtures keep the experiments bounded while allowing actual filesystem behavior to be observed.

Raw records precede interpretation. Each study saves input/source hashes, environment information, commands, counts, and criteria. Historical failures remain visible. New hypotheses require a new protocol or explicitly versioned amendment, not edited labels in a measured dataset.

## Next protocol, not yet executed

Phase 12 evaluates both same-ID caller responses with retained receipts at a fixed epoch. The next protocol should place receipt retirement between duplicate rollback and the fresh resolution read, defining a justified outcome when the original reply is unavailable. A missing receipt must not become fabricated success or authority to restore an old effect. Mid-storage-operation cuts, failures during recovery, many-caller histories, capture-time mutation, creation, resource limits, and live-agent evaluation remain separate obligations. Define success criteria and error accounting before extending the measured claim.

## Documentation and evidence integrity

Living summaries use concise academic English: question, method, result, interpretation, and limitation. Earlier protocol text, the v3 design note, task manifests, and raw outputs are preserved byte-for-byte to maintain their recorded hashes. Dated log entries describe what was known at the time; a later entry supplies corrections or extensions. This distinction allows a readable portfolio without retroactively improving the experimental record.

## Phase 7: current approval at trusted receipt

The [revision analysis plan](REVISION_PROTOCOL.md) defines nine cases, three arms, and the ordered-journal oracle. A receipt is valid only if its bytes and revision match the latest preceding committed nonrevoked approval. Pending publication requests are not yet committed. All nine cases stay in the valid-receipt denominator; five post-capture transitions form the invalid-receipt denominator. The sets overlap. [Findings](REVISION_FINDINGS.md) record 27 rows and distinguish receipt validity from later obsolescence. The freeze occurred before measurement after joint protocol/draft review.

## Phase 8: recovered state and delivery

The [recovery protocol](RECOVERY_PROTOCOL.md) specifies the 19-case matrix before implementation. The parent validates each child exit and event prefix, then reopens a fresh store after publication stops. **State coherence** requires the expected old/new revision, approval, and payload together (all 19 cases). **Valid delivery** requires bytes and revision matching the expected active approval (15 cases; four committed revocations excluded). **Invalid gap delivery** concerns the two after-stage update schedules. **Acknowledged recovery** covers four after-ack cases, while another four cuts recover committed state without an acknowledgment. These sets overlap and cannot be pooled.

The verified split arm's two digest denials prevent invalid delivery without repairing the pair or recovering the previous payload. SQLite changes the storage layout and transaction boundary, retaining a usable state in those cases. Counts measure deterministic process-exit recovery, not a power-loss success rate. [Findings](RECOVERY_FINDINGS.md).

## Phase 9: intent across repeated publication

The [retry protocol](RETRY_PROTOCOL.md) freezes 20 schedules before implementation. **Retry success / 12 cases** requires the ideal final state, committed effect sequence, and original semantic receipt, including two before-commit retries that create their first effect. **Duplicate retry cases / 12** count actual extra effect rows for the original ID; a response label alone is insufficient. The two state/receipt gaps are a subset. **Conflict rejection / 2** requires a conflict and no observation change. **Distinct-intent completion / 2** requires a different ID to create revision 3 even with identical payload. **Late-state preservation / 2** requires a historical reply without changing the intervening state. Four single-publication controls and all 20 final state-coherence checks remain separate.

The observed retry success is 2/12 → 10/12 → 12/12; all arms still have 20/20 coherent final pairs. The result concerns retained IDs, one sequential writer, and one database effect domain. It is not a population failure rate or general exactly-once execution claim. [Findings](RETRY_FINDINGS.md).

## Phase 10: retirement and historical response availability

The [retirement protocol](RETIREMENT_PROTOCOL.md) freezes 20 cases across four arms. **Known duplicate effects / 10 late-request schedules** count extra rows for the exact epoch-1 ID. **Later-policy preservation / 10** checks the seeded revision-3 value/revocation and effect prefix. **Historical replies / 10** require the original revision-2 response without mutation; **closed-epoch denial / 6** instead rejects without a commitment revision. Safe refusal and historical completion are separately reported.

Sixteen captures recover completed retirement. **Old logical receipt rows** are two per retaining-store capture and zero per compact-store capture, not a byte or physical reclamation measure. Three new current intents include empty/Unicode values and the same literal ID in a different epoch. Two current repeats, two conflicts, two previously unseen old requests, and one future request retain their own denominators. Rejecting unseen closed-epoch work is the defined cutoff cost.

Observed known duplicates are 0/10 → 6/10 → 2/10 → 0/10; every arm still has 20/20 intrinsically coherent final pairs. A logical epoch is a trusted input for cooperating publishers. Wall-clock expiry, malicious relabeling, and simultaneous writers need separate protocols. [Findings](RETIREMENT_FINDINGS.md).

## Phase 11: effect-time admission and forced overlap

The [overlap protocol](OVERLAP_PROTOCOL.md) freezes 16 cases across three publisher modes. **Invalid old effects / four admission-gap opportunities** compare the request epoch with the active epoch captured in its write transaction, yielding 4/4 → 2/4 → 0/4. **Valid old commits / twelve old cases** are 6 → 6 → 10, while old denials are 2 → 4 → 2. The transaction changes the order by deferring retirement, rather than imposing immediate request-time closure.

**Contention / 2, 2, and 6 cases** requires exact numeric SQLite code 5 at the retirement BEGIN; all controlled retries commit after publisher completion. Four current-epoch controls and two postcommit historical-response cases stay separate. A response after the fence may acknowledge a valid effect before it. Eight verified pause/resume barriers per mode, full child traces, and a controller journal establish these deterministic orders; no timing-based race probability is estimated. [Findings](OVERLAP_FINDINGS.md).

## Phase 12: response correctness beyond duplicate prevention

The [caller protocol](CALLER_PROTOCOL.md) freezes sixteen cases across four modes before implementation. **Correct shared-overlap caller pairs / twelve** require one commitment plus an equivalent original replay for identical intent, or a parameter conflict for changed intent. Counts are 0/12 → 6/12 → 12/12 → 12/12. The six identical and six changed opportunities stay separate: an unconditional conflict is wrong for an identical retry. Recognized collision `storage_error` responses are negative application outcomes, with zero unexpected infrastructure errors in the retained run.

**One shared effect / fifteen** includes twelve overlap cases and three serial controls; all modes satisfy 15/15 because collision paths explicitly roll back the whole transaction. The distinct-key overlap requires two effects despite identical bytes. **Historical replay / two identical-later cases** requires the original revision 4 while current revision 5 remains unchanged. Four later contexts, three serial cases and one distinct case per mode are separate, overlapping denominator groups.

Count code-1555 receipt aborts (12 → 12 → 12 → 0), code-5 busy attempts/completed retries (0 → 0 → 0 → 13), actual committing caller, every child attempt and causal snapshot prefix. Require all ten criteria, 64 records, 52 verified barriers, 157 normal child invocations and zero unexpected errors. The independent verifier reconstructs every counter and checks the input plus eleven source hashes. The protocol fixes epoch 2 and retains receipts during challenged calls; it does not compose retirement with duplicate resolution. [Findings](CALLER_FINDINGS.md).
