# From pathname approval to object and content continuity

[Documentation index](README.md) · [Claims and artifacts](EVIDENCE.md) · [Threat model and limits](LIMITATIONS.md)

## Abstract

CodeGuardian studies whether a runtime decision remains valid for the resource and value an executor ultimately uses. Six synthetic filesystem stages separate lexical policy, resolved paths, file identities, held descriptors, and approved content versions. Descriptor binding prevents the selected pathname substitutions from redirecting content I/O, but does not freeze file contents. In the latest eight-case study, hashing and then rereading the same descriptor delivers an unapproved value in three of five mutation schedules. Returning the captured value that passed validation eliminates those unapproved deliveries while producing three approved but stale values. The contribution is a reproducible account of authorization assumptions, counterexamples, and semantic trade-offs, not a general security guarantee.

## The central argument

A policy decision concerns a representation of a resource. Execution concerns an operating-system object. Protection requires the relationship between those two to survive until the operation occurs.

Let `R(p, t)` denote the object reached by pathname `p` at time `t`, and let `P` be the fixed set of protected file identities. A pathname gate can establish `R(p, t_check) ∉ P`. That observation does not imply `R(p, t_use) ∉ P` when names can change. Phase 5 constructs the missing step directly: the gate approves an ordinary object, the fixture controller changes the name binding, and the later open reaches a protected object.

For an open descriptor `d`, the proposed invariant is narrower: authorization and content I/O refer to the same held object. If `identity(d) ∉ P` at authorization, `P` remains fixed, and the trusted executor retains exclusive control of `d`, subsequent name replacement cannot redirect that descriptor to another object. The executor must avoid reopening the pathname and must defer truncation until after approval. This argument follows established descriptor semantics; the experiment tests the implementation in selected schedules rather than proving all possible executions. See the technical sources in the [protocol](RACE_PROTOCOL.md#technical-basis).

Object continuity does not imply content-version continuity. Let `C(d, t)` be a value read through descriptor `d`. A digest check of `C(d, t1)` cannot authorize `C(d, t2)` if a writer changes the bytes between those reads. Phase 6 keeps the inode constant and exposes exactly that failure. A verified buffer instead checks `H(b) = h*` for the captured value `b` and returns that same value. This conditional argument assumes a trustworthy approved digest, collision resistance, and trusted process memory.

Returning `b` does not imply that `b` equals the current file contents. The latest result separates three properties:

| Property | What the experiment establishes within scope | Remaining distinction |
|---|---|---|
| Object continuity | A held descriptor survives the tested name substitutions. | The object's contents can still change. |
| Approved-version delivery | A validated captured value is the value returned. | Inspection may already have read unapproved bytes. |
| Freshness | Not guaranteed; three approved payloads are stale. | Reauthorization or a different consistency contract is needed. |

## Evidence that changed the design

The [policy dataset](../experiments/cases/v3/README.md) initially provided 45/45 expected-label matches. Its oracle described the checker itself. The [paired replay](REPLAY_FINDINGS.md) then asked about resource effects and required reads: the string gate prevented two protected operations, missed two aliases, and lost two legitimate completions. Safe completion stayed at 4/8. This negative result exposed the gap between a passing policy test and useful protection.

The [resolved-target intervention](GATE_FINDINGS.md) recovered legitimate completion and blocked symlink-mediated protected access in two separately reported eight-task suites. The [identity study](IDENTITY_FINDINGS.md) then changed one assumption: two paths could name the same file through hardlinks. The resolved gate missed both protected hardlinks, while identity checking blocked them. That success depended on topology remaining fixed.

The [replacement study](RACE_FINDINGS.md) challenged that dependency. All four after-check protected substitutions bypassed the identity-path arm. The descriptor arm retained the initial ordinary object through the same substitutions and through benign replacements. Ordinary controls rule out blanket refusal as the explanation for its zero protected content operations. Before-check substitutions distinguish identity authorization from merely holding whichever file was opened.

The [content-version study](CONTENT_FINDINGS.md) then changed bytes without replacing the inode. Identity-only reads returned five unapproved versions; hash/reread returned three; a verified buffer returned none. Both digest arms denied the two changes that preceded capture. All eight cases remained in the delivery denominator: the buffer delivered an approved version in 6/8 cases and an approved but stale version in three. This makes its benefit and limitation visible together. The new delivery rule does not retroactively change the earlier resource-protection oracle.

## Contribution and research judgment

This repository contributes an inspectable experimental progression: a failed assumption, a bounded intervention, and a follow-up that tests the intervention's remaining dependency. It also contributes raw traces, task-level or object-level oracles, prospective protocol freezes, and separate accounting for policy blocks and infrastructure errors.

The security mechanisms themselves are established systems concepts. The project does not claim a new sandbox primitive, a novel discovery of TOCTOU, or an independently evaluated defense against AI agents. Its value lies in making the reasoning testable and in revising claims when the threat model changes.

## Validity and open questions

All cases are curated and visible during development. Related cases are not independent samples. The schedules deterministically arrange check/use ordering; they do not measure concurrent race probability. No confidence interval or population security rate is justified. The arms share controlled fixtures and the earlier descriptor executor; Phase 6 deliberately changes whether the checked value is retained or reread. Its mutations occur before capture or after validation, not during a capture.

The next studies should define legitimate version updates, stale-value handling, and changes during capture before extending the delivery claim. Dynamic protected membership and creation remain separate obligations. Agent integration requires a distinct protocol with model/prompt versions, constrained tools, budgets, repeated task trials, and independent task-correctness assessment.

## Attribution and interpretation

The repository owner directs the project. The commits, logs, and artifacts document what was produced and tested; they do not establish which concepts the owner developed independently or what the owner personally learned.

A portfolio or application account should identify the owner's actual decisions, revisions, explanations, and independent work. [Reflection notes](REFLECTION_NOTES.md) provide evidence-linked prompts without supplying an invented personal narrative. No institutional affiliation, external review, publication, or deployment impact is claimed.
