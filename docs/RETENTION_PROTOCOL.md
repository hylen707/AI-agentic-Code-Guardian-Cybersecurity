# Phase 21 protocol: bounded recovery results without reopened request space

**Prospective status:** freeze this protocol and manifest before implementing the retention store, worker, controller or independent verifier. No Phase 21 result is asserted here.

## Question and changed contract

Phase 20 retains every recovery result. Can a trusted administrator retire those results while old or already-admitted requests remain unable to acquire authority under that retired request space?

Recovery requests now contain the exact `(recovery_epoch, request_id, expected_token, owner)` tuple. The recovery epoch is distinct from the publication target epoch and from the monotonic authority token. One durable singleton names the current recovery epoch, initially 1. A trusted `advance_epoch(expected_epoch)` operation atomically compares that value, advances it by one and deletes results in older recovery epochs. A conflicting comparison returns the current epoch; a lost advancement reply does not promise the original advancement result. Epoch overflow fails closed.

Only the current recovery epoch admits requests. Older epochs return `retired`; later epochs return `future_epoch`, with no decision, result or grant. Retirement intentionally ends historical-result retrieval: a retired request is rejected even when its ID was never used. Within the current epoch, first durable non-busy decisions, including conflicts and target-completed decisions, bind ID, exact inputs and historical outcome. Same-intent retries replay; changed intent returns `request_conflict`. The same textual ID in a newly admitted recovery epoch is a new logical request. Its old token is never restored.

Each recovery epoch has a fixed capacity of **two result rows**. Existing-result lookup precedes the capacity check. An unrecorded ID at capacity returns `capacity_exhausted` without binding that ID. Busy also binds nothing. Safe advancement deletes older rows and frees capacity in the new epoch. Thus the intended application result set has at most two rows and one epoch counter, without per-ID retirement tombstones. This is a bound on logical application results, not total SQLite bytes: append-only authority grants and observer witnesses are retained for evaluation, and file-page reclamation, input-byte growth and arbitrary long histories are excluded.

## Arms and causal contrast

| Arm | Recovery-epoch admission |
|---|---|
| `erase_only` | Checks future epochs but admits old epochs after their results have been deleted. |
| `cached_floor` | Checks current/retired/future in a separate read snapshot, then uses that permission in a later writer transaction. |
| `atomic_floor` | Checks the epoch inside the same writer transaction as ID lookup, capacity, decision, grant and result. |

All arms use atomic retirement and Phase 20's atomic decision/result coupling, with namespaced result keys. Only admission placement/treatment differs. All migration effects retain the unchanged Phase 19 transactional authority fence. Recovery and advancement are trusted explicit operations, not authentication, automatic failure detection or a lifetime-work budget.

A result committed before retirement may be delivered afterward: its linearization preceded advancement. In contrast, a cached admission does not authorize a new decision after its epoch has retired. The observer witness records the actual epoch at decision commit, not the cached check. Observer decisions and retirement witnesses never answer API queries or admit requests. Original/changed probes and raw streams must distinguish lost result availability from reopened authority.

## Frozen histories and execution

Sixteen histories cross ASCII/revoked and Unicode/empty publication fixtures: **32 cases per arm, 96 case/arm records**. Both patterns retain an additional Unicode publication update. Exact inputs, process generations, pause stages and continuation/exit actions are fixed in `experiments/tasks/retention-eval-v1/tasks.json`.

| History | Boundary exercised |
|---|---|
| `quiet_retirement` | Original, changed and never-used old IDs after retirement; textual ID reused in the new epoch. |
| `exit_before_rotation` | Advancer exits before its transaction commits; the old result survives rollback. |
| `exit_after_rotation` | Advancement commits but its reply is lost; a retry conflicts safely. |
| `exit_before_rotation_reply` | Completed storage work, then marked exit before delivery. |
| `stale_admission_unused` | A pauses after epoch admission; B attempts retirement; A continues, followed by retirement retry. |
| `stale_admission_changed` | Same ordering with an ID whose original result is deleted during the gap. |
| `lookup_holds_writer` | Result lookup holds the writer; advancement defers, then succeeds on retry. |
| `rotation_holds_writer` | Advancement holds the writer; request defers, then retries after retirement. |
| `reply_after_retirement` | A commits a result, B retires it, then A delivers the committed historical reply. |
| `capacity_and_reuse` | Two results, overflow, same-ID replay/conflict, retirement and new-epoch reuse. |
| `multiple_rotations` | Four populated epochs and repeated deletion, including repeated textual IDs. |
| `future_namespace` | Future requests and wrong expected advancement cannot create implicit epochs. |
| `closed_target_retirement` | Retire recovery results after target closure; preserve publication history. |
| `conflict_retirement` | An original conflict would become applicable if retirement reopened its old ID. |
| `decision_rollback_then_retire` | Request exits before decision commit; neither result nor grant survives. |
| `lost_result_then_retire` | Request commits, loses its reply, and its result is deliberately retired. |

Workers pause at declared application boundaries, bind role, generation, exact typed input and stage, then accept an exact typed continuation or emit a flushed marker and exit with code 73. Before-commit exits test SQLite rollback; after-commit exits preserve effects. No arbitrary timing or sleeps select winners. At most two children overlap; the parent and OS survive. Failed infrastructure rows remain in the full grid.

After each frozen history, advance the current recovery epoch once more. Probe each actual first decision's original and changed intent plus a never-used old ID. Record every API event and coherent before/after snapshot. Then submit two fresh current-epoch IDs, probe their originals and changed intents, and attempt one overflow. Close the target with current authority, repeat the retired/current probes, and query original and changed publication intents. Changed retired probes deliberately use the current token; old epoch identity must still prevent admission.

## Evidence and decision rules

Retain exact commands, numbered raw and decoded streams, live resume bindings, stderr, exit status, ordered parent actions, coherent boundary snapshots, decisions, grants, result rows and retirement witnesses. Record the maximum observed result-row count, boundary observations exceeding two rows, retired rows, decisions/grants committed under a retired epoch, rebound logical IDs, actual retired-probe denominators/correctness, probe state changes, capacity behavior, same/changed current-result correctness, busy callers, marked/normal exits, target closure and publication-history preservation.

An independent stdlib verifier imports neither the runner nor any mechanism. It reconstructs epoch checks, writer ownership, transactional retirement/deletion, request decisions/results, rollback, capacity and replies from the frozen histories; independently recounts outcomes; and checks raw/source/manifest hashes, freeze identity and unchanged inherited sources. Consistently recorded wrong replies remain outcome failures. Live wire integers must reject JSON booleans.

The atomic arm requires no retired decisions/grants, rebound IDs, stale results or result-bound violations; all retired probes rejected without state mutation; correct current replay/conflict and capacity behavior; no caller/infrastructure/transport failures; and preserved migration/publication authority. Weak-arm failures remain visible. Completion is reported separately from safety. The row bound is exact for these controlled histories, while the transaction structure explains its invariant under the specified API; this is not an arbitrary-history proof.

## Exclusions

One fixed migration target, one reusable authority slot, two retained results per recovery epoch, trusted administrative calls, controller-granted writer order and application-boundary process exits. No authentication, many-caller fairness, adversarial epoch advancement, host/storage/power failure, durable client delivery, storage-byte reclamation, full-database size bound or lifetime-work bound is established. Retired results are intentionally unavailable; their removal does not establish any right to re-evaluate their old request identities.
