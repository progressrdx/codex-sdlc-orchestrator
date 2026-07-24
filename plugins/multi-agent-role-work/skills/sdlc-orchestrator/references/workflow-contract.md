# Workflow contract

## Activation

The formal workflow starts only from an explicit user request. An active workflow continues when `.ai-workflow/active.yaml` exists and the user asks to continue or change that requirement. Ordinary questions and isolated edits stay outside the workflow.

## Modes

- `quick`: intake, lightweight design/test planning, implementation, verification, acceptance. Use for low-risk, localized work.
- `standard`: PRD and three-role PRD review, design/test planning, readiness review, implementation, verification, acceptance.
- `strict`: standard flow plus explicit database and release-plan artifacts, each allowed to be marked not applicable with justification.

## Artifacts

All durable artifacts belong under `docs/requirements/<workflow-id>/`. The state file is the index, not a substitute for the artifacts.

## Decisions

At each configured gate, every required role must submit an explicit verdict. A rejection is not averaged away. Resolve blockers, revise the artifact, reset stale approvals, and review again.

## Human authorization

Human authorization is distinct from AI review. Configure it at initialization for any gate that controls destructive data changes, permissions, production release, security exceptions, legal/compliance decisions, or another irreversible or high-impact action.

At a configured checkpoint:

1. Complete independent role verdicts and current approved meeting notes.
2. Present the current evidence to the user or named authority.
3. Pause until that person explicitly approves or rejects.
4. Record approval only from that explicit response, with a separate repository evidence file.

Never delegate human approval to another Agent or infer it from silence. The state script binds the approval to current decision and meeting hashes, but it cannot authenticate the approver.

## Communication records

Create structured meeting notes whenever two or more roles exchange findings, negotiate a disagreement, change scope, triage a defect, or make a gate decision. Preserve the purpose, each material role position, key reasoning, disagreements, decisions with rationale, action owners, open questions, and next step. Omit greetings, repetition, chain-of-thought, and raw transcripts.

Gate meeting notes summarize independent role reviews; they do not replace those reviews. A gate advances only when the recorded meeting covers all required roles, has an approved outcome, and snapshots the current decision evidence. Any later decision, material artifact change, new issue, issue resolution, or workflow reopen supersedes affected meeting notes and requires a fresh record.

## Change control

When an approved requirement changes:

1. Record the change as an issue or decision.
2. Return to the earliest affected stage.
3. Invalidate downstream gate decisions and artifacts as appropriate.
4. Update traceability and rerun affected tests.
5. Record a `change_control` meeting when multiple roles discuss the change.

## Evidence

Statements such as “implemented”, “tested”, or “approved” require a path, command result, review record, or other inspectable evidence. Never use confidence language as evidence.

The state script is not an authentication boundary. Enforce reviewer independence operationally by delegating to separate agents, using unique review files, and preserving their unedited findings. Deterministic checks reject missing or trivial evidence but cannot prove that a document is correct.

## State integrity

State files use a versioned schema, monotonic revision, atomic replacement, and a repository-scoped cross-process writer lock. A stale writer is rejected when the on-disk revision differs from the revision it loaded. These controls protect local consistency; they do not resolve Git merge conflicts or provide tamper-proof audit history.
