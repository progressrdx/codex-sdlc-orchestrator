---
name: sdlc-orchestrator
description: Coordinate an explicit, formal multi-role software delivery workflow with persistent state and review gates. Use only when the user asks to start, continue, inspect, reopen, or manage the formal SDLC workflow, or when an active `.ai-workflow/active.yaml` exists and the user is continuing that workflow. Do not use for ordinary coding, explanations, isolated fixes, or casual planning without an active workflow.
---

# Coordinate the SDLC workflow

Keep the main thread focused on business decisions, state transitions, and synthesized results. Delegate bounded work to independent role subagents and explicitly name the bundled phase Skill in every delegation prompt. The plugin must work without project-local Skills, custom agents, `.codex/config.toml`, or `AGENTS.md` changes.

## Start or resume

1. Locate the repository root.
2. Resolve this Skill's own directory from the loaded `SKILL.md` path and run `python3 <skill-dir>/scripts/workflow.py --root <repository-root> status`. Never assume the Skill lives inside the target repository.
3. If no workflow exists and the user explicitly requested the formal process, initialize it with `init --title ... --mode standard --request ...`.
4. Run `next` before assigning work.
5. Do not initialize a formal workflow from an ordinary coding request.

Read [workflow-contract.md](references/workflow-contract.md) before the first state transition in a workflow.
Use [meeting-notes-template.md](assets/meeting-notes-template.md) for every cross-role communication summary.

## Route by stage

| Stage | Assignment |
|---|---|
| `intake`, `prd` | Spawn a `product_manager` task with `$sdlc-product`. |
| `prd_review` | Spawn `product_manager`, `developer`, and `tester` tasks independently with `$sdlc-review`; wait and synthesize disagreements. |
| `design` | Spawn a `developer` task with `$sdlc-engineering` and a `tester` task with `$sdlc-testing`; parallelize only when their writes do not overlap. |
| `readiness_review` | Spawn all three role tasks independently with `$sdlc-review`. |
| `implementation` | Spawn a `developer` task with `$sdlc-engineering`. |
| `verification` | Spawn a `tester` task with `$sdlc-testing`; send confirmed defects to a `developer` task. |
| `acceptance` | Spawn all three role tasks with `$sdlc-review`; product checks intent, tester checks evidence, developer answers technical findings. |

Use a role-named subagent task and include the role boundary plus the explicit bundled `$sdlc-*` Skill in its prompt. Project custom agents may be used when available, but the workflow must never depend on them. Never omit the Skill and rely on the task name alone.

## Enforce gates

- Record artifacts only after checking that the referenced path exists.
- Convert every blocking finding into a tracked issue; resolve it only with owner-matched evidence.
- After every exchange involving two or more roles, create concise meeting notes that preserve each role's key position, disagreements, decisions, owners, and follow-up actions. Do not store a raw transcript.
- Record gate meetings only after collecting independent role verdicts. The PRD, readiness, and acceptance gates cannot advance without current meeting notes covering every required role.
- Record design coordination as `design_sync`, implementation defects as `defect_triage`, requirement changes as `change_control`, and other cross-role discussions as `ad_hoc`.
- Never infer `approve` from silence or from an artifact's existence.
- Never let the implementer substitute for independent test approval.
- Ask the user only for unresolved business choices, authority, or scope changes.
- Run `advance` only after recording role decisions and resolving blockers.
- On rejection, keep the current gate, assign revisions, and review again.
- Preserve role outputs and the synthesized review under `docs/requirements/<workflow-id>/`.

## Commands

Resolve `workflow.py` relative to this Skill and use `python3 <skill-dir>/scripts/workflow.py --root <repository-root> --help` for the complete interface. Common subcommands:

```text
workflow.py init --title "..." --mode standard --request "..."
workflow.py status
workflow.py next
workflow.py record-artifact --name prd --path docs/requirements/.../01-prd.md
workflow.py add-issue --source testing --severity blocker --summary "..."
workflow.py resolve-issue --issue-id ISSUE-001 --resolved-by product --resolution "..." --evidence docs/requirements/.../01-prd.md
workflow.py decide --gate prd_review --role testing --verdict approve --evidence docs/requirements/.../reviews/prd-testing.md
workflow.py record-meeting --type prd_review --title "PRD review" --participants product,engineering,testing --outcome approved --path docs/requirements/.../meetings/MTG-001-prd-review.md
workflow.py advance
```

Keep meeting files under `docs/requirements/<workflow-id>/meetings/` and include the returned `MTG-*` ID in later issue, change, or delivery summaries when relevant.
