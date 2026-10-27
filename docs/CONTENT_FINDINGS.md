# Phase 6 findings: validate the value that will be delivered

**Study:** eight same-inode content cases, three arms, 24 records.

**Run:** 2026-10-27 (Asia/Seoul); artifact filenames use UTC.

## Finding

A file descriptor preserves an object's identity through name changes, but it does not preserve the object's bytes through a separate writer's updates. In this study, a passing content hash also fails to authorize a later reread: all three after-validation mutations produce a different returned value in that comparator. Returning the captured value that was actually validated avoids those unapproved deliveries, at the cost of returning an older approved value in the same three cases.

The contract is version-specific delivery from an ordinary file. These are not protected-file access counts, and the identity-only arm is not expected to enforce a content policy it never implemented.

| Outcome | Identity only | Hash, then reread | Verified buffer |
|---|---:|---:|---:|
| Unapproved deliveries / mutation cases | 5/5 | 3/5 | 0/5 |
| Approved-version deliveries / all cases | 3/8 | 3/8 | 6/8 |
| All deliveries / all cases | 8/8 | 6/8 | 6/8 |
| Content-version denials | 0 | 2 | 2 |
| Unchanged controls delivered correctly | 3/3 | 3/3 | 3/3 |
| Approved but stale deliveries | 0 | 0 | 3 |
| Cases retaining the original inode | 8/8 | 8/8 | 8/8 |
| Infrastructure errors | 0 | 0 | 0 |

All eight cases remain in the delivery denominator. The two before-capture changes are denied by both digest arms because the captured bytes no longer match the configured version. Zero unapproved deliveries therefore does not mean eight successful deliveries. Inspection of those rejected bytes still occurs inside the reader; this is a delivery rule, not a no-read rule.

## Mechanism and controls

| Condition | Identity only | Hash, then reread | Verified buffer |
|---|---|---|---|
| ASCII, Unicode, and empty controls | Approved payload | Approved payload | Approved payload |
| Overwrite or truncate before capture | Changed payload | Denied after inspection | Denied after inspection |
| Overwrite, truncate, or append after validation | Changed payload | Changed payload despite a passing earlier digest | Original approved payload; stale relative to the live file |

The controller writes through a hardlink to the ordinary file. No pathname replacement occurs, and the retained oracle descriptor confirms identity continuity in every row. The same-length overwrite keeps byte count constant, so a size check alone would not distinguish the versions. Truncation and append test shorter and longer values. Unicode and empty controls verify that successful delivery is based on a returned value rather than ASCII assumptions or truthiness.

The hash/reread comparator uses `pread` for inspection without moving the descriptor offset; the unchanged Phase 5 executor then reads that same descriptor. Its three failures isolate a content check/use gap without a new pathname lookup. The verified reader instead captures one UTF-8 string with the unchanged executor, validates its exact encoded bytes against a copied trusted digest configuration, and returns the same immutable string. The action cannot provide its own approved digest.

## Argument and boundary

Let `C(d, t)` be the bytes read from descriptor `d` at time `t`, and `h*` the trusted approved digest. A check of `H(C(d, t1)) = h*` does not constrain `C(d, t2)` after a writer changes the file. By contrast, the buffer implementation captures `b`, checks `H(b) = h*`, and returns `b`. Under the digest's collision-resistance assumption, a trustworthy digest, and trusted process memory, this binds the delivery to the checked version.

That argument does not establish `b = C(d, t_release)`. Three raw rows show the opposite: approved delivery and freshness can diverge. An application must choose whether it needs the approved version, the latest version, or a rule for reauthorization. The experiment does not resolve that product decision.

## Evidence and reproduction

The [protocol](CONTENT_PROTOCOL.md) and [manifest](../experiments/tasks/content-eval-v1/tasks.json) were frozen at [`ce3fd6d`](https://github.com/hylen707/AI-agentic-Code-Guardian-Cybersecurity/commit/ce3fd6d245a2013090f7bd8c6367d08895132723) before implementation. The cases remained visible during development; this is a prospective diagnostic study, not a blind holdout.

- [Raw case/arm records](../experiments/results/2026-10-27T12-21-15-144558Z-content-v1.jsonl)
- [Summary, source/task hashes, trusted configuration, and environment](../experiments/results/2026-10-27T12-21-15-144558Z-content-v1-summary.json)
- [Complete test transcript](../experiments/results/2026-10-27T12-21-15-144558Z-content-v1-unit-tests.txt)
- [Artifact consistency verification](../experiments/results/2026-10-27T12-21-15-144558Z-content-v1-verification.json)

```bash
python -m unittest discover -s tests -v
python experiments/run_content_comparison.py --dataset experiments/tasks/content-eval-v1/tasks.json --base-commit 4b47ab21db9808646cfc4a0dfd1be308896bf227 --freeze-commit ce3fd6d245a2013090f7bd8c6367d08895132723
```

All 67 tests passed, including 12 new tests for payload retention, mismatch denial without payload, Unicode/empty delivery, copied policy configuration, resource-gate composition, error propagation, descriptor cleanup, short inspection reads, and record integrity. The measured comparison exited 0; all nine prespecified summary criteria held. Errors remain distinct from policy denials.

## Validity and next question

This study uses synthetic small UTF-8 files, static trusted digests, and deterministic mutation points. It does not evaluate mutation during capture, concurrent attack probability, large-file resource limits, streaming release, digest provenance, dynamic policy updates, or live-agent behavior. The in-memory value is not an atomic filesystem snapshot. SHA-256 is used as an established comparison mechanism; its cryptographic properties are assumed, not experimentally established here.

The next useful study should define reauthorization when an approved version legitimately changes, including how a consumer handles an approved but stale value. A separate capture-time mutation experiment could test mixed-read rejection under a fixed version rule. Neither should be described as completed. Phase 5's resource-identity findings and its protected-open accounting remain unchanged.
