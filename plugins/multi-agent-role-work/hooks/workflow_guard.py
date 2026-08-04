#!/usr/bin/env python3
"""Codex lifecycle guard for an active multi-role workflow.

The hook is intentionally small and dependency-tolerant. It does not replace
the workflow CLI; it prevents the coordinator from forgetting to consult it.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

try:
    import yaml  # type: ignore
except ImportError:  # pragma: no cover - Codex currently bundles PyYAML.
    yaml = None


EDIT_STAGES = {"prototype", "implementation"}
PATCH_PATH = re.compile(r"^\*\*\* (?:Add|Update|Delete) File: (.+)$", re.MULTILINE)


def load_mapping(path: Path) -> dict[str, Any]:
    try:
        text = path.read_text(encoding="utf-8")
        value = yaml.safe_load(text) if yaml else json.loads(text)
    except Exception:  # A lifecycle guard must fail open on malformed external input.
        return {}
    return value if isinstance(value, dict) else {}


def active_workflow(cwd: Path) -> tuple[Path, dict[str, Any]] | None:
    start = cwd if cwd.is_dir() else cwd.parent
    for candidate in (start, *start.parents):
        pointer = candidate / ".ai-workflow" / "active.yaml"
        if not pointer.is_file():
            continue
        pointer_data = load_mapping(pointer)
        relative = pointer_data.get("state_path")
        if not isinstance(relative, str) or not relative:
            return None
        state_path = (candidate / relative).resolve()
        try:
            state_path.relative_to(candidate.resolve())
        except ValueError:
            return None
        state = load_mapping(state_path)
        workflow = state.get("workflow")
        if isinstance(workflow, dict) and workflow.get("status") == "active":
            return candidate.resolve(), state
        return None
    return None


def prompt_context(state: dict[str, Any]) -> dict[str, Any]:
    workflow = state["workflow"]
    stage = str(workflow.get("current_stage", "unknown"))
    mode = str(workflow.get("mode", "unknown"))
    workflow_id = str(workflow.get("id", "unknown"))
    context = (
        f"An active formal SDLC workflow exists: {workflow_id}, mode={mode}, stage={stage}. "
        "First classify whether this prompt refers to that requirement. If it does, explicitly use "
        "$sdlc-orchestrator and run overview/status before assigning work or editing files; never infer "
        "the stage from conversation text. If the prompt is unrelated, answer it normally without "
        "mutating the active requirement. "
    )
    if stage in {"user_feedback", "delivery_confirmation"}:
        context += (
            "At this user decision stage, only unambiguous explicit approval is approval. Criticism, "
            "a defect, mismatch, change request, or a negative example must be recorded as "
            "request_changes with the earliest affected stage before any product edit. If it is unclear "
            "whether the user wants the sample fixed or the workflow/plugin changed, ask one focused "
            "question and do not edit. "
        )
    if stage not in EDIT_STAGES:
        context += "Product/source edits are not authorized at the current stage."
    return {
        "hookSpecificOutput": {
            "hookEventName": "UserPromptSubmit",
            "additionalContext": context,
        }
    }


def is_workflow_evidence(root: Path, raw_path: str) -> bool:
    candidate = Path(raw_path.strip())
    resolved = candidate.resolve() if candidate.is_absolute() else (root / candidate).resolve()
    try:
        relative = resolved.relative_to(root)
    except ValueError:
        return False
    parts = relative.parts
    return bool(parts) and (
        parts[0] == ".ai-workflow"
        or len(parts) >= 2 and parts[0] == "docs" and parts[1] == "requirements"
    )


def guard_patch(root: Path, state: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any] | None:
    stage = str(state["workflow"].get("current_stage", "unknown"))
    if stage in EDIT_STAGES:
        return None
    tool_input = payload.get("tool_input", {})
    command = tool_input.get("command", "") if isinstance(tool_input, dict) else ""
    paths = PATCH_PATH.findall(command) if isinstance(command, str) else []
    if paths and all(is_workflow_evidence(root, path) for path in paths):
        return None
    reason = (
        f"Formal SDLC workflow is at '{stage}', where product/source edits are not authorized. "
        "Use $sdlc-orchestrator, record the user's decision or finding, and rewind to prototype or "
        "implementation before editing. Workflow evidence under .ai-workflow/ or docs/requirements/ "
        "remains writable."
    )
    return {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }
    }


def main() -> int:
    action = sys.argv[1] if len(sys.argv) > 1 else "prompt"
    try:
        payload = json.load(sys.stdin)
    except (ValueError, TypeError):
        return 0
    if not isinstance(payload, dict):
        return 0
    cwd = Path(str(payload.get("cwd") or Path.cwd())).resolve()
    active = active_workflow(cwd)
    if active is None:
        return 0
    root, state = active
    output = prompt_context(state) if action == "prompt" else guard_patch(root, state, payload)
    if output is not None:
        print(json.dumps(output, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
