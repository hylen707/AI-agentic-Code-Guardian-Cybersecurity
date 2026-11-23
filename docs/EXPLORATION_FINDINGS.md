# Phase 22: generated histories expose what sequential checks miss

[Documentation index](README.md) · [Frozen protocol](EXPLORATION_PROTOCOL.md) · [Grammar](../experiments/tasks/exploration-eval-v1/grammar.json)

## Question and result

Phase 21 used handwritten histories to separate retired admission from late delivery of a valid result. Phase 22 generates a finite history space against those **unchanged mechanisms** and adds an abstract observable-prefix consistency check.

Across **3,372 records**, transactional admission explains all **1,124/1,124 histories** and **9,458/9,458 observed prefixes** under the current-epoch sequential contract. Cached admission passes all **512 sequential histories**, yet fails **17 of 612 declared overlap histories**. Those failures contain seventeen retired decisions and ten retired grants. All treatments observe a maximum of two result rows in this shallow grammar: passing the row-count check does not establish current-epoch membership or valid authority.

All **581 tests** pass, including 27 added regressions. Independent verification passes all five criteria, including retained weak-arm counterexamples. No mechanism improvement or arbitrary-history proof is claimed by this stage.

## Prospective finite coverage

The protocol and grammar were frozen at [`72ec18d`](https://github.com/hylen707/AI-agentic-Code-Guardian-Cybersecurity/commit/72ec18deca46756349e3cad33a640432058f3d6b), parent Phase 21 main `aba4945d9b866a865c3dd49b6e9bf6a0dcb73505`, before the generator, controller and new checker were implemented. All inherited mechanism, transport and reference sources remain byte-identical to that base.

| Family, per arm | Frozen construction | Declared histories |
|---|---|---:|
| Sequential | Eight templates in every length-three ordering. Observations cover their shorter prefixes. | 8³ = 512 |
| Overlap candidates | Nine zero/one-operation seed prefixes; eight ordered caller pairs; every declared caller-A checkpoint; continue or marked exit. | 9 × 34 × 2 = 612 |
| Total | Three unchanged treatments. | 1,124 per arm; 3,372 records |

The alphabet includes original, changed, distinct-current and future requests, expected-epoch advancement and closure. Request inputs may refer to the current epoch/token. In overlap candidates, **both callers' exact inputs are resolved before either starts**. A requests one pivot; B completes; A then continues or exits if it actually paused. This enumerates the specified single-pivot grammar, not every interleaving of two processes.

A path can finish before reaching its requested checkpoint. Erase-only realizes 552/612 pivots; each guarded arm realizes 534/612. The remaining 60, 78 and 78 candidates are retained as serial executions, without fabricated continuations or exits. No state deduplication removes a declared record. The mixed UTF-8 fixture retains a Unicode publication and a revocation.

## Two checking layers

The first layer reuses Phase 21's unchanged independent reference. It reconstructs writer ownership, admission, lookup/capacity, decision/result and advancement/deletion commits, rollback and exact typed wire bindings. It checks the raw stream against decoded events and every coherent snapshot. The new verifier imports that stdlib-only reference, never the generator, controller, worker or mechanism; transitive source identity is checked explicitly.

The second layer implements a separate sequential API specification over the observable recovery epoch, authority, append-only grants, publication target and retained results. It does not use transaction events or witnesses to determine an outcome. Admission precedes lookup; lookup precedes capacity; advancement compares, deletes and increments. Busy is an exact no-effect reply, whose actual writer justification is checked by the first layer.

At each retained boundary, search all bounded orders consistent with invocation/response intervals. Completed calls must return their exact observed answer. A pending or crashed call may be omitted or included with an unobserved reply, but the resulting application state must match the snapshot. Included crashed calls must precede their observed termination. Parent-controlled event order defines intervals; wall-clock timing does not choose winners.

This permits a committed result to return after retirement. It cannot justify a retired result row by simply moving the request before advancement: advancement would have deleted that row. Checking prefixes also prevents a later cleanup from hiding an earlier inconsistent observation. Snapshot observations repeat some prefixes; history counts and unique state signatures remain separate.

## Independently reconstructed results

| Family | Treatment | Consistent histories / declared | Consistent prefix observations | Retired grants |
|---|---|---:|---:|---:|
| sequence | `erase_only` | 470/512 | 3,870/4,096 | 30 |
| sequence | `cached_floor` | 512/512 | 4,096/4,096 | 0 |
| sequence | `atomic_floor` | 512/512 | 4,096/4,096 | 0 |
| overlap | `erase_only` | 536/612 | 4,936/5,380 | 45 |
| overlap | `cached_floor` | 595/612 | 5,277/5,362 | 10 |
| overlap | `atomic_floor` | 612/612 | 5,362/5,362 | 0 |

Erase-only has **118 inconsistent histories** across both families and 75 retired grants. Cached admission has seventeen inconsistent overlap histories and ten retired grants. The transactional treatment has none. All three still close **1,124/1,124** targets, replay **2,248/2,248** publication originals and reject **2,248/2,248** changed publication intents. Infrastructure, caller, transport-response and publication failures are zero in every group.

Transactional admission produces 282 busy replies in overlap candidates, versus 172 for cached and 186 for erase-only. These are observed deferrals, not a fairness or latency result. Recovery-result membership and historical publication authority remain distinct.

| Family | Treatment | Unique observable state signatures | Unique controller-labeled transitions |
|---|---|---:|---:|
| sequence | `erase_only` | 158 | 666 |
| sequence | `cached_floor` | 116 | 560 |
| sequence | `atomic_floor` | 116 | 560 |
| overlap | `erase_only` | 80 | 456 |
| overlap | `cached_floor` | 76 | 430 |
| overlap | `atomic_floor` | 51 | 339 |

These signatures deduplicate the recorded application projection and labeled boundary transitions. They do not count the complete abstract reachable-state graph. Weak-arm signatures can include illegal states. Counts are not pooled into a population security percentage.

## Short observed counterexamples

A sequential `advance → old_a` prefix is sufficient for erase-only: the epoch advances to 2, then a literal epoch-1 request is evaluated and stored. The row count remains one, but no legal current-epoch sequential execution produces that result.

For cached admission, the shortest observed overlap failure starts with `current_a` paused after admission. Advancement commits and returns. A then commits its old-epoch request. Reordering A before advancement would remove its result; ordering A afterward would reject it. Neither order explains the observed row and grant together. The transactional arm instead defers advancement while A holds the writer.

The [verification artifact](../experiments/results/2026-11-23-exploration-v1-verification.json) retains the shortest observed failing prefix for each weak arm/family, selected by invocation count, boundary count and case ID. This selection is over generated observations, not a globally minimal proof. A separate positive control confirms that a result committed before retirement may be delivered afterward without an inconsistency.

## Verification and reproduction

The retained run uses **Python 3.12.14 on Linux**. It records **3,672 children**, **1,620 realized live pivots**, **810 marked exits**, **2,862 normal child terminations** and **9,612 parent API operations**. The 216 unreached candidates remain in the grid. All 3,372 histories have coherent raw/decoded streams, exact commands, snapshots, replies, grant/result witnesses and publication controls. The compressed archive is hashed before lossless decoding.

New regressions cover pending/crashed inclusion, omitted operations, completed-call real-time order, late delivery, capacity and identity, typed Boolean substitutions, fixed paired inputs, false exits, forged states, coherent wrong replies, missing rows and transitive reference/hash changes. Final source passes the full 581-test suite. Prior Phase 20 and 21 retained evidence also verifies unchanged.

```bash
python -m unittest discover -s tests -v
python experiments/run_exploration.py \
  --output /tmp/codeguardian-exploration-v1.jsonl.gz \
  --base-commit aba4945d9b866a865c3dd49b6e9bf6a0dcb73505 \
  --freeze-commit 72ec18deca46756349e3cad33a640432058f3d6b
python experiments/verify_exploration.py /tmp/codeguardian-exploration-v1.metadata.json
```

| Artifact | Content |
|---|---|
| [Raw histories](../experiments/results/2026-11-23-exploration-v1.jsonl.gz) | All 3,372 compressed JSONL records. |
| [Metadata](../experiments/results/2026-11-23-exploration-v1.metadata.json) | Frozen/base/source/raw identities and independently recounted controller measures. |
| [Independent checks](../experiments/results/2026-11-23-exploration-v1-verification.json) | Trace counts, abstract-prefix results, state/transition signatures and short counterexamples. |
| [Final full test output](../experiments/results/2026-11-23-exploration-v1-tests.txt) | All 581 passing tests. |
| [Execution record](../experiments/results/2026-11-23-exploration-v1-execution.json) | Commands, observed exits and elapsed times; temporary intermediate outputs are identified. |

## Limits and next boundary

This covers eight templates, depth three, nine overlap seed prefixes, one A pivot, two children, capacity two, one mixed UTF-8 fixture, trusted administrators and application-boundary process exits. It does not exhaust the scheduler or prove arbitrary histories, authentication, fairness, host/storage/power durability, total database bytes or lifetime work. The reference reconstruction and abstract specification can share conceptual assumptions. Observer access to coherent snapshots is part of the evaluation, not a production client guarantee.

The next coverage boundary is a second independently scheduled pivot or a third caller, with an explicit larger grammar and separately reported denominators. This stage establishes the value and limits of generated-prefix checking without silently enlarging its claim.
