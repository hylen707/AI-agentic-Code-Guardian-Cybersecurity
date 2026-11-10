# Phase 16 findings: safe retention is not completed migration

## Result and scope

A finite retry budget makes unfinished migration explicit. Under repeated controller-arranged source changes, validated-only migration completes **12/24** cases and exhausts its budget in the other twelve. It completes all **42/42** declared runtime publication intents and retains every original receipt. Transactional-first migration completes **24/24** cases but completes **0/42** old-epoch publication intents. Switching to transactional selection on the final allowed attempt completes **24/24** migrations and **16/42** publications. All actual committed history remains available in all three policies.

These are separate outcomes. Retaining full receipts after exhaustion preserves history while leaving compaction unfinished. Refusing a request that never committed preserves closure without completing that publication. The fallback completes migration in the arranged order because its last attempt successfully acquires the writer; the result establishes no fairness, starvation freedom or wall-clock bound.

The [protocol](PROGRESS_PROTOCOL.md) and [24-case manifest](../experiments/tasks/progress-eval-v1/tasks.json) were frozen at [`1c6328e`](https://github.com/hylen707/AI-agentic-Code-Guardian-Cybersecurity/commit/1c6328e80c8ef5ee07c00eb5bca447e958e44a71) before the new implementation, tests, controller and verifier. Earlier source and evidence bytes remain unchanged. The study reuses Phase 15's complete-source mechanisms; it adds the finite invocation policy and repeated-interference histories.

## Design and equal opportunities

Every fixture starts with A at revision 1, an epoch-1 `seed-a` approval of B at revision 2, and `seed-b` revocation at revision 3. Migration targets epoch 2. The 24 cases cross attempt budgets B={1,2,3}, distinct old-epoch intents N={0,1,2,4}, and two value patterns. Updates cycle ASCII B, empty update and Unicode; the fourth returns to B. Revocations always use `None` and still advance the revision. Empty update and revocation are different operations.

Each migration attempt pauses after its initial selection. If a declared runtime intent remains, exactly one publisher attempts it while migration is paused. Validated selection permits that publication and rejects the changed source before cleanup. Transactional selection holds its writer from selection through commit; the publisher gets numeric busy 5, then retries the same epoch, ID and bytes after release and is refused after closure.

The controller stops on migration completion or at the attempt limit, saves a stop snapshot, then attempts every remaining declared old intent. Remaining work commits if the namespace is still open after exhaustion; it is refused if migration closed the epoch. No extra migration runs after the limit. All three policies therefore receive the same 42 distinct runtime intents, even when they finish migration at different points.

| Policy | Selection scope | Observed migration behavior |
|---|---|---|
| `validated_budget` | Literal validation on every attempt | Completes in N+1 attempts when N<B; otherwise exhausts at B |
| `transactional_first` | Writer held from the first selection | Completes on attempt 1 |
| `validated_fallback` | Validation until the last allowed attempt, then writer held | Completes within B; B=1 locks immediately |

All attempts use fresh child processes and strict pipe resumes bound to role, stage, attempt and budget. There are **72 case/policy records**, **104 live barriers** and **260 normal child completions**. No sleep controls the order. Only numeric SQLite busy at the publisher's BEGIN is a modeled deferral. Migration acquisition failures and other storage/process errors are infrastructure failures, not progress outcomes.

## Results with separate denominators

| Measure | Validated budget | Transactional first | Validated fallback |
|---|---:|---:|---:|
| Migration completed / cases | 12/24 | 24/24 | 24/24 |
| Budget exhausted / cases | 12/24 | 0/24 | 0/24 |
| Runtime publications completed / equal declared intents | 42/42 | 0/42 | 16/42 |
| Runtime publications refused after closure | 0/42 | 42/42 | 26/42 |
| Original runtime replay / actual committed runtime requests | 42/42 | N/A: 0 commits | 16/16 |
| Original seed replay / seeded requests | 48/48 | 48/48 | 48/48 |
| Changed runtime conflicts / actual commits | 42/42 | N/A: 0 commits | 16/16 |
| Never-committed exact/changed unavailable pairs | 0 | 42 | 26 |
| Missing authoritative receipts | 0 | 0 | 0 |
| Duplicate effects or receipt authority | 0 | 0 | 0 |

The absence of committed runtime requests in transactional-first is a **0/0 replay opportunity**, not 42 successful historical replies. The 48 seeded commitments per policy provide historical controls even in that arm. Both original and changed-intent queries leave the database unchanged in all 72 cases, so acknowledgments do not restore an older approval over the current state.

| Attempt and representation accounting | Validated budget | Transactional first | Validated fallback |
|---|---:|---:|---:|
| Migration attempts / barriers | 40 | 24 | 40 |
| Stale attempts, each equal to its pause snapshot | 28 | 0 | 16 |
| Busy publication attempts / completed same-intent retries | 0 / 0 | 18 / 18 | 12 / 12 |
| Runtime replay from compact / full authority | 8 / 34 | 0 / 0 | 16 / 0 |
| Final summary rows, including seeds | 32 | 48 | 64 |
| Final full receipt rows, including seeds | 58 | 0 | 0 |
| Publisher children / total children | 42 / 82 | 60 / 84 | 54 / 94 |
| Unexpected infrastructure errors | 0 | 0 | 0 |

Validated-only's 58 full rows occur in its twelve open, exhausted cases: 24 seeded rows plus 34 runtime rows. Its twelve completed cases instead retain 32 summary rows: 24 seeded plus eight runtime. Those full rows are valid authority, but their presence is not completed compaction. Fallback's 64 summaries bind 48 seeded and sixteen runtime commits; transactional-first's 48 summaries bind only the seeds.

### The budget boundary

Each cell below describes validated-only migration; each B/N pair has two value-pattern cases.

| Attempt budget | N=0 | N=1 | N=2 | N=4 |
|---|---|---|---|---|
| B=1 | Complete on 1 | Exhaust on 1 | Exhaust on 1 | Exhaust on 1 |
| B=2 | Complete on 1 | Complete on 2 | Exhaust on 2 | Exhaust on 2 |
| B=3 | Complete on 1 | Complete on 2 | Complete on 3 | Exhaust on 3 |

This is an observed boundary for the injected history: one fresh interference per available candidate selection. It is not a probability estimate or a statement about arbitrary scheduling. Increasing a finite budget does not make success unconditional when changes can continue through every allowed attempt.

### One concrete B=3, N=4 update history

| Policy | Stop snapshot and remaining work | Final current state and retained authority |
|---|---|---|
| Validated budget | Three publications commit and stale all three attempts; stop at epoch 1, revision 6. The fourth then commits without another migration. | Epoch 1, revision 7, ASCII B; six full receipts |
| Transactional first | First publisher is busy; migration closes epoch 1 on attempt 1. Its retry and the remaining three are refused. | Epoch 2, revision 3, approval revoked; two summaries |
| Validated fallback | Two publications commit and stale attempts 1–2. Attempt 3 holds the writer; the third publisher is busy, then refused, as is the fourth. | Epoch 2, revision 5, approved empty value; four summaries |

In each history an original revision-4 response, if that request actually committed, remains distinct from the final current revision. Querying the earlier receipt never rolls the publication back.

## Implementation and independent checks

[`progress_store.py`](../src/progress_store.py) validates policy/budget/attempt inputs and selects an existing Phase 15 scope. [`progress_worker.py`](../experiments/progress_worker.py) supplies the numbered live barrier. [`run_progress_comparison.py`](../experiments/run_progress_comparison.py) owns the finite invocation loop and retains all attempts, including stale rollbacks and busy publisher retries. Budgets are per invocation and are not persisted across process restarts.

The [independent verifier](../experiments/verify_progress_results.py) imports only the standard library. It reconstructs original intents, actual publication history, current delivery, receipt types, source sets, child commands/events, selection policy, transaction witnesses, causal snapshots, query support and every summary counter. All **ten prospective criteria pass**. It verifies the input and **thirteen source hashes**. These hashes and caller-supplied commit labels are reproducibility records, not external attestation.

The full suite passes **386 tests**, including **33 new tests**. Regression checks cover repeated staleness and revocation, quiet completion after interference, budget-one fallback, unchanged historical replies, empty/Unicode intent, rollback and writer release, migration-BEGIN error classification, cross-attempt resume rejection, incorrect busy codes, altered causal prefixes, invented historical replies, and preserved failure records. A consistently recorded wrong replay still produces failed scientific criteria; agreement between the raw file and its stored oracle is insufficient.

## Evidence and reproduction

Recorded run: `2026-11-10T05-04-15-304663Z-progress-v1`; Python 3.12.14, SQLite 3.53.1, Linux. Narrative date: 2026-11-10, Asia/Seoul. The starting implementation was [`ad638dd`](https://github.com/hylen707/AI-agentic-Code-Guardian-Cybersecurity/commit/ad638dd74700359375003d7d38d0674b572eab5f); the design freeze is linked above.

- [72 raw records](../experiments/results/2026-11-10T05-04-15-304663Z-progress-v1.jsonl)
- [Summary, environment, command and hashes](../experiments/results/2026-11-10T05-04-15-304663Z-progress-v1-summary.json)
- [Independent reconstruction](../experiments/results/2026-11-10T05-04-15-304663Z-progress-v1-verification.json)
- [386-test transcript](../experiments/results/2026-11-10T05-04-15-304663Z-progress-v1-unit-tests.txt) and [experiment console](../experiments/results/2026-11-10T05-04-15-304663Z-progress-v1-console.txt)

From the repository root:

```bash
python -m unittest discover -s tests -v
python experiments/run_progress_comparison.py \
  --dataset experiments/tasks/progress-eval-v1/tasks.json \
  --base-commit "$(git rev-parse HEAD)" \
  --freeze-commit 1c6328e80c8ef5ee07c00eb5bca447e958e44a71 \
  --output-dir /tmp/codeguardian-progress
python experiments/verify_progress_results.py \
  --summary experiments/results/2026-11-10T05-04-15-304663Z-progress-v1-summary.json \
  --dataset experiments/tasks/progress-eval-v1/tasks.json
```

The first runner records the currently executed checkout; to verify that fresh run, pass its new summary path. The last command verifies the retained historical run against unchanged source bytes. Use the [experiment guide](../experiments/README.md#reading-and-preserving-artifacts) to distinguish those operations. The runner and verifier return nonzero when criteria fail; failures remain in the raw records.

## Interpretation and next question

This study separates safe history retention from finishing migration within an explicit attempt limit. The fallback converts the final allowed attempt into an ordering decision that trades publication completion for closure. It is one tested policy, not an optimality claim; a fresh source read after writer acquisition is another possible design. SQLite's [transaction control](https://sqlite.org/lang_transaction.html) and [isolation](https://sqlite.org/isolation.html) describe the underlying single-writer behavior and acquisition failures, rather than promising scheduler fairness.

The setup gives migration access to the writer at its declared attempt boundaries and contains at most a migrator and one publisher child at a time. There is no wall-clock measurement, restart-persistent budget, crash/interference composition, multiple-compactor study, general many-caller guarantee, physical erasure or production validation. Compact receipts retain Phase 14's typed SHA-256 and trusted-metadata assumptions. Measurement witnesses cannot reconstruct missing authority for the application.

The next question is restart continuity: if a migration process stops and restarts, does it retain the attempt budget and report a truthful outcome without losing earlier publication history? A new prospective design is required before making that claim.
