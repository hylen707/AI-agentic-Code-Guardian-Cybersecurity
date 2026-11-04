# Phase 10 findings: forgetting a request does not retire its intent

**Study:** 20 cases in each of four arms, 80 case/arm records. **Recorded run (UTC):** `2026-11-04T15:09:50.473480Z`.

## Question and result

Phase 9 binds a publication to a retained request receipt. Phase 10 removes that retention assumption. Each request now carries an epoch as well as its ID, operation, and exact payload. Retirement closes the old epoch to new mutations while optionally preserving its historical replies.

| Outcome | Retain all | Forget only | Delete, then fence | Atomic fence |
|---|---:|---:|---:|---:|
| Known late requests with an extra effect / 10 | 0/10 | 6/10 | 2/10 | 0/10 |
| Later policy preserved / those 10 | 10/10 | 4/10 | 8/10 | 10/10 |
| Original historical commitment returned / 10 | 10/10 | 4/10 | 2/10 | 4/10 |
| Known closed-epoch requests safely rejected / 6 | 0/6 | 0/6 | 6/6 | 6/6 |
| Revoked value reinstated by an old request | 0 | 3 | 1 | 0 |
| Newer approval withdrawn by an old request | 0 | 3 | 1 | 0 |
| Recovery captures with deletion ahead of fence | 0 | 0 | 2 | 0 |
| Old receipt rows per completed retirement | 2 | 0 | 0 | 0 |
| New active-epoch intents completed / 3 | 3/3 | 3/3 | 3/3 | 3/3 |
| Active-epoch repeats correctly handled / 2 | 2/2 | 2/2 | 2/2 | 2/2 |
| Active-epoch conflicts correctly rejected / 2 | 2/2 | 2/2 | 2/2 | 2/2 |
| Previously unseen old requests rejected / 2 | 2/2 | 0/2 | 2/2 | 2/2 |
| Future-epoch request rejected / 1 | 1/1 | 1/1 | 1/1 | 1/1 |
| Intrinsically coherent final content/approval / 20 | 20/20 | 20/20 | 20/20 | 20/20 |
| Declared worker exits / 8 | 8/8 | 8/8 | 8/8 | 8/8 |
| Normal retirement completions / 12 | 12/12 | 12/12 | 12/12 | 12/12 |
| Infrastructure errors | 0 | 0 | 0 | 0 |

The denominator sets overlap. Ten known-request schedules contain update/revocation fixtures at normal completion or four interruption boundaries. Six of those ten recover a completed retirement; the other four precede its commit. Sixteen of all 20 cases recover completed retirement. Before any follow-up request, each retaining-store capture has its two seeded old receipts, 32 old rows across those 16 observations; compact stores have zero. These are logical row counts, not disk reclamation or memory measurements.

## Why deletion reopens a completed request

Every fixture first commits epoch-1 ID 1 at revision 2, then an opposing policy under ID 2 at revision 3. One fixture approves B and later revokes it. The other revokes and later approves C. Current payload, approval, and revision remain transactionally coupled in every arm.

The forgetting arm deletes old receipts and advances its epoch together, but omits the rule that a missing receipt from an older epoch must be rejected. After completed retirement, each old ID 1 looks new. Its update or revocation creates revision 4. Three update schedules reinstate revoked B; three revocation schedules withdraw the newer C approval. Both previously unseen old IDs also apply. Merely forgetting state does not establish which old intent is still admissible.

The retaining arm keeps the receipt, returns its original revision-2 commitment, and leaves revision 3 intact in all ten known-request cases. Its historical-response availability depends on keeping the two old records. It still rejects previously unseen requests from the closed epoch, so retaining history does not reopen that epoch for new work.

## Cleanup itself needs a recovery boundary

The split arm first commits receipt deletion, then commits the epoch advance. At its `after_cleanup` cut, both old receipts are gone but active epoch 1 remains. A reopened publisher sees an admissible epoch and no matching receipt, so both selected old requests apply again. This produces one reinstated revoked value and one withdrawn newer approval. The same arm rejects all six old known requests after the fence has committed.

The atomic arm changes the epoch and deletes older receipts in one transaction. Its after-cleanup cut is still before commit: reopening recovers epoch 1 and both receipts, allowing a historical replay with no mutation. After commit, reopening sees epoch 2 and no old receipts, so it rejects epoch 1. All ten selected known requests preserve the later policy, with zero duplicate effects and zero old rows after completed retirement.

The old request's effect is counted using the full `(epoch, ID)` pair. An epoch-2 request using the same literal ID is a legitimate new intent and completes at revision 4. It is not counted as a repeated epoch-1 effect. Empty and Unicode updates, two current-epoch repeats, two parameter conflicts, and a future-epoch rejection provide separate controls.

## Historical response availability is the price of forgetting

The atomic arm returns the original receipt in the four known-request cases where retirement has not committed. After completed retirement it safely rejects all six remaining known requests with `epoch_retired` and no commitment revision. It cannot return the deleted historical receipt. The retaining arm can return that receipt in all ten cases.

Closing the epoch also rejects two previously unseen requests issued in that old epoch. This is the explicit cutoff contract, including its cost to delayed work. A refusal is not evidence that the original request completed, and it does not tell the caller to automatically relabel that request as a fresh intent. A new epoch denotes a new trusted publication decision.

The epoch is a trusted namespace/freshness input. This fixture does not authenticate clients or prevent a malicious caller from relabeling old intent with a newly authorized epoch. The experiment studies cooperating publishers preserving request identity.

## Fault model, tests, and independent recount

The child retires epoch 1 to target 2 and emits an exact flushed JSON trace. There are 32 real `os._exit(73)` terminations and 48 normally completed retirement workers. The parent validates both the event prefix and exit status, then reopens for each capture and follow-up publication. A random failure, timeout, or malformed observation cannot become a successful denial.

The `before_retire` cut precedes writes. The split after-cleanup cut follows a committed deletion; the same logical cut in other arms leaves one transaction uncommitted. `after_commit` precedes the acknowledgment; `after_ack` follows it. All recovered layouts match those declared distinctions. The parent, kernel, filesystem, and SQLite library keep running; no cut lies inside a storage call or recovery operation. This establishes no power-loss, torn-write, or recovery-crash guarantee.

All SQLite captures report `journal_mode=delete`, `synchronous=2` (`FULL`), and `integrity_check=ok`. The **176-test suite passes**, including 35 new tests for scoped identity, target retry without another epoch advance, exact parameter binding, epoch and cleanup write failures, real child exits, false rejection labels, timeout/error accounting, and forged observations. Target-retirement retry is covered by unit tests; the experiment grid performs one retirement per fixture.

The independent verifier imports neither stores, worker, nor measured runner. It enumerates expected committed effect prefixes and physical receipt layouts, rebuilds current delivery and historical-response fields, and checks every raw counter and all **twelve prespecified criteria**. The recount matches all 80 rows with zero infrastructure errors. The manifest hash and **eight source hashes**, including unchanged Phase 8 and Phase 9 dependencies, match the measured run. This is artifact consistency verification, not an external evaluation of the store or SQLite.

## Evidence and reproduction

The [protocol](RETIREMENT_PROTOCOL.md) and [20-case manifest](../experiments/tasks/retirement-eval-v1/tasks.json) were committed before Phase 10 implementation at [`b6e1c71`](https://github.com/hylen707/AI-agentic-Code-Guardian-Cybersecurity/commit/b6e1c712648f7f0225fe236238badddf30b9e41d). The cases were visible during development. Earlier code, frozen plans, inputs, and measured artifacts retain their bytes.

- [80 raw state, epoch, effect, receipt, and response records](../experiments/results/2026-11-04T15-09-50-473480Z-retirement-v1.jsonl)
- [Summary, denominators, hashes, versions, platform, and command](../experiments/results/2026-11-04T15-09-50-473480Z-retirement-v1-summary.json)
- [Independent prefix and retirement recount](../experiments/results/2026-11-04T15-09-50-473480Z-retirement-v1-verification.json)
- [Full 176-test transcript](../experiments/results/2026-11-04T15-09-50-473480Z-retirement-v1-unit-tests.txt)
- [Experiment console](../experiments/results/2026-11-04T15-09-50-473480Z-retirement-v1-console.txt)

```bash
python -m unittest discover -s tests -v
python experiments/run_retirement_comparison.py --dataset experiments/tasks/retirement-eval-v1/tasks.json --base-commit "$(git rev-parse HEAD)" --freeze-commit b6e1c712648f7f0225fe236238badddf30b9e41d
python experiments/verify_retirement_results.py --summary experiments/results/2026-11-04T15-09-50-473480Z-retirement-v1-summary.json --dataset experiments/tasks/retirement-eval-v1/tasks.json
```

Use a fresh run's printed summary filename to audit that run. Full historical verification requires matching all eight source versions. The base/freeze arguments are recorded provenance labels; they do not check out or validate a commit. New outputs use exclusive creation. Runner exit status reports infrastructure errors; verifier status also reports unmet scientific criteria. See the [experiment guide](../experiments/README.md).

## Limits and next question

This is an explicit logical-epoch retirement in a trusted sequential database fixture. It does not implement wall-clock TTL, caller authentication, tenant isolation, physical storage reclamation, or external side-effect coordination. The effect observer retains history and grows; one epoch counter does not bound the entire database. Large stores, multiple resources, schema migration, simultaneous publication/retirement, and live-task adapters remain outside this run.

A fence-first design with later cleanup remains a separate comparison; the observed two-step failure concerns deletion-first ordering.

The next question is a request admitted before retirement but writing after it: must epoch validation share the publication transaction when retirement and publication overlap? A future protocol should fix that interleaving, count actual old-epoch effects, and retain ordinary concurrent-request controls before claiming safety for multiple writers.
