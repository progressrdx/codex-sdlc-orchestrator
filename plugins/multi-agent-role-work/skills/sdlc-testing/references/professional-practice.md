# Testing professional practice

Use the smallest set of techniques that gives credible evidence for the assigned risk. Verification is an independent investigation, not a checklist-counting exercise.

## Risk model

Rank a test condition using:

- user/business impact if wrong;
- likelihood from complexity, novelty, change size, and defect history;
- detectability before harm;
- reversibility and recovery cost;
- exposure across users, data, permissions, or environments.

Prioritize high-impact irreversible or poorly detectable failures even when their happy path is simple. Record why lower-risk areas received lighter coverage.

## Coverage model

Select applicable dimensions:

- behavior and acceptance rules;
- input partitions, boundaries, malformed and adversarial input;
- state transitions, persistence, cancellation, recovery, retries, duplicates, ordering, and concurrency;
- actors, permissions, tenant/resource isolation, and audit effects;
- contracts, compatibility, migrations, configuration, and external dependency failures;
- performance/resource limits, accessibility, localization, platform/browser/device variation;
- observability, support diagnostics, rollback, and stale or partial data;
- regression around touched code, shared dependencies, and historically fragile paths.

Map each material risk to evidence. Do not create a full matrix when a focused change has only a few meaningful dimensions.

## Test technique selection

- **Example-based:** known business scenarios and acceptance criteria.
- **Equivalence and boundaries:** representative valid/invalid partitions and edges.
- **Decision-table/state-transition:** rule combinations, precedence, and lifecycle behavior.
- **Property-based/invariant:** broad input space where stable properties are clearer than examples.
- **Contract/integration:** ownership and compatibility across process, service, database, file, or tool boundaries.
- **Exploratory:** unfamiliar or interaction-heavy behavior; record charter, observations, and follow-up evidence.
- **Fault injection:** timeouts, partial failures, retries, duplicate delivery, resource exhaustion, or dependency degradation when consequences justify it.
- **Performance/security/accessibility:** use specialized tools and explicit thresholds or standards when these are requirements or material risks.

Choose the cheapest layer that can expose the fault, then retain at least one end-to-end test for the user's core outcome. Avoid UI tests for pure logic and mocks that erase the boundary being tested.

## Oracles and evidence

Define what makes a result correct before running the test. Strong oracles include exact business rules, state invariants, persisted effects, contract schemas, independent calculations, authorized snapshots, and confirmed semantic properties.

Weak signals need additional proof:

- exit code 0 does not prove the intended scenario ran;
- HTTP 2xx does not prove correct body, authorization, or side effect;
- a rendered element does not prove interaction, persistence, navigation, or accessibility;
- a snapshot does not prove semantic correctness;
- absence of logs/exceptions does not prove success;
- a mock response does not prove the real integration.

Evidence must identify build/source, environment, input, action, expected result, actual result, and durable output such as command logs, report, screenshot, trace, query, or artifact path.

## Defect classification

Separate severity from priority.

- **Blocker:** verification or safe use cannot proceed, or a required core outcome is unavailable.
- **Critical:** security/privacy breach, irreversible corruption, broad outage, or equivalent catastrophic impact.
- **Major:** Must behavior is wrong, data/state is materially incorrect, or no practical recovery exists for an important path.
- **Minor:** limited impact with a practical workaround and no material goal failure.

Include reproducible steps, expected/actual behavior, environment/build, frequency, user impact, evidence, suspected boundary without presenting speculation as root cause, and regression scope. A blocked test is not automatically a product defect; explain the blocker and owner.

## Quality verdict

Base the verdict on requirement coverage, core-journey evidence, unresolved defect exposure, blocked high-risk checks, source freshness, and residual risk. Flaky or non-reproducible evidence cannot support approval until stabilized or replaced.

State:

- what was proven;
- what failed or remains blocked;
- what was not tested and why;
- residual risk and affected users/data;
- the exact evidence needed to change a reject or blocked conclusion.
