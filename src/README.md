# Source guide

The source directory contains resource-authorization mechanisms and a version-specific content reader. Earlier implementations remain unchanged so their measured outcomes can be reproduced.

| Module | What it authorizes | How to evaluate it |
|---|---|---|
| `codeguardian.py` | Operation and path spelling | Policy datasets and paired replay |
| `executor_gate.py` | Prepared resolved pathname and content | Three-arm fixed-topology comparison |
| `identity_gate.py` | Prepared path plus current file identity | Hardlink comparison and replacement study |
| `descriptor_executor.py` | Held regular-file descriptor for read/write | Deterministic replacement comparison |
| `verified_content_reader.py` | Captured UTF-8 value matching a trusted version digest | Same-inode content mutation comparison |

The first three return a policy decision. The descriptor executor owns open, authorization, content I/O, and close to preserve the binding it checks. It opens without truncation, checks `fstat`, and uses the same descriptor after approval. It can open a protected object for metadata inspection before denying content I/O; it does not enforce a no-open policy.

The content reader composes that executor without changing it. It captures once, validates the captured value against an owner-configured digest, and returns that same value. A failed check returns no payload, although inspection reads have already occurred. A successful value may be stale relative to the live file. Actions cannot select their own approved digest.

## Local validation

From the repository root:

```bash
python -m unittest discover -s tests -v
```

To classify an action without executing it:

```bash
echo '{"operation":"read","path":"workspace/notes.txt"}' | python src/codeguardian.py
```

Use the [experiment guide](../experiments/README.md) for measured comparisons. The current code uses the Python standard library; the descriptor study is evaluated on Linux with hardlinks and symlinks. These modules assume trusted fixture preparation and are not a general sandbox or a live-agent integration. See the [architecture](../docs/ARCHITECTURE.md) for trust boundaries and the [research statement](../docs/RESEARCH_STATEMENT.md) for the argument.

## Revision-aware receipt

`revision_authority.py` adds one-resource approval snapshots, monotonic updates/revocation, separate checking, and coordinated release to a trusted in-process sink. It composes the existing captured-value reader in the experiment harness; it does not change earlier implementations. Busy publications require caller retries. See [Phase 7 findings](../docs/REVISION_FINDINGS.md).

## Persistent publication stores

`publication_store.py` contains split-file and single-row SQLite stores for the Phase 8 fixture experiment. Individual split replacements use file and directory fsync; the SQLite store verifies rollback-journal `DELETE` mode and `synchronous=FULL`. Both capture a recovered state before delivery, and the verified interface returns exactly the captured bytes checked. A diagnostic unchecked arm omits that digest check.

The worker terminates at declared boundaries without normal cleanup. These stores are independent from the earlier execution gate; they do not provide general filesystem confinement, distributed publication, or power-loss validation. See the [recovery findings](../docs/RECOVERY_FINDINGS.md).
