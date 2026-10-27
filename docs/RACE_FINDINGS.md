# Phase 5 findings: the object checked must be the object used

**Follow-up:** [Phase 6](CONTENT_FINDINGS.md) holds the inode constant while changing its bytes. It tests approved-version delivery, a different contract from the resource-identity claim evaluated here. Original counts and artifacts are retained.

**Study:** ten deterministic pathname-replacement cases, three arms, 30 records.

**Run:** 2026-10-26 (Asia/Seoul); result filenames use UTC.

## Finding

The Phase 4 identity gate fails when an approved pathname changes before the executor opens it. A descriptor-bound executor preserves the authorized ordinary object in the tested after-check replacements, and denies protected objects substituted before authorization. This is evidence about a specific mechanism under controlled schedules.

| Outcome | Baseline | Identity-path gate | Descriptor-bound executor |
|---|---:|---:|---:|
| Protected content operations / attack schedules | 6/6 | 4/6 | 0/6 |
| Protected content-I/O attempts | 6 | 4 | 0 |
| Original-object completion / eligible cases | 2/8 | 2/8 | 8/8 |
| Benign blocks / benign cases | 0/4 | 0/4 | 0/4 |
| Gate blocks | 0 | 2 | 2 |
| Protected opens | 6 | 4 | 2 |
| Infrastructure errors | 0 | 0 | 0 |

Each arm has ten cases. Six introduce protected substitutions; eight assess original-object completion because the original file is available at authorization. These sets overlap. The two before-check substitutions are excluded from the completion denominator by the frozen protocol, not removed after observing failure. Access counts refer to the evaluated executor; fixture setup and trusted oracle inspections are excluded.

## Mechanism by condition

| Condition, two cases each | Baseline | Identity-path gate | Descriptor-bound executor |
|---|---|---|---|
| Ordinary controls | Original object used | Original object used | Original object used |
| Protected hardlink before check | Protected read/write | Both blocked before open | Both opened, then denied before content I/O |
| Protected hardlink after check | Protected read/write | Protected read/write | Original object used |
| Protected parent symlink after check | Protected read/write | Protected read/write | Original object used |
| Benign replacement after check | Replacement object used | Replacement object used | Original object used |

The benign-replacement condition makes object continuity visible even without a protected resource. Under this protocol, operating on the new ordinary object does not satisfy the original-object goal. A different product could intentionally prefer the latest pathname binding; that is a separate semantic choice and should not be described as a security failure here.

## Why the comparison is informative

The unchanged `IdentityAwareGate` inspects the current pathname identity and then relinquishes control to an executor that opens that pathname. The controller replaces a leaf hardlink or a parent directory after approval. The open reaches a different identity, so the earlier check no longer governs the operation.

`DescriptorExecutor` opens without `O_TRUNC` or `O_CREAT`, checks regular-file type and protected identity with `fstat`, and performs I/O through the held descriptor. A later name replacement cannot redirect that open object. Truncation occurs only after approval. Metadata errors raise an infrastructure failure rather than an allow decision.

The oracle records the identity of the descriptor actually used for I/O, a retained hardlink witness to the original ordinary object, and protected-file bytes. It does not classify risk from the pre-check path. The protected identity is obtained from a separately held oracle descriptor and is not passed to the gate. Both oracle and gate still share the operating system's identity semantics; this is not an independently implemented filesystem model.

## Evidence and reproduction

The [protocol](RACE_PROTOCOL.md) and [ten-case manifest](../experiments/tasks/race-eval-v1/tasks.json) were committed at [`d0ddc20`](https://github.com/hylen707/AI-agentic-Code-Guardian-Cybersecurity/commit/d0ddc20aac99365adb85bc48ef53539c8028a127) before implementation. They remain unchanged. The implementation was developed against these visible mechanisms, so the freeze is prospective, not blind.

- [Raw case/arm records](../experiments/results/2026-10-26T08-23-21-637204Z-race-v1.jsonl)
- [Summary, criteria, environment, commands, and hashes](../experiments/results/2026-10-26T08-23-21-637204Z-race-v1-summary.json)
- [Complete unit-test transcript](../experiments/results/2026-10-26T08-23-21-637204Z-race-v1-unit-tests.txt)
- [Artifact verification](../experiments/results/2026-10-26T08-23-21-637204Z-race-v1-verification.json)

```bash
python -m unittest discover -s tests -v
python experiments/run_race_comparison.py --dataset experiments/tasks/race-eval-v1/tasks.json --base-commit 1829252dfc7421511f9d6c4aa1d49a0eb9f57ec0 --freeze-commit d0ddc20aac99365adb85bc48ef53539c8028a127
```

All 55 unit tests passed, including 11 new tests for descriptor lifetime, denied-write preservation, metadata failure, parent replacement, partial writes, special-file rejection, manifest validation, and failed-I/O accounting. The experiment exited 0; all seven prespecified summary criteria held. Exit 0 denotes absence of infrastructure errors and is distinct from the scientific criteria.

## Limits and next test

The descriptor arm's zero protected content operations coexists with **two protected opens** for metadata authorization. The implementation does not enforce a no-open policy. Only existing regular-file reads and writes were evaluated. The controller changes names at fixed boundaries; there are no concurrent threads, timing estimates, dynamic protected membership, hostile devices, mount changes, or live-agent tasks.

Descriptor binding retains an object, not an immutable version of its contents. The next protocol should vary content or policy membership while holding identity constant, and define the desired behavior before implementation. General directory confinement and creation require additional OS-level design. Earlier fixed-topology results remain valid within their original assumptions; this study narrows how far they can be extended.
