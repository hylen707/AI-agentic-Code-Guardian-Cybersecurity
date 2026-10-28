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

## Research thesis and threat model

CodeGuardian studies a gap between **what a policy authorizes** and **what a filesystem executor actually uses**. AI coding agents motivate this problem, but the completed experiments use real file operations on disposable synthetic fixtures, not live-agent actions.

The research moves from lexical path checks to resolved targets, device/inode identity, held descriptors, and approved content versions. Let `R(p,t)` denote the object reached through pathname `p` at time `t`. Approving `R(p,t_check)` need not authorize `R(p,t_use)` after name replacement. A descriptor can preserve object identity without freezing bytes; a verified buffer can preserve approved bytes without guaranteeing freshness.

Each new phase tests an assumption left open by the previous one. The contribution is a **counterexample-driven, reproducible argument**, not a claim to a new security primitive. See the [research statement](docs/RESEARCH_STATEMENT.md).

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

## Research progression: six experiments, six distinct claims

**Phase 1 · Policy conformance.** The checker matches 45/45 expected labels in the largest dataset, but versions v1–v3 overlap. Label agreement tests an implementation against curated inputs, not whether actual file I/O honors the intended policy. [Verification](experiments/results/2026-10-25T16-05-40Z-verification.json).

**Phase 2 · Task replay.** Eight tasks introduce observable resource operations and required read/file goals. The string gate reduces protected operations from 4/4 to 2/4, yet safe completion remains 4/8: two protected aliases escape and two benign paths lose legitimate completion. Less risky-looking output is not necessarily more *safely completed work*. [Findings](docs/REPLAY_FINDINGS.md).

**Phase 3 · Resolved-target approval.** An executor-aware gate achieves 0/4 protected operations and 8/8 safe completions in each of two related eight-task suites, reported separately. The frozen supplemental suite is developer-visible rather than blind. The improvement depends on static topology. [Protocol](docs/GATE_PROTOCOL.md) · [Findings](docs/GATE_FINDINGS.md).

**Phase 4 · File identity.** Hardlinks can have different names but identical `(st_dev, st_ino)`. Adding checks against configured protected identities reduces 2/3 protected operations under the resolved gate to 0/3 in the six-task suite, with 6/6 safe completions. The pre-open check is still exposed to later pathname replacement. [Protocol](docs/IDENTITY_PROTOCOL.md) · [Findings](docs/IDENTITY_FINDINGS.md).

**Phase 5 · Object continuity.** Deterministic replacement schedules expose that gap: the identity-path arm permits 4/6 protected content operations. Opening without truncation, checking with `fstat`, and then using the *same descriptor* yields 0/6 content operations and 8/8 eligible original-object completions. Two protected objects are nonetheless opened for metadata checks before denial; zero protected content I/O does **not** mean zero protected opens. [Protocol](docs/RACE_PROTOCOL.md) · [Findings](docs/RACE_FINDINGS.md).

**Phase 6 · Content continuity.** Same-inode mutations defeat a digest check followed by a separate reread (3/5 unapproved deliveries). Validating and returning the *captured buffer* gives 0/5 unapproved deliveries. Two changed-before-capture cases are denied after inspection, and three changed-after-validation cases return approved yet stale values. The observed claim concerns delivery of approved bytes, not freshness or no-read confidentiality. [Protocol](docs/CONTENT_PROTOCOL.md) · [Findings](docs/CONTENT_FINDINGS.md).

The studies share mechanisms but answer different questions. Combining their counts into a single safety percentage would erase distinctions between names, file objects, and returned values.

## Read the research

| Reader's purpose | Starting point |
|---|---|
| Understand the argument and contribution | [Research statement](docs/RESEARCH_STATEMENT.md) |
| Inspect the question and design rationale | [Project rationale](docs/IDEATION_REPORT.md) |
| Compare methods and outcome definitions | [Study map](docs/EXPERIMENT_PLAN.md) |
| Review implementation and trust boundaries | [Architecture](docs/ARCHITECTURE.md) and [source guide](src/README.md) |
| Reproduce a result | [Experiment guide](experiments/README.md) |
| Audit development and decisions | [Research log](docs/RESEARCH_LOG.md) and [changelog](docs/CHANGELOG.md) |
| Trace prior findings | [Paired replay](docs/REPLAY_FINDINGS.md), [resolved targets](docs/GATE_FINDINGS.md), [file identity](docs/IDENTITY_FINDINGS.md), [descriptor binding](docs/RACE_FINDINGS.md) |
| Prepare an authentic personal account | [Reflection notes](docs/REFLECTION_NOTES.md) |

## Experimental methodology and outcome definitions

| Control | Practice | Purpose |
|---|---|---|
| Paired arms | Equivalent declared tasks and fresh disposable fixtures | Avoid contamination between comparisons |
| Independent oracle | Observe actual file identity, I/O effects, goals, or returned bytes | Do not infer protection from labels alone |
| Frozen design | Commit later-phase protocols and case manifests before implementation | Expose post-hoc changes to claims or denominators |
| Error accounting | Report denials, benign blocks, metadata opens, content I/O, and infrastructure failures separately | A broken run must not count as protection |
| Provenance | Retain case-level JSONL, summary criteria, hashes, environment, commands, and test output | Make conclusions auditable |

**Metrics have different units.** Phase 1 counts label matches. Phases 2–4 count protected operations and safe/functional task completion. Phase 5 counts protected content I/O separately from protected metadata opens and measures original-object completion. Phase 6 counts delivered approved/unapproved versions, denials, and approved-but-stale results; all eight cases remain in the delivery denominator.

The recorded 67 passing unit tests establish regression behavior, not 67 independent adversarial trials. Selected deterministic schedules and developer-visible cases are useful mechanism tests, but they do not measure real-world race frequency, live-agent effectiveness, or statistical confidence. [Study map and criteria](docs/EXPERIMENT_PLAN.md).

## Evidence trail and reproducibility

Each research claim follows **question → frozen protocol → manifest → raw case/arm records → summary → bounded interpretation**. For Phase 6, the [protocol](docs/CONTENT_PROTOCOL.md) and [eight-case manifest](experiments/tasks/content-eval-v1/tasks.json) were frozen at [`ce3fd6d`](https://github.com/hylen707/AI-agentic-Code-Guardian-Cybersecurity/commit/ce3fd6d245a2013090f7bd8c6367d08895132723) before implementation. Audit the [24 raw records](experiments/results/2026-10-27T12-21-15-144558Z-content-v1.jsonl), [summary/provenance](experiments/results/2026-10-27T12-21-15-144558Z-content-v1-summary.json), and [test transcript](experiments/results/2026-10-27T12-21-15-144558Z-content-v1-unit-tests.txt).

The unchanged ASCII, Unicode, and empty controls check legitimate deliveries; before-capture versus after-validation changes distinguish denial, unapproved delivery, and stale approved delivery. The final live bytes are compared with the returned bytes. Inspection and infrastructure failures are not silently recoded as denials.

Reproduce on disposable Linux fixtures using the [experiment guide](experiments/README.md). A new execution does not overwrite historical evidence. The [research log](docs/RESEARCH_LOG.md) records decisions; the [changelog](docs/CHANGELOG.md) records implemented updates. [Attribution](docs/RESEARCH_STATEMENT.md#attribution-and-interpretation) distinguishes AI assistance from unverified personal authorship.

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
