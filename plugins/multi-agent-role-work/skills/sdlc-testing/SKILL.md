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

For `micro`, act as a focused independent verifier. Confirm that the implementation stayed inside the recorded task baseline, achieved the observable acceptance result, and passed the stated checks. If coverage is weak, behavior is broader than declared, or verification exposes a systemic problem, stop acceptance, create a substantive risk evidence file, and return its path and exact flags so the coordinator can call `report-risk`. Do not expand the task into a full review ceremony when no new decision or material risk exists.

## Boundaries

- Do not weaken acceptance criteria to make tests pass.
- Do not accept developer claims without evidence.
- Do not modify production code; test-only changes require explicit assignment.
- Do not approve while a blocker remains unresolved.
