# From pathname approval to object continuity

## Abstract

CodeGuardian studies a narrow problem relevant to tool-using AI systems: whether a runtime decision remains valid for the resource an executor eventually uses. A sequence of synthetic filesystem experiments separates lexical policy conformance, resolved paths, file identities, and descriptor-bound execution. Earlier positive results are preserved alongside counterexamples to their broader interpretation. In the latest ten-case deterministic replacement study, a pre-open identity gate permits four protected content operations across six attack schedules. A descriptor-bound executor permits none and completes the specified operation on the original object in all eight eligible cases. It still opens two protected objects for metadata inspection. The contribution is a reproducible account of authorization assumptions and failure mechanisms, with explicit limits on generalization.

## The central argument

A policy decision concerns a representation of a resource. Execution concerns an operating-system object. Protection requires the relationship between those two to survive until the operation occurs.

Let `R(p, t)` denote the object reached by pathname `p` at time `t`, and let `P` be the fixed set of protected file identities. A pathname gate can establish `R(p, t_check) ∉ P`. That observation does not imply `R(p, t_use) ∉ P` when names can change. The latest experiment constructs the missing step directly: the gate approves an ordinary object, the fixture controller changes the name binding, and the later open reaches a protected object.

For an open descriptor `d`, the proposed invariant is narrower: authorization and content I/O refer to the same held object. If `identity(d) ∉ P` at authorization, `P` remains fixed, and the trusted executor retains exclusive control of `d`, subsequent name replacement cannot redirect that descriptor to another object. The executor must avoid reopening the pathname and must defer truncation until after approval. This argument follows established descriptor semantics; the experiment tests the implementation in selected schedules rather than proving all possible executions. See the technical sources in the [protocol](RACE_PROTOCOL.md#technical-basis).

Object continuity does not imply content integrity. Another actor could alter bytes in the same inode. Nor does it implement a no-open policy: descriptor inspection requires an open. Those are different properties and would require different experiments.

## Evidence that changed the design

The [policy dataset](../experiments/cases/v3/README.md) initially provided 45/45 expected-label matches. Its oracle described the checker itself. The [paired replay](REPLAY_FINDINGS.md) then asked about resource effects and required reads: the string gate prevented two protected operations, missed two aliases, and lost two legitimate completions. Safe completion stayed at 4/8. This negative result exposed the gap between a passing policy test and useful protection.

The [resolved-target intervention](GATE_FINDINGS.md) recovered legitimate completion and blocked symlink-mediated protected access in two separately reported eight-task suites. The [identity study](IDENTITY_FINDINGS.md) then changed one assumption: two paths could name the same file through hardlinks. The resolved gate missed both protected hardlinks, while identity checking blocked them. That success depended on topology remaining fixed.

The [replacement study](RACE_FINDINGS.md) challenged that dependency. All four after-check protected substitutions bypassed the identity-path arm. The descriptor arm retained the initial ordinary object through the same substitutions and through benign replacements. Ordinary controls rule out blanket refusal as the explanation for its zero protected content operations. Before-check substitutions distinguish identity authorization from merely holding whichever file was opened.

## Contribution and research judgment

This repository contributes an inspectable experimental progression: a failed assumption, a bounded intervention, and a follow-up that tests the intervention's remaining dependency. It also contributes raw traces, task-level or object-level oracles, prospective protocol freezes, and separate accounting for policy blocks and infrastructure errors.

The security mechanisms themselves are established systems concepts. The project does not claim a new sandbox primitive, a novel discovery of TOCTOU, or an independently evaluated defense against AI agents. Its value lies in making the reasoning testable and in revising claims when the threat model changes.

## Validity and open questions

All cases are curated and visible during development. Related cases are not independent samples. The latest schedules deterministically arrange the check/use ordering; they do not measure how often an adversary wins a concurrent race. No confidence interval or population security rate is justified by these data. The baseline and intervention share controlled fixtures and content-I/O routines, but the intervention deliberately changes the order of open and authorization.

The next studies should distinguish object identity from object state, test fail-closed behavior under policy-inventory changes, and define creation semantics. Agent integration should follow a separate protocol with model and prompt versions, constrained tool permissions, budgets, repeated task trials, and an external or otherwise independent assessment of task correctness.

## Attribution and interpretation

The repository owner directs the project. This continuation used ChatGPT/Codex to assist with experiment design, implementation, execution, analysis, and English-language editing. The commits, logs, and artifacts document what was produced and tested; they do not establish which concepts the owner developed independently or what the owner personally learned.

A portfolio or application account should identify the owner's actual decisions, revisions, explanations, and independent work, and disclose assistance where relevant. [Reflection notes](REFLECTION_NOTES.md) provide evidence-linked prompts without supplying an invented personal narrative. No institutional affiliation, external review, publication, or deployment impact is claimed.
