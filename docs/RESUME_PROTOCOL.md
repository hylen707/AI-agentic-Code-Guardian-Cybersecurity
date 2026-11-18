# Phase 18 protocol: overlapping resumption, exits and source changes

**Status:** prospective protocol; freeze this file and the manifest in a commit before implementing the worker, controller or verifier. No Phase 18 result is claimed here.

## Question and comparison

Does Phase 17's shared durable reservation remain bounded when two callers overlap with interruption and source publication? Does the exploratory resumption loop return justified responses in those combined histories? Admission, migration completion, response correctness and historical authority are separate obligations.

Compare unchanged `RestartPublicationStore(..., "reserved_reconcile", budget)` (`restart_baseline`) with unchanged `ResumptionPublicationStore(..., "reserved_reconcile", budget)` (`reconciled_resumption`). The intervention accepts peer completion and classifies numeric SQLite writer contention as `retry_later`. It does not reclaim reservations, establish exclusive ownership or guarantee eventual closure. No mechanism changes may be included in these arms during measurement.

## Frozen case universe and executable schedule

The manifest contains sixteen (scenario, budget) declarations crossed with `updates` and `revocations`: **32 cases per arm, 64 case/arm records**. Every case uses one fixed job targeting epoch 2, two seeded original publications (update and revocation), and four distinct child generations. Generations 1/2 are the original callers; 3/4 run after the overlap has settled. A publication is performed by the parent process only where declared, while all child writers are released. Its exact epoch, request ID and typed UTF-8 payload are in the manifest.

| Scenario | Budgets | Controlled ordering |
|---|---|---|
| `admission_finish` | 1, 2 | A pauses after reservation; B finishes; A continues. |
| `selection_finish` | 2 | A pauses after selection; B finishes; A continues with the earlier source. |
| `writer_busy` | 1, 2 | A holds the writer before commit; B attempts admission; A continues. |
| `exit_admission` | 1, 2 | A pauses after reservation; B finishes; A exits without selecting. |
| `exit_stale` | 1, 2 | A selects; parent publishes; A detects staleness and pauses; B finishes; A exits. |
| `exit_before_commit` | 1, 2 | A holds uncommitted migration; B attempts admission; A exits; parent publishes. |
| `exit_after_commit` | 1, 2 | A commits and pauses before reporting; B finishes; A exits. |
| `both_selected_exit` | 2 | Both select; A acquires writer and exits before commit; B continues. |
| `both_selected_source_exit` | 2 | Same, but the parent publishes after A exits and before B continues. |
| `busy_reserved_exit` | 2 | A selects; B holds uncommitted migration; A attempts its write; B exits; parent publishes. |

The manifest's ordered steps are authoritative. `start` spawns a child and reads until a declared pause or terminal message; `resume` supplies an exact generation/attempt/stage/budget-bound `continue` or `exit`; `publish` performs the declared request. Every case then starts generations 3/4 without pauses. There are no sleeps or probabilistic race searches. The cut is a flushed marker followed by `os._exit(73)` at the selected boundary; it is not a host power-loss or storage-operation fault.

## Fixtures, observations and independent reconstruction

All I/O uses fresh disposable synthetic SQLite fixtures on Linux/Python 3.11+. Seed keys are `seed-a` (update to `approved=version-b\n`) and `seed-b` (revocation). A publication uses `source-change`, epoch 1. Update cases include empty and Unicode values, distinct from `None` revocation. Every actual original intent is queried after the final two callers, and a changed typed intent is queried with the same key. Queries must be inert.

Retain the exact manifest declaration, per-step parent action, generation-bound command, raw stdout, decoded numbered child events, stderr/exit code, and a coherent application/accounting snapshot at every returned boundary. Keep baseline exceptions visible as caller errors. Non-control exits, timeouts, malformed streams and process-start errors are infrastructure failures and remain in the full grid.

A standalone stdlib verifier must reconstruct durable reservations, selected sources, writer ownership, migration commit/rollback, publications and returned answers in the granted order. It must not import implementation or runner code. In particular, a before-commit exit drops the tentative migration; an after-commit exit preserves it. Each completed response needs an observed committed target; each exhausted response needs an open target and no free slot at its own observation. `retry_later` makes no completion assertion and requires actual arranged contention. Historical replies must bind the exact original operation/value/revision, including typed revocation versus empty update.

## Measures and decisions fixed before measurement

Use the complete 32-case denominator per arm and preserve infrastructure failures. Report:

- Admission count and overruns; persisted counter agreement and consumed reservations without migration.
- Final closed/open targets after generations 3/4; neither an exception nor an exhausted response is equivalent to final closure.
- Original caller exceptions, explicit retry replies, supported/unsupported completed and exhausted responses.
- Exhaustion while a peer is live, and exhausted observations whose target subsequently closes. These are diagnostics, not false-exhaustion labels: exhaustion is an admission snapshot.
- Planned code-73 exits, normal child completions, strict barrier count and infrastructure failures.
- Complete full/compact authority, publication effects, current content/approval coherence, original replays and changed-intent conflicts; query inertness.

The reconciled arm meets the bounded response contract only if there are no overruns, unsupported responses, unexpected caller errors, lost/duplicated authority or infrastructure failures. Baseline failures must remain visible. Final migration completion is reported separately and is not a success gate: conservative reservations can be consumed without work. Do not pool results with earlier studies or claim a security rate, fairness, latency or live-agent effectiveness.

Before claiming completion: run all unit tests; run the full grid; independently verify every raw record and summary, raw/manifest/source hashes, and protocol/manifest identity against the freeze commit. Reject mutations of causal order, bindings, exits, reservations, commit witnesses and history. A consistently recorded unsupported answer must still fail the response criterion.

## Scope and exclusions

The parent, OS, Python interpreter, SQLite and cooperating publishers are trusted. Faults occur only at declared application boundaries. There are at most two overlapping callers, one target and budgets 1/2; writer acquisition is granted by the controller. No ownership lease, authenticated client, arbitrary many-caller history, wall-clock expiry, fairness, source adversary, storage corruption, host loss or production enforcement claim is tested.
