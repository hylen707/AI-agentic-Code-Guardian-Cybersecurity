# Simultaneous resumption: exploratory pilot

## Question and counterexample

Can two processes resume the same Phase 17 job while sharing its durable attempt budget and returning justified responses?

The existing `reserved_reconcile` policy serializes reservation correctly, but its caller loop accepts only `migrated` and `stale_selection`. A second process can finish after the first caller reserves a slot and before it selects the source. Selection then returns `already_migrated`; the first caller raises `ValueError` even though the target is committed. Separately, an overlapping SQLite writer produces `SQLITE_BUSY`, which the earlier study deliberately exposed as an error.

This is a **post hoc exploratory pilot**, developed after inspecting those execution paths. It is not a prospectively frozen Phase 18 evaluation. The earlier seventeen studies and their retained evidence are unchanged.

## Intervention and response contract

`ResumptionPublicationStore` retains Phase 17's fixed job, durable pre-work reservations, transaction boundaries and validated source selection. It accepts `already_migrated` and reconciles the durable target after an attempted migration. It translates only numeric `SQLITE_BUSY` into `retry_later`; other storage errors remain exceptions. The baseline implementation remains available for comparison.

| Response | Meaning |
|---|---|
| `completed` | The durable target was observed at epoch 2. A response need not imply that this caller performed the migration. |
| `budget_exhausted` | At this admission snapshot, the target was still open and no further slot was available. An already admitted peer may still complete it. This does not certify permanent failure of the job. |
| `retry_later` | A writer prevented this invocation from proceeding. The response makes no claim about the current target. A reservation committed before contention remains spent. |

No internal waiting, unbounded retries, reservation refunds, ownership leases or fairness mechanism is introduced.

## Executed design

Each arm uses a fresh temporary SQLite store, a seeded publication, two spawned processes with distinct generation numbers, and exact stage/generation-bound pipe resumes. The parent holds one caller at a live checkpoint and grants the other a specific execution order. Both original caller outcomes, including baseline exceptions, remain in the raw record. After both settle, two fresh processes query/resume the same job. The runner also checks the original historical publication and a changed-intent conflict.

| Schedule | Budget | Arranged order |
|---|---|---|
| Admission overtaken | 1, 2 | Pause A after admission; run B to an outcome; resume A. |
| Selection overtaken | 1, 2 | Pause A after selection; run B to an outcome; resume A. |
| Writer collision | 1, 2 | Pause A before commit while it owns the writer; run B; resume A. |
| Both selected | 2 | Pause both after selection; complete A; resume B with its now-stale selection. |

The two-selection schedule with budget 1 is excluded by construction: a second slot is required to reach that checkpoint. Seven schedules per arm produce **14 case/arm records**, **28 original caller outcomes** and **28 follow-up outcomes**.

## Observation

| Measure | Phase 17 baseline | Reconciled resumption |
|---|---:|---:|
| Case/arm records | 7 | 7 |
| Original caller exceptions / 14 callers | 3 | 0 |
| Explicit `retry_later` / 14 callers | 0 | 2 |
| Admission-exhaustion snapshots / 14 callers | 2 | 2 |
| Cases exceeding the shared attempt budget / 7 | 0 | 0 |
| Cases whose two follow-ups report the committed target / 7 | 7 | 7 |
| Seeded original publications replayed correctly / 7 | 7 | 7 |

The baseline exceptions comprise one overtaken-admission `ValueError` and two writer-contention `OperationalError` responses. Both arms eventually close in every arranged schedule because the controller grants one admitted writer completion. This is not evidence that every initial caller immediately succeeds or that arbitrary schedules eventually finish. In the budget-1 admission/selection schedules, B legitimately sees exhausted admission while A is still in flight; its later follow-up sees completion.

## Evidence and reproduction

```bash
python3 -m unittest discover -s tests -v
python3 experiments/run_resumption_comparison.py \
  --output /tmp/codeguardian-resumption-v1.jsonl
python3 experiments/verify_resumption_results.py /tmp/codeguardian-resumption-v1.jsonl
```

The retained execution on November 17, 2026 used Linux x86-64 and Python 3.14.4. All **430 tests** passed, including eight added regressions. Python emitted SQLite connection `ResourceWarning` messages during the full suite; the unfiltered log preserves them. This run does not establish a warning-free suite.

- [Raw records](../experiments/results/2026-11-17-resumption-v1.jsonl)
- [Base commit, source hashes and raw hash](../experiments/results/2026-11-17-resumption-v1.metadata.json)
- [Independent verification output](../experiments/results/2026-11-17-resumption-v1-verification.json)
- [Full test log](../experiments/results/2026-11-17-resumption-v1-tests.txt) and [execution environment](../experiments/results/2026-11-17-resumption-v1-execution.json)
- [Runner](../experiments/run_resumption_comparison.py), [independent checker](../experiments/verify_resumption_results.py), [regressions](../tests/test_resumption_store.py)

The checker imports only the standard library. It checks the complete declared grid, barrier identities, durable reservation sequence, caller outcomes, follow-up convergence, migration witness, single publication effect, compact authority, and historical replies. It verifies raw and complete `src/*.py` source hashes. Mutation regressions reject missing/duplicated cases and altered counters, responses, effects, summaries, witnesses and barrier identities. This is a structural/outcome checker, not a full event-history reconstruction. Controller/infrastructure failures abort the runner; they must not be treated as absent scientific cases.

## Limits and next experiment

These are two cooperating callers, one fixed target, budgets 1/2, one seeded update and controller-granted writer order. There is no simultaneous host failure, hostile caller, source publication during this pilot, arbitrary many-caller history, scheduler fairness estimate, latency claim, power-loss model or production security boundary. Unit regressions additionally cover a failed invocation after durable commit and contention after reservation; these are not extra process-schedule observations.

The next prospective study should freeze a manifest before measurement and combine overlapping resumptions with marked process exits, repeated source changes and admission exhaustion while another reservation remains in flight. It should distinguish a snapshot of admission exhaustion from a stable job outcome and reconstruct each response against the live history.
