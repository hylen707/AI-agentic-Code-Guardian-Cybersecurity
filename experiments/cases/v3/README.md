# Synthetic dataset v3

## Design recorded before the first v3 run

This dataset freezes 45 expected decisions against the existing string policy.
It copies all 21 v2 cases, changing only their `dataset_version` to `v3`, and
adds 24 cases. The v1 and v2 files remain unchanged. No monitor or runner code
was changed to prepare v3.

| Class | Inherited | Added | Total | Expected decision |
|---|---:|---:|---:|---|
| legitimate | 8 | 8 | 16 | allow |
| risky | 9 | 10 | 19 | block |
| invalid_input | 4 | 6 | 10 | block |

Added cases cover:

- `SAFE-009`–`SAFE-016`: workspace-root equality, trailing and repeated
  separators, surrounding path whitespace, a sibling of the protected prefix,
  a dotfile, a Unicode filename, and mixed separators.
- `RISK-010`–`RISK-019`: protected-root equality, protected paths with trailing,
  repeated, or backslash separators, nested parent and dot components, an
  allowlist prefix collision, case-sensitive root matching, UNC spelling,
  and a drive-relative spelling.
- `INVALID-005`–`INVALID-010`: null or boolean operations, null or numeric paths,
  whitespace-only paths, and a null top-level action.

Labels were assigned from the documented policy before running the dataset,
not copied from observed decisions. Policy-rejected spellings are grouped as
`risky` for consistency with v1/v2; this label does not imply every such
spelling would be malicious on an actual filesystem. In particular, explicit
dot components are conservatively blocked even when they could resolve safely.

## Interpretation limits

The monitor normalizes strings only. The labels deliberately describe that
policy, including allowing the exact `workspace` root and treating path casing
as significant. They do not establish portable or safe filesystem behavior.
The checker does not resolve symlinks, model case-insensitive filesystems,
decode URLs, validate every operating-system filename constraint, or execute
an action. Extra action fields are currently ignored.

This hand-authored extension is not an independent holdout set. Dataset versions
overlap and must not be summed as independent observations. Raw malformed JSON
is not covered: each `input` is a valid JSON value serialized by the runner.
Results measure decision agreement, not task completion or reduction of risky
behavior by an AI agent. Before a real adapter, define filesystem semantics and
the trust boundary separately.

Run from the repository root:

```bash
python experiments/run_dataset.py --dataset experiments/cases/v3/actions.jsonl
```
