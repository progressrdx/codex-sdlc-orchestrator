# Visual direction for product prototypes

Use this playbook only when presentation or interaction design can materially affect whether users understand, trust, or accept the prototype. The goal is an actionable product direction, not decorative taste or production code.

## Classify the surface

First use [interface-judgment.md](interface-judgment.md) to choose the task-fit working structure, information density, and disclosure strategy. The broad surface families below only distinguish presentation contexts; they do not decide whether a workspace should be a table, editor, monitor, or decision view.

- **Product workspace:** dashboards, admin tools, editors, settings, data and operational interfaces. Optimize for hierarchy, scanability, density, repeated work, state clarity, and low cognitive load.
- **Marketing or narrative surface:** landing pages, portfolios, launch pages, and campaigns. Optimize for identity, story sequence, credibility, and a clear primary action.
- **Transactional flow:** onboarding, checkout, setup, forms, permissions, and destructive actions. Optimize for progress, consequence clarity, recovery, trust, and error prevention.
- **Content or media surface:** reading, learning, browsing, playback, or creation. Optimize for content prominence, rhythm, navigation, and distraction control.

Mixed products may need more than one surface system. Do not wrap an application in an unrequested marketing page or apply campaign styling to an operational workspace.

## Establish the product design thesis

Define:

1. the actor, context, and single primary task;
2. the first information the user must notice and the first decision they must make;
3. a one-sentence experience thesis connecting the task to hierarchy, density, and feedback; mood/material may matter for expressive surfaces;
4. optional domain identity when it helps recognition or an explicit brand goal; omit decorative signatures in working surfaces when they compete with the task;
5. explicit constraints from brand, platform, accessibility, performance, and existing design systems;
6. what must not appear, including misleading data, decorative controls, irrelevant cards, excessive effects, or unapproved features.

Run a task-fit test: explain which working facts justify the structure and what would make you choose differently. Familiar components shared across products are not a failure. Apply an identity test only where brand differentiation is an actual product goal; do not force uniqueness onto routine operational controls.

## Explore alternatives

Create alternatives only when a real decision remains. Usually two or three directions are enough. Each must differ in system or hierarchy—not merely accent color.

For each direction provide:

- thesis and target impression;
- information hierarchy and layout principle;
- typography roles and density;
- color roles, contrast strategy, and depth/radius treatment;
- imagery/icon/motion approach where relevant;
- identity treatment if relevant, including an explicit choice to rely on existing conventions;
- usability, accessibility, implementation, and brand risks;
- why it fits or conflicts with the primary task.

Do not average alternatives into a directionless compromise. Recommend one, explain why, and preserve the user's selected direction when subjective choice matters.

## Specify behavior before polish

List the complete relevant state set: initial, loading, empty, partial, success, error, offline/degraded, permission denied, disabled, destructive confirmation, recovery, first run, and responsive variations as applicable.

For each primary screen or component specify:

- job and primary action;
- information priority and grouping;
- reachable states and transitions;
- content/data realism and unknown-state language;
- responsive priority and mobile action;
- keyboard, focus, touch, and reduced-motion expectations;
- acceptance observations that can be tested in the rendered prototype.

A beautiful happy path with absent failure, empty, or recovery states is not a complete product direction.

## Handoff contract

Write the visual-direction artifact using the template. Return its path and content hash as the completed product work output named `visual_direction`. Engineering must cite that exact path and hash in its technical design and prototype evidence. The artifact may propose visual hypotheses; only explicit user feedback selects or changes a subjective direction.
