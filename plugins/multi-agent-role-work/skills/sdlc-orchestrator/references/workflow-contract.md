# Workflow contract

## Activation

The formal workflow starts only from an explicit user request. An active workflow continues when `.ai-workflow/active.yaml` exists and the user asks to continue or change that requirement. Ordinary questions and isolated edits stay outside the workflow.

Use `start --request "..." --mode auto` as the default initialization path for natural-language requests. It captures the original request, derives a usable title when none is supplied, and prints the same progress summary that `overview` returns later. Starting a workflow opens scope and risk analysis; it does not authorize PRD, design, or coding.

## Modes

- `auto`: temporary start mode. The coordinator must complete `scope_check`, record risk triage, and select a concrete mode before continuing.
- `micro`: intake, scope/risk check, implementation, independent verification, lightweight user delivery confirmation, completion. Use only for explicit, localized, low-risk work with reliable verification.
- `quick`: intake, scope/risk check, lightweight design/test planning, readiness review, implementation, verification, acceptance, user delivery confirmation, completion. Clarification, requirement confirmation, prototype, and user feedback are enabled only when the risk assessment requires them.
- `standard`: intake, scope/risk check, clarification, user confirmation, PRD and three-role PRD review, design/test planning, readiness review, prototype or MVP preview, user feedback, implementation, verification, acceptance, user delivery confirmation, completion.
- `strict`: standard flow plus locked user-confirmed core outcomes, registered Must acceptance criteria, explicit database and release-plan artifacts, scoped source binding, semantic profile-based final-journey verification, and human approval checkpoints at readiness and acceptance.

The risk assessment recommends the lowest safe mode from explicit flags. A user-requested mode is a floor, and the selected mode must never be below the deterministic recommendation. Always perform the gap analysis; skip user questions only when no unresolved high-impact choice exists. Three or more distinct quick-level flags require at least `standard`; `weak_verification` combined with `user_visible` or `external_dependency` also requires at least `standard`. These explicit rules avoid opaque scoring while accounting for risk combinations.

Modes may escalate `micro → quick → standard → strict` when new evidence appears. Every role reports newly discovered risk with separate repository evidence. `report-risk` combines active flags, calculates the minimum safe mode, records `escalation_required`, and blocks all advancement when the current mode is insufficient. It recommends an upgrade; it does not silently apply one. A resolved report requires separate evidence, different resolver and verifier identities, and `resolve-risk`. A mistaken report may be withdrawn only by its original reporter or the user through `withdraw-risk`. Both operations recompute the escalation blocker; neither lowers the already selected mode. A named human may accept a reversible, non-sensitive escalation risk without upgrading by recording rationale, distinct evidence, and an expiry through `accept-escalation-risk`; the state records reduced assurance and blocks again after expiry. Security/privacy, irreversible, data-migration, and production-release flags cannot use this exception. After explicit user approval, `escalate-mode` binds separate approval evidence, switches to the approved mode, invalidates downstream work, and rewinds to `scope_check` for a refreshed baseline. Targets below the recommendation are rejected. Strict escalation automatically configures human checkpoints at readiness and acceptance. Downgrades require a new assessment showing why the earlier risk no longer applies.

## Artifacts

All durable artifacts belong under `docs/requirements/<workflow-id>/`. The state file is the index, not a substitute for the artifacts.

The scope/risk artifact records in-scope and out-of-scope boundaries, observable acceptance, verification, checked gaps, risk flags, mode recommendation, selected mode, and conditional gates. A role authors this artifact before `assess-risk` registers it; CLI arguments are structured state inputs, not a substitute for the analysis document. Clarification evidence must cover questions, missing details, assumptions, and acceptance-criteria gaps. Requirement confirmation, preview feedback, and final delivery confirmation must record explicit user approval; inferred agreement is not enough. Prototype evidence must describe preview scope and how the user can inspect it.

Strict mode adds two protected baselines. `record-core-goals` stores user-confirmed `GOAL-*` outcomes before PRD work. `register-acceptance-criteria` binds Must `AC-*` entries to the current PRD hash. Engineering, testing, or product cannot later mark either baseline as mock-only, deferred, removed, replaced, or not applicable. A reduction requires a distinct `approve-scope-change` record with the approving user's name, rationale, affected IDs, and evidence. The default rewind remains the baseline stage. A user-approved impact analysis may name a later earliest affected stage, with a separate reason explaining why earlier artifacts remain valid; `AC-*` changes cannot skip verification and `GOAL-*` changes cannot skip acceptance.

## Decisions

At each configured gate, every required role must submit an explicit verdict and a distinct stable task/session reference. The reference is included in meeting and human-approval snapshots so accidental role reuse is rejected. A rejection is not averaged away. Resolve blockers, revise the artifact, reset stale approvals, and review again.

In strict verification, prefer one `submit-verification` manifest over a long sequence of granular commands. It atomically records a clean committed source binding, every Must-criterion verdict, and the matching final-journey profile. The source scope is a reviewed set of repository-relative paths; Git tree/blob metadata is hashed once per gate evaluation, and unrelated paths do not invalidate scoped verification. An empty scope intentionally binds the whole repository.

Journey profiles cover `web`, `desktop`, `api`, `cli`, `library`, and `data` deliverables. Testers may truthfully record `pass`, `fail`, `blocked`, or `not_applicable`; required non-pass results are preserved but block advancement. Builds, screenshots, hardcoded URLs, source inspection, prototype approval, and developer self-tests do not substitute for executing the applicable final user journey.

Do not enter PRD, design, or coding from an unanalyzed one-sentence request. `scope_check` must first inspect actors, rules, boundaries, data/API effects, permissions, states, failures, compatibility, subjective choices, acceptance, and verification. Ask focused questions and require confirmation when material uncertainty exists; do not manufacture questions for a decisive low-risk task.

When preview is enabled, do not wait until final acceptance to show user-facing work. After readiness review, build the smallest meaningful preview and ask for user feedback. Record `approve`, `request_changes`, or `reject` explicitly. A change request or rejection preserves its evidence and rewinds to the affected scope, clarification, PRD, design, or prototype stage instead of continuing to final implementation.

No concrete mode can finish on product, developer, or tester confidence alone. After verification and any configured acceptance ceremony, show the user the result, implementation summary, and test evidence. Explicit approval completes the workflow; `request_changes` or `reject` preserves the decision and rewinds to implementation by default.

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

Statements such as “implemented”, “tested”, or “approved” require a path, command result, review record, or other inspectable evidence. Never use confidence language as evidence. Evidence hashes are rechecked when a gate is evaluated; changing an indexed artifact, review, meeting record, or human approval makes it stale until it is re-recorded and, where applicable, re-reviewed. Risk-report hashes are rechecked immediately before an escalation is accepted, and escalation approval must use separate evidence.

The state script is not an authentication boundary. It requires distinct role task/session references and preserves them in downstream snapshots, which provides audit traceability and prevents accidental reuse but does not prove who controlled a session. Enforce reviewer independence operationally by delegating to separate agents, using unique review files, and preserving their unedited findings. Deterministic checks reject missing or trivial evidence but cannot prove that a document is correct.

## State integrity

State files use a versioned schema, semantic checksum, monotonic revision, atomic replacement, a prior-valid-state backup, and a repository-scoped cross-process writer lock. Persistence, locking, and checksum handling live in the isolated `state_store.py` module rather than the workflow command layer. Unsupported direct edits fail closed; use workflow commands. `audit-state` remains available when the main state checksum or syntax is damaged, and `repair-state --from-backup --confirm RESTORE` restores only a validated backup with a new revision and audit entry. A stale writer is rejected when the on-disk revision differs from the revision it loaded. These controls protect local consistency; they do not resolve Git merge conflicts or provide a cryptographic identity for reviewers.

Use `overview` for handoffs and progress checks. It reports the active stage, whether advancement is currently allowed, missing evidence, open or carried issues, meeting-note count, and configured human approval gates.
