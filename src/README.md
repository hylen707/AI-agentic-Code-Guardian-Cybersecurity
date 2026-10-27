# Source guide

The source directory contains four successive authorization mechanisms. Earlier implementations remain unchanged so their measured failures can be reproduced.

| Module | What it authorizes | How to evaluate it |
|---|---|---|
| `codeguardian.py` | Operation and path spelling | Policy datasets and paired replay |
| `executor_gate.py` | Prepared resolved pathname and content | Three-arm fixed-topology comparison |
| `identity_gate.py` | Prepared path plus current file identity | Hardlink comparison and replacement study |
| `descriptor_executor.py` | Held regular-file descriptor for read/write | Deterministic replacement comparison |

The first three return a policy decision. The descriptor executor owns open, authorization, content I/O, and close to preserve the binding it checks. It opens without truncation, checks `fstat`, and uses the same descriptor after approval. It can open a protected object for metadata inspection before denying content I/O; it does not enforce a no-open policy.

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
