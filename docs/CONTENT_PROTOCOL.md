# Phase 6 protocol: approved content on a stable file identity

**Status:** prospective protocol. Commit this document and the case manifest before implementing or executing the comparison. Earlier protocols, code, and results remain unchanged.

## Question and contract

Does retaining the correct file identity ensure that a consumer receives the content version approved by a trusted policy? If a content digest is checked, must the exact checked payload also be retained?

The new contract is deliberately stricter than Phase 5: a successful read may deliver only UTF-8 bytes matching a trusted, preconfigured SHA-256 digest for that target. The proposed action cannot supply or modify that digest. This is a version-specific delivery rule, not a judgment that changed content is malicious. The consumer is the runner's receipt of the returned payload; no model consumes it.

The hypothesis is that identity continuity alone cannot satisfy this contract, and that hashing then rereading the same descriptor leaves a content check/use gap. Capturing, validating, and delivering one immutable in-memory value should remove that reread gap under the stated assumptions. It may return an approved but outdated value.

## Arms and intervention

Each case runs on three fresh synthetic fixtures:

1. `identity_only`: the unchanged Phase 5 `DescriptorExecutor` reads the authorized ordinary file. It has no version-specific content rule.
2. `hash_then_reread`: a diagnostic comparator checks a SHA-256 digest with `pread` on the authorized descriptor, discards the inspected bytes, and lets the unchanged executor read that same descriptor for delivery. A mismatch denies delivery. `pread` leaves the descriptor offset unchanged.
3. `verified_buffer`: a reader uses the unchanged executor to capture UTF-8 content once, hashes that captured value, denies a mismatch, and returns that same immutable string after validation. There is no second filesystem read for delivery.

All arms retain Phase 5 resource authorization. The controller changes bytes of the existing ordinary inode through a separate hardlink. It never renames or replaces files. The oracle holds an additional descriptor to check that the device/inode identity stays constant and to inspect final bytes.

`before_capture` changes content after identity authorization but before inspection or delivery reads. `after_validation` changes content after a passing digest check but before payload release. In `identity_only`, the corresponding unvalidated checkpoint occurs before its read. In `hash_then_reread`, the checkpoint precedes its second read. In `verified_buffer`, the checkpoint follows capture and validation but precedes returning the captured value. This ordering is the intervention, not a random timing model.

## Frozen cases

Eight cases are declared in `experiments/tasks/content-eval-v1/tasks.json`:

| Condition | Fixture | Timing | Cases |
|---|---|---|---:|
| Unchanged text | ASCII, Unicode, empty | none | 3 |
| Same-length overwrite | ASCII | before_capture | 1 |
| Truncation | ASCII | before_capture | 1 |
| Same-length overwrite | ASCII | after_validation | 1 |
| Truncation | ASCII | after_validation | 1 |
| Append | ASCII | after_validation | 1 |

The approved ASCII bytes are `approved=true\n`; the same-length replacement is `approved=oops\n`; truncation keeps the first five bytes; append adds `late update\n`. The Unicode fixture is `approved=안전 ✓\n`; the empty fixture is zero bytes. Digests are derived from these approved fixture bytes during trusted setup, before intervention. They are not selected from observed outcomes.

## Measures and prespecified expectations

Report all eight cases per arm; do not exclude changed-before-capture cases from completion counts.

- **Unapproved deliveries / mutation cases:** successfully returned payloads whose exact UTF-8 bytes differ from the approved bytes, out of five mutation schedules. Expect 5/5, 3/5, and 0/5 for identity-only, hash/reread, and verified-buffer arms respectively.
- **Approved-version deliveries / all cases:** returned bytes exactly equal the approved bytes, out of eight. Expect 3/8, 3/8, and 6/8.
- **All deliveries / all cases:** expect 8/8, 6/8, and 6/8. Both digest arms should deny the two mutations that precede capture.
- **Unchanged controls delivered correctly / controls:** expect 3/3 for every arm, including an empty payload as a successful delivery.
- **Approved but stale deliveries:** payload equals approved bytes but differs from final live-file bytes. Expect zero, zero, and three. The verified-buffer result must not be presented as a freshness guarantee.
- **Content inspection:** record inspection hashes and lengths, including rejected samples. Denying a payload does not undo reads already performed inside the executor. This is not a no-read policy.
- **Identity continuity and errors:** all cases must retain the original inode. Report setup, metadata, read, decode, hook, and oracle failures separately from policy denials; errors cannot count as successful protection.

These expectations are hypotheses. Preserve disagreements and failed runs before any follow-up change. The identity-only arm is a comparator under a new contract, not evidence that Phase 5 failed its original resource-identity claim. Results are not protected-resource access counts and cannot be pooled with Phase 5's 0/6.

## Evidence and analysis

Record one JSONL row per case/arm: schedule, event order, observed identities, approved/inspected/delivered/final byte hashes and lengths, status, reason, and oracle outcomes. Preserve the trusted configuration hash, source/task hashes, environment, commands, base/freeze revisions, test output, and a summary derived from every declared row. Require exactly one row per declared case/arm and fail explicitly on duplicates or missing rows.

The oracle compares returned bytes directly with the predefined approved and final bytes rather than trusting the policy's digest decision. Record both byte-equality outcomes and hashes. Recompute summary outcomes from raw artifacts as an additional consistency check. This is not an independent replication or another empirical sample.

## Scope and limitations

This is a deterministic mechanism study on Linux, with trusted fixture construction and small existing regular UTF-8 files. It uses static approved digests, static protected membership, and trusted executor memory and hooks. There is no live agent, arbitrary user path, shell command, network action, thread race, content change during the capture itself, write authorization, policy update, or newly created target.

The buffer is not an atomic filesystem snapshot; it is an immutable value captured by the process. A future change during capture could produce mixed bytes, and a digest check would accept only a matching approved value under the hash assumption. Collision resistance, digest authenticity/distribution, large-file limits, streaming release, and freshness are not established here. No unvalidated prefix may be released by the implemented reader. The whole captured value is checked before return.

## Technical basis

- Linux man-pages, [open(2)](https://man7.org/linux/man-pages/man2/open.2.html): descriptor continuity concerns the open object, not an immutable content version.
- Linux man-pages, [pread(2)](https://man7.org/linux/man-pages/man2/pread.2.html): reading at a specified offset does not advance the descriptor's current offset.
- Python documentation, [hashlib](https://docs.python.org/3/library/hashlib.html): SHA-256 operates on supplied bytes and provides a digest for comparison.

Sources consulted 2026-10-27 (Asia/Seoul). Content hashing and buffered validation are established techniques. The contribution is an explicit counterexample, comparison, and account of the trade-off between an approved version and current content.
