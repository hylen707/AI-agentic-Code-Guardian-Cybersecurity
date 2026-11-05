# Phase 12 findings: one request effect and two correct caller outcomes

**Status:** completed 2026-11-05 (Asia/Seoul). Sixteen developer-visible cases across four modes produced 64 records. The protocol and manifest were [committed before implementation](https://github.com/hylen707/AI-agentic-Code-Guardian-Cybersecurity/commit/628df4caa665e0724eba498769bf754bc1725522). Earlier implementation, protocols, inputs and measured evidence retain their bytes.

## Result

One committed request effect does not imply correct caller-visible idempotency. Every mode retains exactly one shared effect in 15/15 shared-key cases. In twelve overlapping cases, correct outcome pairs are **0/12 → 6/12 → 12/12 → 12/12**. An exposed duplicate-key error fails both identical and changed-intent calls. Unconditionally labeling the collision as a conflict handles changed intent but falsely rejects identical retries. Resolving the original receipt after rollback and holding lookup through the write transaction both satisfy the selected contract.

| Outcome and denominator | Precheck/error | Unconditional conflict | Resolve original receipt | Transactional lookup |
|---|---:|---:|---:|---:|
| Correct shared-overlap caller pairs / 12 | 0/12 | 6/12 | 12/12 | 12/12 |
| Correct identical overlap replays / 6 | 0/6 | 0/6 | 6/6 | 6/6 |
| Correct changed-intent overlap conflicts / 6 | 0/6 | 6/6 | 6/6 | 6/6 |
| False identical conflicts | 0 | 6 | 0 | 0 |
| Modeled final storage errors | 12 | 0 | 0 | 0 |
| One shared effect / 15 shared cases | 15/15 | 15/15 | 15/15 | 15/15 |
| Receipt-key aborts with explicit full rollback | 12 | 12 | 12 | 0 |
| Busy attempts / completed retries | 0/0 | 0/0 | 0/0 | 13/13 |
| Correct serial caller pairs / 3 | 3/3 | 3/3 | 3/3 | 3/3 |
| Both distinct-ID effects and responses / 1 | 1/1 | 1/1 | 1/1 | 1/1 |
| Independent later state preserved / 4 | 4/4 | 4/4 | 4/4 | 4/4 |
| Original historical replay / 2 identical-later cases | 0/2 | 0/2 | 2/2 | 2/2 |
| Correct pairs in later contexts / 4 | 0/4 | 2/4 | 4/4 | 4/4 |
| New durable effects across 16 cases | 21 | 21 | 21 | 21 |
| Coherent current final states / 16 | 16/16 | 16/16 | 16/16 | 16/16 |
| Normal child invocations | 36 | 36 | 36 | 49 |
| Unexpected infrastructure errors | 0 | 0 | 0 | 0 |

The eligibility sets overlap. Fifteen shared-key cases include twelve overlaps and three serial controls. The distinct-key control has two legitimate effects. The four later contexts add an independent publication, yielding 21 new effects per mode. These counts are fixed histories, not sampled production rates or an aggregate security score.

## Why the outcomes differ

All modes bind `(epoch, request_id)` to operation and exact bytes. Empty update differs from revocation. Unicode normalization is not applied; visually similar NFC/NFD strings can conflict. Each fixture first approves B, revokes it, then closes epoch 1; challenged calls run at fixed epoch 2 with no retirement and retained receipts.

The three precheck modes release their read transaction before the first caller pauses. The second caller commits shared revision 4. When the first resumes, it tentatively updates publication and inserts an effect before the receipt INSERT fails with numeric primary-key code 1555. Every collision path explicitly rolls back the whole transaction. SQLite's default ABORT cancels the failing statement, so the unique key alone would not undo preceding writes. The retained state, effect and caller rows confirm that no tentative losing revision persists.

`precheck_insert` returns the modeled `storage_error`; this normal-exit response is an intended negative result, not an unexpected process failure. `constraint_conflict` returns a conflict without comparing the rival's operation/bytes, making six identical retries wrong. `resolve_duplicate` instead closes the failed transaction, reads the original receipt in a fresh transaction, and returns either its commitment or a parameter conflict.

`transactional_lookup` obtains `BEGIN IMMEDIATE` before lookup and holds it through commitment. The first caller wins; the second receives numeric `SQLITE_BUSY` (5) at BEGIN with checked zero timeout. All thirteen controller retries complete after writer release with the same caller and inputs. One is a distinct-key request, showing that this writer scope also defers independent intent. Neither invocation counts nor barrier deadlines measure latency, throughput, fairness or starvation.

## Original commitment and current state

In precheck races the second caller wins; in transactional races the first wins. Caller names identify start order only. An observer row written with publication, effect and receipt identifies the actual committer. The response oracle uses the earliest actual same-key commitment and its declared operation/bytes.

Four schedules add independent revision 5 before the losing caller's final response. Every mode preserves that current state. In the two identical-later cases, both successful designs return the original shared revision 4, including its original digest or revocation. Reading the latest publication to fabricate the reply would violate this contract. Changed-intent callers conflict without restoring earlier state. Thus current delivery and historical acknowledgment remain separate obligations.

## Validation and provenance

All **244 unit tests passed**, including 35 new tests. They cover full collision rollback, exact error classification, failed observer/receipt writes, real writer contention, original-result replay, operation/Unicode differences, callback failures and strict caller-bound resumes. Artifact tests challenge wrong historical revisions, false conflicts, forged winners, changed retry commands/identities, missing traces, causal-prefix rewrites and repeated/missing grid records. Incorrect business responses remain negative caller verdicts rather than being relabeled as successful protection.

The independent verifier imports no store, worker or measured controller. It rebuilds the 64-record grid, caller event sequences, controller journal, publication/effect/receipt history, delivery and both responses using only the standard library. It matches every counter and **all ten criteria**, checks the dataset plus **eleven source hashes**, and confirms **52 verified overlaps**, twelve serial records and **157 normal child invocations**. Trusted local observers and supplied commit labels do not provide external attestation.

The run used Python **3.12.14**, SQLite **3.53.1**, Linux, rollback-journal `DELETE` and `synchronous=FULL`. The supported full-suite requirement is Python 3.11+ on Linux for numeric SQLite result metadata and process-pipe selectors. Unknown errors remain infrastructure failures; only code 1555 at receipt insertion and code 5 at BEGIN enter modeled paths. All artifact files use unique names and exclusive creation.

## Evidence and reproduction

- [Frozen protocol](CALLER_PROTOCOL.md), [manifest](../experiments/tasks/caller-eval-v1/tasks.json), [freeze commit](https://github.com/hylen707/AI-agentic-Code-Guardian-Cybersecurity/commit/628df4caa665e0724eba498769bf754bc1725522).
- [Raw caller/controller/capture records](../experiments/results/2026-11-05T01-18-48-550840Z-caller-v1.jsonl).
- [Summary, environment, command and hashes](../experiments/results/2026-11-05T01-18-48-550840Z-caller-v1-summary.json).
- [Independent verification](../experiments/results/2026-11-05T01-18-48-550840Z-caller-v1-verification.json).
- [Full unit-test transcript](../experiments/results/2026-11-05T01-18-48-550840Z-caller-v1-unit-tests.txt) and [experiment console](../experiments/results/2026-11-05T01-18-48-550840Z-caller-v1-console.txt).
- [Store](../src/caller_store.py), [worker](../experiments/caller_worker.py), [controller](../experiments/run_caller_comparison.py), [verifier](../experiments/verify_caller_results.py), [tests](../tests/test_caller_store.py).

```bash
python -m unittest discover -s tests -v
python experiments/run_caller_comparison.py --dataset experiments/tasks/caller-eval-v1/tasks.json --base-commit "$(git rev-parse HEAD)" --freeze-commit 628df4caa665e0724eba498769bf754bc1725522
python experiments/verify_caller_results.py --summary experiments/results/2026-11-05T01-18-48-550840Z-caller-v1-summary.json --dataset experiments/tasks/caller-eval-v1/tasks.json
```

For new measurements, use their printed summary filename. Commit arguments are caller-supplied provenance labels; they do not check out or verify source revisions. The summary hashes the actual files. A clean controller exit reports absence of unexpected infrastructure failures; the independent verifier additionally fails on unmet scientific criteria. See the [experiment guide](../experiments/README.md#phase-12-simultaneous-same-id-callers).

## Limits and next question

The result concerns two known callers, optional controlled later work, one SQLite effect domain, a fixed epoch and retained receipts. No retirement happens between duplicate rollback and the resolution read. Arbitrary caller populations, authenticated identity, hostile input, WAL, network failures, external effects, process crashes and host power loss remain outside scope. The experiments neither discover a new idempotency primitive nor prove general exactly-once execution.

Receipt resolution and transactional lookup are both correct in these histories, with different rollback and deferral counts. The next question is how the response contract changes if retirement removes the receipt between collision rollback and resolution. Safe refusal, unavailable historical acknowledgment and any attempted new effect must be distinguished before composing these mechanisms.

## Technical basis

The [protocol's primary references](CALLER_PROTOCOL.md#technical-basis) document SQLite statement/transaction rollback, numeric result codes, writer admission and original-request idempotency contracts. These established mechanisms motivate the comparison; the raw records above support the measured counts.
