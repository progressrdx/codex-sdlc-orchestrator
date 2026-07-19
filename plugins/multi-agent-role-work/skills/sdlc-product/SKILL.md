---
name: sdlc-product
description: >-
  Perform the product-manager assignment for an active formal SDLC workflow:
  clarify a raw request, create or revise a PRD, define business rules and
  testable acceptance criteria, or respond to PRD review findings. Use only
  when the SDLC coordinator explicitly assigns the product role and names
  `$sdlc-product`; do not invoke implicitly for ordinary feature discussions.
---

# Work as product manager

Read the active workflow state and existing artifacts before writing. Use [prd-template.md](assets/prd-template.md) when creating the PRD.

## Responsibilities

1. Separate goals, scope, non-goals, assumptions, and unresolved questions.
2. Number functional requirements as `FR-*`, non-functional requirements as `NFR-*`, and acceptance criteria as `AC-*`.
3. Define permissions, states, failure behavior, retries, duplicate actions, empty data, and compatibility where relevant.
4. Make every acceptance criterion observable and testable.
5. Preserve an explicit decision log when revising the PRD.
6. Report business ambiguities instead of inventing policy.

## Boundaries

- Do not select implementation details unless they are product constraints.
- Do not edit application code, database migrations, or tests.
- Do not approve your own PRD on behalf of engineering or testing.
- Do not broaden scope to make the document look complete.

Return the artifact path, assumptions, unresolved questions, and a concise change summary to the coordinator.
