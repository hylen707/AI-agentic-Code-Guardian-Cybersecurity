# Threat model and validity limits

**Scope:** completed studies through Phase 16. These assumptions bound the measured results; they are not a deployable security specification.

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
- The descriptor-based content reader handles small existing regular files that decode as UTF-8. Resource exhaustion, large-file limits, streaming release, and hostile-object behavior beyond the implemented checks require separate work.

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
| Regression tests versus experiment trials | 386 current passing tests are not 386 independent adversarial samples |
| No live-agent adapter or task trials | No evidence yet about model behavior, agent attack success, task accuracy, cost, latency, or deployment impact |

## Open questions

Phase 7 evaluates approval at receipt, Phase 8 evaluates publisher-exit recovery, Phase 9 evaluates retained request IDs, Phase 10 evaluates logical retirement, Phase 11 fixes one publisher/retirer overlap, Phase 12 fixes two same-ID callers with retained receipts, Phase 13 places retirement around post-rollback resolution, Phase 14 tests compact summaries and migration interruption, Phase 15 overlaps publication with source selection, and Phase 16 tests finite attempt policies under repeated source changes. Restart-persistent budgets, many-caller histories, fairness, authenticated epochs, wall-clock expiry, mutation during capture, dynamic protected membership, creation semantics, general directory confinement, and streaming validation remain separate obligations. Live-agent claims would additionally require model/prompt versions, tool permissions, budgets, repeated trials, and an independent task-correctness oracle. None of these is reported as completed.

## Dynamic approval extension

Phase 7 changes the contract to committed revision and approved bytes at trusted in-process receipt. Publishers and receiver must cooperate with one lock. A busy update or revocation remains pending until retried; two measured attempts are deferred. Valid receipt does not revoke already delivered information or guarantee validity at later use. Publication and observer failures can leave effects already applied: there is no file/approval transaction, rollback, or crash recovery. The [findings](REVISION_FINDINGS.md) report these boundaries alongside the zero-invalid-receipt result.

## Restart-recovery extension

Phase 8 introduces trusted fixture stores and a child-process fault model. Separate file replacements can leave content and approval mismatched. Verification denies the mismatches but does not restore state; a SQLite row transaction preserves old-or-new state in the selected cuts. This changes data placement, with SQLite and its OS integration as trusted dependencies. The recovered database payload is not an authorization rule for arbitrary external files.

`os._exit` skips Python cleanup while the parent, filesystem, and kernel keep running. Checkpoints lie outside storage syscalls and SQLite commit internals. File/directory fsync and checked SQLite settings do not turn these observations into a power-loss experiment. No multiple-writer, hostile-mutation, crash-during-recovery, large-file, or performance claim follows. Committed revocations are enforced; pending revocation requests need not have taken effect. Absence of acknowledgment does not imply absence of commitment. Exactly-once retries remain untested. [Protocol](RECOVERY_PROTOCOL.md) · [Findings](RECOVERY_FINDINGS.md).

## Request-retry extension

Phase 9 adds a trusted caller-supplied ID and exact operation/payload binding in one store namespace. It tests coherent SQLite publication with unkeyed, separately recorded, and atomically recorded receipts. Retrying an old ID may return an old commitment receipt; current delivery must still follow the latest publication. The observer is trusted instrumentation in the same state transaction, not an independently secured audit service.

There is one sequential publisher, no identity authentication or tenant separation, and no external side effect. The caller must reuse its original ID to obtain deduplication. Within Phase 9, all receipts remain indefinitely. Phase 10 tests logical retirement and epoch-scoped reuse; clock-based expiry, capacity, and migration remain untested. The checkpoints simulate process exit while the OS and parent survive, not a network protocol or host power loss. Selected at-most-once database effects and equivalent historical replies do not imply general exactly-once execution. [Protocol](RETRY_PROTOCOL.md) · [Findings](RETRY_FINDINGS.md).

## Receipt-retirement extension

Phase 10 closes a trusted logical epoch and compares retained history, deletion without closure enforcement, deletion before fence commitment, and coupled retirement. Old receipts can acknowledge historical commitment; after compaction, rejecting a closed epoch does not recover that missing receipt. The same rule rejects previously unseen old requests, which is an explicit cost to delayed work. New active-epoch IDs and composite-key reuse are controlled separately.

The epoch and original request identity must be trusted and preserved by cooperating callers. They are not authenticated capabilities, and relabeling old intent with a newly authorized epoch is outside this experiment. The store does not implement a timer, TTL, clock recovery, tenant isolation, or a production retention period. Logical row deletion does not establish physical space reclamation; the retained effect observer grows. Cases use one sequential writer, with no concurrent publication/retirement, external effects, host power loss, or recovery-time failures. [Protocol](RETIREMENT_PROTOCOL.md) · [Findings](RETIREMENT_FINDINGS.md).

## Controlled-overlap extension

Phase 11 uses a live publisher and a separate retirement child on one SQLite fixture, with fixed pipe barriers. Commit witnesses distinguish an invalid new effect below a closed epoch from a valid older effect whose response arrives later. Closing the namespace does not undo its already committed value. The writer lock defers six retirement probes in the transactional mode; controlled retries complete after publication, with no general latency or fairness guarantee.

There are two roles, small trusted fixtures, rollback-journal mode, and trusted instrumentation. Within Phase 11, this does not establish arbitrary concurrent histories, many-writer progress, simultaneous duplicate-request semantics, conditional-write equivalence, WAL behavior, caller authentication, network-failure recovery, or crash safety. Numeric contention classification requires Python 3.11+; unknown errors are infrastructure failures. The selected weak arms release their admission scope and do not change Phase 10's original implementation. [Protocol](OVERLAP_PROTOCOL.md) · [Findings](OVERLAP_FINDINGS.md).

## Concurrent-caller extension

Phase 12 holds epoch 2 fixed and retains receipts while two known callers overlap. Optional independent later work occurs before the losing caller receives its final result. A same-transaction actor row identifies the actual winner, but remains trusted local instrumentation. Modeled code-1555 collision errors and false identical conflicts remain negative caller outcomes even when only one effect persists. Explicit whole-transaction rollback establishes the selected one-effect result; SQLite statement-level ABORT alone would not undo earlier writes.

The two successful modes differ in collision rollback versus writer deferral. Counts of twelve rollbacks and thirteen busy retries describe the fixed grid, including serialization of a distinct-key control; they are not latency, throughput, fairness or starvation measurements. Caller names describe start order, not priority. Byte equality is exact, including empty updates, revocation and different Unicode encodings.

A retained receipt supports an original revision-4 acknowledgment after current state reaches revision 5. The study does not retire that receipt during resolution, inject crashes, use network requests, authenticate callers, run arbitrary many-caller schedules, or coordinate external effects. A clean process exit does not imply a correct response. Passing all ten expected comparison criteria includes preserving the negative outcomes of weak modes. [Protocol](CALLER_PROTOCOL.md) · [Findings](CALLER_FINDINGS.md).

## Retirement-during-resolution extension

Phase 13 uses a fresh snapshot of namespace and receipt after whole duplicate rollback. When closure has removed the receipt, safe refusal returns `outcome_unavailable` with no commitment fields. It means the original result is unavailable through that interface, not that the request never committed. A matching guess from current state or the observer cannot establish a receipt-supported replay or conflict. The application never uses the trusted observer to resolve requests.

Guarded resolution reserves the writer after rollback and before the measured retirement attempt. This makes twelve retirements wait and preserves their original decisions. If retirement wins before reservation acquisition, the implementation safely returns unavailable; one regression test covers this fallback, while the measured gap ordering deliberately acquires the guard first. No general progress or protection of every instant in that earlier gap is claimed.

Optional later publication occurs before unguarded resolution and after guarded resolution/retirement. Later-state preservation therefore compares these declared causal orders, not identical latency or service schedules. A closed-epoch write may recreate a deleted receipt while leaving content/approval coherent; both effects remain negative evidence. Epochs, callers, storage and observation code are trusted. Arbitrary caller populations, authentication, timer expiry, physical reclamation, external effects, network failure, WAL, crashes and power loss remain untested. [Protocol](RESOLUTION_PROTOCOL.md) · [Findings](RESOLUTION_FINDINGS.md).

## Compact-receipt extension

Phase 14 replaces exact retained-byte comparison with an explicit operation and SHA-256 fingerprint. Correct historical equivalence is conditional on collision/second-preimage resistance and trusted metadata. A substituted comparison digest in a unit diagnostic produces a false match, exposing that assumption without finding a real SHA-256 collision. The measured strings do not prove general cryptographic security or a minimum receipt schema.

This fixture can reuse an update's input digest as its original approval digest. APIs with a different response/input relationship may require additional metadata. Hashes do not authenticate the caller, encrypt content or grant a new epoch. Summaries are application authority; retained effect observers are measurement evidence and cannot repair a vanished summary.

Completed compaction removes old full receipt payload BLOB rows, while current publication and other evidence may retain the same bytes. Per-record digest size is bounded, but record count and observer history still grow. Logical row layouts do not measure physical reclamation, secure erasure, privacy, memory use or performance. The cuts terminate one child at application boundaries while parent, filesystem and kernel survive. Concurrent publishers/compactors, repeated recovery faults, WAL, external effects, network failures, failures inside storage calls and host power loss remain outside scope. [Protocol](COMPACTION_PROTOCOL.md) · [Findings](COMPACTION_FINDINGS.md).

## Concurrent-source-selection extension

Phase 15 fixes one migration, one main publisher role and optional independent later work. A writer held before selection orders old work after closure: refused requests never committed, and their refusal is a useful-completion cost. Exact inside-writer validation instead aborts stale migration preparation and retries after the publisher completes. This single scheduled retry establishes neither starvation freedom nor a bounded retry/latency guarantee under repeated interference.

The migration's actual source read and witnesses are trusted instrumentation. Weak modes observe source changes but deliberately do not gate on them. The literal source comparison includes full receipt tuples and introduces no additional hash-based manifest assumption; compact replay retains Phase 14's typed SHA-256 assumption. Application responses never consult the observer to recover a missing summary.

The study reports actual committed-history denominators alongside old-work completion. It does not pool missing committed replies with never-committed refusals, infer fairness from barrier completion, benchmark performance or establish arbitrary many-writer behavior. Other correct interventions, such as using a fresh source read directly inside the short write transaction, are not ruled out. Crash/interference composition, multiple migrating actors, network and external effects, authenticated epochs, WAL and host power loss remain untested. [Protocol](SELECTION_PROTOCOL.md) · [Findings](SELECTION_FINDINGS.md).

## Bounded-progress extension

Phase 16 grants the migration writer-acquisition opportunities and injects at most one distinct publisher per selected attempt. Budgets are 1, 2 or 3; intent counts are 0, 1, 2 or 4. Its observed N<B boundary is a finite scheduled result, not a general progress theorem. A final-attempt writer scope finishes under this order but does not guarantee acquisition under an arbitrary scheduler, fairness, throughput or a wall-clock deadline.

The budget is scoped to one controller invocation and is not persisted through crashes or restarts. No interrupted attempt is combined with repeated interference. Stopping at exhaustion leaves epoch 1 open with full receipts and may allow remaining declared intents to commit. That preserves actual history without completing compaction. Closing first refuses never-committed old intents; zero history loss cannot be reported as useful publication completion. All three policies retain trusted effect/witness instrumentation, which never supplies application replay authority. Compact rows retain the earlier digest assumptions, and logical row counts do not establish physical erasure or a storage bound.
