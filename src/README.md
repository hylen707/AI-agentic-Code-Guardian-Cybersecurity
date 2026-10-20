# Source code

The first policy checker is in `codeguardian.py`.

## What it does
- Accepts a synthetic action record with `operation` and `path`.
- Applies a deterministic allowlist.
- Blocks unknown operations, absolute paths, traversal patterns, paths outside the allowlist, and protected paths.
- Returns a decision and reason.
- Does not read, write, or execute the proposed target action.

## Run locally
From the repository root:

```bash
python -m unittest discover -s tests -v
```

To classify sample JSON-lines input without executing any action:

```bash
echo '{"operation":"read","path":"workspace/notes.txt"}' | python src/codeguardian.py
```

## Important limitation
This is a first-step policy checker for synthetic records, not a secure sandbox and not yet connected to an AI coding agent. Path decisions are string-based and do not resolve filesystem symlinks because this version never accesses the filesystem. Do not use it as a security boundary for real systems.
