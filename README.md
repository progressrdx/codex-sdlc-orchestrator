# AI Project Manager for Codex

An install-once Codex plugin that keeps a project aligned with its goal, advances the work, verifies the result, and asks the user only for meaningful decisions. Its simple project view is backed by the existing persistent, risk-aware multi-role delivery engine.

## Install once

Run this command on any machine with Codex installed:

```bash
codex plugin marketplace add progressrdx/multi-agent-role-work && codex plugin add multi-agent-role-work@personal
```

Start a new Codex task after installation. The plugin is then available in every project; no files need to be copied into those projects and no `AGENTS.md` or `.codex/config.toml` needs to be edited.

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

Those progress checks use the user-facing `project` view. It shows the current goal, current focus, recent verified results, quality status, and anything that genuinely needs a user decision. Internal stages, modes, gates, role meetings, and cost controls remain available through the advanced `overview` diagnostic command.

Use `继续团队开发` to resume a paused workflow and `查看研发进度` to inspect it. Because the plugin installs no lifecycle hook, a bare “继续” is always ordinary conversation and never routes or resumes a formal workflow.

Clear continuation phrases work only when `.ai-workflow/active.yaml` exists. Without an active workflow, “继续团队开发” or “开始验收” reports that no workflow exists and never creates one.

Ordinary coding, explanation, and isolated-fix requests do not activate the formal workflow.

## What the user sees

The default project update is intentionally compact:

```text
目标：会员积分在配置的到期日失效
当前：正在开发已确认的功能
核心结果：
- [等待验证] 到期积分不再计入可用余额
最近完成：
- 实现方案已完成
- 质量检查计划已完成
可查看成果：
- 查看实现结果：docs/requirements/REQ-points/implementation.md
质量：最终质量检查尚未完成
需要你决定：暂无
下一步：我会继续推进，并在出现可体验结果或需要你判断时更新你。
```

Core-result states are derived from recorded goals, implementation evidence, verification, and final outcomes—never from a fabricated percentage. When a preview, implementation summary, quality report, journey report, or delivery result exists, the view exposes it as an inspectable action. Resolved problems are summarized separately from remaining risks.

The state machine, exact evidence, assurance mode, role handoffs, and verification bindings are still preserved. They are diagnostics and enforcement mechanisms rather than the default product language.

When compatible external design Skills are installed, the coordinator can add them to a relevant role assignment. Product Design is used only for explicit visual exploration, screenshot-grounded audits, faithful source cloning, or implementation of a selected visual target—not for ordinary frontend work merely because it has a UI. Frontend design guidance and web-interface review Skills remain optional; the bundled product, engineering, and testing roles continue normally when they are unavailable, and the coordinator discloses which specialized pass did not run.

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

Meeting records exist for material decisions, disagreements, defect triage, scope changes, and accountable handoffs—not routine status or raw transcripts. Gate bundles carry their own inline record, avoiding a redundant extra document.

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

Formal workflow routing is explicit and on demand. Start with `团队开发：<request>` or `$sdlc-orchestrator`; continue with phrases such as “继续团队开发” or “查看研发进度”. The plugin installs no lifecycle hooks and does not block ordinary source edits. At preview or delivery confirmation, criticism such as “这个结果不对” is treated as requested changes—not as approval or permission to silently edit the sample. The coordinator records the decision through the workflow command before changing product files; any later product change invalidates the verification binding and blocks delivery until verification runs again.

Natural-language starts use temporary `auto` mode. During `scope_check`, the coordinator must explicitly check actors/permissions, goals/scope, business rules/states, data/API effects, failures/edges, compatibility/rollout, subjective choices, and acceptance/verification. It records scope, exclusions, unresolved gaps, and risk flags, then recommends `micro`, `quick`, `standard`, or `strict`. API/data changes, cross-module behavior, security/privacy, migrations, production actions, and irreversible work raise the minimum mode. An explicitly requested mode is never silently downgraded.

The selected mode can grow with the work: `micro → quick → standard → strict`. New risk is stably keyed to its baseline, affected scope, and originating work item, so retries update rather than duplicate it. Optional external capabilities such as publishing or paid acquisition can be isolated from core delivery and require separate authorization and verification. Workflow escalation still blocks until explicit user approval.

Strict mode prevents a team from silently replacing a confirmed live outcome with a mock-only MVP. Removing, deferring, replacing, or marking a core goal or Must criterion not applicable requires separate user-approved scope-change evidence. Acceptance is tied to the scoped source tested; later relevant code edits invalidate criterion verdicts and the final journey, while unrelated repository changes do not. Journey profiles support web, desktop, API, CLI, library, and data deliverables. A tester can record `fail`, `blocked`, or `not_applicable` truthfully; required non-pass results remain visible and block delivery.

Strict verification uses one manifest instead of a long chain of state calls:

```bash
workflow.py submit-verification \
  --manifest docs/requirements/<requirement-id>/08-verification-bundle.yaml
```

The manifest names one completed testing work item, an expected state revision, and an idempotency key. It contains reviewed source paths, explicit writable output paths, actual build/test commands, every `AC-*` verdict, and the final journey. Granular commands remain available for recovery but require the same completed testing work-item outputs.

Enabled PRD review, readiness review, and acceptance gates require independent role verdicts plus current meeting notes covering all required roles. Unresolved blockers prevent the workflow from advancing. When preview is enabled, explicit user approval is required before implementation. A user `request_changes` or `reject` verdict is preserved and automatically rewinds the workflow to the affected stage.

Gate recording is also bundled. Instead of three separate role-decision commands followed by a meeting command, the coordinator normally submits one manifest:

```bash
workflow.py submit-gate-review \
  --manifest docs/requirements/<requirement-id>/reviews/readiness-bundle.yaml
```

The state changes only after the expected revision, idempotency key, complete role set, completed review work items, distinct actors/evidence, verdict consistency, structured findings, and inline meeting validate. Reject requires a finding; approve cannot retain blocker or major findings.

Every delegated role attempt is persisted before work starts with input revision/hashes, role/stage, attempt, actor reference, renewable lease, hard deadline, and content-addressed outputs. Expired, cancelled, superseded, wrong-stage, or stale-baseline output cannot become an artifact or approval. The handoff budget is enforced and excess attempts require repository evidence.

Each role verdict carries a distinct Codex task/session reference. The reference is included in meeting and human-approval snapshots, preventing accidental use of one role task for multiple approvals. This provides traceability, not cryptographic proof of identity.

User-approved scope reductions remain conservative by default, but they can include an evidenced earliest impact stage. For example, deferring one external `AC-*` during acceptance can rewind only to verification when the user-approved record explains why the PRD, design, and implementation remain valid.

Workflow state uses:

- Schema validation and migration from schema v1.
- A monotonic revision checked before every update.
- Atomic file replacement with flushed data.
- A repository-scoped cross-process writer lock.
- A validated previous-state backup plus `audit-state` and explicit backup repair.
- Live evidence hashes: changing an indexed artifact, review, meeting note, or human-approval file blocks further gate advancement until refreshed.
- Immutable delivery candidates: strict binds commit/tree plus a sorted path/mode/blob manifest; lightweight modes freeze a content-addressed workspace manifest. Ignored/untracked gaps, hidden index flags, incomplete symlinks, and submodules fail closed.
- Command-backed verification materializes only that candidate. Candidate inputs are kernel-enforced read-only with macOS Seatbelt or Linux bubblewrap; unavailable isolation fails closed. Source exclusions never grant write access, only prevalidated output roots may change, and output links or special files are rejected.
- Streamed verification evidence: output is hashed without loading it all into memory; local logs are capped at 2 MB, commonly formatted credentials are redacted, and stale unreferenced logs are pruned.
- Mode-aware cost policy in `overview`: delta-only context, smoke tests before broad tests, an enforced per-run command ceiling, a visible role-handoff budget, no full passing logs, and only the roles required by the enabled gate.
- Explicit backward-only reopen for upstream changes; downstream artifacts and work items are superseded before replacement work starts, and late output cannot trigger a silent rewind.
- Required user confirmation and preview feedback whenever those gates are enabled by the selected flow.
- Risk-based `micro`, `quick`, `standard`, and `strict` selection, with conditional clarification and preview gates for quick work.
- Evidence-backed automatic escalation recommendations that block unsafe continuation until the user approves a higher mode.
- First-class user feedback decisions: approve, request changes, or reject.
- Formal major-issue disposition: acceptance blocks on open major findings unless a named authority records an evidenced risk acceptance or scheduled deferral.
- Impact-scoped change control with conservative fallback.
- Distinct role task/session references bound into gate snapshots.
- Atomic gate-review bundles for role verdicts and meeting notes.
- Explicit lifecycle with deterministic pointer recovery, `list/activate/deactivate/abandon`, and terminal-state immutability.
- Embedded plugin provenance plus `version`/`doctor` for source/cache collisions, runtime tamper, and restart-required updates.

These are local consistency controls, not identity authentication or tamper-proof audit guarantees. See [SECURITY.md](SECURITY.md) and [THREAT_MODEL.md](THREAT_MODEL.md).

## Implementation architecture

The installed plugin keeps workflow behavior split by responsibility:

| Module | Responsibility |
|---|---|
| `workflow.py` | Shared workflow rules and compatibility facade. |
| `workflow_cli.py` | CLI parser definitions and the mutating-command registry. |
| `state_store.py` | Checksums, atomic writes, backups, and cross-process locking. |
| `delivery_candidate.py` | Immutable candidates, blob materialization, symlink closure, and mutation manifests. |
| `work_items.py` / `work_commands.py` | Role leases, attempts, baseline freshness, and output acceptance. |
| `stage_submission.py` | Expected-revision and idempotency receipts for atomic submissions. |
| `runtime_provenance.py` | Source/install/loaded identity and hard-failure diagnostics. |
| `lifecycle_commands.py` / `artifact_commands.py` | Workflow lifecycle and role-owned artifact handlers. |
| `command_runtime.py` | Shared compatibility binding between the facade and command modules. |
| `risk_policy.py` | Deterministic risk flags, safe-mode calculation, and escalation policy. |
| `risk_commands.py` | Scope assessment, discovered-risk lifecycle, escalation acceptance, and mode escalation commands. |
| `review_commands.py` | Role verdicts, atomic gate-review bundles, meeting records, and human-approval binding. |
| `assurance_commands.py` | Protected goals/criteria, scope changes, source binding, criterion verdicts, and user-journey verification. |
| `delivery_commands.py` | Preview feedback, final delivery confirmation, and issue resolution/disposition. |
| `source_policy.py` | Candidate identity and freshness bindings for strict and lightweight modes. |
| `execution_policy.py` | Mode-aware cost budgets, branch context, isolated fail-fast command execution, process cleanup, and bounded local logs. |

The public command names remain stable across this split. State is migrated to the current checksummed schema before use, while the small wrappers in `workflow.py` preserve existing integrations and let each implementation module be tested independently.

## Assurance coverage and limits

| Concern | Current behavior | Boundary |
|---|---|---|
| Coordinator call volume | Gate reviews and strict verification use atomic bundle commands. | Granular commands remain available for recovery. |
| Source freshness | Every mode blocks delivery after post-test product edits. Strict mode binds a committed tree; other modes bind a content-addressed workspace candidate without requiring a commit. | Workflow/evidence paths can be excluded from product scope, but exclusions never become writable output permissions. |
| Stage routing | Explicit workflow phrases and the coordinator Skill route formal work; the plugin installs no lifecycle hooks. | The coordinator must invoke `overview` after routing and follow the workflow state-machine rules. |
| Token cost | Deterministic commands run outside the model; verification and per-stage handoff budgets are enforced; handoffs use deltas, hashes, and paths. | Codex does not expose actual per-task token accounting; semantic review still consumes tokens. |
| Role independence | Gate roles require distinct task/session references and evidence files. | References provide traceability, not cryptographic identity. |
| User satisfaction | Every concrete mode ends with explicit user delivery confirmation. | The tool cannot infer approval from silence or authenticate the human. |
| Final journey | Deliverable-specific profiles accept truthful pass, fail, blocked, and not-applicable results. | Required non-pass results block advancement. |
| Scope changes | Conservative rewind is the default; evidenced user-approved changes can select a safe later impact stage. | `AC-*` changes cannot skip verification and `GOAL-*` changes cannot skip acceptance. |
| State corruption | Checksummed atomic state keeps a validated backup with audit and explicit repair commands. | It does not solve Git merge conflicts or malicious host access. |
| Regression protection | The suite covers migrations, corruption recovery, escalation expiry, scoped source changes, atomic bundles, and local rewinds. | Repository-specific product behavior still needs project tests. |
| Documentation/versioning | README, Skill contract, manifest version, generated provenance, and installed cache identity are checked together. | Publishing the source revision is a separate explicit Git action; a new Codex task is required to load an updated installed Skill. |
| Runtime identity | Embedded payload/entry hashes and `doctor` distinguish source-newer, collision, tamper, unavailable source, and restart-required. | Host compromise remains outside the plugin trust boundary. |

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

For local diagnostics, `workflow.py overview` exposes the internal workflow state. For the normal user-facing update, use `workflow.py project` or `workflow.py project --json`.

The workflow state tool is a delivery-integrity guard, not an identity or security system. Task/session references improve traceability, while independent role agents and evidence-based reviews provide the practical separation of responsibilities.
