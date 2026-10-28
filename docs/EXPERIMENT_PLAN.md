# Study map and evaluation standards

**Status:** living overview through Phase 6, 2026-10-27 (Asia/Seoul). Frozen protocols govern their respective runs.

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

Phase 6 has now varied content while holding identity constant. The next protocol should define how legitimate version changes become authorized and how consumers handle approved but stale values. Changes during capture, dynamic protected membership, and creation remain untested; each needs explicit success criteria before implementation.

Before live-agent evaluation, record model and prompt versions, tool schema, permissions, task budgets, repeated trials, and an independent task-correctness oracle. Evaluate useful work and protection jointly. Current fixture results do not supply those observations.

## Documentation and evidence integrity

Living summaries use concise academic English: question, method, result, interpretation, and limitation. Earlier protocol text, the v3 design note, task manifests, and raw outputs are preserved byte-for-byte to maintain their recorded hashes. Dated log entries describe what was known at the time; a later entry supplies corrections or extensions. This distinction allows a readable portfolio without retroactively improving the experimental record.
