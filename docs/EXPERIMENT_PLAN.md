# Study map and evaluation standards

**Status:** living overview through Phase 5, 2026-10-26 (Asia/Seoul). Frozen protocols govern their respective runs.

## Questions, units, and evidence

| Stage | Unit and comparison | Outcome | Protocol or design | Findings |
|---|---|---|---|---|
| 1. Policy conformance | 20, 21, and 45 overlapping synthetic inputs | Agreement with expected policy labels | [v3 design](../experiments/cases/v3/README.md) | [Verification](../experiments/results/2026-10-25T16-05-40Z-verification.json) |
| 2. Paired replay | Eight tasks, baseline and string gate | Protected operations; functional and safe completion | [Replay protocol](REPLAY_PROTOCOL.md) | [Replay findings](REPLAY_FINDINGS.md) |
| 3. Resolved targets | Eight development and eight supplemental tasks, three arms; suites separate | Protected operations and task goals | [Gate protocol](GATE_PROTOCOL.md) | [Gate findings](GATE_FINDINGS.md) |
| 4. File identity | Six hardlink-focused tasks, four arms | Protected operations and task goals | [Identity protocol](IDENTITY_PROTOCOL.md) | [Identity findings](IDENTITY_FINDINGS.md) |
| 5. Descriptor binding | Ten deterministic replacement cases, three arms | Protected content I/O, protected opens, original-object completion | [Replacement protocol](RACE_PROTOCOL.md) | [Replacement findings](RACE_FINDINGS.md) |

These studies develop a mechanism argument. They do not estimate a population success rate, and their denominators should not be combined. A prospective freeze prevents silent post-result changes; it does not make developer-visible cases a blind holdout.

## Outcome definitions

**Policy agreement** compares the observed decision with a predefined label. It establishes conformance on those inputs, not resource protection.

**Functional completion** in Phases 2–4 requires all declared file/read goals. **Safe completion** additionally requires zero protected-resource events. A final report file alone is insufficient when a required read did not occur.

**Protected content operations** in Phase 5 count successful read/write operations through a descriptor whose identity matches the protected fixture. **Protected opens** are counted independently, even when the gate subsequently denies content I/O. Failed attempts remain in the trace and in the attempt count.

**Original-object completion** in Phase 5 requires the specified operation on the initial ordinary inode and the expected content outcome. Its eight-case denominator excludes the two before-check substitutions prospectively. It is a narrower measure than task completion, and overlaps with the six attack schedules.

**Benign blocks** count denials on each protocol's ordinary cases. Infrastructure failures, shared-guard rejections, and policy denials are distinct categories. An error must not improve an apparent protection rate by disappearing from the record.

## Experimental controls

Every compared arm receives a fresh fixture. Within a study, proposals, initial bytes, schedules, and goals are fixed across arms. The intervention changes the approval/execution mechanism; the oracle observes resource identity and effects independently of the decision label. Synthetic fixtures keep the experiments bounded while allowing actual filesystem behavior to be observed.

Raw records precede interpretation. Each study saves input/source hashes, environment information, commands, counts, and criteria. Historical failures remain visible. New hypotheses require a new protocol or explicitly versioned amendment, not edited labels in a measured dataset.

## Next protocol, not yet executed

The next study should hold the pathname or descriptor identity constant while varying content or protected membership. It must specify whether authorization concerns an object, a content version, or current policy membership. Creation needs a separate design because no existing file identity is available before the operation.

Before live-agent evaluation, record model and prompt versions, tool schema, permissions, task budgets, repeated trials, and an independent task-correctness oracle. Evaluate useful work and protection jointly. Current fixture results do not supply those observations.

## Documentation and evidence integrity

Living summaries use concise academic English: question, method, result, interpretation, and limitation. Earlier protocol text, the v3 design note, task manifests, and raw outputs are preserved byte-for-byte to maintain their recorded hashes. Dated log entries describe what was known at the time; a later entry supplies corrections or extensions. This distinction allows a readable portfolio without retroactively improving the experimental record.
