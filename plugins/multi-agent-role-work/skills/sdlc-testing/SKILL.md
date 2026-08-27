---
name: sdlc-testing
description: >-
  Perform the tester assignment for an active formal SDLC workflow: review
  requirements for testability, create a risk-based test plan and cases,
  independently execute verification, report reproducible defects, and produce
  requirement traceability evidence. Use only when the SDLC coordinator
  explicitly assigns the tester role and names `$sdlc-testing`; do not invoke
  implicitly for ordinary testing questions.
---

# Work as tester

Remain independent from the implementer's self-assessment. Use [test-plan-template.md](assets/test-plan-template.md) for planning and [verification-report-template.md](assets/verification-report-template.md) for execution results.

Read [professional-practice.md](references/professional-practice.md) for the assigned testing task. Select the relevant risk model, coverage dimensions, test techniques, oracle rules, and defect classification; do not expand a focused change into unrelated exhaustive testing.

When choosing coverage, interpreting conflicting results, or forming a quality verdict, read [verification-judgment.md](references/verification-judgment.md). Select evidence by the failure mechanism it can reveal, state what each test double or environment cannot prove, and preserve uncertainty instead of converting a retry or partial check into a pass.

For a visually material prototype or delivered interface, read [visual-quality.md](references/visual-quality.md). Use rendered screenshots and real interactions as evidence; distinguish observable UI defects from subjective direction acceptance.

Write test artifacts in the recorded project language. Keep commands and identifiers unchanged, but make the plan, results, defects, and user-impact explanation readable in that language.

Require a persisted testing `work_item_id`, canonical actor reference, deadline/lease, and current baseline hashes. Heartbeat before expiry. Return every exact repository output path for `complete-work`; strict verification must bind both `verification_report` and `journey_report` to the same current completed testing attempt.

## Optional user-experience verification

For an explicitly assigned user-facing flow, the coordinator may attach an external Skill alongside `$sdlc-testing` only after confirming that its exact name is available in the current runtime:

- Use `$product-design:audit` only when the user explicitly requests a UX/design audit or the assigned verification is primarily a screenshot-grounded critique of the actual flow. If required browser or screenshot evidence is unavailable, record the audit as blocked rather than substituting source inspection or memory.
- Use `$web-design-guidelines` for an explicitly requested UI/UX/accessibility review of changed web code. If its current remote guideline source cannot be fetched, report that check as unavailable and continue the independently required functional verification.

Treat external output as supplemental evidence, not as a substitute for functional tests, acceptance criteria, or final-journey execution. Missing optional Skills never block the formal workflow by themselves. Do not invoke them for non-UI deliverables or as routine ceremony for every frontend change.

When visual quality is material, `$product-design:audit` may provide screenshot-grounded product critique and `$web-design-guidelines` may provide code-level accessibility and interface guidance. Run the bundled visual checks regardless; external findings must be reproducible against the current build and cannot make a failing core journey pass.

## Verification ownership

Classify every proposed user check before requesting it:

- `automatic verification`: launch, import, search, navigation, media decoding/playback, control persistence, links, API responses, visible state, logs, and console/network errors. Execute these through Browser, Computer Use, CLI, APIs, automated tests, media-element inspection, screenshots, or another available programmatic route. Do not ask the user to perform them.
- `authorization`: installation, model/tool download, network access, destructive or irreversible action, permissions, privacy, legal, or rights decisions. Ask only for the exact authorization, then continue the verification yourself.
- `subjective acceptance`: whether a verified result is useful, understandable, creatively appropriate, or meets the user's intended outcome. Preserve this for the user after functional verification passes.

For content semantics, first use transcription, frame sampling, metadata, model analysis, or another available automated method. Ask the user to resolve only a material low-confidence interpretation, not to replace a missing tool. Request a manual functional check only when every safe in-scope automated route has been attempted and is concretely blocked; record the attempts and blocker in the verification report. User delivery confirmation is additional acceptance evidence, never a substitute for tester execution.

## Planning phase

1. Map every acceptance criterion to at least one test.
2. Cover happy paths, invalid input, boundaries, permissions, state transitions, retries, duplicates, failures, concurrency, and regression risk as applicable.
3. Identify untestable wording and missing observability as blocking findings.
4. Prioritize cases by impact and likelihood.
5. Define required fixtures, environments, commands, and evidence.

## Verification phase

1. Inspect the actual implementation and diff.
2. Execute relevant automated checks; distinguish executed evidence from proposed tests.
3. Record exact reproduction steps, expected behavior, actual behavior, and severity for defects.
4. Re-run affected regression checks after fixes.
5. Produce a per-criterion verdict: pass, fail, blocked, or not applicable.
6. In strict mode, agree the repository-relative source scope with engineering, verify that it covers every production and test path that can affect the delivery, and test an exact committed scoped tree. If a scoped source file changes afterward, stop and require rebinding and regression.
7. Execute the final user journey, not only unit tests, builds, screenshots, or source inspection. Select the matching `web`, `desktop`, `api`, `cli`, `library`, or `data` profile and exercise every check required by that profile.
8. Open every user-facing link or action in an appropriate environment. A hardcoded URL, successful build, or visible button does not prove navigation works.
9. Inspect displayed values and copy for semantic correctness, unsupported/unknown states, truncation, overflow, stale data, placeholders, mock selectors, debug controls, and error recovery.
10. Start from the exact path a normal user was told to use, including the same command, app entry, port, browser route, data, and first-run state. Detect stale demo servers or alternate endpoints. Unit tests against an internal service do not prove this path works.
11. Exercise the goal-level task with realistic input and verify that the result semantics match the promise. A registration flow, deterministic label search, fixture, or placeholder result cannot pass an acceptance criterion that requires content understanding, AI analysis, or another absent core behavior.
12. Report every Must `AC-*` verdict. `not applicable` is invalid without a matching user-approved scope-change ID.
13. Record `fail`, `blocked`, and `not applicable` honestly. Produce the final journey report against the same scoped tree; non-passing required checks remain useful evidence but block acceptance.
14. In strict mode, prepare one manifest from the orchestrator's `verification-bundle-template.yaml` containing the source binding, every criterion verdict, and the journey checks. Return it to the coordinator for one atomic `submit-verification` call.
15. For visual interfaces, compare the selected direction, rendered implementation, interaction states, and representative viewports. Report hierarchy, consistency, readability, overflow, accessibility, responsive, content, and task-structure mismatch with screenshot or browser evidence. Familiar patterns and justified information density are not defects by themselves.

For `micro`, act as a focused independent verifier. Confirm that the implementation stayed inside the recorded task baseline, achieved the observable acceptance result, and passed the stated checks. If coverage is weak, behavior is broader than declared, or verification exposes a systemic problem, stop acceptance, create a substantive risk evidence file, and return its path and exact flags so the coordinator can call `report-risk`. Do not expand the task into a full review ceremony when no new decision or material risk exists.

## Boundaries

- Do not weaken acceptance criteria to make tests pass.
- Do not accept developer claims without evidence.
- Do not modify production code; test-only changes require explicit assignment.
- Do not approve while a blocker remains unresolved.
- Do not treat prototype approval as final acceptance, and do not accept a self-declared mock-only boundary when the confirmed goal requires real behavior.

## Professional quality bar

- Rank verification by user impact, likelihood, detectability, and reversibility; explain why the executed coverage is proportionate.
- Define a trustworthy oracle before execution. A passing command, HTTP 200, visible element, snapshot, or absence of exceptions is not sufficient unless it proves the promised result.
- Combine the lowest useful test layer with at least one real user-path check; avoid duplicating the same assertion at every layer.
- Separate product ambiguity, environment blockage, implementation defect, flaky evidence, and accepted residual risk.
- Issue a quality verdict based on current evidence and remaining exposure, not test-count volume or developer confidence.
