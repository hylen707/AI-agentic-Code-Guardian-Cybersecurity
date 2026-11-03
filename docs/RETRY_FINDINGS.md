# Phase 9 findings: coherent state does not make retries safe

**Study:** 20 cases in each of three arms, 60 case/arm records. Measured 2026-11-03 (Asia/Seoul).

## Question and result

Phase 8 couples content and approval through recovery. Phase 9 keeps that coherent SQLite state in every arm and changes how a caller's publication intent is identified across retries. A request ID binds an operation and its exact payload. An old commitment receipt may be returned again, but its old effect must not be applied over a later update or revocation.

| Outcome | Unkeyed | Separate receipt transaction | Receipt in state transaction |
|---|---:|---:|---:|
| Successful same-intent retry contracts / 12 | 2/12 | 10/12 | 12/12 |
| Retry cases with an extra effect for ID 1 / 12 | 10/12 | 2/12 | 0/12 |
| Extra-effect cases at state/receipt gap / 2 | 2/2 | 2/2 | 0/2 |
| Missing first receipt at those gaps / 2 | 2/2 | 2/2 | 0/2 |
| Changed intent correctly rejected / 2 | 0/2 | 2/2 | 2/2 |
| New ID, identical intent correctly applied / 2 | 2/2 | 2/2 | 2/2 |
| Intervening state preserved on late retry / 2 | 0/2 | 2/2 | 2/2 |
| Revoked value reinstated by an old retry | 1 | 0 | 0 |
| Newer approval withdrawn by an old retry | 1 | 0 | 0 |
| ASCII, empty, Unicode, revocation controls / 4 | 4/4 | 4/4 | 4/4 |
| Intrinsically coherent final content/approval / 20 | 20/20 | 20/20 | 20/20 |
| Declared publisher exits verified / 8 | 8/8 | 8/8 | 8/8 |
| Normal first publications completed / 12 | 12/12 | 12/12 | 12/12 |
| Infrastructure errors | 0 | 0 | 0 |

The denominator groups overlap. Twelve retry cases include eight process-exit schedules, two ordinary repeats, and two late retries. Two of the process exits occur before the first commit; applying that request for the first time is correct. The other ten unkeyed retries create a second effect. Unkeyed publication writes no receipts anywhere; the table's missing-receipt row concerns only the two declared gap cases.

## The missing atomicity boundary

Every arm commits payload, approval, revision, and an effect-observer row in one SQLite transaction. The request-aware arms also bind each ID to its operation and exact bytes. Their database, journal mode, synchronization settings, first-request semantics, and receipt matching are shared; only the receipt's transaction boundary changes.

The separate-receipt arm commits the publication before recording that request's result. Exiting between those commits leaves a coherent revision-2 publication and no receipt for ID 1. The restart reader returns correct current data, but a retry cannot recognize the completed request and publishes revision 3. Both the update and revocation schedules expose the same gap. Recording a receipt in the same transaction closes that selected gap: recovery reveals either neither effect nor receipt, or both. All 12 selected retries then satisfy the expected effect and response contract.

The effect observer records each actual revision transition with its request ID in the state transaction. The oracle checks those rows and direct recovered state, rather than trusting a `replayed` label. This observer is trusted fixture instrumentation in the same database, not an external audit service. An explicit regression test changes an unkeyed response to claim replay; the second effect still prevents a successful verdict.

## A repeated value and a repeated intent differ

Both request-aware arms reject same-ID requests with version-C bytes or with a changed operation, without changing any captured state or observer rows. Empty update bytes are a value; revocation is a different operation. Exact UTF-8 bytes are retained without Unicode normalization.

All arms also accept a different ID carrying the identical update or revocation. The two legitimate-intent controls reach revision 3. Deduplicating by payload alone would fail that contract. The experiment relies on a caller preserving and reusing an ID when it means to retry; using a new ID intentionally creates a new publication.

## A historical receipt is not current authorization

One schedule publishes version B, revokes it under ID 2, then repeats ID 1. Unkeyed retry creates revision 4 and makes B readable again. The opposite schedule first revokes, then approves version C under ID 2; an unkeyed repeat of the old revocation creates revision 4 and denies C.

Both request-aware arms instead return ID 1's original revision-2 receipt while leaving the revision-3 update or revocation unchanged. Their reader still evaluates the current publication. Returning a cached receipt does not grant permission to use its old payload or undo later policy. These two cases expose why content/approval coherence is insufficient: every final pair remains coherent, including the two unkeyed states that violate the declared publication-intent contract.

This changes the contract beyond Phase 8; its coherent-state result remains intact. The study does not label every repeated same-value publication a security violation. Different IDs explicitly authorize different intents in this trusted fixture namespace.

## Fault model and verification

The worker uses a real child process, flushed event traces, and `os._exit(73)` at four named boundaries. The full grid contains 24 declared terminations and 36 normally completed first publications. The parent requires the exact event prefix and return code, then reopens the store for recovery and each follow-up call. A failure or timeout cannot be counted as successful protection.

At `before_commit`, the retry creates the first effect. At `after_state_commit`, the separate-receipt arm has not yet recorded the receipt. At `after_record_commit`, it has; the atomic arm reaches that logical barrier without another transaction. At `after_ack`, the pipe contains the returned commitment receipt. These are application checkpoints, not equivalent internal instruction offsets or simulated network packets.

All SQLite observations report `journal_mode=delete`, `synchronous=2` (`FULL`), and `integrity_check=ok`. The parent, kernel, and storage remain running. There are no cuts inside a storage syscall, database commit, or recovery operation. No power-loss or arbitrary storage-failure guarantee follows.

All **141 unit tests passed**, including 30 new tests for exact request binding, conflicts, historical responses, distinct intents, live exception boundaries, receipt-insertion failure, actual child exits, timeout/error accounting, false replay claims, and forged observations. Tests are separate from the 60 research records.

The independent verifier imports neither the publisher nor the measured runner. It enumerates expected committed effect prefixes for the fixed schedules, reconstructs current delivery and historical response fields, validates every child trace and case/arm pair, and recounts every counter and all **ten prespecified criteria**. The recount matches, with zero infrastructure errors. The input hash and all **seven source hashes**, including the unchanged Phase 8 storage dependency, match the recorded run.

## Evidence and reproduction

The [protocol](RETRY_PROTOCOL.md) and [manifest](../experiments/tasks/retry-eval-v1/tasks.json) were committed before Phase 9 implementation at [`1b71525`](https://github.com/hylen707/AI-agentic-Code-Guardian-Cybersecurity/commit/1b7152561029c22f9bc04ba7568937b01a3fe2e2). Cases were visible during development. Earlier code, frozen plans, inputs, and measured artifacts retain their bytes.

- [Raw traces, state/effect/receipt observations, and follow-up responses](../experiments/results/2026-11-03T02-27-20-879552Z-retry-v1.jsonl)
- [Summary, denominators, source/input hashes, versions, platform, and command](../experiments/results/2026-11-03T02-27-20-879552Z-retry-v1-summary.json)
- [Independent effect-prefix recount](../experiments/results/2026-11-03T02-27-20-879552Z-retry-v1-verification.json)
- [Full 141-test transcript](../experiments/results/2026-11-03T02-27-20-879552Z-retry-v1-unit-tests.txt)
- [Experiment console](../experiments/results/2026-11-03T02-27-20-879552Z-retry-v1-console.txt)

```bash
python -m unittest discover -s tests -v
python experiments/run_retry_comparison.py --dataset experiments/tasks/retry-eval-v1/tasks.json --base-commit "$(git rev-parse HEAD)" --freeze-commit 1b7152561029c22f9bc04ba7568937b01a3fe2e2
python experiments/verify_retry_results.py --summary experiments/results/2026-11-03T02-27-20-879552Z-retry-v1-summary.json --dataset experiments/tasks/retry-eval-v1/tasks.json
```

The verifier command audits the retained run; use a new run's printed summary filename to audit that run. Full historical verification requires the versions matching all seven recorded source hashes. Commit arguments are provenance labels, not automatic checkout validation. The runner exits nonzero on infrastructure errors; the verifier also exits nonzero on unmet scientific criteria. See the [experiment guide](../experiments/README.md).

## Limits and next question

This is one sequential trusted writer per small fixture store. A database row is the only publication target; no external service, filesystem executor, or live task participates. There is no tenant isolation, authenticated caller identity, simultaneous request race, receipt eviction, expiration, or migration. The result establishes the selected at-most-once publication effects and equivalent historical replies within retained request records, not general exactly-once execution.

The next question is receipt retention: if an old request record is deleted, can a delayed retry reinstate a revoked value? A future protocol must distinguish safe retirement from merely forgetting an ID, specify a freshness or rejection rule, and retain legitimate new-ID controls. Concurrent writers and failures inside storage/recovery require separate fault models.
