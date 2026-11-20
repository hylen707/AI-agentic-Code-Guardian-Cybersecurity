# Phase 20 protocol: interrupted recovery requests need their own durable result

**Prospective status:** freeze this protocol and manifest before implementing the request store, worker, controller or verifier. No Phase 20 result is asserted here.

## Question and contract

Phase 19 fences stale authority, but its parent recovery calls always return. If replacement commits and its caller loses the reply, can a retry recover that particular request's outcome after another replacement or target closure?

A recovery request is an exact `(request_id, expected_token, owner)` tuple. The first durable non-busy decision binds its ID to those inputs and to its outcome, including conflict or already-completed outcomes. A same-intent retry must return that historical outcome without another grant or reactivating old authority. Reusing an ID with different inputs must return `request_conflict`, even after target closure. Busy before any durable decision does not claim the ID. Historical lease fields describe the old outcome, never current authority.

Authority remains Phase 19's one reusable slot with monotonic tokens and append-only grants. This is not Phase 18's lifetime attempt/work budget, authentication, a secret capability or automatic failure detection. All migration effects use unchanged transactional fencing.

## Arms

| Arm | Request/result treatment |
|---|---|
| `current_only` | Re-runs token CAS against current state and returns the fresh observation; no request receipt is consulted. |
| `separate_receipt` | Reads any receipt before CAS, commits the decision/grant, and records the keyed result in a second transaction. A collision resolves the existing receipt rather than repeating a write. |
| `atomic_receipt` | Looks up the exact ID/intent inside the write transaction, then couples a first decision, any grant and its immutable result in that transaction. Lookup precedes target-completed handling. |

Every non-busy CAS decision has an observer witness committed with it in all arms. That witness includes request ID, exact inputs, outcome and any granted token. It is oracle evidence only, never an application admission or reply source. The first witness per ID defines the original decision; extra witnesses cannot redefine it. A receipt can therefore disagree with an actual earlier grant, even if its inputs match.

Record wrapper statuses `observed` (current-only), `recorded` (new receipt), `replayed` (matching receipt), `request_conflict` (ID bound to other inputs), or `busy`. Outcomes are typed `reclaimed`, `conflict` or `completed` objects. Report a missing original outcome separately from a receipt that falsely presents a later decision as history.

## Frozen histories: 24 cases per arm

Twelve histories cross two fixture patterns, producing **24 cases per arm, 72 case/arm records**. Patterns vary request-key encoding and existing publication value types: ASCII keys with a revoked seed, and Unicode keys with an empty update. Both retain a Unicode update receipt. These patterns are controls, not a claim that key encoding causes an outcome difference.

| History | Ordering |
|---|---|
| `quiet_retry` | One request commits, then the same request is retried. |
| `exit_before_decision` | Caller exits before its decision transaction commits; a fresh caller retries. |
| `exit_after_decision` | Decision/grant commits, caller exits before the next stage or reply; a fresh caller retries. |
| `exit_before_reply` | All application storage work completes, then the caller exits before replying. |
| `later_replacement_after_loss` | Original decision commits and reply is lost; a different ID grants the next token; original ID retries. |
| `target_closes_after_loss` | Original decision commits and reply is lost; migration closes the target; original ID retries. |
| `overlap_lookup_same` | A pauses after lookup; B attempts the same intent; A continues; B's intent retries. |
| `overlap_lookup_changed` | Same gap, but B reuses the ID with a different owner. |
| `receipt_gap_same` | A pauses after decision commit; B attempts the same intent; A continues. |
| `receipt_gap_changed` | In that gap, B reuses the ID with the next expected token and a different owner. |
| `first_conflict_then_applicable` | Original ID records a conflict; another ID advances authority; original inputs would now apply if re-evaluated. |
| `owner_reuse_after_loss` | Original result is followed by a different-ID transfer back to owner label 1; original ID retries. |

The manifest fixes exact request tuples, process generations, pause stages, continuation and code-73 exit actions. A live pause binds generation, request ID, expected token, owner, role and stage, with exact JSON types. Atomic lookup holds the writer while separate lookup does not; a blocked competitor is recorded as busy and is not treated as a completed decision. Exits occur at application boundaries, not inside SQLite operations. Parent and OS survive.

After original callers settle, the controller queries each actual original request and a changed typed intent, closes any still-open target using current authority, then repeats those queries after closure. It also queries all original publication receipts and changed publication intents. A historical outcome is never installed as current authority. Parent queries may append observer decisions in weak arms; authority/publication-state inertness is measured separately from observer or receipt writes. Canonical originals come from actual first committed witnesses, not intended-request labels.

## Evidence, measures and decisions

Use fresh disposable SQLite fixtures on Linux/Python 3.11+. Retain parent action order, exact child commands, raw and decoded numbered streams, live bindings, stderr/exit codes, and coherent snapshots at each boundary. Preserve witnesses, request receipts, grants, current authority, target state and historical publication authority. Failed infrastructure records remain in the complete 72-record grid.

An independent stdlib verifier, importing no mechanism or runner, reconstructs writer ownership, receipt lookup, decision/grant commit, separate receipt commit/collision, rollback and replies. It derives original intent/outcome from the first committed decision witness. It must reject changed order, inputs, wire types, exits, grants, receipts and source identities. A consistently recorded wrong answer must still fail its outcome criterion.

Report per arm: correct original query answers with actual denominators; unavailable current-only originals; falsely recorded/replayed history; changed-intent response failures; grants not justified by the first decision for that ID; authority changes during history queries; lifetime grants; deferred writers; normal/marked process exits; final closure; publication replay/conflict correctness; and infrastructure/caller errors. Safe token CAS is not equivalent to request/result continuity. Migration closure, current authority and historical outcomes remain separate.

The atomic arm's bounded claim requires no unjustified grants, historical-answer failures, changed-ID failures, history-query authority mutations, publication history loss, caller errors or infrastructure failures. Weak-arm failures remain visible. Completion is reported, not pooled into a security rate. Before completion, run the full unit suite and frozen grid; independently verify raw/source/manifest hashes, frozen Git identity and unchanged inherited mechanisms.

## Exclusions

There is one reusable authority slot and one fixed target, at most two overlapping request processes, retained receipts and trusted recovery/source publishers. Writer ordering is controller-granted. No receipt retirement, result garbage collection, automatic retry policy, request authentication, arbitrary many-caller history, fairness, host/storage fault or lifetime-work bound is established.
