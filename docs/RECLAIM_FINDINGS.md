# Phase 19 findings: reusable permission must fence the displaced holder

## Claim and accounting contract

**Reassigning a slot does not stop its former holder. Checking its token in a separate scope can still become obsolete before the write.** In the twenty selected cases per arm, invalid migration effects are **10 → 2 → 0** for cached permission, a separate fence check, and a check inside the committing transaction. Every arm eventually closes its target and preserves publication history. Those successful outcomes do not make the weak-arm effects authorized.

This is a reusable-authority experiment, not a refund of Phase 18's lifetime attempt budget. Each fixture has one current permission slot. Its owner/token pair changes by trusted compare-and-swap, and every grant remains in an append-only history. A fixture can have three lifetime grants while retaining one current slot. These results do **not** establish that Phase 18's ten unfinished cases can be completed under their original cumulative limit.

The [protocol](RECLAIM_PROTOCOL.md) and [20-case manifest](../experiments/tasks/reclaim-eval-v1/tasks.json) were frozen at [`ea005ce0a6c26e01ba90a4271900663407acd5b0`](https://github.com/hylen707/AI-agentic-Code-Guardian-Cybersecurity/commit/ea005ce0a6c26e01ba90a4271900663407acd5b0) before implementation. The existing mechanism modules remain byte-identical to base `baf986b4fa701c38bd2407e114c87b0773b4cc51`; the new store lives in its own reclamation module. The earlier Phase 18 and pilot evidence still verify unchanged.

## Design and observations

Ten histories are crossed with update/revocation patterns: **20 cases per arm, 60 case/arm records**. Each fixture has two seeded publication receipts; seed values distinguish a Unicode update, an empty update and typed revocation. Two cases per arm also publish a declared source change. Two real child processes exercise the original and current authority. Exact generation/owner/token/checkpoint bindings control continuation or marked code-73 exit.

Recovery is an explicit trusted operation; it does not decide whether a process is dead. The experiment deliberately keeps the displaced holder alive. A replacement either commits a new token, returns an unchanged busy/conflict response, or observes an already completed target and grants nothing. Token checks, source validation and actual effect authorization have separate observations. The independent stdlib verifier reconstructs grants, selected sources, writer ownership, tentative writes, commit/rollback and every response without importing the mechanisms or controller.

| Measure | Cached permission | Separate fence | Transactional fence |
|---|---:|---:|---:|
| Cases | 20 | 20 | 20 |
| Migration effects with invalid owner/token / 20 | 10 | 2 | 0 |
| Original-holder migration effects, valid or invalid | 16 | 8 | 8 |
| Stale-token refusals | 0 | 10 | 10 |
| Independent source-change refusals | 2 | 0 | 0 |
| Committed replacement grants | 16 | 16 | 14 |
| Recovery calls blocked by the writer | 4 | 4 | 6 |
| Conflicting recovery calls | 2 | 2 | 2 |
| Recovery calls observing completion, without a grant | 6 | 6 | 6 |
| Lifetime token grants, including twenty initial grants | 36 | 36 | 34 |
| Final target completion / 20 | 20 | 20 | 20 |
| Actual historical originals replayed | 42/42 | 42/42 | 42/42 |
| Changed-intent conflicts | 42/42 | 42/42 | 42/42 |
| Unexpected caller/response/infrastructure errors | 0 | 0 | 0 |

Each arm records four marked exits, thirty-six normal child completions and eighteen live barriers. Across the study there are **120 child processes, 12 marked exits and 54 bound barriers**. All queries are inert; every recovered snapshot matches the independently reconstructed committed state. Historical reply denominators comprise forty seeded originals plus two committed source publications per arm. No count is pooled with Phase 18 or interpreted as a race probability.

## Counterexamples and mechanism boundary

**A successful recovery request can leave a live stale writer.** When replacement commits before the old caller selects or writes, cached permission can still close the target using token 1 after authority has advanced. Instrumentation observes the current token inside the writer transaction but does not authorize weak arms. Thus coherent receipt compaction and a correct `migrated` receipt can coexist with an invalid authority decision.

**A separate check has its own gap.** In `reclaim_after_fence`, the old caller has just checked owner 1/token 1. Replacement commits owner 2/token 2 before its later write. Both cached and separate-check arms commit an invalid effect in the two value-pattern cases. The transactional arm holds the SQLite writer across its check and effect. The recovery request is busy, not a completed revocation; the still-authorized caller commits first. Recovery then truthfully reports completion without allocating a new token. The two additional busy recoveries and two fewer replacement grants expose that ordering cost.

**Owner equality does not restore an old token.** In `aba_owner`, authority moves 1/1 → 2/2 → 1/3. The old owner label matches again, but token 1 is not token 3. The separate and transactional checks refuse the stale holder; cached permission produces an invalid effect. Tokens, not owner labels alone, carry the displacement history.

**Source validity and authority validity differ.** After a declared source publication, cached permission rejects its earlier source and the replacement caller migrates the current receipts. The other arms reject the old token first. Those two source refusals are not evidence that cached authority was valid.

**Interruption must be interpreted at the commit boundary.** A before-commit exit releases the writer and rolls back tentative compaction; replacement then grants a new token and the next caller completes. An after-commit exit loses the reply but retains closure, so recovery grants nothing. A stale expected-token recovery request conflicts and never creates an extra grant.

## Verification and reproduction

The retained run uses Linux x86-64/Python 3.12.14. **486 tests passed**, including 31 new regressions. The worker and independent verifier check binding types as well as values: JSON `true` must not impersonate integer token `1`. Tests cover live wrong/Boolean bindings, owner reuse, stale recovery CAS, token exhaustion, policy binding, non-busy storage errors, writer-held recovery, rollback, lost replies, causal order, raw streams, grant/effect witnesses, provenance and historical answers. Consistently recorded false completion or wrong history still fails the corresponding criterion.

```bash
python -m unittest discover -s tests -v
python experiments/run_reclaim_comparison.py \
  --output /tmp/codeguardian-reclaim-v1.jsonl \
  --base-commit baf986b4fa701c38bd2407e114c87b0773b4cc51 \
  --freeze-commit ea005ce0a6c26e01ba90a4271900663407acd5b0
python experiments/verify_reclaim_results.py /tmp/codeguardian-reclaim-v1.metadata.json
```

- [Raw histories](../experiments/results/2026-11-18-reclaim-v1.jsonl)
- [Frozen/base/source/raw identities and controller counts](../experiments/results/2026-11-18-reclaim-v1.metadata.json)
- [Independent reconstruction and criteria](../experiments/results/2026-11-18-reclaim-v1-verification.json)
- [Full test output](../experiments/results/2026-11-18-reclaim-v1-tests.txt) and [execution environment](../experiments/results/2026-11-18-reclaim-v1-execution.json)
- [Store](../src/reclamation/store.py), [worker](../experiments/reclaim_worker.py), [controller](../experiments/run_reclaim_comparison.py), [independent verifier](../experiments/verify_reclaim_results.py), [tests](../tests/test_reclaim.py)

Source identities cover the new store and harness, the inherited publication mechanisms and the reused process transport. Frozen files must match their Git objects and the declared freeze parent. Failed infrastructure records retain their place in the full grid. The transactional arm's claim requires zero invalid effects, unsupported answers, history loss and infrastructure failures; final completion is reported independently.

## Limits and next question

This is a fixed-target, trusted-controller study on disposable fixtures. The token gates migration, while source publication and replacement are separately trusted operations. It does not provide client authentication, a secret capability, automatic failure detection, fairness, a clock-based lease, arbitrary many-caller correctness, host-power-loss durability or a lifetime-work limit. Writer ordering is granted by the controller. The reference model checks these selected histories, not every concurrent execution.

The next boundary is recovery of the replacement operation itself: overlapping recovery requests and a process exit before or after the durable grant can leave a caller uncertain whether its particular replacement committed. The current parent recovery calls always return; no historical recovery-request result or automatic retry policy is established here.
