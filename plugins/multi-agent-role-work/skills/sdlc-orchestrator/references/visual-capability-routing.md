# Visual capability routing

Use this route only when visual or interaction presentation materially affects user judgment. Backend changes, nonvisual APIs, internal migrations, and ordinary copy-only edits skip it.

## Scope classification

During scope/risk analysis record:

- affected surface and primary user task;
- whether an existing approved design system/direction is sufficient;
- whether visual direction remains subjective or materially open;
- required prototype fidelity and representative viewports;
- available optional Skills and the bundled fallback;
- how visual behavior will be verified automatically.

Use existing `user_visible` and `subjective_judgment` risk flags when applicable; do not invent a new risk flag solely for aesthetics. The evidence must explicitly say whether the visual capability chain is active.

## Role chain

1. **Product direction at design:** begin a product work item. Use `$sdlc-product` and its visual-direction playbook. If the exact optional `$product-design:ideate` Skill is available and the work is primarily visual exploration, attach it. Complete the work item with `visual_direction=<path>`.
2. **Engineering design and prototype:** verify the completed product work-item status, output path, and current file SHA-256, then pass that binding to engineering. Use `$sdlc-engineering`; for materially visual implementation attach available `$frontend-design` and/or `$ui-ux-pro-max`. Engineering copies the effective visual decisions and state requirements into the indexed technical design, cites the supporting direction binding in design/prototype evidence, renders the result, and completes the formal engineering artifacts.
3. **Testing design and verification:** pass the same direction binding and current rendered build to testing. Use `$sdlc-testing`; attach available `$product-design:audit` and/or `$web-design-guidelines` only when their exact names are available and relevant. Testing checks observable visual quality independently.
4. **User feedback:** present the rendered prototype, what it proves, what remains simulated, the recommended direction, and meaningful alternatives. Ask the user for subjective direction approval only after automatic functional and visual checks have run.

The three design-stage role handoffs fit the normal quick/standard/strict per-stage ceiling. Keep them sequential when engineering depends on product direction; testing may plan independently only after the product direction and requirements are stable.

`visual_direction` is a supporting completed work output, not a new `record-artifact` name or schema field. Do not call `record-artifact --name visual_direction`. The indexed technical design carries the effective decisions; reviewers recheck its cited supporting output hash before relying on it. If the direction changes, reopen design and produce replacement product/engineering evidence rather than silently editing the supporting file.

## Fallback and boundaries

- Missing optional Skills never block the workflow. Use the bundled visual playbooks and disclose that the specialized external pass did not run.
- Product does not edit application code or technical design. Engineering does not select unresolved product behavior or silently replace the visual direction. Testing does not turn personal preference into a defect.
- Generated images or mockups are direction evidence, not proof of implemented behavior.
- Visual polish cannot compensate for an absent core capability, fake data, inaccessible behavior, missing states, or a broken user journey.
