# Phase 22 protocol: generated histories and observable prefix consistency

**Prospective status:** freeze this protocol and the grammar manifest before implementing the generator, controller, abstract specification or verifier. No Phase 22 outcome is asserted here. Phase 21's application mechanisms and transport remain unchanged.

## Question

Phase 21's handwritten histories distinguish retired admission from late delivery. Do those distinctions survive systematic generation over a finite request alphabet, and can every observed prefix be explained by the current-epoch sequential contract?

The application contract remains recovery-epoch admission, immutable within-epoch request results, capacity two, atomic expected-epoch advancement/deletion, monotonic authority tokens and transactionally fenced publication migration. Retirement deliberately ends old-result retrieval. This study adds schedule coverage and an abstract history check, not a new storage mechanism or a general proof.

## Frozen finite grammar

One fixture has the two publication seeds in the manifest: a Unicode update and a revocation. The mixed UTF-8 request alphabet uses key `request-α` plus `slot-b` and `slot-c`. `initial` means literal epoch/token 1; `current` means the observed current recovery epoch/token when inputs are resolved; `future` means current recovery epoch plus one. Owners are fixed positive integers. All values retain exact JSON types.

| Template | Inputs resolved at invocation |
|---|---|
| `old_a` | Epoch 1, `request-α`, expected token 1, owner 2. |
| `changed_a` | Epoch 1, `request-α`, expected current token, owner 3. |
| `current_a` | Current epoch, `request-α`, expected current token, owner 2. |
| `current_b` | Current epoch, `slot-b`, expected current token, owner 2. |
| `current_c` | Current epoch, `slot-c`, expected current token, owner 3. |
| `future_a` | Next epoch, `request-α`, expected current token, owner 2. |
| `advance` | Expected current recovery epoch. |
| `close` | Migrate the fixed publication target using current owner/token. |

Enumerate all **8³ = 512 length-three sequential histories per arm**. Their observed prefixes cover depths zero through three; do not present repeated prefix occurrences as unique states.

For overlap, use all nine seed prefixes of length zero or one. The eight ordered caller pairs are old/same, old/changed, current/distinct, current/advance, old/advance, advance/old, advance/future and advance/advance. Resolve both callers' exact inputs once from the state after the seed prefix, so they remain fixed during the overlap. A starts first and requests one declared checkpoint pause; B runs to completion; if A paused, continue A or mark its exit with code 73. Request checkpoints are `after_admission`, `after_lookup`, `before_decision_commit`, `after_decision_commit`, `before_reply`; advancement checkpoints are `before_rotation_commit`, `after_rotation_commit`, `before_reply`.

This is a **single-pivot grammar**, not every interleaving of two processes. A checkpoint that the invoked path never reaches yields a serial record with no A resume/exit. Retain that declared candidate, count realized pauses separately and do not invent a crash or overlap. With the frozen pair matrix, there are **612 declared overlap histories per arm**: nine prefixes × two finish choices × 34 caller-A checkpoint choices across pairs. Three unchanged arms (`erase_only`, `cached_floor`, `atomic_floor`) yield **1,124 histories per arm, 3,372 records** in total. No state deduplication prunes this grid.

Each history gets a fresh SQLite fixture. Retain prefix calls, exact child commands, raw/decoded numbered streams, typed role/generation/input/stage bindings, continuation actions, marked exit status and coherent snapshots. Close the target after callers settle, then query original and changed publication intents. Infrastructure failures remain in the full declared grid.

## Two independent checking layers

First, reuse the unchanged, mechanism-independent Phase 21 reference reconstruction to check epoch admission, writer ownership, receipt lookup/capacity, decision/grant and advancement/deletion commits, rollback and bound transport. The new verifier may import that frozen stdlib-only reference; it must not import a mechanism, worker, controller or generator. Hash this transitive reference dependency explicitly.

Second, implement a separate abstract sequential specification over only observable application state: recovery epoch, current authority, append-only grants, publication target epoch and retained results. It does not inspect implementation events or transaction witnesses to decide an API outcome. Request lookup precedes capacity; admission precedes lookup; advancement compares/deletes/increments. Busy is an exact no-effect response. Close uses the supplied authority. The observed state must match a legal abstract state, not merely satisfy a row count.

At every retained call/boundary snapshot, independently enumerate operation orders consistent with observed invocation/response intervals. Completed calls must reproduce their exact replies. Pending or crashed calls may be omitted or take effect with an unobserved reply, provided the observed state matches. A crashed operation, if included, must linearize before its observed termination. Respect completed-call real-time order. A previously committed result delivered after retirement may be valid. A retired result row cannot be explained away by changing call order. Record consistency for every observed prefix, and summarize complete histories separately. This bounded observable-prefix check is not an unrestricted linearizability theorem or a client-delivery guarantee.

Generate the declared grid independently in the verifier. Compare controller safety/count summaries against reference reconstruction, then report abstract-prefix results as a distinct verification measure. Record unique observable state and labeled transition signatures separately from repeated observations. Select a shortest observed failing prefix per weak arm using invocation count, boundary count, then case ID; retain exact input and state evidence rather than claiming a globally minimal counterexample.

## Measures and acceptance

Report per arm and history family: declared/completed/infrastructure histories, realized/unreached pivots, child counts, marked/normal exits, busy responses, caller/transport errors, commit-time retired decisions/grants, rebound epoch/ID bindings, maximum live results, stale/bound-violating snapshots, target closure and publication replay/conflict correctness. Independent verification additionally reports checked/consistent prefix observations, consistent histories, unique abstract states/transitions and shortest observed failures.

The strong arm requires all declared rows, no execution or publication failures, no retired decisions/grants, rebound IDs, stale rows or result-bound violations, and every observable prefix consistent with the abstract specification. Weak failures must remain visible. Verify protocol/base/freeze identity, complete source coverage and compressed raw hashes. Run the full unit suite plus generated grid, preserve raw evidence and independently verify prior Phase 21 evidence unchanged.

## Limits

Eight templates, depth three, nine overlap seed prefixes, one A pivot, two children, fixed capacity two, mixed UTF-8 fixture, one target, trusted administrative/source calls and application-boundary process exits. No arbitrary-history proof, complete scheduler exploration, probability estimate, fairness, authentication, host/storage/power fault, full-database byte bound or lifetime-work limit. The abstract specification and prior reference may share conceptual assumptions; mutation tests must challenge coherent wrong replies as well as malformed records.
