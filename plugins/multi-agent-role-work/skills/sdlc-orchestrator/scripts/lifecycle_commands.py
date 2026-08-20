"""Workflow lifecycle, inspection, and stage-transition commands."""

from __future__ import annotations

from typing import Any

from command_runtime import invoke as invoke_bound


def invoke(name: str, api: Any, args: Any) -> Any:
    return invoke_bound(globals(), name, api, args)


def cmd_version(args: argparse.Namespace) -> int:
    identity = current_tool_identity(args.runtime_root)
    if args.json:
        print(json.dumps(identity, indent=2, ensure_ascii=False, sort_keys=True))
    else:
        print(f"{identity['plugin_name']} {identity['version']}")
        print(f"Payload: {identity['payload_sha256']}")
        print(f"Entry: {identity['entry_path']} ({identity['entry_sha256']})")
        print(f"Runtime: {identity['runtime_root']}")
    return 0


def cmd_doctor(args: argparse.Namespace) -> int:
    runtime_root = Path(args.runtime_root).expanduser().resolve()
    loaded_identity: dict[str, Any] | None = None
    if runtime_root == default_plugin_root().resolve():
        loaded_identity = current_tool_identity(runtime_root)
    try:
        report = doctor_runtime(
            runtime_root,
            source_root=args.source_root,
            entry_path=args.entry,
            loaded_version=(loaded_identity or {}).get("version"),
            loaded_payload_sha256=(loaded_identity or {}).get("payload_sha256"),
            loaded_entry_sha256=(loaded_identity or {}).get("entry_sha256"),
        )
    except ProvenanceError as exc:
        raise WorkflowError(f"Unable to diagnose the workflow runtime: {exc}") from exc
    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False, sort_keys=True))
    else:
        print(f"Runtime provenance: {report['status']}")
        print(report["message"])
        print(f"Runtime: {report['runtime']['runtime_root']}")
        if report.get("source"):
            print(f"Source: {report['source']['runtime_root']}")
    return doctor_exit_code(report)


def cmd_init(args: argparse.Namespace) -> None:
    root = repository_root(args.root)
    if args.force:
        raise WorkflowError(
            "--force is disabled because it could overwrite evidence or orphan an active workflow; "
            "deactivate or abandon the current workflow, then initialize a new ID."
        )

    workflow_id = args.id or workflow_id_from_title(args.title)
    validate_workflow_id(workflow_id)
    ensure_pointer_available(root, workflow_id)
    path = state_path(root, workflow_id)
    if path.exists():
        raise WorkflowError(
            f"Workflow already exists: {workflow_id}. Use activate or reopen; choose a new ID to start over."
        )

    docs_dir = root / "docs" / "requirements" / workflow_id
    docs_dir.mkdir(parents=True, exist_ok=True)
    request_path = docs_dir / "00-original-request.md"
    atomic_write_text(
        request_path,
        f"# Original request: {args.title}\n\n{args.request.strip()}\n",
    )
    timestamp = now()
    tool_identity = current_tool_identity()
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
        "work_items": {},
        "stage_submissions": {},
        "runtime_provenance": {
            "created_by_tool": dict(tool_identity),
            "last_mutated_by_tool": dict(tool_identity),
        },
        "history": [
            {"at": timestamp, "event": "initialized", "detail": f"Started {args.mode} workflow"}
        ],
    }
    save_state(path, state)
    claim_active_pointer(root, path, state)
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
    provenance = state.get("runtime_provenance", {})
    last_tool = provenance.get("last_mutated_by_tool", {})
    if last_tool:
        print(
            "Last mutated by tool: "
            f"{last_tool.get('plugin_name')} {last_tool.get('version')} "
            f"payload={last_tool.get('payload_sha256')}"
        )
        if runtime_identity_changed(last_tool, current_tool_identity()):
            print(
                "Runtime provenance warning: the loaded tool identity differs from the "
                "last recorded mutator; run doctor."
            )
    else:
        print("Last mutated by tool: unavailable (legacy workflow state)")
    required_human = state.get("human_approval_policy", {}).get("required_gates", [])
    print("Human approval gates: " + (",".join(required_human) if required_human else "none"))
    missing, notes = stage_requirements(root, state)
    print("Can advance: " + ("yes" if not missing and workflow["status"] == "active" else "no"))
    for item in missing:
        print(f"- {item}")
    for item in notes:
        print(f"- note:{item}")


def _validated_state_copy(
    root: Path,
    path: Path,
    raw: dict[str, Any],
) -> dict[str, Any]:
    candidate = json.loads(json.dumps(raw))
    verify_state_checksum(candidate, path, CURRENT_SCHEMA_VERSION)
    migrate_state(root, candidate)
    validate_state(candidate, path)
    return candidate


def _other_valid_live_states(
    root: Path,
    target_path: Path,
) -> list[tuple[Path, dict[str, Any]]]:
    live: list[tuple[Path, dict[str, Any]]] = []
    for candidate_path in sorted((root / ".ai-workflow").glob("*/state.yaml")):
        if candidate_path.resolve() == target_path.resolve():
            continue
        try:
            raw = load_data(candidate_path)
            candidate = _validated_state_copy(root, candidate_path, raw)
        except (WorkflowError, KeyError, TypeError, ValueError) as exc:
            raise WorkflowError(
                "Cannot prove active-pointer safety while another workflow state is "
                f"invalid: {candidate_path.relative_to(root)} ({exc})"
            ) from exc
        if candidate["workflow"]["status"] in LIVE_POINTER_STATUSES:
            live.append((candidate_path.resolve(), candidate))
    return live


def _repair_routing_preflight(
    root: Path,
    path: Path,
    restored: dict[str, Any],
) -> tuple[list[tuple[Path, dict[str, Any]]], int]:
    workflow_id = str(restored["workflow"].get("id", ""))
    if workflow_id != path.parent.name or path.resolve() != state_path(root, workflow_id).resolve():
        raise WorkflowError(
            "Backup workflow identity does not match the state path selected for repair."
        )

    other_live = _other_valid_live_states(root, path)
    if len(other_live) > 1:
        owners = ", ".join(item[1]["workflow"]["id"] for item in other_live)
        raise WorkflowError(
            "Cannot repair while multiple other live workflows exist: " + owners
        )

    pointer_owner: str | None = None
    pointer_revision = int(restored.get("revision", 0))
    pointer = active_pointer(root)
    if pointer.exists():
        try:
            pointer_data = load_data(pointer)
            resolve_pointer_path(root, pointer_data)
            pointer_owner = str(pointer_data.get("workflow_id", ""))
        except WorkflowError as exc:
            raise WorkflowError(
                "Cannot repair while the active pointer is invalid; repair routing first."
            ) from exc
        if pointer_owner == workflow_id:
            recorded_revision = pointer_data.get("state_revision")
            if type(recorded_revision) is not int or recorded_revision < 0:
                raise WorkflowError(
                    "Cannot repair because the active pointer has an invalid state revision."
                )
            pointer_revision = max(pointer_revision, recorded_revision)
            pointer_status = pointer_data.get("status")
            if pointer_status != restored["workflow"]["status"]:
                raise WorkflowError(
                    "Cannot repair because backup lifecycle status conflicts with the "
                    "active pointer status."
                )

    restored_is_live = restored["workflow"]["status"] in LIVE_POINTER_STATUSES
    other_owner = (
        str(other_live[0][1]["workflow"]["id"])
        if other_live
        else None
    )
    if restored_is_live:
        if other_owner:
            raise WorkflowError(
                f"Cannot restore live workflow {workflow_id}; workflow {other_owner} is already live."
            )
        if pointer_owner not in {None, workflow_id}:
            raise WorkflowError(
                f"Cannot restore live workflow {workflow_id}; active pointer belongs to {pointer_owner}."
            )
    elif pointer_owner not in {None, workflow_id, other_owner}:
        raise WorkflowError(
            f"Active pointer owner {pointer_owner} is inconsistent with persisted workflow state."
        )
    elif pointer_owner not in {None, workflow_id} and pointer_owner != other_owner:
        raise WorkflowError(
            f"Active pointer owner {pointer_owner} does not match the only live workflow."
        )
    return other_live, pointer_revision


def cmd_audit_state(args: argparse.Namespace) -> None:
    root = repository_root(args.root)
    path = state_path(root, args.id)
    parse_error = ""
    integrity_error = ""
    state_valid = False
    try:
        raw = load_data(path)
    except WorkflowError as exc:
        raw = {}
        parse_error = str(exc)
    else:
        try:
            _validated_state_copy(root, path, raw)
            state_valid = True
        except (WorkflowError, KeyError, TypeError, ValueError) as exc:
            integrity_error = str(exc)
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
        "integrity_error": integrity_error or None,
        "schema_version": raw.get("schema_version"),
        "revision": raw.get("revision"),
        "state_valid": state_valid,
        "checksum_valid": checksum_valid,
        "expected_checksum": expected,
        "actual_checksum": actual,
        "backup_path": str(backup_path.relative_to(root)),
        "backup_exists": backup_path.exists(),
        "backup_valid": backup_valid,
        "backup_revision": backup_revision,
        "repair_available": not state_valid and backup_valid,
    }
    if args.json:
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        return
    print(f"State: {payload['path']}")
    if parse_error:
        print(f"Parse error: {parse_error}")
    if integrity_error:
        print(f"Integrity error: {integrity_error}")
    print(f"State: {'valid' if state_valid else 'INVALID'}")
    print(f"Checksum: {'valid' if checksum_valid else 'INVALID'}")
    print(
        "Backup: "
        + (
            f"valid revision {backup_revision}"
            if backup_valid
            else ("invalid" if backup_path.exists() else "not available yet")
        )
    )
    if not state_valid and backup_valid:
        print("Recovery: run repair-state --from-backup --confirm RESTORE")


def cmd_repair_state(args: argparse.Namespace) -> None:
    if args.confirm != "RESTORE":
        raise WorkflowError("State repair requires --confirm RESTORE.")
    root = repository_root(args.root)
    path = state_path(root, args.id)
    current_raw: dict[str, Any] = {}
    try:
        current_raw = load_data(path)
        _validated_state_copy(root, path, current_raw)
    except (WorkflowError, KeyError, TypeError, ValueError):
        pass
    else:
        status = current_raw.get("workflow", {}).get("status", "unknown")
        raise WorkflowError(
            "Current workflow state is valid "
            f"({status}); repair-state cannot be used to roll back valid state."
        )

    backup_path = path.with_name("state.backup.yaml")
    try:
        backup_raw = load_data(backup_path)
        backup = _validated_state_copy(root, backup_path, backup_raw)
    except (WorkflowError, KeyError, TypeError, ValueError) as exc:
        raise WorkflowError(f"State backup is not valid for recovery: {exc}") from exc

    restored = json.loads(json.dumps(backup))
    other_live, trusted_revision = _repair_routing_preflight(root, path, restored)
    restored["revision"] = trusted_revision + 1
    add_history(restored, "state_restored", f"Restored from {backup_path.name}")
    tool_identity = current_tool_identity()
    provenance = restored.setdefault("runtime_provenance", {})
    if not isinstance(provenance.get("created_by_tool"), dict):
        provenance["created_by_tool"] = dict(tool_identity)
    provenance["last_mutated_by_tool"] = dict(tool_identity)
    restored["state_checksum"] = state_checksum(restored)
    validate_state(restored, path)
    save_data(path, restored)

    workflow_id = str(restored["workflow"]["id"])
    if restored["workflow"]["status"] in LIVE_POINTER_STATUSES:
        claim_active_pointer(root, path, restored)
    else:
        release_active_pointer(root, workflow_id)
        if other_live:
            claim_active_pointer(root, other_live[0][0], other_live[0][1])
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
    ensure_pointer_available(root, workflow["id"])
    workflow["status"] = "active"
    workflow.pop("paused_at", None)
    workflow.pop("pause_reason", None)
    add_history(state, "resumed", f"Resumed at {workflow['current_stage']}")
    save_state(path, state)
    claim_active_pointer(root, path, state)
    print(f"Resumed workflow {workflow['id']} at {workflow['current_stage']}")


def cmd_activate(args: argparse.Namespace) -> None:
    root = repository_root(args.root)
    if not args.id:
        raise WorkflowError("activate requires an explicit --id.")
    path, state = load_state(root, args.id)
    workflow = state["workflow"]
    health, _ = active_pointer_health(root, state)
    if workflow["status"] == "active" and health == "current":
        raise WorkflowError(f"Workflow {workflow['id']} is already active.")
    if workflow["status"] not in {"active", "inactive"}:
        action = "resume" if workflow["status"] == "paused" else "reopen"
        raise WorkflowError(f"Workflow status is {workflow['status']}; use {action} instead.")
    ensure_pointer_available(root, workflow["id"])
    workflow["status"] = "active"
    workflow.pop("deactivated_at", None)
    workflow.pop("deactivation_reason", None)
    add_history(state, "activated", f"Activated at {workflow['current_stage']}")
    save_state(path, state)
    claim_active_pointer(root, path, state)
    print(f"Activated workflow {workflow['id']} at {workflow['current_stage']}")


def cmd_deactivate(args: argparse.Namespace) -> None:
    root = repository_root(args.root)
    path, state = load_state(root, args.id)
    workflow = state["workflow"]
    if workflow["status"] not in LIVE_POINTER_STATUSES:
        raise WorkflowError(f"Workflow status is {workflow['status']}, not active or paused.")
    prior = workflow["status"]
    workflow["status"] = "inactive"
    workflow["deactivated_at"] = now()
    workflow["deactivation_reason"] = args.reason.strip()
    workflow.pop("paused_at", None)
    workflow.pop("pause_reason", None)
    add_history(state, "deactivated", f"{prior}:{args.reason.strip()}")
    save_state(path, state)
    print(f"Deactivated workflow {workflow['id']} at {workflow['current_stage']}")


def cmd_abandon(args: argparse.Namespace) -> None:
    root = repository_root(args.root)
    path, state = load_state(root, args.id)
    workflow = state["workflow"]
    if workflow["status"] in TERMINAL_WORKFLOW_STATUSES:
        raise WorkflowError(f"Workflow status is already {workflow['status']}.")
    workflow["status"] = "abandoned"
    workflow["abandoned_at"] = now()
    workflow["abandon_reason"] = args.reason.strip()
    for key in ("paused_at", "pause_reason", "deactivated_at", "deactivation_reason"):
        workflow.pop(key, None)
    add_history(state, "abandoned", args.reason.strip())
    save_state(path, state)
    print(f"Abandoned workflow {workflow['id']} at {workflow['current_stage']}")


def cmd_list(args: argparse.Namespace) -> None:
    root = repository_root(args.root)
    pointer_owner = None
    if active_pointer(root).exists():
        pointer_owner = load_data(active_pointer(root)).get("workflow_id")
    workflows: list[dict[str, Any]] = []
    for path in sorted((root / ".ai-workflow").glob("*/state.yaml")):
        workflow_id = path.parent.name
        try:
            _, state = load_state(root, workflow_id)
            workflow = state["workflow"]
            workflows.append(
                {
                    "workflow_id": workflow["id"],
                    "title": workflow["title"],
                    "mode": workflow["mode"],
                    "status": workflow["status"],
                    "stage": workflow["current_stage"],
                    "revision": state["revision"],
                    "is_active_pointer": workflow["id"] == pointer_owner,
                }
            )
        except WorkflowError as exc:
            workflows.append({"workflow_id": workflow_id, "status": "invalid", "error": str(exc)})
    payload = {"active_workflow_id": pointer_owner, "workflows": workflows}
    if args.json:
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        return
    print("Active workflow: " + (str(pointer_owner) if pointer_owner else "none"))
    for item in workflows:
        if item["status"] == "invalid":
            print(f"- {item['workflow_id']} invalid: {item['error']}")
        else:
            marker = " *" if item["is_active_pointer"] else ""
            print(f"- {item['workflow_id']} {item['status']} {item['stage']}{marker}")


def cmd_next(args: argparse.Namespace) -> None:
    root = repository_root(args.root)
    _, state = load_state(root, args.id)
    payload = overview_payload(root, state)
    stage = payload["stage"]
    if payload["status"] != "active":
        print(f"Workflow is {payload['status']} at {stage}. {payload['next_action']}")
        if payload["stage_missing_after_resume"]:
            print("Required at this stage after activation:")
            for item in payload["stage_missing_after_resume"]:
                print(f"- {item}")
        return
    print(f"Current stage: {stage}")
    if payload["missing"]:
        print("Required before advancing:")
        for item in payload["missing"]:
            print(f"- {item}")
    else:
        print(f"Ready to advance to: {payload['next_stage']}")
    for item in payload["notes"]:
        print(f"Note: {item}")


def cmd_advance(args: argparse.Namespace) -> None:
    root = repository_root(args.root)
    path, state = load_state(root, args.id)
    workflow = state["workflow"]
    if workflow["status"] != "active":
        raise WorkflowError(f"Workflow status is {workflow['status']}, not active.")
    stage = workflow["current_stage"]
    if stage == "completed":
        raise WorkflowError("Workflow is already complete.")
    active_work_items: list[str] = []
    for work_item_id, raw_item in state.get("work_items", {}).items():
        try:
            item = validate_work_item(raw_item)
        except WorkItemError as exc:
            raise WorkflowError(f"Invalid work item {work_item_id}: {exc}") from exc
        if item["stage"] == stage and item["status"] in {"dispatched", "running"}:
            active_work_items.append(str(work_item_id))
    if active_work_items:
        raise WorkflowError(
            "Gate blocked: active_work_items:" + ",".join(sorted(active_work_items))
        )
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
        workflow["completed_at"] = now()
    add_history(state, "advanced", f"{stage}->{new_stage}")
    save_state(path, state)
    print(f"Advanced {stage} -> {new_stage}")


def cmd_reopen(args: argparse.Namespace) -> None:
    root = repository_root(args.root)
    path, state = load_state(root, args.id)
    workflow = state["workflow"]
    if workflow["status"] not in {"active", "completed", "abandoned"}:
        action = "resume" if workflow["status"] == "paused" else "activate"
        raise WorkflowError(f"Workflow status is {workflow['status']}; use {action} first.")
    ensure_pointer_available(root, workflow["id"])
    old_stage, invalidated_artifacts, invalidated_meetings = rewind_workflow(
        state, args.stage, f"Workflow reopened at {args.stage}"
    )
    add_history(state, "reopened", f"{old_stage}->{args.stage}:{args.reason}")
    if invalidated_artifacts:
        add_history(state, "artifacts_invalidated", ",".join(invalidated_artifacts))
    if invalidated_meetings:
        add_history(state, "meetings_invalidated", ",".join(invalidated_meetings))
    save_state(path, state)
    claim_active_pointer(root, path, state)
    print(f"Reopened workflow at {args.stage}")
