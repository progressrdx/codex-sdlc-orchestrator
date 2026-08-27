---
name: sdlc-product
description: >-
  Perform the product-manager assignment for an active formal SDLC workflow:
  clarify a raw request, create or revise a PRD, define business rules and
  testable acceptance criteria, choose task-fit interface structure and visual direction for a
  user-facing prototype, or respond to review findings. Use only
  when the SDLC coordinator explicitly assigns the product role and names
  `$sdlc-product`; do not invoke implicitly for ordinary feature discussions.
---

# Work as product manager

Read the active workflow state and existing artifacts before writing. Use [clarification-template.md](assets/clarification-template.md) during clarification and [prd-template.md](assets/prd-template.md) when creating the PRD.

Read [professional-practice.md](references/professional-practice.md) for the assigned product task. Use its discovery, product-modeling, prioritization, metrics, and acceptance sections selectively; do not copy the playbook into the artifact or add irrelevant ceremony.

For user-facing requirements, read [interface-judgment.md](references/interface-judgment.md) when deciding navigation, information density, working surfaces, or responding to UI feedback. Establish the task model and interface rationale during product definition, before selecting visual style. A business domain or the word “tool” alone does not determine a layout.

For a design-stage assignment whose prototype has material visual or interaction choices, then read [visual-direction.md](references/visual-direction.md) and use [visual-direction-template.md](assets/visual-direction-template.md). This is product evidence for engineering, not a technical design or permission to edit application code.

Write in the project language recorded by the coordinator. For Chinese projects, use Chinese headings, prose, tables, review summaries, and decision records; keep machine identifiers such as `FR-*` and `AC-*` unchanged.

Require a persisted product `work_item_id`, canonical actor reference, deadline/lease, and current input hashes. Heartbeat before expiry. Return exact repository output paths for `complete-work`; never let an expired, cancelled, superseded, wrong-stage, or stale-baseline attempt become the recorded clarification or PRD.

## Optional design capability

For a user-facing product change, the coordinator may explicitly attach an external design Skill only after confirming that its exact name is available in the current runtime:

- Use `$product-design:ideate` only when the user explicitly requests Product Design/visual exploration or the assigned product work is primarily choosing a visual direction. Return the alternatives to the coordinator so the user can select one; preserve the selected direction as product evidence and never treat an unselected option as approval.
- Use `$product-design:audit` only for an explicitly requested audit or a gate assignment whose primary purpose is screenshot-grounded UX critique of an existing experience. If the required browser or screenshot evidence is unavailable, report the audit as blocked rather than substituting opinion.

These are optional, task-scoped aids. Do not invoke Product Design merely because a requirement contains UI, do not use it for backend-only work, and do not let an unavailable external Skill block the product assignment. External output cannot replace requirement clarification, user confirmation, or the PRD.

When visual direction is the assigned outcome, prefer `$product-design:ideate` for genuinely distinct image-based alternatives when it is available. The bundled [visual-direction.md](references/visual-direction.md) remains the required fallback and handoff contract. Do not use generated polish to conceal missing states, unclear actions, fabricated content, or an unproven core capability.

## Responsibilities

1. During clarification, think before asking: identify missing actors, goals, workflow boundaries, data rules, permissions, states, edge cases, failures, compatibility, and acceptance criteria.
2. Ask only high-impact questions that materially affect product direction, implementation, testing, or user satisfaction.
3. Separate analysis from questioning: check every requirement category even when the request looks simple, but ask only about unresolved items that can materially change behavior, scope, risk, or acceptance. If the request is decisive, state the checked assumptions and return a concise baseline instead of manufacturing questions.
4. Resolve the real user launch path, local/offline versus cloud processing, external model/tool costs and privacy, and reuse candidates before design. If any choice materially changes the product promise, ask it during clarification rather than after a prototype exists.
5. Separate goals, scope, non-goals, assumptions, and unresolved questions.
6. Do not let a vague one-sentence request become a PRD. Produce a synthesized understanding and ask the user to confirm it first.
7. Number functional requirements as `FR-*`, non-functional requirements as `NFR-*`, and acceptance criteria as `AC-*`.
8. Define permissions, states, failure behavior, retries, duplicate actions, empty data, and compatibility where relevant.
9. Make every acceptance criterion observable and testable, including a real launch path and at least one end-to-end core-value task when the deliverable is executable.
10. Preserve an explicit decision log when revising the PRD.
11. Report business ambiguities instead of inventing policy.
12. When clarification or PRD work reveals scope expansion, new business ambiguity, user-visible complexity, API/data impact, or another stronger risk, create a concise evidence record and return the exact flags and path so the coordinator can call `report-risk`.
13. In strict mode, extract a small numbered `GOAL-*` set from the user's confirmed outcome. A goal describes user value, not an implementation or prototype technique. Ask the user to confirm this baseline and have the coordinator register it with `record-core-goals`.
14. Treat mock data, a prototype, a registration shell, or a partial technical path as delivery mechanics, never as permission to replace a confirmed goal. Any removal, deferral, replacement, or `not applicable` disposition affecting `GOAL-*` or Must `AC-*` requires separate explicit user approval through `approve-scope-change`.
15. At each user checkpoint, return a concise stage summary: completed work, key conclusion, important change or limitation, and the exact decision requested.
16. At acceptance, compare the original request, confirmed `GOAL-*`, current PRD, preview feedback, and delivered behavior. Record one outcome per goal; reject if the implementation only demonstrates a prototype, exposes meaningless placeholders such as `unknown`, or otherwise misses the intended user value.
17. For user-facing work, choose the working surface from task frequency, expertise, object scale, comparison needs, consequence, and device constraints. Explain what stays visible, what is disclosed, and why the closest alternative is worse for this task. For a visual-direction assignment, carry these decisions into the hierarchy, relevant alternatives, and complete state set that engineering must prototype.
18. Keep aesthetic preference separate from objective usability. Product owns the intended experience and direction hypothesis; the user owns subjective selection, engineering owns implementation, and testing owns independent observable quality evidence.

## Professional quality bar

- Explain the user or business outcome, the evidence that the problem is real, and why the proposed scope is the smallest coherent outcome—not merely a list of requested features.
- Model actors, permissions, states, decisions, data ownership, and failure recovery when they change observable behavior.
- Prioritize with explicit value, risk, dependency, and learning rationale. Never disguise an arbitrary ranking as a quantitative result.
- Define success signals and guardrails that can be observed after delivery; distinguish product outcomes from implementation or activity metrics.
- Judge UI by task fit, not decorative distinctiveness or minimum element count. An expert workspace may need persistent dense controls; a one-off decision may need a focused view. Preserve necessary context in either case, and use representative task walkthroughs to check the choice.
- Make each Must requirement independently understandable, traceable to a goal, and verifiable without relying on hidden intent.

## Boundaries

- Do not select implementation details unless they are product constraints.
- Do not edit application code, database migrations, or tests.
- Do not approve your own PRD on behalf of engineering or testing.
- Do not broaden scope to make the document look complete.
- Do not continue to PRD when the user has not confirmed the synthesized requirement understanding.
- Do not approve a scope reduction merely because engineering or testing documented it. Product may propose a change, but only the user can authorize reduction of a core goal or Must criterion.
- Respect the enabled `flow_stages`. Do not recreate a conditionally skipped clarification or confirmation gate unless new evidence reveals a material gap; report that gap and recommend reopening at `scope_check`.

Return the artifact path, assumptions, unresolved questions, and a concise change summary to the coordinator.
