# Phase 20 findings: a recovery result belongs to its original request

## Claim and scope

**Safe token CAS does not by itself preserve a recovery request's result. A separately written receipt can even certify the wrong historical decision.** Across twenty-four cases per arm, original-query correctness is **0/60 → 36/60 → 60/60** for current-state re-evaluation, a separate receipt transaction, and an atomic decision/result transaction. Grants not justified by the ID's first decision are **4 → 2 → 0**. All arms still close every target and preserve the original publication receipts.

This extends Phase 19's reusable authority slot; it does not refund Phase 18's lifetime budget. Every migration uses the unchanged transactional fence. The new question concerns the identity and result of the replacement operation itself, after loss, overlap, later replacement or target closure.

The [protocol](REQUEST_PROTOCOL.md) and [24-case manifest](../experiments/tasks/request-eval-v1/tasks.json) were frozen at [`d2ffbb5de6d9bec79a2a70273510ee338c9e28b9`](https://github.com/hylen707/AI-agentic-Code-Guardian-Cybersecurity/commit/d2ffbb5de6d9bec79a2a70273510ee338c9e28b9) before implementation. All inherited mechanism bytes remain identical to base `28d841f5eac844a2389cc3ff513fedde962e45ce`.

## Request/result contract

Within one fixture's fixed job, an exact `(request_id, expected_token, owner)` identifies an intention. Its first durable non-busy decision binds those inputs and its outcome. An identical retry returns that outcome; a changed intention with the same ID returns `request_conflict`. Busy before any durable decision does not bind the ID. Conflicts and already-completed outcomes are retained too: an ID first recording a conflict is not made newly eligible when its expected token later becomes current. A fresh intention needs a fresh ID.

Returned lease fields are historical data, not current authority. A replay may correctly report the original owner 2/token 2 while current authority remains owner 3/token 3. The receipt is looked up before target-completed handling, so later closure cannot replace that historical answer with a generic completion result.

Every arm has an observer witness for each committed CAS decision. The first witness per ID is the oracle's original decision. Witnesses never authorize requests or supply application replies. Thus a current-only failure means the API did not return the original result; it does not claim that no diagnostic evidence of that result exists anywhere in SQLite.

## Design and evidence units

Twelve histories cross two fixture patterns: ASCII versus Unicode recovery IDs, with revoked versus empty-update publication values. These are controls rather than a causal comparison of key encoding. **Twenty-four cases per arm produce 72 case/arm records.** The histories include exits before and after a decision commit, a lost reply, overlapping same/changed intentions, separate-receipt gaps, a first conflict becoming applicable, later authority changes and closure.

Generation/request/expected-token/owner/checkpoint bindings use exact JSON types. A marked application exit flushes its event and exits with code 73; the OS and parent survive. The standalone stdlib model reconstructs writer ownership, receipt lookup, tentative decisions/grants, commit/rollback, receipt collision resolution and every reply without importing mechanism or runner code.

Each arm has thirty actual original recovery-request instances across its fresh fixtures. Each is queried before and after closure: **60 original-result probes and 60 changed-intent probes per arm**. The parent then queries 48 actual original publication intents and 48 changed publication intents. These denominators are separate from live caller replies and grant effects.

## Results

| Measure | Current only | Separate receipt | Atomic receipt |
|---|---:|---:|---:|
| Case/arm records | 24 | 24 | 24 |
| Correct original-result probes | 0/60 | 36/60 | 60/60 |
| Correct changed-intent rejections | 0/60 | 60/60 | 60/60 |
| Grants not justified by the ID's first decision | 4 | 2 | 0 |
| Recorded/replayed answers contradicting original history | 0 | 32 | 0 |
| Unresolved same-intent answers | 82 | 6 | 0 |
| Responses failing the changed-ID contract | 64 | 2 | 0 |
| Retained request receipt rows | 0 | 30 | 30 |
| Lifetime grants, including twenty-four initial grants | 56 | 54 | 52 |
| Writer-busy replies | 0 | 0 | 4 |
| Authority changes during original/changed probes | 0 | 0 | 0 |
| Final migration completion | 24/24 | 24/24 | 24/24 |
| Publication originals replayed | 48/48 | 48/48 | 48/48 |
| Changed publication conflicts | 48/48 | 48/48 | 48/48 |
| Caller/transport/infrastructure errors | 0 | 0 | 0 |

Historical and changed-ID response counters span live callers and probes; they are counts, not percentages with the case denominator. A current-only reply can truthfully describe a fresh CAS observation while failing to answer the original request. That is counted as unresolved history, not falsely claimed recorded history. Execution conformance does not make a weak arm's historical answer correct.

Each arm records **58 child processes: twelve marked exits and forty-six normal completions**, with twenty live barriers. Across the study this is **174 child processes, 36 marked exits and 60 bound barriers**, plus 360 sequential parent recovery probes. The atomic arm's four busy replies occur when its in-transaction lookup holds the writer against an overlapping competitor. Those attempts do not claim an ID or decision. No count is pooled with earlier stages or interpreted as a race probability.

## Counterexamples and intervention

**A grant can survive while its separate receipt does not.** After the original decision commits and the caller exits, an exact retry in the separate arm sees no receipt, re-evaluates the old expected token and records a conflict. The first decision was a grant. A later replacement or closure changes that fresh observation further; neither observation supplies the original grant result. The atomic arm retains the original receipt through the same application exit.

**A same-intent competitor can record the wrong result first.** In `receipt_gap_same`, A grants token 2 and pauses before its separate receipt. B's identical request observes the advanced token and records a conflict. A then resolves that existing receipt and returns the conflict too. There is only one grant, but the result is still wrong. Thirty retained receipt rows in each keyed arm therefore conceal different historical validity.

**Changed inputs can obtain a second grant under one ID.** In `receipt_gap_changed`, A grants under an ID whose receipt is not yet bound. B reuses that ID with expected token 2 and another owner. The separate and current-only arms grant again. The atomic arm already binds the ID with the first grant and rejects B before another CAS. Current-only re-evaluation also allows an ID's original conflict to become a grant after another request advances authority; the retained-conflict contract prevents that change in the keyed arms.

**Lookup belongs before closure, and historical replies do not restore authority.** A correct replay returns the original grant even after the target is closed or another request has transferred authority. The atomic arm returns 60/60 original results without changing current authority during the probes. Its historical token is never installed as current; migration uses the then-current token. Publication history remains correct even in weak recovery-request cases.

## Verification and reproduction

The retained run uses Linux x86-64/Python 3.12.14. **517 tests passed**, including 31 new regressions. They cover immutable capture of request inputs, exact wire types, Unicode IDs, changed intentions, conflict retention, lookup before closure, rollback and lost replies, observer-independent replay, live binding failures, receipt/decision/grant mutations, raw streams, provenance and historical answers. Parent event records are copied when emitted so a returned mutable object cannot rewrite an earlier observation. Consistently recorded wrong answers still fail the relevant outcome criteria.

```bash
python -m unittest discover -s tests -v
python experiments/run_request_comparison.py \
  --output /tmp/codeguardian-request-v1.jsonl \
  --base-commit 28d841f5eac844a2389cc3ff513fedde962e45ce \
  --freeze-commit d2ffbb5de6d9bec79a2a70273510ee338c9e28b9
python experiments/verify_request_results.py /tmp/codeguardian-request-v1.metadata.json
```

- [Raw histories](../experiments/results/2026-11-20-request-v1.jsonl)
- [Frozen/base/source/raw identities and controller counts](../experiments/results/2026-11-20-request-v1.metadata.json)
- [Independent reconstruction and five criteria](../experiments/results/2026-11-20-request-v1-verification.json)
- [Full test output](../experiments/results/2026-11-20-request-v1-tests.txt) and [execution environment](../experiments/results/2026-11-20-request-v1-execution.json)
- [Store](../src/recovery_requests/store.py), [worker](../experiments/request_worker.py), [controller](../experiments/run_request_comparison.py), [independent verifier](../experiments/verify_request_results.py), [tests](../tests/test_requests.py)

The verifier requires the freeze's parent to equal the mechanism base, compares frozen files with their Git objects, checks inherited source identity and current source/raw hashes, and independently reconstructs every count. Infrastructure failures keep their place in the 72-record grid. Earlier Phase 19 and Phase 18 evidence still verify unchanged.

## Limits and next boundary

The request contract is evaluated at `replace_once` in a trusted fixed-job fixture. It is not authentication or a server boundary around every inherited administrative helper. Receipts are retained, recovery IDs are job-local, and only two request processes overlap at a time. Cuts are outside storage operations with parent/OS survival and controller-granted writer order. The reference model and mutation tests cover selected histories, not a proof over arbitrary concurrent schedules, host power loss or shared conceptual mistakes.

Authority/publication-state inertness excludes diagnostic witness and recovery-receipt writes; those writes remain visible in the raw snapshots. Reusable authority is still distinct from a lifetime-work limit. The next boundary is bounded recovery-result retention: deleting a receipt must not make its old ID a fresh intention that can obtain another grant.
