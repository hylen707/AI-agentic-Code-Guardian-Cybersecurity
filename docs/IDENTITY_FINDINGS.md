# Phase 4 findings: filesystem identity closes the hardlink gap

**Scope:** historical fixed-topology result. The subsequent [pathname-replacement study](RACE_FINDINGS.md) reproduces a check-to-open failure and compares descriptor binding. The 0/3 below remains specific to the original six-task suite.

Run date: 2026-10-26 (Asia/Seoul). This is a six-task, hardlink-focused
diagnostic suite on fixed synthetic fixtures. It is not a blind holdout,
production security evaluation, or live-agent result.

## Four-arm result

| Arm | Protected operations / proposals | Functional completion | Safe completion | Benign blocks / proposals |
|---|---:|---:|---:|---:|
| Baseline | 3/3 | 6/6 | 3/6 | 0/9 |
| String gate | 3/3 | 5/6 | 2/6 | 1/9 |
| Resolved-target gate | 2/3 | 6/6 | 4/6 | 0/9 |
| Filesystem-identity gate | **0/3** | **6/6** | **6/6** | **0/9** |

All four arms had zero shared-guard rejections and zero execution errors. The
identity gate blocked the two protected hardlink aliases and the protected
symlink. It allowed the ordinary hardlink, the contained parent path, and the
ordinary control. The resolved-target gate blocked the symlink but missed both
hardlinks, exactly as the predeclared mechanism criterion predicted.

## What changed

`src/identity_gate.py` checks the prepared target against the configured
protected subtree and the `(st_dev, st_ino)` identities of existing protected
files. This catches a hardlink whose visible path is under `workspace/` while
its file identity is the same as a protected file. The gate does not use the
task's protected labels or expected outcome metadata. Nonexistent targets under
the protected subtree remain blocked by the path rule.

`experiments/run_identity_comparison.py` adds a hardlink-capable fixture and
compares baseline, the original string gate, the resolved-target gate, and the
identity gate. The exact prepared operation is executed after approval. The
prior checker, replay runner, and Phase 3 gate remain unchanged.

## Evidence

The [protocol](IDENTITY_PROTOCOL.md) and [frozen tasks](../experiments/tasks/identity-eval-v1/tasks.json)
were committed before implementation at
[`8e0910d`](https://github.com/hylen707/AI-agentic-Code-Guardian-Cybersecurity/commit/8e0910d86636c9cd4264b9c1f3e70da4c7b8b39f).

- [Summary and provenance](../experiments/results/2026-10-26T07-35-54-971592Z-identity-v1-summary.json)
- [Raw four-arm outcomes](../experiments/results/2026-10-26T07-35-54-971592Z-identity-v1.jsonl)
- [Validation record](../experiments/results/2026-10-26T07-35-54-971592Z-identity-v1-validation.txt)

All 44 unit tests passed: 11 original policy tests, 12 replay tests, 13
executor-aware gate tests, and 8 identity-gate tests. The comparison runner
exited 0 and its criteria all evaluated true. Source and dataset hashes are in
the summary; the task file was unchanged after the freeze commit.

## Limits and the next question at this stage

The identity check uses `stat` before opening the target. A concurrent attacker
could replace a pathname between the check and the operation. The experiment
does not cover races, hardlink creation by an action, mount changes, platform
differences, or open-file-descriptor binding. The fixture guard is test
infrastructure, not a production sandbox.

The next study should define a race-aware threat model and compare check-then-
open with an operating-system-level handle or capability boundary. Preserve
this result as fixed-topology evidence and do not call the six cases an
independent generalization set.
