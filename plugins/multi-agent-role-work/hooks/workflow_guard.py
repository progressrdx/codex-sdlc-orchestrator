#!/usr/bin/env python3
"""Tool-level edit guard for an active multi-role workflow.

The hook is intentionally small and dependency-tolerant. It never runs for
ordinary user messages and does not replace the workflow CLI.
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
        if isinstance(workflow, dict) and workflow.get("status") in {"active", "paused"}:
            return candidate.resolve(), state
        return None
    return None


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
    status = str(state["workflow"].get("status", "active"))
    if status == "active" and stage in EDIT_STAGES:
        return None
    tool_input = payload.get("tool_input", {})
    command = tool_input.get("command", "") if isinstance(tool_input, dict) else ""
    paths = PATCH_PATH.findall(command) if isinstance(command, str) else []
    if paths and all(is_workflow_evidence(root, path) for path in paths):
        return None
    reason = (
        f"Formal SDLC workflow is {status} at '{stage}', where product/source edits are not "
        "authorized. "
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
    output = guard_patch(root, state, payload)
    if output is not None:
        print(json.dumps(output, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
