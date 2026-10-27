# Project rationale: authorization at the execution boundary

**Status:** six experimental stages completed on synthetic fixtures; live-agent evaluation remains future work.

**Updated:** 2026-10-27 (Asia/Seoul).

## Research question

Can a lightweight runtime safeguard reduce protected-resource operations while preserving legitimate work, and which execution assumptions determine whether its decisions remain valid?

AI coding agents motivate the question because their proposed actions need an execution boundary. The present experiments isolate the filesystem portion of that boundary. They do not involve an actual model making or adapting proposals.

## Why this question is tractable

File operations offer observable distinctions between a requested name, its resolved target, the underlying file identity, and an open descriptor. A small fixture can change one of these relationships while holding the requested operation constant. That makes it possible to construct counterexamples, attribute failures to a mechanism, and compare bounded interventions without using sensitive data.

The project began with string-policy checks. Its most useful revision was methodological: replacing agreement with hand-authored labels with observations of actual file effects and required task goals. A passing label test could then be examined alongside an execution failure instead of being mistaken for a security result.

## Design progression

| Stage | Assumption examined | Intervention or observation |
|---|---|---|
| Policy conformance | Expected labels adequately describe the implemented policy. | Versioned JSON cases and observed decisions. |
| Paired replay | Allowed names correspond to allowed resources. | Actual fixture execution exposes alias misses and legitimate task losses. |
| Resolved targets | Canonical path approval is sufficient under fixed topology. | Approve the prepared resolved target and immutable request content. |
| File identity | Different pathnames imply different protected resources. | Compare device/inode identities to catch hardlinks. |
| Descriptor binding | A pre-open identity remains valid until use. | Retain and operate on the same authorized descriptor across replacement. |
| Approved content | A stable object or earlier digest implies an approved delivered value. | Validate and return the same captured value; measure stale approved output. |

The [study map](EXPERIMENT_PLAN.md) links each question to its protocol and evidence. Results are reported within each stage's assumptions; later stages do not rewrite earlier measurements.

## Contribution

The deliverable is an auditable experimental argument: explicit threat models, matched comparisons, counterexamples, bounded improvements, raw outcomes, and reproducible commands. The project applies established operating-system mechanisms rather than claiming their invention. Its research value depends on the quality of the questions and evidence, not on the breadth of an unsupported security claim.

## Scope

Experiments use synthetic text, disposable directories, regular files, hardlinks, and symlinks. Controlled file replacement is performed by trusted experiment code. Policy classifiers never execute proposed shell commands; fixture runners execute only their documented operations. There are no real credentials, user documents, production targets, or live-agent sessions in these studies.

The descriptor executor covers existing-file read/write operations; the new reader narrows content delivery to a configured approved UTF-8 version. A production boundary would also need directory confinement, creation semantics, policy updates, trusted version distribution, resource limits, hostile object types, and a defined response to arbitrary concurrent content mutation. These remain separate design obligations.

## Open research direction

Phase 6 now separates stable identity from a particular approved state. Returning a validated buffer prevents the selected unapproved deliveries but can return older content. The next useful question is how legitimate version updates become authorized and how a consumer should respond to stale approved data. Dynamic resource classification and changes during capture require separate protocols.

An eventual agent study should use constrained tools, fixed model/prompt versions, explicit budgets, repeated trials, and task-correctness judgments independent of the gate. That study would address behavior and utility beyond the current fixed proposals.

## Sources and authorship

The technical bases for [descriptor binding](RACE_PROTOCOL.md#technical-basis) and [content validation](CONTENT_PROTOCOL.md#technical-basis) record the systems documentation consulted. The [research statement](RESEARCH_STATEMENT.md) distinguishes the project's contribution from established mechanisms and describes AI assistance. Personal motivation and learning belong in the author's own [reflection notes](REFLECTION_NOTES.md).
