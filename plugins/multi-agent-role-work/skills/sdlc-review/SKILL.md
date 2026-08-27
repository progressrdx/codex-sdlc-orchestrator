---
name: sdlc-review
description: Review a formal SDLC gate from an explicitly assigned product, engineering, or testing perspective and return an evidence-based approve or reject verdict with tracked findings. Use only when the SDLC coordinator explicitly names `$sdlc-review` for `prd_review`, `readiness_review`, or `acceptance`; never invoke implicitly for ordinary code review.
---

# Review a gate independently

Read [gate-criteria.md](references/gate-criteria.md), the active state, all gate inputs, and unresolved issues. Use [review-record-template.md](assets/review-record-template.md) for the result.

Read the assigned role section and current gate section in [role-review-lenses.md](references/role-review-lenses.md). Apply both lenses: the role section defines what expertise you contribute, while the gate section defines what must be proven now. Do not load another role's conclusions or coordinate verdicts before submitting your own.

When evidence is incomplete or conflicting, or a disputed design requires adjudication, read [review-judgment.md](references/review-judgment.md). Distinguish stage-appropriate proof, a real requirement violation, and a reviewer's preference; identify the smallest evidence or authorized correction that could change the verdict.

Write the review in the recorded project language while retaining required machine identifiers for gate, role, verdict, work item, and evidence. The evidence must contain exactly one standalone `review_verdict: approve|reject` line; Chinese documents may instead use `评审结论: approve|reject`. Its value must match the verdict submitted to the workflow tool. Do not express the machine verdict as prose, a Markdown choice, or a negated phrase.

The coordinator must provide the persisted review `work_item_id`, its canonical `actor_ref`, deadline, and current baseline hashes. Heartbeat before the lease expires. Return the exact review path so the coordinator can `complete-work` with output name `review:<gate>:<role>`; a verdict from an expired, cancelled, superseded, wrong-stage, or stale-baseline attempt is rejected.

Review only gates present in the state's enabled `flow_stages`. Do not create missing ceremonies for `micro` or conditionally skipped quick stages. If evidence reveals a risk inconsistent with the selected mode, reject the transition, create a substantive risk evidence record, and return the exact flags and path so the coordinator can call `report-risk`.

## Review rules

1. Review only from the assigned role perspective.
2. Cite requirement IDs, artifact sections, file paths, commands, or test results for every material finding.
3. Classify findings as `blocker`, `major`, or `minor`.
4. Distinguish a missing decision from a defect.
5. Return exactly one verdict: `approve` or `reject`.
6. Reject when any blocker is present or required evidence is absent.
7. Do not coordinate conclusions with the other reviewers before submitting the independent verdict.
8. Reject any attempt to convert a confirmed core goal or Must criterion to deferred, replaced, mock-only, or not applicable without a matching user-approved scope-change record.
9. At acceptance, bind the review to the recorded source revision and final journey report. Reject stale verification, post-test source edits, untested links, semantically wrong content, visible placeholders/debug controls, or a goal-level outcome that is not satisfied.
10. Do not approve merely because every required document exists. Compare the working behavior and final-journey evidence with the user's goal; reject a scaffold, mock, registration shell, or deterministic demo presented as completed core value.
11. Challenge internally consistent but weak evidence: trace claims to the current baseline, distinguish assertions from observations, and identify the smallest missing proof that would change the verdict.

Return the material position, evidence, disagreements, required actions, structured findings (`severity`, `owner`, `summary`), verdict, work-item ID, and canonical task/session reference. Reject requires at least one finding; approve must not retain a blocker or major finding. The coordinator records the exact completed output and reference, then uses the atomic gate bundle's inline meeting for material cross-role decisions.
