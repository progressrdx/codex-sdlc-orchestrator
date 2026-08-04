# Multi-Role SDLC for Codex

An install-once Codex plugin that coordinates product, engineering, and testing roles through a formal software delivery workflow. It keeps persistent state, enforces independent review gates, and records concise cross-role meeting notes.

## Install once

Run this command on any machine with Codex installed:

```bash
codex plugin marketplace add progressrdx/multi-agent-role-work && codex plugin add multi-agent-role-work@personal
```

Start a new Codex task after installation. The plugin is then available in every project; no files need to be copied into those projects and no `AGENTS.md` or `.codex/config.toml` needs to be edited.

On first install or update, review and trust the plugin's lifecycle hooks when Codex prompts, then restart Codex. This is a one-time safety review: the hooks keep later messages attached to the active workflow and prevent accidental product edits outside prototype/implementation stages.

## Start in any project

Open the project in Codex and say:

```text
团队开发：实现会员积分过期功能。
```

`团队开发：<需求>` is the recommended entry. It opens requirement discovery, not implementation authorization. The coordinator records the text after the prefix as the original request, performs a structured requirement-gap and risk check, and recommends the lowest safe workflow mode before PRD, design, or code. It always checks for missing details; it asks the user only when an unresolved choice can materially change the result.

The prefix must introduce an actionable request. A discussion such as “团队开发和个人开发有什么区别” does not activate the workflow. `$sdlc-orchestrator` remains available as the advanced explicit entry:

```text
使用 $sdlc-orchestrator 开发会员积分过期功能。
```

You may also name a minimum mode when you already know the assurance level you need:

```text
团队开发（strict）：执行用户数据迁移，并在就绪评审和最终验收时由我人工批准。
```

To inspect or continue:

```text
继续当前正式研发流程。
当前流程进行到哪一步？
查看当前阻塞问题和待办事项。
```

When you temporarily switch topics, say “暂停当前研发流程”. Pausing preserves all evidence while stopping automatic workflow context and rejecting state changes; “继续当前正式研发流程” resumes at the same stage.

Those progress checks use the workflow `overview`, which summarizes the active stage, whether the gate can advance, missing evidence, open issues, meeting records, and human approval checkpoints.

Short continuation phrases work only when `.ai-workflow/active.yaml` exists. Without an active workflow, “继续” or “开始验收” alone never creates one.

Ordinary coding, explanation, and isolated-fix requests do not activate the formal workflow.

For a high-risk requirement, you can ask for human checkpoints without naming a mode; risk assessment may still recommend `strict`:

```text
团队开发：执行用户数据迁移，并要求在就绪评审和最终验收时由我人工批准。
```

The coordinator pauses at each configured checkpoint. AI role approvals never substitute for the named human authority.

## What it creates

The plugin stores only workflow outputs in the target project:

```text
.ai-workflow/
└── active.yaml

docs/requirements/<requirement-id>/
├── requirements and design artifacts
├── reviews/
└── meetings/
```

Meeting records preserve material product, engineering, and testing viewpoints, disagreements, decisions, rationale, owners, open questions, and next steps—not raw transcripts.

## Workflow

The default `standard` flow is:

```text
intake → scope_check → clarification → requirement_confirmation
       → prd → prd_review → design → readiness_review
       → prototype → user_feedback
       → implementation → verification → acceptance
       → delivery_confirmation → completed
```

- `micro` is the tracked path for explicit, localized, low-risk work: `intake → scope_check → implementation → verification → delivery_confirmation → completed`.
- `quick` skips the full PRD stage. Clarification, requirement confirmation, prototype preview, and user feedback are enabled only when scope, ambiguity, or user-visible judgment requires them.
- `strict` additionally locks user-confirmed `GOAL-*` outcomes, registers Must `AC-*` criteria, requires explicit database-design and release-plan artifacts, atomically binds verification to a scoped committed source revision, executes a profile-appropriate semantic final-user journey, and requires human approval at readiness and acceptance.

Every concrete mode ends with an explicit user delivery confirmation. Product, engineering, and testing approval cannot complete the workflow on the user's behalf.

Formal workflow routing is explicit and on demand. Start with `团队开发：<request>` or `$sdlc-orchestrator`; continue with phrases such as “继续团队开发” or “查看研发进度”. The plugin does not run a hook for ordinary user messages. At preview or delivery confirmation, criticism such as “这个结果不对” is treated as requested changes—not as approval or permission to silently edit the sample. A tool-level write guard runs only for `apply_patch`/Edit/Write operations and blocks product changes until the workflow has rewound to `prototype` or `implementation`; requirement evidence remains writable.

Natural-language starts use temporary `auto` mode. During `scope_check`, the coordinator must explicitly check actors/permissions, goals/scope, business rules/states, data/API effects, failures/edges, compatibility/rollout, subjective choices, and acceptance/verification. It records scope, exclusions, unresolved gaps, and risk flags, then recommends `micro`, `quick`, `standard`, or `strict`. API/data changes, cross-module behavior, security/privacy, migrations, production actions, and irreversible work raise the minimum mode. An explicitly requested mode is never silently downgraded.

The selected mode can grow with the work: `micro → quick → standard → strict`. When product, engineering, or testing reports a newly discovered risk, the state tool automatically recalculates the minimum safe mode. If the current mode is too weak, advancement stops and `overview` explains the risk and recommended upgrade. The mode changes only after explicit user approval; approval rewinds to `scope_check`, preserves the escalation record, and invalidates affected downstream evidence. A strict escalation automatically enables human approval at readiness and acceptance.

Strict mode prevents a team from silently replacing a confirmed live outcome with a mock-only MVP. Removing, deferring, replacing, or marking a core goal or Must criterion not applicable requires separate user-approved scope-change evidence. Acceptance is tied to the scoped source tested; later relevant code edits invalidate criterion verdicts and the final journey, while unrelated repository changes do not. Journey profiles support web, desktop, API, CLI, library, and data deliverables. A tester can record `fail`, `blocked`, or `not_applicable` truthfully; required non-pass results remain visible and block delivery.

Strict verification uses one manifest instead of a long chain of state calls:

```bash
workflow.py submit-verification \
  --manifest docs/requirements/<requirement-id>/08-verification-bundle.yaml
```

The manifest contains the reviewed source paths, actual build and test commands, every `AC-*` verdict, and the final-journey profile/checks. Granular recording commands remain available for recovery.

Enabled PRD review, readiness review, and acceptance gates require independent role verdicts plus current meeting notes covering all required roles. Unresolved blockers prevent the workflow from advancing. When preview is enabled, explicit user approval is required before implementation. A user `request_changes` or `reject` verdict is preserved and automatically rewinds the workflow to the affected stage.

Gate recording is also bundled. Instead of three separate role-decision commands followed by a meeting command, the coordinator normally submits one manifest:

```bash
workflow.py submit-gate-review \
  --manifest docs/requirements/<requirement-id>/reviews/readiness-bundle.yaml
```

The state changes only after the complete role set, distinct actor references and evidence, verdict consistency, and meeting record all validate.

Each role verdict carries a distinct Codex task/session reference. The reference is included in meeting and human-approval snapshots, preventing accidental use of one role task for multiple approvals. This provides traceability, not cryptographic proof of identity.

User-approved scope reductions remain conservative by default, but they can include an evidenced earliest impact stage. For example, deferring one external `AC-*` during acceptance can rewind only to verification when the user-approved record explains why the PRD, design, and implementation remain valid.

Workflow state uses:

- Schema validation and migration from schema v1.
- A monotonic revision checked before every update.
- Atomic file replacement with flushed data.
- A repository-scoped cross-process writer lock.
- A validated previous-state backup plus `audit-state` and explicit backup repair.
- Live evidence hashes: changing an indexed artifact, review, meeting note, or human-approval file blocks further gate advancement until refreshed.
- Source-live verification in every mode: micro, quick, and standard bind tracked and untracked product content while reusing clean Git index identities; strict binds committed reviewed scope. Product changes after testing invalidate delivery evidence.
- Command-backed verification: build/smoke and test commands run in a disposable repository snapshot with fail-fast process-group timeouts. Relative writes cannot alter the original workspace, and product-file mutations inside the snapshot are rejected even when the command fails.
- Streamed verification evidence: output is hashed without loading it all into memory; local logs are capped at 2 MB, commonly formatted credentials are redacted, and stale unreferenced logs are pruned.
- Mode-aware cost policy in `overview`: delta-only context, smoke tests before broad tests, an enforced per-run command ceiling, a visible role-handoff budget, no full passing logs, and only the roles required by the enabled gate.
- Automatic rollback to the earliest affected stage when an upstream artifact changes.
- Required user confirmation and preview feedback whenever those gates are enabled by the selected flow.
- Risk-based `micro`, `quick`, `standard`, and `strict` selection, with conditional clarification and preview gates for quick work.
- Evidence-backed automatic escalation recommendations that block unsafe continuation until the user approves a higher mode.
- First-class user feedback decisions: approve, request changes, or reject.
- Formal major-issue disposition: acceptance blocks on open major findings unless a named authority records an evidenced risk acceptance or scheduled deferral.
- Impact-scoped change control with conservative fallback.
- Distinct role task/session references bound into gate snapshots.
- Atomic gate-review bundles for role verdicts and meeting notes.

These are local consistency controls, not identity authentication or tamper-proof audit guarantees. See [SECURITY.md](SECURITY.md) and [THREAT_MODEL.md](THREAT_MODEL.md).

## Implementation architecture

The installed plugin keeps workflow behavior split by responsibility:

| Module | Responsibility |
|---|---|
| `workflow.py` | Workflow rules, shared evidence validation, state transitions, delivery commands, and compatibility wrappers. |
| `workflow_cli.py` | CLI parser definitions and the mutating-command registry. |
| `state_store.py` | Checksums, atomic writes, backups, and cross-process locking. |
| `command_runtime.py` | Shared compatibility binding between the facade and command modules. |
| `risk_policy.py` | Deterministic risk flags, safe-mode calculation, and escalation policy. |
| `risk_commands.py` | Scope assessment, discovered-risk lifecycle, escalation acceptance, and mode escalation commands. |
| `review_commands.py` | Role verdicts, atomic gate-review bundles, meeting records, and human-approval binding. |
| `assurance_commands.py` | Protected goals/criteria, scope changes, source binding, criterion verdicts, and user-journey verification. |
| `delivery_commands.py` | Preview feedback, final delivery confirmation, and issue resolution/disposition. |
| `source_policy.py` | Strict scoped-Git bindings plus tracked/untracked workspace bindings for other modes. |
| `execution_policy.py` | Mode-aware cost budgets, branch context, isolated fail-fast command execution, process cleanup, and bounded local logs. |

The public command names and state schema remain stable across this split. The small wrappers in `workflow.py` preserve existing integrations while the implementation modules can be tested and maintained independently.

## Assurance coverage and limits

| Concern | Current behavior | Boundary |
|---|---|---|
| Coordinator call volume | Gate reviews and strict verification use atomic bundle commands. | Granular commands remain available for recovery. |
| Source freshness | Every mode blocks delivery after post-test product edits. Strict Git metadata can be limited to reviewed delivery paths; other modes reuse clean Git index identities and hash dirty/untracked workspace content without requiring a commit. | Workflow/evidence paths are excluded; strict empty scope binds all other tracked paths. |
| Stage routing | Explicit workflow phrases and the coordinator Skill route formal work; no hook runs on ordinary user messages. A tool-level edit hook denies accidental product patches outside development stages. | The coordinator must invoke `overview` after routing; the edit hook requires one-time trust and is a guardrail, not a host security sandbox. |
| Token cost | Deterministic commands run outside the model; `overview` exposes a mode budget, verification command count is enforced, and role handoffs use deltas, hashes, and evidence paths. | Codex does not expose actual per-task token accounting to this plugin; the role-handoff ceiling remains coordinator-enforced, and semantic review still consumes tokens. |
| Role independence | Gate roles require distinct task/session references and evidence files. | References provide traceability, not cryptographic identity. |
| User satisfaction | Every concrete mode ends with explicit user delivery confirmation. | The tool cannot infer approval from silence or authenticate the human. |
| Final journey | Deliverable-specific profiles accept truthful pass, fail, blocked, and not-applicable results. | Required non-pass results block advancement. |
| Scope changes | Conservative rewind is the default; evidenced user-approved changes can select a safe later impact stage. | `AC-*` changes cannot skip verification and `GOAL-*` changes cannot skip acceptance. |
| State corruption | Checksummed atomic state keeps a validated backup with audit and explicit repair commands. | It does not solve Git merge conflicts or malicious host access. |
| Regression protection | The suite covers migrations, corruption recovery, escalation expiry, scoped source changes, atomic bundles, and local rewinds. | Repository-specific product behavior still needs project tests. |
| Documentation/versioning | README, Skill contract, manifest version, installed cache version, and remote source are updated together. | A new Codex task is required to load an updated installed Skill. |

If checksum or syntax corruption prevents normal commands, inspect and recover the last valid revision:

```bash
workflow.py audit-state
workflow.py repair-state --from-backup --confirm RESTORE
```

## Update or uninstall

```bash
codex plugin marketplace upgrade personal
codex plugin add multi-agent-role-work@personal
```

```bash
codex plugin remove multi-agent-role-work
```

## Development verification

```bash
python3 -m unittest discover -s tests -v
python3 /path/to/plugin-creator/scripts/validate_plugin.py plugins/multi-agent-role-work
```

The workflow state tool is a delivery-integrity guard, not an identity or security system. Task/session references improve traceability, while independent role agents and evidence-based reviews provide the practical separation of responsibilities.
