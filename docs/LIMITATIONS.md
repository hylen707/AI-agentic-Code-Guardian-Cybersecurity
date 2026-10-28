# Threat model and validity limits

**Scope:** completed studies through Phase 6. These assumptions bound the measured results; they are not a deployable security specification.

## Assets and authorization contracts

Phases 2–5 protect configured synthetic file resources while preserving legitimate work. Phase 6 adds a different contract: the consumer should receive only the configured approved UTF-8 value of an ordinary file. A successful content-version check does not replace protected-resource authorization.

| Property | Operational meaning | What it does not imply |
|---|---|---|
| Policy conformance | A decision matches the curated expected label. | Actual filesystem protection or useful work |
| Resource protection | No successful protected operation under the phase's oracle | Zero metadata opens, general directory confinement, or future policy correctness |
| Object continuity | Authorization and content I/O use the same held descriptor. | Immutable bytes or current content |
| Approved-version delivery | Returned bytes equal the trusted approved value. | No inspection of rejected bytes, atomic capture, or freshness |
| Freshness | The returned approved value also matches the final live bytes in the study's comparison. | A general concurrent consistency guarantee |

Exact outcome definitions and overlapping eligibility sets are in the [evaluation standards](EXPERIMENT_PLAN.md#outcome-definitions).

## Controlled adversarial capabilities

| Study | What the fixture controller may vary | Condition held fixed |
|---|---|---|
| Phase 1 | Lexical operation/path records, malformed inputs, and path spellings | Expected string-policy labels; no filesystem execution |
| Phases 2–3 | Proposals using direct protected names, benign path components, or symlink aliases | Fixture topology during each task; declared goals |
| Phase 4 | Hardlink aliases sharing protected or ordinary file identity | Topology during approval and use; configured protected inventory |
| Phase 5 | Protected hardlinks before/after the check, parent replacement after the check, and benign file replacement after the check | Selected deterministic boundaries; static protected identities; trusted descriptor ownership |
| Phase 6 | Same-inode overwrite/truncate before capture; overwrite/truncate/append after validation, through a hardlink | Approved digest, process memory, initial value, and inode identity |

The controllers are trusted experiment instrumentation. They arrange a counterexample at a known boundary; no autonomous adversary chooses arbitrary paths, code, or schedules. The manifests define the tested combinations, not every possible action under these capabilities. [Protocols and manifests](EVIDENCE.md#artifact-index) are the study-specific authority.

## Trusted components and assumptions

- The harness, fixture construction, scheduling hooks, OS identity semantics, and observation code behave as intended. The oracle receives resource/content evidence separately from policy decisions, but remains part of the trusted harness.
- Protected membership is configured before the run and remains fixed. A `(st_dev, st_ino)` match is meaningful within the fixture lifetime; dynamic membership and broader identity lifecycle are untested.
- The executor retains control of each descriptor, performs authorization before content I/O or truncation, and never reopens the name for the approved operation. Holding a descriptor alone does not establish confinement.
- The content owner supplies the approved digest; the action cannot choose it. Digest provenance, SHA-256 collision resistance, and trusted immutable process values are assumptions, not experimental discoveries.
- The latest reader handles small existing regular files that decode as UTF-8. Resource exhaustion, large-file limits, streaming release, and hostile-object behavior beyond the implemented checks require separate work.

See [architecture](ARCHITECTURE.md) and the technical sources in the [replacement protocol](RACE_PROTOCOL.md#technical-basis) and [content protocol](CONTENT_PROTOCOL.md) for implementation details.

## Failure cases that remain visible

The string gate loses two legitimate replay completions while missing two protected aliases. Resolved paths miss protected hardlinks; pre-open identity checks miss later name replacement. Descriptor binding closes the selected redirections but still opens two protected objects for metadata before denial. Hash/reread delivers three unapproved values after validation. A verified buffer prevents those deliveries, yet reads the two rejected versions for inspection and returns three approved but stale values. These outcomes motivate narrower contracts; they are retained in the [evidence map](EVIDENCE.md).

## Threats to validity

| Threat | Consequence for interpretation |
|---|---|
| Small, curated, developer-visible cases | No population security rate, blind generalization claim, or justified confidence interval |
| Nested policy versions and related suites | Counts cannot be pooled or treated as independent repetitions |
| Deterministic check/use schedules | Demonstrates selected orderings; does not measure concurrent race probability |
| Shared implementation and trusted observation infrastructure | Agreement cannot independently establish correctness of OS semantics, all oracle code, or every execution |
| Different contracts across stages | Identity-only Phase 6 failures do not invalidate Phase 5's narrower identity result; task completion and payload delivery are different measures |
| Regression tests versus experiment trials | 67 recorded passing tests are not 67 independent adversarial samples |
| No live-agent adapter or task trials | No evidence yet about model behavior, agent attack success, task accuracy, cost, latency, or deployment impact |

## Open questions

Legitimate version updates and stale-value handling require a prospective protocol before implementation. Mutation during capture, dynamic protected membership, creation semantics, general directory confinement, and streaming validation remain separate obligations. Live-agent claims would additionally require model/prompt versions, tool permissions, budgets, repeated trials, and an independent task-correctness oracle. None of these is reported as completed.
