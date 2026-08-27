# Engineering professional practice

Use only the sections relevant to the assigned design, implementation, defect, or delivery task. Existing repository instructions and observed behavior take precedence over generic patterns.

## Repository and change diagnosis

- Establish the real entry point, affected components, dependency direction, build/test commands, configuration sources, runtime boundaries, and existing patterns before proposing change.
- Trace the behavior from external input to observable output. Identify ownership of validation, state mutation, side effects, and error translation.
- Inspect nearby tests, migrations, compatibility adapters, feature flags, telemetry, and deployment assumptions. Distinguish confirmed facts from hypotheses.
- Define the change surface and invariants that must remain true. Avoid unrelated cleanup unless it is required for correctness or testability.

## Architecture decisions

For decisions that are costly to reverse, compare credible options using requirement fit, consistency with current architecture, failure isolation, operability, security/privacy, migration cost, testability, and reversibility. Prefer a simple local change when it satisfies the same invariants.

Record:

- context and forces;
- selected option and rejected alternatives;
- affected contracts and dependencies;
- failure modes and operational consequences;
- migration/rollback strategy;
- evidence that will validate the decision.

Do not introduce a service, queue, cache, framework, repository layer, generic abstraction, or asynchronous flow solely because it is fashionable or hypothetically reusable.

## Contracts and data

- Specify inputs, outputs, validation, authorization, error taxonomy, timeouts, retries, idempotency, ordering, pagination, versioning, and compatibility as applicable.
- For state changes, identify transaction boundary, invariants, concurrent writers, duplicate delivery, partial failure, reconciliation, and audit needs.
- For schema changes, plan expand/migrate/contract when zero-downtime compatibility matters. Define backfill batching, restartability, monitoring, and rollback limitations.
- Treat events, files, environment variables, command-line options, and database schemas as contracts—not only HTTP APIs.
- Never fabricate absent data. Model unknown, unavailable, stale, redacted, and not-applicable states explicitly when users can observe them.

## Security, privacy, and reliability

Apply proportionately when the boundary exists:

- authentication versus authorization; least privilege; tenant/resource ownership;
- input trust, injection, path traversal, unsafe deserialization, secret exposure, and sensitive logging;
- data minimization, retention, deletion, encryption boundary, external processing, and consent;
- timeout budgets, bounded retry with jitter, circuit breaking, backpressure, resource limits, cancellation, and graceful degradation;
- deterministic idempotency and replay behavior for side effects;
- actionable logs/metrics/traces with correlation and without sensitive payload leakage.

Report newly discovered security/privacy, irreversible-data, permission, migration, or production-release risk immediately; do not bury it as a design footnote.

## Implementation discipline

- Build a thin vertical slice through the real entry point early, then deepen behavior. Keep intermediate scaffolding truthful and removable.
- Keep functions and modules aligned with one reason to change; use names and types to expose domain invariants. Comments should explain non-obvious rationale, not restate code.
- Validate at the boundary that owns the rule. Preserve error context while presenting stable external errors.
- Add tests at the cheapest layer that proves the behavior: unit for local rules, integration for boundaries/contracts, and end-to-end for the core launch path.
- For a defect, reproduce first, identify the violated invariant and root cause, add a regression check, make the narrow fix, and test adjacent risk. Do not patch only the observed symptom when the same cause remains reachable.

## Delivery evidence

Before handoff, provide:

- changed files/components and mapped requirements;
- contract/schema/configuration changes and compatibility impact;
- executed build, static, unit, integration, and relevant end-to-end commands with results;
- canonical launch and smoke path;
- migration, deployment, monitoring, and rollback steps when applicable;
- deviations, known limitations, and residual risks.

A successful build proves compilation, not user value. A passing unit suite proves only its assertions. State exactly what each item of evidence establishes.
