# Gate criteria

## PRD review

- Product: goals, scope, business rules, decisions, and acceptance criteria are coherent; strict core goals faithfully preserve the user's confirmed outcome.
- Engineering: requirements are feasible, non-contradictory, bounded, and specific enough to design.
- Testing: acceptance criteria are observable; boundaries, permissions, failures, and state behavior are testable.
- All roles: user confirmation exists, no material clarification gap remains hidden in assumptions, and no core outcome was silently reduced to a prototype or mock.

## Readiness review

- Product: design preserves approved intent and does not reduce a core goal; any proposed reduction has explicit user-approved scope-change evidence.
- Engineering: design covers interfaces, data, failure behavior, compatibility, rollout, and identified risks as applicable.
- Testing: test plan traces every acceptance criterion and the design exposes enough evidence to verify it.
- All roles: if preview is enabled, the next step is a prototype or MVP suitable for user feedback; otherwise the risk assessment contains a credible reason that preview is unnecessary.

## Acceptance

- Product: each confirmed core goal has a current satisfied outcome, or a matching explicit user-approved scope change.
- Engineering: implementation matches design; checks, deviations, migration, and rollback evidence are complete.
- Testing: every Must criterion has an independent current-source verdict; the final user journey passes launch, core outcomes, semantic content, interactions, external links, UI quality, release hygiene, and source-of-truth checks; no blocker remains.
- Engineering: the reviewed source fingerprint matches the committed revision under test; no post-verification source change is hidden.
- All roles: when preview was enabled, user feedback was explicitly approved or requested changes were incorporated and re-reviewed.
