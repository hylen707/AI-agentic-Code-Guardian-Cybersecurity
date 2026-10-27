# Phase 5 protocol: authorization across pathname replacement

**Status:** prospective protocol; freeze this file and the task manifest in Git before implementing or running the new executor. Earlier protocols and evidence remain unchanged.

## Question and competing explanations

Does checking a file's identity before opening its pathname prevent protected content operations when that pathname changes after authorization? Does authorizing an already-open descriptor and using that same descriptor preserve the authorized object?

The mechanism hypothesis is that the time between a pathname check and a later open permits substitution. The competing explanation is that apparent protection comes from refusing all work. Ordinary controls and benign replacements distinguish object binding from blanket refusal.

## Intervention and schedule

Compare three arms on a fresh synthetic Linux fixture for every case:

1. `baseline`: open the pathname and perform the operation without a policy gate.
2. `identity_path`: use the unchanged Phase 4 `IdentityAwareGate`, then open the approved pathname.
3. `descriptor_bound`: open an existing regular file without truncation or creation, inspect its descriptor identity against configured protected identities, then perform content I/O through that same descriptor. Denial closes the descriptor without reading, writing, or truncating.

The trusted fixture controller introduces one deterministic replacement at the specified boundary. `before_check` means after preparation but before identity checking/opening. `after_check` means after the arm's authorization point but before content I/O; the pathname arms have not opened the file, while the descriptor arm has. The baseline uses the same boundary without a decision. These schedules model an adversarial interleaving; they do not measure concurrent win probability.

Ten cases pair `read` and `write` with five conditions:

| Condition | Timing | Replacement | Cases |
|---|---|---|---:|
| Ordinary control | none | none | 2 |
| Protected leaf alias | before_check | hardlink to protected file | 2 |
| Protected leaf alias | after_check | hardlink to protected file | 2 |
| Protected parent alias | after_check | rename ordinary directory; install symlink to protected directory | 2 |
| Benign leaf replacement | after_check | different ordinary file | 2 |

The controller operates only inside a newly created temporary root. All strings and files are synthetic. No arbitrary user-supplied paths, shell commands, network requests, or live agents are involved in the experiment. Setup or capability failures must fail explicitly, without skipping cases.

## Oracle and denominators

The oracle retains a hardlink witness to the initial ordinary file and records protected identity from a separately held descriptor. It observes the descriptor actually used for content I/O and the resulting witness/protected bytes. It does not infer success from a gate's decision or a pre-open path label.

- **Protected content operations / attack schedules:** successful reads or writes through a descriptor matching the protected identity, out of six protected-substitution cases per arm. Record attempted protected content I/O separately, including failures.
- **Original-object completion / eligible cases:** eight cases where the original ordinary object is available at the authorization point (controls plus all after-check replacements). A read must return the original bytes through that identity; a write must change the retained original object to the specified bytes through that identity. Before-check substitutions are excluded prospectively: the original object has already been displaced before either gate can authorize it.
- **Benign blocks / benign cases:** gate denials among the four ordinary-control and benign-replacement cases.
- **Protected opens:** successful opens of protected identity, including descriptors denied before content I/O. Zero protected content operations must never be presented as zero protected opens.
- **Infrastructure errors:** setup, open, metadata, content-I/O, and oracle failures; none count as successful gate blocks. Preserve every failed run.

These denominators overlap: after-check attacks also test original-object continuity. Do not add them as independent observations or call original-object completion live-agent task completion.

## Prespecified expectations and falsification

Expect baseline and identity-path arms to perform protected content I/O in all four after-check attack cases; expect the identity-path arm to block both before-check hardlink substitutions. Expect the descriptor arm to have zero protected content operations, two protected opens denied before I/O, eight original-object completions, and zero benign blocks. Any deviation must be retained and analyzed. Expected values are hypotheses, not measured outcomes.

Save one raw JSONL record per case/arm, a summary derived from those records, source and task SHA-256 hashes, Python/platform information, base/freeze commits, commands, and test output. Require exactly one record for every declared case in each arm. Exit nonzero for infrastructure failure; record scientific criteria independently. Do not tune the manifest after observing results.

## Assumptions and limits

Only existing regular-file reads and writes are in scope. The trusted controller changes names, not bytes in the pinned original inode. Protected membership is static and captured before intervention. The trusted executor owns descriptor lifetime and does not reopen the path after authorization. There is no descriptor tampering, inode reuse while witnesses remain alive, dynamic policy update, malicious special file, creation, deletion, mount change, general path confinement, latency benchmark, or live-agent evaluation. Opening for metadata authorization is itself an OS access; this design does not enforce a no-open policy. A writable open has no `O_TRUNC`; truncation occurs only after approval. Concurrent writes to the same inode could still change its contents.

## Technical basis

- MITRE, [CWE-367](https://cwe.mitre.org/data/definitions/367.html): names the check/use state-change weakness.
- Linux man-pages, [open(2)](https://man7.org/linux/man-pages/man2/open.2.html): an open descriptor retains its object reference after pathname replacement.
- Linux man-pages, [stat(2)](https://man7.org/linux/man-pages/man2/stat.2.html): `fstat` obtains metadata for a descriptor.
- Python documentation, [os interfaces](https://docs.python.org/3/library/os.html): implementation interfaces for descriptor operations.

Sources consulted 2026-10-26. These mechanisms are established systems concepts; the contribution here is a reproducible comparison and a bounded claim, not a new security primitive.
