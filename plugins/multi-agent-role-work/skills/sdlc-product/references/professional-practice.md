# Product professional practice

Use the sections relevant to the assigned product task. The purpose is better product judgment, not a larger document.

## Problem framing and discovery

- Identify the actor, triggering situation, desired progress, current workaround, consequence of failure, and evidence available. Mark inference as inference.
- Separate the requested solution from the underlying outcome. Preserve the user's chosen direction unless evidence exposes a contradiction, infeasibility, or material alternative worth deciding.
- For reuse research, compare only capabilities that can change build-versus-adapt scope. Record source date, fit, gaps, operational/privacy cost, and the decision; popularity alone is not fit.
- Ask a question only when different answers would materially alter behavior, scope, risk, architecture, or acceptance. Otherwise make a reversible assumption explicit.

## Product model

Choose only the models the behavior needs:

- **Journey:** trigger, entry point, primary steps, success, recovery, exit.
- **Actors and permissions:** actor, resource, allowed action, precondition, denial behavior, audit need.
- **State machine:** state, entering event, invariant, allowed transition, failure/recovery transition.
- **Decision table:** conditions, rule precedence, result, ambiguous or uncovered combinations.
- **Data lifecycle:** source, owner, validation, retention, correction, export/deletion, privacy boundary.

Use stable IDs when a model affects requirements or tests. A diagram or table must resolve ambiguity; do not add one for decoration.

## Scope and prioritization

- Define the smallest end-to-end outcome a real user can complete. Infrastructure, registration, navigation, or a generated shell is not an outcome unless that is the confirmed goal.
- Evaluate candidates by user/business value, urgency or cost of delay, risk reduction/learning, dependency unlock, and delivery cost. Qualitative rankings are acceptable when evidence is limited.
- Mark Must only when omission breaks the confirmed outcome, a binding constraint, safety, or launch viability. Record non-goals and deferred items with impact.
- Treat an external integration, live data source, model, paid service, permission, or migration as a product dependency with fallback and user-visible failure behavior.

## Metrics and learning

- Define a primary success signal tied to completed user value, not page views, output count, or engineering activity.
- Add diagnostic signals for funnel/state failures and guardrails for quality, reliability, privacy, cost, or harmful side effects when relevant.
- State measurement window, population, source, baseline or comparison, and known blind spots. Do not invent numeric targets without a source or user decision.
- For uncertain propositions, name the cheapest evidence that could falsify the assumption before expensive implementation.

## Requirement and acceptance quality

Every Must requirement should identify actor, trigger, observable behavior, rules/state effects, failure behavior, and traceability to a goal. Split requirements that contain independently releasable behaviors.

An acceptance criterion should establish:

1. a controllable precondition and realistic input;
2. one observable action or event;
3. a specific outcome, including state/data effects where relevant;
4. negative or recovery behavior when risk warrants it;
5. an oracle that does not depend on “looks correct” or hidden implementation knowledge.

Reject criteria that merely say “works,” “supports,” “is user friendly,” “performs well,” or “uses AI” without observable semantics. For AI or content analysis, include representative inputs, meaningful output properties, unacceptable failure modes, and how uncertainty is communicated.

## Product handoff evidence

Return the product model used, high-impact decisions and rationale, assumptions, unresolved choices, requirement/goal traceability, measurable success signals, scope exclusions, and any newly discovered risk. Keep speculative ideas out of the approved baseline.
