# Phase 19 protocol: reclaiming permission requires fencing the old holder

**Prospective status:** freeze this protocol and manifest before implementing the mechanism, worker, controller or verifier. No result is claimed in this file.

## Question and the accounting boundary

Phase 18 conservatively consumes reservations even when a caller exits. Can a trusted recovery operation reassign permission while preventing the displaced holder from later committing migration?

This experiment deliberately changes the admission contract. There is **one reusable permission slot**, identified by a durable, monotonically increasing token and an owner label. The grant history is append-only; a replacement adds a new token rather than decrementing or erasing any admission. This bounds current authority, **not lifetime grants, physical work or Phase 18's cumulative attempt budget**. Results must not be presented as eliminating Phase 18's unfinished cases under its original budget.

Recovery is an explicit, trusted compare-and-swap request. It does not infer failure from elapsed time or apparent inactivity. The replaced process is intentionally allowed to remain alive. Owner labels may be reused; tokens may not. Authentication, automatic failure detection and leases based on clocks are outside scope.

## Three arms with equal source validation

| Arm | Permission check before migration effect |
|---|---|
| `cached_permission` | Uses the originally issued token without enforcing its current validity. |
| `separate_fence` | Reads and checks the current owner/token in a separate scope before the write. |
| `transactional_fence` | Checks the current owner/token in the SQLite transaction that commits migration. |

All arms perform the same validated source selection. A source change may reject a selected source independently of token validity. An already committed target is reconciled before granting a replacement or performing an effect. The experiment uses the existing publication/receipt representation and a new, isolated reclamation module; earlier mechanism modules and evidence remain unchanged.

A trusted replacement transaction requires the expected current token and a positive replacement owner. If the writer is busy it returns `busy`, changes nothing, and must not be counted as completed revocation. If the target is already closed it returns `completed` without allocating a token. Otherwise an exact token match appends token+1 and changes current authority atomically; mismatch returns `conflict`. A failed or replayed compare-and-swap cannot consume another token.

## Frozen universe: 20 cases per arm

Ten scenarios are crossed with `updates` and `revocations`, giving **20 cases per arm and 60 case/arm records**. The manifest fixes all caller pauses, replacement arguments, source requests and resume/exit actions. Every fixture starts at epoch 1, target 2, owner 1/token 1, and contains two actual publication receipts. `seed-a` is a Unicode update; `seed-b` is an empty update in update-pattern cases and a revocation otherwise. A single declared source publication appears only in `source_changed`.

| Scenario | Controlled history |
|---|---|
| `no_reclaim` | A migrates with its original token; B observes the completed target. |
| `stale_before_select` | A pauses before selecting; replacement 1→2 commits; A resumes. |
| `reclaim_after_selection` | A selects; replacement 1→2 commits; A resumes. |
| `reclaim_after_fence` | A pauses after its check; recovery attempts replacement; A resumes; the request is retried. |
| `reclaim_before_commit` | A holds the write transaction before commit; recovery attempts replacement; A commits; recovery retries. |
| `exit_before_commit` | A holds an uncommitted write; recovery encounters busy; A exits; recovery retries. |
| `exit_after_commit` | A has committed but not replied; recovery sees completion; A exits. |
| `source_changed` | A selects; replacement commits; a source publication commits; A resumes against its earlier selection. |
| `aba_owner` | A selects with owner 1/token 1; authority transfers to owner 2/token 2 and back to owner 1/token 3; A resumes. |
| `stale_recovery_cas` | Replacement to owner 2 commits; an older expected-token request for owner 3 conflicts; A resumes. |

B always starts after A settles and uses the then-current authority, selected by the trusted controller. B performs at most one migration call; both callers can instead return truthful completion without another effect. There are no loops that silently refill a lifetime budget. A code-73 exit is a flushed, generation-bound application checkpoint followed by `os._exit(73)`. The parent and OS survive; there are no failures inside storage operations.

## Evidence and independent reconstruction

Use disposable synthetic SQLite fixtures on Linux/Python 3.11+. Retain the exact parent actions, bound child commands, raw/decoded numbered streams, stderr/exit codes, coherent snapshots at every boundary, full grant history and the migration-time owner/token witness. Instrumentation must not authorize an effect in weak arms. Preserve every error, conflict, busy response and infrastructure failure in the complete 60-record grid.

A separate stdlib verifier, importing no implementation or runner, reconstructs publication state, grant history, current authority, writer ownership, tentative writes, commit/rollback, observed fence checks and every response. Exact generation/owner/token/stage bindings are required. It must distinguish a blocked recovery request from a committed replacement, an owner label from its token, and a rolled-back migration from a committed one with a lost reply.

At final state, query all actually committed original publication intents and changed typed intents. Historical replies and current policy must remain coherent; queries must change no durable state. Denominators belong to each arm's actual committed requests, not intended publication labels.

## Measures and prospective decision rules

Report per arm: invalid migration effects (token/owner did not match authority at effect commit), displaced-holder effects, stale-token refusals, source-change refusals, successful/blocked/conflicting/completed recovery calls, lifetime token grants, ABA cases, final migration completion, caller errors, planned exits, strict barriers, historical replays/conflicts and lost/duplicated authority. Report the total number of committed replacements separately from current capacity.

The transactional arm satisfies the bounded claim only with zero invalid effects, unjustified responses, history loss, unexpected caller errors and infrastructure failures. Completion under the granted schedule is reported separately. In a write-held interval, postponing recovery and allowing the currently authorized write to commit is acceptable; claiming revocation already completed is not. Weak-arm counterexamples and unchanged-source controls must remain visible. Do not pool counts with earlier stages or interpret these schedules as a measured race probability.

Before completion, run all unit tests and the full grid; verify raw/source/manifest identities and the frozen Git objects; reject mutations of ownership, tokens, expected-token recovery arguments, live bindings, order, exits, commit witnesses, responses and history. A consistently recorded invalid effect must remain a failure for the transactional arm.

## Limits and next boundary

This is a trusted recovery/fencing mechanism study for one slot, one target and at most two caller processes, not a production scheduler or sandbox. Durable tokens exclude wraparound; SQLite-range integers are validated. A blocked writer must be retried by the controller. There is no fairness, host-power-loss, malicious-client, token-secrecy, automatic failure-detection, unbounded-retry or lifetime-work bound claim.
