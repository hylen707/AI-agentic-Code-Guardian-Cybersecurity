# Phase 18 findings: overlapping recovery and observation-time truth

## Claim and contribution

**A shared durable admission bound survives the arranged overlaps and exits; a justified caller response does not imply that migration eventually finishes.** Phase 17's baseline produces twelve original caller errors. The reconciled loop produces none, replacing ten writer-contention errors with explicit retry responses and recognizing two peer-completed targets. Both arms close only 22 of 32 cases. The remaining ten retain their historical authority while all available reservations are spent.

This study follows the exploratory [simultaneous-resumption pilot](RESUMPTION_FINDINGS.md). Unlike that pilot, the [protocol](RESUME_PROTOCOL.md) and [32-case manifest](../experiments/tasks/resume-eval-v1/tasks.json) were frozen at [`f87c4a11609b02a8660b4be7358cb1fc70880cec`](https://github.com/hylen707/AI-agentic-Code-Guardian-Cybersecurity/commit/f87c4a11609b02a8660b4be7358cb1fc70880cec) before implementing the controller, worker or verifier. All existing mechanism source files remain byte-identical to base `9f7621a4d92964cbeb35d9d5c6b4f0b09603b0d2`.

## Design and independent observation

Sixteen (scenario, budget) schedules are crossed with update and revocation patterns, giving **32 cases per arm and 64 case/arm records**. Each fresh fixture has one fixed migration target, two seeded original requests, four distinct child generations and at most two overlapping callers. Generations 3/4 resume after the initial overlap settles. Twelve cases per arm additionally execute a declared parent-process source publication. Values include Unicode, empty updates and typed revocation.

Live pipe barriers bind generation, attempt, budget, role and checkpoint. A cut emits a marker and exits with code 73 at an application boundary. The controller grants writer ordering; it does not estimate the probability of a race. The standalone stdlib verifier independently reconstructs durable admission, source selection, writer ownership, tentative migration, commit/rollback, publication, response and recovered state. It imports neither the runner nor the mechanisms. Raw stdout and parent commands must agree with that reconstruction.

The terminal-answer distinction is precise: `completed` requires an observed committed target; `budget_exhausted` describes an open target and no available slot **at that observation**; `retry_later` reports arranged writer contention and makes no completion assertion. A live admitted peer may later close a target that another caller observed as admission-exhausted.

## Results and separate denominators

| Measure | Restart baseline | Reconciled resumption |
|---|---:|---:|
| Case/arm records | 32 | 32 |
| Original caller errors / 64 original callers | 12 | 0 |
| Explicit retry responses / 64 original callers | 0 | 10 |
| Durable admissions | 48 | 48 |
| Cases exceeding shared admission budget / 32 | 0 | 0 |
| Unsupported completion/exhaustion/retry answers | 0 | 0 |
| Final migration completed / 32 | 22 | 22 |
| Final migration still open / 32 | 10 | 10 |
| Reserved slots retained in those open cases | 14 | 14 |
| Exhausted observations while a peer remains live | 6 | 6 |
| Exhausted observations whose target later closes | 2 | 2 |
| Supported original historical replies / actual originals | 76/76 | 76/76 |
| Changed-intent conflicts / actual originals | 76/76 | 76/76 |
| Marked code-73 child exits | 22 | 22 |
| Normal child completions | 106 | 106 |
| Generation/attempt-bound pauses | 46 | 46 |
| Infrastructure failures | 0 | 0 |

Normal process completion includes a baseline caller error reported through its structured protocol. It is not equivalent to a successful caller response. Across both arms the record covers **256 child processes, 44 marked exits, 212 normal process completions and 92 live barriers**. The 76 historical originals per arm comprise 64 seeded requests and 12 source publications. Every history query is inert; every observed snapshot matches the reconstructed committed state.

## Counterexamples that survive the intervention

**Exhausted admission can precede completion.** With budget 1, A reserves and pauses. B correctly observes no free slot while the target is open. A then commits. Both fresh follow-ups report completion. This occurs in two case/arm records per arm, one per value pattern. B's earlier answer is not false; reading it as a permanent job outcome would be false.

**A reservation can outlive useful work.** A before-commit exit rolls back namespace change and receipt compaction while retaining the already committed attempt charge. With budget 1, later callers cannot migrate. Parent publication still commits in the open namespace, and all original outcomes remain available.

**Two admitted attempts still need not close the target.** In `both_selected_source_exit`, both callers select; A exits before commit; a parent publication changes the source; B detects staleness. Both slots are spent. In `busy_reserved_exit`, A spends a slot before B acquires the writer; A encounters contention; B then exits before commit. The explicit retry response preserves the admission contract but cannot grant another slot. Both schedules remain open with budget 2.

The five unclosed (scenario, budget) pairs are `exit_admission/1`, `exit_stale/1`, `exit_before_commit/1`, `both_selected_source_exit/2` and `busy_reserved_exit/2`, each crossed with two patterns. No reservation reclamation or ownership lease was tested, so none is inferred from these results.

## Evidence and reproduction

The retained run uses Linux x86-64 and Python 3.12.14. **455 tests passed**, including 25 new regressions. Tests reject changed causal order, live/recorded resume bindings, exit codes, missing markers, raw streams, reservations, publication identities, source hashes and summaries. Consistently recorded false completion and wrong historical replies still fail the relevant outcome criteria.

```bash
python -m unittest discover -s tests -v
python experiments/run_resume_comparison.py \
  --output /tmp/codeguardian-resume-v1.jsonl \
  --base-commit 9f7621a4d92964cbeb35d9d5c6b4f0b09603b0d2 \
  --freeze-commit f87c4a11609b02a8660b4be7358cb1fc70880cec
python experiments/verify_resume_results.py /tmp/codeguardian-resume-v1.metadata.json
```

- [Raw histories](../experiments/results/2026-11-18-resume-v1.jsonl)
- [Source/manifest/raw hashes and controller counts](../experiments/results/2026-11-18-resume-v1.metadata.json)
- [Independent reconstruction and four criteria](../experiments/results/2026-11-18-resume-v1-verification.json)
- [Full test output](../experiments/results/2026-11-18-resume-v1-tests.txt) and [execution environment](../experiments/results/2026-11-18-resume-v1-execution.json)
- [Controller](../experiments/run_resume_comparison.py), [worker](../experiments/resume_worker.py), [independent verifier](../experiments/verify_resume_results.py), [regressions](../tests/test_resume.py)

Verification checks the frozen files against their Git object, requires the freeze's parent to equal the declared mechanism base, validates all mechanism bytes against that base, and compares raw/source hashes and independently reconstructed counts. A failed run remains in the 64-record grid; it cannot shrink a denominator.

## Interpretation and next question

These are controlled two-caller mechanism studies with trusted parent, OS and SQLite, bounded budgets 1/2 and cuts outside storage operations. They do not establish arbitrary many-caller correctness, scheduling fairness, a power-loss guarantee, production enforcement, or live-agent effectiveness. The independent replay is a reference model for these granted schedules, not a proof over every concurrent history.

The next question concerns reservation reclamation: how can a trusted recovery decision distinguish a stopped worker from a merely delayed one, and fence the older generation before reusing permission? Returning a slot based only on apparent inactivity could let an older admitted worker act after permission has been reassigned. That mechanism and its accounting definition need a separate prospective protocol.
