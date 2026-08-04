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

from risk_policy import (
    CLOSED_RISK_STATUSES,
    MODE_RANK,
    NON_WAIVABLE_ESCALATION_FLAGS,
    REQUIREMENT_AREAS,
    RISK_FLAGS,
    combined_risk_flags,
    recommended_mode_for,
    refresh_escalation,
)
from risk_commands import invoke as invoke_risk_command
from review_commands import invoke as invoke_review_command
from assurance_commands import invoke as invoke_assurance_command
from delivery_commands import invoke as invoke_delivery_command
from execution_policy import EXECUTION_POLICIES, execute_verification_commands, repository_context
from source_policy import SourcePolicyError, source_binding, workspace_binding
from state_store import (
    WorkflowError,
    atomic_write_text,
    load_data,
    save_data,
    state_checksum,
    verify_state_checksum,
    workflow_lock,
)
from workflow_cli import MUTATING_COMMANDS, build_parser as create_cli_parser


CURRENT_SCHEMA_VERSION = 10
WORKFLOW_ID_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{2,80}")
ROLES = ("product", "engineering", "testing")
GATES = ("prd_review", "readiness_review", "acceptance")
MEETING_TYPES = GATES + ("design_sync", "defect_triage", "change_control", "ad_hoc")
MEETING_PARTICIPANTS = ROLES + ("user", "coordinator")
MEETING_OUTCOMES = ("approved", "rejected", "aligned", "actions_required", "escalated")
ARTIFACTS = (
    "original_request",
    "risk_assessment",
    "clarification_questions",
    "requirement_confirmation",
    "core_goals",
    "prd",
    "review_log",
    "technical_design",
    "database_design",
    "test_plan",
    "test_cases",
    "prototype",
    "user_feedback",
    "implementation",
    "verification_report",
    "journey_report",
    "release_plan",
    "delivery_report",
    "delivery_confirmation",
    "traceability",
)
ARTIFACT_STAGE = {
    "original_request": "intake",
    "risk_assessment": "scope_check",
    "clarification_questions": "clarification",
    "requirement_confirmation": "requirement_confirmation",
    "core_goals": "requirement_confirmation",
    "prd": "prd",
    "review_log": "prd_review",
    "technical_design": "design",
    "database_design": "design",
    "test_plan": "design",
    "test_cases": "design",
    "release_plan": "design",
    "prototype": "prototype",
    "user_feedback": "user_feedback",
    "implementation": "implementation",
    "verification_report": "verification",
    "journey_report": "verification",
    "traceability": "verification",
    "delivery_report": "acceptance",
    "delivery_confirmation": "delivery_confirmation",
}
ARTIFACT_CHANGE_STAGE = {
    "original_request": "intake",
    "risk_assessment": "scope_check",
    "clarification_questions": "clarification",
    "requirement_confirmation": "requirement_confirmation",
    "core_goals": "requirement_confirmation",
    "prd": "prd",
    "technical_design": "design",
    "database_design": "design",
    "test_plan": "design",
    "test_cases": "design",
    "release_plan": "design",
    "prototype": "prototype",
    "user_feedback": "user_feedback",
    "implementation": "implementation",
    "verification_report": "verification",
    "journey_report": "verification",
    "traceability": "verification",
    "delivery_report": "acceptance",
    "delivery_confirmation": "delivery_confirmation",
}
ARTIFACT_INVALIDATES_GATES = {
    "requirement_confirmation": GATES,
    "core_goals": GATES,
    "prd": GATES,
    "technical_design": ("readiness_review", "acceptance"),
    "database_design": ("readiness_review", "acceptance"),
    "test_plan": ("readiness_review", "acceptance"),
    "test_cases": ("readiness_review", "acceptance"),
    "release_plan": ("readiness_review", "acceptance"),
    "prototype": ("acceptance",),
    "user_feedback": ("acceptance",),
    "implementation": ("acceptance",),
    "verification_report": ("acceptance",),
    "journey_report": ("acceptance",),
    "traceability": ("acceptance",),
    "delivery_report": ("acceptance",),
    "delivery_confirmation": (),
}
NOT_APPLICABLE_ALLOWED = {"database_design", "test_cases", "release_plan", "traceability"}
DOCUMENT_ARTIFACTS = {
    "risk_assessment",
    "clarification_questions",
    "requirement_confirmation",
    "core_goals",
    "prd",
    "technical_design",
    "database_design",
    "test_plan",
    "test_cases",
    "prototype",
    "user_feedback",
    "verification_report",
    "journey_report",
    "release_plan",
    "delivery_report",
    "delivery_confirmation",
    "traceability",
    "review_log",
}
MIN_DOCUMENT_CHARS = 80
MIN_DOCUMENT_HEADINGS = 3
JOURNEY_CHECKS = (
    "launch",
    "core_outcomes",
    "content_semantics",
    "interactions",
    "external_links",
    "ui_quality",
    "release_hygiene",
    "source_truth",
)
JOURNEY_RESULTS = ("pass", "fail", "blocked", "not_applicable")
JOURNEY_PROFILES = {
    "web": JOURNEY_CHECKS,
    "desktop": JOURNEY_CHECKS,
    "api": (
        "launch",
        "core_outcomes",
        "content_semantics",
        "interactions",
        "external_links",
        "release_hygiene",
        "source_truth",
    ),
    "cli": (
        "launch",
        "core_outcomes",
        "content_semantics",
        "interactions",
        "release_hygiene",
        "source_truth",
    ),
    "library": (
        "core_outcomes",
        "content_semantics",
        "interactions",
        "release_hygiene",
        "source_truth",
    ),
    "data": (
        "core_outcomes",
        "content_semantics",
        "interactions",
        "release_hygiene",
        "source_truth",
    ),
}
FLOWS = {
    "auto": (
        "intake",
        "scope_check",
    ),
    "micro": (
        "intake",
        "scope_check",
        "implementation",
        "verification",
        "delivery_confirmation",
        "completed",
    ),
    "quick": (
        "intake",
        "scope_check",
        "clarification",
        "requirement_confirmation",
        "design",
        "readiness_review",
        "prototype",
        "user_feedback",
        "implementation",
        "verification",
        "acceptance",
        "delivery_confirmation",
        "completed",
    ),
    "standard": (
        "intake",
        "scope_check",
        "clarification",
        "requirement_confirmation",
        "prd",
        "prd_review",
        "design",
        "readiness_review",
        "prototype",
        "user_feedback",
        "implementation",
        "verification",
        "acceptance",
        "delivery_confirmation",
        "completed",
    ),
    "strict": (
        "intake",
        "scope_check",
        "clarification",
        "requirement_confirmation",
        "prd",
        "prd_review",
        "design",
        "readiness_review",
        "prototype",
        "user_feedback",
        "implementation",
        "verification",
        "acceptance",
        "delivery_confirmation",
        "completed",
    ),
}
LEGACY_V3_FLOWS = {
    mode: tuple(
        stage
        for stage in stages
        if stage not in {"scope_check", "delivery_confirmation"}
    )
    for mode, stages in FLOWS.items()
    if mode in {"quick", "standard", "strict"}
}
GATE_ROLES = {
    "auto": {},
    "micro": {},
    "quick": {
        "readiness_review": ("engineering", "testing"),
        "acceptance": ("product", "engineering", "testing"),
    },
    "standard": {gate: ROLES for gate in GATES},
    "strict": {gate: ROLES for gate in GATES},
}
STAGE_LABELS = {
    "intake": "Intake",
    "scope_check": "Scope and risk check",
    "clarification": "Requirement clarification",
    "requirement_confirmation": "Requirement confirmation",
    "prd": "PRD drafting",
    "prd_review": "PRD review",
    "design": "Design and test planning",
    "readiness_review": "Readiness review",
    "prototype": "Prototype or MVP preview",
    "user_feedback": "User feedback",
    "implementation": "Implementation",
    "verification": "Verification",
    "acceptance": "Acceptance",
    "delivery_confirmation": "User delivery confirmation",
    "completed": "Completed",
}
STAGE_GUIDANCE = {
    "intake": "Capture the raw request and advance to a scope and risk check.",
    "scope_check": "Analyze requirement gaps and risks, recommend the lowest safe workflow mode, and record the task baseline.",
    "clarification": "Identify missing details, ambiguities, edge cases, constraints, and acceptance criteria before drafting PRD.",
    "requirement_confirmation": "Ask the user to confirm the synthesized requirement understanding before formal design or development.",
    "prd": "Have product create or revise the PRD, then record the PRD artifact.",
    "prd_review": "Collect independent product, engineering, and testing verdicts, then record gate meeting notes.",
    "design": "Create technical design and test plan artifacts; strict mode may also need database and release plans.",
    "readiness_review": "Review whether implementation can start, record role verdicts, and preserve meeting notes.",
    "prototype": "Create the smallest inspectable prototype, MVP, screenshot, or demo that lets the user judge direction.",
    "user_feedback": "Collect explicit user feedback on the preview; if rejected, revise requirements or design before final implementation.",
    "implementation": "Implement the approved scope and record implementation evidence.",
    "verification": "Run verification, record the report, and triage any defects.",
    "acceptance": "Review delivery evidence, handle major findings, and record final acceptance.",
    "delivery_confirmation": "Show the verified result and evidence to the user; finish only after explicit approval, or rewind when changes are requested.",
    "completed": "No next workflow action is required.",
}


def now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def workflow_stages(state: dict[str, Any]) -> tuple[str, ...]:
    configured = state.get("workflow", {}).get("flow_stages")
    if isinstance(configured, list) and configured:
        return tuple(str(stage) for stage in configured)
    return FLOWS[state["workflow"]["mode"]]


def flow_for(mode: str, gate_policy: dict[str, bool] | None = None) -> tuple[str, ...]:
    if mode != "quick":
        return FLOWS[mode]
    policy = gate_policy or {}
    stages = ["intake", "scope_check"]
    if policy.get("clarification"):
        stages.append("clarification")
    if policy.get("requirement_confirmation"):
        stages.append("requirement_confirmation")
    stages.extend(("design", "readiness_review"))
    if policy.get("preview"):
        stages.extend(("prototype", "user_feedback"))
    stages.extend(
        ("implementation", "verification", "acceptance", "delivery_confirmation", "completed")
    )
    return tuple(stages)


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


def active_pointer(root: Path) -> Path:
    return root / ".ai-workflow" / "active.yaml"


def validate_workflow_id(workflow_id: str) -> None:
    if not WORKFLOW_ID_PATTERN.fullmatch(workflow_id):
        raise WorkflowError(
            "Workflow ID must be 3-81 characters using letters, digits, dot, underscore, or hyphen."
        )


def state_path(root: Path, workflow_id: str | None = None) -> Path:
    if workflow_id:
        validate_workflow_id(workflow_id)
        return root / ".ai-workflow" / workflow_id / "state.yaml"
    pointer = active_pointer(root)
    if not pointer.exists():
        raise WorkflowError("No active workflow. Start one with the init command.")
    data = load_data(pointer)
    relative = data.get("state_path")
    if not isinstance(relative, str) or not relative:
        raise WorkflowError(f"Invalid active pointer: {pointer}")
    resolved = (root / relative).resolve()
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise WorkflowError("Active workflow state must be inside the repository root.") from exc
    return resolved


def load_state(root: Path, workflow_id: str | None = None) -> tuple[Path, dict[str, Any]]:
    path = state_path(root, workflow_id)
    state = load_data(path)
    verify_state_checksum(state, path, CURRENT_SCHEMA_VERSION)
    migrate_state(root, state)
    validate_state(state, path)
    return path, state


def migrate_state(root: Path, state: dict[str, Any]) -> None:
    version = state.get("schema_version")
    if version in {1, 2, 3, 4, 5, 6, 7, 8, 9}:
        state["schema_version"] = CURRENT_SCHEMA_VERSION
        state.setdefault("revision", 0)
        state.setdefault("human_approval_policy", {"required_gates": []})
        state.setdefault("human_approvals", {})
        workflow = state.setdefault("workflow", {})
        legacy_mode = workflow.get("mode")
        if legacy_mode in LEGACY_V3_FLOWS:
            workflow.setdefault("requested_mode", legacy_mode)
            workflow.setdefault("flow_stages", list(LEGACY_V3_FLOWS[legacy_mode]))
        state.setdefault("risk_assessment", {"status": "legacy_not_required"})
        state.setdefault("user_feedback_records", [])
        state.setdefault("delivery_confirmation_records", [])
        state.setdefault("risk_reports", [])
        state.setdefault("escalation", {"status": "none"})
        if version >= 5 and workflow.get("status") == "active":
            configured = workflow.get("flow_stages", [])
            if "delivery_confirmation" not in configured and "completed" in configured:
                configured.insert(configured.index("completed"), "delivery_confirmation")
    state.setdefault("core_goals", {})
    state.setdefault("scope_changes", [])
    state.setdefault("acceptance_criteria", {})
    state.setdefault("criterion_verdicts", {})
    state.setdefault("core_outcomes", {})
    state.setdefault("source_revision", {})
    state.setdefault("verification_snapshot", {})
    state.setdefault("journey_validation", {})
    state.setdefault("repository_context", {})
    for collection in ("artifacts", "human_approvals"):
        for item in state.get(collection, {}).values():
            if item.get("status") == "not_applicable" or item.get("evidence_sha256"):
                continue
            try:
                evidence_path, _ = repository_evidence_path(root, str(item.get("path", item.get("evidence", ""))))
            except WorkflowError:
                continue
            if evidence_path.is_file():
                item["evidence_sha256"] = content_sha256(evidence_path)
    for decisions in state.get("decisions", {}).values():
        for decision in decisions.values():
            if decision.get("evidence_sha256"):
                continue
            try:
                evidence_path, _ = repository_evidence_path(root, str(decision.get("evidence", "")))
            except WorkflowError:
                continue
            if evidence_path.is_file():
                decision["evidence_sha256"] = content_sha256(evidence_path)
    for meeting in state.get("meetings", []):
        if meeting.get("evidence_sha256"):
            continue
        try:
            evidence_path, _ = repository_evidence_path(root, str(meeting.get("path", "")))
        except WorkflowError:
            continue
        if evidence_path.is_file():
            meeting["evidence_sha256"] = content_sha256(evidence_path)


def validate_state(state: dict[str, Any], path: Path) -> None:
    if state.get("schema_version") != CURRENT_SCHEMA_VERSION:
        raise WorkflowError(
            f"Unsupported schema_version in {path}: {state.get('schema_version')}; "
            f"expected {CURRENT_SCHEMA_VERSION}."
        )
    revision = state.get("revision")
    if not isinstance(revision, int) or revision < 0:
        raise WorkflowError(f"Invalid revision in {path}: {revision!r}")
    workflow = state.get("workflow")
    if not isinstance(workflow, dict):
        raise WorkflowError(f"Missing workflow mapping in {path}")
    mode = workflow.get("mode")
    stage = workflow.get("current_stage")
    if mode not in FLOWS:
        raise WorkflowError(f"Invalid workflow mode in {path}: {mode!r}")
    configured_stages = workflow.get("flow_stages")
    if not isinstance(configured_stages, list) or not configured_stages:
        raise WorkflowError(f"Invalid workflow flow_stages in {path}")
    allowed_stages = set(STAGE_LABELS)
    if (
        configured_stages[0] != "intake"
        or len(configured_stages) != len(set(configured_stages))
        or any(item not in allowed_stages for item in configured_stages)
        or (mode != "auto" and configured_stages[-1] != "completed")
    ):
        raise WorkflowError(f"Invalid workflow flow_stages in {path}: {configured_stages!r}")
    if stage not in configured_stages:
        raise WorkflowError(f"Invalid workflow stage in {path}: {stage!r}")
    if workflow.get("status") not in {"active", "paused", "completed"}:
        raise WorkflowError(f"Invalid workflow status in {path}: {workflow.get('status')!r}")
    required_gates = state.get("human_approval_policy", {}).get("required_gates", [])
    if not isinstance(required_gates, list) or any(gate not in GATES for gate in required_gates):
        raise WorkflowError(f"Invalid human approval policy in {path}")
    for name in (
        "artifacts",
        "decisions",
        "human_approvals",
        "escalation",
        "core_goals",
        "acceptance_criteria",
        "criterion_verdicts",
        "core_outcomes",
        "source_revision",
        "verification_snapshot",
        "journey_validation",
        "repository_context",
    ):
        if not isinstance(state.get(name), dict):
            raise WorkflowError(f"Invalid {name} mapping in {path}")
    for name in (
        "issues",
        "meetings",
        "history",
        "user_feedback_records",
        "delivery_confirmation_records",
        "risk_reports",
        "scope_changes",
    ):
        if not isinstance(state.get(name), list):
            raise WorkflowError(f"Invalid {name} list in {path}")


def workflow_id_from_title(title: str) -> str:
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:32]
    if not slug:
        slug = "requirement"
    return f"REQ-{timestamp}-{slug}"


def title_from_request(request: str) -> str:
    compact = " ".join(request.strip().split())
    if not compact:
        return "Requirement"
    sentence = re.split(r"[。.!?]\s*", compact, maxsplit=1)[0].strip()
    return sentence[:60] or "Requirement"


def add_history(state: dict[str, Any], event: str, detail: str) -> None:
    state.setdefault("history", []).append({"at": now(), "event": event, "detail": detail})
    state["workflow"]["updated_at"] = now()


def evidence_matches(root: Path, raw_path: str, expected_hash: str | None) -> bool:
    """Return whether an indexed repository file still has its recorded content."""
    if not expected_hash:
        return False
    try:
        evidence_path, _ = repository_evidence_path(root, raw_path)
    except WorkflowError:
        return False
    return evidence_path.is_file() and content_sha256(evidence_path) == expected_hash


def artifact_ready(root: Path, state: dict[str, Any], name: str) -> bool:
    item = state.get("artifacts", {}).get(name, {})
    if item.get("status") == "not_applicable":
        return True
    return item.get("status") == "ready" and evidence_matches(
        root, str(item.get("path", "")), item.get("evidence_sha256")
    )


def test_execution_ready(root: Path, execution: dict[str, Any]) -> bool:
    return bool(
        execution.get("status") == "pass"
        and execution.get("commands")
        and evidence_matches(
            root,
            str(execution.get("log_path", "")),
            execution.get("log_sha256"),
        )
    )


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
        "scope_check": ("risk_assessment",),
        "clarification": ("clarification_questions",),
        "requirement_confirmation": ("requirement_confirmation",),
        "prd": ("prd",),
        "design": ("technical_design", "test_plan"),
        "prototype": ("prototype",),
        "user_feedback": ("user_feedback",),
        "implementation": ("implementation",),
        "verification": ("verification_report",),
        "acceptance": ("delivery_report",),
        "delivery_confirmation": ("delivery_confirmation",),
    }.get(stage, ())
    if mode == "strict" and stage == "design":
        required += ("database_design", "release_plan")
    if mode == "strict" and stage == "requirement_confirmation":
        required += ("core_goals",)
    if mode == "strict" and stage == "verification":
        required += ("journey_report",)
    return required


def required_gate_roles(state: dict[str, Any], gate: str) -> tuple[str, ...]:
    return tuple(GATE_ROLES[state["workflow"]["mode"]].get(gate, ()))


def gate_decision_snapshot(state: dict[str, Any], gate: str) -> dict[str, str]:
    decisions = state.get("decisions", {}).get(gate, {})
    return {
        role: (
            f"{decision.get('verdict', '')}:"
            f"{decision.get('evidence_sha256', '')}:"
            f"{decision.get('actor_ref', '')}"
        )
        for role, decision in sorted(decisions.items())
    }


def gate_meeting_ready(root: Path, state: dict[str, Any], gate: str) -> bool:
    return current_gate_meeting(root, state, gate) is not None


def decision_is_current(root: Path, decision: dict[str, Any]) -> bool:
    return (
        decision.get("verdict") in {"approve", "reject"}
        and bool(str(decision.get("actor_ref", "")).strip())
        and evidence_matches(
            root, str(decision.get("evidence", "")), decision.get("evidence_sha256")
        )
    )


def current_gate_meeting(root: Path, state: dict[str, Any], gate: str) -> dict[str, Any] | None:
    required_roles = set(required_gate_roles(state, gate))
    snapshot = gate_decision_snapshot(state, gate)
    decisions = state.get("decisions", {}).get(gate, {})
    if any(not decision_is_current(root, decisions.get(role, {})) for role in required_roles):
        return None
    for meeting in reversed(state.get("meetings", [])):
        if (
            meeting.get("status") == "current"
            and meeting.get("type") == gate
            and meeting.get("stage") == gate
            and meeting.get("outcome") == "approved"
            and required_roles.issubset(set(meeting.get("participants", [])))
            and meeting.get("decision_snapshot") == snapshot
            and evidence_matches(
                root, str(meeting.get("path", "")), meeting.get("evidence_sha256")
            )
        ):
            return meeting
    return None


def human_approval_required(state: dict[str, Any], gate: str) -> bool:
    return gate in state.get("human_approval_policy", {}).get("required_gates", [])


def human_approval_ready(root: Path, state: dict[str, Any], gate: str) -> bool:
    if not human_approval_required(state, gate):
        return True
    meeting = current_gate_meeting(root, state, gate)
    approval = state.get("human_approvals", {}).get(gate, {})
    return bool(
        meeting
        and approval.get("status") == "current"
        and approval.get("decision_snapshot") == gate_decision_snapshot(state, gate)
        and approval.get("meeting_evidence_sha256") == meeting.get("evidence_sha256")
        and evidence_matches(
            root, str(approval.get("evidence", "")), approval.get("evidence_sha256")
        )
    )


def invalidate_gate_meetings(state: dict[str, Any], gates: tuple[str, ...], reason: str) -> list[str]:
    invalidated: list[str] = []
    for meeting in state.get("meetings", []):
        if meeting.get("status") == "current" and meeting.get("type") in gates:
            meeting["status"] = "superseded"
            meeting["superseded_at"] = now()
            meeting["superseded_reason"] = reason
            invalidated.append(str(meeting.get("id")))
    for gate in gates:
        approval = state.get("human_approvals", {}).get(gate)
        if approval and approval.get("status") == "current":
            approval["status"] = "superseded"
            approval["superseded_at"] = now()
            approval["superseded_reason"] = reason
    return invalidated


def rewind_workflow(
    state: dict[str, Any],
    stage: str,
    reason: str,
    *,
    preserve_artifacts: set[str] | None = None,
) -> tuple[str, list[str], list[str]]:
    """Return a workflow to an affected stage and supersede downstream evidence."""
    preserve_artifacts = preserve_artifacts or set()
    mode = state["workflow"]["mode"]
    stages = workflow_stages(state)
    if stage not in stages or stage == "completed":
        raise WorkflowError(f"Stage {stage} is not valid for {mode} mode.")
    old_stage = state["workflow"]["current_stage"]
    rewind_index = stages.index(stage)
    state["workflow"]["current_stage"] = stage
    state["workflow"]["status"] = "active"

    for gate in list(state.get("decisions", {})):
        if gate in stages and stages.index(gate) >= rewind_index:
            del state["decisions"][gate]

    invalidated_meetings: list[str] = []
    for meeting in state.get("meetings", []):
        meeting_stage = meeting.get("stage")
        if (
            meeting.get("status") == "current"
            and meeting_stage in stages
            and stages.index(meeting_stage) >= rewind_index
        ):
            meeting["status"] = "superseded"
            meeting["superseded_at"] = now()
            meeting["superseded_reason"] = reason
            invalidated_meetings.append(str(meeting.get("id")))

    for gate, approval in state.get("human_approvals", {}).items():
        if (
            approval.get("status") == "current"
            and gate in stages
            and stages.index(gate) >= rewind_index
        ):
            approval["status"] = "superseded"
            approval["superseded_at"] = now()
            approval["superseded_reason"] = reason

    if "implementation" in stages and rewind_index <= stages.index("implementation"):
        state["source_revision"] = {}
    if "verification" in stages and rewind_index <= stages.index("verification"):
        state["criterion_verdicts"] = {}
        state["journey_validation"] = {}
    if "acceptance" in stages and rewind_index <= stages.index("acceptance"):
        state["core_outcomes"] = {}

    invalidated_artifacts: list[str] = []
    for name, produced_at in ARTIFACT_STAGE.items():
        if name in preserve_artifacts or produced_at not in stages:
            continue
        if stages.index(produced_at) >= rewind_index:
            artifact = state.get("artifacts", {}).get(name)
            if artifact and artifact.get("status") in {"ready", "not_applicable"}:
                artifact["status"] = "superseded"
                artifact["updated_at"] = now()
                invalidated_artifacts.append(name)
    return old_stage, invalidated_artifacts, invalidated_meetings


def stage_requirements(root: Path, state: dict[str, Any]) -> tuple[list[str], list[str]]:
    stage = state["workflow"]["current_stage"]
    missing: list[str] = []
    notes: list[str] = []

    for name in required_artifacts(state, stage):
        if not artifact_ready(root, state, name):
            missing.append(f"artifact:{name}")

    if stage == "scope_check":
        assessment = state.get("risk_assessment", {})
        artifact = state.get("artifacts", {}).get("risk_assessment", {})
        if not (
            assessment.get("status") == "current"
            and assessment.get("selected_mode") == state["workflow"]["mode"]
            and assessment.get("evidence_sha256") == artifact.get("evidence_sha256")
        ):
            missing.append("risk_assessment:mode_selection")

    if state["workflow"]["mode"] == "strict":
        if stage == "requirement_confirmation":
            goals_artifact = state.get("artifacts", {}).get("core_goals", {})
            goals = state.get("core_goals", {})
            if not goals or any(
                goal.get("evidence_sha256") != goals_artifact.get("evidence_sha256")
                for goal in goals.values()
            ):
                missing.append("core_goals:user_confirmed_baseline")
        if stage == "prd":
            prd = state.get("artifacts", {}).get("prd", {})
            criteria = state.get("acceptance_criteria", {})
            if not criteria or any(
                item.get("prd_sha256") != prd.get("evidence_sha256")
                for item in criteria.values()
            ):
                missing.append("acceptance_criteria:prd_baseline")
        if stage in {"verification", "acceptance", "delivery_confirmation"}:
            scope_paths = tuple(state.get("source_revision", {}).get("scope_paths", []))
            ignored_paths = tuple(state.get("source_revision", {}).get("ignored_paths", []))
            try:
                fingerprint = current_source_fingerprint(root, scope_paths, ignored_paths)
            except WorkflowError as exc:
                missing.append("source_revision:git_unavailable")
                notes.append(str(exc))
                fingerprint = {
                    "source_tree_sha256": "",
                    "dirty_paths": [],
                }
            source = state.get("source_revision", {})
            if not source or source.get("source_tree_sha256") != fingerprint["source_tree_sha256"]:
                missing.append("source_revision:stale_or_missing")
            if not test_execution_ready(root, source.get("test_execution", {})):
                missing.append("source_revision:test_execution")
            if fingerprint["dirty_paths"]:
                missing.append("source_revision:uncommitted_source")
            criteria = state.get("acceptance_criteria", {})
            verdicts = state.get("criterion_verdicts", {})
            for criterion_id in criteria:
                verdict = verdicts.get(criterion_id, {})
                if (
                    not fingerprint["source_tree_sha256"]
                    or not verdict_is_current(
                        root,
                        state,
                        verdict,
                        criterion_id,
                        fingerprint["source_tree_sha256"],
                    )
                ):
                    missing.append(f"criterion_verdict:{criterion_id}")
            journey = state.get("journey_validation", {})
            journey_profile = str(journey.get("profile", "web"))
            required_checks = JOURNEY_PROFILES.get(journey_profile, JOURNEY_CHECKS)
            if not (
                journey.get("source_tree_sha256") == fingerprint["source_tree_sha256"]
                and evidence_matches(
                    root,
                    str(journey.get("evidence", "")),
                    journey.get("evidence_sha256"),
                )
                and all(
                    journey.get("checks", {}).get(check) == "pass"
                    for check in required_checks
                )
            ):
                missing.append("journey_validation:final_user_journey")
        if stage == "acceptance":
            for goal_id in state.get("core_goals", {}):
                outcome = state.get("core_outcomes", {}).get(goal_id, {})
                if (
                    not fingerprint["source_tree_sha256"]
                    or not outcome_is_current(
                        root,
                        state,
                        outcome,
                        goal_id,
                        fingerprint["source_tree_sha256"],
                    )
                ):
                    missing.append(f"core_outcome:{goal_id}")

    if state["workflow"]["mode"] != "strict" and stage in {
        "acceptance",
        "delivery_confirmation",
    }:
        snapshot = state.get("verification_snapshot", {})
        try:
            current_workspace = workspace_binding(
                root,
                tuple(snapshot.get("ignored_paths", [])),
            )
        except SourcePolicyError as exc:
            missing.append("verification_snapshot:workspace_unavailable")
            notes.append(str(exc))
            current_workspace = {"source_tree_sha256": ""}
        if not snapshot:
            missing.append("verification_snapshot:missing")
        elif not test_execution_ready(root, snapshot.get("test_execution", {})):
            missing.append("verification_snapshot:test_execution")
        elif snapshot.get("source_tree_sha256") != current_workspace["source_tree_sha256"]:
            missing.append("verification_snapshot:source_changed_after_verification")
            notes.append(
                "Product files changed after the recorded verification report; "
                "return to implementation and rerun independent verification."
            )

    if stage in GATES:
        decisions = state.get("decisions", {}).get(stage, {})
        for role in required_gate_roles(state, stage):
            verdict = decisions.get(role, {}).get("verdict")
            if verdict != "approve" or not decision_is_current(root, decisions.get(role, {})):
                missing.append(f"approval:{stage}:{role}")
                if verdict == "reject":
                    notes.append(f"{role} rejected {stage}")
        if not gate_meeting_ready(root, state, stage):
            missing.append(f"meeting:{stage}")
        if human_approval_required(state, stage) and not human_approval_ready(root, state, stage):
            missing.append(f"human_approval:{stage}")

    escalation = state.get("escalation", {})
    if escalation.get("status") == "required":
        missing.append(f"escalation_required:{escalation.get('report_id', 'unknown')}")
        notes.append(
            f"mode {escalation.get('from_mode')} is below recommended "
            f"{escalation.get('recommended_mode')}"
        )
    if (
        escalation.get("status") == "accepted_risk"
        and str(escalation.get("acceptance_expires_on", "")) < now()[:10]
    ):
        missing.append(f"escalation_acceptance_expired:{escalation.get('report_id', 'unknown')}")
        notes.append("The accepted escalation risk must be reassessed or escalated.")

    blockers = open_blockers(state)
    if blockers:
        missing.extend(f"blocker:{item['id']}" for item in blockers)
    if stage == "acceptance":
        missing.extend(
            f"major:{item['id']}"
            for item in state.get("issues", [])
            if item.get("severity") == "major" and item.get("status") == "open"
        )
    return missing, notes


def scope_change_authorizes(
    root: Path, state: dict[str, Any], change_id: str, item_id: str
) -> bool:
    return any(
        change.get("id") == change_id
        and change.get("status") == "approved"
        and item_id in change.get("items", [])
        and evidence_matches(
            root, str(change.get("evidence", "")), change.get("evidence_sha256")
        )
        for change in state.get("scope_changes", [])
    )


def verdict_is_current(
    root: Path,
    state: dict[str, Any],
    verdict: dict[str, Any],
    criterion_id: str,
    source_hash: str,
) -> bool:
    if verdict.get("source_tree_sha256") != source_hash or not evidence_matches(
        root, str(verdict.get("evidence", "")), verdict.get("evidence_sha256")
    ):
        return False
    if verdict.get("verdict") == "pass":
        return True
    return verdict.get("verdict") == "not_applicable" and scope_change_authorizes(
        root, state, str(verdict.get("scope_change_id", "")), criterion_id
    )


def outcome_is_current(
    root: Path,
    state: dict[str, Any],
    outcome: dict[str, Any],
    goal_id: str,
    source_hash: str,
) -> bool:
    if outcome.get("source_tree_sha256") != source_hash or not evidence_matches(
        root, str(outcome.get("evidence", "")), outcome.get("evidence_sha256")
    ):
        return False
    if outcome.get("verdict") == "satisfied":
        return True
    return outcome.get("verdict") in {"not_applicable", "deferred"} and scope_change_authorizes(
        root, state, str(outcome.get("scope_change_id", "")), goal_id
    )


def current_source_fingerprint(
    root: Path,
    scope_paths: tuple[str, ...] = (),
    ignored_paths: tuple[str, ...] = (),
) -> dict[str, Any]:
    try:
        return source_binding(root, scope_paths, ignored_paths)
    except SourcePolicyError as exc:
        raise WorkflowError(str(exc)) from exc


def outstanding_issues(state: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        issue
        for issue in state.get("issues", [])
        if issue.get("status") in {"open", "accepted_risk", "deferred"}
    ]


def completed_artifacts(root: Path, state: dict[str, Any]) -> list[str]:
    return [name for name in ARTIFACTS if artifact_ready(root, state, name)]


def next_stage_name(state: dict[str, Any]) -> str | None:
    workflow = state["workflow"]
    stage = workflow["current_stage"]
    if stage == "completed":
        return None
    stages = workflow_stages(state)
    index = stages.index(stage)
    if index + 1 >= len(stages):
        return None
    return stages[index + 1]


def overview_payload(root: Path, state: dict[str, Any]) -> dict[str, Any]:
    workflow = state["workflow"]
    stage = workflow["current_stage"]
    if workflow["status"] == "paused":
        missing, notes = ["workflow:paused"], ["Resume the workflow before making changes."]
    else:
        missing, notes = stage_requirements(root, state)
    health_warnings: list[str] = []
    recorded_context = state.get("repository_context", {})
    current_context = repository_context(root)
    if (
        recorded_context.get("git_branch")
        and current_context.get("git_branch")
        and recorded_context["git_branch"] != current_context["git_branch"]
    ):
        health_warnings.append(
            f"Git branch changed from {recorded_context['git_branch']} to "
            f"{current_context['git_branch']}; confirm this workflow belongs on the current branch."
        )
    pointer = active_pointer(root)
    if workflow["status"] in {"active", "paused"} and not pointer.exists():
        health_warnings.append("Active workflow pointer is missing; use --id until it is restored.")
    next_stage = None if missing else next_stage_name(state)
    return {
        "workflow_id": workflow["id"],
        "title": workflow["title"],
        "mode": workflow["mode"],
        "status": workflow["status"],
        "stage": stage,
        "stage_label": STAGE_LABELS.get(stage, stage),
        "can_advance": workflow["status"] == "active" and not missing,
        "next_stage": next_stage,
        "next_stage_label": STAGE_LABELS.get(next_stage, next_stage) if next_stage else None,
        "next_action": (
            f"Review risk {state.get('escalation', {}).get('report_id')} and obtain explicit user approval to escalate from "
            f"{state.get('escalation', {}).get('from_mode')} to at least {state.get('escalation', {}).get('recommended_mode')}."
            if state.get("escalation", {}).get("status") == "required"
            else (
                f"Advance to {STAGE_LABELS.get(next_stage, next_stage)}."
                if next_stage and not missing
                else STAGE_GUIDANCE.get(stage, "Continue the current workflow stage.")
            )
        ),
        "missing": missing,
        "notes": notes,
        "completed_artifacts": completed_artifacts(root, state),
        "outstanding_issues": [
            {
                "id": issue.get("id"),
                "severity": issue.get("severity"),
                "status": issue.get("status"),
                "owner": issue.get("owner"),
                "summary": issue.get("summary"),
            }
            for issue in outstanding_issues(state)
        ],
        "meeting_notes": len(state.get("meetings", [])),
        "state_revision": state["revision"],
        "human_approval_gates": state.get("human_approval_policy", {}).get("required_gates", []),
        "risk_recommendation": state.get("risk_assessment", {}).get("recommended_mode"),
        "enabled_stages": list(workflow_stages(state)),
        "escalation": state.get("escalation", {"status": "none"}),
        "execution_policy": EXECUTION_POLICIES[workflow["mode"]],
        "health_warnings": health_warnings,
    }


def print_overview(payload: dict[str, Any]) -> None:
    print(f"Workflow: {payload['workflow_id']} — {payload['title']}")
    print(
        f"Stage: {payload['stage']} ({payload['stage_label']})  "
        f"Mode: {payload['mode']}  Status: {payload['status']}"
    )
    print(f"Can advance: {'yes' if payload['can_advance'] else 'no'}")
    print(f"Next action: {payload['next_action']}")
    if payload["completed_artifacts"]:
        print("Completed artifacts: " + ", ".join(payload["completed_artifacts"]))
    else:
        print("Completed artifacts: none")
    if payload["missing"]:
        print("Required now:")
        for item in payload["missing"]:
            print(f"- {item}")
    if payload["outstanding_issues"]:
        print("Open or carried issues:")
        for issue in payload["outstanding_issues"]:
            print(
                f"- {issue['id']} {issue['severity']} {issue['status']} "
                f"owner={issue['owner']}: {issue['summary']}"
            )
    else:
        print("Open or carried issues: none")
    if payload["health_warnings"]:
        print("Health warnings:")
        for warning in payload["health_warnings"]:
            print(f"- {warning}")
    print(f"Meeting notes: {payload['meeting_notes']}")
    if payload["risk_recommendation"]:
        print(f"Risk-recommended mode: {payload['risk_recommendation']}")
    print("Enabled stages: " + " -> ".join(payload["enabled_stages"]))
    policy = payload["execution_policy"]
    print(f"Cost policy: {policy['context']}; {policy['testing']}")
    if payload["escalation"].get("status") == "required":
        escalation = payload["escalation"]
        print(
            f"Escalation required: {escalation.get('from_mode')} -> "
            f"{escalation.get('recommended_mode')} ({escalation.get('report_id')})"
        )
    elif payload["escalation"].get("status") == "accepted_risk":
        escalation = payload["escalation"]
        print(
            "Escalation risk accepted with reduced assurance until "
            f"{escalation.get('acceptance_expires_on')} "
            f"({escalation.get('report_id')})"
        )
    gates = payload["human_approval_gates"]
    print("Human approval gates: " + (",".join(gates) if gates else "none"))


def save_state(path: Path, state: dict[str, Any]) -> None:
    expected_revision = state.get("revision", 0)
    if path.exists():
        on_disk = load_data(path)
        actual_revision = on_disk.get("revision", 0)
        if actual_revision != expected_revision:
            raise WorkflowError(
                f"Workflow state changed concurrently: expected revision "
                f"{expected_revision}, found {actual_revision}."
            )
        verify_state_checksum(on_disk, path, CURRENT_SCHEMA_VERSION)
        save_data(path.with_name("state.backup.yaml"), on_disk)
    state["schema_version"] = CURRENT_SCHEMA_VERSION
    state["revision"] = expected_revision + 1
    state["state_checksum"] = state_checksum(state)
    validate_state(state, path)
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


def require_artifact_content(name: str, path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    if name == "clarification_questions":
        for marker in ("question", "missing", "assumption", "acceptance"):
            if not contains_marker(text, marker):
                raise WorkflowError(
                    f"Clarification evidence must cover questions, missing details, "
                    f"assumptions, and acceptance criteria; missing: {marker}"
                )
    elif name == "requirement_confirmation":
        if not (
            contains_marker(text, "user")
            and (contains_marker(text, "confirmed") or contains_marker(text, "approve"))
        ):
            raise WorkflowError(
                "Requirement confirmation evidence must record explicit user confirmation."
            )
    elif name == "prototype":
        for marker in ("preview", "scope", "how to inspect"):
            if not contains_marker(text, marker):
                raise WorkflowError(f"Prototype evidence must identify: {marker}")
    elif name == "user_feedback":
        if not (
            contains_marker(text, "user")
            and contains_marker(text, "feedback")
            and (contains_marker(text, "approve") or contains_marker(text, "approved"))
        ):
            raise WorkflowError("User feedback evidence must record explicit user approval.")


def cmd_init(args: argparse.Namespace) -> None:
    root = repository_root(args.root)
    pointer = active_pointer(root)
    if pointer.exists() and not args.force:
        active = load_data(pointer).get("workflow_id", "unknown")
        raise WorkflowError(f"Workflow {active} is already active. Complete it or use --force.")

    workflow_id = args.id or workflow_id_from_title(args.title)
    validate_workflow_id(workflow_id)
    path = state_path(root, workflow_id)
    if path.exists() and not args.force:
        raise WorkflowError(f"Workflow already exists: {workflow_id}")

    docs_dir = root / "docs" / "requirements" / workflow_id
    docs_dir.mkdir(parents=True, exist_ok=True)
    request_path = docs_dir / "00-original-request.md"
    atomic_write_text(
        request_path,
        f"# Original request: {args.title}\n\n{args.request.strip()}\n",
    )
    timestamp = now()
    state: dict[str, Any] = {
        "schema_version": CURRENT_SCHEMA_VERSION,
        "revision": 0,
        "workflow": {
            "id": workflow_id,
            "title": args.title,
            "mode": args.mode,
            "requested_mode": args.mode,
            "flow_stages": list(FLOWS[args.mode]),
            "status": "active",
            "current_stage": FLOWS[args.mode][0],
            "created_at": timestamp,
            "updated_at": timestamp,
        },
        "artifacts": {
            "original_request": {
                "path": str(request_path.relative_to(root)),
                "status": "ready",
                "evidence_sha256": content_sha256(request_path),
                "updated_at": timestamp,
                "notes": "Captured during workflow initialization.",
            }
        },
        "issues": [],
        "decisions": {},
        "human_approval_policy": {
            "required_gates": list(dict.fromkeys(args.require_human_approval or []))
        },
        "human_approvals": {},
        "meetings": [],
        "risk_assessment": {"status": "pending"},
        "user_feedback_records": [],
        "delivery_confirmation_records": [],
        "risk_reports": [],
        "escalation": {"status": "none"},
        "core_goals": {},
        "scope_changes": [],
        "acceptance_criteria": {},
        "criterion_verdicts": {},
        "core_outcomes": {},
        "source_revision": {},
        "verification_snapshot": {},
        "journey_validation": {},
        "repository_context": repository_context(root),
        "history": [
            {"at": timestamp, "event": "initialized", "detail": f"Started {args.mode} workflow"}
        ],
    }
    if args.force and path.exists():
        state["revision"] = int(load_data(path).get("revision", 0))
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


def cmd_start(args: argparse.Namespace) -> None:
    if not getattr(args, "title", None):
        args.title = title_from_request(args.request)
    cmd_init(args)
    root = repository_root(args.root)
    _, state = load_state(root, getattr(args, "id", None))
    print()
    print("Overview:")
    print_overview(overview_payload(root, state))


def cmd_assess_risk(args: argparse.Namespace) -> None:
    invoke_risk_command("cmd_assess_risk", sys.modules[__name__], args)


def cmd_report_risk(args: argparse.Namespace) -> None:
    invoke_risk_command("cmd_report_risk", sys.modules[__name__], args)


def cmd_resolve_risk(args: argparse.Namespace) -> None:
    invoke_risk_command("cmd_resolve_risk", sys.modules[__name__], args)


def cmd_withdraw_risk(args: argparse.Namespace) -> None:
    invoke_risk_command("cmd_withdraw_risk", sys.modules[__name__], args)


def cmd_accept_escalation_risk(args: argparse.Namespace) -> None:
    invoke_risk_command("cmd_accept_escalation_risk", sys.modules[__name__], args)


def cmd_escalate_mode(args: argparse.Namespace) -> None:
    invoke_risk_command("cmd_escalate_mode", sys.modules[__name__], args)


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
    print(f"Artifacts satisfied: {sum(artifact_ready(root, state, name) for name in ARTIFACTS)}")
    print(f"Meeting notes: {len(state.get('meetings', []))}")
    print(f"Open blockers: {len(blockers)}")
    print(f"State revision: {state['revision']}")
    required_human = state.get("human_approval_policy", {}).get("required_gates", [])
    print("Human approval gates: " + (",".join(required_human) if required_human else "none"))
    missing, notes = stage_requirements(root, state)
    print("Can advance: " + ("yes" if not missing and workflow["status"] == "active" else "no"))
    for item in missing:
        print(f"- {item}")
    for item in notes:
        print(f"- note:{item}")


def cmd_audit_state(args: argparse.Namespace) -> None:
    root = repository_root(args.root)
    path = state_path(root, args.id)
    parse_error = ""
    try:
        raw = load_data(path)
    except WorkflowError as exc:
        raw = {}
        parse_error = str(exc)
    expected = raw.get("state_checksum")
    actual = state_checksum(raw) if raw else None
    checksum_valid = (
        bool(raw)
        and (raw.get("schema_version") != CURRENT_SCHEMA_VERSION or expected == actual)
    )
    backup_path = path.with_name("state.backup.yaml")
    backup_valid = False
    backup_revision: int | None = None
    if backup_path.exists():
        try:
            backup = load_data(backup_path)
            verify_state_checksum(backup, backup_path, CURRENT_SCHEMA_VERSION)
            validate_state(backup, backup_path)
            backup_valid = True
            backup_revision = int(backup.get("revision", 0))
        except (WorkflowError, ValueError, TypeError):
            backup_valid = False
    payload = {
        "path": str(path.relative_to(root)),
        "parse_error": parse_error or None,
        "schema_version": raw.get("schema_version"),
        "revision": raw.get("revision"),
        "checksum_valid": checksum_valid,
        "expected_checksum": expected,
        "actual_checksum": actual,
        "backup_path": str(backup_path.relative_to(root)),
        "backup_exists": backup_path.exists(),
        "backup_valid": backup_valid,
        "backup_revision": backup_revision,
        "repair_available": backup_valid,
    }
    if args.json:
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        return
    print(f"State: {payload['path']}")
    if parse_error:
        print(f"Parse error: {parse_error}")
    print(f"Checksum: {'valid' if checksum_valid else 'INVALID'}")
    print(
        "Backup: "
        + (
            f"valid revision {backup_revision}"
            if backup_valid
            else ("invalid" if backup_path.exists() else "not available yet")
        )
    )
    if not checksum_valid and backup_valid:
        print("Recovery: run repair-state --from-backup --confirm RESTORE")


def cmd_repair_state(args: argparse.Namespace) -> None:
    if args.confirm != "RESTORE":
        raise WorkflowError("State repair requires --confirm RESTORE.")
    root = repository_root(args.root)
    path = state_path(root, args.id)
    backup_path = path.with_name("state.backup.yaml")
    backup = load_data(backup_path)
    verify_state_checksum(backup, backup_path, CURRENT_SCHEMA_VERSION)
    validate_state(backup, backup_path)
    try:
        current_revision = int(load_data(path).get("revision", 0))
    except (WorkflowError, ValueError, TypeError):
        current_revision = int(backup.get("revision", 0))
    restored = json.loads(json.dumps(backup))
    restored["revision"] = max(current_revision, int(backup.get("revision", 0))) + 1
    add_history(restored, "state_restored", f"Restored from {backup_path.name}")
    restored["state_checksum"] = state_checksum(restored)
    validate_state(restored, path)
    save_data(path, restored)
    print(f"Restored workflow state from {backup_path.name}")


def cmd_overview(args: argparse.Namespace) -> None:
    root = repository_root(args.root)
    _, state = load_state(root, args.id)
    payload = overview_payload(root, state)
    if args.json:
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        return
    print_overview(payload)


def cmd_pause(args: argparse.Namespace) -> None:
    root = repository_root(args.root)
    path, state = load_state(root, args.id)
    workflow = state["workflow"]
    if workflow["status"] != "active":
        raise WorkflowError(f"Workflow status is {workflow['status']}, not active.")
    workflow["status"] = "paused"
    workflow["paused_at"] = now()
    workflow["pause_reason"] = args.reason.strip()
    add_history(state, "paused", args.reason.strip())
    save_state(path, state)
    print(f"Paused workflow {workflow['id']} at {workflow['current_stage']}")


def cmd_resume(args: argparse.Namespace) -> None:
    root = repository_root(args.root)
    path, state = load_state(root, args.id)
    workflow = state["workflow"]
    if workflow["status"] != "paused":
        raise WorkflowError(f"Workflow status is {workflow['status']}, not paused.")
    workflow["status"] = "active"
    workflow.pop("paused_at", None)
    workflow.pop("pause_reason", None)
    add_history(state, "resumed", f"Resumed at {workflow['current_stage']}")
    save_state(path, state)
    print(f"Resumed workflow {workflow['id']} at {workflow['current_stage']}")


def cmd_next(args: argparse.Namespace) -> None:
    root = repository_root(args.root)
    _, state = load_state(root, args.id)
    workflow = state["workflow"]
    stage = workflow["current_stage"]
    if stage == "completed":
        print("Workflow is complete. No next action.")
        return
    missing, notes = stage_requirements(root, state)
    print(f"Current stage: {stage}")
    if missing:
        print("Required before advancing:")
        for item in missing:
            print(f"- {item}")
    else:
        stages = workflow_stages(state)
        next_stage = stages[stages.index(stage) + 1]
        print(f"Ready to advance to: {next_stage}")
    for item in notes:
        print(f"Note: {item}")


def cmd_record_core_goals(args: argparse.Namespace) -> None:
    invoke_assurance_command("cmd_record_core_goals", sys.modules[__name__], args)


def cmd_register_acceptance_criteria(args: argparse.Namespace) -> None:
    invoke_assurance_command("cmd_register_acceptance_criteria", sys.modules[__name__], args)


def cmd_approve_scope_change(args: argparse.Namespace) -> None:
    invoke_assurance_command("cmd_approve_scope_change", sys.modules[__name__], args)


def cmd_submit_verification(args: argparse.Namespace) -> None:
    invoke_assurance_command("cmd_submit_verification", sys.modules[__name__], args)


def cmd_record_source_revision(args: argparse.Namespace) -> None:
    invoke_assurance_command("cmd_record_source_revision", sys.modules[__name__], args)


def cmd_record_criterion_verdict(args: argparse.Namespace) -> None:
    invoke_assurance_command("cmd_record_criterion_verdict", sys.modules[__name__], args)


def cmd_record_user_journey(args: argparse.Namespace) -> None:
    invoke_assurance_command("cmd_record_user_journey", sys.modules[__name__], args)


def cmd_record_core_outcome(args: argparse.Namespace) -> None:
    invoke_assurance_command("cmd_record_core_outcome", sys.modules[__name__], args)


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
        require_artifact_content(args.name, absolute)
    for other_name, other in state.get("artifacts", {}).items():
        if other_name != args.name and other.get("path") == str(relative) and other.get("status") != "superseded":
            raise WorkflowError(f"Artifact path is already used by {other_name}: {relative}")
    previous = state.get("artifacts", {}).get(args.name, {})
    next_hash = content_sha256(absolute) if args.status == "ready" else None
    verification_binding: dict[str, Any] | None = None
    verification_execution: dict[str, Any] | None = None
    if (
        args.name == "verification_report"
        and args.status == "ready"
        and state["workflow"]["mode"] != "strict"
    ):
        if state["workflow"]["current_stage"] != "verification":
            raise WorkflowError("A verification report can only be recorded during verification.")
        if not (args.test_command or "").strip():
            raise WorkflowError(
                "A non-strict verification report requires --test-command so passing evidence "
                "is backed by an actual deterministic run."
            )
        prior_snapshot = state.get("verification_snapshot", {})
        ignored_paths = tuple(prior_snapshot.get("ignored_paths", []))
        if not ignored_paths:
            original_request = state.get("artifacts", {}).get("original_request", {}).get("path", "")
            if original_request:
                ignored_paths = (Path(str(original_request)).parent.as_posix(),)
        try:
            before_execution = workspace_binding(root, ignored_paths)
        except SourcePolicyError as exc:
            raise WorkflowError(str(exc)) from exc
        verification_execution = execute_verification_commands(
            root,
            state,
            tuple(
                (label, command)
                for label, command in (
                    ("build_or_smoke", args.build_command or ""),
                    ("test", args.test_command or ""),
                )
                if command.strip()
            ),
            args.command_timeout,
        )
        try:
            verification_binding = workspace_binding(root, ignored_paths)
        except SourcePolicyError as exc:
            raise WorkflowError(str(exc)) from exc
        if before_execution["source_tree_sha256"] != verification_binding["source_tree_sha256"]:
            raise WorkflowError(
                "Verification commands changed product files. Exclude genuine generated output "
                "through repository ignore rules, or restore source and rerun."
            )
    changed = bool(previous) and (
        previous.get("path") != str(relative)
        or previous.get("status") != args.status
        or previous.get("evidence_sha256") != next_hash
        or previous.get("notes", "") != (args.notes or "")
    )
    if changed and args.name in {"requirement_confirmation", "core_goals"}:
        state["core_goals"] = {}
        state["core_outcomes"] = {}
        state["scope_changes"] = []
    if changed and args.name == "prd":
        state["acceptance_criteria"] = {}
        state["criterion_verdicts"] = {}
    if changed and args.name in {"implementation", "verification_report", "journey_report"}:
        state["source_revision"] = {}
        state["criterion_verdicts"] = {}
        state["core_outcomes"] = {}
        state["journey_validation"] = {}
    state.setdefault("artifacts", {})[args.name] = {
        "path": str(relative),
        "status": args.status,
        "evidence_sha256": next_hash,
        "updated_at": now(),
        "notes": args.notes or "",
    }
    if verification_binding is not None:
        state["verification_snapshot"] = {
            **verification_binding,
            "verification_evidence_sha256": next_hash,
            "test_execution": verification_execution,
            "recorded_at": now(),
        }
    invalidated: list[str] = []
    invalidated_meetings: list[str] = []
    automatic_rewind = ""
    if changed and args.name in ARTIFACT_CHANGE_STAGE:
        affected_stage = ARTIFACT_CHANGE_STAGE[args.name]
        stages = workflow_stages(state)
        if stages.index(state["workflow"]["current_stage"]) >= stages.index(affected_stage):
            old_stage, invalidated_artifacts, invalidated_meetings = rewind_workflow(
                state,
                affected_stage,
                f"Artifact {args.name} changed",
                preserve_artifacts={args.name},
            )
            automatic_rewind = f"{old_stage}->{affected_stage}"
            if invalidated_artifacts:
                add_history(state, "artifacts_invalidated", ",".join(invalidated_artifacts))
    else:
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
    if automatic_rewind:
        add_history(state, "change_control_required", f"{args.name}:{automatic_rewind}")
    if invalidated:
        add_history(state, "decisions_invalidated", f"{args.name}:{','.join(invalidated)}")
    if invalidated_meetings:
        add_history(state, "meetings_invalidated", ",".join(invalidated_meetings))
    save_state(path, state)
    print(f"Recorded artifact {args.name} ({args.status}): {relative}")
    if automatic_rewind:
        print(f"Change detected; workflow automatically rewound: {automatic_rewind}")


def cmd_record_user_feedback(args: argparse.Namespace) -> None:
    invoke_delivery_command("cmd_record_user_feedback", sys.modules[__name__], args)


def cmd_record_delivery_confirmation(args: argparse.Namespace) -> None:
    invoke_delivery_command("cmd_record_delivery_confirmation", sys.modules[__name__], args)


def next_meeting_id(state: dict[str, Any]) -> str:
    numbers = []
    for meeting in state.get("meetings", []):
        match = re.fullmatch(r"MTG-(\d+)", str(meeting.get("id", "")))
        if match:
            numbers.append(int(match.group(1)))
    return f"MTG-{max(numbers, default=0) + 1:03d}"


def cmd_add_issue(args: argparse.Namespace) -> None:
    invoke_delivery_command("cmd_add_issue", sys.modules[__name__], args)


def cmd_resolve_issue(args: argparse.Namespace) -> None:
    invoke_delivery_command("cmd_resolve_issue", sys.modules[__name__], args)


def cmd_disposition_issue(args: argparse.Namespace) -> None:
    invoke_delivery_command("cmd_disposition_issue", sys.modules[__name__], args)


def cmd_decide(args: argparse.Namespace) -> None:
    invoke_review_command("cmd_decide", sys.modules[__name__], args)


def cmd_submit_gate_review(args: argparse.Namespace) -> None:
    invoke_review_command("cmd_submit_gate_review", sys.modules[__name__], args)


def cmd_record_meeting(args: argparse.Namespace) -> None:
    invoke_review_command("cmd_record_meeting", sys.modules[__name__], args)


def cmd_record_human_approval(args: argparse.Namespace) -> None:
    invoke_review_command("cmd_record_human_approval", sys.modules[__name__], args)


def cmd_advance(args: argparse.Namespace) -> None:
    root = repository_root(args.root)
    path, state = load_state(root, args.id)
    workflow = state["workflow"]
    if workflow["status"] != "active":
        raise WorkflowError(f"Workflow status is {workflow['status']}, not active.")
    stage = workflow["current_stage"]
    if stage == "completed":
        raise WorkflowError("Workflow is already complete.")
    missing, notes = stage_requirements(root, state)
    if missing:
        detail = ", ".join(missing)
        if notes:
            detail += "; " + "; ".join(notes)
        raise WorkflowError(f"Gate blocked: {detail}")
    stages = workflow_stages(state)
    new_stage = stages[stages.index(stage) + 1]
    workflow["current_stage"] = new_stage
    if new_stage == "completed":
        workflow["status"] = "completed"
    add_history(state, "advanced", f"{stage}->{new_stage}")
    save_state(path, state)
    if new_stage == "completed":
        pointer = active_pointer(root)
        if pointer.exists():
            active = load_data(pointer)
            if active.get("workflow_id") == workflow["id"]:
                pointer.unlink()
    print(f"Advanced {stage} -> {new_stage}")


def cmd_reopen(args: argparse.Namespace) -> None:
    root = repository_root(args.root)
    path, state = load_state(root, args.id)
    old_stage, invalidated_artifacts, invalidated_meetings = rewind_workflow(
        state, args.stage, f"Workflow reopened at {args.stage}"
    )
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
    return create_cli_parser(sys.modules[__name__])


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    try:
        if args.command in MUTATING_COMMANDS:
            root = repository_root(args.root)
            with workflow_lock(root):
                if args.command not in {"init", "start", "repair-state", "resume"}:
                    _, current = load_state(root, args.id)
                    if current["workflow"]["status"] == "paused":
                        raise WorkflowError(
                            "Workflow is paused. Resume it before recording or changing delivery state."
                        )
                args.func(args)
        else:
            args.func(args)
        return 0
    except WorkflowError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
