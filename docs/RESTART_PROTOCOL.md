# Phase 17 protocol: migration budget and outcome continuity after restart

**Status:** publish this protocol and the 28-case manifest before implementing the new restart store, worker, controller, tests or independent verifier. Cases are developer-visible. Earlier source, frozen protocols, manifests and measured artifacts retain their bytes.

## Question and contracts

Phase 16 bounds one uninterrupted controller invocation. A fresh process can forget that budget, and a lost response can make a completed migration look unfinished. This study composes fixed process exits with the existing validated-source migration. It asks whether one fixed job retains its attempt limit and reports a truthful terminal result after restart, while preserving all actual publication history.

Define an **admitted attempt** as permission committed before migration preparation can begin. The budget B limits total admitted attempts for this job across all process generations, including admission followed by an exit before selection. Conservative charging can spend a slot without useful work; report that cost rather than refunding an uncertain slot. Actual source selections, completed migrations, publication completion, and charged admissions are distinct units.

The job is fixed to target epoch 2, a policy and a budget. Restart must retain those fields. `completed` is truthful iff the recovered active epoch is 2; `budget_exhausted` is truthful iff the target is not committed and no permitted slot remains under the policy's accounting. A closed namespace is direct application state in this single-migrator fixture; do not consult observer tables to decide completion or restore a lost receipt. No other compactor or epoch advancement occurs.

## Four accounting and recovery policies

All policies reuse unchanged Phase 15 `validated_selection`, atomic fence/deletion/summary migration, typed compact receipts and publication semantics. A job row stores policy, budget, target and used count. Volatile mode leaves persisted used at zero and keeps its count in one process. A trusted observer admission table records each actual admission's ordinal, generation, within-process attempt number and persisted before/after counts; it does not authorize application work. Publication and migration observers remain unchanged.

| Policy | Charging | Recovery decision order |
|---|---|---|
| `volatile_budget` | Increment process memory before each attempt; restart resets it | Read active epoch before testing the local limit |
| `post_accounting` | Increment durable used after an attempt returns; an exit before accounting loses its charge | Read active epoch before testing durable used |
| `reserved_limit_first` | Commit durable used+1 with admission before preparation | Test used>=B first, then inspect active epoch |
| `reserved_reconcile` | Same durable admission reservation | Inspect active epoch first, then enforce used>=B |

Admission, job binding and its observer row share one checked SQLite writer transaction. The two reserved policies cannot admit beyond the persisted bound in this single-migrator schedule. A reserved slot is never refunded after an interrupted attempt. Post-accounting performs a separate transaction after the migration result; volatile accounting disappears with the process. Successful live migration returns `completed` directly after its accounting. A restarted process must derive its response from recovered state instead of relying on the lost live result.

Only ordinary process exits at named application checkpoints are injected. The worker emits an exact `planned_exit` marker and calls `os._exit(73)`, bypassing normal cleanup. Parent and OS remain alive. Checked rollback-journal `DELETE`, `synchronous=FULL` and zero runtime probe timeout apply. Any unexpected SQLite error, busy result, malformed trace, unmarked exit, wrong code, timeout or missing response is an infrastructure failure. No host power-loss, mid-syscall or storage-corruption claim is made.

## Fixture and 28 finite histories

Initialize A at revision 1, publish B as epoch-1 `seed-a` at revision 2, then revoke as `seed-b` at revision 3. Create the fixed job with used=0. Cross B={1,2}, the seven schedules below and two value patterns. Updates cycle ASCII B, empty update, Unicode `approved=안전 ✓\n`, then B; revocations always use `None`. Each case declares exactly four distinct epoch-1 intents `item-1` through `item-4`, with no normalization. Thus each policy receives **112 equal runtime intents** across 28 cases; there are **112 case/policy records** overall.

| Schedule | Armed exit generations | Publication during each selection pause |
|---|---:|---|
| `quiet_control` | 0 | None |
| `interference_control` | 0 | One next remaining intent |
| `after_admission` | 1 | None; exit after admission commit before source selection |
| `after_stale` | Up to 2 | One next intent; exit after stale rollback before accounting |
| `after_accounting` | 1 | One next intent; exit after accounting a stale result |
| `before_commit` | 1 | None; exit after migration writes but before its COMMIT |
| `after_commit` | 1 | None; migration has committed, accounting/result not yet returned |

Each invocation may make several attempts until it returns a terminal result. A new process generation reopens the same database/job after every marked exit. The first one or two generations arm their declared cut; the last generation has no exit cut. If a reserved budget prevents reaching a second armed cut, that generation returns normally and the unused cut is not an error or a performed exit. No invocation is added after a terminal response.

Every actual source selection pauses at `after_selection` on a live pipe barrier. Resume binds role, generation, attempt number, budget and stage. Under the three interference schedules, the controller commits the next distinct publisher during this pause, then resumes migration; exact validation returns stale without cleanup. No sleeps arrange the order. Four intents suffice for the declared finite attempts, including the two reset generations in weak policies.

Save each invocation's before/after recovered snapshot, every live barrier's before/after-publisher snapshot, complete stdout/stderr/events/command/return code, all publisher attempts and a causal controller journal. Once a terminal result is received, capture the stop state and attempt all remaining declared old intents **without another migration**. Remaining work commits in an open namespace and is refused after closure. Save final state; query exact and changed intents for both seeds and all four runtime identities; save the post-query state. A committed original must replay with its actual revision/approval, its changed intent must conflict, and a never-committed closed identity must remain unavailable. Queries must leave the state unchanged.

## Prospective predictions and denominators

| Measure across 28 cases | Volatile | Post-accounting | Reserved limit first | Reserved reconcile |
|---|---:|---:|---:|---:|
| Actual admitted attempts | 54 | 50 | 38 | 38 |
| Cases exceeding B admitted attempts | 12 | 8 | 0 | 0 |
| Excess admissions above B | 16 | 12 | 0 | 0 |
| Actual completed migrations | 16 | 16 | 12 | 12 |
| Reported completed / exhausted | 16 / 12 | 16 / 12 | 10 / 18 | 12 / 16 |
| False exhaustion after a committed migration | 0 | 0 | 2 | 0 |
| Joint bound and truthful-outcome cases | 16 | 20 | 26 | 28 |
| Runtime intents committed / refused | 48 / 64 | 48 / 64 | 64 / 48 | 64 / 48 |
| Original runtime replays / actual commits | 48/48 | 48/48 | 64/64 | 64/64 |
| Final summary / full receipt rows, including seeds | 32 / 72 | 32 / 72 | 24 / 96 | 24 / 96 |
| Actual source selections / live barriers | 50 | 46 | 34 | 34 |
| Stale rollbacks | 30 | 26 | 18 | 18 |
| Marked exits / normal migration invocations | 24 / 28 | 24 / 28 | 22 / 28 | 22 / 28 |

There are **164 strict live barriers**, **92 marked exits**, **560 normal child completions** (112 terminal migration invocations plus 448 publisher children), and **652 child processes** overall. Publication busy is unexpected here because validated selection closes its read before the pause. In each policy all 56 seeded commitments replay and all changed committed intents conflict; false historical claims, repeated effects, missing authority and unexpected errors are predicted zero.

The two reserved policies leave four additional cases open: B=1 after-admission and before-commit cuts, with two value patterns each. A reserved slot is consumed without completing migration, preventing a fresh attempt on restart. This is the cost of conservative charging. At B=1 after-commit, both have actually completed migration, but limit-first returns exhausted before reconciling the active epoch. Their mutation histories match; their response truth differs.

Do not interpret extra weak-policy completions as budget-compliant progress, an open retained namespace as completed compaction, or refused never-committed requests as lost history. Compare admission bounds, actual completion, terminal truth, published work and historical authority separately. Counts are finite arranged histories, not probabilities or throughput estimates.

## Evidence and ten criteria

Retain raw JSONL, summary/provenance, independent verification, console and unit transcript. Include input/source SHA-256, starting/freeze commit labels, commands, UTC timestamps and Python/SQLite/platform versions. Earlier source and raw evidence remain unchanged. A controller oracle and separate standard-library-only verifier must independently reconstruct job accounting, admissions, source transitions, actual process prefixes, barrier bindings, current state, query authority and all counters. The verifier must import no measured modules. Matching hashes establish local bytes, not external attestation.

1. Exact 28-case grid per policy, fixed job bindings, all declared intents and complete retained failures.
2. Admitted-attempt, excess and bound-case totals, with the stated admission-based unit.
3. Actual closure versus reported completion/exhaustion, including the two limit-first false exhaustions and joint contract totals.
4. Counter recovery distinguishes memory reset, lost post-accounting charges and conservative durable reservations.
5. Exact 112-intent completion/refusal denominators per policy, all original/changed replies supported, and all query operations inert.
6. Every actual commit retains one full or compact receipt; representation counts distinguish open recovery from closed migration.
7. Stale rollback is inert and selected/observed migration sources, publication witnesses and current delivery agree with history.
8. Named cut prefixes, code 73, 92 marked exits and 560 normal completions match, without classifying arbitrary failures as planned exits.
9. All 164 strict live barriers, 652 children, generation/attempt ordering and causal snapshots agree; no hidden post-terminal migration.
10. No invented history, duplicate effect, missing authority or unexpected infrastructure error; provenance and independent recount match even when a weak policy violates its contract.

Adverse contract observations in weak modes are expected study findings, not successful defenses. The verifier rejects altered traces/counters/hashes and recomputes scientific criteria for consistently recorded unfavorable results. A new runtime or source change after measurement requires preserving that run and making a new measurement.

## Scope and sources

The job/epoch/ID assignment, local store, controller and observers are trusted. There is one restarting migrator, at most one publisher during a pause, no simultaneous compactors, no hostile admission ledger and no external effect domain. Reservations limit admissions rather than completed SQL transactions or elapsed time. No fair acquisition, bounded latency, physical erasure, general storage bound or production result is claimed. SHA-256 compact authority retains Phase 14's assumptions. Recovery establishes only these selected process-exit boundaries while the parent and OS survive.

Technical basis: [SQLite atomic commit and rollback](https://sqlite.org/atomiccommit.html), [transaction control](https://sqlite.org/lang_transaction.html), and [Python process exit](https://docs.python.org/3/library/os.html#os._exit). Prior evidence: [finite invocation findings](PROGRESS_FINDINGS.md) and [source selection findings](SELECTION_FINDINGS.md).
