# Project guidance

This repository contains a Codex-native, multi-role SDLC workflow.

## Formal workflow activation

- Start the formal process only when the user explicitly asks to start it or invokes `$sdlc-orchestrator`.
- Continue it only when `.ai-workflow/active.yaml` exists and the user is referring to that active requirement.
- Do not apply the formal process to ordinary questions, isolated fixes, explanations, or casual planning.
- Keep coordination lightweight. Role Skills have implicit invocation disabled; the coordinator must name them explicitly in delegated prompts.
- Spawn independent `product_manager`, `developer`, and `tester` role tasks at the stages defined by `$sdlc-orchestrator`, with the corresponding explicit bundled Skill and role boundary in each prompt. Project custom agents are optional and the published plugin must not depend on them.
- After any communication involving two or more roles, preserve a concise structured meeting record with material viewpoints, disagreements, decisions and rationale, action owners, open questions, and next step. Do not preserve a raw transcript.
- Never code before the configured pre-implementation checks pass: the readiness gate when present, or the recorded scope/risk check for `micro`.
- When any role discovers risk above the selected mode, preserve evidence and report it to the workflow state tool. Do not continue until the automatic escalation recommendation is explicitly resolved by the user.
- Do not treat an artifact, reviewer silence, or developer self-test as approval.

## Verification

After modifying the workflow implementation, run:

```text
python3 -m unittest discover -s tests -v
python3 "${CODEX_HOME:-$HOME/.codex}/skills/.system/skill-creator/scripts/quick_validate.py" plugins/multi-agent-role-work/skills/sdlc-orchestrator
```

Validate every changed Skill, not only the coordinator.
