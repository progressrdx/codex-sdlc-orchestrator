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

The natural-language phrase is enough to open the workflow, but it is not treated as permission to build. The coordinator initializes the workflow with the friendly `start` entry, records your original request, and first moves into product-led clarification so missing details and ambiguous expectations are found before PRD, design, or code. `$sdlc-orchestrator` remains available when an explicit Skill invocation is preferred:

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
intake → clarification → requirement_confirmation
       → prd → prd_review → design → readiness_review
       → prototype → user_feedback
       → implementation → verification → acceptance → completed
```

- `quick` still requires clarification, user confirmation, prototype preview, and user feedback, but skips the full PRD stage.
- `strict` additionally requires explicit database-design and release-plan artifacts; they may be marked not applicable with justification.

PRD review, readiness review, and acceptance require independent role verdicts plus current meeting notes covering all required roles. Unresolved blockers prevent the workflow from advancing. User-facing work must be previewed before final implementation; if the user rejects the direction, the workflow reopens to the earliest affected stage.

Workflow state uses:

- Schema validation and migration from schema v1.
- A monotonic revision checked before every update.
- Atomic file replacement with flushed data.
- A repository-scoped cross-process writer lock.
- Live evidence hashes: changing an indexed artifact, review, meeting note, or human-approval file blocks further gate advancement until refreshed.
- Automatic rollback to the earliest affected stage when an upstream artifact changes.
- Required user confirmation before PRD/design/coding and required user feedback after prototype/MVP preview.
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
