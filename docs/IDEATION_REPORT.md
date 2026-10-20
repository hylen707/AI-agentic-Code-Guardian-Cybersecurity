# CodeGuardian — Ideation Report

**Status:** initial draft; revise as the project develops  
**Last updated:** 2026-10-20

## 1. Project idea
CodeGuardian explores whether a lightweight runtime monitor can help identify and block risky actions proposed by an AI coding agent, while still allowing ordinary software-development tasks to proceed.

## 2. Research question
Can a lightweight runtime monitor reduce risky actions by an AI coding agent without substantially reducing completion of legitimate tasks in a controlled test environment?

## 3. Motivation
AI coding agents may propose actions that change files or invoke tools. A project can benefit from a separate policy layer that checks an action before it is allowed. This project will examine that idea in a small, controlled setting rather than making claims about all real-world agents.

## 4. Threat model and scope
**In scope**
- Synthetic action proposals such as reading or editing a project-owned test file.
- Clearly labeled risky proposals, such as attempting to access a path outside the temporary project directory.
- A monitor that classifies actions as allowed or blocked and records the decision.
- Evaluation on a predefined set of harmless test cases.

**Out of scope**
- Testing against real users, school computers, or production systems.
- Collecting passwords, tokens, or personal data.
- Connecting to external networks or services.
- Running destructive or arbitrary shell commands.
- Claiming the monitor secures all AI agents or prevents every attack.

## 5. Proposed method
1. Define a small action schema and an explicit allowlist.
2. Create a fixed dataset of synthetic safe and risky action records.
3. Run each case without the monitor to establish a baseline where meaningful.
4. Run the same cases through the monitor.
5. Save each input, decision, reason, and outcome.
6. Calculate the measures defined in `EXPERIMENT_PLAN.md`.
7. Discuss both successful blocks and incorrect blocks.

## 6. Measures
- Risky-action block rate.
- False-positive rate on legitimate actions.
- Completion rate for legitimate tasks.
- Optional decision latency.

All measures must include raw counts and the exact test-set size.

## 7. Expected contribution
The intended contribution is a reproducible small-scale demonstration of a runtime policy-checking approach and an honest analysis of its trade-offs. This is a proposed outcome, not a result established by the current draft.

## 8. Limitations
A small synthetic dataset cannot establish how well the approach performs against real AI coding agents or unseen attacks. Rule-based monitoring may miss risks that are not represented in the test cases and may block legitimate work. Test-set design and the chosen rules may bias the result.

## 9. Results
**Not available yet.** Complete this section only after running the planned experiments.
- Number of safe cases: TBD
- Number of risky cases: TBD
- Risky actions blocked: TBD
- False positives: TBD
- Legitimate tasks completed: TBD
- Notable failure cases: TBD

## 10. References
Add the actual sources read and used. For each source, record its title, author or organization, publication date where available, URL, and the specific idea it informed. Do not list sources that were not consulted.

## 11. Personal reflection — complete later
- What assumption did I make at the start?
- Which design choice was hardest, and what evidence informed it?
- What failed or surprised me?
- How did I change the project after seeing evidence?
- What would I investigate next, and why?
