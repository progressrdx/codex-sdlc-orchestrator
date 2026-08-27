# Role-specific review lenses

Use the assigned role lens and the active gate lens together. These lenses guide independent judgment; they do not replace concrete citations or the verdict rules in the main Skill.

## Product lens

Test whether the baseline preserves the user's intended outcome:

- problem, actor, outcome, scope, non-goals, and assumptions are coherent;
- Must priorities reflect goal necessity rather than stakeholder preference or implementation convenience;
- workflows, states, permissions, business rules, data meaning, failures, and recovery are unambiguous where relevant;
- metrics measure user value and guardrails rather than activity;
- acceptance criteria prove meaningful semantics through the real journey;
- prototypes, mocks, dependencies, costs, privacy, and limitations are represented truthfully;
- no goal or Must behavior was silently deferred, weakened, or replaced.

Product rejects unresolved policy decisions, contradictory outcomes, unobservable success, and a technically working result that does not deliver the promised user value.

For materially visual work, product also checks that the surface type, primary task, information hierarchy, complete state set, selected direction, and remaining subjective choices are explicit. Visual polish must not hide missing product behavior or fabricated content.

## Engineering lens

Test whether the baseline can be built and operated safely:

- proposed boundaries fit the current system and avoid unjustified complexity;
- interfaces, schemas, events, configuration, validation, errors, and compatibility are explicit;
- security/privacy, concurrency, idempotency, failure isolation, resource limits, and observability are addressed where exposed;
- migration, deployment, rollback, and external dependency behavior are credible;
- implementation evidence covers the actual changed surface and current source;
- deviations and residual technical risks are visible;
- the canonical launch path exercises the real integrated behavior.

Engineering rejects infeasible or contradictory scope, missing high-impact failure design, unsafe irreversible change, stale source evidence, and scaffolding presented as complete behavior.

For materially visual work, engineering also checks the direction path/hash binding, design-system consistency, state completeness, responsive behavior, accessibility implementation, rendered evidence, and whether optional design guidance changed approved product decisions.

## Testing lens

Test whether the claim is independently falsifiable and sufficiently proven:

- each Must criterion has a clear oracle and proportionate risk coverage;
- boundaries, negative cases, state transitions, permissions, failures, recovery, compatibility, and regression are covered where material;
- environment, data, commands, source/build identity, expected result, actual result, and evidence are reproducible;
- the real user entry point and core goal journey were executed;
- semantic correctness is proven beyond status codes, rendering, snapshots, or mocks;
- blocked and flaky checks are not counted as passes;
- unresolved defects and untested exposure are reflected honestly in the verdict.

Testing rejects missing or stale evidence, an untestable criterion, an unexecuted core journey, a blocker, or residual risk above the accepted threshold.

For materially visual work, testing also checks the actual rendered build at representative viewports and states, separates objective defects from aesthetic preference, and requires screenshot/browser evidence for visual claims.

## PRD review lens

Review completeness of decisions rather than document volume. Locate contradictions, hidden assumptions, untestable wording, absent failure behavior, and dependencies that change the product promise. Require enough clarity to design and test without inventing policy.

## Readiness review lens

Review whether the proposed design and test strategy jointly cover every Must outcome and material risk. Require stable verification seams, safe migration/rollback where needed, a credible real launch path, and an explicit disposition for unresolved decisions.

## Acceptance lens

Review only current implementation and evidence. Trace every confirmed goal and Must criterion to the exact source/build and user-journey result. Check semantic quality, visible limitations, compatibility, operations, and unresolved defects. Artifacts describing intended behavior cannot substitute for observed behavior.
