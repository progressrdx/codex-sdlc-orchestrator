# Visual quality verification

Use this playbook when visual presentation or interaction materially affects the product outcome. Verify the actual rendered build and classify findings by observable impact; do not turn personal taste into a defect.

## Evidence setup

- Start from the canonical user launch path against the current source/build.
- Read the approved visual direction, prototype evidence, requirements, and relevant design-system constraints.
- Capture representative narrow and wide viewports plus high-risk intermediate widths.
- Exercise the primary journey and material loading, empty, partial, error, disabled, success, focus, permission, and recovery states.
- Record browser/automation method, viewport, data, theme, locale, zoom, evidence path, and current source identity.

## Objective checks

### Purpose and hierarchy

- The screen's purpose, primary action, current state, and consequence are discoverable.
- Reading order and grouping match information priority.
- Repeated operational tasks remain scannable; decorative content does not dominate work.
- Execute the task-fit walkthrough from product direction using representative object counts and exceptions. Verify comparison fields, frequent controls, selection scope, risk consequences, and return context remain available. A sparse screenshot or fewer clicks alone does not prove a better interface.
- Treat hidden necessary evidence or broken batch/repeat work as a task failure; do not require all tools to use a single-action view or fail a justified dense workspace for being dense.

### System coherence

- Typography roles, spacing rhythm, color roles, component states, icons, radius/depth, and motion are internally consistent.
- The design follows the selected direction or records a deliberate approved deviation.
- Components encode real grouping or interaction instead of generic card/pill decoration.

### Content and states

- Content uses real or explicitly representative data and contains no fabricated claims, unexplained `unknown`, debug controls, or misleading placeholders.
- Loading, empty, partial, error, disabled, success, permission, and recovery behavior are meaningful where applicable.
- Long text, numbers, localization, missing values, validation messages, and truncation remain understandable.

### Responsive and interaction quality

- Primary content and actions remain available without overlap, clipping, unintended horizontal scroll, or unusable density.
- Keyboard order, visible focus, semantic controls, accessible names, touch targets, contrast, zoom, and reduced-motion behavior meet the project standard.
- Hover-only behavior has a keyboard/touch route; animation does not block understanding or action.

### Product identity

- The structure is justified by the user's task, not merely a style preset with the product name substituted. Familiar tables, forms, and editor conventions are legitimate when they fit.
- Distinctive choices, if needed for an actual identity goal, support the domain and primary task rather than competing with them. Lack of novelty is not by itself a defect.
- Marketing, operational, transactional, and content surfaces use an appropriate density and narrative model.

## Subjective versus defect

Testing may fail observable issues such as unreadable contrast, weak hierarchy that hides a required action, inconsistent states, overflow, inaccessible interaction, direction mismatch, misleading content, or responsive breakage.

Do not fail solely because another palette, font, or stylistic direction is personally preferred when the selected direction meets requirements. Present low-confidence aesthetic observations separately for user acceptance.

## Finding format

For each finding record severity, viewport/state, reproduction path, expected product or visual rule, actual observation, screenshot/browser evidence, affected users/task, and smallest credible correction. State whether it is functional, accessibility, responsive, content, consistency, direction-fidelity, or subjective-feedback territory.
