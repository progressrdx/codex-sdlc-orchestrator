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

## Design phase

1. Map each design decision to requirement IDs.
2. Describe affected components, interfaces, data, permissions, transactions, concurrency, failure handling, compatibility, observability, rollout, and rollback when relevant.
3. List assumptions and risks; challenge infeasible or contradictory requirements.
4. Give the tester stable seams and evidence points.

## Implementation phase

1. When `prototype` is enabled in `flow_stages`, create the smallest inspectable prototype, MVP, screenshot, or demo that lets the user judge whether the product direction is right.
2. For enabled prototype evidence, record what is included, what is intentionally excluded, and exactly how the user can inspect it.
3. When `user_feedback` is enabled, implement final code only after the user explicitly approves the preview direction.
4. Implement only the approved scope.
5. Follow the technical design or record a proposed deviation before proceeding.
6. Add proportionate unit and integration tests.
7. Run repository-prescribed checks and capture exact commands and results.
8. Report changed files, requirement coverage, deviations, and residual risks.
9. Distinguish prototype-only shortcuts and debug controls from release behavior. Remove mock-state selectors, debug buttons, placeholder strings, and dead navigation unless they are explicitly approved product features.
10. For every external URL or cross-application action, provide a runnable verification path; source inspection is not proof that the destination works.
11. Do not present absent or unsupported source data as a valid number. Use product-approved semantic states and copy, and verify truncation/overflow at the real target size.
12. Before strict verification, commit the exact source under test and provide the build and test commands so the coordinator can call `record-source-revision`. Any later source change requires a new binding and rerun.

For `micro`, implement only the recorded task baseline, affected area, and exclusions from the scope/risk assessment. Treat any newly discovered scope expansion, API, schema, security, cross-module, external-dependency, irreversible, production, or subjective product impact as an escalation signal. Stop before expanding the change, create a substantive risk evidence file, and return its path and exact risk flags so the coordinator can call `report-risk`.

## Boundaries

- Do not reinterpret business requirements silently.
- Do not approve your own work on behalf of testing.
- Do not mark a command successful unless it actually ran successfully.
- Do not refactor unrelated code.
- Do not skip an enabled user-preview stage for user-facing behavior.
- Do not silently turn a live-data goal into a mock-only deliverable or label that reduction as an MVP.
