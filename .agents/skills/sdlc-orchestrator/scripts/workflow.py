#!/usr/bin/env python3
"""Deterministic state and gate management for the multi-role SDLC workflow."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    import yaml  # type: ignore
except ImportError:  # JSON is valid YAML 1.2 and is the dependency-free fallback.
    yaml = None


ROLES = ("product", "engineering", "testing")
GATES = ("prd_review", "readiness_review", "acceptance")
MEETING_TYPES = GATES + ("design_sync", "defect_triage", "change_control", "ad_hoc")
MEETING_PARTICIPANTS = ROLES + ("user", "coordinator")
MEETING_OUTCOMES = ("approved", "rejected", "aligned", "actions_required", "escalated")
ARTIFACTS = (
    "original_request",
    "prd",
    "review_log",
    "technical_design",
    "database_design",
    "test_plan",
    "test_cases",
    "implementation",
    "verification_report",
    "release_plan",
    "delivery_report",
    "traceability",
)
ARTIFACT_STAGE = {
    "prd": "prd",
    "review_log": "prd_review",
    "technical_design": "design",
    "database_design": "design",
    "test_plan": "design",
    "test_cases": "design",
    "release_plan": "design",
    "implementation": "implementation",
    "verification_report": "verification",
    "traceability": "verification",
    "delivery_report": "acceptance",
}
ARTIFACT_INVALIDATES_GATES = {
    "prd": GATES,
    "technical_design": ("readiness_review", "acceptance"),
    "database_design": ("readiness_review", "acceptance"),
    "test_plan": ("readiness_review", "acceptance"),
    "test_cases": ("readiness_review", "acceptance"),
    "release_plan": ("readiness_review", "acceptance"),
    "implementation": ("acceptance",),
    "verification_report": ("acceptance",),
    "traceability": ("acceptance",),
    "delivery_report": ("acceptance",),
}
NOT_APPLICABLE_ALLOWED = {"database_design", "test_cases", "release_plan", "traceability"}
DOCUMENT_ARTIFACTS = {
    "prd",
    "technical_design",
    "database_design",
    "test_plan",
    "test_cases",
    "verification_report",
    "release_plan",
    "delivery_report",
    "traceability",
    "review_log",
}
MIN_DOCUMENT_CHARS = 80
MIN_DOCUMENT_HEADINGS = 3
FLOWS = {
    "quick": (
        "intake",
        "design",
        "readiness_review",
        "implementation",
        "verification",
        "acceptance",
        "completed",
    ),
    "standard": (
        "intake",
        "prd",
        "prd_review",
        "design",
        "readiness_review",
        "implementation",
        "verification",
        "acceptance",
        "completed",
    ),
    "strict": (
        "intake",
        "prd",
        "prd_review",
        "design",
        "readiness_review",
        "implementation",
        "verification",
        "acceptance",
        "completed",
    ),
}
GATE_ROLES = {
    "quick": {
        "readiness_review": ("engineering", "testing"),
        "acceptance": ("product", "engineering", "testing"),
    },
    "standard": {gate: ROLES for gate in GATES},
    "strict": {gate: ROLES for gate in GATES},
}


class WorkflowError(RuntimeError):
    pass


def now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def repository_root(explicit: str | None = None) -> Path:
    if explicit:
        return Path(explicit).expanduser().resolve()
    try:
        output = subprocess.check_output(
            ["git", "rev-parse", "--show-toplevel"],
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
        if output:
            return Path(output).resolve()
    except (OSError, subprocess.CalledProcessError):
        pass
    return Path.cwd().resolve()


def load_data(path: Path) -> dict[str, Any]:
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise WorkflowError(f"State file not found: {path}") from exc
    data = yaml.safe_load(text) if yaml else json.loads(text)
    if not isinstance(data, dict):
        raise WorkflowError(f"Invalid mapping in {path}")
    return data


def save_data(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if yaml:
        rendered = yaml.safe_dump(data, sort_keys=False, allow_unicode=True)
    else:
        rendered = json.dumps(data, indent=2, ensure_ascii=False) + "\n"
    path.write_text(rendered, encoding="utf-8")


def active_pointer(root: Path) -> Path:
    return root / ".ai-workflow" / "active.yaml"


def state_path(root: Path, workflow_id: str | None = None) -> Path:
    if workflow_id:
        return root / ".ai-workflow" / workflow_id / "state.yaml"
    pointer = active_pointer(root)
    if not pointer.exists():
        raise WorkflowError("No active workflow. Start one with the init command.")
    data = load_data(pointer)
    relative = data.get("state_path")
    if not isinstance(relative, str) or not relative:
        raise WorkflowError(f"Invalid active pointer: {pointer}")
    return root / relative


def load_state(root: Path, workflow_id: str | None = None) -> tuple[Path, dict[str, Any]]:
    path = state_path(root, workflow_id)
    return path, load_data(path)


def workflow_id_from_title(title: str) -> str:
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:32]
    if not slug:
        slug = "requirement"
    return f"REQ-{timestamp}-{slug}"


def add_history(state: dict[str, Any], event: str, detail: str) -> None:
    state.setdefault("history", []).append({"at": now(), "event": event, "detail": detail})
    state["workflow"]["updated_at"] = now()


def artifact_ready(state: dict[str, Any], name: str) -> bool:
    item = state.get("artifacts", {}).get(name, {})
    return item.get("status") in {"ready", "not_applicable"}


def open_blockers(state: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        issue
        for issue in state.get("issues", [])
        if issue.get("status") == "open" and issue.get("severity") == "blocker"
    ]


def required_artifacts(state: dict[str, Any], stage: str) -> tuple[str, ...]:
    mode = state["workflow"]["mode"]
    required = {
        "intake": ("original_request",),
        "prd": ("prd",),
        "design": ("technical_design", "test_plan"),
        "implementation": ("implementation",),
        "verification": ("verification_report",),
        "acceptance": ("delivery_report",),
    }.get(stage, ())
    if mode == "strict" and stage == "design":
        required += ("database_design", "release_plan")
    return required


def required_gate_roles(state: dict[str, Any], gate: str) -> tuple[str, ...]:
    return tuple(GATE_ROLES[state["workflow"]["mode"]].get(gate, ()))


def gate_decision_snapshot(state: dict[str, Any], gate: str) -> dict[str, str]:
    decisions = state.get("decisions", {}).get(gate, {})
    return {
        role: f"{decision.get('verdict', '')}:{decision.get('evidence_sha256', '')}"
        for role, decision in sorted(decisions.items())
    }


def gate_meeting_ready(state: dict[str, Any], gate: str) -> bool:
    required_roles = set(required_gate_roles(state, gate))
    snapshot = gate_decision_snapshot(state, gate)
    for meeting in reversed(state.get("meetings", [])):
        if (
            meeting.get("status") == "current"
            and meeting.get("type") == gate
            and meeting.get("stage") == gate
            and meeting.get("outcome") == "approved"
            and required_roles.issubset(set(meeting.get("participants", [])))
            and meeting.get("decision_snapshot") == snapshot
        ):
            return True
    return False


def invalidate_gate_meetings(state: dict[str, Any], gates: tuple[str, ...], reason: str) -> list[str]:
    invalidated: list[str] = []
    for meeting in state.get("meetings", []):
        if meeting.get("status") == "current" and meeting.get("type") in gates:
            meeting["status"] = "superseded"
            meeting["superseded_at"] = now()
            meeting["superseded_reason"] = reason
            invalidated.append(str(meeting.get("id")))
    return invalidated


def stage_requirements(state: dict[str, Any]) -> tuple[list[str], list[str]]:
    stage = state["workflow"]["current_stage"]
    missing: list[str] = []
    notes: list[str] = []

    for name in required_artifacts(state, stage):
        if not artifact_ready(state, name):
            missing.append(f"artifact:{name}")

    if stage in GATES:
        decisions = state.get("decisions", {}).get(stage, {})
        for role in required_gate_roles(state, stage):
            verdict = decisions.get(role, {}).get("verdict")
            if verdict != "approve":
                missing.append(f"approval:{stage}:{role}")
                if verdict == "reject":
                    notes.append(f"{role} rejected {stage}")
        if not gate_meeting_ready(state, stage):
            missing.append(f"meeting:{stage}")

    blockers = open_blockers(state)
    if blockers:
        missing.extend(f"blocker:{item['id']}" for item in blockers)
    return missing, notes


def save_state(path: Path, state: dict[str, Any]) -> None:
    save_data(path, state)


def repository_evidence_path(
    root: Path,
    raw_path: str,
    *,
    minimum_chars: int = 0,
) -> tuple[Path, Path]:
    candidate = Path(raw_path)
    absolute = candidate if candidate.is_absolute() else root / candidate
    if not absolute.exists():
        raise WorkflowError(f"Evidence path does not exist: {absolute}")
    try:
        relative = absolute.resolve().relative_to(root)
    except ValueError as exc:
        raise WorkflowError("Evidence must be inside the repository root.") from exc
    if minimum_chars:
        if not absolute.is_file():
            raise WorkflowError(f"Evidence must be a file: {relative}")
        content_length = len(absolute.read_text(encoding="utf-8").strip())
        if content_length < minimum_chars:
            raise WorkflowError(
                f"Evidence is too small to be substantive: {relative} "
                f"({content_length} < {minimum_chars} characters)"
            )
    return absolute, relative


def content_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def require_markdown_structure(path: Path) -> None:
    headings = sum(
        1 for line in path.read_text(encoding="utf-8").splitlines() if re.match(r"^#{1,6}\s+\S", line)
    )
    if headings < MIN_DOCUMENT_HEADINGS:
        raise WorkflowError(
            f"Document evidence needs at least {MIN_DOCUMENT_HEADINGS} Markdown headings: {path.name}"
        )


def contains_marker(text: str, marker: str) -> bool:
    variants = {marker, marker.replace("_", " "), marker.replace("_", "-")}
    return any(variant.lower() in text.lower() for variant in variants)


def cmd_init(args: argparse.Namespace) -> None:
    root = repository_root(args.root)
    pointer = active_pointer(root)
    if pointer.exists() and not args.force:
        active = load_data(pointer).get("workflow_id", "unknown")
        raise WorkflowError(f"Workflow {active} is already active. Complete it or use --force.")

    workflow_id = args.id or workflow_id_from_title(args.title)
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{2,80}", workflow_id):
        raise WorkflowError("Workflow ID must be 3-81 characters using letters, digits, dot, underscore, or hyphen.")
    path = state_path(root, workflow_id)
    if path.exists() and not args.force:
        raise WorkflowError(f"Workflow already exists: {workflow_id}")

    docs_dir = root / "docs" / "requirements" / workflow_id
    docs_dir.mkdir(parents=True, exist_ok=True)
    request_path = docs_dir / "00-original-request.md"
    request_path.write_text(
        f"# Original request: {args.title}\n\n{args.request.strip()}\n",
        encoding="utf-8",
    )
    timestamp = now()
    state: dict[str, Any] = {
        "schema_version": 1,
        "workflow": {
            "id": workflow_id,
            "title": args.title,
            "mode": args.mode,
            "status": "active",
            "current_stage": FLOWS[args.mode][0],
            "created_at": timestamp,
            "updated_at": timestamp,
        },
        "artifacts": {
            "original_request": {
                "path": str(request_path.relative_to(root)),
                "status": "ready",
                "updated_at": timestamp,
                "notes": "Captured during workflow initialization.",
            }
        },
        "issues": [],
        "decisions": {},
        "meetings": [],
        "history": [
            {"at": timestamp, "event": "initialized", "detail": f"Started {args.mode} workflow"}
        ],
    }
    save_state(path, state)
    save_data(
        pointer,
        {
            "workflow_id": workflow_id,
            "state_path": str(path.relative_to(root)),
            "updated_at": timestamp,
        },
    )
    print(f"Initialized {workflow_id} in {args.mode} mode")
    print(f"State: {path.relative_to(root)}")
    print(f"Artifacts: {docs_dir.relative_to(root)}")


def cmd_status(args: argparse.Namespace) -> None:
    root = repository_root(args.root)
    _, state = load_state(root, args.id)
    if args.json:
        print(json.dumps(state, indent=2, ensure_ascii=False))
        return
    workflow = state["workflow"]
    blockers = open_blockers(state)
    print(f"Workflow: {workflow['id']} — {workflow['title']}")
    print(f"Mode: {workflow['mode']}  Status: {workflow['status']}  Stage: {workflow['current_stage']}")
    print(f"Artifacts satisfied: {sum(artifact_ready(state, name) for name in ARTIFACTS)}")
    print(f"Meeting notes: {len(state.get('meetings', []))}")
    print(f"Open blockers: {len(blockers)}")
    missing, notes = stage_requirements(state)
    print("Can advance: " + ("yes" if not missing and workflow["status"] == "active" else "no"))
    for item in missing:
        print(f"- {item}")
    for item in notes:
        print(f"- note:{item}")


def cmd_next(args: argparse.Namespace) -> None:
    root = repository_root(args.root)
    _, state = load_state(root, args.id)
    workflow = state["workflow"]
    stage = workflow["current_stage"]
    if stage == "completed":
        print("Workflow is complete. No next action.")
        return
    missing, notes = stage_requirements(state)
    print(f"Current stage: {stage}")
    if missing:
        print("Required before advancing:")
        for item in missing:
            print(f"- {item}")
    else:
        stages = FLOWS[workflow["mode"]]
        next_stage = stages[stages.index(stage) + 1]
        print(f"Ready to advance to: {next_stage}")
    for item in notes:
        print(f"Note: {item}")


def cmd_record_artifact(args: argparse.Namespace) -> None:
    root = repository_root(args.root)
    path, state = load_state(root, args.id)
    if args.status == "not_applicable" and args.name not in NOT_APPLICABLE_ALLOWED:
        raise WorkflowError(f"Artifact {args.name} cannot be marked not_applicable.")
    if args.status == "not_applicable" and not (args.notes or "").strip():
        raise WorkflowError("A not_applicable artifact requires a justification in --notes.")
    minimum = MIN_DOCUMENT_CHARS if args.name in DOCUMENT_ARTIFACTS and args.status == "ready" else 0
    absolute, relative = repository_evidence_path(root, args.path, minimum_chars=minimum)
    if args.name in DOCUMENT_ARTIFACTS and args.status == "ready":
        require_markdown_structure(absolute)
    for other_name, other in state.get("artifacts", {}).items():
        if other_name != args.name and other.get("path") == str(relative) and other.get("status") != "superseded":
            raise WorkflowError(f"Artifact path is already used by {other_name}: {relative}")
    state.setdefault("artifacts", {})[args.name] = {
        "path": str(relative),
        "status": args.status,
        "updated_at": now(),
        "notes": args.notes or "",
    }
    invalidated: list[str] = []
    for gate in ARTIFACT_INVALIDATES_GATES.get(args.name, ()):
        if gate in state.get("decisions", {}):
            del state["decisions"][gate]
            invalidated.append(gate)
    invalidated_meetings = invalidate_gate_meetings(
        state,
        tuple(ARTIFACT_INVALIDATES_GATES.get(args.name, ())),
        f"Artifact {args.name} changed",
    )
    add_history(state, "artifact_recorded", f"{args.name}={args.status}:{relative}")
    if invalidated:
        add_history(state, "decisions_invalidated", f"{args.name}:{','.join(invalidated)}")
    if invalidated_meetings:
        add_history(state, "meetings_invalidated", ",".join(invalidated_meetings))
    save_state(path, state)
    print(f"Recorded artifact {args.name} ({args.status}): {relative}")


def next_issue_id(state: dict[str, Any]) -> str:
    numbers = []
    for issue in state.get("issues", []):
        match = re.fullmatch(r"ISSUE-(\d+)", str(issue.get("id", "")))
        if match:
            numbers.append(int(match.group(1)))
    return f"ISSUE-{max(numbers, default=0) + 1:03d}"


def next_meeting_id(state: dict[str, Any]) -> str:
    numbers = []
    for meeting in state.get("meetings", []):
        match = re.fullmatch(r"MTG-(\d+)", str(meeting.get("id", "")))
        if match:
            numbers.append(int(match.group(1)))
    return f"MTG-{max(numbers, default=0) + 1:03d}"


def cmd_add_issue(args: argparse.Namespace) -> None:
    root = repository_root(args.root)
    path, state = load_state(root, args.id)
    issue_id = next_issue_id(state)
    issue = {
        "id": issue_id,
        "source": args.source,
        "owner": args.owner,
        "severity": args.severity,
        "summary": args.summary,
        "status": "open",
        "resolution": "",
        "created_at": now(),
        "resolved_at": None,
    }
    state.setdefault("issues", []).append(issue)
    current_stage = state["workflow"]["current_stage"]
    invalidated_meetings = (
        invalidate_gate_meetings(state, (current_stage,), f"Issue {issue_id} added")
        if current_stage in GATES
        else []
    )
    add_history(state, "issue_added", f"{issue_id}:{args.severity}:{args.summary}")
    if invalidated_meetings:
        add_history(state, "meetings_invalidated", ",".join(invalidated_meetings))
    save_state(path, state)
    print(f"Added {issue_id}")


def cmd_resolve_issue(args: argparse.Namespace) -> None:
    root = repository_root(args.root)
    path, state = load_state(root, args.id)
    evidence_path, evidence = repository_evidence_path(
        root, args.evidence, minimum_chars=MIN_DOCUMENT_CHARS
    )
    evidence_hash = content_sha256(evidence_path)
    for issue in state.get("issues", []):
        if issue.get("id") == args.issue_id:
            if issue.get("status") == "resolved":
                raise WorkflowError(f"Issue already resolved: {args.issue_id}")
            if args.resolved_by != issue.get("owner"):
                raise WorkflowError(
                    f"Issue owner is {issue.get('owner')}; got resolved_by={args.resolved_by}."
                )
            evidence_text = evidence_path.read_text(encoding="utf-8")
            if args.issue_id not in evidence_text:
                raise WorkflowError(f"Resolution evidence must name {args.issue_id}.")
            for decisions in state.get("decisions", {}).values():
                for decision in decisions.values():
                    if decision.get("evidence_sha256") == evidence_hash:
                        raise WorkflowError("Resolution evidence reuses a gate review document.")
            for previous in state.get("issues", []):
                if previous.get("resolution_evidence_sha256") == evidence_hash:
                    raise WorkflowError("Resolution evidence is already used by another issue.")
            issue["status"] = "resolved"
            issue["resolution"] = args.resolution
            issue["resolved_by"] = args.resolved_by
            issue["resolution_evidence"] = str(evidence)
            issue["resolution_evidence_sha256"] = evidence_hash
            issue["resolved_at"] = now()
            current_stage = state["workflow"]["current_stage"]
            invalidated_meetings = (
                invalidate_gate_meetings(
                    state, (current_stage,), f"Issue {args.issue_id} resolved"
                )
                if current_stage in GATES
                else []
            )
            add_history(state, "issue_resolved", f"{args.issue_id}:{args.resolution}")
            if invalidated_meetings:
                add_history(state, "meetings_invalidated", ",".join(invalidated_meetings))
            save_state(path, state)
            print(f"Resolved {args.issue_id}")
            return
    raise WorkflowError(f"Unknown issue: {args.issue_id}")


def cmd_decide(args: argparse.Namespace) -> None:
    root = repository_root(args.root)
    path, state = load_state(root, args.id)
    current = state["workflow"]["current_stage"]
    if current != args.gate:
        raise WorkflowError(f"Cannot decide {args.gate} while current stage is {current}.")
    required_roles = required_gate_roles(state, args.gate)
    if args.role not in required_roles:
        raise WorkflowError(f"Role {args.role} is not a reviewer for {args.gate} in this mode.")
    evidence_path, evidence = repository_evidence_path(
        root, args.evidence, minimum_chars=MIN_DOCUMENT_CHARS
    )
    evidence_text = evidence_path.read_text(encoding="utf-8")
    for required_text in (args.gate, args.role, "verdict", args.verdict):
        if not contains_marker(evidence_text, required_text):
            readable = required_text.replace("_", " ")
            raise WorkflowError(f"Review evidence must identify: {readable}")
    evidence_hash = content_sha256(evidence_path)
    for gate, decisions in state.get("decisions", {}).items():
        for role, decision in decisions.items():
            if (
                decision.get("evidence_sha256") == evidence_hash
                and (gate, role) != (args.gate, args.role)
            ):
                raise WorkflowError(f"Review evidence content is already used by {gate}:{role}.")
    invalidated_meetings = invalidate_gate_meetings(
        state, (args.gate,), f"{args.role} decision changed"
    )
    state.setdefault("decisions", {}).setdefault(args.gate, {})[args.role] = {
        "verdict": args.verdict,
        "notes": args.notes or "",
        "evidence": str(evidence),
        "evidence_sha256": evidence_hash,
        "at": now(),
    }
    add_history(state, "gate_decision", f"{args.gate}:{args.role}:{args.verdict}")
    if invalidated_meetings:
        add_history(state, "meetings_invalidated", ",".join(invalidated_meetings))
    save_state(path, state)
    print(f"Recorded {args.role}={args.verdict} for {args.gate}")


def cmd_record_meeting(args: argparse.Namespace) -> None:
    root = repository_root(args.root)
    path, state = load_state(root, args.id)
    stage = state["workflow"]["current_stage"]
    if args.type in GATES and args.type != stage:
        raise WorkflowError(f"Cannot record {args.type} minutes while current stage is {stage}.")

    participants = tuple(
        dict.fromkeys(item.strip() for item in args.participants.split(",") if item.strip())
    )
    if len(participants) < 2:
        raise WorkflowError("Meeting notes require at least two distinct participants.")
    unknown = sorted(set(participants) - set(MEETING_PARTICIPANTS))
    if unknown:
        raise WorkflowError(f"Unknown meeting participants: {','.join(unknown)}")

    meeting_path, relative = repository_evidence_path(
        root, args.path, minimum_chars=MIN_DOCUMENT_CHARS
    )
    require_markdown_structure(meeting_path)
    content = meeting_path.read_text(encoding="utf-8")
    if not contains_marker(content, args.type):
        raise WorkflowError(f"Meeting notes must identify: {args.type.replace('_', ' ')}")
    for participant in participants:
        if not contains_marker(content, participant):
            raise WorkflowError(f"Meeting notes must identify participant: {participant}")

    evidence_hash = content_sha256(meeting_path)
    for meeting in state.get("meetings", []):
        if meeting.get("evidence_sha256") == evidence_hash:
            raise WorkflowError(f"Meeting-note content is already used by {meeting.get('id')}.")

    decision_snapshot: dict[str, str] = {}
    if args.type in GATES:
        required_roles = set(required_gate_roles(state, args.type))
        if not required_roles.issubset(set(participants)):
            missing = sorted(required_roles - set(participants))
            raise WorkflowError(f"Gate meeting is missing participants: {','.join(missing)}")
        decisions = state.get("decisions", {}).get(args.type, {})
        missing_decisions = sorted(required_roles - set(decisions))
        if missing_decisions:
            raise WorkflowError(f"Gate meeting is missing role decisions: {','.join(missing_decisions)}")
        verdicts = {decisions[role].get("verdict") for role in required_roles}
        if args.outcome == "approved" and verdicts != {"approve"}:
            raise WorkflowError("An approved meeting requires every role verdict to approve.")
        if "reject" in verdicts and args.outcome == "approved":
            raise WorkflowError("A rejected role verdict cannot produce an approved meeting.")
        decision_snapshot = gate_decision_snapshot(state, args.type)

    meeting_id = next_meeting_id(state)
    meeting = {
        "id": meeting_id,
        "type": args.type,
        "title": args.title,
        "stage": stage,
        "participants": list(participants),
        "outcome": args.outcome,
        "path": str(relative),
        "evidence_sha256": evidence_hash,
        "decision_snapshot": decision_snapshot,
        "status": "current",
        "created_at": now(),
    }
    state.setdefault("meetings", []).append(meeting)
    add_history(state, "meeting_recorded", f"{meeting_id}:{args.type}:{args.outcome}")
    save_state(path, state)
    print(f"Recorded {meeting_id} ({args.type}): {relative}")


def cmd_advance(args: argparse.Namespace) -> None:
    root = repository_root(args.root)
    path, state = load_state(root, args.id)
    workflow = state["workflow"]
    if workflow["status"] != "active":
        raise WorkflowError(f"Workflow status is {workflow['status']}, not active.")
    stage = workflow["current_stage"]
    if stage == "completed":
        raise WorkflowError("Workflow is already complete.")
    missing, notes = stage_requirements(state)
    if missing:
        detail = ", ".join(missing)
        if notes:
            detail += "; " + "; ".join(notes)
        raise WorkflowError(f"Gate blocked: {detail}")
    stages = FLOWS[workflow["mode"]]
    new_stage = stages[stages.index(stage) + 1]
    workflow["current_stage"] = new_stage
    if new_stage == "completed":
        workflow["status"] = "completed"
        pointer = active_pointer(root)
        if pointer.exists():
            active = load_data(pointer)
            if active.get("workflow_id") == workflow["id"]:
                pointer.unlink()
    add_history(state, "advanced", f"{stage}->{new_stage}")
    save_state(path, state)
    print(f"Advanced {stage} -> {new_stage}")


def cmd_reopen(args: argparse.Namespace) -> None:
    root = repository_root(args.root)
    path, state = load_state(root, args.id)
    mode = state["workflow"]["mode"]
    if args.stage not in FLOWS[mode] or args.stage == "completed":
        raise WorkflowError(f"Stage {args.stage} is not valid for {mode} mode.")
    old_stage = state["workflow"]["current_stage"]
    state["workflow"]["current_stage"] = args.stage
    state["workflow"]["status"] = "active"
    stages = FLOWS[mode]
    reopened_index = stages.index(args.stage)
    for gate in list(state.get("decisions", {})):
        if gate in stages and stages.index(gate) >= reopened_index:
            del state["decisions"][gate]
    invalidated_meetings: list[str] = []
    for meeting in state.get("meetings", []):
        meeting_stage = meeting.get("stage")
        if (
            meeting.get("status") == "current"
            and meeting_stage in stages
            and stages.index(meeting_stage) >= reopened_index
        ):
            meeting["status"] = "superseded"
            meeting["superseded_at"] = now()
            meeting["superseded_reason"] = f"Workflow reopened at {args.stage}"
            invalidated_meetings.append(str(meeting.get("id")))
    invalidated_artifacts: list[str] = []
    for name, produced_at in ARTIFACT_STAGE.items():
        if produced_at in stages and stages.index(produced_at) >= reopened_index:
            artifact = state.get("artifacts", {}).get(name)
            if artifact and artifact.get("status") in {"ready", "not_applicable"}:
                artifact["status"] = "superseded"
                artifact["updated_at"] = now()
                invalidated_artifacts.append(name)
    add_history(state, "reopened", f"{old_stage}->{args.stage}:{args.reason}")
    if invalidated_artifacts:
        add_history(state, "artifacts_invalidated", ",".join(invalidated_artifacts))
    if invalidated_meetings:
        add_history(state, "meetings_invalidated", ",".join(invalidated_meetings))
    save_state(path, state)
    save_data(
        active_pointer(root),
        {
            "workflow_id": state["workflow"]["id"],
            "state_path": str(path.relative_to(root)),
            "updated_at": now(),
        },
    )
    print(f"Reopened workflow at {args.stage}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", help="Repository root; defaults to git root or current directory")
    parser.add_argument("--id", help="Workflow ID; defaults to the active workflow")
    subparsers = parser.add_subparsers(dest="command", required=True)

    init = subparsers.add_parser("init", help="Initialize and activate a workflow")
    init.add_argument(
        "--id",
        default=argparse.SUPPRESS,
        help="Workflow ID; generated from the title when omitted",
    )
    init.add_argument("--title", required=True)
    init.add_argument("--mode", choices=tuple(FLOWS), default="standard")
    init.add_argument("--request", required=True)
    init.add_argument("--force", action="store_true")
    init.set_defaults(func=cmd_init)

    status = subparsers.add_parser("status", help="Show workflow status")
    status.add_argument("--json", action="store_true")
    status.set_defaults(func=cmd_status)

    next_cmd = subparsers.add_parser("next", help="Show the next required evidence or transition")
    next_cmd.set_defaults(func=cmd_next)

    artifact = subparsers.add_parser("record-artifact", help="Record an existing repository artifact")
    artifact.add_argument("--name", choices=ARTIFACTS, required=True)
    artifact.add_argument("--path", required=True)
    artifact.add_argument("--status", choices=("ready", "not_applicable", "superseded"), default="ready")
    artifact.add_argument("--notes")
    artifact.set_defaults(func=cmd_record_artifact)

    issue = subparsers.add_parser("add-issue", help="Add a tracked review issue")
    issue.add_argument("--source", choices=("product", "engineering", "testing", "user", "coordinator"), required=True)
    issue.add_argument("--owner", choices=("product", "engineering", "testing", "user", "coordinator"), default="coordinator")
    issue.add_argument("--severity", choices=("blocker", "major", "minor"), required=True)
    issue.add_argument("--summary", required=True)
    issue.set_defaults(func=cmd_add_issue)

    resolve = subparsers.add_parser("resolve-issue", help="Resolve a tracked issue")
    resolve.add_argument("--issue-id", required=True)
    resolve.add_argument("--resolution", required=True)
    resolve.add_argument("--resolved-by", choices=("product", "engineering", "testing", "user", "coordinator"), required=True)
    resolve.add_argument("--evidence", required=True, help="Repository file documenting the resolution")
    resolve.set_defaults(func=cmd_resolve_issue)

    decide = subparsers.add_parser("decide", help="Record an independent role verdict at the current gate")
    decide.add_argument("--gate", choices=GATES, required=True)
    decide.add_argument("--role", choices=ROLES, required=True)
    decide.add_argument("--verdict", choices=("approve", "reject"), required=True)
    decide.add_argument("--evidence", required=True, help="Unique repository review record for this role and gate")
    decide.add_argument("--notes")
    decide.set_defaults(func=cmd_decide)

    meeting = subparsers.add_parser(
        "record-meeting", help="Index structured notes for a cross-role communication"
    )
    meeting.add_argument("--type", choices=MEETING_TYPES, required=True)
    meeting.add_argument("--title", required=True)
    meeting.add_argument(
        "--participants",
        required=True,
        help="Comma-separated roles, for example product,engineering,testing",
    )
    meeting.add_argument("--outcome", choices=MEETING_OUTCOMES, required=True)
    meeting.add_argument("--path", required=True)
    meeting.set_defaults(func=cmd_record_meeting)

    advance = subparsers.add_parser("advance", help="Advance only when deterministic gate requirements pass")
    advance.set_defaults(func=cmd_advance)

    reopen = subparsers.add_parser("reopen", help="Reopen at an earlier stage and invalidate downstream decisions")
    reopen.add_argument("--stage", required=True)
    reopen.add_argument("--reason", required=True)
    reopen.set_defaults(func=cmd_reopen)
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    try:
        args.func(args)
        return 0
    except WorkflowError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
