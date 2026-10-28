# Claims and evidence

This map connects the six completed stages to their conditions, denominators, and retained artifacts. Counts describe the selected cases. The [evaluation standards](EXPERIMENT_PLAN.md) define the metrics; [threat model and limits](LIMITATIONS.md) bound their interpretation.

## Phases 1 and 2: labels versus resource effects

Phase 1 records 20/20, 21/21, and 45/45 expected-label matches for v1, v2, and v3. These versions are nested, not independent samples. Phase 2 then executes eight tasks in two fresh-fixture arms (16 task/arm records).

| Replay outcome | Baseline | String gate |
|---|---:|---:|
| Protected operations / protected proposals | 4/4 | 2/4 |
| Functional task completion | 8/8 | 6/8 |
| Safe task completion | 4/8 | 4/8 |

Two direct protected operations are blocked, two symlink aliases escape, and two benign path spellings lose legitimate completion. A passing label test therefore does not establish resource protection or an improvement in safely completed work. [Replay findings](REPLAY_FINDINGS.md) explain the task goals and negative result.

## Phases 3 and 4: resolved names and file identities

| Study | Compared arms | Protected operations | Safe completion |
|---|---|---|---|
| Phase 3 development: 8 tasks, 24 records | Baseline → string gate → resolved gate | 4/4 → 2/4 → 0/4 | 4/8 → 4/8 → 8/8 |
| Phase 3 supplemental: 8 tasks, 24 records | Baseline → string gate → resolved gate | 4/4 → 2/4 → 0/4 | 4/8 → 4/8 → 8/8 |
| Phase 4: 6 tasks, 24 records | Baseline → string gate → resolved gate → identity gate | 3/3 → 3/3 → 2/3 → 0/3 | 3/6 → 2/6 → 4/6 → 6/6 |

Phase 3 approves the resolved target under static topology; its two related suites stay separate. The supplemental cases were frozen before implementation but remained developer-visible. Phase 4 introduces hardlinks: different resolved names can share device/inode identity. Checking configured protected identities closes the two hardlink misses, while still depending on no later pathname replacement. [Gate findings](GATE_FINDINGS.md) · [Identity findings](IDENTITY_FINDINGS.md).

## Phase 5: preserve the authorized object

Ten deterministic replacement cases run in three arms (30 records). Six are attack schedules; eight are eligible for original-object completion. Those sets overlap and must not be added.

| Outcome | Baseline | Identity-path | Descriptor-bound |
|---|---:|---:|---:|
| Protected content operations / attack schedules | 6/6 | 4/6 | 0/6 |
| Protected opens / attack schedules | 6/6 | 4/6 | 2/6 |
| Original-object completion / eligible cases | 2/8 | 2/8 | 8/8 |
| Benign blocks / benign cases | 0/4 | 0/4 | 0/4 |
| Infrastructure errors | 0 | 0 | 0 |

Opening without truncation, authorizing with `fstat`, and retaining the same descriptor prevents the selected after-check redirections. The two before-check protected substitutions still cause metadata opens followed by denial. Zero protected content operations is not zero protected opens. These are selected orderings, not concurrent race win rates. [Replacement findings](RACE_FINDINGS.md).

## Phase 6: deliver the validated value

Eight cases run in three arms (24 records): three unchanged ASCII/Unicode/empty controls and five same-inode mutation schedules.

| Outcome | Identity-only | Hash/reread | Verified buffer |
|---|---:|---:|---:|
| Unapproved deliveries / mutation cases | 5/5 | 3/5 | 0/5 |
| Approved deliveries / all cases | 3/8 | 3/8 | 6/8 |
| All deliveries / all cases | 8/8 | 6/8 | 6/8 |
| Content-version denials / all cases | 0/8 | 2/8 | 2/8 |
| Approved control deliveries / controls | 3/3 | 3/3 | 3/3 |
| Approved but stale deliveries / all cases | 0/8 | 0/8 | 3/8 |
| Infrastructure errors | 0 | 0 | 0 |

Both digest arms inspect and deny two before-capture changes. Only the buffer retains the approved value through three after-validation changes; those three deliveries are stale relative to the final live bytes. The content rule permits inspection and does not promise freshness. The identity-only arm never implemented this new delivery rule. [Content findings](CONTENT_FINDINGS.md).

## Artifact index

Raw links contain case/arm records; summary links contain counts and, for filesystem studies, provenance and source hashes. The policy verification record supplies additional input/source checks for Phase 1.

| Stage/run | Manifest | Raw records | Summary |
|---|---|---|---|
| 1 · v1 | [Input](../experiments/cases/v1/actions.jsonl) | [JSONL](../experiments/results/2026-10-25T16-05-40Z-v1.jsonl) | [JSON](../experiments/results/2026-10-25T16-05-40Z-v1-summary.json) |
| 1 · v2 | [Input](../experiments/cases/v2/actions.jsonl) | [JSONL](../experiments/results/2026-10-25T16-05-41Z-v2.jsonl) | [JSON](../experiments/results/2026-10-25T16-05-41Z-v2-summary.json) |
| 1 · v3 | [Input](../experiments/cases/v3/actions.jsonl) | [JSONL](../experiments/results/2026-10-25T16-06-42Z-v3.jsonl) | [JSON](../experiments/results/2026-10-25T16-06-42Z-v3-summary.json) |
| 2 · replay | [Input](../experiments/tasks/replay-v1/tasks.json) | [JSONL](../experiments/results/2026-10-25T16-23-07-058859Z-replay-v1.jsonl) | [JSON](../experiments/results/2026-10-25T16-23-07-058859Z-replay-v1-summary.json) |
| 3 · development | [Input](../experiments/tasks/replay-v1/tasks.json) | [JSONL](../experiments/results/2026-10-26T02-23-10-090530Z-gate-v1-development.jsonl) | [JSON](../experiments/results/2026-10-26T02-23-10-090530Z-gate-v1-development-summary.json) |
| 3 · supplemental | [Input](../experiments/tasks/gate-eval-v1/tasks.json) | [JSONL](../experiments/results/2026-10-26T02-23-27-301341Z-gate-v1-supplemental.jsonl) | [JSON](../experiments/results/2026-10-26T02-23-27-301341Z-gate-v1-supplemental-summary.json) |
| 4 · identity | [Input](../experiments/tasks/identity-eval-v1/tasks.json) | [JSONL](../experiments/results/2026-10-26T07-35-54-971592Z-identity-v1.jsonl) | [JSON](../experiments/results/2026-10-26T07-35-54-971592Z-identity-v1-summary.json) |
| 5 · replacement | [Input](../experiments/tasks/race-eval-v1/tasks.json) | [JSONL](../experiments/results/2026-10-26T08-23-21-637204Z-race-v1.jsonl) | [JSON](../experiments/results/2026-10-26T08-23-21-637204Z-race-v1-summary.json) |
| 6 · content | [Input](../experiments/tasks/content-eval-v1/tasks.json) | [JSONL](../experiments/results/2026-10-27T12-21-15-144558Z-content-v1.jsonl) | [JSON](../experiments/results/2026-10-27T12-21-15-144558Z-content-v1-summary.json) |

[Phase 1 verification](../experiments/results/2026-10-25T16-05-40Z-verification.json) · [Phase 5 consistency check](../experiments/results/2026-10-26T08-23-21-637204Z-race-v1-verification.json) · [Phase 6 consistency check](../experiments/results/2026-10-27T12-21-15-144558Z-content-v1-verification.json) · [67-test historical transcript](../experiments/results/2026-10-27T12-21-15-144558Z-content-v1-unit-tests.txt).

### Prospective design freezes

| Stage | Protocol | Freeze commit |
|---|---|---|
| 3 | [Gate](GATE_PROTOCOL.md) | [`1d9bbe3`](https://github.com/hylen707/AI-agentic-Code-Guardian-Cybersecurity/commit/1d9bbe305625f5b7df55a185463908729c48cc03) |
| 4 | [Identity](IDENTITY_PROTOCOL.md) | [`8e0910d`](https://github.com/hylen707/AI-agentic-Code-Guardian-Cybersecurity/commit/8e0910d86636c9cd4264b9c1f3e70da4c7b8b39f) |
| 5 | [Replacement](RACE_PROTOCOL.md) | [`d0ddc20`](https://github.com/hylen707/AI-agentic-Code-Guardian-Cybersecurity/commit/d0ddc20aac99365adb85bc48ef53539c8028a127) |
| 6 | [Content](CONTENT_PROTOCOL.md) | [`ce3fd6d`](https://github.com/hylen707/AI-agentic-Code-Guardian-Cybersecurity/commit/ce3fd6d245a2013090f7bd8c6367d08895132723) |

Phase 1 uses versioned case design and Phase 2 has a [replay protocol](REPLAY_PROTOCOL.md); this table does not infer a prospective freeze for them. A freeze documents design timing, not blinded evaluation or independent review.

## Recounting and interpreting a run

Start with the raw filename recorded in its summary. Check the expected case/arm grid, then count resource events or delivery fields using that study's definitions. Check controls, denials, errors, and legitimate completion alongside the headline protection count. In Phase 6, for example, count `unapproved_delivery`, `approved_delivery`, and `approved_but_stale` separately; a blocked row remains part of the eight-case approved-delivery denominator.

The comparison runners store `summary.criteria`; exit 0 indicates clean execution, not that every criterion is true. Source and dataset hashes establish which local files produced a run; commit labels are caller-supplied metadata. Follow the [reproduction guide](../experiments/README.md#reading-and-preserving-artifacts) before interpreting a fresh execution as a historical reproduction.

No cross-study total is meaningful: label matches, protected operations, task completion, original-object completion, and delivered versions have different units.
