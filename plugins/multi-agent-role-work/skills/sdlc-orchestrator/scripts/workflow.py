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
from source_policy import SourcePolicyError, source_binding
from state_store import (
    WorkflowError,
    atomic_write_text,
    load_data,
    save_data,
    state_checksum,
    verify_state_checksum,
    workflow_lock,
)


CURRENT_SCHEMA_VERSION = 8
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
    if version in {1, 2, 3, 4, 5, 6, 7}:
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
    state.setdefault("journey_validation", {})
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
    if workflow.get("status") not in {"active", "completed"}:
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
        "journey_validation",
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
        if stage in {"verification", "acceptance"}:
            scope_paths = tuple(state.get("source_revision", {}).get("scope_paths", []))
            try:
                fingerprint = current_source_fingerprint(root, scope_paths)
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
    root: Path, scope_paths: tuple[str, ...] = ()
) -> dict[str, Any]:
    try:
        return source_binding(root, scope_paths)
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
    missing, notes = stage_requirements(root, state)
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
    print(f"Meeting notes: {payload['meeting_notes']}")
    if payload["risk_recommendation"]:
        print(f"Risk-recommended mode: {payload['risk_recommendation']}")
    print("Enabled stages: " + " -> ".join(payload["enabled_stages"]))
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
        "journey_validation": {},
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


def gate_choice(value: str, default: bool) -> bool:
    if value == "auto":
        return default
    return value == "yes"


def markdown_bullets(items: list[str], empty: str) -> str:
    values = [item.strip() for item in items if item.strip()]
    if not values:
        return f"- {empty}"
    return "\n".join(f"- {item}" for item in values)


def cmd_assess_risk(args: argparse.Namespace) -> None:
    root = repository_root(args.root)
    path, state = load_state(root, args.id)
    workflow = state["workflow"]
    if workflow["current_stage"] != "scope_check":
        raise WorkflowError("Risk assessment can only be recorded during scope_check.")
    if state.get("escalation", {}).get("status") == "required":
        raise WorkflowError(
            "Resolve the pending escalation with escalate-mode before refreshing scope_check."
        )

    reported_flags = [
        str(flag)
        for report in state.get("risk_reports", [])
        if report.get("status") not in CLOSED_RISK_STATUSES
        for flag in report.get("flags", [])
    ]
    flags = list(dict.fromkeys(list(args.risk or []) + reported_flags))
    checked_areas = list(dict.fromkeys(args.checked_area or []))
    gaps = list(dict.fromkeys(args.gap or []))
    reasons = list(dict.fromkeys(args.reason or []))
    missing_areas = [area for area in REQUIREMENT_AREAS if area not in checked_areas]
    if missing_areas:
        raise WorkflowError(
            "Requirement-gap analysis is incomplete; unchecked areas: "
            + ",".join(missing_areas)
        )
    recommended = recommended_mode_for(flags)
    if gaps and recommended == "micro":
        recommended = "quick"

    selected = args.selected_mode
    requested = workflow.get("requested_mode", workflow.get("mode", "auto"))
    floor = recommended
    if requested in MODE_RANK and MODE_RANK[requested] > MODE_RANK[floor]:
        floor = str(requested)
    if MODE_RANK[selected] < MODE_RANK[floor]:
        raise WorkflowError(
            f"Selected mode {selected} is below the safe minimum {floor}; "
            f"risks recommend {recommended} and the requested mode was {requested}."
        )

    clarification = gate_choice(args.needs_clarification, bool(gaps))
    confirmation = gate_choice(args.needs_confirmation, clarification)
    preview = gate_choice(
        args.needs_preview,
        any(flag in {"user_visible", "subjective_judgment"} for flag in flags),
    )
    if clarification and not confirmation:
        raise WorkflowError("Requirement confirmation is required when clarification changes scope.")
    if selected == "micro" and (clarification or confirmation or preview):
        raise WorkflowError("Micro mode cannot carry clarification, confirmation, or preview gates.")
    if selected in {"standard", "strict"}:
        clarification = confirmation = preview = True
    policy = {
        "clarification": clarification,
        "requirement_confirmation": confirmation,
        "preview": preview,
    }
    stages = flow_for(selected, policy)
    if selected == "strict":
        required_gates = state.setdefault("human_approval_policy", {}).setdefault(
            "required_gates", []
        )
        for gate in ("readiness_review", "acceptance"):
            if gate not in required_gates:
                required_gates.append(gate)
    configured_human = state.get("human_approval_policy", {}).get("required_gates", [])
    unavailable = [gate for gate in configured_human if gate not in stages]
    if unavailable:
        raise WorkflowError(
            "Selected flow omits configured human approval gates: " + ",".join(unavailable)
        )

    assessment_path, relative = repository_evidence_path(
        root, args.evidence, minimum_chars=MIN_DOCUMENT_CHARS
    )
    require_markdown_structure(assessment_path)
    assessment_text = assessment_path.read_text(encoding="utf-8")
    for marker in ("task baseline", "requirement gaps", "risk flags", "workflow decision"):
        if not contains_marker(assessment_text, marker):
            raise WorkflowError(f"Risk assessment evidence must identify: {marker}")
    evidence_hash = content_sha256(assessment_path)
    state.setdefault("artifacts", {})["risk_assessment"] = {
        "path": str(relative),
        "status": "ready",
        "evidence_sha256": evidence_hash,
        "updated_at": now(),
        "notes": "Registered from an independently authored scope and risk assessment.",
    }
    state["risk_assessment"] = {
        "status": "current",
        "flags": flags,
        "checked_areas": checked_areas,
        "gaps": gaps,
        "baseline": {
            "scope": args.scope.strip(),
            "out_of_scope": args.out_of_scope.strip(),
            "acceptance": args.acceptance.strip(),
            "verification": args.verification.strip(),
        },
        "recommended_mode": recommended,
        "selected_mode": selected,
        "gate_policy": policy,
        "reasons": reasons,
        "evidence": str(relative),
        "evidence_sha256": evidence_hash,
        "at": now(),
    }
    old_mode = workflow["mode"]
    workflow["mode"] = selected
    workflow["flow_stages"] = list(stages)
    add_history(state, "risk_assessed", f"recommended={recommended}:selected={selected}")
    if old_mode != selected:
        add_history(state, "mode_selected", f"{old_mode}->{selected}")
    save_state(path, state)
    print(f"Risk assessment registered: {relative}")
    print(f"Recommended mode: {recommended}")
    print(f"Selected mode: {selected}")
    print("Enabled conditional gates: " + ",".join(name for name, enabled in policy.items() if enabled) if any(policy.values()) else "Enabled conditional gates: none")


def next_risk_report_id(state: dict[str, Any]) -> str:
    numbers = []
    for report in state.get("risk_reports", []):
        match = re.fullmatch(r"RSK-(\d+)", str(report.get("id", "")))
        if match:
            numbers.append(int(match.group(1)))
    return f"RSK-{max(numbers, default=0) + 1:03d}"


def cmd_report_risk(args: argparse.Namespace) -> None:
    root = repository_root(args.root)
    path, state = load_state(root, args.id)
    workflow = state["workflow"]
    if workflow["status"] != "active" or workflow["mode"] == "auto":
        raise WorkflowError("Report discovered risk only after the initial scope assessment.")
    flags = list(dict.fromkeys(args.risk or []))
    if not flags:
        raise WorkflowError("At least one --risk flag is required.")
    evidence_path, relative = repository_evidence_path(
        root, args.evidence, minimum_chars=MIN_DOCUMENT_CHARS
    )
    require_markdown_structure(evidence_path)
    evidence_hash = content_sha256(evidence_path)
    for report in state.get("risk_reports", []):
        if report.get("evidence_sha256") == evidence_hash:
            raise WorkflowError(f"Risk evidence is already used by {report.get('id')}.")

    report_id = next_risk_report_id(state)
    report = {
        "id": report_id,
        "source": args.source,
        "summary": args.summary.strip(),
        "flags": flags,
        "status": "recorded",
        "recommended_mode": recommended_mode_for(
            list(dict.fromkeys(combined_risk_flags(state) + flags))
        ),
        "evidence": str(relative),
        "evidence_sha256": evidence_hash,
        "at": now(),
    }
    state.setdefault("risk_reports", []).append(report)
    add_history(state, "risk_reported", f"{report_id}:{args.source}:{','.join(flags)}")
    requires_escalation = refresh_escalation(
        state,
        summary=args.summary.strip(),
        detected_by=args.source,
        timestamp=now,
    )
    if requires_escalation:
        report["status"] = "requires_escalation"
        add_history(
            state,
            "escalation_required",
            f"{workflow['mode']}->{state['escalation']['recommended_mode']}:{report_id}",
        )
    save_state(path, state)
    print(f"Recorded risk {report_id}: {relative}")
    if requires_escalation:
        print(
            f"Escalation required: {workflow['mode']} -> at least "
            f"{state['escalation']['recommended_mode']}"
        )
        print("Workflow advancement is blocked until explicit user approval is recorded.")
    else:
        print(f"Current mode {workflow['mode']} remains sufficient.")


def risk_report_by_id(state: dict[str, Any], report_id: str) -> dict[str, Any]:
    for report in state.get("risk_reports", []):
        if report.get("id") == report_id:
            return report
    raise WorkflowError(f"Unknown risk report: {report_id}")


def validate_risk_disposition_evidence(
    root: Path,
    state: dict[str, Any],
    report: dict[str, Any],
    *,
    evidence: str,
    disposition: str,
    actor: str,
) -> tuple[str, str]:
    evidence_path, relative = repository_evidence_path(
        root, evidence, minimum_chars=MIN_DOCUMENT_CHARS
    )
    require_markdown_structure(evidence_path)
    evidence_text = evidence_path.read_text(encoding="utf-8")
    for marker in (str(report["id"]), disposition, actor):
        if not contains_marker(evidence_text, marker):
            raise WorkflowError(f"Risk disposition evidence must identify: {marker}")
    evidence_hash = content_sha256(evidence_path)
    if evidence_hash == report.get("evidence_sha256"):
        raise WorkflowError("Risk disposition requires evidence distinct from the risk report.")
    for other in state.get("risk_reports", []):
        if other.get("disposition_evidence_sha256") == evidence_hash:
            raise WorkflowError("Risk disposition evidence is already used by another report.")
    return str(relative), evidence_hash


def cmd_resolve_risk(args: argparse.Namespace) -> None:
    root = repository_root(args.root)
    path, state = load_state(root, args.id)
    report = risk_report_by_id(state, args.risk_id)
    if report.get("status") in {"resolved", "withdrawn"}:
        raise WorkflowError(f"Risk report is already closed: {args.risk_id}")
    if args.resolved_by == args.verified_by:
        raise WorkflowError("Risk resolution requires a distinct resolver and verifier.")
    relative, evidence_hash = validate_risk_disposition_evidence(
        root,
        state,
        report,
        evidence=args.evidence,
        disposition="resolved",
        actor=args.resolved_by,
    )
    evidence_text = (root / relative).read_text(encoding="utf-8")
    if not contains_marker(evidence_text, args.verified_by):
        raise WorkflowError(
            f"Risk resolution evidence must identify verifier: {args.verified_by}"
        )
    report.update(
        {
            "status": "resolved",
            "resolution": args.resolution.strip(),
            "resolved_by": args.resolved_by,
            "verified_by": args.verified_by,
            "disposition_evidence": relative,
            "disposition_evidence_sha256": evidence_hash,
            "resolved_at": now(),
        }
    )
    still_required = refresh_escalation(
        state,
        summary=f"{args.risk_id} resolved: {args.resolution.strip()}",
        detected_by=args.verified_by,
        timestamp=now,
    )
    add_history(state, "risk_resolved", f"{args.risk_id}:{args.resolved_by}:{args.verified_by}")
    save_state(path, state)
    print(f"Resolved risk {args.risk_id}; independently verified by {args.verified_by}")
    print("Escalation remains required." if still_required else "No escalation blocker remains.")


def cmd_withdraw_risk(args: argparse.Namespace) -> None:
    root = repository_root(args.root)
    path, state = load_state(root, args.id)
    report = risk_report_by_id(state, args.risk_id)
    if report.get("status") in {"resolved", "withdrawn"}:
        raise WorkflowError(f"Risk report is already closed: {args.risk_id}")
    if args.withdrawn_by not in {report.get("source"), "user"}:
        raise WorkflowError("Only the original reporter or the user may withdraw a risk.")
    relative, evidence_hash = validate_risk_disposition_evidence(
        root,
        state,
        report,
        evidence=args.evidence,
        disposition="withdrawn",
        actor=args.withdrawn_by,
    )
    report.update(
        {
            "status": "withdrawn",
            "withdrawal_reason": args.reason.strip(),
            "withdrawn_by": args.withdrawn_by,
            "disposition_evidence": relative,
            "disposition_evidence_sha256": evidence_hash,
            "withdrawn_at": now(),
        }
    )
    still_required = refresh_escalation(
        state,
        summary=f"{args.risk_id} withdrawn: {args.reason.strip()}",
        detected_by=args.withdrawn_by,
        timestamp=now,
    )
    add_history(state, "risk_withdrawn", f"{args.risk_id}:{args.withdrawn_by}")
    save_state(path, state)
    print(f"Withdrew risk {args.risk_id}")
    print("Escalation remains required." if still_required else "No escalation blocker remains.")


def cmd_accept_escalation_risk(args: argparse.Namespace) -> None:
    root = repository_root(args.root)
    path, state = load_state(root, args.id)
    escalation = state.get("escalation", {})
    if escalation.get("status") != "required":
        raise WorkflowError("No mode escalation is currently required.")
    flags = set(escalation.get("flags", []))
    forbidden = sorted(flags & NON_WAIVABLE_ESCALATION_FLAGS)
    if forbidden:
        raise WorkflowError(
            "These escalation risks cannot be accepted without upgrading mode: "
            + ",".join(forbidden)
        )
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", args.expires_on):
        raise WorkflowError("Expiry date must use YYYY-MM-DD.")
    evidence_path, relative = repository_evidence_path(
        root, args.evidence, minimum_chars=MIN_DOCUMENT_CHARS
    )
    require_markdown_structure(evidence_path)
    evidence_text = evidence_path.read_text(encoding="utf-8")
    for marker in ("accepted_risk", args.approved_by, str(escalation.get("report_id"))):
        if not contains_marker(evidence_text, marker):
            raise WorkflowError(f"Escalation risk acceptance evidence must identify: {marker}")
    evidence_hash = content_sha256(evidence_path)
    reports_by_id = {report.get("id"): report for report in state.get("risk_reports", [])}
    reserved_hashes = {
        reports_by_id[report_id].get("evidence_sha256")
        for report_id in escalation.get("report_ids", [])
        if report_id in reports_by_id
    }
    if evidence_hash in reserved_hashes:
        raise WorkflowError("Escalation risk acceptance requires distinct evidence.")
    for report_id in escalation.get("report_ids", []):
        report = reports_by_id.get(report_id)
        if report is None:
            continue
        report.update(
            {
                "status": "accepted_risk",
                "accepted_by": args.approved_by.strip(),
                "acceptance_reason": args.reason.strip(),
                "acceptance_expires_on": args.expires_on,
                "disposition_evidence": str(relative),
                "disposition_evidence_sha256": evidence_hash,
                "accepted_at": now(),
            }
        )
    state["escalation"] = {
        **escalation,
        "status": "accepted_risk",
        "approved_by": args.approved_by.strip(),
        "acceptance_reason": args.reason.strip(),
        "acceptance_expires_on": args.expires_on,
        "acceptance_evidence": str(relative),
        "acceptance_evidence_sha256": evidence_hash,
        "assurance": "reduced",
        "resolved_at": now(),
    }
    add_history(
        state,
        "escalation_risk_accepted",
        f"{escalation.get('report_id')}:{args.approved_by}:{args.expires_on}",
    )
    save_state(path, state)
    print(
        "Accepted escalation risk without changing mode; assurance is reduced until "
        f"{args.expires_on}."
    )


def cmd_escalate_mode(args: argparse.Namespace) -> None:
    root = repository_root(args.root)
    path, state = load_state(root, args.id)
    escalation = state.get("escalation", {})
    if escalation.get("status") != "required":
        raise WorkflowError("No mode escalation is currently required.")
    workflow = state["workflow"]
    target = args.to_mode
    recommended = str(escalation.get("recommended_mode"))
    if MODE_RANK[target] < MODE_RANK[recommended]:
        raise WorkflowError(
            f"Selected escalation target {target} is below recommended mode {recommended}."
        )
    if MODE_RANK[target] <= MODE_RANK[workflow["mode"]]:
        raise WorkflowError("Escalation target must be higher than the current mode.")

    reports_by_id = {report.get("id"): report for report in state.get("risk_reports", [])}
    for report_id in escalation.get("report_ids", []):
        report = reports_by_id.get(report_id, {})
        if not evidence_matches(
            root, str(report.get("evidence", "")), report.get("evidence_sha256")
        ):
            raise WorkflowError(f"Escalation risk evidence is stale: {report_id}")
    approval_path, approval_relative = repository_evidence_path(
        root, args.evidence, minimum_chars=MIN_DOCUMENT_CHARS
    )
    require_markdown_structure(approval_path)
    approval_hash = content_sha256(approval_path)
    if approval_hash in {
        reports_by_id[report_id].get("evidence_sha256")
        for report_id in escalation.get("report_ids", [])
        if report_id in reports_by_id
    }:
        raise WorkflowError("Escalation approval requires distinct evidence.")

    flags = combined_risk_flags(state)
    previous_policy = state.get("risk_assessment", {}).get("gate_policy", {})
    policy = {
        "clarification": bool(previous_policy.get("clarification")),
        "requirement_confirmation": bool(previous_policy.get("requirement_confirmation")),
        "preview": bool(previous_policy.get("preview"))
        or any(flag in {"user_visible", "subjective_judgment"} for flag in flags),
    }
    if policy["clarification"]:
        policy["requirement_confirmation"] = True
    if target in {"standard", "strict"}:
        policy = {
            "clarification": True,
            "requirement_confirmation": True,
            "preview": True,
        }
    old_mode = workflow["mode"]
    old_stage = workflow["current_stage"]
    workflow["mode"] = target
    workflow["flow_stages"] = list(flow_for(target, policy))
    _, invalidated_artifacts, invalidated_meetings = rewind_workflow(
        state,
        "scope_check",
        f"Mode escalation approved for {','.join(escalation.get('report_ids', []))}",
    )
    state.setdefault("risk_assessment", {})["status"] = "superseded"
    if target == "strict":
        required_gates = state.setdefault("human_approval_policy", {}).setdefault(
            "required_gates", []
        )
        for gate in ("readiness_review", "acceptance"):
            if gate not in required_gates:
                required_gates.append(gate)
    for report_id in escalation.get("report_ids", []):
        if report_id in reports_by_id:
            reports_by_id[report_id]["status"] = "escalated"
            reports_by_id[report_id]["escalated_to"] = target
    state["escalation"] = {
        **escalation,
        "status": "accepted",
        "to_mode": target,
        "approved_by": args.approved_by.strip(),
        "approval_reason": args.reason.strip(),
        "approval_evidence": str(approval_relative),
        "approval_evidence_sha256": approval_hash,
        "resolved_at": now(),
    }
    add_history(
        state,
        "mode_escalated",
        f"{old_mode}->{target}:{old_stage}->scope_check:{escalation.get('report_id')}",
    )
    if invalidated_artifacts:
        add_history(state, "artifacts_invalidated", ",".join(invalidated_artifacts))
    if invalidated_meetings:
        add_history(state, "meetings_invalidated", ",".join(invalidated_meetings))
    save_state(path, state)
    print(f"Mode escalation approved by {args.approved_by}: {old_mode} -> {target}")
    print("Workflow rewound to scope_check; refresh the baseline before continuing.")


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


def parse_key_value(values: list[str], label: str) -> dict[str, str]:
    parsed: dict[str, str] = {}
    for value in values:
        key, separator, description = value.partition("=")
        key = key.strip()
        description = description.strip()
        if not separator or not key or not description:
            raise WorkflowError(f"{label} must use ID=description: {value!r}")
        if key in parsed:
            raise WorkflowError(f"Duplicate {label} ID: {key}")
        parsed[key] = description
    return parsed


def indexed_document(root: Path, raw_path: str) -> tuple[Path, Path, str]:
    absolute, relative = repository_evidence_path(
        root, raw_path, minimum_chars=MIN_DOCUMENT_CHARS
    )
    require_markdown_structure(absolute)
    return absolute, relative, content_sha256(absolute)


def cmd_record_core_goals(args: argparse.Namespace) -> None:
    root = repository_root(args.root)
    path, state = load_state(root, args.id)
    if state["workflow"]["current_stage"] != "requirement_confirmation":
        raise WorkflowError("Core goals can only be locked during requirement_confirmation.")
    goals = parse_key_value(args.goal, "goal")
    if any(not re.fullmatch(r"GOAL-\d{3}", goal_id) for goal_id in goals):
        raise WorkflowError("Core goal IDs must use GOAL-001 format.")
    absolute, relative, evidence_hash = indexed_document(root, args.evidence)
    text = absolute.read_text(encoding="utf-8").lower()
    if "user" not in text or not any(marker in text for marker in ("confirm", "approved", "确认", "批准")):
        raise WorkflowError("Core-goal evidence must record explicit user confirmation.")
    missing_ids = [goal_id for goal_id in goals if goal_id.lower() not in text]
    if missing_ids:
        raise WorkflowError("Core-goal evidence is missing IDs: " + ",".join(missing_ids))
    timestamp = now()
    state["core_goals"] = {
        goal_id: {
            "description": description,
            "evidence": str(relative),
            "evidence_sha256": evidence_hash,
            "confirmed_at": timestamp,
        }
        for goal_id, description in goals.items()
    }
    state["artifacts"]["core_goals"] = {
        "path": str(relative),
        "status": "ready",
        "evidence_sha256": evidence_hash,
        "updated_at": timestamp,
        "notes": "User-confirmed immutable outcome baseline.",
    }
    state["core_outcomes"] = {}
    add_history(state, "core_goals_locked", ",".join(goals))
    save_state(path, state)
    print("Locked user-confirmed core goals: " + ",".join(goals))


def cmd_register_acceptance_criteria(args: argparse.Namespace) -> None:
    root = repository_root(args.root)
    path, state = load_state(root, args.id)
    if state["workflow"]["current_stage"] != "prd":
        raise WorkflowError("Acceptance criteria can only be registered during PRD drafting.")
    prd = state.get("artifacts", {}).get("prd", {})
    if not artifact_ready(root, state, "prd"):
        raise WorkflowError("Record the current PRD artifact before registering its criteria.")
    criteria = parse_key_value(args.criterion, "criterion")
    if any(not re.fullmatch(r"AC-\d{3}", criterion_id) for criterion_id in criteria):
        raise WorkflowError("Acceptance criterion IDs must use AC-001 format.")
    prd_text = (root / str(prd["path"])).read_text(encoding="utf-8").lower()
    missing_ids = [criterion_id for criterion_id in criteria if criterion_id.lower() not in prd_text]
    if missing_ids:
        raise WorkflowError("PRD is missing acceptance criterion IDs: " + ",".join(missing_ids))
    state["acceptance_criteria"] = {
        criterion_id: {
            "description": description,
            "priority": "must",
            "prd_sha256": prd["evidence_sha256"],
            "registered_at": now(),
        }
        for criterion_id, description in criteria.items()
    }
    state["criterion_verdicts"] = {}
    add_history(state, "acceptance_criteria_registered", ",".join(criteria))
    save_state(path, state)
    print("Registered Must acceptance criteria: " + ",".join(criteria))


def next_scope_change_id(state: dict[str, Any]) -> str:
    numbers = [
        int(match.group(1))
        for change in state.get("scope_changes", [])
        if (match := re.fullmatch(r"SC-(\d+)", str(change.get("id", ""))))
    ]
    return f"SC-{max(numbers, default=0) + 1:03d}"


def scope_change_impact(
    state: dict[str, Any],
    items: list[str],
    requested_stage: str | None,
    impact_reason: str | None,
    evidence_text: str,
) -> tuple[str, str, str]:
    """Resolve a conservative default or an explicitly evidenced local rewind."""
    stages = workflow_stages(state)
    has_goal = any(item.startswith("GOAL-") for item in items)
    has_criterion = any(item.startswith("AC-") for item in items)
    baseline_stage = "requirement_confirmation" if has_goal else "prd"
    latest_safe_stage = "verification" if has_criterion else "acceptance"
    impact_stage = requested_stage or baseline_stage
    reason = (impact_reason or "").strip()

    if impact_stage not in stages or impact_stage == "completed":
        raise WorkflowError(f"Scope-change impact stage is not enabled: {impact_stage}")
    if baseline_stage not in stages or latest_safe_stage not in stages:
        raise WorkflowError("Scope-change items are incompatible with the selected workflow flow.")
    if not (
        stages.index(baseline_stage)
        <= stages.index(impact_stage)
        <= stages.index(latest_safe_stage)
    ):
        raise WorkflowError(
            f"Impact stage must be between {baseline_stage} and {latest_safe_stage}."
        )
    if requested_stage:
        if not reason:
            raise WorkflowError("--impact-reason is required with --impact-stage.")
        if impact_stage.lower() not in evidence_text:
            raise WorkflowError(
                "Scope-change evidence must name the approved earliest impact stage."
            )
    return baseline_stage, impact_stage, reason


def cmd_approve_scope_change(args: argparse.Namespace) -> None:
    root = repository_root(args.root)
    path, state = load_state(root, args.id)
    unknown = [
        item for item in args.item
        if item not in state.get("core_goals", {}) and item not in state.get("acceptance_criteria", {})
    ]
    if unknown:
        raise WorkflowError("Scope change references unknown items: " + ",".join(unknown))
    absolute, relative, evidence_hash = indexed_document(root, args.evidence)
    text = absolute.read_text(encoding="utf-8").lower()
    if "user" not in text or not any(marker in text for marker in ("approve", "approved", "批准", "同意")):
        raise WorkflowError("Scope reduction requires explicit user approval evidence.")
    if args.approved_by.strip().lower() not in text:
        raise WorkflowError("Scope-change evidence must name the approving user.")
    missing_ids = [item for item in args.item if item.lower() not in text]
    if missing_ids:
        raise WorkflowError("Scope-change evidence is missing item IDs: " + ",".join(missing_ids))
    baseline_stage, affected_stage, impact_reason = scope_change_impact(
        state,
        args.item,
        args.impact_stage,
        args.impact_reason,
        text,
    )
    change_id = next_scope_change_id(state)
    state["scope_changes"].append(
        {
            "id": change_id,
            "status": "approved",
            "items": list(dict.fromkeys(args.item)),
            "disposition": args.disposition,
            "approved_by": args.approved_by.strip(),
            "reason": args.reason.strip(),
            "baseline_stage": baseline_stage,
            "impact_stage": affected_stage,
            "impact_reason": impact_reason or "Conservative baseline rewind.",
            "evidence": str(relative),
            "evidence_sha256": evidence_hash,
            "approved_at": now(),
        }
    )
    stages = workflow_stages(state)
    current_stage = state["workflow"]["current_stage"]
    if (
        affected_stage in stages
        and current_stage in stages
        and stages.index(current_stage) >= stages.index(affected_stage)
    ):
        old_stage, invalidated_artifacts, invalidated_meetings = rewind_workflow(
            state,
            affected_stage,
            f"User-approved scope change {change_id}",
            preserve_artifacts={"requirement_confirmation", "core_goals", "prd"},
        )
        add_history(state, "change_control_required", f"{change_id}:{old_stage}->{affected_stage}")
        if invalidated_artifacts:
            add_history(state, "artifacts_invalidated", ",".join(invalidated_artifacts))
        if invalidated_meetings:
            add_history(state, "meetings_invalidated", ",".join(invalidated_meetings))
    add_history(state, "scope_change_approved", f"{change_id}:{','.join(args.item)}")
    save_state(path, state)
    print(f"Recorded user-approved scope change {change_id}")


def require_current_source(root: Path, state: dict[str, Any]) -> dict[str, Any]:
    source = state.get("source_revision", {})
    current = current_source_fingerprint(root, tuple(source.get("scope_paths", [])))
    if source.get("source_tree_sha256") != current["source_tree_sha256"]:
        raise WorkflowError("Record the current source revision before this evidence.")
    if current["dirty_paths"]:
        raise WorkflowError("Source tree has uncommitted changes: " + ",".join(current["dirty_paths"]))
    return current


def cmd_submit_verification(args: argparse.Namespace) -> None:
    """Atomically register a strict source binding, AC verdicts, and journey evidence."""
    root = repository_root(args.root)
    path, state = load_state(root, args.id)
    if state["workflow"]["mode"] != "strict" or state["workflow"]["current_stage"] != "verification":
        raise WorkflowError("Verification bundles can only be submitted during strict verification.")
    manifest_path, manifest_relative = repository_evidence_path(root, args.manifest)
    manifest = load_data(manifest_path)
    source_spec = manifest.get("source")
    journey_spec = manifest.get("journey")
    criteria_spec = manifest.get("criteria")
    if not isinstance(source_spec, dict) or not isinstance(journey_spec, dict):
        raise WorkflowError("Verification manifest requires source and journey mappings.")
    if not isinstance(criteria_spec, list):
        raise WorkflowError("Verification manifest requires a criteria list.")

    scope_paths = tuple(str(item) for item in source_spec.get("paths", []) if str(item).strip())
    current = current_source_fingerprint(root, scope_paths)
    if current["dirty_paths"]:
        raise WorkflowError(
            "Commit the scoped source under verification first: "
            + ",".join(current["dirty_paths"])
        )
    source_evidence, source_relative, source_hash = indexed_document(
        root, str(source_spec.get("evidence", ""))
    )
    del source_evidence
    build_command = str(source_spec.get("build_command", "")).strip()
    test_command = str(source_spec.get("test_command", "")).strip()
    if not build_command or not test_command:
        raise WorkflowError("Verification manifest source requires build_command and test_command.")

    expected_criteria = set(state.get("acceptance_criteria", {}))
    pending_verdicts: dict[str, dict[str, Any]] = {}
    for item in criteria_spec:
        if not isinstance(item, dict):
            raise WorkflowError("Each verification criterion must be a mapping.")
        criterion_id = str(item.get("id", ""))
        verdict = str(item.get("verdict", ""))
        if criterion_id not in expected_criteria:
            raise WorkflowError(f"Unknown acceptance criterion: {criterion_id}")
        if criterion_id in pending_verdicts:
            raise WorkflowError(f"Duplicate acceptance criterion: {criterion_id}")
        if verdict not in {"pass", "fail", "blocked", "not_applicable"}:
            raise WorkflowError(f"Invalid verdict for {criterion_id}: {verdict}")
        scope_change_id = str(item.get("scope_change_id", "")) or None
        if verdict == "not_applicable" and not scope_change_authorizes(
            root, state, scope_change_id or "", criterion_id
        ):
            raise WorkflowError(
                f"not_applicable requires a user-approved scope change: {criterion_id}"
            )
        evidence, relative, evidence_hash = indexed_document(
            root, str(item.get("evidence", ""))
        )
        evidence_text = evidence.read_text(encoding="utf-8").lower().replace("_", " ")
        if criterion_id.lower() not in evidence_text or verdict.replace("_", " ") not in evidence_text:
            raise WorkflowError(
                f"Criterion evidence must identify {criterion_id} and {verdict}."
            )
        pending_verdicts[criterion_id] = {
            "verdict": verdict,
            "verified_by": "testing",
            "scope_change_id": scope_change_id,
            "evidence": str(relative),
            "evidence_sha256": evidence_hash,
            "source_tree_sha256": current["source_tree_sha256"],
            "recorded_at": now(),
        }
    missing_criteria = sorted(expected_criteria - set(pending_verdicts))
    if missing_criteria:
        raise WorkflowError(
            "Verification bundle is missing criteria: " + ",".join(missing_criteria)
        )

    profile = str(journey_spec.get("profile", "web"))
    if profile not in JOURNEY_PROFILES:
        raise WorkflowError(f"Unknown journey profile: {profile}")
    checks = journey_spec.get("checks")
    if not isinstance(checks, dict):
        raise WorkflowError("Verification manifest journey requires a checks mapping.")
    normalized_checks = {str(key): str(value) for key, value in checks.items()}
    unknown_checks = sorted(set(normalized_checks) - set(JOURNEY_CHECKS))
    missing_checks = sorted(set(JOURNEY_PROFILES[profile]) - set(normalized_checks))
    invalid_checks = sorted(
        check
        for check, result in normalized_checks.items()
        if result not in JOURNEY_RESULTS
    )
    if unknown_checks or missing_checks or invalid_checks:
        raise WorkflowError(
            "Journey checks are invalid; "
            f"missing={','.join(missing_checks) or 'none'} "
            f"unknown={','.join(unknown_checks) or 'none'} "
            f"invalid_results={','.join(invalid_checks) or 'none'}"
        )
    journey_evidence, journey_relative, journey_hash = indexed_document(
        root, str(journey_spec.get("evidence", ""))
    )
    journey_text = journey_evidence.read_text(encoding="utf-8").lower()
    absent = [check for check in normalized_checks if check not in journey_text]
    if absent:
        raise WorkflowError("Journey report is missing check sections: " + ",".join(absent))

    timestamp = now()
    state["source_revision"] = {
        **current,
        "evidence": str(source_relative),
        "evidence_sha256": source_hash,
        "build_command": build_command,
        "test_command": test_command,
        "recorded_at": timestamp,
    }
    state["criterion_verdicts"] = pending_verdicts
    state["core_outcomes"] = {}
    state["journey_validation"] = {
        "checks": normalized_checks,
        "profile": profile,
        "verified_by": "testing",
        "evidence": str(journey_relative),
        "evidence_sha256": journey_hash,
        "source_tree_sha256": current["source_tree_sha256"],
        "recorded_at": timestamp,
    }
    state["artifacts"]["journey_report"] = {
        "path": str(journey_relative),
        "status": "ready",
        "evidence_sha256": journey_hash,
        "updated_at": timestamp,
        "notes": f"Registered atomically from {manifest_relative}.",
    }
    add_history(
        state,
        "verification_bundle_submitted",
        f"{manifest_relative}:{current['git_head']}:{profile}",
    )
    save_state(path, state)
    non_passing = [
        criterion_id
        for criterion_id, verdict in pending_verdicts.items()
        if verdict["verdict"] != "pass"
    ] + [
        check
        for check, result in normalized_checks.items()
        if check in JOURNEY_PROFILES[profile] and result != "pass"
    ]
    print(
        "Recorded atomic strict verification bundle"
        + (f"; gate remains blocked by: {','.join(non_passing)}" if non_passing else "")
    )


def cmd_record_source_revision(args: argparse.Namespace) -> None:
    root = repository_root(args.root)
    path, state = load_state(root, args.id)
    if state["workflow"]["mode"] != "strict" or state["workflow"]["current_stage"] != "verification":
        raise WorkflowError("Source revision binding is required only during strict verification.")
    absolute, relative, evidence_hash = indexed_document(root, args.evidence)
    current = current_source_fingerprint(root, tuple(args.source_path or ()))
    if current["dirty_paths"]:
        raise WorkflowError(
            "Commit the exact source under verification first: " + ",".join(current["dirty_paths"])
        )
    state["source_revision"] = {
        **current,
        "evidence": str(relative),
        "evidence_sha256": evidence_hash,
        "build_command": args.build_command.strip(),
        "test_command": args.test_command.strip(),
        "recorded_at": now(),
    }
    state["criterion_verdicts"] = {}
    state["core_outcomes"] = {}
    state["journey_validation"] = {}
    add_history(state, "source_revision_bound", current["git_head"])
    save_state(path, state)
    print(f"Bound verification to source revision {current['git_head']}")


def cmd_record_criterion_verdict(args: argparse.Namespace) -> None:
    root = repository_root(args.root)
    path, state = load_state(root, args.id)
    if state["workflow"]["current_stage"] != "verification":
        raise WorkflowError("Criterion verdicts can only be recorded during verification.")
    if args.criterion_id not in state.get("acceptance_criteria", {}):
        raise WorkflowError(f"Unknown acceptance criterion: {args.criterion_id}")
    current = require_current_source(root, state)
    if args.verdict == "not_applicable" and not scope_change_authorizes(
        root, state, args.scope_change_id or "", args.criterion_id
    ):
        raise WorkflowError("not_applicable requires a matching user-approved scope change.")
    absolute, relative, evidence_hash = indexed_document(root, args.evidence)
    text = absolute.read_text(encoding="utf-8").lower()
    if args.criterion_id.lower() not in text or args.verdict.replace("_", " ") not in text.replace("_", " "):
        raise WorkflowError("Verdict evidence must identify the criterion and verdict.")
    state["criterion_verdicts"][args.criterion_id] = {
        "verdict": args.verdict,
        "verified_by": "testing",
        "scope_change_id": args.scope_change_id,
        "evidence": str(relative),
        "evidence_sha256": evidence_hash,
        "source_tree_sha256": current["source_tree_sha256"],
        "recorded_at": now(),
    }
    add_history(state, "criterion_verdict_recorded", f"{args.criterion_id}:{args.verdict}")
    save_state(path, state)
    print(f"Recorded testing verdict for {args.criterion_id}: {args.verdict}")


def cmd_record_user_journey(args: argparse.Namespace) -> None:
    root = repository_root(args.root)
    path, state = load_state(root, args.id)
    if state["workflow"]["current_stage"] != "verification":
        raise WorkflowError("Final user-journey validation belongs to verification.")
    current = require_current_source(root, state)
    checks = parse_key_value(args.check, "check")
    required_checks = JOURNEY_PROFILES[args.profile]
    unknown = sorted(set(checks) - set(JOURNEY_CHECKS))
    missing = sorted(set(required_checks) - set(checks))
    invalid_results = sorted(
        check for check, result in checks.items() if result not in JOURNEY_RESULTS
    )
    if unknown or missing or invalid_results:
        raise WorkflowError(
            "Journey checks are invalid; "
            f"missing={','.join(missing) or 'none'} "
            f"unknown={','.join(unknown) or 'none'} "
            f"invalid_results={','.join(invalid_results) or 'none'}"
        )
    absolute, relative, evidence_hash = indexed_document(root, args.evidence)
    text = absolute.read_text(encoding="utf-8").lower()
    absent = [check for check in checks if check not in text]
    if absent:
        raise WorkflowError("Journey report is missing check sections: " + ",".join(absent))
    timestamp = now()
    state["journey_validation"] = {
        "checks": checks,
        "profile": args.profile,
        "verified_by": "testing",
        "evidence": str(relative),
        "evidence_sha256": evidence_hash,
        "source_tree_sha256": current["source_tree_sha256"],
        "recorded_at": timestamp,
    }
    state["artifacts"]["journey_report"] = {
        "path": str(relative),
        "status": "ready",
        "evidence_sha256": evidence_hash,
        "updated_at": timestamp,
        "notes": "End-to-end validation against the final source revision.",
    }
    add_history(state, "user_journey_verified", current["source_tree_sha256"])
    save_state(path, state)
    non_passing = [check for check, result in checks.items() if result != "pass"]
    print(
        "Recorded final user-journey evidence"
        + (f"; non-passing checks: {','.join(non_passing)}" if non_passing else "")
    )


def cmd_record_core_outcome(args: argparse.Namespace) -> None:
    root = repository_root(args.root)
    path, state = load_state(root, args.id)
    if state["workflow"]["current_stage"] != "acceptance":
        raise WorkflowError("Core outcomes can only be assessed during acceptance.")
    if args.goal_id not in state.get("core_goals", {}):
        raise WorkflowError(f"Unknown core goal: {args.goal_id}")
    current = require_current_source(root, state)
    if args.verdict in {"not_applicable", "deferred"} and not scope_change_authorizes(
        root, state, args.scope_change_id or "", args.goal_id
    ):
        raise WorkflowError("Reduced core outcomes require a matching user-approved scope change.")
    absolute, relative, evidence_hash = indexed_document(root, args.evidence)
    text = absolute.read_text(encoding="utf-8").lower()
    if args.goal_id.lower() not in text or args.verdict.replace("_", " ") not in text.replace("_", " "):
        raise WorkflowError("Outcome evidence must identify the goal and verdict.")
    state["core_outcomes"][args.goal_id] = {
        "verdict": args.verdict,
        "verified_by": "product",
        "scope_change_id": args.scope_change_id,
        "evidence": str(relative),
        "evidence_sha256": evidence_hash,
        "source_tree_sha256": current["source_tree_sha256"],
        "recorded_at": now(),
    }
    add_history(state, "core_outcome_recorded", f"{args.goal_id}:{args.verdict}")
    save_state(path, state)
    print(f"Recorded product outcome for {args.goal_id}: {args.verdict}")


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


def next_issue_id(state: dict[str, Any]) -> str:
    numbers = []
    for issue in state.get("issues", []):
        match = re.fullmatch(r"ISSUE-(\d+)", str(issue.get("id", "")))
        if match:
            numbers.append(int(match.group(1)))
    return f"ISSUE-{max(numbers, default=0) + 1:03d}"


def next_feedback_id(state: dict[str, Any]) -> str:
    numbers = []
    for feedback in state.get("user_feedback_records", []):
        match = re.fullmatch(r"UFB-(\d+)", str(feedback.get("id", "")))
        if match:
            numbers.append(int(match.group(1)))
    return f"UFB-{max(numbers, default=0) + 1:03d}"


def next_delivery_confirmation_id(state: dict[str, Any]) -> str:
    numbers = []
    for record in state.get("delivery_confirmation_records", []):
        match = re.fullmatch(r"DCF-(\d+)", str(record.get("id", "")))
        if match:
            numbers.append(int(match.group(1)))
    return f"DCF-{max(numbers, default=0) + 1:03d}"


def cmd_record_user_feedback(args: argparse.Namespace) -> None:
    root = repository_root(args.root)
    path, state = load_state(root, args.id)
    workflow = state["workflow"]
    if workflow["current_stage"] != "user_feedback":
        raise WorkflowError("User feedback can only be recorded during user_feedback.")
    evidence_path, relative = repository_evidence_path(
        root, args.evidence, minimum_chars=MIN_DOCUMENT_CHARS
    )
    require_markdown_structure(evidence_path)
    evidence_hash = content_sha256(evidence_path)
    for other_name, other in state.get("artifacts", {}).items():
        if other_name != "user_feedback" and other.get("path") == str(relative):
            raise WorkflowError(f"User feedback evidence is already used by {other_name}.")

    feedback_id = next_feedback_id(state)
    record = {
        "id": feedback_id,
        "verdict": args.verdict,
        "summary": args.summary.strip(),
        "affected_stage": args.affected_stage,
        "evidence": str(relative),
        "evidence_sha256": evidence_hash,
        "at": now(),
    }
    state.setdefault("user_feedback_records", []).append(record)

    if args.verdict == "approve":
        if args.affected_stage:
            raise WorkflowError("Approved feedback must not specify --affected-stage.")
        state.setdefault("artifacts", {})["user_feedback"] = {
            "path": str(relative),
            "status": "ready",
            "evidence_sha256": evidence_hash,
            "updated_at": now(),
            "notes": f"Explicit user approval recorded as {feedback_id}.",
        }
        add_history(state, "user_feedback_approved", feedback_id)
        save_state(path, state)
        print(f"Recorded {feedback_id}: user approved the preview direction")
        return

    if not args.affected_stage:
        raise WorkflowError("Change-request or rejection feedback requires --affected-stage.")
    stages = workflow_stages(state)
    if args.affected_stage not in stages:
        raise WorkflowError(f"Affected stage is not enabled in this flow: {args.affected_stage}")
    if stages.index(args.affected_stage) >= stages.index("user_feedback"):
        raise WorkflowError("Affected stage must be earlier than user_feedback.")
    old_stage, invalidated_artifacts, invalidated_meetings = rewind_workflow(
        state,
        args.affected_stage,
        f"User feedback {feedback_id}: {args.verdict}",
    )
    add_history(
        state,
        "user_feedback_changes_requested",
        f"{feedback_id}:{old_stage}->{args.affected_stage}:{args.verdict}",
    )
    if invalidated_artifacts:
        add_history(state, "artifacts_invalidated", ",".join(invalidated_artifacts))
    if invalidated_meetings:
        add_history(state, "meetings_invalidated", ",".join(invalidated_meetings))
    save_state(path, state)
    print(
        f"Recorded {feedback_id}: {args.verdict}; "
        f"workflow rewound to {args.affected_stage}"
    )


def cmd_record_delivery_confirmation(args: argparse.Namespace) -> None:
    root = repository_root(args.root)
    path, state = load_state(root, args.id)
    workflow = state["workflow"]
    if workflow["current_stage"] != "delivery_confirmation":
        raise WorkflowError(
            "Delivery confirmation can only be recorded during delivery_confirmation."
        )
    evidence_path, relative = repository_evidence_path(
        root, args.evidence, minimum_chars=MIN_DOCUMENT_CHARS
    )
    require_markdown_structure(evidence_path)
    evidence_text = evidence_path.read_text(encoding="utf-8")
    for marker in ("user", args.verdict):
        if not contains_marker(evidence_text, marker):
            raise WorkflowError(f"Delivery confirmation evidence must identify: {marker}")
    evidence_hash = content_sha256(evidence_path)
    confirmation_id = next_delivery_confirmation_id(state)
    record = {
        "id": confirmation_id,
        "verdict": args.verdict,
        "summary": args.summary.strip(),
        "affected_stage": args.affected_stage,
        "evidence": str(relative),
        "evidence_sha256": evidence_hash,
        "at": now(),
    }
    state.setdefault("delivery_confirmation_records", []).append(record)

    if args.verdict == "approve":
        if args.affected_stage:
            raise WorkflowError("Approved delivery must not specify --affected-stage.")
        state.setdefault("artifacts", {})["delivery_confirmation"] = {
            "path": str(relative),
            "status": "ready",
            "evidence_sha256": evidence_hash,
            "updated_at": now(),
            "notes": f"Explicit user delivery approval recorded as {confirmation_id}.",
        }
        add_history(state, "delivery_confirmed", confirmation_id)
        save_state(path, state)
        print(f"Recorded {confirmation_id}: user approved the verified delivery")
        return

    affected_stage = args.affected_stage or "implementation"
    stages = workflow_stages(state)
    if affected_stage not in stages:
        raise WorkflowError(f"Affected stage is not enabled in this flow: {affected_stage}")
    if stages.index(affected_stage) >= stages.index("delivery_confirmation"):
        raise WorkflowError("Affected stage must be earlier than delivery_confirmation.")
    old_stage, invalidated_artifacts, invalidated_meetings = rewind_workflow(
        state,
        affected_stage,
        f"Delivery confirmation {confirmation_id}: {args.verdict}",
    )
    add_history(
        state,
        "delivery_changes_requested",
        f"{confirmation_id}:{old_stage}->{affected_stage}:{args.verdict}",
    )
    if invalidated_artifacts:
        add_history(state, "artifacts_invalidated", ",".join(invalidated_artifacts))
    if invalidated_meetings:
        add_history(state, "meetings_invalidated", ",".join(invalidated_meetings))
    save_state(path, state)
    print(
        f"Recorded {confirmation_id}: {args.verdict}; workflow rewound to {affected_stage}"
    )


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
            if issue.get("status") != "open":
                raise WorkflowError(f"Issue is already dispositioned: {args.issue_id}")
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


def cmd_disposition_issue(args: argparse.Namespace) -> None:
    """Record an explicit, evidenced acceptance or deferral for a major issue."""
    root = repository_root(args.root)
    path, state = load_state(root, args.id)
    evidence_path, evidence = repository_evidence_path(
        root, args.evidence, minimum_chars=MIN_DOCUMENT_CHARS
    )
    require_markdown_structure(evidence_path)
    evidence_text = evidence_path.read_text(encoding="utf-8")
    for marker in (args.issue_id, args.disposition, args.approved_by):
        if not contains_marker(evidence_text, marker):
            raise WorkflowError(f"Disposition evidence must identify: {marker}")
    if args.disposition == "deferred" and not args.due_date:
        raise WorkflowError("A deferred issue requires --due-date (YYYY-MM-DD).")
    if args.due_date and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", args.due_date):
        raise WorkflowError("Due date must use YYYY-MM-DD.")
    evidence_hash = content_sha256(evidence_path)
    for issue in state.get("issues", []):
        if issue.get("id") != args.issue_id:
            continue
        if issue.get("severity") != "major":
            raise WorkflowError("Only major issues require an explicit disposition.")
        if issue.get("status") != "open":
            raise WorkflowError(f"Issue is already dispositioned: {args.issue_id}")
        if any(
            other.get("resolution_evidence_sha256") == evidence_hash
            or other.get("disposition_evidence_sha256") == evidence_hash
            for other in state.get("issues", [])
        ):
            raise WorkflowError("Disposition evidence is already used by another issue.")
        issue["status"] = args.disposition
        issue["disposition"] = args.disposition
        issue["disposition_rationale"] = args.rationale
        issue["disposition_approved_by"] = args.approved_by
        issue["disposition_evidence"] = str(evidence)
        issue["disposition_evidence_sha256"] = evidence_hash
        issue["due_date"] = args.due_date
        issue["dispositioned_at"] = now()
        current_stage = state["workflow"]["current_stage"]
        invalidated_meetings = (
            invalidate_gate_meetings(
                state, (current_stage,), f"Issue {args.issue_id} dispositioned"
            )
            if current_stage in GATES
            else []
        )
        add_history(state, "issue_dispositioned", f"{args.issue_id}:{args.disposition}")
        if invalidated_meetings:
            add_history(state, "meetings_invalidated", ",".join(invalidated_meetings))
        save_state(path, state)
        print(f"Recorded {args.disposition} for {args.issue_id}")
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
    actor_ref = args.actor_ref.strip()
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:/-]{2,127}", actor_ref):
        raise WorkflowError("Actor reference must be a stable 3-128 character task or session ID.")
    for role, decision in state.get("decisions", {}).get(args.gate, {}).items():
        if role != args.role and decision.get("actor_ref") == actor_ref:
            raise WorkflowError(
                f"Actor reference is already used by {role} at {args.gate}; "
                "independent roles require distinct task/session references."
            )
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
        "actor_ref": actor_ref,
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


def cmd_record_human_approval(args: argparse.Namespace) -> None:
    root = repository_root(args.root)
    path, state = load_state(root, args.id)
    current = state["workflow"]["current_stage"]
    if current != args.gate:
        raise WorkflowError(f"Cannot approve {args.gate} while current stage is {current}.")
    if not human_approval_required(state, args.gate):
        raise WorkflowError(f"Human approval is not configured for {args.gate}.")
    meeting = current_gate_meeting(root, state, args.gate)
    if meeting is None:
        raise WorkflowError("Human approval requires current approved gate meeting notes.")
    evidence_path, evidence = repository_evidence_path(
        root, args.evidence, minimum_chars=MIN_DOCUMENT_CHARS
    )
    evidence_text = evidence_path.read_text(encoding="utf-8")
    for marker in (args.gate, args.approved_by, "approve"):
        if not contains_marker(evidence_text, marker):
            raise WorkflowError(f"Human approval evidence must identify: {marker}")
    evidence_hash = content_sha256(evidence_path)
    reserved_hashes = {
        meeting.get("evidence_sha256"),
        *(
            decision.get("evidence_sha256")
            for decision in state.get("decisions", {}).get(args.gate, {}).values()
        ),
    }
    if evidence_hash in reserved_hashes:
        raise WorkflowError("Human approval requires distinct evidence.")
    state.setdefault("human_approvals", {})[args.gate] = {
        "status": "current",
        "approved_by": args.approved_by,
        "notes": args.notes or "",
        "evidence": str(evidence),
        "evidence_sha256": evidence_hash,
        "decision_snapshot": gate_decision_snapshot(state, args.gate),
        "meeting_evidence_sha256": meeting.get("evidence_sha256"),
        "at": now(),
    }
    add_history(state, "human_approval", f"{args.gate}:{args.approved_by}")
    save_state(path, state)
    print(f"Recorded human approval for {args.gate} by {args.approved_by}")


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
    init.add_argument(
        "--require-human-approval",
        action="append",
        choices=GATES,
        help="Require a separately evidenced human approval at this gate; repeat as needed",
    )
    init.add_argument("--force", action="store_true")
    init.set_defaults(func=cmd_init)

    start = subparsers.add_parser(
        "start", help="Start a workflow from a plain-language requirement and print an overview"
    )
    start.add_argument(
        "--id",
        default=argparse.SUPPRESS,
        help="Workflow ID; generated from the title when omitted",
    )
    start.add_argument("--request", required=True)
    start.add_argument("--title", help="Optional short title; defaults to the first request sentence")
    start.add_argument("--mode", choices=tuple(FLOWS), default="auto")
    start.add_argument(
        "--require-human-approval",
        action="append",
        choices=GATES,
        help="Require a separately evidenced human approval at this gate; repeat as needed",
    )
    start.add_argument("--force", action="store_true")
    start.set_defaults(func=cmd_start)

    status = subparsers.add_parser("status", help="Show workflow status")
    status.add_argument("--json", action="store_true")
    status.set_defaults(func=cmd_status)

    audit = subparsers.add_parser(
        "audit-state",
        help="Diagnose state integrity even when normal status loading is blocked",
    )
    audit.add_argument("--json", action="store_true")
    audit.set_defaults(func=cmd_audit_state)

    repair = subparsers.add_parser(
        "repair-state",
        help="Restore the last valid automatic state backup",
    )
    repair.add_argument("--from-backup", action="store_true", required=True)
    repair.add_argument("--confirm", required=True)
    repair.set_defaults(func=cmd_repair_state)

    overview = subparsers.add_parser("overview", help="Show a concise progress report")
    overview.add_argument("--json", action="store_true")
    overview.set_defaults(func=cmd_overview)

    next_cmd = subparsers.add_parser("next", help="Show the next required evidence or transition")
    next_cmd.set_defaults(func=cmd_next)

    risk = subparsers.add_parser(
        "assess-risk",
        help="Record structured requirement gaps, recommend a mode, and configure conditional gates",
    )
    risk.add_argument("--selected-mode", choices=tuple(MODE_RANK), required=True)
    risk.add_argument(
        "--checked-area",
        action="append",
        choices=REQUIREMENT_AREAS,
        help="Requirement category that was explicitly checked; all categories are required",
    )
    risk.add_argument("--risk", action="append", choices=RISK_FLAGS)
    risk.add_argument("--gap", action="append", help="Unresolved requirement gap; repeat as needed")
    risk.add_argument("--reason", action="append", help="Mode-selection reason; repeat as needed")
    risk.add_argument("--scope", required=True)
    risk.add_argument("--out-of-scope", required=True)
    risk.add_argument("--acceptance", required=True)
    risk.add_argument("--verification", required=True)
    risk.add_argument(
        "--evidence",
        required=True,
        help="Existing repository scope/risk document authored before state registration",
    )
    risk.add_argument(
        "--needs-clarification", choices=("auto", "yes", "no"), default="auto"
    )
    risk.add_argument(
        "--needs-confirmation", choices=("auto", "yes", "no"), default="auto"
    )
    risk.add_argument("--needs-preview", choices=("auto", "yes", "no"), default="auto")
    risk.set_defaults(func=cmd_assess_risk)

    report_risk = subparsers.add_parser(
        "report-risk",
        help="Record newly discovered risk and automatically require a safer mode when needed",
    )
    report_risk.add_argument(
        "--source",
        choices=("product", "engineering", "testing", "user", "coordinator"),
        required=True,
    )
    report_risk.add_argument("--risk", action="append", choices=RISK_FLAGS, required=True)
    report_risk.add_argument("--summary", required=True)
    report_risk.add_argument("--evidence", required=True)
    report_risk.set_defaults(func=cmd_report_risk)

    resolve_risk = subparsers.add_parser(
        "resolve-risk",
        help="Close a risk with separate resolution evidence and independent verification",
    )
    resolve_risk.add_argument("--risk-id", required=True)
    resolve_risk.add_argument("--resolution", required=True)
    resolve_risk.add_argument(
        "--resolved-by",
        choices=("product", "engineering", "testing", "user", "coordinator"),
        required=True,
    )
    resolve_risk.add_argument(
        "--verified-by",
        choices=("product", "engineering", "testing", "user", "coordinator"),
        required=True,
    )
    resolve_risk.add_argument("--evidence", required=True)
    resolve_risk.set_defaults(func=cmd_resolve_risk)

    withdraw_risk = subparsers.add_parser(
        "withdraw-risk",
        help="Withdraw a mistaken risk report with explicit reporter or user evidence",
    )
    withdraw_risk.add_argument("--risk-id", required=True)
    withdraw_risk.add_argument("--reason", required=True)
    withdraw_risk.add_argument(
        "--withdrawn-by",
        choices=("product", "engineering", "testing", "user", "coordinator"),
        required=True,
    )
    withdraw_risk.add_argument("--evidence", required=True)
    withdraw_risk.set_defaults(func=cmd_withdraw_risk)

    accept_risk = subparsers.add_parser(
        "accept-escalation-risk",
        help="Accept a waivable escalation risk with named human evidence and an expiry",
    )
    accept_risk.add_argument("--approved-by", required=True)
    accept_risk.add_argument("--reason", required=True)
    accept_risk.add_argument("--expires-on", required=True, help="YYYY-MM-DD")
    accept_risk.add_argument("--evidence", required=True)
    accept_risk.set_defaults(func=cmd_accept_escalation_risk)

    escalate = subparsers.add_parser(
        "escalate-mode",
        help="Apply a user-approved mode escalation and rewind to scope_check",
    )
    escalate.add_argument("--to-mode", choices=tuple(MODE_RANK), required=True)
    escalate.add_argument("--approved-by", required=True)
    escalate.add_argument("--reason", required=True)
    escalate.add_argument("--evidence", required=True)
    escalate.set_defaults(func=cmd_escalate_mode)

    artifact = subparsers.add_parser("record-artifact", help="Record an existing repository artifact")
    artifact.add_argument("--name", choices=ARTIFACTS, required=True)
    artifact.add_argument("--path", required=True)
    artifact.add_argument("--status", choices=("ready", "not_applicable", "superseded"), default="ready")
    artifact.add_argument("--notes")
    artifact.set_defaults(func=cmd_record_artifact)

    goals = subparsers.add_parser(
        "record-core-goals",
        help="Lock explicit user-confirmed outcomes before strict design work",
    )
    goals.add_argument("--goal", action="append", required=True, help="GOAL-001=outcome")
    goals.add_argument("--evidence", required=True)
    goals.set_defaults(func=cmd_record_core_goals)

    criteria = subparsers.add_parser(
        "register-acceptance-criteria",
        help="Register Must acceptance criteria from the current PRD",
    )
    criteria.add_argument("--criterion", action="append", required=True, help="AC-001=behavior")
    criteria.set_defaults(func=cmd_register_acceptance_criteria)

    scope_change = subparsers.add_parser(
        "approve-scope-change",
        help="Record explicit user authorization to reduce or defer a core goal or criterion",
    )
    scope_change.add_argument("--item", action="append", required=True, help="GOAL-001 or AC-001")
    scope_change.add_argument(
        "--disposition", choices=("removed", "deferred", "replaced"), required=True
    )
    scope_change.add_argument("--approved-by", required=True)
    scope_change.add_argument("--reason", required=True)
    scope_change.add_argument(
        "--impact-stage",
        choices=tuple(STAGE_LABELS),
        help="User-approved earliest affected stage; defaults to the conservative baseline.",
    )
    scope_change.add_argument(
        "--impact-reason",
        help="Why stages before --impact-stage remain valid; required with --impact-stage.",
    )
    scope_change.add_argument("--evidence", required=True)
    scope_change.set_defaults(func=cmd_approve_scope_change)

    verification_bundle = subparsers.add_parser(
        "submit-verification",
        help="Atomically register strict source, criterion, and journey evidence from one manifest",
    )
    verification_bundle.add_argument("--manifest", required=True)
    verification_bundle.set_defaults(func=cmd_submit_verification)

    source_revision = subparsers.add_parser(
        "record-source-revision",
        help="Bind strict verification to a committed source tree",
    )
    source_revision.add_argument("--evidence", required=True)
    source_revision.add_argument("--build-command", required=True)
    source_revision.add_argument("--test-command", required=True)
    source_revision.add_argument(
        "--source-path",
        action="append",
        help="Delivery path or module to bind; repeat as needed. Defaults to the whole Git tree.",
    )
    source_revision.set_defaults(func=cmd_record_source_revision)

    criterion_verdict = subparsers.add_parser(
        "record-criterion-verdict",
        help="Record independent testing verdict for one acceptance criterion",
    )
    criterion_verdict.add_argument("--criterion-id", required=True)
    criterion_verdict.add_argument(
        "--verdict", choices=("pass", "fail", "blocked", "not_applicable"), required=True
    )
    criterion_verdict.add_argument("--scope-change-id")
    criterion_verdict.add_argument("--evidence", required=True)
    criterion_verdict.set_defaults(func=cmd_record_criterion_verdict)

    journey = subparsers.add_parser(
        "record-user-journey",
        help="Record semantic end-to-end testing against the final source revision",
    )
    journey.add_argument("--profile", choices=tuple(JOURNEY_PROFILES), default="web")
    journey.add_argument(
        "--check",
        action="append",
        required=True,
        help="check_name=pass|fail|blocked|not_applicable",
    )
    journey.add_argument("--evidence", required=True)
    journey.set_defaults(func=cmd_record_user_journey)

    outcome = subparsers.add_parser(
        "record-core-outcome",
        help="Record product assessment of a user-confirmed core goal",
    )
    outcome.add_argument("--goal-id", required=True)
    outcome.add_argument(
        "--verdict", choices=("satisfied", "not_applicable", "deferred"), required=True
    )
    outcome.add_argument("--scope-change-id")
    outcome.add_argument("--evidence", required=True)
    outcome.set_defaults(func=cmd_record_core_outcome)

    feedback = subparsers.add_parser(
        "record-user-feedback",
        help="Record an explicit user preview verdict and rewind on requested changes",
    )
    feedback.add_argument(
        "--verdict", choices=("approve", "request_changes", "reject"), required=True
    )
    feedback.add_argument("--summary", required=True)
    feedback.add_argument("--evidence", required=True)
    feedback.add_argument("--affected-stage", choices=tuple(STAGE_LABELS))
    feedback.set_defaults(func=cmd_record_user_feedback)

    delivery = subparsers.add_parser(
        "record-delivery-confirmation",
        help="Record explicit user approval or requested changes for a verified delivery",
    )
    delivery.add_argument(
        "--verdict", choices=("approve", "request_changes", "reject"), required=True
    )
    delivery.add_argument("--summary", required=True)
    delivery.add_argument("--evidence", required=True)
    delivery.add_argument("--affected-stage", choices=tuple(STAGE_LABELS))
    delivery.set_defaults(func=cmd_record_delivery_confirmation)

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

    disposition = subparsers.add_parser(
        "disposition-issue",
        help="Record an evidenced human acceptance or scheduled deferral for a major issue",
    )
    disposition.add_argument("--issue-id", required=True)
    disposition.add_argument("--disposition", choices=("accepted_risk", "deferred"), required=True)
    disposition.add_argument("--approved-by", required=True)
    disposition.add_argument("--rationale", required=True)
    disposition.add_argument("--evidence", required=True)
    disposition.add_argument("--due-date", help="Required for deferred issues; YYYY-MM-DD")
    disposition.set_defaults(func=cmd_disposition_issue)

    decide = subparsers.add_parser("decide", help="Record an independent role verdict at the current gate")
    decide.add_argument("--gate", choices=GATES, required=True)
    decide.add_argument("--role", choices=ROLES, required=True)
    decide.add_argument(
        "--actor-ref",
        required=True,
        help="Stable subagent task/session reference; provides traceability, not authentication.",
    )
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

    human = subparsers.add_parser(
        "record-human-approval",
        help="Record a human authorization bound to current reviews and meeting evidence",
    )
    human.add_argument("--gate", choices=GATES, required=True)
    human.add_argument("--approved-by", required=True)
    human.add_argument("--evidence", required=True)
    human.add_argument("--notes")
    human.set_defaults(func=cmd_record_human_approval)

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
        mutating = {
            "init",
            "start",
            "repair-state",
            "assess-risk",
            "report-risk",
            "resolve-risk",
            "withdraw-risk",
            "accept-escalation-risk",
            "escalate-mode",
            "record-artifact",
            "record-core-goals",
            "register-acceptance-criteria",
            "approve-scope-change",
            "submit-verification",
            "record-source-revision",
            "record-criterion-verdict",
            "record-user-journey",
            "record-core-outcome",
            "record-user-feedback",
            "record-delivery-confirmation",
            "add-issue",
            "resolve-issue",
            "disposition-issue",
            "decide",
            "record-meeting",
            "record-human-approval",
            "advance",
            "reopen",
        }
        if args.command in mutating:
            with workflow_lock(repository_root(args.root)):
                args.func(args)
        else:
            args.func(args)
        return 0
    except WorkflowError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
