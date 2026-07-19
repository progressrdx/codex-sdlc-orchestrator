---
name: sdlc-review
description: Review a formal SDLC gate from an explicitly assigned product, engineering, or testing perspective and return an evidence-based approve or reject verdict with tracked findings. Use only when the SDLC coordinator explicitly names `$sdlc-review` for `prd_review`, `readiness_review`, or `acceptance`; never invoke implicitly for ordinary code review.
---

# Review a gate independently

Read [gate-criteria.md](references/gate-criteria.md), the active state, all gate inputs, and unresolved issues. Use [review-record-template.md](assets/review-record-template.md) for the result.

## Review rules

1. Review only from the assigned role perspective.
2. Cite requirement IDs, artifact sections, file paths, commands, or test results for every material finding.
3. Classify findings as `blocker`, `major`, or `minor`.
4. Distinguish a missing decision from a defect.
5. Return exactly one verdict: `approve` or `reject`.
6. Reject when any blocker is present or required evidence is absent.
7. Do not coordinate conclusions with the other reviewers before submitting the independent verdict.

Return the material position, evidence, disagreements, required actions, and verdict in a form the coordinator can summarize without inventing discussion. The coordinator, not the reviewer, creates the cross-role meeting notes and records the final state transition.
