# Documentation

CodeGuardian studies the continuity between an authorization decision and the filesystem object or content eventually used. Start with the route matching your purpose.

| Purpose | Reading route |
|---|---|
| Understand the research | [Project overview](../README.md) → [research statement](RESEARCH_STATEMENT.md) → [threat model and limits](LIMITATIONS.md) |
| Reproduce a result | [Experiment guide](../experiments/README.md) → relevant manifest/protocol below → [evidence map](EVIDENCE.md) |
| Review the implementation | [Architecture](ARCHITECTURE.md) → [source guide](../src/README.md) → [evaluation standards](EXPERIMENT_PLAN.md) |
| Audit a claim | [Evidence map](EVIDENCE.md) → raw records and summary → corresponding findings |

## Research and evaluation

| Document | Responsibility |
|---|---|
| [Research statement](RESEARCH_STATEMENT.md) | Abstract, technical argument, contribution, and attribution |
| [Threat model and limits](LIMITATIONS.md) | Controlled adversarial actions, trusted components, assumptions, and validity threats |
| [Evidence map](EVIDENCE.md) | Claim → conditions and denominator → raw records and summary → interpretation |
| [Study map and evaluation standards](EXPERIMENT_PLAN.md) | Outcome definitions, controls, and requirements for future protocols |
| [Architecture](ARCHITECTURE.md) | Component interfaces, execution order, and trust boundaries |
| [Experiment guide](../experiments/README.md) | Environment, executable commands, expected outputs, and provenance |

## Study-specific methods and results

| Stage | Method | Result |
|---|---|---|
| 1. Policy conformance | [v3 case design](../experiments/cases/v3/README.md); v1–v3 overlap | [Verification record](../experiments/results/2026-10-25T16-05-40Z-verification.json) |
| 2. Paired replay | [Replay protocol](REPLAY_PROTOCOL.md) | [Replay findings](REPLAY_FINDINGS.md) |
| 3. Resolved targets | [Gate protocol](GATE_PROTOCOL.md); development and supplemental suites stay separate | [Gate findings](GATE_FINDINGS.md) |
| 4. Hardlink identity | [Identity protocol](IDENTITY_PROTOCOL.md) | [Identity findings](IDENTITY_FINDINGS.md) |
| 5. Pathname replacement | [Replacement protocol](RACE_PROTOCOL.md) | [Replacement findings](RACE_FINDINGS.md) |
| 6. Same-inode content mutation | [Content protocol](CONTENT_PROTOCOL.md) | [Content findings](CONTENT_FINDINGS.md) |

## Rationale and history

- [Project rationale](IDEATION_REPORT.md): original motivation and proposed scope; read completed results through the evidence map.
- [Research log](RESEARCH_LOG.md): dated questions, decisions, negative results, and interpretation.
- [Changelog](CHANGELOG.md): implemented changes and their validation.
- [Reflection notes](REFLECTION_NOTES.md): evidence-linked prompts for the author's own account.
- [Documentation benchmark](DOCUMENTATION_BENCHMARK.md): official reference projects, observed documentation patterns, and application decisions.

The README is the entry point; this index owns navigation. The research statement owns the argument, the experiment guide owns execution instructions, and the evidence map owns cross-study artifact lookup. Frozen protocols, measured manifests, and raw evidence retain their historical contents. A later finding refines a claim through a new record rather than silently changing an earlier result.
