# Phase 17 findings: a restart can lose a limit or a completed outcome

## Result and scope

Keeping an attempt limit in process memory permits extra admissions after restart. Charging only after work returns also loses attempts when the process exits before accounting. Across 28 cases per policy, these designs exceed the declared budget in **12** and **8** cases respectively. Both policies that reserve a slot durably before work exceed the budget in **zero** cases.

Durable charging alone does not make the terminal answer truthful. At budget 1, an exit after migration COMMIT leaves the target complete and the last slot consumed. Checking the limit before the active epoch returns `budget_exhausted` in **two completed cases**. Reconciling the committed namespace before checking the limit returns the correct completed outcome without another admission. This final policy meets both the admission bound and terminal-truth contract in **28/28** selected cases.

That safety has a cost. Reserving a slot before work can consume the only slot before migration completes, leaving four cases open that weaker accounting policies finish by regranting permission. Actual migration completion is **16/28 → 16/28 → 12/28 → 12/28** across the four policies. All actual publication history remains authoritative. These are finite process-exit results with the parent and OS alive, not a general crash-recovery, fairness or performance guarantee.

## Prospective design and contracts

The [protocol](RESTART_PROTOCOL.md) and [28-case manifest](../experiments/tasks/restart-eval-v1/tasks.json) were published at [`948e246`](https://github.com/hylen707/AI-agentic-Code-Guardian-Cybersecurity/commit/948e246274c57df29419f16ab3e1281f3c31d462) before the new implementation, worker, controller, tests and verifier. Earlier implementation, protocols, inputs and raw evidence retain their bytes. This extends [Phase 16](PROGRESS_FINDINGS.md), whose budget applied to one uninterrupted invocation.

An **admitted attempt** is permission committed before migration preparation begins. The job's budget limits those admissions across process generations, including an admission followed immediately by an exit. A reserved but uncertain slot is not refunded. This unit differs from source selection, a returned attempt result, a completed migration and elapsed time.

Each fixture starts at revision 1 with A, approves B as epoch-1 `seed-a` at revision 2, and revokes as `seed-b` at revision 3. A fixed job binds the policy, budget and target epoch 2. Budgets 1/2 cross seven schedules and update/revocation patterns, yielding **28 cases × four policies = 112 records**. Each case declares four distinct epoch-1 intents; every policy receives the same **112 runtime intents**. Updates include ASCII, empty and Unicode values; revocations remain explicitly typed.

| Policy | When an attempt is charged | Decision on restart |
|---|---|---|
| `volatile_budget` | Process memory before preparation | Active epoch, then local limit |
| `post_accounting` | Durable counter after the attempt returns | Active epoch, then durable limit |
| `reserved_limit_first` | Durable reservation with admission | Durable limit, then active epoch |
| `reserved_reconcile` | Same durable reservation | Active epoch, then durable limit |

All policies use the unchanged complete-source `validated_selection` migration. Job binding, durable reservation where applicable, and an observer admission row share one writer transaction. The observer measures actual admissions; it does not grant permission, decide completion or reconstruct application receipts. Reconciliation reads the active epoch as direct application state in this single-migrator, fixed-target fixture.

## Cut locations and real process histories

Quiet and interference controls run normally. Five other schedules exit after admission, after a stale result, after accounting, before migration COMMIT, or after migration COMMIT before accounting/result delivery. Stale-result cases arm up to two exit generations; the other cut cases arm one. If the budget prevents a second armed cut from being reached, the process returns normally rather than manufacturing another exit.

The worker emits an exact marker and calls `os._exit(73)`, bypassing normal cleanup. Every actual source selection pauses on a pipe barrier bound to role, generation, attempt, budget and stage. Interference schedules publish the next distinct original intent there, causing validation to roll back before cleanup. The parent reopens the same database after each process stops. There are no scheduling sleeps.

After receiving a terminal result, the controller saves a stop snapshot and attempts every remaining declared old intent without another migration. An open namespace accepts it; a closed namespace refuses it. The controller then queries both seeds and all four runtime IDs with original and changed intent, saving the post-query state. This prevents early stopping from silently shrinking the publication denominator.

Checked journal mode is `DELETE`, synchronous level is `FULL`, and runtime probes have zero busy timeout. Unexpected busy, unmarked/wrong exits, incomplete traces, timeouts and storage errors are infrastructure failures. No such failure is counted as a successful defense or modeled exhaustion.

## Admission bounds and terminal truth

| Measure across 28 cases | Volatile | Post-accounting | Reserved limit first | Reserved reconcile |
|---|---:|---:|---:|---:|
| Actual admitted attempts | 54 | 50 | 38 | 38 |
| Cases exceeding the declared budget | 12 | 8 | 0 | 0 |
| Excess admissions above each case's budget | 16 | 12 | 0 | 0 |
| Actual completed migrations | 16/28 | 16/28 | 12/28 | 12/28 |
| Reported completed / exhausted | 16 / 12 | 16 / 12 | 10 / 18 | 12 / 16 |
| False exhausted result after actual commit | 0 | 0 | 2 | 0 |
| Truthful terminal results | 28/28 | 28/28 | 26/28 | 28/28 |
| Both bounded admissions and truthful result | 16/28 | 20/28 | 26/28 | 28/28 |
| Final persisted used counters, summed | 0 | 30 | 38 | 38 |

The volatile counter resets even after its accounting checkpoint. Post-accounting survives that checkpoint, but exits after admission or a stale result precede its charge. Both reserved policies retain the charge before those cuts. The observed admission table is measurement evidence; application decisions never count that table to repair weak accounting.

### Two counterexamples with the same budget

| Budget-1 history | Recovered facts | Consequence |
|---|---|---|
| Exit after a stale result, before accounting | A publication committed; validated migration rolled back. A volatile or post-accounted charge is lost. | Restart can grant another attempt for the same job. Two armed stale exits produce three admissions in the weak policies. |
| Exit after migration COMMIT | Namespace is epoch 2; summaries are present; a reserved used counter is 1. | Limit-first reports exhausted; reconciliation reports completed, with no additional admission. |

The reserved policies differ only in recovery decision order. Their actual closure, admission count and receipt layouts match. A truthful reply is therefore an obligation separate from mutation safety and budget enforcement.

### Conservative charging costs work

At budget 1, after-admission and before-COMMIT cuts consume the only reserved slot while the target remains uncommitted. Across the two value patterns these are **four additional open cases** for both reserved policies. A slot reserved before selection may perform no source work; a before-COMMIT exit rolls back migration writes while retaining the earlier admission reservation. The remaining publication intents then commit in the still-open namespace.

This is a conservative bound on permission, not a promise that every charged attempt reaches selection or completes. Refunding an uncertain slot, identifying safely reusable attempts or guaranteeing eventual completion would require another protocol. Extra weak-policy migration completions cannot be presented as budget-compliant progress.

## Publication and historical authority

| Measure | Volatile | Post-accounting | Reserved limit first | Reserved reconcile |
|---|---:|---:|---:|---:|
| Runtime publication completion / equal declared intents | 48/112 | 48/112 | 64/112 | 64/112 |
| Never-committed old intents refused | 64/112 | 64/112 | 48/112 | 48/112 |
| Original runtime replay / actual commits | 48/48 | 48/48 | 64/64 | 64/64 |
| Seed originals / seeded commitments | 56/56 | 56/56 | 56/56 | 56/56 |
| Changed runtime conflicts / actual commits | 48/48 | 48/48 | 64/64 | 64/64 |
| Final summary / full receipt rows, including seeds | 32 / 72 | 32 / 72 | 24 / 96 | 24 / 96 |
| Missing authority, duplicate effects or invented history | 0 | 0 | 0 | 0 |

Completed migrations in this manifest are quiet, so compact rows bind the seeds. Runtime commits occur in open histories and replay from full authority. The four additional open cases in reserved policies explain their sixteen additional runtime completions. Those are useful publications with unfinished migration, not an increase in completed compaction. Refused never-committed IDs remain unavailable for both exact and changed queries.

All query pairs together leave every final database unchanged, and historical acknowledgment never restores an older current policy. Application replies use full or compact receipts, not admission/publication/migration observers. Compact matching retains Phase 14's SHA-256 and trusted-metadata assumptions; these row counts establish neither physical erasure nor a total storage bound.

## Process evidence and independent reconstruction

| Evidence measure | Volatile | Post-accounting | Reserved limit first | Reserved reconcile |
|---|---:|---:|---:|---:|
| Source selections / strict live barriers | 50 | 46 | 34 | 34 |
| Inert stale rollbacks | 30 | 26 | 18 | 18 |
| Marked exits | 24 | 24 | 22 | 22 |
| Normal terminal migration invocations | 28 | 28 | 28 | 28 |
| Normal publisher children | 112 | 112 | 112 | 112 |
| All child processes | 164 | 164 | 162 | 162 |
| Unexpected infrastructure errors | 0 | 0 | 0 | 0 |

Overall evidence contains **164 live barriers**, **92 marked exits**, **560 normal child completions** and **652 child processes**. Every exit prefix, generation, admission, source selection, publication, resume and recovered snapshot is retained. Stale attempts preserve the post-publication state without fencing, deleting or inventing authority.

The [independent verifier](../experiments/verify_restart_results.py) imports only the standard library. It consumes events through a separate replay implementation, reconstructing job accounting, source/commit boundaries, causal snapshots, original requests, current delivery and terminal truth. All **ten prospective criteria pass**, including the predicted weak-policy failures. Passing these study criteria does not mean all four policies satisfy the desired contract.

All **422 unit tests** pass, including **36 new tests**. They cover fixed job binding, conservative reservation, volatile/post-accounting resets, lost postcommit replies, observer-independent reconciliation, writer-error classification, strict generation-bound resumes, altered cut markers/counters, hidden extra work, and unsupported history. A consistently recorded wrong historical reply still fails scientific criteria. The verifier checks the input and **sixteen source hashes**; hashes and caller-supplied commit labels are local reproducibility evidence, not external attestation.

## Evidence and reproduction

Run: `2026-11-11T01-35-18-483374Z-restart-v1`; Python 3.12.14, SQLite 3.53.1, Linux. Narrative date: 2026-11-11, Asia/Seoul. Starting implementation: [`53b732a`](https://github.com/hylen707/AI-agentic-Code-Guardian-Cybersecurity/commit/53b732a6dc86e54d88f641bcc9b5786b15f4ce92). The design freeze is linked above.

- [112 raw process/accounting records](../experiments/results/2026-11-11T01-35-18-483374Z-restart-v1.jsonl)
- [Summary, environment, command and hashes](../experiments/results/2026-11-11T01-35-18-483374Z-restart-v1-summary.json)
- [Independent reconstruction](../experiments/results/2026-11-11T01-35-18-483374Z-restart-v1-verification.json)
- [422-test transcript](../experiments/results/2026-11-11T01-35-18-483374Z-restart-v1-unit-tests.txt) and [experiment console](../experiments/results/2026-11-11T01-35-18-483374Z-restart-v1-console.txt)

From the repository root:

```bash
python -m unittest discover -s tests -v
python experiments/run_restart_comparison.py \
  --dataset experiments/tasks/restart-eval-v1/tasks.json \
  --base-commit "$(git rev-parse HEAD)" \
  --freeze-commit 948e246274c57df29419f16ab3e1281f3c31d462 \
  --output-dir /tmp/codeguardian-restart
python experiments/verify_restart_results.py \
  --summary experiments/results/2026-11-11T01-35-18-483374Z-restart-v1-summary.json \
  --dataset experiments/tasks/restart-eval-v1/tasks.json
```

The runner measures the executed checkout and retains failures; the final command verifies the historical run against matching source bytes. For a fresh run, pass its new summary path to the verifier. Both return nonzero when criteria fail. See the [experiment guide](../experiments/README.md#reading-and-preserving-artifacts) for provenance-label and artifact-preservation limits.

## Interpretation and next question

Admission permission must survive a process that may never return its attempt result. A recovered completed target must be reconciled before announcing exhaustion. The complete policy therefore combines durable reservation with a truthful recovery decision; it does not guarantee that every reservation produces work or that the target eventually completes.

This trusts one fixed job, one restarting migrator, the controller and local storage. Another compactor cannot independently advance the namespace in these histories. There is no host power-loss experiment, arbitrary filesystem corruption, interrupted syscall, fair-acquisition proof, elapsed-time bound or deployment result. [SQLite atomic commit](https://sqlite.org/atomiccommit.html) and [Python immediate process exit](https://docs.python.org/3/library/os.html#os._exit) describe the underlying mechanisms and assumptions; the experiment validates only the selected process boundaries while the OS survives.

The next question is simultaneous resumption: if two processes resume the same fixed job together, do they share the admission limit and produce justified terminal answers? That requires a new prospective concurrency design; the present sequential generations do not establish it.
