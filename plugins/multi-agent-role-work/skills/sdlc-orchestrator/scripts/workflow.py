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
    escalation_acceptance_expired,
    recommended_mode_for,
    refresh_escalation,
)
from risk_commands import invoke as invoke_risk_command
from review_commands import invoke as invoke_review_command
from assurance_commands import invoke as invoke_assurance_command
from delivery_commands import invoke as invoke_delivery_command
from work_commands import invoke as invoke_work_command, require_completed_output
from lifecycle_commands import invoke as invoke_lifecycle_command
from artifact_commands import invoke as invoke_artifact_command
from work_items import WorkItemError, supersede_work_item, validate_work_item
from stage_submission import StageSubmissionError, validate_submission_receipt
from execution_policy import (
    EXECUTION_POLICIES,
    execute_verification_commands,
    parse_verification_timeout,
    repository_context,
)
from source_policy import SourcePolicyError, source_binding, workspace_binding
from runtime_provenance import (
    ProvenanceError,
    default_plugin_root,
    doctor_exit_code,
    doctor_runtime,
    inspect_runtime,
    require_mutation_runtime,
)
from state_store import (
    WorkflowError,
    atomic_write_text,
    claim_owned_data,
    load_data,
    remove_owned_data,
    save_data,
    state_checksum,
    verify_state_checksum,
    workflow_lock,
)
from workflow_cli import MUTATING_COMMANDS, build_parser as create_cli_parser


CURRENT_SCHEMA_VERSION = 11
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
ARTIFACT_ROLE = {
    "clarification_questions": "product",
    "prd": "product",
    "technical_design": "engineering",
    "database_design": "engineering",
    "test_plan": "testing",
    "test_cases": "testing",
    "release_plan": "engineering",
    "prototype": "engineering",
    "implementation": "engineering",
    "verification_report": "testing",
    "journey_report": "testing",
    "traceability": "testing",
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
SPECIALIZED_ARTIFACT_COMMANDS = {
    "user_feedback": "record-user-feedback",
    "delivery_confirmation": "record-delivery-confirmation",
}
SOURCE_IDENTITY_FIELDS = (
    "git_head",
    "git_tree",
    "candidate_manifest_sha256",
    "source_tree_sha256",
)
ATOMIC_ARTIFACT_BUNDLE_GROUPS = {
    "design": frozenset(
        {
            "technical_design",
            "database_design",
            "test_plan",
            "test_cases",
            "release_plan",
        }
    ),
}
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


LIVE_POINTER_STATUSES = frozenset({"active", "paused"})
TERMINAL_WORKFLOW_STATUSES = frozenset({"completed", "abandoned"})
LIFECYCLE_MUTATION_COMMANDS = frozenset(
    {"init", "start", "repair-state", "resume", "activate", "deactivate", "abandon", "reopen"}
)
TOOL_IDENTITY_FIELDS = (
    "schema_version", "plugin_name", "version", "runtime_root", "entry_path",
    "entry_sha256", "payload_sha256", "git_revision", "dirty",
)


def canonical_state_path(root: Path, workflow_id: str) -> Path:
    validate_workflow_id(workflow_id)
    return root / ".ai-workflow" / workflow_id / "state.yaml"


def resolve_pointer_path(root: Path, data: dict[str, Any]) -> Path:
    workflow_id = data.get("workflow_id")
    relative = data.get("state_path")
    if not isinstance(workflow_id, str):
        raise WorkflowError(f"Invalid active pointer workflow_id: {active_pointer(root)}")
    validate_workflow_id(workflow_id)
    if not isinstance(relative, str) or not relative:
        raise WorkflowError(f"Invalid active pointer state_path: {active_pointer(root)}")
    resolved = (root / relative).resolve()
    try:
        resolved.relative_to(root.resolve())
    except ValueError as exc:
        raise WorkflowError("Active pointer state_path must be inside the repository root.") from exc
    expected = canonical_state_path(root, workflow_id).resolve()
    if resolved != expected:
        raise WorkflowError(
            f"Active pointer state_path does not match workflow_id {workflow_id}: {relative}"
        )
    return resolved


def state_path(root: Path, workflow_id: str | None = None) -> Path:
    if workflow_id:
        return canonical_state_path(root, workflow_id)
    pointer = active_pointer(root)
    if pointer.exists():
        # Resolve without loading state so audit/repair can still address a corrupt
        # state file. Normal state loads validate the repository-wide live invariant.
        return resolve_pointer_path(root, load_data(pointer))
    recovered = reconcile_live_workflow_pointer(root)
    if recovered is None:
        raise WorkflowError("No active workflow. Start one with init or activate an existing ID.")
    return recovered[0]


def pointer_record(root: Path, path: Path, state: dict[str, Any]) -> dict[str, Any]:
    workflow = state["workflow"]
    return {
        "workflow_id": workflow["id"],
        "state_path": str(path.relative_to(root)),
        "state_revision": state["revision"],
        "status": workflow["status"],
        "updated_at": now(),
    }


def claim_active_pointer(root: Path, path: Path, state: dict[str, Any]) -> None:
    workflow = state["workflow"]
    if workflow["status"] not in LIVE_POINTER_STATUSES:
        raise WorkflowError(f"Cannot activate workflow with status {workflow['status']}.")
    pointer = active_pointer(root)
    if pointer.exists():
        current = load_data(pointer)
        current_id = current.get("workflow_id")
        if current_id != workflow["id"]:
            raise WorkflowError(
                f"Workflow {current_id} is already active. Deactivate, abandon, or complete it first."
            )
    claim_owned_data(
        pointer,
        pointer_record(root, path, state),
        owner_key="workflow_id",
        owner=workflow["id"],
    )


def release_active_pointer(root: Path, workflow_id: str) -> bool:
    return remove_owned_data(
        active_pointer(root), owner_key="workflow_id", owner=workflow_id
    )


def _load_state_file(root: Path, path: Path) -> dict[str, Any]:
    state = load_data(path)
    verify_state_checksum(state, path, CURRENT_SCHEMA_VERSION)
    migrate_state(root, state)
    validate_state(state, path)
    return state


def _live_workflow_states(root: Path) -> list[tuple[Path, dict[str, Any]]]:
    """Return every valid active/paused workflow, failing closed on corrupt state."""
    live: list[tuple[Path, dict[str, Any]]] = []
    workflow_root = root / ".ai-workflow"
    if not workflow_root.exists():
        return live
    for path in sorted(workflow_root.glob("*/state.yaml")):
        state = _load_state_file(root, path)
        workflow_id = state["workflow"].get("id")
        if workflow_id != path.parent.name:
            raise WorkflowError(
                f"Workflow state ID {workflow_id!r} does not match directory {path.parent.name!r}."
            )
        if state["workflow"]["status"] in LIVE_POINTER_STATUSES:
            live.append((path.resolve(), state))
    return live


def reconcile_live_workflow_pointer(
    root: Path,
) -> tuple[Path, dict[str, Any]] | None:
    """Validate the single-live invariant and recover a missing/stale pointer."""
    pointer_path = active_pointer(root)
    pointed_path: Path | None = None
    pointed_state: dict[str, Any] | None = None
    pointer_owner: str | None = None
    if pointer_path.exists():
        pointer = load_data(pointer_path)
        pointed_path = resolve_pointer_path(root, pointer)
        pointed_state = _load_state_file(root, pointed_path)
        pointer_owner = str(pointer.get("workflow_id"))

    live = _live_workflow_states(root)
    if len(live) > 1:
        owners = ", ".join(item[1]["workflow"]["id"] for item in live)
        raise WorkflowError(
            "Multiple live workflows were found; refusing to choose or replace the active "
            f"pointer: {owners}. Deactivate or abandon all but one workflow explicitly."
        )

    live_item = live[0] if live else None
    if pointed_state is not None:
        pointed_status = pointed_state["workflow"]["status"]
        if pointed_status not in LIVE_POINTER_STATUSES:
            release_active_pointer(root, pointer_owner or "")
            pointed_path = None
            pointed_state = None
        elif live_item is None or live_item[1]["workflow"]["id"] != pointer_owner:
            raise WorkflowError(
                "Active pointer ownership does not match the repository's live workflow state."
            )

        if pointed_state is not None:
            pointer_revision = load_data(pointer_path).get("state_revision")
            if pointer_revision is not None and (
                not isinstance(pointer_revision, int)
                or pointer_revision > pointed_state["revision"]
            ):
                raise WorkflowError(
                    f"Active pointer revision {pointer_revision!r} is ahead of state revision "
                    f"{pointed_state['revision']}; refusing to rewrite the pointer."
                )

    if live_item is None:
        return None

    live_path, live_state = live_item
    if pointed_path is None:
        claim_active_pointer(root, live_path, live_state)
    else:
        expected = pointer_record(root, live_path, live_state)
        pointer = load_data(pointer_path)
        if any(pointer.get(key) != expected[key] for key in ("state_revision", "status")):
            claim_active_pointer(root, live_path, live_state)
    return live_path, live_state


def reconcile_pointer_for_state(
    root: Path,
    path: Path,
    state: dict[str, Any],
    *,
    require_owner: bool,
) -> None:
    pointer_path = active_pointer(root)
    workflow = state["workflow"]
    if not pointer_path.exists():
        if require_owner:
            raise WorkflowError("No active workflow. Start one with init or activate an existing ID.")
        return
    pointer = load_data(pointer_path)
    pointer_state_path = resolve_pointer_path(root, pointer)
    pointer_id = pointer.get("workflow_id")
    if pointer_id != workflow["id"]:
        if require_owner:
            raise WorkflowError(
                f"Active pointer workflow {pointer_id} does not match state workflow {workflow['id']}."
            )
        return
    if pointer_state_path != path.resolve():
        raise WorkflowError("Active pointer resolved to the wrong workflow state file.")
    if workflow["status"] not in LIVE_POINTER_STATUSES:
        release_active_pointer(root, workflow["id"])
        if require_owner:
            raise WorkflowError(
                "No active workflow. Removed a stale pointer to "
                f"{workflow['status']} workflow {workflow['id']}."
            )
        return
    pointer_revision = pointer.get("state_revision")
    if pointer_revision is not None and (
        not isinstance(pointer_revision, int) or pointer_revision > state["revision"]
    ):
        raise WorkflowError(
            f"Active pointer revision {pointer_revision!r} is ahead of state revision {state['revision']}."
        )
    expected = pointer_record(root, path, state)
    if any(pointer.get(key) != expected[key] for key in ("state_revision", "status")):
        claim_active_pointer(root, path, state)


def load_state(root: Path, workflow_id: str | None = None) -> tuple[Path, dict[str, Any]]:
    path = state_path(root, workflow_id)
    state = _load_state_file(root, path)
    if workflow_id and state["workflow"].get("id") != workflow_id:
        raise WorkflowError(
            f"Workflow state ID {state['workflow'].get('id')} does not match requested ID {workflow_id}."
        )
    if workflow_id is None:
        live = reconcile_live_workflow_pointer(root)
        if live is None:
            raise WorkflowError("No active workflow. Start one with init or activate an existing ID.")
        if live[0] != path.resolve():
            raise WorkflowError("Active pointer resolved to a different live workflow state file.")
    reconcile_pointer_for_state(root, path, state, require_owner=workflow_id is None)
    return path, state


def require_active_workflow_owner(root: Path, workflow_id: str | None) -> tuple[Path, dict[str, Any]]:
    """Load the requested state only when it owns the repository live pointer."""
    live = reconcile_live_workflow_pointer(root)
    if live is None:
        if workflow_id is not None:
            path, selected = load_state(root, workflow_id)
            status = selected["workflow"]["status"]
            if status in TERMINAL_WORKFLOW_STATUSES:
                return path, selected
        raise WorkflowError("No active workflow. Activate it before mutating it.")
    live_path, live_state = live
    if workflow_id is not None and live_state["workflow"]["id"] != workflow_id:
        raise WorkflowError(
            f"Active workflow is {live_state['workflow']['id']}; refusing to mutate non-active "
            f"workflow {workflow_id}. Activate it explicitly first."
        )
    reconcile_pointer_for_state(root, live_path, live_state, require_owner=True)
    return live_path, live_state


def ensure_pointer_available(root: Path, workflow_id: str) -> None:
    live = reconcile_live_workflow_pointer(root)
    if live is None:
        return
    _, state = live
    if state["workflow"]["id"] != workflow_id:
        raise WorkflowError(
            f"Workflow {state['workflow']['id']} is already active. "
            "Deactivate, abandon, or complete it first."
        )


def migrate_state(root: Path, state: dict[str, Any]) -> None:
    version = state.get("schema_version")
    migrated_to_role_work_items = version in {1, 2, 3, 4, 5, 6, 7, 8, 9, 10}
    if version in {1, 2, 3, 4, 5, 6, 7, 8, 9, 10}:
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
    state.setdefault("work_items", {})
    state.setdefault("stage_submissions", {})
    state.setdefault("runtime_provenance", {})
    if migrated_to_role_work_items:
        # Older schemas did not bind role-produced evidence to a leased work
        # item. Preserve the bytes for audit, but never manufacture provenance
        # or allow that evidence to satisfy a v11 role gate.
        for name, artifact in state.get("artifacts", {}).items():
            if name in ARTIFACT_ROLE and not artifact.get("producer_work_item_id"):
                artifact["legacy_unbound"] = True
        for decisions in state.get("decisions", {}).values():
            for decision in decisions.values():
                if not decision.get("producer_work_item_id"):
                    decision["legacy_unbound"] = True
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
    status = workflow.get("status")
    if status not in {"active", "paused", "inactive", "completed", "abandoned"}:
        raise WorkflowError(f"Invalid workflow status in {path}: {workflow.get('status')!r}")
    if (status == "completed") != (stage == "completed"):
        raise WorkflowError(
            f"Invalid workflow lifecycle in {path}: completed status and completed stage must match."
        )
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
        "work_items",
        "stage_submissions",
        "runtime_provenance",
    ):
        if not isinstance(state.get(name), dict):
            raise WorkflowError(f"Invalid {name} mapping in {path}")
    for work_item_id, work_item in state.get("work_items", {}).items():
        try:
            checked = validate_work_item(work_item)
        except WorkItemError as exc:
            raise WorkflowError(f"Invalid work item {work_item_id} in {path}: {exc}") from exc
        if checked["work_item_id"] != work_item_id:
            raise WorkflowError(f"Work item key does not match its ID in {path}: {work_item_id}")
        if checked["role"] not in ROLES or checked["stage"] not in configured_stages:
            raise WorkflowError(f"Work item has an invalid workflow role or stage: {work_item_id}")
    for receipt_key, receipt in state.get("stage_submissions", {}).items():
        try:
            checked_receipt = validate_submission_receipt(receipt)
        except StageSubmissionError as exc:
            raise WorkflowError(
                f"Invalid stage submission {receipt_key} in {path}: {exc}"
            ) from exc
        if checked_receipt["idempotency_key"] != receipt_key:
            raise WorkflowError(
                f"Stage-submission key does not match its receipt in {path}: {receipt_key}"
            )
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
    if name in ARTIFACT_ROLE and (
        item.get("legacy_unbound") or not item.get("producer_work_item_id")
    ):
        return False
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


def execution_candidate_matches(
    execution: dict[str, Any], binding: dict[str, Any]
) -> bool:
    candidate = execution.get("candidate", {})
    if not isinstance(candidate, dict):
        return False
    if binding.get("binding_type") == "git_commit":
        return all(
            candidate.get(key) == expected
            for key, expected in {
                "kind": "git_commit",
                "commit_oid": binding.get("git_head"),
                "tree_oid": binding.get("git_tree"),
                "manifest_sha256": binding.get("candidate_manifest_sha256"),
            }.items()
        )
    if binding.get("binding_type") == "workspace_content":
        return all(
            candidate.get(key) == expected
            for key, expected in {
                "kind": "workspace_content",
                "tree_oid": binding.get("candidate_tree"),
                "manifest_sha256": binding.get("candidate_manifest_sha256"),
            }.items()
        )
    return False


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
        and bool(str(decision.get("producer_work_item_id", "")).strip())
        and not decision.get("legacy_unbound")
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
    if rewind_index > stages.index(old_stage):
        raise WorkflowError(
            f"Reopen cannot move forward from {old_stage} to {stage}; use advance after satisfying gates."
        )
    state["workflow"]["current_stage"] = stage
    state["workflow"]["status"] = "active"
    for key in (
        "paused_at",
        "pause_reason",
        "deactivated_at",
        "deactivation_reason",
        "abandoned_at",
        "abandon_reason",
        "completed_at",
    ):
        state["workflow"].pop(key, None)

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
    superseded_revision = int(state.get("revision", 0)) + 1
    for work_item_id, item in list(state.get("work_items", {}).items()):
        work_stage = item.get("stage") if isinstance(item, dict) else None
        if (
            work_stage in stages
            and stages.index(work_stage) >= rewind_index
            and item.get("status") in {"dispatched", "running", "completed"}
        ):
            try:
                state["work_items"][work_item_id] = supersede_work_item(
                    item,
                    at=now(),
                    reason=reason,
                    superseded_by_revision=superseded_revision,
                )
            except WorkItemError as exc:
                raise WorkflowError(
                    f"Unable to supersede stale work item {work_item_id}: {exc}"
                ) from exc
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
            if not source or any(
                source.get(key) != fingerprint.get(key)
                for key in SOURCE_IDENTITY_FIELDS
            ):
                missing.append("source_revision:stale_or_missing")
            if not test_execution_ready(root, source.get("test_execution", {})):
                missing.append("source_revision:test_execution")
            elif not execution_candidate_matches(source["test_execution"], source):
                missing.append("source_revision:candidate_mismatch")
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
        elif not execution_candidate_matches(snapshot["test_execution"], snapshot):
            missing.append("verification_snapshot:candidate_mismatch")
        elif any(
            snapshot.get(key) != current_workspace.get(key)
            for key in ("candidate_tree", "candidate_manifest_sha256", "source_tree_sha256")
        ):
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
    if escalation_acceptance_expired(escalation):
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


def active_pointer_health(root: Path, state: dict[str, Any]) -> tuple[str, str | None]:
    workflow = state["workflow"]
    pointer_path = active_pointer(root)
    if not pointer_path.exists():
        return ("missing", None) if workflow["status"] in LIVE_POINTER_STATUSES else ("none", None)
    try:
        pointer = load_data(pointer_path)
        resolve_pointer_path(root, pointer)
    except WorkflowError as exc:
        return "invalid", str(exc)
    pointer_id = str(pointer.get("workflow_id", ""))
    if pointer_id != workflow["id"]:
        return "owned_by_other", pointer_id
    if workflow["status"] not in LIVE_POINTER_STATUSES:
        return "stale_terminal", pointer_id
    if pointer.get("state_revision") != state["revision"] or pointer.get("status") != workflow["status"]:
        return "stale", pointer_id
    return "current", pointer_id


def overview_payload(root: Path, state: dict[str, Any]) -> dict[str, Any]:
    workflow = state["workflow"]
    stage = workflow["current_stage"]
    status = workflow["status"]
    stage_missing, stage_notes = stage_requirements(root, state)
    missing, notes = list(stage_missing), list(stage_notes)
    health_warnings: list[str] = []
    recorded_context = state.get("repository_context", {})
    current_context = repository_context(root)
    provenance = state.get("runtime_provenance", {})
    current_tool = current_tool_identity()
    last_tool = provenance.get("last_mutated_by_tool", {})
    if last_tool and runtime_identity_changed(last_tool, current_tool):
        health_warnings.append(
            "Loaded workflow tool identity differs from the last recorded mutator; run doctor."
        )
    if (
        recorded_context.get("git_branch")
        and current_context.get("git_branch")
        and recorded_context["git_branch"] != current_context["git_branch"]
    ):
        health_warnings.append(
            f"Git branch changed from {recorded_context['git_branch']} to "
            f"{current_context['git_branch']}; confirm this workflow belongs on the current branch."
        )
    pointer_health, pointer_owner = active_pointer_health(root, state)
    if status in LIVE_POINTER_STATUSES and pointer_health != "current":
        missing.append(f"workflow:pointer_{pointer_health}")
        if pointer_health == "owned_by_other":
            health_warnings.append(f"Active pointer belongs to workflow {pointer_owner}.")
        else:
            health_warnings.append("Active workflow pointer is missing, stale, or invalid; use activate to restore it.")
    lifecycle_actions = {
        "paused": "Resume this workflow before continuing.",
        "inactive": "Activate this workflow before continuing.",
        "completed": "No next workflow action is required.",
        "abandoned": "This workflow was abandoned; reopen it explicitly to continue.",
    }
    if status != "active":
        missing = [] if status == "completed" else [f"workflow:{status}"]
        notes = [] if status == "completed" else [lifecycle_actions[status]]
    next_stage = next_stage_name(state) if status == "active" and not missing else None
    if status in lifecycle_actions:
        next_action = lifecycle_actions[status]
    elif pointer_health != "current":
        next_action = "Restore this workflow's active pointer with activate before continuing."
    elif state.get("escalation", {}).get("status") == "required":
        escalation = state.get("escalation", {})
        next_action = (
            f"Review risk {escalation.get('report_id')} and obtain explicit user approval to escalate "
            f"from {escalation.get('from_mode')} to at least {escalation.get('recommended_mode')}."
        )
    elif next_stage and not missing:
        next_action = f"Advance to {STAGE_LABELS.get(next_stage, next_stage)}."
    else:
        next_action = STAGE_GUIDANCE.get(stage, "Continue the current workflow stage.")
    return {
        "workflow_id": workflow["id"],
        "title": workflow["title"],
        "mode": workflow["mode"],
        "status": status,
        "stage": stage,
        "stage_label": STAGE_LABELS.get(stage, stage),
        "can_advance": status == "active" and pointer_health == "current" and not missing,
        "next_stage": next_stage,
        "next_stage_label": STAGE_LABELS.get(next_stage, next_stage) if next_stage else None,
        "next_action": next_action,
        "missing": missing,
        "notes": notes,
        "stage_missing_after_resume": stage_missing,
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
        "meeting_notes": sum(1 for item in state.get("meetings", []) if item.get("status") == "current"),
        "meeting_notes_total": len(state.get("meetings", [])),
        "state_revision": state["revision"],
        "human_approval_gates": state.get("human_approval_policy", {}).get("required_gates", []),
        "risk_recommendation": state.get("risk_assessment", {}).get("recommended_mode"),
        "enabled_stages": list(workflow_stages(state)),
        "escalation": state.get("escalation", {"status": "none"}),
        "execution_policy": EXECUTION_POLICIES[workflow["mode"]],
        "health_warnings": health_warnings,
        "pointer_health": pointer_health,
        "pause_reason": workflow.get("pause_reason"),
        "runtime_provenance": provenance,
        "current_tool_identity": current_tool,
    }


def print_overview(payload: dict[str, Any]) -> None:
    print(f"Workflow: {payload['workflow_id']} — {payload['title']}")
    print(
        f"Stage: {payload['stage']} ({payload['stage_label']})  "
        f"Mode: {payload['mode']}  Status: {payload['status']}"
    )
    print(f"Can advance: {'yes' if payload['can_advance'] else 'no'}")
    print(f"Next action: {payload['next_action']}")
    last_tool = payload.get("runtime_provenance", {}).get("last_mutated_by_tool", {})
    if last_tool:
        print(
            "Last mutated by tool: "
            f"{last_tool.get('plugin_name')} {last_tool.get('version')} "
            f"payload={last_tool.get('payload_sha256')}"
        )
    else:
        print("Last mutated by tool: unavailable (legacy workflow state)")
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
    print(
        "Cost budget: recommended role handoffs per stage <= "
        f"{policy['recommended_max_role_handoffs_per_stage']}; "
        "verification commands per run <= "
        f"{policy['max_verification_commands_per_run']} (enforced)"
    )
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
    runtime_report = require_mutation_runtime_health(state)
    tool_identity = {key: runtime_report["runtime"].get(key) for key in TOOL_IDENTITY_FIELDS}
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
    provenance = state.setdefault("runtime_provenance", {})
    provenance.setdefault("created_by_tool", tool_identity)
    provenance["last_mutated_by_tool"] = tool_identity
    state["schema_version"] = CURRENT_SCHEMA_VERSION
    state["revision"] = expected_revision + 1
    state["state_checksum"] = state_checksum(state)
    validate_state(state, path)
    save_data(path, state)
    if path.name == "state.yaml" and path.parent.parent.name == ".ai-workflow":
        root = path.parents[2]
        pointer = active_pointer(root)
        if pointer.exists() and load_data(pointer).get("workflow_id") == state["workflow"]["id"]:
            if state["workflow"]["status"] in LIVE_POINTER_STATUSES:
                claim_active_pointer(root, path, state)
            else:
                release_active_pointer(root, state["workflow"]["id"])


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


def current_tool_identity(runtime_root: Path | str | None = None) -> dict[str, Any]:
    """Return the immutable identity fields of the workflow tool executing now."""
    try:
        observed = inspect_runtime(runtime_root or default_plugin_root())
    except ProvenanceError as exc:
        raise WorkflowError(f"Unable to identify the workflow runtime: {exc}") from exc
    return {key: observed.get(key) for key in TOOL_IDENTITY_FIELDS}


LOADED_TOOL_IDENTITY = current_tool_identity()


def runtime_identity_changed(recorded: dict[str, Any], current: dict[str, Any]) -> bool:
    return any(
        recorded.get(field) != current.get(field)
        for field in ("plugin_name", "version", "entry_path", "entry_sha256", "payload_sha256")
    )


def require_mutation_runtime_health(state: dict[str, Any] | None = None) -> dict[str, Any]:
    """Fail closed before any command is permitted to write workflow state."""
    try:
        return require_mutation_runtime(
            default_plugin_root(),
            recorded_identity=(state or {}).get("runtime_provenance", {}).get(
                "last_mutated_by_tool", {}
            ),
            loaded_identity=LOADED_TOOL_IDENTITY,
        )
    except ProvenanceError as exc:
        raise WorkflowError(f"Runtime provenance audit failed: {exc}") from exc


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


def cmd_version(args: argparse.Namespace) -> int:
    return invoke_lifecycle_command("cmd_version", sys.modules[__name__], args)


def cmd_doctor(args: argparse.Namespace) -> int:
    return invoke_lifecycle_command("cmd_doctor", sys.modules[__name__], args)


def cmd_init(args: argparse.Namespace) -> None:
    invoke_lifecycle_command("cmd_init", sys.modules[__name__], args)


def cmd_start(args: argparse.Namespace) -> None:
    invoke_lifecycle_command("cmd_start", sys.modules[__name__], args)


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
    invoke_lifecycle_command("cmd_status", sys.modules[__name__], args)


def cmd_audit_state(args: argparse.Namespace) -> None:
    invoke_lifecycle_command("cmd_audit_state", sys.modules[__name__], args)


def cmd_repair_state(args: argparse.Namespace) -> None:
    invoke_lifecycle_command("cmd_repair_state", sys.modules[__name__], args)


def cmd_overview(args: argparse.Namespace) -> None:
    invoke_lifecycle_command("cmd_overview", sys.modules[__name__], args)


def cmd_pause(args: argparse.Namespace) -> None:
    invoke_lifecycle_command("cmd_pause", sys.modules[__name__], args)


def cmd_resume(args: argparse.Namespace) -> None:
    invoke_lifecycle_command("cmd_resume", sys.modules[__name__], args)


def cmd_activate(args: argparse.Namespace) -> None:
    invoke_lifecycle_command("cmd_activate", sys.modules[__name__], args)


def cmd_deactivate(args: argparse.Namespace) -> None:
    invoke_lifecycle_command("cmd_deactivate", sys.modules[__name__], args)


def cmd_abandon(args: argparse.Namespace) -> None:
    invoke_lifecycle_command("cmd_abandon", sys.modules[__name__], args)


def cmd_list(args: argparse.Namespace) -> None:
    invoke_lifecycle_command("cmd_list", sys.modules[__name__], args)


def cmd_next(args: argparse.Namespace) -> None:
    invoke_lifecycle_command("cmd_next", sys.modules[__name__], args)


def cmd_record_core_goals(args: argparse.Namespace) -> None:
    invoke_assurance_command("cmd_record_core_goals", sys.modules[__name__], args)


def cmd_begin_work(args: argparse.Namespace) -> None:
    invoke_work_command("cmd_begin_work", sys.modules[__name__], args)


def cmd_heartbeat_work(args: argparse.Namespace) -> None:
    invoke_work_command("cmd_heartbeat_work", sys.modules[__name__], args)


def cmd_complete_work(args: argparse.Namespace) -> None:
    invoke_work_command("cmd_complete_work", sys.modules[__name__], args)


def cmd_cancel_work(args: argparse.Namespace) -> None:
    invoke_work_command("cmd_cancel_work", sys.modules[__name__], args)


def cmd_timeout_work(args: argparse.Namespace) -> None:
    invoke_work_command("cmd_timeout_work", sys.modules[__name__], args)


def cmd_fail_work(args: argparse.Namespace) -> None:
    invoke_work_command("cmd_fail_work", sys.modules[__name__], args)


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
    invoke_artifact_command("cmd_record_artifact", sys.modules[__name__], args)


def cmd_record_artifact_bundle(args: argparse.Namespace) -> None:
    invoke_artifact_command("cmd_record_artifact_bundle", sys.modules[__name__], args)


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
    invoke_lifecycle_command("cmd_advance", sys.modules[__name__], args)


def cmd_reopen(args: argparse.Namespace) -> None:
    invoke_lifecycle_command("cmd_reopen", sys.modules[__name__], args)


def build_parser() -> argparse.ArgumentParser:
    return create_cli_parser(sys.modules[__name__])


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    try:
        if args.command in MUTATING_COMMANDS:
            root = repository_root(args.root)
            with workflow_lock(root):
                current: dict[str, Any] | None = None
                if args.command not in LIFECYCLE_MUTATION_COMMANDS:
                    _, current = require_active_workflow_owner(root, args.id)
                    status = current["workflow"]["status"]
                    if status == "paused":
                        raise WorkflowError(
                            "Workflow is paused. Resume it before recording or changing delivery state."
                        )
                    if status in TERMINAL_WORKFLOW_STATUSES:
                        raise WorkflowError(
                            f"The {status} workflow is immutable. Use reopen for a new delivery iteration."
                        )
                    if status == "inactive":
                        raise WorkflowError(
                            "Workflow is inactive. Activate it before recording or changing delivery state."
                        )
                elif args.command not in {"init", "start", "repair-state"}:
                    _, current = load_state(root, args.id)
                require_mutation_runtime_health(current)
                result = args.func(args)
        else:
            result = args.func(args)
        return int(result or 0)
    except WorkflowError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
