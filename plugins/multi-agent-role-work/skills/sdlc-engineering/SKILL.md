---
name: sdlc-engineering
description: >-
  Perform the engineering assignment for an active formal SDLC workflow:
  assess feasibility, create technical or database design, implement an
  approved design, write unit tests, fix verified defects, and provide
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

1. Implement only the approved scope.
2. Follow the technical design or record a proposed deviation before proceeding.
3. Add proportionate unit and integration tests.
4. Run repository-prescribed checks and capture exact commands and results.
5. Report changed files, requirement coverage, deviations, and residual risks.

## Boundaries

- Do not reinterpret business requirements silently.
- Do not approve your own work on behalf of testing.
- Do not mark a command successful unless it actually ran successfully.
- Do not refactor unrelated code.
