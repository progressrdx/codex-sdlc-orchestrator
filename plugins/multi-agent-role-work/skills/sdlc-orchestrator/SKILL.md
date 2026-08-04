---
name: sdlc-orchestrator
description: Coordinate an explicit formal multi-role software delivery workflow with persistent state and review gates. Use when the user starts an actionable request with `团队开发：` (team development), explicitly asks to start or manage a formal/multi-role SDLC workflow, invokes `$sdlc-orchestrator`, or continues an active `.ai-workflow/active.yaml` requirement. Do not use when the user merely discusses team development, asks an ordinary question, or requests an isolated fix without explicitly choosing the workflow.
---

# Coordinate the SDLC workflow

Keep the main thread focused on business decisions, state transitions, and synthesized results. Delegate bounded work to independent role subagents and explicitly name the bundled phase Skill in every delegation prompt. The plugin must work without project-local Skills, custom agents, `.codex/config.toml`, or `AGENTS.md` changes.

## Start or resume

1. Locate the repository root.
2. Resolve this Skill's own directory from the loaded `SKILL.md` path and run `python3 <skill-dir>/scripts/workflow.py --root <repository-root> status`. Never assume the Skill lives inside the target repository.
3. Treat an actionable `团队开发：<request>` prefix as an explicit formal-process request. Pass `<request>` to `start --request` without asking the user to repeat it. Equivalent explicit phrases such as “启动正式研发流程” or “使用多角色流程开发” also qualify. A discussion such as “团队开发和个人开发有什么区别” does not.
4. If no workflow exists and the user explicitly requested the formal process, initialize it with `start --request ... --mode auto` unless the user explicitly chose a mode. Add `--title ...` only when the user gives a better short title. Add `--require-human-approval <gate>` for each configured human checkpoint.
5. Treat an explicitly requested mode as a minimum floor. Natural-language requests without a mode always start in `auto`; determine the lowest safe concrete mode during scope analysis.
6. When an active workflow exists, let short requests such as “继续”, “查看进度”, “修改需求”, or “开始验收” resume or inspect that workflow. Without an active workflow, those phrases alone do not start one.
   If the user explicitly pauses the workflow, run `pause --reason ...`; paused state preserves evidence but suppresses hook routing and rejects delivery mutations. Run `resume` only when the user asks to continue.
7. On every turn that refers to an active workflow, run `overview` before assigning work or writing files. Do not infer the current stage from the conversation, a prior summary, or the user's wording. The bundled prompt hook reinforces this check but does not replace it.
8. Treat `start` as opening scope and risk analysis, not permission to build. Advance from intake to `scope_check`, read [scope-risk-template.md](assets/scope-risk-template.md), and inspect the request and repository before asking questions or selecting a mode.
9. Do not initialize a formal workflow from an ordinary coding request.

At `scope_check`, always analyze every `assess-risk --checked-area` category: actors/permissions, goals/scope, business rules/states, data/API effects, failures/edges, compatibility/rollout, subjective choices, and acceptance/verification. This thinking is mandatory; user questions are conditional. If no unresolved high-impact gap exists, record that conclusion and avoid ceremonial questions. Author the complete scope/risk artifact from [scope-risk-template.md](assets/scope-risk-template.md), then register that existing evidence with `assess-risk --evidence`; the state command must not author the assessment. Present the recommendation and reasons, and never select a mode below the deterministic safe minimum. An explicitly requested mode is a floor.

If any role discovers a new risk, preserve a substantive risk record and call `report-risk`. The state tool combines current and newly reported flags, including documented combination rules, calculates the minimum safe mode, and blocks every transition with `escalation_required` when the current mode is too weak. Present the report, affected workflow cost, and recommended mode to the user. If later evidence removes the risk, use `resolve-risk` with a distinct resolver and verifier, or `withdraw-risk` only when the original reporter or user retracts a mistaken report; both require separate evidence and recompute the blocker. A named human may explicitly accept a reversible, non-sensitive escalation risk through `accept-escalation-risk` with rationale, separate evidence, and an expiry; this keeps the current mode but marks assurance as reduced. Never permit that disposition for security/privacy, irreversible, migration, or production-release flags. Otherwise, only after explicit approval, preserve separate approval evidence and call `escalate-mode`; it switches mode, rewinds to `scope_check`, invalidates downstream evidence, and requires a refreshed baseline. Do not silently escalate effort or continue under a weaker flow.

Require a human checkpoint for destructive data changes, permission changes, production release authorization, security exceptions, legal/compliance decisions, or another irreversible/high-impact action. Use `readiness_review` when authorization is needed before implementation and `acceptance` when authorization is needed before final delivery. Tell the user which checkpoints were configured.

Read [workflow-contract.md](references/workflow-contract.md) before the first state transition in a workflow.
Use [meeting-notes-template.md](assets/meeting-notes-template.md) for every cross-role communication summary.
Use [gate-review-bundle-template.yaml](assets/gate-review-bundle-template.yaml) for PRD, readiness, and acceptance gate reviews.
In strict mode, use [core-goals-template.md](assets/core-goals-template.md) at requirement confirmation, [final-user-journey-template.md](assets/final-user-journey-template.md) during verification, and [verification-bundle-template.yaml](assets/verification-bundle-template.yaml) to submit the source binding, all criterion verdicts, and the journey result atomically.

## Route by stage

| Stage | Assignment |
|---|---|
| `intake` | Capture the raw request and advance to `scope_check` if the formal workflow was explicit. |
| `scope_check` | Perform structured requirement-gap and risk analysis, recommend/select the mode, and configure conditional quick gates with `assess-risk`. |
| `clarification` | Spawn a `product_manager` task with `$sdlc-product`; require missing-point analysis and focused user questions before recording `clarification_questions`. |
| `requirement_confirmation` | Present the synthesized understanding and unresolved choices to the user; record `requirement_confirmation` only after explicit user confirmation. In strict mode, lock the confirmed `GOAL-*` outcomes with `record-core-goals`. |
| `prd` | Spawn a `product_manager` task with `$sdlc-product`. In strict mode register every Must `AC-*` from the current PRD. |
| `prd_review` | Spawn `product_manager`, `developer`, and `tester` tasks independently with `$sdlc-review`; wait, synthesize disagreements, then prefer one `submit-gate-review` bundle for all verdicts and meeting notes. |
| `design` | Spawn a `developer` task with `$sdlc-engineering` and a `tester` task with `$sdlc-testing`; parallelize only when their writes do not overlap. |
| `readiness_review` | Spawn every required role task independently with `$sdlc-review`; submit their verdicts and the meeting atomically. |
| `prototype` | Spawn a `developer` task with `$sdlc-engineering` to create the smallest inspectable prototype, MVP, screenshot, or demo. |
| `user_feedback` | Present the prototype to the user; use `record-user-feedback`. Only unambiguous explicit approval unlocks implementation. Criticism, a defect, mismatch, or change request is `request_changes`/`reject` and must be recorded before edits. |
| `implementation` | Spawn a `developer` task with `$sdlc-engineering`. |
| `verification` | Spawn a `tester` task with `$sdlc-testing`; send confirmed defects to a `developer` task. In strict mode prefer one `submit-verification` bundle that binds the scoped committed source, every criterion verdict, and the profile-appropriate final journey. |
| `acceptance` | Spawn all required role tasks with `$sdlc-review`; product checks each confirmed core outcome, tester checks current-source journey evidence, developer answers technical findings, and the coordinator submits one gate-review bundle. |
| `delivery_confirmation` | In every mode, show the user the working result, implementation summary, and test evidence. Only unambiguous explicit approval completes delivery. Record criticism, defects, mismatch, negative examples, or requested changes with `record-delivery-confirmation --verdict request_changes` before any product edit, selecting the earliest affected stage. |

Use a role-named subagent task and include the role boundary plus the explicit bundled `$sdlc-*` Skill in its prompt. Project custom agents may be used when available, but the workflow must never depend on them. Never omit the Skill and rely on the task name alone.

Apply the `overview` execution policy to control cost. Pass role agents the current decision summary, affected criteria, changed paths, and evidence paths—not the full transcript or complete passing logs. Run deterministic smoke/focused tests before broad semantic review, stop on the first failure, and expand only when the selected mode or observed risk requires it.

Only route stages present in the state's `flow_stages`. In `micro`, assign implementation to engineering and verification to an independent tester, then obtain lightweight user delivery confirmation; do not invent product work, prototype work, role gates, or meetings that the selected flow omits.

## Enforce gates

- Record artifacts only after checking that the referenced path exists.
- Do not advance past `scope_check` without a current structured risk assessment and task baseline. Never treat a short request as proof that no gaps or risks exist.
- When a role reports scope expansion, API/data impact, business ambiguity, weak verification, external dependency, systemic failure, security/privacy, migration, production, or irreversible risk, call `report-risk` before continuing. Never hide a discovered trigger inside an implementation summary.
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
- Convert every blocking finding into a tracked issue; resolve it only with owner-matched evidence.
- At acceptance, an open `major` issue also blocks delivery. Resolve it, or record an evidenced `accepted_risk` or `deferred` disposition with the named human authority; deferred issues require a due date.
- After every exchange involving two or more roles, create concise meeting notes that preserve each role's key position, disagreements, decisions, owners, and follow-up actions. Do not store a raw transcript.
- Record every role verdict with the canonical subagent task/session identifier as `--actor-ref`. The state tool rejects one reference reused by different roles at the same gate and binds the references into meeting and human-approval snapshots. This is traceability, not cryptographic authentication.
- Record gate meetings only after collecting independent role verdicts. Prefer one `submit-gate-review` manifest containing exactly the required roles, distinct actor references/evidence, and the synthesized meeting record. Validation is atomic: an invalid role or meeting leaves the prior gate state unchanged.
- When an indexed artifact changes, the state tool automatically rewinds to its earliest affected stage and supersedes downstream evidence. Treat the returned `change_control_required` event as a required cross-role change-control discussion before rebuilding downstream artifacts.
- Evidence is live: if an indexed artifact, review, meeting note, or human approval file changes after recording, its hash no longer matches and the gate cannot advance until it is recorded and reviewed again.
- Verification is source-live and command-backed in every concrete mode. For micro, quick, and standard, record `verification_report` with `--test-command` and optionally `--build-command`; the state tool executes them, stores a local bounded log, and records only command metadata/hashes in state. A nonzero or timed-out command stops immediately. Strict verification bundles execute their build and test commands before binding the committed scope. Any later product change blocks delivery until independent tests run again. Do not paste full passing logs into agent prompts; inspect the local log only for failures and never deliberately print secrets.
- Select the final-journey profile that matches the deliverable (`web`, `desktop`, `api`, `cli`, `library`, or `data`). Record `fail`, `blocked`, or `not_applicable` truthfully; required non-pass results remain stored and block advancement instead of forcing a false all-pass report.
- The final journey must test actual semantics and actions appropriate to the profile. A build, screenshot, source inspection, or prototype approval is insufficient.
- Never edit `state.yaml` directly. Schema 10 state includes an integrity checksum and unsupported manual edits fail closed. Use `audit-state`; when a prior valid automatic backup exists, use the explicit `repair-state --from-backup --confirm RESTORE` recovery path.
- Record design coordination as `design_sync`, implementation defects as `defect_triage`, requirement changes as `change_control`, and other cross-role discussions as `ad_hoc`.
- Never infer `approve` from silence or from an artifact's existence.
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
workflow.py init --title "..." --mode standard --request "..." --require-human-approval acceptance
workflow.py overview
workflow.py status
workflow.py next
workflow.py assess-risk --evidence docs/requirements/.../00-scope-and-risk.md --help
workflow.py report-risk --source engineering --risk api_change --summary "..." --evidence docs/requirements/.../risks/RSK-api.md
workflow.py resolve-risk --risk-id RSK-001 --resolved-by engineering --verified-by testing --resolution "..." --evidence docs/requirements/.../risks/RSK-001-resolution.md
workflow.py withdraw-risk --risk-id RSK-002 --withdrawn-by engineering --reason "..." --evidence docs/requirements/.../risks/RSK-002-withdrawal.md
workflow.py accept-escalation-risk --approved-by "user" --reason "..." --expires-on 2026-12-31 --evidence docs/requirements/.../risks/RSK-002-acceptance.md
workflow.py escalate-mode --to-mode standard --approved-by "user" --reason "..." --evidence docs/requirements/.../approvals/RSK-escalation.md
workflow.py record-artifact --name clarification_questions --path docs/requirements/.../00-clarification.md
workflow.py record-artifact --name requirement_confirmation --path docs/requirements/.../00-requirement-confirmation.md
workflow.py record-core-goals --goal "GOAL-001=User can complete the real target journey" --evidence docs/requirements/.../00-core-goals.md
workflow.py record-artifact --name prd --path docs/requirements/.../01-prd.md
workflow.py register-acceptance-criteria --criterion "AC-001=Observable Must behavior"
workflow.py approve-scope-change --item AC-001 --disposition deferred --approved-by "user-name" --reason "..." --impact-stage verification --impact-reason "Earlier design and implementation remain valid" --evidence docs/requirements/.../changes/SC-001.md
workflow.py record-artifact --name prototype --path docs/requirements/.../07-prototype.md
workflow.py record-user-feedback --verdict approve --summary "..." --evidence docs/requirements/.../07-user-feedback.md
workflow.py record-user-feedback --verdict request_changes --affected-stage design --summary "..." --evidence docs/requirements/.../07-user-feedback.md
workflow.py submit-verification --manifest docs/requirements/.../08-verification-bundle.yaml
workflow.py record-artifact --name verification_report --path docs/requirements/.../08-verification.md --build-command "..." --test-command "..."
workflow.py record-source-revision --source-path src --source-path tests --build-command "..." --test-command "..." --evidence docs/requirements/.../08-source-verification.md
workflow.py record-criterion-verdict --criterion-id AC-001 --verdict pass --evidence docs/requirements/.../tests/AC-001.md
workflow.py record-user-journey --profile api --check launch=pass --check core_outcomes=pass --check content_semantics=pass --check interactions=pass --check external_links=blocked --check release_hygiene=pass --check source_truth=pass --evidence docs/requirements/.../08-final-journey.md
workflow.py record-core-outcome --goal-id GOAL-001 --verdict satisfied --evidence docs/requirements/.../09-goal-outcomes.md
workflow.py record-delivery-confirmation --verdict approve --summary "..." --evidence docs/requirements/.../09-delivery-confirmation.md
workflow.py add-issue --source testing --severity blocker --summary "..."
workflow.py resolve-issue --issue-id ISSUE-001 --resolved-by product --resolution "..." --evidence docs/requirements/.../01-prd.md
workflow.py disposition-issue --issue-id ISSUE-002 --disposition accepted_risk --approved-by "release-owner" --rationale "..." --evidence docs/requirements/.../decisions/ISSUE-002.md
workflow.py submit-gate-review --manifest docs/requirements/.../reviews/readiness-bundle.yaml
workflow.py decide --gate prd_review --role testing --actor-ref tester-task-id --verdict approve --evidence docs/requirements/.../reviews/prd-testing.md
workflow.py record-meeting --type prd_review --title "PRD review" --participants product,engineering,testing --outcome approved --path docs/requirements/.../meetings/MTG-001-prd-review.md
workflow.py record-human-approval --gate acceptance --approved-by "release-owner" --evidence docs/requirements/.../approvals/acceptance.md
workflow.py audit-state
workflow.py repair-state --from-backup --confirm RESTORE
workflow.py pause --reason "User paused this requirement"
workflow.py resume
workflow.py advance
```

Treat granular `decide`/`record-meeting` and source/criterion/journey commands as advanced recovery tools. The normal route uses one gate-review bundle per enabled role gate and one verification bundle in strict mode, preventing partially registered review runs.

Keep meeting files under `docs/requirements/<workflow-id>/meetings/` and include the returned `MTG-*` ID in later issue, change, or delivery summaries when relevant.
