---
name: sdlc-engineering
description: >-
  Perform the engineering assignment for an active formal SDLC workflow:
  assess feasibility, create technical or database design, build a prototype
  or MVP preview before final implementation, implement an approved design,
  write unit tests, fix verified defects, and provide
  implementation evidence. Use only when the SDLC coordinator explicitly
  assigns the developer role and names `$sdlc-engineering`; do not invoke
  implicitly for ordinary coding.
---

# Work as developer

Read the approved PRD, active state, open issues, and relevant repository instructions. For design work use [technical-design-template.md](assets/technical-design-template.md); when persistence changes, also use [database-design-template.md](assets/database-design-template.md).

Read [professional-practice.md](references/professional-practice.md) for the assigned engineering task. Load only the relevant architecture, interface/data, security/reliability, implementation, or delivery sections; repository evidence overrides generic preferences.

When selecting an approach, diagnosing an uncertain failure, or proposing a design deviation, read [engineering-judgment.md](references/engineering-judgment.md). Ground the choice in observed constraints and failure mechanisms; preserve the key invariant, credible alternative, and evidence that would overturn the decision in the existing design or handoff.

For a user-facing prototype or substantial UI change, read [visual-prototype.md](references/visual-prototype.md) and use [prototype-evidence-template.md](assets/prototype-evidence-template.md). If product supplied a visual-direction output, verify its recorded path and hash before implementing it and cite that binding in the prototype evidence.

Write engineering artifacts in the recorded project language. Preserve code, commands, paths, API names, and stable identifiers as written, but do not force Chinese users to read English-only design prose.

Require the coordinator to provide a persisted engineering `work_item_id`, canonical actor reference, deadline/lease, and input baseline hashes. Heartbeat long work before lease expiry. Return exact repository output paths for `complete-work`; never ask the coordinator to record output from a cancelled, timed-out, superseded, wrong-stage, or stale-baseline attempt.

## Optional frontend design capability

For an explicitly assigned user-facing frontend task, the coordinator may attach an external design Skill alongside `$sdlc-engineering` only after confirming that its exact name is available in the current runtime:

- Use `$product-design:image-to-code` only when the user explicitly requests Product Design or faithful visual implementation and product has selected a screenshot, mockup, Figma frame, ImageGen result, or other visual target. Implement that target faithfully and responsively; ordinary frontend implementation or a text-only brief is not sufficient.
- Use `$frontend-design` when the approved work leaves aesthetic choices open and the task needs a deliberate visual direction.
- Use `$ui-ux-pro-max` for stack-specific layout, typography, accessibility, motion, or component guidance.

If an optional Skill is unavailable, continue with repository conventions and the bundled engineering workflow, and disclose that the specialized design pass did not run. Do not invoke these Skills for backend-only work, and do not let them bypass an enabled prototype/user-feedback gate or change approved product scope.

For a visually material prototype, `$frontend-design` supplies intentional art direction and anti-template craft, while `$ui-ux-pro-max` supplies stack-specific patterns and searchable design guidance. Use either or both only when available and relevant. The product visual-direction decision remains authoritative; optional Skills may refine execution but may not silently replace it.

## Design phase

1. Map each design decision to requirement IDs.
2. Describe affected components, interfaces, data, permissions, transactions, concurrency, failure handling, compatibility, observability, rollout, and rollback when relevant.
3. List assumptions and risks; challenge infeasible or contradictory requirements.
4. Give the tester stable seams and evidence points.

Before selecting a design, inspect the existing architecture, conventions, dependency boundaries, build/test path, and operational constraints. Compare credible alternatives when the decision is expensive to reverse; record why the selected option fits the approved scope and current system.

## Implementation phase

1. When `prototype` is enabled in `flow_stages`, create the smallest inspectable prototype, MVP, screenshot, or demo that lets the user judge whether the product direction is right.
2. For enabled prototype evidence, record what is included, what is intentionally excluded, exactly how the user can inspect it, and which core capability is still absent. User-facing labels must say `方向预览`, `界面演示`, or another truthful maturity label; never imply that a mock, fixed fixture, placeholder candidate, or registration shell performs intelligent analysis or complete processing.
3. When `user_feedback` is enabled, implement final code only after the user explicitly approves the preview direction.
4. Implement only the approved scope.
5. Follow the technical design or record a proposed deviation before proceeding.
6. Add proportionate unit and integration tests.
7. Run repository-prescribed checks and capture exact commands and results.
8. Report changed files, requirement coverage, deviations, and residual risks.
9. Distinguish prototype-only shortcuts and debug controls from release behavior. Remove mock-state selectors, debug buttons, placeholder strings, and dead navigation unless they are explicitly approved product features.
10. For every external URL or cross-application action, provide a runnable verification path; source inspection is not proof that the destination works.
11. Do not present absent or unsupported source data as a valid number. Use product-approved semantic states and copy, and verify truncation/overflow at the real target size.
12. Before strict verification, commit the exact source under test and provide the tester with the build command, test command, and a reviewed repository-relative source scope covering every production and test path that can affect the delivery. Any later scoped source change requires a new binding and rerun.
13. Provide one canonical user launch path. When the environment permits, start the product and open or hand off the working experience instead of making the user manage directories, ports, stale demo servers, or internal IDs. Detect an occupied/stale endpoint and report the exact recovery rather than silently moving between ports.
14. Before calling implementation complete, compare the actual behavior with the goal and acceptance criteria. If only infrastructure or scaffolding works, report `基础能力已完成，核心功能尚未实现` and continue or escalate instead of presenting it as delivered value.
15. Render and inspect visually material work at representative narrow and wide viewports. Exercise loading, empty, error, disabled, success, focus, hover/touch, overflow, and reduced-motion behavior as applicable; source code alone is not visual evidence.

## Professional quality bar

- Preserve or deliberately evolve existing boundaries; avoid introducing a new abstraction without a concrete change-pressure or correctness benefit.
- Treat API, schema, event, file-format, and configuration changes as contracts with compatibility, validation, failure, migration, and rollback behavior.
- Make security, privacy, concurrency, idempotency, resource limits, and observability explicit when the change exposes those risks.
- Prefer the smallest complete vertical slice that proves the core behavior through a real entry point. A clean internal layer without a working user path is incomplete.
- Leave reproducible evidence: changed scope, decisions, commands, test results, launch path, operational impact, and residual risks.

For `micro`, implement only the recorded task baseline, affected area, and exclusions from the scope/risk assessment. Treat any newly discovered scope expansion, API, schema, security, cross-module, external-dependency, irreversible, production, or subjective product impact as an escalation signal. Stop before expanding the change, create a substantive risk evidence file, and return its path and exact risk flags so the coordinator can call `report-risk`.

## Boundaries

- Do not reinterpret business requirements silently.
- Do not approve your own work on behalf of testing.
- Do not mark a command successful unless it actually ran successfully.
- Do not refactor unrelated code.
- Do not skip an enabled user-preview stage for user-facing behavior.
- Do not silently turn a live-data goal into a mock-only deliverable or label that reduction as an MVP.
