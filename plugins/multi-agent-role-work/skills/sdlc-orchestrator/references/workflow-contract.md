# Workflow contract

## Activation

The formal workflow starts only from an explicit user request. The recommended entry is an actionable `团队开发：<request>` prompt; the text after the prefix becomes the original request and opens discovery only. Explicit requests to start a formal or multi-role development process and direct `$sdlc-orchestrator` invocation are equivalent advanced entries. Merely discussing team development does not activate the workflow. An active workflow continues when `.ai-workflow/active.yaml` exists and the user asks to continue, inspect, change, or accept that requirement. Without active state, short continuation phrases do not create a workflow. Ordinary questions and isolated edits stay outside the workflow.

Use `start --request "..." --mode auto` as the default initialization path for natural-language requests. It captures the original request, derives a usable title when none is supplied, and prints the same progress summary that `overview` returns later. Starting a workflow opens scope and risk analysis; it does not authorize PRD, design, or coding.

On every later prompt explicitly routed to an active requirement, read `overview` before delegating or editing. Routing is on demand through `$sdlc-orchestrator` or clear phrases such as “继续团队开发”, “查看研发进度”, “修改当前需求”, or “开始验收”. A bare “继续” is ordinary conversation because the Skill cannot inspect active state before it is selected; no active pointer means even a clear continuation phrase reports no workflow and never creates one. The plugin installs no lifecycle hooks; ordinary conversation never runs workflow code.

`pause` keeps the pointer, stage, and evidence and rejects all delivery mutations until `resume`. Resume only from an explicit formal-workflow request such as “继续团队开发”; a bare “继续” neither invokes the workflow nor changes state. Unrelated prompts remain ordinary conversation because no lifecycle hook is registered. Use pause when the user temporarily switches topics; do not complete or discard a requirement merely to avoid context overhead.

## Modes

- `auto`: temporary start mode. The coordinator must complete `scope_check`, record risk triage, and select a concrete mode before continuing.
- `micro`: intake, scope/risk check, implementation, independent verification, lightweight user delivery confirmation, completion. Use only for explicit, localized, low-risk work with reliable verification.
- `quick`: intake, scope/risk check, lightweight design/test planning, readiness review, implementation, verification, acceptance, user delivery confirmation, completion. Clarification, requirement confirmation, prototype, and user feedback are enabled only when the risk assessment requires them.
- `standard`: intake, scope/risk check, clarification, user confirmation, PRD and three-role PRD review, design/test planning, readiness review, prototype or MVP preview, user feedback, implementation, verification, acceptance, user delivery confirmation, completion.
- `strict`: standard flow plus locked user-confirmed core outcomes, registered Must acceptance criteria, explicit database and release-plan artifacts, scoped source binding, semantic profile-based final-journey verification, and human approval checkpoints at readiness and acceptance.

The risk assessment recommends the lowest safe mode from explicit flags. A user-requested mode is a floor, and the selected mode must never be below the deterministic recommendation. Always perform the gap analysis; skip user questions only when no unresolved high-impact choice exists. Three or more distinct quick-level flags require at least `standard`; `weak_verification` combined with `user_visible` or `external_dependency` also requires at least `standard`. These explicit rules avoid opaque scoring while accounting for risk combinations.

Modes may escalate `micro → quick → standard → strict` when new evidence appears. Every role reports newly discovered risk with separate repository evidence and its originating work-item ID. `report-risk` gives one baseline/scope/origin a stable identity, so retries update instead of duplicating it. Workflow- or stage-scoped risk participates in mode escalation. An optional external capability such as publishing or paid acquisition uses `scope_kind=capability`; it remains isolated from core delivery and requires separate authorization and verification. Escalation is recommended, never silently applied. Resolution, withdrawal, constrained acceptance, and explicit escalation retain their existing evidence and authority rules.

## Artifacts

All durable artifacts belong under `docs/requirements/<workflow-id>/`. The state file is the index, not a substitute for the artifacts. Each role delegation is a persisted work item with stage, role, actor reference, attempt, input revision/hashes, lease, heartbeat, hard deadline, status, and content-addressed outputs. Role-owned artifacts and reviews are accepted only from a completed, unexpired item whose baseline is still current. Rewind supersedes affected attempts; late output is rejected.

The scope/risk artifact records in-scope and out-of-scope boundaries, observable acceptance, verification, checked gaps, risk flags, mode recommendation, selected mode, and conditional gates. A role authors this artifact before `assess-risk` registers it; CLI arguments are structured state inputs, not a substitute for the analysis document. Clarification evidence must cover questions, missing details, assumptions, and acceptance-criteria gaps. Requirement confirmation, preview feedback, and final delivery confirmation must record explicit user approval; inferred agreement is not enough. Prototype evidence must describe preview scope and how the user can inspect it.

Strict mode adds two protected baselines. `record-core-goals` stores user-confirmed `GOAL-*` outcomes before PRD work. `register-acceptance-criteria` binds Must `AC-*` entries to the current PRD hash. Engineering, testing, or product cannot later mark either baseline as mock-only, deferred, removed, replaced, or not applicable. A reduction requires a distinct `approve-scope-change` record with the approving user's name, rationale, affected IDs, and evidence. The default rewind remains the baseline stage. A user-approved impact analysis may name a later earliest affected stage, with a separate reason explaining why earlier artifacts remain valid; `AC-*` changes cannot skip verification and `GOAL-*` changes cannot skip acceptance.

## Decisions

At each configured gate, every required role submits an explicit verdict, distinct task/session reference, and completed review work item. Prefer `submit-gate-review`, which requires an expected state revision and idempotency key, then validates the complete role set, unique evidence/actors, verdict consistency, participant coverage, structured findings, and inline meeting before one state write. Reject requires a finding; approve cannot retain blocker/major findings. Findings are stably upserted into the issue ledger. Granular commands remain recovery interfaces but retain the same completed-work-item authorization.

In strict verification, prefer one `submit-verification` manifest with an expected state revision and idempotency key. It atomically records one clean committed delivery candidate, every Must-criterion verdict, and the matching journey from a completed testing work item. Candidate identity includes commit OID, tree OID, and sorted path/mode/blob manifest. Tests materialize those blobs, never ambient ignored or untracked bytes. Source exclusions and writable generated outputs are separate; only explicit `output_paths` may change.

Journey profiles cover `web`, `desktop`, `api`, `cli`, `library`, and `data` deliverables. Testers may truthfully record `pass`, `fail`, `blocked`, or `not_applicable`; required non-pass results are preserved but block advancement. Builds, screenshots, hardcoded URLs, source inspection, prototype approval, and developer self-tests do not substitute for executing the applicable final user journey.

Do not enter PRD, design, or coding from an unanalyzed one-sentence request. `scope_check` must first inspect actors, rules, boundaries, data/API effects, permissions, states, failures, compatibility, subjective choices, acceptance, and verification. Ask focused questions and require confirmation when material uncertainty exists; do not manufacture questions for a decisive low-risk task.

When preview is enabled, do not wait until final acceptance to show user-facing work. After readiness review, build the smallest meaningful preview and ask for user feedback. Record `approve`, `request_changes`, or `reject` explicitly. A change request or rejection preserves its evidence and rewinds to the affected scope, clarification, PRD, design, or prototype stage instead of continuing to final implementation.

No concrete mode can finish on product, developer, or tester confidence alone. After verification and any configured acceptance ceremony, show the user the result, implementation summary, and test evidence. Only unambiguous explicit approval completes the workflow. Criticism, a defect, mismatch, negative example, `request_changes`, or rejection preserves the decision and rewinds to the earliest affected stage before product edits. If the user might be diagnosing the workflow itself rather than asking to polish the sample, ask one focused question and make no product edit.

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

Create a structured meeting record only for a material decision, disagreement, scope change, defect triage, or accountable handoff. Routine status and passing checks do not create minutes. The atomic gate bundle's inline meeting is the durable gate record; standalone Markdown is a recovery or organizational option, not a redundant fourth artifact. Omit greetings, repetition, chain-of-thought, and raw transcripts.

Gate meeting notes summarize independent role reviews; they do not replace those reviews. A gate advances only when the recorded meeting covers all required roles, has an approved outcome, and snapshots the current decision evidence. Any later decision, material artifact change, new issue, issue resolution, or workflow reopen supersedes affected meeting notes and requires a fresh record.

## Change control

When an approved requirement changes:

1. Record the change as an issue or decision.
2. Return to the earliest affected stage.
3. Invalidate downstream gate decisions and artifacts as appropriate.
4. Update traceability and rerun affected tests.
5. Record a `change_control` meeting when multiple roles discuss the change.

Call `reopen` to the earliest affected stage before dispatching replacement work. Reopen supersedes downstream state and work items. Artifact commands require their own current stage, so they cannot accept a delayed earlier-stage result while silently rewinding. When multiple design artifacts share one new baseline, `record-artifact-bundle` validates all completed work-item outputs and records them atomically.

## Evidence

Statements such as “implemented”, “tested”, or “approved” require a path, command result, review record, or other inspectable evidence. Never use confidence language as evidence. Evidence hashes are rechecked when a gate is evaluated; changing an indexed artifact, review, meeting record, or human approval makes it stale until it is re-recorded and, where applicable, re-reviewed. Risk-report hashes are rechecked immediately before an escalation is accepted, and escalation approval must use separate evidence.

Micro, quick, and standard verification reports bind one content-addressed workspace candidate while excluding workflow state and requirement evidence. Strict binds an immutable Git commit/tree candidate and rejects ignored/untracked gaps, hidden index flags, incomplete or escaping symlinks, and submodules. Verification and later gates compare the same candidate identity; a passing command from a larger ambient worktree cannot validate a smaller delivery archive.

Verification commands are executed by the state tool against a disposable candidate rather than accepted as strings. Candidate inputs are kernel-enforced read-only: macOS uses Seatbelt and Linux uses a bubblewrap read-only mount namespace; if the applicable backend is unavailable, verification fails closed. Only prevalidated output roots and private scratch are writable, and output symlinks, hardlinks, special files, case collisions, or Unicode-normalization collisions are rejected. Each run is fail-fast, process-group time-bounded, and stored under `.ai-workflow/<id>/test-runs/`; state keeps sanitized commands, exit codes, durations, byte counts, output hashes, isolation metadata, and the bounded log hash. Output is streamed to disk, common credential formats are redacted from the retained log, and old unreferenced logs are pruned. Passing logs are not model context. The filesystem boundary does not block network calls, external services, or explicit host side effects outside file writes; those remain within the current user's authority.

The state script is not an authentication boundary. It requires distinct role task/session references and preserves them in downstream snapshots, which provides audit traceability and prevents accidental reuse but does not prove who controlled a session. Enforce reviewer independence operationally by delegating to separate agents, using unique review files, and preserving their unedited findings. Deterministic checks reject missing or trivial evidence but cannot prove that a document is correct.

## State integrity

State files use a versioned schema, semantic checksum, monotonic revision, atomic replacement, backup, and repository lock. The pointer binds workflow ID, revision, and status; a missing pointer recovers only one unique live workflow, while multiple live states fail closed. `list`, `activate`, `deactivate`, `abandon`, and backward-only `reopen` form the lifecycle. Candidate, work-item, lifecycle, artifact, runtime-provenance, review, assurance, risk, and delivery logic live in separate modules behind `workflow.py`. The plugin embeds payload/entry provenance and exposes `version`/`doctor`; equal-version/different-payload or tamper is a hard failure, while a source/runtime update requires reinstall and a new task. Direct state edits remain unsupported; use `audit-state` and explicit backup repair.

Use `overview` for handoffs and progress checks. It reports the active stage, whether advancement is currently allowed, missing evidence, open or carried issues, meeting-note count, and configured human approval gates.
