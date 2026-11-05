# Phase 11 findings: a final recheck still leaves a commit gap

**Study:** 16 cases in each of three modes, 48 case/mode records. Measured 2026-11-05 (Asia/Seoul). **Recorded run (UTC):** `2026-11-05T00:16:36.716146Z`.

## Question and result

Phase 10 retires a logical epoch under sequential publication. Phase 11 places a real publisher and a real retirement process on the same SQLite fixture. The controller pauses the publisher at declared boundaries and lets retirement attempt to commit before resuming it. The question is whether admission still authorizes the epoch in which the effect actually commits.

| Outcome | Cached admission | Separate recheck | Transactional admission |
|---|---:|---:|---:|
| Invalid old effects / four admission-gap opportunities | 4/4 | 2/4 | 0/4 |
| Invalid after initial admission / two cases | 2/2 | 0/2 | 0/2 |
| Invalid after final decision / two cases | 2/2 | 2/2 | 0/2 |
| Valid old commits / twelve old-epoch cases | 6/12 | 6/12 | 10/12 |
| Correct old-epoch denials / those twelve | 2/12 | 4/12 | 2/12 |
| Retirement attempts deferred by `SQLITE_BUSY` | 2 | 2 | 6 |
| Deferred retirements completed on scheduled retry | 2/2 | 2/2 | 6/6 |
| Current-epoch value/revocation controls | 4/4 | 4/4 | 4/4 |
| Valid commitment replied after retirement / two cases | 2/2 | 2/2 | 2/2 |
| Cases recreating a receipt below the retired epoch | 4 | 2 | 0 |
| Intrinsically coherent final content/approval | 16/16 | 16/16 | 16/16 |
| Final active epoch closed to target 2 | 16/16 | 16/16 | 16/16 |
| Verified live pause/resume barriers | 8/8 | 8/8 | 8/8 |
| Publisher child completions | 16 | 16 | 16 |
| Retirement child completions, including busy probes | 18 | 18 | 22 |
| Infrastructure errors | 0 | 0 | 0 |

The denominator sets overlap. Four opportunities combine update/revocation with retirement after initial admission or after the last decision. Twelve old-epoch cases also include clear retirement-first/publication-first orderings, a pause inside the write transaction, and a pause after commit. Four current-epoch controls cover ASCII, empty, Unicode, and revocation. Counts are selected schedules, not concurrent failure probabilities or population availability estimates.

## Why rechecking does not close the write gap

All modes keep the retirement operation atomic and the publication state/effect/receipt transaction intact. The intervention is where the publisher checks its epoch and how long it retains that database scope.

Cached admission reads epoch 1 and releases the read transaction. If retirement commits before the later write, its old decision still permits a new epoch-1 effect under active epoch 2. Both selected pause positions expose this for update and revocation, four cases total. The invalid writes also recreate a receipt in the retired namespace.

A separate fresh recheck catches retirement inserted after initial admission, rejecting both requests before publication. It does not catch retirement inserted after that final check but before the write transaction. Both checks can correctly report epoch 1, yet the later transaction publishes under epoch 2. The two invalid cases remain coherent payload/approval pairs; a correct digest does not establish valid epoch admission.

These diagnostic paths intentionally release the admission scope. They do not change or retroactively invalidate Phase 10's original transactional publisher. This study tests that remaining concurrency assumption explicitly.

## What the transaction protects, and what it delays

Transactional admission obtains `BEGIN IMMEDIATE` before the first check and keeps the transaction through publication commit. Retirement cannot obtain its write transaction during either admission pause or the before-commit pause. Its nonblocking probe returns numeric `SQLITE_BUSY` (5), and the controller retries after publisher completion. All six such retries commit target epoch 2.

The two before-commit cases defer retirement in every mode, because every publisher already holds its write transaction there. The transactional mode additionally defers the four initial/final-decision probes. It obtains zero selected late effects by ordering those publications before retirement, increasing valid old commits from six to ten. It does not make a retirement request immediately effective or establish lock-wait fairness or latency.

## Judge the epoch at the effect, not at the response

Every new publication atomically inserts a commit witness containing its revision, requested epoch, and active epoch read in that same write transaction. All modes take the observer reading; the weak modes deliberately do not use it as an additional gate. The oracle compares that committed witness with actual state, effect, receipt, and delivery observations.

In the after-commit controls, publication commits under epoch 1, then pauses before its response. Retirement commits epoch 2, and only then does the publisher return its revision-4 commitment. All six such responses across the modes describe valid earlier effects. Comparing only the final epoch with the request's epoch would misclassify them.

Retiring a namespace prevents new old-epoch effects; it does not retract already committed values. A valid epoch-1 publication may remain the current policy after the epoch closes. A returned commitment is historical acknowledgment, not a perpetual authorization capability.

The witness and controller channels are trusted fixture instrumentation, not an external audit service or tamper-proof attestation. Missing witnesses, false denial labels, inconsistent bytes, or invented controller order are rejected by both assessments rather than counted as successful protection.

## Real process coverage and verification

There are **24 forced-overlap records** where a live publisher waits on a pipe barrier while a separate retirement child runs, and 24 ordering/current controls. No sleep is used to arrange the schedule. All 48 publisher children and 58 retirement children complete normally, **106 child invocations** total. At most the publisher and one retirement child are live together; a busy retry is a fresh child after publication completes. No crash injection is used in the 48-record comparison.

Each retirement probe verifies `busy_timeout=0`, and only numeric code 5 from its `BEGIN IMMEDIATE` is a valid deferral. Other errors remain infrastructure failures. Every final capture has checked rollback-journal `delete`, `synchronous=2` (`FULL`), and `integrity_check=ok`. Parent captures use one read transaction over state, namespace, effects, receipts, and witnesses; uncommitted publisher changes are absent from the before-commit pause capture.

The **209-test suite passes**, including 33 new tests for real contention, scope gaps, postcommit response ordering, atomic witnesses, write/callback failures, nonbusy errors, current values, strict resume messages, barrier deadlines and cleanup, false denials, missing instrumentation, and forged journals.

The independent verifier imports neither stores, worker, nor measured controller. It rebuilds the fixed case/mode grid, actor traces, controller journal, state/effect/receipt/witness captures, and summary counts. All **ten prespecified criteria** match, with zero infrastructure errors. The input hash and **nine source hashes**, including the unchanged earlier storage dependencies, match the recorded run. This verifies artifact consistency; it is not an external evaluation of SQLite or a proof over arbitrary concurrent histories.

## Evidence and reproduction

The [protocol](OVERLAP_PROTOCOL.md) and [16-case manifest](../experiments/tasks/overlap-eval-v1/tasks.json) were committed before Phase 11 implementation at [`db733ee`](https://github.com/hylen707/AI-agentic-Code-Guardian-Cybersecurity/commit/db733eef02c79176e2fbd2e241c3bce20410ae19). Cases were visible during development. Earlier code, frozen inputs/plans, and measured artifacts retain their bytes.

- [48 raw actor traces, controller journals, and captured witnesses](../experiments/results/2026-11-05T00-16-36-716146Z-overlap-v1.jsonl)
- [Summary, denominators, hashes, versions, platform, and command](../experiments/results/2026-11-05T00-16-36-716146Z-overlap-v1-summary.json)
- [Independent actor and witness recount](../experiments/results/2026-11-05T00-16-36-716146Z-overlap-v1-verification.json)
- [Full 209-test transcript](../experiments/results/2026-11-05T00-16-36-716146Z-overlap-v1-unit-tests.txt)
- [Experiment console](../experiments/results/2026-11-05T00-16-36-716146Z-overlap-v1-console.txt)

Use **Python 3.11+ on Linux** for the current full suite and this study's numeric SQLite error metadata and pipe selector support. Earlier standalone runners retain their recorded requirements.

```bash
python -m unittest discover -s tests -v
python experiments/run_overlap_comparison.py --dataset experiments/tasks/overlap-eval-v1/tasks.json --base-commit "$(git rev-parse HEAD)" --freeze-commit db733eef02c79176e2fbd2e241c3bce20410ae19
python experiments/verify_overlap_results.py --summary experiments/results/2026-11-05T00-16-36-716146Z-overlap-v1-summary.json --dataset experiments/tasks/overlap-eval-v1/tasks.json
```

For a fresh run, pass its printed summary filename to the verifier. Full historical verification requires matching all nine source versions. Commit arguments are caller-supplied provenance labels, not automatic checkout validation. Outputs use exclusive creation. Controller exit status reports infrastructure errors; the verifier also reports unmet scientific criteria. See the [experiment guide](../experiments/README.md).

## Limits and next question

The study fixes one publishing role and one retiring role in a trusted local database namespace. It does not measure random race probability, throughput, latency, fairness, starvation, many-writer histories, WAL isolation, caller authentication, wall-clock TTL, external side effects, power loss, or recovery-time crashes. Conditional writes and other isolation strategies remain separate comparisons. Fixed pipe barriers establish these interleavings, not a general concurrent-safety theorem.

The next question is simultaneous callers using the same request identity: can both obtain a consistent historical outcome, including changed parameters, without mistaking a duplicate-key abort or timeout for correct replay/conflict handling? A separate protocol must specify that caller-visible contract and count both process outcomes.
