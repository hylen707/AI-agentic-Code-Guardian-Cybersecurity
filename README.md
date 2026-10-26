# CodeGuardian

**What must a runtime safeguard authorize: a path, a file, or an open handle?**

CodeGuardian is a reproducible systems-security study motivated by AI coding agents. It tests how authorization changes when a file has multiple names or when a name changes between inspection and execution. Five experimental stages move from policy-label agreement to observed file effects, retaining the failures that motivate each intervention.

The current contribution is a set of controlled counterexamples and comparisons. The experiments execute real operating-system file operations on disposable synthetic fixtures. They do not evaluate a live agent or establish a production security boundary.

## Research at a glance

| Question | Evidence | Consequence |
|---|---|---|
| Does policy-label agreement imply resource protection? | 45/45 v3 label matches coexist with two symlink misses and two legitimate task losses in the paired replay. | Evaluate actual resources and task goals separately from policy labels. |
| Does resolving a path address aliases? | The resolved-target gate achieves 0/4 protected operations and 8/8 safe completions in each of two related suites, reported separately. | Resolve the executor's target; retain fixed-topology assumptions. |
| Is a canonical path a unique file identity? | Hardlink-focused comparison: resolved gate 2/3 protected operations; identity gate 0/3. | Include device/inode identity for existing files. |
| Does a pre-open identity check survive replacement? | Deterministic replacement study: identity-path gate 4/6 protected content operations; descriptor-bound executor 0/6. | Authorize and use the same open object under the stated assumptions. |

These suites answer different questions and overlap in mechanisms. Their counts are not independent samples and should not be pooled into an overall security percentage.

## Latest experiment: pathname replacement

Ten cases pair reads and writes with ordinary controls, protected hardlink substitution before or after authorization, parent-directory substitution, and benign replacement. Each case runs in three fresh fixtures: 30 case/arm records.

| Outcome | No gate | Identity check, then pathname open | Descriptor-bound executor |
|---|---:|---:|---:|
| Protected content operations / attack schedules | 6/6 | 4/6 | **0/6** |
| Original-object completion / eligible cases | 2/8 | 2/8 | **8/8** |
| Benign blocks / benign cases | 0/4 | 0/4 | **0/4** |
| Protected opens, including metadata authorization | 6 | 4 | **2** |
| Infrastructure errors | 0 | 0 | 0 |

The descriptor arm opens two protected objects to inspect metadata, denies both, and performs no protected content I/O. Its `0/6` therefore means zero successful protected reads or writes in these six schedules, **not zero protected opens**. Original-object completion measures the specified operation on the initial ordinary inode; it is not live-agent task completion. The 6-case and 8-case denominators overlap.

The protocol and manifest were [frozen before implementation](https://github.com/hylen707/AI-agentic-Code-Guardian-Cybersecurity/commit/d0ddc20aac99365adb85bc48ef53539c8028a127). Read the [findings](docs/RACE_FINDINGS.md), [protocol](docs/RACE_PROTOCOL.md), and [raw evidence](experiments/results/2026-10-26T08-23-21-637204Z-race-v1.jsonl). All **55 unit tests passed** on 2026-10-26 (Asia/Seoul).

## Read the research

| Reader's purpose | Starting point |
|---|---|
| Understand the argument and contribution | [Research statement](docs/RESEARCH_STATEMENT.md) |
| Inspect the question and design rationale | [Project rationale](docs/IDEATION_REPORT.md) |
| Compare methods and outcome definitions | [Study map](docs/EXPERIMENT_PLAN.md) |
| Review implementation and trust boundaries | [Architecture](docs/ARCHITECTURE.md) and [source guide](src/README.md) |
| Reproduce a result | [Experiment guide](experiments/README.md) |
| Audit development and decisions | [Research log](docs/RESEARCH_LOG.md) and [changelog](CHANGELOG.md) |
| Trace prior findings | [Paired replay](docs/REPLAY_FINDINGS.md), [resolved targets](docs/GATE_FINDINGS.md), [file identity](docs/IDENTITY_FINDINGS.md) |
| Prepare an authentic personal account | [Reflection notes](docs/REFLECTION_NOTES.md) |

## Reproduce the latest study

Use Python 3.10+ on Linux with hardlink and symlink support. The implementation uses the standard library.

```bash
python -m unittest discover -s tests -v
python experiments/run_race_comparison.py --dataset experiments/tasks/race-eval-v1/tasks.json --base-commit 1829252dfc7421511f9d6c4aa1d49a0eb9f57ec0 --freeze-commit d0ddc20aac99365adb85bc48ef53539c8028a127
```

Each run saves raw records and a summary with hashes, environment, commands, and explicit criteria. Earlier code, measured datasets, frozen protocols, and raw results remain available. The current documentation was edited for clarity without rewriting experimental history.

## Scope and next question

The descriptor experiment covers existing regular-file reads and writes under deterministic name replacement, static protected membership, and trusted descriptor ownership. It does not establish confinement against arbitrary filesystem changes, protection against writes to the same inode, a no-open policy, or a concurrent attack success rate. Creation, dynamic policy updates, and live-agent adaptation require new protocols.

The next research question is whether object continuity remains useful when the intended object itself changes: concurrent content mutation, changes to protected membership, and the semantics of newly created files. A future agent study also needs fixed model settings, constrained tools, task budgets, and an independently administered evaluation.

This continuation includes AI-assisted implementation, analysis, and editing. Repository evidence supports technical claims; personal contribution and learning claims require the author's own account. See [attribution and interpretation](docs/RESEARCH_STATEMENT.md#attribution-and-interpretation).
