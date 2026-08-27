# Visual prototype implementation

Use this playbook for a materially visual user-facing prototype or substantial UI change. Implement the selected product direction through the repository's real stack and render it; do not substitute a description, static source review, or generic component gallery.

## Bind the direction

If product produced `visual_direction`, record its producer work-item ID, repository path, and SHA-256 in the technical design and prototype evidence. Confirm that the direction matches the current requirement baseline. Copy the effective visual-system decisions and required state set into the indexed technical design; a link alone is not the governing baseline.

An explicitly labeled recommended visual hypothesis may be implemented for preview before subjective user selection. Stop only when unresolved choices change product behavior, scope, navigation consequences, authority, or an explicit pre-approval requirement—not merely because the user has not yet seen the prototype.

Optional frontend Skills may refine execution, but do not overwrite the selected hierarchy, behavior, product states, or explicit constraints.

Carry the product's task-fit structure and visible/disclosed information decisions into the build. Do not convert a comparison table into cards, hide repeated controls, or replace a workspace with a single decision panel merely to make it cleaner. If the handoff specifies only style without enough task structure, request the missing product decision before inventing navigation or removing necessary context.

## Build a coherent system

- Reuse existing tokens, components, icons, fonts, and interaction conventions when they fit; evolve them deliberately rather than creating a parallel system.
- Define role-based tokens for color, typography, spacing, radius, elevation, motion, and responsive constraints. Avoid scattered one-off values that prevent coherent iteration.
- Make typography and spacing express hierarchy. Decoration must support identity, grouping, affordance, sequence, or atmosphere.
- Use cards, pills, gradients, oversized type, glass effects, animations, and illustrations only when they earn a functional or identity role.
- Use real or explicitly labeled representative content. Never invent testimonials, metrics, inventory, user records, or model confidence.

## Implement the experience, not a poster

- Start at the canonical user entry point and show the primary working surface—not an unrequested landing wrapper.
- Implement realistic loading, empty, partial, error, disabled, success, focus, destructive/recovery, and permission states as applicable.
- Preserve semantic structure, reading order, keyboard access, visible focus, touch targets, contrast, zoom, and reduced-motion behavior.
- Design responsive behavior from information priority. Do not merely shrink desktop dimensions; preserve the primary action and avoid clipping, overlap, inaccessible off-screen controls, and unreadable wrapping.
- Keep motion purposeful, bounded, and optional. The product must remain understandable without animation.

## Rendered verification before handoff

Run the real application and inspect representative narrow and wide viewports. Exercise the primary journey and material states. Capture durable screenshot or browser evidence and check:

- first-view purpose, hierarchy, and primary action;
- representative-volume comparison, repeat actions, filter/selection preservation, and return-to-work context where the task requires them;
- consistency of typography, spacing, color roles, components, icons, and interaction feedback;
- text/data overflow, truncation, empty values, long localization, and zoom;
- keyboard, focus, hover, touch, reduced motion, and screen-size behavior;
- console/network failures and stale or placeholder content;
- fidelity to the bound visual direction without sacrificing product behavior.

Record what the prototype proves, what remains simulated or absent, exact launch instructions, evidence paths, viewport sizes, known visual limitations, and the visual-direction path/hash.
