#!/usr/bin/env python3
"""Deterministic state and gate management for the multi-role SDLC workflow."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    import fcntl  # type: ignore
except ImportError:  # pragma: no cover - Windows fallback is exercised on Windows.
    fcntl = None

try:
    import msvcrt  # type: ignore
except ImportError:  # pragma: no cover - POSIX uses fcntl.
    msvcrt = None

try:
    import yaml  # type: ignore
except ImportError:  # JSON is valid YAML 1.2 and is the dependency-free fallback.
    yaml = None


CURRENT_SCHEMA_VERSION = 2
WORKFLOW_ID_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{2,80}")
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
    "original_request": "intake",
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
ARTIFACT_CHANGE_STAGE = {
    "original_request": "intake",
    "prd": "prd",
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


def atomic_write_text(path: Path, rendered: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=path.parent,
        text=True,
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(rendered)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        try:
            directory = os.open(path.parent, os.O_RDONLY)
        except OSError:
            return
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        temporary.unlink(missing_ok=True)


def save_data(path: Path, data: dict[str, Any]) -> None:
    if yaml:
        rendered = yaml.safe_dump(data, sort_keys=False, allow_unicode=True)
    else:
        rendered = json.dumps(data, indent=2, ensure_ascii=False) + "\n"
    atomic_write_text(path, rendered)


@contextmanager
def workflow_lock(root: Path) -> Any:
    lock_key = hashlib.sha256(str(root).encode("utf-8")).hexdigest()
    lock_path = Path(tempfile.gettempdir()) / "multi-agent-role-work-locks" / f"{lock_key}.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
    timeout = float(os.environ.get("SDLC_LOCK_TIMEOUT", "5"))
    deadline = time.monotonic() + max(timeout, 0)
    acquired = False
    try:
        while not acquired:
            try:
                if fcntl is not None:
                    fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
                elif msvcrt is not None:  # pragma: no cover - Windows only.
                    if os.fstat(descriptor).st_size == 0:
                        os.write(descriptor, b"\0")
                    os.lseek(descriptor, 0, os.SEEK_SET)
                    msvcrt.locking(descriptor, msvcrt.LK_NBLCK, 1)
                else:  # pragma: no cover - supported Python platforms provide one.
                    raise WorkflowError("No supported file-lock implementation is available.")
                acquired = True
            except (BlockingIOError, OSError):
                if time.monotonic() >= deadline:
                    raise WorkflowError(
                        "Another workflow update is in progress. Retry after it completes."
                    )
                time.sleep(0.05)
        yield
    finally:
        if acquired:
            if fcntl is not None:
                fcntl.flock(descriptor, fcntl.LOCK_UN)
            elif msvcrt is not None:  # pragma: no cover - Windows only.
                os.lseek(descriptor, 0, os.SEEK_SET)
                msvcrt.locking(descriptor, msvcrt.LK_UNLCK, 1)
        os.close(descriptor)


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
    migrate_state(root, state)
    validate_state(state, path)
    return path, state


def migrate_state(root: Path, state: dict[str, Any]) -> None:
    version = state.get("schema_version")
    if version == 1:
        state["schema_version"] = CURRENT_SCHEMA_VERSION
        state.setdefault("revision", 0)
        state.setdefault("human_approval_policy", {"required_gates": []})
        state.setdefault("human_approvals", {})
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
    if stage not in FLOWS[mode]:
        raise WorkflowError(f"Invalid workflow stage in {path}: {stage!r}")
    if workflow.get("status") not in {"active", "completed"}:
        raise WorkflowError(f"Invalid workflow status in {path}: {workflow.get('status')!r}")
    required_gates = state.get("human_approval_policy", {}).get("required_gates", [])
    if not isinstance(required_gates, list) or any(gate not in GATES for gate in required_gates):
        raise WorkflowError(f"Invalid human approval policy in {path}")
    for name in ("artifacts", "decisions", "human_approvals"):
        if not isinstance(state.get(name), dict):
            raise WorkflowError(f"Invalid {name} mapping in {path}")
    for name in ("issues", "meetings", "history"):
        if not isinstance(state.get(name), list):
            raise WorkflowError(f"Invalid {name} list in {path}")


def workflow_id_from_title(title: str) -> str:
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:32]
    if not slug:
        slug = "requirement"
    return f"REQ-{timestamp}-{slug}"


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


def gate_meeting_ready(root: Path, state: dict[str, Any], gate: str) -> bool:
    return current_gate_meeting(root, state, gate) is not None


def decision_is_current(root: Path, decision: dict[str, Any]) -> bool:
    return evidence_matches(
        root, str(decision.get("evidence", "")), decision.get("evidence_sha256")
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
    stages = FLOWS[mode]
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
    state["schema_version"] = CURRENT_SCHEMA_VERSION
    state["revision"] = expected_revision + 1
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
    previous = state.get("artifacts", {}).get(args.name, {})
    next_hash = content_sha256(absolute) if args.status == "ready" else None
    changed = bool(previous) and (
        previous.get("path") != str(relative)
        or previous.get("status") != args.status
        or previous.get("evidence_sha256") != next_hash
        or previous.get("notes", "") != (args.notes or "")
    )
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
        stages = FLOWS[state["workflow"]["mode"]]
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
    stages = FLOWS[workflow["mode"]]
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
            "record-artifact",
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
