---
name: sdlc-review
description: Review a formal SDLC gate from an explicitly assigned product, engineering, or testing perspective and return an evidence-based approve or reject verdict with tracked findings. Use only when the SDLC coordinator explicitly names `$sdlc-review` for `prd_review`, `readiness_review`, or `acceptance`; never invoke implicitly for ordinary code review.
---

# Review a gate independently

Read [gate-criteria.md](references/gate-criteria.md), the active state, all gate inputs, and unresolved issues. Use [review-record-template.md](assets/review-record-template.md) for the result.

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

Return the material position, evidence, disagreements, required actions, structured findings (`severity`, `owner`, `summary`), verdict, work-item ID, and canonical task/session reference. Reject requires at least one finding; approve must not retain a blocker or major finding. The coordinator records the exact completed output and reference, then uses the atomic gate bundle's inline meeting for material cross-role decisions.
