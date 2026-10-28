# Documentation benchmark and application

**Reviewed:** 2026-10-29 (Asia/Seoul), against CodeGuardian main at `2786dd9699dc526f8e9bbea9ac3b907a326af74d`.

This review compares documentation responsibilities and verification paths. Reference projects differ in purpose and maturity; their documentation does not validate CodeGuardian's methods or results. Sources below are official project pages viewed on the review date, using mutable main/site URLs rather than archived snapshots.

## Reference observations and application decisions

| Reference and inspected location | Observed pattern | Application to CodeGuardian |
|---|---|---|
| [SWE-bench README](https://github.com/SWE-bench/SWE-bench#readme): overview, setup, usage, and output locations | Connects the research task to installation, an evaluation command, and paths for logs and run summaries. Detailed evaluation instructions are linked separately. | Put a minimal runnable path early in the README. Name expected records, output directory, and summary checks next to the command; keep full commands in the experiment guide. |
| [Inspect README](https://github.com/UKGovernmentBEIS/inspect_ai#readme) and [official documentation](https://inspect.aisi.org.uk/): introduction and navigation | The README introduces the framework and directs readers to documentation. The guide separates basics, components, running, and analysis, with additional reference material. | Add a docs index with routes for understanding, reproducing, implementing, and auditing. Assign the argument, commands, artifact lookup, and limits to named documents. |
| [NVIDIA garak README](https://github.com/NVIDIA/garak#readme): installation, examples, and result interpretation | Explains the scanner's purpose and usage, then explains output counts, failures, errors, and detailed JSONL logging. | State each metric's unit and denominator. Distinguish policy denial, infrastructure failure, protected opens, content I/O, approved delivery, and freshness. |
| [CyberGym README](https://github.com/sunblaze-ucb/cybergym#readme): setup and evaluation; links to FAQ and submission guidance | Separates environment/data setup from evaluation and result verification, while pointing readers to documents on setup interpretation and reporting. | Make environment assumptions, trusted components, case visibility, and limits easy to find. Link protocols/manifests to raw records and summaries rather than presenting an unsupported aggregate score. |

These applications are editorial judgments drawn from the observed structures. No upstream prose, artwork, or code is copied. Leaderboards, paper badges, package-install instructions, publication claims, license badges, and external-review signals are not inferred from the reference projects.

## Diagnosis of the previous documentation

The prior README already states a coherent question, reports counterexamples, discloses assistance, and preserves important distinctions. Its weakness is navigation and repetition, not an absence of research content. It repeats the progression in the opening table, stage narratives, methodology, evidence trail, and latest-study sections; the first runnable command appears late. The flat docs directory lacks its own entry point, and a reviewer must open several findings pages to locate all case/arm evidence.

The old reproduction examples also pass historical starting-commit labels to a current checkout. The runners record those arguments without verifying the checkout. That can mislead a reader about the files actually executed even though source hashes remain available.

| Responsibility | Resulting location | Review criterion |
|---|---|---|
| Purpose, contribution, representative results, and first run | [Root README](../README.md) | A new reader can find the question, scope, command, expected output, and next document without reading the entire study history. |
| Navigation and document ownership | [Docs index](README.md) | Every research document is reachable by purpose or stage. |
| Cross-stage result and artifact lookup | [Evidence map](EVIDENCE.md) | Each stage has conditions, denominators, raw records, summaries, and bounded interpretation. |
| Adversarial actions, trust, and untested obligations | [Threat model and limits](LIMITATIONS.md) | Controlled capabilities and assumptions are explicit; failure cases remain visible. |
| Execution and provenance | [Experiment guide](../experiments/README.md) | Current reruns record the checked-out revision; historical metadata stays in historical evidence. |
| Detailed argument and metric definitions | [Research statement](RESEARCH_STATEMENT.md), [study map](EXPERIMENT_PLAN.md), and existing findings | Existing reasoning remains available without duplicating every paragraph in the README. |

## Evidence preservation and validation

Documentation changes do not constitute a new research phase. Frozen protocols, measured case manifests, implementation, tests, and historical result files are preserved byte-for-byte against the reviewed base. Dated history receives new entries rather than revised past claims.

Validation results are recorded in the [changelog](CHANGELOG.md) after execution. The review checks local Markdown destinations and heading fragments, recounts historical summaries, verifies recorded source/task hashes, and runs the documented experiments and existing unit tests. A successful rerun checks reproducibility of these cases; it does not expand the threat model or supply an independent evaluation.
