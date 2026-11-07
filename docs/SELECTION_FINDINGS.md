# Phase 15 findings: an atomic migration still needs a complete source

**Status:** completed 2026-11-07 (Asia/Seoul). Twenty-four developer-visible cases across four modes produced 96 records. The protocol and manifest were [committed before implementation](https://github.com/hylen707/AI-agentic-Code-Guardian-Cybersecurity/commit/07f99a5c57bb06984d683db99e92128d7605187c). Earlier source, frozen designs, inputs and measured artifacts retain their bytes.

## Result

An atomic fence/deletion/summary commit can still discard a legitimate receipt if its source was selected before that request committed. Cached selection loses **eight** committed `inflight` receipts in eight source gaps. A separate read refresh catches the four early arrivals but loses the four late arrivals. Transactional selection and exact inside-writer validation lose none, with different amounts of old work completed.

| Outcome and denominator | Cached selection | Separate refresh | Transactional selection | Validated selection |
|---|---:|---:|---:|---:|
| Lost committed `inflight` history / 8 source gaps | 8 | 4 | 0 | 0 |
| Old publications committed in those gaps | 8 | 8 | 0 | 8 |
| Never-committed old requests refused in those gaps | 0 | 0 | 8 | 0 |
| Old publication completion / 20 old intents | 14/20 | 14/20 | 6/20 | 14/20 |
| Supported original replay / actual old commitments | 6/14 | 10/14 | 6/6 | 14/14 |
| Total never-committed old refusals / 20 | 6/20 | 6/20 | 14/20 | 6/20 |
| Old summary rows across 24 cases | 56 | 60 | 56 | 64 |
| Missing old summary rows | 8 | 4 | 0 | 0 |
| Complete old-effect summary coverage / 24 | 16/24 | 20/24 | 24/24 | 24/24 |
| Publisher busy attempts / completed retries | 2 / 2 | 2 / 2 | 10 / 10 | 2 / 2 |
| Stale migration attempts / completed retries | 0 / 0 | 0 / 0 | 0 / 0 | 8 / 8 |
| Publisher-first original controls / 6 | 6/6 | 6/6 | 6/6 | 6/6 |
| Original revision-4 reply after independent revision 5 / 2 | 2/2 | 2/2 | 2/2 | 2/2 |
| Current-epoch publication and replay / 4 | 4/4 | 4/4 | 4/4 | 4/4 |
| Final epoch 2, coherent current state / 24 | 24/24 | 24/24 | 24/24 | 24/24 |
| Old full receipt rows at final observation | 0 | 0 | 0 | 0 |
| Selected/observed source mismatch commit witnesses | 8 | 4 | 0 | 0 |
| Verified live barriers | 12 | 12 | 12 | 12 |
| Normal child completions | 52 | 52 | 60 | 60 |
| Unexpected infrastructure errors | 0 | 0 | 0 | 0 |

The groups overlap. The transactional arm has **no committed-history opportunity in the eight source gaps**: its pending publisher defers and then is refused after closure. Its zero losses are not eight successful historical replays. Actual work completion and actual committed-history preservation must be read together. These fixed histories are not production rates, random race trials or an aggregate security score.

## Source membership can expire before its atomic use

Each fixture approves B at revision 2, revokes at revision 3 and initially retains two epoch-1 receipts. Migration targets epoch 2. A runtime publisher uses a new ID, `inflight`, with ASCII, empty update, Unicode or revocation. An early pause occurs after initial selection; a late pause occurs after the selected mode's final refresh. The publisher can commit revision 4 while the unguarded migration is paused.

Cached selection keeps its original two-row set. A subsequent transaction advances the fence, deletes all old full rows, and inserts two summaries. Publication state remains at revision 4, but `inflight` has neither a full nor compact receipt. The application returns unavailable on its old retry despite that request having actually committed. A separate refresh includes an arrival before its refresh; an arrival after that read closes still disappears in the later deletion.

All modes instrument the actual old source inside the write transaction. Weak modes deliberately do not use that observation as a gate. Their atomically stored migration witnesses record selected revision/count 3/2 against actual revision/count 4/3 in the failing cases. The current state and the closed epoch remain coherent, showing why those properties alone miss the historical loss.

## Two valid interventions, different work outcomes

Transactional selection obtains `BEGIN IMMEDIATE` before source selection and holds it through commit. An old publisher at either source pause receives numeric SQLite busy 5 at BEGIN with checked zero timeout. After the migration completes, the controller retries the **same epoch, ID, operation and bytes**. Closure now refuses that never-committed work. The mode completes six of twenty old intents across the full grid and preserves all six original outcomes.

Validated selection reads its candidate source outside the writer. Inside a new write transaction it rereads epoch, current revision and sorted full receipt tuples and compares them literally. If they differ, it rolls back before any fence, cleanup or witness writes. All eight stale captures retain epoch 1, revision 4, three full receipts and no committed migration witness. A fresh controller-scheduled migration attempt selects all three and completes. The mode completes fourteen old intents and preserves all fourteen original outcomes.

This comparison does not prove either design exhaustive, optimal or generally fair. A fresh source selected directly inside the shorter write transaction is another possible intervention, not separately benchmarked here. Literal tuple validation adds no hash-based manifest assumption; application equality for the compact receipts still uses Phase 14's typed SHA-256 assumption and trusted metadata.

## Controls separate lost replies from refused work

At `before_commit`, every mode holds a writer, causing two busy attempts per mode and unchanged old-epoch retries that are refused after closure. At `after_commit` and migration-first controls, old work is refused immediately. These requests never acquire an effect and must not be counted as deleted historical replies.

All four independent epoch-2 intents commit and replay correctly. Their epoch is assigned as new work, not substituted onto an old retry. Six publisher-first cases preserve the original receipt, including two where `inflight` commits revision 4 and independent key `later` publishes D at revision 5 before migration. The old reply remains revision 4 while current delivery remains D at revision 5. Empty update and revocation remain distinct, with no Unicode normalization.

Publication witnesses store requested/active epoch atomically with the effect and receipt. Migration witnesses store selected/actual revision and source counts atomically with closure and replacement summaries. The observer establishes experimental denominators but is never queried to reconstruct an application result. Each final application follow-up preserves state and authority; unsupported historical guesses do not count as successful replay.

## Validation and provenance

All **353 tests passed**, including **37 new tests**. They cover early/late selection, cached loss, separate-refresh gaps, guarded refusal, literal validation and fresh retry, equal-fingerprint distinct IDs, value/operation forms, historical replies after later policy, atomic witness failures, pre/postcommit exceptions, real busy metadata, unknown SQL errors, WAL rejection and role/stage-bound resume messages. Evidence tests reject changed retry identity, source/witness forgeries, missing barriers and causal prefixes, invented historical replies and incorrect never-committed follow-up results. An entirely failed mode stays visible in infrastructure counts.

The independent verifier imports no store, worker or measured controller. With only the stdlib it reconstructs all source sets, validation results, actor/controller traces, consistent snapshots, effect/receipt/witness histories, actual committed denominators, response support and counters. It matches **all ten criteria**, checks the input and **twelve source hashes**, and verifies **48 live barriers** and **224 normal child completions**, including modeled busy and stale-selection attempts. There are zero unexpected infrastructure errors. The expected weak history losses remain present.

The run used Python **3.12.14**, SQLite **3.53.1**, Linux, rollback-journal `DELETE` and `synchronous=FULL`. Python 3.11+ is required for numeric SQLite error metadata and process-pipe selectors. Only numeric busy 5 at publisher BEGIN is modeled; unknown errors and migration BEGIN failures remain infrastructure errors. Captures and witnesses are trusted local instrumentation. Commit labels are supplied metadata, not source authentication or external attestation.

## Evidence and reproduction

- [Frozen protocol](SELECTION_PROTOCOL.md), [24-case manifest](../experiments/tasks/selection-eval-v1/tasks.json), [freeze commit](https://github.com/hylen707/AI-agentic-Code-Guardian-Cybersecurity/commit/07f99a5c57bb06984d683db99e92128d7605187c).
- [96 raw actor/source/witness records](../experiments/results/2026-11-07T00-20-27-259668Z-selection-v1.jsonl).
- [Summary, environment, executed command and hashes](../experiments/results/2026-11-07T00-20-27-259668Z-selection-v1-summary.json).
- [Independent verification report](../experiments/results/2026-11-07T00-20-27-259668Z-selection-v1-verification.json).
- [Complete test transcript](../experiments/results/2026-11-07T00-20-27-259668Z-selection-v1-unit-tests.txt) and [experiment console](../experiments/results/2026-11-07T00-20-27-259668Z-selection-v1-console.txt).
- [Store](../src/selection_store.py), [worker](../experiments/selection_worker.py), [controller](../experiments/run_selection_comparison.py), [verifier](../experiments/verify_selection_results.py), [tests](../tests/test_selection_store.py).

```bash
python -m unittest discover -s tests -v
python experiments/run_selection_comparison.py --dataset experiments/tasks/selection-eval-v1/tasks.json --base-commit "$(git rev-parse HEAD)" --freeze-commit 07f99a5c57bb06984d683db99e92128d7605187c
python experiments/verify_selection_results.py --summary experiments/results/2026-11-07T00-20-27-259668Z-selection-v1-summary.json --dataset experiments/tasks/selection-eval-v1/tasks.json
```

For a fresh run, use its printed summary filename. Base/freeze labels do not check out or authenticate source; actual local files are hashed. A clean controller exit means no unexpected infrastructure failure. The independent verifier additionally fails on unmet scientific criteria and needs matching source versions to verify historical evidence. Artifacts use unique names and exclusive creation. [Experiment guide](../experiments/README.md#phase-15-complete-source-selection-under-publication).

## Limits and next question

One migration and one main publisher role follow deterministic pipe barriers; optional later work completes before migration in two controls. At most two children run simultaneously. The single fresh retry is scheduled after the interfering publisher finishes. Repeated source changes, finite retry budgets, starvation, fairness, latency, throughput, arbitrary many-writer histories and multiple migrating actors remain untested.

This stage does not combine live interference with Phase 14's process-exit cuts or test network/external effects, caller authentication, WAL, faults during storage operations or host power loss. Source selection retains full values transiently, typed summary comparison assumes SHA-256 properties, retained record count still grows, and no secure-erasure or total-space claim follows. Established transaction and optimistic-validation mechanisms are used; no new primitive or general exactly-once guarantee is claimed.

The next protocol should define repeated interfering publications and a finite migration retry budget. Publication completion, migration completion, refused work and preservation of actual committed receipts must remain separate before claiming bounded progress.

## Technical basis

The [protocol's primary references](SELECTION_PROTOCOL.md#limits-and-technical-basis) document SQLite transaction scope, isolation, numeric contention and inherited hash assumptions. These mechanisms motivate the comparison; the raw records above support its measured counts.
