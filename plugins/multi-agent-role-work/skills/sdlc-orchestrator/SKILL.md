---
name: sdlc-orchestrator
description: "Start, create, or keep a project aligned with its goal: 开始一个新项目, 开启一个新项目, 创建新项目, 我想做一个项目, 帮我做一个项目, 开始项目：具体目标, 继续推进当前项目, 项目有没有跑偏, 查看项目进展, 调整项目目标, or explicit $sdlc-orchestrator use. Once Project Compass has activated in the current task or the user is referring to its active project, keep using it for every project follow-up—including ordinary-sounding questions, explanations, bug reports, isolated fixes, testing requests, feedback, and acceptance—so the branded status and safeguards do not disappear between turns. Read state first, keep delivery mechanics internal, and surface only goal alignment, outcomes, quality, and meaningful user decisions. Do not use for unrelated ordinary questions or isolated work outside an active Project Compass project."
---

# Keep the project aligned with its goal

Keep the main thread focused on the user's goal, whether the work is still aligned, observable outcomes, quality, and decisions that genuinely need the user. Treat stages, modes, gates, roles, evidence bindings, and state transitions as internal implementation details unless the user explicitly asks for technical diagnostics. Delegate bounded work to independent role subagents and explicitly name the bundled phase Skill in every delegation prompt. The plugin must work without project-local Skills, custom agents, `.codex/config.toml`, or `AGENTS.md` changes.

## Visible activation signature

The first user-facing message in each routed Project Compass turn must begin with this stable identity block before any question, update, or result:

```markdown
### Project Compass
**项目守航已开启**
```

Follow it with one short sentence explaining the immediate value, such as “我会持续检查项目是否偏离目标，发现变化时先向你说明。” Never omit, rename, paraphrase, or bury this first-turn identity block. Its presence is the user's confirmation that the plugin was actually invoked; if the block is absent, treat the experience as an ordinary Codex response rather than a Project Compass response. Show the activation text exactly once per user turn.

The final response of every routed turn must retain a persistent, compact Project Compass result card. Begin it with `### Project Compass`, then a bold plain-language status such as `**方向一致，正在推进**`, `**需要你决定**`, `**发现偏离风险**`, or `**本轮目标已完成**`. Include `目标`, `本轮结果`, and `你需要做` in concise user language; write `无需操作` when nothing requires the user. If the first response is also the final response, combine the activation text and result fields in one card instead of rendering two cards. If commentary preceded the final response, repeat the Project Compass brand header in the final card but do not repeat `项目守航已开启`. The persistent final card is required because progress commentary may be collapsed after the turn. Do not call either block a native card or imply that Skill-authored Markdown is host-rendered plugin UI.

## User-visible operating contract

- Use the language of the user's project request for all user-facing messages and generated project documents. A Chinese request means Chinese-first requirements, design, review, testing, meeting, and delivery artifacts; preserve English identifiers only where machines require them. English requests remain English.
- Keep the same turn running through safe internal steps. Do not end a turn merely because a document needs a heading, identifier, hash refresh, format correction, state registration, or another recoverable internal action. Fix it, validate it, and continue.
- Stop only for a meaningful user decision, an inspectable preview that genuinely needs direction approval, a verified result needing delivery confirmation, an authorization/safety boundary, an unrecoverable external blocker, or completed work. When stopping, state `为什么停`, `是否需要你操作`, and the exact decision or input needed. Never ask the user to send “继续” for internal mechanics.
- At every document or preview confirmation, include a short stage summary in the same message: what was completed, the key conclusion, any important change or limitation, and exactly what the user is confirming. Keep it concise enough to understand without opening the full document.
- Before asking the user to test or inspect anything, classify the work as `自动验证`, `需要授权`, or `主观验收`. If Browser, Computer Use, CLI, an API, tests, media-element state, logs, screenshots, or another available programmatic method can verify it, run that verification yourself and report the evidence. Never ask the user to click, search, play media, check persistence, open a link, or report whether a machine-observable behavior works merely to substitute for automated QA.
- Ask the user only for a meaningful authorization or human judgment: installation/download/network permission, destructive or irreversible action, legal/privacy/rights decisions, a product or creative preference, low-confidence semantic interpretation after automated analysis was attempted, or final subjective acceptance. When a required tool is missing, ask only for permission to install or download it and continue automatically after approval; do not transfer the tool's analysis task to the user. If every in-scope automated route is genuinely blocked, state what was attempted and why it is inaccessible before requesting the smallest possible manual check.
- Delivery confirmation asks whether an already programmatically verified result meets the user's goal; it is not permission to outsource functional testing to the user.
- Treat a prototype, fixture, mock, placeholder, registration shell, or deterministic demo as evidence about direction only. Never call it a finished feature, formal implementation, intelligent analysis, or achieved core value. Explicitly name which core capability is still absent.
- Before claiming the project is on track, compare the inspectable behavior—not only documents, reviews, or state transitions—with the recorded goal and completion standard. If the user can only exercise scaffolding while the goal requires real semantics, label it as a possible drift or incomplete proof and correct course before further ceremony.
- Keep only the current effective product, design, testing, and preview documents in the main requirement directory. After a replacement baseline is successfully recorded, preserve superseded documents under `docs/requirements/<workflow-id>/_archive/<change-or-archive-id>/` through `archive-documents --manifest ...`; never delete historical evidence by default. The archive index must identify the reason and replacement document. Archived documents are history only: exclude them from current summaries, goal interpretation, role context, and user-facing document lists. Never archive an active artifact, and never move files by hand in a way that breaks recorded evidence paths.
- Prefer one compact update per meaningful outcome. Do not repeat the activation text or restate detailed progress in commentary and the final response; the required persistent final Project Compass card should summarize the outcome rather than copy the commentary.

## Start or resume

Within an already active project, after reading state and before choosing a handoff or responding to conflicting evidence, read [coordination-judgment.md](references/coordination-judgment.md). Route the unresolved decision to its responsible role and seek the smallest sufficient evidence; this guidance does not activate workflows or override stage, authorization, independence, or execution-budget rules.

1. Locate the repository root.
2. Resolve this Skill's own directory from the loaded `SKILL.md` path and run `python3 <skill-dir>/scripts/workflow.py --root <repository-root> status`. Never assume the Skill lives inside the target repository.
3. Treat `开始一个新项目`, `开启一个新项目`, `创建新项目`, and equivalent first-person requests such as `我想做一个项目` or `帮我做一个项目` as friendly discovery entries. When no goal is included, show the activation signature, say “我会持续检查项目是否偏离目标，发现变化时先向你说明。”, then ask only “你想完成什么？像平时聊天一样描述即可。” Do not initialize state yet. Treat an actionable `开始项目：<goal>` or equivalent request to keep a named goal moving without drifting as an explicit project start. Pass the goal to `start --request` without asking the user to repeat it. The legacy `团队开发：<request>` and direct `$sdlc-orchestrator` invocation remain advanced compatibility entries, not the default product language. Merely discussing project management does not activate the workflow.
4. If no workflow exists and the user explicitly asked to start a project with a concrete goal, initialize it with `start --request ... --mode auto` unless the user explicitly chose an assurance level. Add `--title ...` only when the user gives a better short title. Add `--require-human-approval <gate>` for each configured human checkpoint.
   `start` safely initializes Git when the target is not already covered by a repository. Do not create a baseline commit, change branches/remotes, or include existing uncommitted work without explicit user direction. If Git is unavailable, surface the loss of version protection without blocking goal discovery.
5. Treat an explicitly requested mode as a minimum floor. Natural-language requests without a mode always start in `auto`; determine the lowest safe concrete mode during scope analysis.
6. Route clear project phrases such as “继续推进当前项目”, “项目有没有跑偏”, “查看项目进展”, “调整项目目标”, and “确认最终结果”. After Project Compass has activated in the current task, keep routing every follow-up that refers to the same project, including short questions, explanations, defect reports, isolated fixes, testing requests, preview feedback, and acceptance. A bare “继续” remains ordinary conversation only when neither the current task context nor an active project reference identifies a Project Compass project. Without active state, even a clear continuation phrase reports that no project exists and never creates one.
   If the user explicitly pauses the project, run `pause --reason ...`; paused state preserves evidence and rejects delivery mutations. Run `resume` only for an explicit project continuation such as “继续推进当前项目”.
7. On every routed project turn, run `prepare-turn --json` before `overview --json`, assigning work, or writing files. `prepare-turn` adopts a compatible installed runtime, safely initializes Git for an existing unprotected project, and rejects source files changed after the last recorded state update without an active role attempt. If it reports `reconciliation_required`, do not modify the product: explain that Project Compass found work outside its recorded project state, then reopen or reconcile the earliest affected stage before continuing. Do not infer internal state from the conversation, a prior summary, or the user's wording. Begin the turn with the visible activation signature, then use `project` for the user-facing update; lead with the goal-alignment signal, version protection, result maturity, resolved problems, and available preview/report actions, making repository targets clickable when the client supports file links. Clearly say whether user action is required. Do not expose SDLC, modes, stages, gates, role meetings, evidence keys, or cost policy unless the user explicitly asks for advanced diagnostics. The plugin installs no lifecycle hooks; unrelated ordinary conversation must remain unaffected.
8. Fail closed when this Skill's loaded directory or `workflow.py` no longer exists after a plugin reinstall. Never bypass the missing Skill by manually reading `.ai-workflow`, editing product files, or approximating the workflow from memory. Locate the currently installed `multi-agent-role-work` runtime, read its replacement `sdlc-orchestrator/SKILL.md` completely, run its `version` and `prepare-turn`, and continue only if those checks succeed. Otherwise ask the user to start a new task; make no project change in the stale task.
9. Treat `start` as opening scope and risk analysis, not permission to build. Advance from intake to `scope_check`, read [scope-risk-template.md](assets/scope-risk-template.md), and inspect the request and repository before asking questions or selecting a mode.
10. Do not initialize a formal workflow from an ordinary coding request.

At `scope_check`, always analyze every `assess-risk --checked-area` category: actors/permissions, goals/scope, business rules/states, data/API effects, failures/edges, compatibility/rollout, subjective choices, and acceptance/verification. This thinking is mandatory; user questions are conditional. If no unresolved high-impact gap exists, record that conclusion and avoid ceremonial questions. Author the complete scope/risk artifact from [scope-risk-template.md](assets/scope-risk-template.md), then register that existing evidence with `assess-risk --evidence`; the state command must not author the assessment. Present the user-visible impact and any decision needed, and never select a mode below the deterministic safe minimum. State the internal mode only when the user explicitly asks for advanced diagnostics or when a change in assurance materially affects user behavior. An explicitly requested mode is a floor.

Before leaving `scope_check`, also settle or explicitly defer these product-shaping facts: the real user launch path, local/offline versus cloud or paid analysis, required external tools/models and their install/network/privacy cost, the language of generated documents, and which common capabilities should be researched for reuse. Perform a focused market/open-source scan before designing a generic foundation; record why each relevant capability is reused, adapted, or built. Do not wait until implementation to discover a decision that changes the architecture or user promise.

If any role discovers a new risk, preserve a substantive risk record and call `report-risk`. The state tool combines current and newly reported flags, including documented combination rules, calculates the minimum safe mode, and blocks every transition with `escalation_required` when the current mode is too weak. Present the report, affected workflow cost, and recommended mode to the user. If later evidence removes the risk, use `resolve-risk` with a distinct resolver and verifier, or `withdraw-risk` only when the original reporter or user retracts a mistaken report; both require separate evidence and recompute the blocker. A named human may explicitly accept a reversible, non-sensitive escalation risk through `accept-escalation-risk` with rationale, separate evidence, and an expiry; this keeps the current mode but marks assurance as reduced. Never permit that disposition for security/privacy, irreversible, migration, or production-release flags. Otherwise, only after explicit approval, preserve separate approval evidence and call `escalate-mode`; it switches mode, rewinds to `scope_check`, invalidates downstream evidence, and requires a refreshed baseline. Do not silently escalate effort or continue under a weaker flow.

Require a human checkpoint for destructive data changes, permission changes, production release authorization, security exceptions, legal/compliance decisions, or another irreversible/high-impact action. Use `readiness_review` when authorization is needed before implementation and `acceptance` when authorization is needed before final delivery. Tell the user which checkpoints were configured.

Read [workflow-contract.md](references/workflow-contract.md) before the first state transition in a workflow.
Use [meeting-notes-template.md](assets/meeting-notes-template.md) only when a material cross-role decision, disagreement, defect triage, scope change, or ownership handoff is not already captured by an atomic gate bundle. Do not create minutes for routine status updates or passing checks.
Use [gate-review-bundle-template.yaml](assets/gate-review-bundle-template.yaml) for PRD, readiness, and acceptance gate reviews.
Use [design-artifact-bundle-template.yaml](assets/design-artifact-bundle-template.yaml) when design outputs share one baseline.
For a project with material visual or interaction direction, read [visual-capability-routing.md](references/visual-capability-routing.md) before assigning `design`, `prototype`, or visual verification work.
In strict mode, use [core-goals-template.md](assets/core-goals-template.md) at requirement confirmation, [final-user-journey-template.md](assets/final-user-journey-template.md) during verification, and [verification-bundle-template.yaml](assets/verification-bundle-template.yaml) to submit the source binding, all criterion verdicts, and the journey result atomically.

## Route by stage

| Stage | Assignment |
|---|---|
| `intake` | Capture the raw request and advance to `scope_check` if the formal workflow was explicit. |
| `scope_check` | Perform structured requirement-gap and risk analysis, recommend/select the mode, and configure conditional quick gates with `assess-risk`. |
| `clarification` | Spawn a `product_manager` task with `$sdlc-product`; require missing-point analysis and focused user questions before recording `clarification_questions`. |
| `requirement_confirmation` | Present a concise stage summary plus the synthesized understanding and unresolved choices; record `requirement_confirmation` only after explicit user confirmation. In strict mode, lock the confirmed `GOAL-*` outcomes with `record-core-goals`. |
| `prd` | Spawn a `product_manager` task with `$sdlc-product`. In strict mode register every Must `AC-*` from the current PRD. |
| `prd_review` | Spawn `product_manager`, `developer`, and `tester` tasks independently with `$sdlc-review`; wait, synthesize disagreements, then prefer one `submit-gate-review` bundle for all verdicts and meeting notes. |
| `design` | Spawn a `developer` task with `$sdlc-engineering` and a `tester` task with `$sdlc-testing`. For materially visual or interaction-led work, first spawn a `product_manager` task with `$sdlc-product` to produce the visual-direction output; engineering must bind and consume it. Parallelize only work whose inputs and writes do not overlap. |
| `readiness_review` | Spawn every required role task independently with `$sdlc-review`; submit their verdicts and the meeting atomically. |
| `prototype` | Spawn a `developer` task with `$sdlc-engineering` to create the smallest inspectable prototype, MVP, screenshot, or demo. For materially visual work, attach available `$frontend-design` and/or `$ui-ux-pro-max`, require rendered narrow/wide evidence and complete relevant states, and preserve the selected visual-direction binding. |
| `user_feedback` | Present the prototype with a concise summary of what it proves, what it does not yet do, and the exact direction decision; use `record-user-feedback`. Only unambiguous explicit approval unlocks implementation. Criticism, a defect, mismatch, or change request is `request_changes`/`reject` and must be recorded before edits. |
| `implementation` | Spawn a `developer` task with `$sdlc-engineering`. |
| `verification` | Spawn a `tester` task with `$sdlc-testing`; send confirmed defects to a `developer` task. For materially visual work, attach available `$product-design:audit` and/or `$web-design-guidelines` and require screenshot-grounded visual-quality evidence. In strict mode prefer one `submit-verification` bundle that binds the scoped committed source, every criterion verdict, and the profile-appropriate final journey. |
| `acceptance` | Spawn all required role tasks with `$sdlc-review`; product checks each confirmed core outcome, tester checks current-source journey evidence, developer answers technical findings, and the coordinator submits one gate-review bundle. |
| `delivery_confirmation` | In every mode, show the user the working result, concise stage summary, actual launch path, core-value evidence, limitations, and test evidence. Only unambiguous explicit approval completes delivery. Record criticism, defects, mismatch, negative examples, or requested changes with `record-delivery-confirmation --verdict request_changes` before any product edit, selecting the earliest affected stage. |

Use a role-named subagent task and include the role boundary plus the explicit bundled `$sdlc-*` Skill in its prompt. Before naming an optional external Skill, confirm that its exact name appears in the current runtime's available Skill list. Use Product Design only when the user explicitly requests it or the assigned work is primarily visual exploration, screenshot-grounded UX audit, faithful source cloning, or implementation of a selected visual target; ordinary frontend implementation does not qualify by itself. `$frontend-design`, `$ui-ux-pro-max`, and `$web-design-guidelines` may augment relevant frontend work when available. Missing optional Skills never block the formal workflow: continue with the bundled role Skill and disclose the reduced capability. Project custom agents and optional Skills may help, but the workflow must never depend on them. Never omit the bundled role Skill and rely on the task name alone.

Do not equate `user_visible` with materially visual. A CLI message, API response, or background workflow can be user-visible without needing visual direction. Activate the visual capability chain only when typography, color, composition, density, imagery, motion, responsive layout, or interaction presentation can materially affect user judgment. Record that classification in the scope/risk evidence.

Apply the `overview` execution policy to control cost. Treat its role-handoff count as the default per-stage ceiling and its verification-command count as a tool-enforced limit; exceed the handoff ceiling only for newly evidenced risk or explicit user direction, and explain why. Pass role agents the current decision summary, affected criteria, changed paths, and evidence paths—not the full transcript or complete passing logs. Run deterministic smoke/focused tests before broad semantic review, stop on the first failure, and expand only when the selected mode or observed risk requires it.

Before every role delegation, call `begin-work` with the exact role, canonical task reference, hard deadline, and renewable lease. Heartbeat long-running assignments, cancel or time out abandoned attempts, then call `complete-work` with every repository output before recording it. Role-owned artifacts, reviews, and strict verification are rejected unless their exact bytes come from a current completed work item. If the input baseline changes or the workflow rewinds, dispatch a new attempt; never accept a late result from the superseded attempt. The CLI enforces the per-stage handoff budget and requires repository evidence for any override.

For a role review, run `check-review-evidence --gate ... --role ... --verdict ... --path ...` immediately after the role returns and before `complete-work` or bundle assembly. Correct schema, headings, identifiers, and bilingual marker problems before expensive review orchestration. A presentation-only correction that does not change the substantive verdict or reviewed baseline does not justify asking the user to continue or rerunning unrelated product work.

Only route stages present in the state's `flow_stages`. In `micro`, assign implementation to engineering and verification to an independent tester, then obtain lightweight user delivery confirmation; do not invent product work, prototype work, role gates, or meetings that the selected flow omits.

## Enforce gates

- Record artifacts only after checking that the referenced path exists.
- When two or more artifacts in one design baseline change together, use `record-artifact-bundle --manifest <repository-yaml-or-json>` instead of sequential `record-artifact` calls. Each role-owned item includes `work_item_id`. Replacement baselines require an explicit `reopen` first; the tool never accepts late output by silently rewinding after the fact.
- Do not advance past `scope_check` without a current structured risk assessment and task baseline. Never treat a short request as proof that no gaps or risks exist.
- When a role reports scope expansion, API/data impact, business ambiguity, weak verification, external dependency, systemic failure, security/privacy, migration, production, or irreversible risk, call `report-risk --origin-work-item ... --scope-kind ... --affected-scope ...` before continuing. Never hide a discovered trigger inside an implementation summary. Use `scope-kind capability` for an optional external action such as publishing or paid acquisition; it stays isolated from the core product flow and must be authorized and verified separately.
- Treat `escalation_required` as a hard stop. Do not call `escalate-mode` until the user or named authority explicitly approves the displayed risk evidence and target mode. Never choose a target below the recommendation.
- Close a risk only with separate disposition evidence. `resolve-risk` requires different resolver and verifier identities; `withdraw-risk` is limited to the original reporter or user. Never edit state statuses directly.
- Treat `accept-escalation-risk` as a constrained exception, not normal completion: require a named human, rationale, expiry, separate evidence, and disclose reduced assurance. Never use it for security/privacy, irreversible, migration, or production-release risk.
- Do not advance past `clarification` until the product role has identified missing details, ambiguity, assumptions, and acceptance-criteria gaps. The coordinator should ask only the high-impact questions needed to avoid wasted downstream work.
- Do not advance past `requirement_confirmation` until the user explicitly confirms the synthesized requirement understanding.
- In strict mode, preserve the user's essential outcomes as `GOAL-*`. Do not advance without `record-core-goals`, and never let later roles redefine those goals as mock-only implementation boundaries.
- Register strict Must criteria from the current PRD. A missing verdict, `fail`, or `blocked` blocks acceptance. `not_applicable`, deferral, removal, or replacement is valid only through `approve-scope-change` with separate explicit user evidence naming the affected IDs.
- Scope changes rewind conservatively by default. Use `--impact-stage` only when the approving evidence names the earliest affected stage and `--impact-reason` explains why earlier PRD/design/implementation evidence remains valid. Never choose a stage after verification for an `AC-*` change or after acceptance for a `GOAL-*` change.
- When `user_feedback` is enabled, do not advance until the user has inspected a prototype, MVP, screenshot, demo, or equivalent preview and explicitly approves the direction through `record-user-feedback --verdict approve`.
- No mode completes on AI review alone. Show the verified result and evidence to the user and require `record-delivery-confirmation --verdict approve`; requested changes rewind to implementation by default.
- At `user_feedback` and `delivery_confirmation`, classify the user's intent before acting. A complaint or example of process/product failure is not permission to silently polish the sample. If it is ambiguous whether the user wants the delivered product changed or is diagnosing the workflow/plugin itself, ask one focused question and do not edit either product.
- If the user rejects the preview, preserve the feedback and reopen to the earliest affected stage instead of continuing toward final verification.
- Put every review finding in the gate manifest as structured severity, owner, and summary. A reject requires at least one finding; approve cannot retain blocker/major findings. The tool upserts these findings into the issue ledger with stable keys, so prose cannot silently bypass issue tracking.
- At acceptance, an open `major` issue also blocks delivery. Resolve it, or record an evidenced `accepted_risk` or `deferred` disposition with the named human authority; deferred issues require a due date.
- Preserve a concise meeting record only for a material cross-role decision, disagreement, defect triage, scope change, or ownership handoff. The inline gate bundle is the meeting record for gate reviews; do not author a redundant fourth file or store a raw transcript.
- Record every role verdict with the canonical subagent task/session identifier as `--actor-ref`. The state tool rejects one reference reused by different roles at the same gate and binds the references into meeting and human-approval snapshots. This is traceability, not cryptographic authentication.
- Record gate meetings only after collecting independent role verdicts. Prefer one `submit-gate-review` manifest containing exactly the required roles, distinct actor references/evidence, and the synthesized meeting record. Validation is atomic: an invalid role or meeting leaves the prior gate state unchanged.
- When an indexed upstream artifact must change, explicitly `reopen` the earliest affected stage before dispatching replacement work. Reopen supersedes downstream artifacts, reviews, and work items; a command at a later stage cannot silently install an earlier baseline.
- Evidence is live: if an indexed artifact, review, meeting note, or human approval file changes after recording, its hash no longer matches and the gate cannot advance until it is recorded and reviewed again.
- Verification is source-live and command-backed in every concrete mode. Strict mode constructs one immutable delivery candidate from the exact commit/tree/path-mode-blob manifest and materializes tests only from those blobs; lightweight modes freeze a content-addressed workspace candidate. Ignored, untracked, hidden-index, escaping-symlink, submodule, path-collision, and candidate-mismatch gaps fail closed. Candidate inputs are kernel-enforced read-only with macOS Seatbelt or Linux bubblewrap; an unavailable backend fails closed. Source exclusions do not grant write permission, and only prevalidated `output_paths` may change; output links and special files are rejected. Any later candidate change blocks delivery. This is not a network, credential, process, or external-service sandbox, so reject those side effects unless separately authorized.
- Select the final-journey profile that matches the deliverable (`web`, `desktop`, `api`, `cli`, `library`, or `data`). Record `fail`, `blocked`, or `not_applicable` truthfully; required non-pass results remain stored and block advancement instead of forcing a false all-pass report.
- The final journey must test actual semantics and actions appropriate to the profile. A build, screenshot, source inspection, or prototype approval is insufficient.
- Never edit `state.yaml` directly. Schema 11 state includes an integrity checksum and unsupported manual edits fail closed. Use `audit-state`; `repair-state --from-backup --confirm RESTORE` is allowed only when the current state is corrupt and the automatic backup, identity, live-owner, pointer, and provenance checks all pass. It cannot roll back any valid active or terminal state. Use `list`, `activate`, `deactivate`, or `abandon` for multi-workflow lifecycle; completed/abandoned workflows are immutable except for explicit backward `reopen`. Pointer loss recovers only a unique live owner and multiple live states fail closed.
- Run `version` when identifying the executing plugin and `doctor --source-root <editable-plugin>` when source/cache behavior differs. `VERSION_COLLISION` and `RUNTIME_TAMPERED` are hard failures; reinstall and start a new task rather than guessing which payload ran.
- Never edit project code directly from a routed follow-up, even when the request sounds like an isolated fix. First run `prepare-turn`, then use the active stage, a persisted role work item, and the required verification route. A successful syntax check, unit test, API probe, or initial media timestamp does not justify user acceptance when the observable browser journey can be executed programmatically; exercise the full claimed interaction before asking for subjective acceptance.
- Record design coordination as `design_sync`, implementation defects as `defect_triage`, requirement changes as `change_control`, and other cross-role discussions as `ad_hoc`.
- Never infer `approve` from silence or from an artifact's existence.
- Requirement confirmation evidence must declare exactly one machine-readable line, `confirmation_verdict: approve` or `confirmation_verdict: reject` (Chinese documents may use `确认结论: approve|reject`). Record the same verdict with `record-requirement-confirmation`; prose such as “未确认” or “不同意” is never interpreted as approval.
- Every gate-review evidence file must declare exactly one `review_verdict: approve|reject` line (or `评审结论: approve|reject`) matching the submitted review verdict.
- User-feedback evidence must declare exactly one `feedback_verdict: approve|reject|request_changes` line (or `反馈结论: ...`) matching `record-user-feedback --verdict`.
- Delivery-confirmation evidence must declare exactly one `delivery_verdict: approve|reject|request_changes` line (or `交付结论: ...`) matching `record-delivery-confirmation --verdict`. Negated prose such as “user did not approve” never counts as approval.
- Never let the implementer substitute for independent test approval.
- At a configured human checkpoint, pause after current role verdicts and approved meeting notes. Present the evidence and ask the user or named authority for an explicit decision. Never manufacture, delegate, or infer human authorization.
- After explicit authorization, preserve a concise approval record under `docs/requirements/<workflow-id>/approvals/` and call `record-human-approval`. The state tool binds it to the current review and meeting hashes; later evidence changes make it stale.
- Ask the user only for unresolved business choices, authority, or scope changes.
- Run `advance` only after recording role decisions and resolving blockers.
- On rejection, keep the current gate, assign revisions, and review again.
- Preserve role outputs and the synthesized review under `docs/requirements/<workflow-id>/`.

## Commands

Resolve `workflow.py` relative to this Skill and use `python3 <skill-dir>/scripts/workflow.py --root <repository-root> --help` for the complete interface. Common subcommands:

```text
workflow.py start --request "..." --mode standard --require-human-approval acceptance
workflow.py start --request "..." --mode auto
workflow.py prepare-turn --json
workflow.py begin-work --work-item-id engineering-design-001 --role engineering --actor-ref engineering-task-id --deadline-at <ISO-8601-deadline>
workflow.py complete-work --work-item-id engineering-design-001 --output technical_design=docs/requirements/.../04-technical-design.md
workflow.py init --title "..." --mode standard --request "..." --require-human-approval acceptance
workflow.py overview
workflow.py project
workflow.py status
workflow.py next
workflow.py assess-risk --evidence docs/requirements/.../00-scope-and-risk.md --help
workflow.py report-risk --source engineering --risk api_change --summary "..." --evidence docs/requirements/.../risks/RSK-api.md
workflow.py resolve-risk --risk-id RSK-001 --resolved-by engineering --verified-by testing --resolution "..." --evidence docs/requirements/.../risks/RSK-001-resolution.md
workflow.py withdraw-risk --risk-id RSK-002 --withdrawn-by engineering --reason "..." --evidence docs/requirements/.../risks/RSK-002-withdrawal.md
workflow.py accept-escalation-risk --approved-by "user" --reason "..." --expires-on 2026-12-31 --evidence docs/requirements/.../risks/RSK-002-acceptance.md
workflow.py escalate-mode --to-mode standard --approved-by "user" --reason "..." --evidence docs/requirements/.../approvals/RSK-escalation.md
workflow.py record-artifact --name clarification_questions --work-item-id product-clarification-001 --path docs/requirements/.../00-clarification.md
workflow.py record-requirement-confirmation --verdict approve --summary "User approved the documented requirement baseline" --evidence docs/requirements/.../00-requirement-confirmation.md
workflow.py record-core-goals --goal "GOAL-001=User can complete the real target journey" --evidence docs/requirements/.../00-core-goals.md
workflow.py record-artifact --name prd --work-item-id product-prd-001 --path docs/requirements/.../01-prd.md
workflow.py archive-documents --manifest docs/requirements/.../changes/ARC-001.json
workflow.py register-acceptance-criteria --criterion "AC-001=Observable Must behavior"
workflow.py approve-scope-change --item AC-001 --disposition deferred --approved-by "user-name" --reason "..." --impact-stage verification --impact-reason "Earlier design and implementation remain valid" --evidence docs/requirements/.../changes/SC-001.md
workflow.py record-artifact --name prototype --work-item-id engineering-prototype-001 --path docs/requirements/.../07-prototype.md
workflow.py record-user-feedback --verdict approve --summary "..." --evidence docs/requirements/.../07-user-feedback.md
workflow.py record-user-feedback --verdict request_changes --affected-stage design --summary "..." --evidence docs/requirements/.../07-user-feedback.md
workflow.py submit-verification --manifest docs/requirements/.../08-verification-bundle.yaml
workflow.py record-artifact --name verification_report --work-item-id testing-verification-001 --path docs/requirements/.../08-verification.md --build-command "..." --test-command "..." --output-path build
workflow.py record-source-revision --source-path src --source-path tests --output-path build --build-command "..." --test-command "..." --evidence docs/requirements/.../08-source-verification.md
workflow.py record-criterion-verdict --criterion-id AC-001 --work-item-id testing-verification-001 --verdict pass --evidence docs/requirements/.../tests/AC-001.md
workflow.py record-user-journey --work-item-id testing-verification-001 --profile api --check launch=pass --check core_outcomes=pass --check content_semantics=pass --check interactions=pass --check external_links=blocked --check release_hygiene=pass --check source_truth=pass --evidence docs/requirements/.../08-final-journey.md
workflow.py record-core-outcome --goal-id GOAL-001 --work-item-id testing-verification-001 --verdict satisfied --evidence docs/requirements/.../09-goal-outcomes.md
workflow.py record-delivery-confirmation --verdict approve --summary "..." --evidence docs/requirements/.../09-delivery-confirmation.md
workflow.py add-issue --source testing --severity blocker --summary "..."
workflow.py resolve-issue --issue-id ISSUE-001 --resolved-by product --resolution "..." --evidence docs/requirements/.../01-prd.md
workflow.py disposition-issue --issue-id ISSUE-002 --disposition accepted_risk --approved-by "release-owner" --rationale "..." --evidence docs/requirements/.../decisions/ISSUE-002.md
workflow.py submit-gate-review --manifest docs/requirements/.../reviews/readiness-bundle.yaml
workflow.py decide --gate prd_review --role testing --actor-ref tester-task-id --work-item-id testing-prd-review-001 --verdict approve --evidence docs/requirements/.../reviews/prd-testing.md
workflow.py record-meeting --type prd_review --title "PRD review" --participants product,engineering,testing --outcome approved --path docs/requirements/.../meetings/MTG-001-prd-review.md
workflow.py record-human-approval --gate acceptance --approved-by "release-owner" --evidence docs/requirements/.../approvals/acceptance.md
workflow.py audit-state
workflow.py repair-state --from-backup --confirm RESTORE
workflow.py version --json
workflow.py doctor --source-root /path/to/editable/plugin --json
workflow.py pause --reason "User paused this requirement"
workflow.py resume
workflow.py advance
```

Treat granular `decide`/`record-meeting` and source/criterion/journey commands as advanced recovery tools. The normal route uses one gate-review bundle per enabled role gate and one verification bundle in strict mode, preventing partially registered review runs.

Keep meeting files under `docs/requirements/<workflow-id>/meetings/` and include the returned `MTG-*` ID in later issue, change, or delivery summaries when relevant.
