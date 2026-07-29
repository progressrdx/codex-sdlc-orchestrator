# Multi-Role SDLC for Codex

An install-once Codex plugin that coordinates product, engineering, and testing roles through a formal software delivery workflow. It keeps persistent state, enforces independent review gates, and records concise cross-role meeting notes.

## Install once

Run this command on any machine with Codex installed:

```bash
codex plugin marketplace add progressrdx/multi-agent-role-work && codex plugin add multi-agent-role-work@personal
```

Start a new Codex task after installation. The plugin is then available in every project; no files need to be copied into those projects and no `AGENTS.md` or `.codex/config.toml` needs to be edited.

## Start in any project

Open the project in Codex and say:

```text
启动标准研发流程：实现会员积分过期功能。
```

The natural-language phrase is enough to open the workflow, but it is not treated as permission to build. The coordinator records the original request, performs a structured requirement-gap and risk check, and recommends the lowest safe workflow mode before PRD, design, or code. It always checks for missing details; it asks the user only when an unresolved choice can materially change the result. `$sdlc-orchestrator` remains available when an explicit Skill invocation is preferred:

```text
使用 $sdlc-orchestrator 启动标准研发流程：实现会员积分过期功能。
```

To inspect or continue:

```text
继续当前正式研发流程。
当前流程进行到哪一步？
查看当前阻塞问题和待办事项。
```

Those progress checks use the workflow `overview`, which summarizes the active stage, whether the gate can advance, missing evidence, open issues, meeting records, and human approval checkpoints.

Ordinary coding, explanation, and isolated-fix requests do not activate the formal workflow.

For a high-risk requirement, ask for human checkpoints explicitly:

```text
启动严格研发流程，并要求在就绪评审和最终验收时由我人工批准：执行用户数据迁移。
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
       → implementation → verification → acceptance → completed
```

- `micro` is the tracked path for explicit, localized, low-risk work: `intake → scope_check → implementation → verification → completed`.
- `quick` skips the full PRD stage. Clarification, requirement confirmation, prototype preview, and user feedback are enabled only when scope, ambiguity, or user-visible judgment requires them.
- `strict` additionally requires explicit database-design and release-plan artifacts plus human approval at readiness and acceptance; the artifacts may be marked not applicable with justification.

Natural-language starts use temporary `auto` mode. During `scope_check`, the coordinator must explicitly check actors/permissions, goals/scope, business rules/states, data/API effects, failures/edges, compatibility/rollout, subjective choices, and acceptance/verification. It records scope, exclusions, unresolved gaps, and risk flags, then recommends `micro`, `quick`, `standard`, or `strict`. API/data changes, cross-module behavior, security/privacy, migrations, production actions, and irreversible work raise the minimum mode. An explicitly requested mode is never silently downgraded.

The selected mode can grow with the work: `micro → quick → standard → strict`. When product, engineering, or testing reports a newly discovered risk, the state tool automatically recalculates the minimum safe mode. If the current mode is too weak, advancement stops and `overview` explains the risk and recommended upgrade. The mode changes only after explicit user approval; approval rewinds to `scope_check`, preserves the escalation record, and invalidates affected downstream evidence. A strict escalation automatically enables human approval at readiness and acceptance.

Enabled PRD review, readiness review, and acceptance gates require independent role verdicts plus current meeting notes covering all required roles. Unresolved blockers prevent the workflow from advancing. When preview is enabled, explicit user approval is required before implementation. A user `request_changes` or `reject` verdict is preserved and automatically rewinds the workflow to the affected stage.

Workflow state uses:

- Schema validation and migration from schema v1.
- A monotonic revision checked before every update.
- Atomic file replacement with flushed data.
- A repository-scoped cross-process writer lock.
- Live evidence hashes: changing an indexed artifact, review, meeting note, or human-approval file blocks further gate advancement until refreshed.
- Automatic rollback to the earliest affected stage when an upstream artifact changes.
- Required user confirmation and preview feedback whenever those gates are enabled by the selected flow.
- Risk-based `micro`, `quick`, `standard`, and `strict` selection, with conditional clarification and preview gates for quick work.
- Evidence-backed automatic escalation recommendations that block unsafe continuation until the user approves a higher mode.
- First-class user feedback decisions: approve, request changes, or reject.
- Formal major-issue disposition: acceptance blocks on open major findings unless a named authority records an evidenced risk acceptance or scheduled deferral.

These are local consistency controls, not identity authentication or tamper-proof audit guarantees. See [SECURITY.md](SECURITY.md) and [THREAT_MODEL.md](THREAT_MODEL.md).

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

The workflow state tool is a delivery-integrity guard, not an identity or security system. Independent role agents and evidence-based reviews provide the practical separation of responsibilities.
