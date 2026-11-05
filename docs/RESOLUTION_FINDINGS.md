# Phase 13 findings: retirement can preserve safety while removing the answer

**Status:** completed 2026-11-05 (Asia/Seoul). Sixteen developer-visible cases across three modes produced 48 records. The protocol and manifest were [committed before implementation](https://github.com/hylen707/AI-agentic-Code-Guardian-Cybersecurity/commit/48a87f6b3103339d67906253c4486fcf660a84c2). Earlier source, frozen design, input and measured-artifact bytes are preserved.

## Result

After a recognized duplicate is rolled back, retirement can delete the original receipt before resolution reads it. Treating that absence as permission to write again repeats the shared effect in **12/12** selected gaps. A fresh fenced lookup prevents every duplicate, but returns **12 unavailable original outcomes**. Guarded lookup preserves all twelve original replay/conflict outcomes by ordering retirement after resolution; it defers twelve retirement attempts, and every scheduled retry completes.

These are different properties: one state effect, a justified terminal response, and availability of the original outcome. Safe refusal need not reconstruct history. An unavailable result does not say that the original request never committed.

| Outcome and denominator | Retry missing receipt | Fenced resolution | Guarded resolution |
|---|---:|---:|---:|
| Extra shared-effect cases / 12 gaps | 12/12 | 0/12 | 0/12 |
| Safe terminal resolutions / 12 gaps | 0/12 | 12/12 | 12/12 |
| Justified unavailable outcomes / 12 gaps | 0/12 | 12/12 | 0/12 |
| Receipt-supported original replay/conflict / 12 gaps | 0/12 | 0/12 | 12/12 |
| Original identical replays / 6 gaps | 0/6 | 0/6 | 6/6 |
| Original changed-intent conflicts / 6 gaps | 0/6 | 0/6 | 6/6 |
| One shared effect / all 16 cases | 4/16 | 16/16 | 16/16 |
| Original resolution controls / 4 | 4/4 | 4/4 | 4/4 |
| Independent later state preserved / 4 | 0/4 | 4/4 | 4/4 |
| Exact receipt-key aborts and full rollbacks | 16 | 16 | 16 |
| Busy retirements / completed retries | 0/0 | 0/0 | 12/12 |
| Below-fence commit cases | 12 | 0 | 0 |
| Recreated below-fence receipt cases | 12 | 0 | 0 |
| Retired cases with no old receipt / 14 | 2/14 | 14/14 | 14/14 |
| New durable effects across 16 cases | 32 | 20 | 20 |
| Coherent final states / 16 | 16/16 | 16/16 | 16/16 |
| Final epoch 3 / epoch 2 cases | 14/2 | 14/2 | 14/2 |
| Verified pause/resume barriers | 32 | 32 | 32 |
| Normal child invocations | 50 | 50 | 62 |
| Unexpected infrastructure errors | 0 | 0 | 0 |

The groups overlap. Twelve gaps contain six identical and six changed-intent requests; four of those gaps add later work. Four remaining controls resolve before retirement or retain receipts. Counts describe selected histories, not production probabilities, independent samples or an overall security percentage.

## The duplicate is known, but its original reply can be lost

Trusted setup approves B at revision 2, revokes at revision 3, then atomically closes epoch 1 to epoch 2. The first caller reads a missing epoch-2 shared receipt and closes that read. While it pauses, the second commits the shared request at revision 4. The resumed first tentatively updates publication and inserts an effect before the receipt INSERT reports primary-key code 1555. Every mode explicitly rolls back the whole transaction before entering resolution.

That rollback matters: SQLite's default ABORT only backs out the failing statement. The earlier publication/effect changes would remain pending without whole rollback. The resolution captures contain only the actual second-caller winner, confirming that no tentative first-caller effect survives. The weak fallback's later committed effect is a separate transaction, not evidence that rollback failed.

In unguarded gap histories, retirement advances to epoch 3 and deletes the epoch-2 receipt before the next lookup. `retry_missing` observes this closure but reuses cached admission to publish again with the **original epoch 2 and ID**. It does not silently assign a new epoch. The atomic observer records requested epoch 2 and active epoch 3 with the extra effect. Deletion can therefore be followed by both a below-fence effect and a recreated old receipt, even while content and approval remain coherent.

`fenced_resolution` reads namespace and receipt together. Missing evidence below the fence yields `outcome_unavailable` with no commitment revision/digest and no new write. This preserves one shared effect in every case. It cannot classify the removed original parameters through that receipt interface, so both identical and changed-intent gaps lose the equivalent original result. Neither the current publication nor the trusted measurement observer supplies a replacement application answer.

## Guarding resolution changes the order

`guarded_resolution` obtains `BEGIN IMMEDIATE` after collision rollback and before the resolution pause. The concurrent retirement probe returns numeric `SQLITE_BUSY` (5) at BEGIN with checked zero timeout. First then reads the original receipt, compares exact operation/bytes, and decides its original revision/digest or a parameter conflict. It releases the reservation before returning that result. The controller completes retirement on retry. All twelve controlled retries succeed.

The reservation does not protect the entire interval before acquisition. A regression test retires immediately after collision rollback but before guard acquisition; guarded lookup then returns unavailable safely. The measured gap ordering deliberately obtains the reservation first. No uninterrupted availability or many-caller progress guarantee is claimed.

Four gap histories add independent epoch-3 revision 5. In unguarded modes that work commits before first resolves; weak retry overwrites or revokes it at revision 6, while fenced refusal preserves it. Under the guard, original resolution finishes first, then retirement and independent revision 5 commit. Both safe modes preserve all four later states under these explicitly different causal orders. The comparison does not rank latency, throughput, fairness or starvation.

## Evidence supporting a response

The original actual committer is second in these schedules. State, effect, receipt and caller/requested-epoch/active-epoch witness are written atomically. The oracle reconstructs exact original intent from these durable observations; the application uses only namespace and receipt. Empty update differs from revocation. NFC and NFD encodings are compared byte-for-byte without normalization.

A supported original outcome requires both the correct response fields and an original receipt available to resolution. A guessed revision 4 after receipt loss can match historical truth accidentally and still lacks that support. Unavailable responses must contain no commitment fields. The raw caller lookup events, consistent snapshots and response checks retain these distinctions.

## Validation and provenance

All **283 unit tests passed**, including **39 new tests**. They exercise retirement before guard acquisition, real writer contention, whole collision rollback, exact error scope, atomic observer/receipt failures, pre/postcommit exceptions, failed guarded callbacks, WAL rejection and caller-bound resume commands. Artifact tests challenge invented historical replies, unavailable results carrying commitment fields, false conflicts after receipt loss, forged commit epochs, lost barriers, wrong retirement targets, causal-prefix changes, semantic manifest duplicates and missing/repeated records. An entirely failed comparison mode remains visible in infrastructure counts.

The independent verifier uses only the standard library and imports no store, worker or measured controller. It reconstructs 48 records, all actor/controller traces and causal snapshots, original-response support, current delivery, below-fence effects and every summary counter. It matches **all ten criteria**, the input and **eleven source hashes**, **96 verified barriers** and **162 normal child invocations**, with **zero unexpected infrastructure errors**. Modeled weak failures remain part of the scientific result.

The run used Python **3.12.14**, SQLite **3.53.1**, Linux, rollback-journal `DELETE` and `synchronous=FULL`. Python 3.11+ on Linux is required for numeric SQLite metadata and process-pipe selectors. Only code 1555 at the receipt INSERT and code 5 at write-probe BEGIN enter modeled paths; another primary-key error from the effect INSERT remains an infrastructure failure. Captures use trusted local instrumentation, and commit labels are supplied metadata rather than external attestation.

## Evidence and reproduction

- [Frozen protocol](RESOLUTION_PROTOCOL.md), [16-case manifest](../experiments/tasks/resolution-eval-v1/tasks.json), [freeze commit](https://github.com/hylen707/AI-agentic-Code-Guardian-Cybersecurity/commit/48a87f6b3103339d67906253c4486fcf660a84c2).
- [Raw caller/retirement/capture records](../experiments/results/2026-11-05T14-19-51-567114Z-resolution-v1.jsonl).
- [Summary, environment, executed command and hashes](../experiments/results/2026-11-05T14-19-51-567114Z-resolution-v1-summary.json).
- [Independent verification report](../experiments/results/2026-11-05T14-19-51-567114Z-resolution-v1-verification.json).
- [Complete unit-test transcript](../experiments/results/2026-11-05T14-19-51-567114Z-resolution-v1-unit-tests.txt) and [experiment console](../experiments/results/2026-11-05T14-19-51-567114Z-resolution-v1-console.txt).
- [Store](../src/resolution_store.py), [worker](../experiments/resolution_worker.py), [controller](../experiments/run_resolution_comparison.py), [verifier](../experiments/verify_resolution_results.py), [tests](../tests/test_resolution_store.py).

```bash
python -m unittest discover -s tests -v
python experiments/run_resolution_comparison.py --dataset experiments/tasks/resolution-eval-v1/tasks.json --base-commit "$(git rev-parse HEAD)" --freeze-commit 48a87f6b3103339d67906253c4486fcf660a84c2
python experiments/verify_resolution_results.py --summary experiments/results/2026-11-05T14-19-51-567114Z-resolution-v1-summary.json --dataset experiments/tasks/resolution-eval-v1/tasks.json
```

For new measurements, use the printed summary filename. Base/freeze arguments do not check out or authenticate revisions; the summary hashes actual local source bytes. A clean controller exit indicates absence of unexpected infrastructure errors. The independent verifier additionally fails on unmet scientific criteria. Artifacts use unique names and exclusive creation; historical verification needs matching source versions. See the [experiment guide](../experiments/README.md#phase-13-retirement-during-duplicate-resolution).

## Limits and next question

The comparison fixes known callers, one database effect domain, trusted logical epochs and selected pipe-barrier orders. Guard acquisition precedes the measured retirement attempt; its earlier gap remains a fallback obligation. The observer is retained instrumentation and is never queried to produce application outcomes. Receipt deletion is logical, not measured physical reclamation or bounded total storage.

No caller authentication, timer expiry, hostile epoch relabeling, arbitrary many-caller progress, external effect, network failure, WAL, crash or power-loss claim follows. Guarding and safe unavailable responses are established design choices with different availability and ordering costs. No new database primitive or general exactly-once guarantee is claimed.

The next question is what compact retained receipt summaries can preserve after old payload removal. A new protocol must define the evidence needed for each historical replay/conflict claim and keep any retained observer separate from application authority.

## Technical basis

The [protocol's primary sources](RESOLUTION_PROTOCOL.md#technical-basis) document SQLite statement/transaction rollback, writer reservation and numeric result codes, together with original-request identity and retention limits. Those mechanisms motivate the design; the retained records above support the empirical counts.
