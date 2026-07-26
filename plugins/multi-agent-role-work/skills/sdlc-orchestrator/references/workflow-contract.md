# Workflow contract

## Activation

The formal workflow starts only from an explicit user request. An active workflow continues when `.ai-workflow/active.yaml` exists and the user asks to continue or change that requirement. Ordinary questions and isolated edits stay outside the workflow.

Use `start --request "..."` as the default initialization path for natural-language requests. It captures the original request, derives a usable title when none is supplied, and prints the same progress summary that `overview` returns later. Starting a workflow opens clarification; it does not authorize PRD, design, or coding.

## Modes

- `quick`: intake, clarification, user confirmation, lightweight design/test planning, readiness review, prototype or MVP preview, user feedback, implementation, verification, acceptance. Use for low-risk, localized work.
- `standard`: intake, clarification, user confirmation, PRD and three-role PRD review, design/test planning, readiness review, prototype or MVP preview, user feedback, implementation, verification, acceptance.
- `strict`: standard flow plus explicit database and release-plan artifacts, each allowed to be marked not applicable with justification.

## Artifacts

All durable artifacts belong under `docs/requirements/<workflow-id>/`. The state file is the index, not a substitute for the artifacts.

Clarification evidence must cover questions, missing details, assumptions, and acceptance-criteria gaps. Requirement confirmation and user feedback must record explicit user approval; inferred agreement is not enough. Prototype evidence must describe preview scope and how the user can inspect it.

## Decisions

At each configured gate, every required role must submit an explicit verdict. A rejection is not averaged away. Resolve blockers, revise the artifact, reset stale approvals, and review again.

Do not enter PRD, design, or coding from a vague one-sentence request. The product role must first identify what is missing or unclear, ask focused questions, synthesize the current understanding, and get explicit user confirmation.

Do not wait until final acceptance to show user-facing work. After readiness review, build the smallest meaningful preview and ask for user feedback. If the user rejects the direction, preserve the feedback and reopen to clarification, PRD, or design instead of continuing to final implementation.

An open `major` issue blocks acceptance. It must be resolved, or be explicitly dispositioned as `accepted_risk` or `deferred` by a named human authority with separate evidence. A deferred issue also records a due date. Minor issues remain visible but do not independently block a gate.

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

The state tool automatically rewinds to the earliest affected stage when a recorded artifact changes and supersedes downstream state. This is a safety floor, not a substitute for the required change-control discussion.

## Evidence

Statements such as “implemented”, “tested”, or “approved” require a path, command result, review record, or other inspectable evidence. Never use confidence language as evidence. Evidence hashes are rechecked when a gate is evaluated; changing an indexed artifact, review, meeting record, or human approval makes it stale until it is re-recorded and, where applicable, re-reviewed.

The state script is not an authentication boundary. Enforce reviewer independence operationally by delegating to separate agents, using unique review files, and preserving their unedited findings. Deterministic checks reject missing or trivial evidence but cannot prove that a document is correct.

## State integrity

State files use a versioned schema, monotonic revision, atomic replacement, and a repository-scoped cross-process writer lock. A stale writer is rejected when the on-disk revision differs from the revision it loaded. These controls protect local consistency; they do not resolve Git merge conflicts or provide tamper-proof audit history.

Use `overview` for handoffs and progress checks. It reports the active stage, whether advancement is currently allowed, missing evidence, open or carried issues, meeting-note count, and configured human approval gates.
