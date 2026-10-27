# CodeGuardian

**What must a runtime safeguard authorize: a path, an object, or a content version?**

CodeGuardian is a reproducible systems-security study motivated by AI coding agents. Six experimental stages examine what happens when resource names, identities, and contents diverge between inspection and execution. The project retains the counterexamples that motivate each intervention.

The experiments perform real operating-system file operations on disposable synthetic fixtures. They establish bounded mechanism results, not live-agent effectiveness or a production security boundary.

## Research at a glance

| Question | Evidence | Consequence |
|---|---|---|
| Does policy agreement imply resource protection? | 45/45 label matches coexist with two symlink misses and two legitimate task losses in paired replay. | Measure resources and task goals separately from labels. |
| Does path resolution address aliases? | 0/4 protected operations and 8/8 safe completions in each of two related suites, reported separately. | Approve the resolved target under explicit topology assumptions. |
| Is a pathname a unique file identity? | Resolved gate: 2/3 protected operations; identity gate: 0/3 in the hardlink suite. | Account for device/inode identity. |
| Does pre-open identity checking survive name replacement? | Identity-path gate: 4/6 protected content operations; descriptor executor: 0/6. | Use the same authorized open object. |
| Does the same object guarantee the approved bytes? | Hash/reread: 3/5 unapproved deliveries; verified buffer: 0/5, with three stale approved deliveries. | Validate the value actually delivered and distinguish approval from freshness. |

These suites answer different questions and overlap in mechanisms. Their counts must not be pooled into an overall security percentage.

## Latest experiment: same file, different content

Eight cases compare identity-only reads, a digest check followed by a reread, and delivery of the captured value that passed validation. Three unchanged controls cover ASCII, Unicode, and empty content; five schedules change bytes without replacing the inode. Every case runs in three fresh fixtures: 24 case/arm records.

| Outcome | Identity only | Hash, then reread | Verified buffer |
|---|---:|---:|---:|
| Unapproved deliveries / mutation cases | 5/5 | 3/5 | **0/5** |
| Approved-version deliveries / all cases | 3/8 | 3/8 | **6/8** |
| Content-version denials | 0 | 2 | 2 |
| Unchanged controls delivered correctly | 3/3 | 3/3 | **3/3** |
| Approved but stale deliveries | 0 | 0 | **3** |
| Infrastructure errors | 0 | 0 | 0 |

The verified reader prevents delivery of an unapproved version in these schedules, but it still reads changed bytes for inspection in the two denied cases. It also returns an older approved value in three cases. This is neither a no-read policy nor a freshness guarantee. The identity-only comparator never implemented the newly introduced version rule; its result does not invalidate Phase 5's identity claim.

The protocol and manifest were [frozen before implementation](https://github.com/hylen707/AI-agentic-Code-Guardian-Cybersecurity/commit/ce3fd6d245a2013090f7bd8c6367d08895132723). Read the [findings](docs/CONTENT_FINDINGS.md), [protocol](docs/CONTENT_PROTOCOL.md), and [raw evidence](experiments/results/2026-10-27T12-21-15-144558Z-content-v1.jsonl). All **67 unit tests passed** on 2026-10-27 (Asia/Seoul).

## Prior result: pathname replacement

The [Phase 5 study](docs/RACE_FINDINGS.md) observed 6/6 → 4/6 → 0/6 protected content operations across no-gate, identity-path, and descriptor-bound arms. The descriptor arm completed original-object operations in 8/8 eligible cases, but still opened two protected objects for metadata authorization before denying content I/O. These resource-access measures are different from Phase 6's content-delivery measures.

## Read the research

| Reader's purpose | Starting point |
|---|---|
| Understand the argument and contribution | [Research statement](docs/RESEARCH_STATEMENT.md) |
| Inspect the question and design rationale | [Project rationale](docs/IDEATION_REPORT.md) |
| Compare methods and outcome definitions | [Study map](docs/EXPERIMENT_PLAN.md) |
| Review implementation and trust boundaries | [Architecture](docs/ARCHITECTURE.md) and [source guide](src/README.md) |
| Reproduce a result | [Experiment guide](experiments/README.md) |
| Audit development and decisions | [Research log](docs/RESEARCH_LOG.md) and [changelog](CHANGELOG.md) |
| Trace prior findings | [Paired replay](docs/REPLAY_FINDINGS.md), [resolved targets](docs/GATE_FINDINGS.md), [file identity](docs/IDENTITY_FINDINGS.md), [descriptor binding](docs/RACE_FINDINGS.md) |
| Prepare an authentic personal account | [Reflection notes](docs/REFLECTION_NOTES.md) |

## Reproduce the latest study

Use Python 3.10+ on Linux with hardlink support and `pread`; the standard library is sufficient. The full test suite also exercises symlinks and FIFOs.

```bash
python -m unittest discover -s tests -v
python experiments/run_content_comparison.py --dataset experiments/tasks/content-eval-v1/tasks.json --base-commit 4b47ab21db9808646cfc4a0dfd1be308896bf227 --freeze-commit ce3fd6d245a2013090f7bd8c6367d08895132723
```

Runs save raw records and summaries with hashes, environment, commands, and criteria. Earlier implementations, measured datasets, frozen protocols, and raw results remain available. New findings refine the scope of claims without rewriting experimental history.

## Scope and next question

The latest reader operates on small existing UTF-8 files with static approved digests and trusted process memory. It does not provide atomic filesystem snapshots, streaming validation, general directory confinement, dynamic policy updates, or live-agent integration. The next question is how to authorize a legitimate new version while making stale approved values explicit to the consumer.

This continuation includes AI-assisted design, implementation, execution, analysis, and editing. Repository evidence supports technical claims; personal contribution and learning claims require the author's own account. See [attribution and interpretation](docs/RESEARCH_STATEMENT.md#attribution-and-interpretation).
