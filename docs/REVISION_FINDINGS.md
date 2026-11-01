# Phase 7 findings: approval must survive until receipt

**Study:** nine deterministic cases, three arms, 27 case/arm records. Measured 2026-11-01 (Asia/Seoul).

## Question and result

Phase 6 validates a captured value under a static approved digest. This study asks what happens when a trusted publisher subsequently changes or revokes that approval. The contract now requires both the bytes and the approval revision to be current when a trusted in-process consumer records receipt.

| Outcome | Snapshot only | Recheck then release | Coordinated release |
|---|---:|---:|---:|
| Invalid receipts / five post-capture transitions | 5/5 | 2/5 | 0/5 |
| Valid receipts / all cases | 3/9 | 3/9 | 5/9 |
| All receipts / all cases | 8/9 | 5/9 | 5/9 |
| Denials / all cases | 1/9 | 4/9 | 4/9 |
| Unchanged control receipts | 2/2 | 2/2 | 2/2 |
| Early approved update received | 1/1 | 1/1 | 1/1 |
| Deferred publication attempts | 0 | 0 | 2 |
| Requested publications eventually committed | 8/8 | 8/8 | 8/8 |
| Valid at receipt, obsolete at final observation | 0 | 0 | 2 |
| Infrastructure errors | 0 | 0 | 0 |

All cases retain file identity. The five transition cases overlap other rows; counts must not be pooled. Denied cases remain in the nine-case valid-receipt denominator. The snapshot comparator never implemented this new dynamic contract; its failures do not invalidate Phase 6's static-digest result.

## Mechanism and counterexample

A snapshot-only release accepts a value after an intervening update or revocation. A separate final check rejects three transitions before that check, but permits two changes in the gap between checking and receipt. Coordinated release holds the same lock used for publication while it checks the candidate and appends the receipt. The two scheduled publication attempts cannot commit inside that interval and are retried immediately afterward.

That ordering changes the meaning of the result. The candidate is current at receipt because the update or revocation is still pending, not because it has been ignored or reversed. All requested publications eventually commit, and two previously valid receipts are obsolete at final observation. A longer consumer operation would delay publication longer; latency, fairness, and starvation were not measured.

The A-to-B-to-A case returns to identical bytes at revision 3. The revision-1 candidate is rejected under the selected revision-specific rule. A content-equality-only contract would accept those bytes. This case demonstrates the chosen semantics rather than an intrinsic danger in identical content.

## Oracle and validation

Each raw journal records the initial approval, committed publications, capture, scheduling boundaries, and consumer receipt. Receipt validity compares direct bytes and revision against the last preceding committed approval. A final-file comparison alone cannot establish receipt-time validity. The receiver and journal remain trusted instrumentation.

All **85 tests passed**, including 18 revision tests covering revocation, ABA, payload mismatch, lock exclusion from another thread, callback failures, retained partial receipt effects, malformed manifests, and forged stored assessments. A separate artifact recount reconstructed receipt validity from saved journals and matched all summary counts. All nine declared criteria held; no infrastructure errors occurred. These regression tests are not additional adversarial samples.

## Evidence and reproduction

The [analysis plan](REVISION_PROTOCOL.md) and [nine-case manifest](../experiments/tasks/revision-eval-v1/tasks.json) were frozen before the recorded measurement at [`85c6e23`](https://github.com/hylen707/AI-agentic-Code-Guardian-Cybersecurity/commit/85c6e23898da60b39dc7450da0f4b9a721ac7374). Implementation drafts already existed and were reviewed with the protocol. This is a pre-measurement analysis freeze, not a pre-implementation freeze or blind evaluation.

- [Raw journals](../experiments/results/2026-11-01T13-54-33-678609Z-revision-v1.jsonl)
- [Summary, source/task hashes, environment, and command](../experiments/results/2026-11-01T13-54-33-678609Z-revision-v1-summary.json)
- [Test transcript](../experiments/results/2026-11-01T13-54-33-678609Z-revision-v1-unit-tests.txt)
- [Artifact verification](../experiments/results/2026-11-01T13-54-33-678609Z-revision-v1-verification.json)

```bash
python -m unittest discover -s tests -v
python experiments/run_revision_comparison.py --dataset experiments/tasks/revision-eval-v1/tasks.json --base-commit "$(git rev-parse HEAD)" --freeze-commit 85c6e23898da60b39dc7450da0f4b9a721ac7374
```

## Limits and next question

The authority coordinates one resource and a short trusted in-memory sink. All publishers cooperate with its non-reentrant lock. Pending requests do not have immediate effect. The result does not cover uncooperative writers, distributed coordination, crash recovery, atomic file/approval transactions, policy authentication, or subsequent use of a delivered value. Publication or observer failures propagate; a callback exception does not promise rollback of an already committed revision or recorded receipt.

The next study should test failure between writing bytes, committing approval, and recording publication, with explicit recovery semantics. Resource limits and publication delay also need their own measurements before extending the receipt-time claim.
