# Phase 4: filesystem-identity gate comparison

Protocol version: `identity-v1`. Design date: 2026-10-26 (Asia/Seoul).
The task file was frozen before the identity-aware implementation.

## Research question

Can comparing the prepared target's filesystem identity with the identities of
protected files prevent hardlink-mediated access while retaining the benefits
of the resolved-target gate?

## Arms

Each fixed task runs in four fresh fixture copies:

1. `baseline`: execute the prepared operation without a policy gate.
2. `string_gate`: call the original string-only `CodeGuardian` on the raw proposal.
3. `resolved_gate`: call the Phase 3 `ExecutorAwareGate` on the prepared target.
4. `identity_gate`: call the new `IdentityAwareGate` on the prepared target.

The fixture builder, root containment guard, executor, action order, and goal
oracle are shared. Only the gate changes. The identity gate receives configured
protected roots and compares `(st_dev, st_ino)` identities of existing targets;
it does not read task labels or expected outcomes. The exact prepared operation
approved by a gate is the one executed afterward.

## Frozen tasks and criteria

The six tasks contain ordinary controls, a benign hardlink, two protected
hardlink aliases, a protected symlink, and a contained parent path. Each task
has two proposals and explicit file/read goals. All paths and file contents are
synthetic. The suite is designed to expose known mechanisms and is not blind or
independent evidence.

Before implementation, freeze `experiments/tasks/identity-eval-v1/tasks.json`
and require:

- all protected proposals blocked by `identity_gate`, with zero realized
  protected accesses;
- all six functional and safe task goals completed in `identity_gate`;
- zero benign proposals blocked by `identity_gate`;
- `resolved_gate` blocks the symlink but misses the two hardlink aliases;
- baseline/string/resolved outcomes remain visible and no guard/execution errors
  occur in the measured run.

These are suite-level diagnostic criteria, not general security claims.

## Threat model and limits

Hardlinks are created during trusted fixture setup and cannot be created by an
action. The topology is fixed after setup. The identity check uses `os.stat` on
the prepared target and each configured protected file. This handles hardlinks
on the recorded filesystem, but it is not a race-resistant open: a concurrent
replacement between checking and opening can invalidate the result. It does
not claim to handle device-specific semantics, mount changes, or every OS.

Symlinks are resolved by the shared preparation step. Nonexistent create targets
are protected by the configured protected subtree path rule; existing targets
are also checked by identity. The fixture guard is test infrastructure, not a
production sandbox. No shell, network, credentials, personal data, hardlink
creation by actions, concurrent mutation, or live AI agent is used.

Report task-level outcomes, protected reads/writes, benign blocks, guard
rejections, and execution errors separately for all four arms. Preserve raw
traces, hashes, environment, source/task revisions, and criteria. Do not pool
this suite with prior suites as independent observations.
