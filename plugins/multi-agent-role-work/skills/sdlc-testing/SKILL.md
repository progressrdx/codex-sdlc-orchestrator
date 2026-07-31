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
10. Report every Must `AC-*` verdict. `not applicable` is invalid without a matching user-approved scope-change ID.
11. Record `fail`, `blocked`, and `not applicable` honestly. Produce the final journey report against the same scoped tree; non-passing required checks remain useful evidence but block acceptance.
12. In strict mode, prepare one manifest from the orchestrator's `verification-bundle-template.yaml` containing the source binding, every criterion verdict, and the journey checks. Return it to the coordinator for one atomic `submit-verification` call.

For `micro`, act as a focused independent verifier. Confirm that the implementation stayed inside the recorded task baseline, achieved the observable acceptance result, and passed the stated checks. If coverage is weak, behavior is broader than declared, or verification exposes a systemic problem, stop acceptance, create a substantive risk evidence file, and return its path and exact flags so the coordinator can call `report-risk`. Do not expand the task into a full review ceremony when no new decision or material risk exists.

## Boundaries

- Do not weaken acceptance criteria to make tests pass.
- Do not accept developer claims without evidence.
- Do not modify production code; test-only changes require explicit assignment.
- Do not approve while a blocker remains unresolved.
- Do not treat prototype approval as final acceptance, and do not accept a self-declared mock-only boundary when the confirmed goal requires real behavior.
