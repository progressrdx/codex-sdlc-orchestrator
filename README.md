# Codex Multi-Role SDLC

A project-local Codex workflow that coordinates a product manager, developer, and tester through persistent, evidence-based delivery stages.

## Design

- The coordinator is the only implicitly discoverable workflow Skill.
- Role and review Skills disable implicit invocation and load only when the coordinator names them.
- `.ai-workflow/` stores deterministic state; `docs/requirements/<id>/` stores durable artifacts.
- Project agents under `.codex/agents/` keep product, engineering, and testing responsibilities separate.
- Review gates require explicit role verdicts and reject unresolved blockers.
- Every cross-role review, disagreement, defect triage, or change discussion produces concise meeting notes under `docs/requirements/<id>/meetings/`.

## Start

In Codex, ask:

```text
使用 $sdlc-orchestrator 启动标准研发流程：实现会员积分过期功能。
```

To inspect or continue:

```text
继续当前正式研发流程。
当前流程进行到哪一步？
```

Ordinary coding requests do not start the workflow.

## State tool

```text
python3 .agents/skills/sdlc-orchestrator/scripts/workflow.py --help
python3 .agents/skills/sdlc-orchestrator/scripts/workflow.py status
python3 .agents/skills/sdlc-orchestrator/scripts/workflow.py next
```

The default `standard` flow is:

```text
intake → prd → prd_review → design → readiness_review
       → implementation → verification → acceptance → completed
```

`quick` skips the full PRD stage. `strict` additionally requires explicit database-design and release-plan artifacts, which may be marked not applicable with justification.

At PRD review, readiness review, and acceptance, independent role reviews are followed by a structured meeting summary. The state machine will not advance a gate without current meeting notes covering all required roles. Meeting notes retain key viewpoints, disagreements, decisions, rationale, owners, open questions, and next steps—not a raw chat transcript.

## Trust boundary

The state tool is a workflow integrity guard, not an identity or security system. It requires repository evidence, distinct review records, matching issue owners, and substantive document size, but a human with filesystem access can still forge those inputs. Real reviewer independence comes from the coordinator assigning separate Codex agents and preserving their outputs. Content quality remains a review responsibility; deterministic checks only prevent obvious omissions and stage skipping.
