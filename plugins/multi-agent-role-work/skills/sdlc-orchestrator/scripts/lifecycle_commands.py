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

    version_control = ensure_git_repository(root)
    language = communication_language(args.request)
    docs_dir = root / "docs" / "requirements" / workflow_id
    docs_dir.mkdir(parents=True, exist_ok=True)
    request_path = docs_dir / "00-original-request.md"
    request_heading = "原始需求" if language == "zh-CN" else "Original request"
    atomic_write_text(
        request_path,
        f"# {request_heading}：{args.title}\n\n{args.request.strip()}\n",
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
        "requirement_confirmation_records": [],
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
        "repository_context": {**repository_context(root), **version_control},
        "user_preferences": {"language": language},
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
    if not getattr(args, "quiet", False):
        print(f"Initialized {workflow_id} in {args.mode} mode")
        print(f"State: {path.relative_to(root)}")
        print(f"Artifacts: {docs_dir.relative_to(root)}")


def cmd_start(args: argparse.Namespace) -> None:
    if not getattr(args, "title", None):
        args.title = title_from_request(args.request)
    args.quiet = True
    cmd_init(args)
    root = repository_root(args.root)
    _, state = load_state(root, getattr(args, "id", None))
    print()
    print("Project:")
    print_project_view(project_view_payload(root, state))


def cmd_prepare_turn(args: argparse.Namespace) -> int:
    root = repository_root(args.root)
    path, state = load_state(root, args.id)
    workflow = state["workflow"]
    if workflow["status"] != "active":
        raise WorkflowError(
            f"Workflow status is {workflow['status']}; prepare-turn requires an active project."
        )

    changed_paths = source_activity_after_state(root, state)
    version_control = ensure_git_repository(root)
    current_identity = current_tool_identity()
    previous_identity = state.get("runtime_provenance", {}).get("last_mutated_by_tool", {})
    payload: dict[str, Any] = {
        "workflow_id": workflow["id"],
        "status": "reconciliation_required" if changed_paths else "ready",
        "stage": workflow["current_stage"],
        "version_control": version_control,
        "runtime_changed": bool(
            previous_identity and runtime_identity_changed(previous_identity, current_identity)
        ),
        "unrecorded_source_paths": changed_paths,
    }
    if changed_paths:
        payload["message"] = (
            "Source files changed after the last workflow state update without an active role "
            "attempt. Reconcile or reopen the earliest affected stage before more product work."
        )
        if args.json:
            print(json.dumps(payload, indent=2, ensure_ascii=False))
        else:
            print("Project continuity: reconciliation required")
            print(payload["message"])
            for item in changed_paths:
                print(f"- {item}")
        return 2

    observed_context = {
        **state.get("repository_context", {}),
        **repository_context(root),
        **version_control,
        **continuity_snapshot(root),
    }
    state_changed = observed_context != state.get("repository_context", {}) or payload["runtime_changed"]
    if state_changed:
        state["repository_context"] = observed_context
        details: list[str] = []
        if payload["runtime_changed"]:
            details.append(
                f"runtime {previous_identity.get('version', 'unknown')} -> {current_identity['version']}"
            )
        if version_control.get("version_control_status") == "initialized":
            details.append("initialized Git protection")
        add_history(state, "turn_prepared", "; ".join(details) or "refreshed project continuity")
        save_state(path, state)
        payload["state_revision"] = state["revision"]
    else:
        payload["state_revision"] = state["revision"]
    payload["message"] = "Project continuity checks passed."
    if args.json:
        print(json.dumps(payload, indent=2, ensure_ascii=False))
    else:
        print("Project continuity: ready")
        print(f"Version protection: {version_control.get('version_control', 'unavailable')}")
        print(f"Workflow stage: {workflow['current_stage']}")
    return 0


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


PROJECT_FOCUS = {
    "intake": "正在理解你的目标和项目背景",
    "scope_check": "正在梳理范围、验收结果和潜在风险",
    "clarification": "正在确认会影响最终结果的关键细节",
    "requirement_confirmation": "已整理目标和范围，准备与你确认",
    "prd": "正在把目标转化为清晰的产品方案",
    "prd_review": "正在检查产品方案是否完整、可实现、可验证",
    "design": "正在制定实现方案和质量检查计划",
    "readiness_review": "正在做开发前的风险和可执行性检查",
    "prototype": "正在准备可体验的第一版",
    "user_feedback": "第一版已可体验，正在等待你的方向判断",
    "implementation": "正在开发已确认的功能",
    "verification": "正在运行检查、定位问题并确认核心流程",
    "acceptance": "正在做交付前的最终质量复核",
    "delivery_confirmation": "结果已经验证，等待你体验确认",
    "completed": "本次目标已经完成",
}

PROJECT_RESULT_LABELS = {
    "clarification_questions": "关键需求问题已梳理",
    "requirement_confirmation": "目标和范围已确认",
    "core_goals": "核心目标已锁定",
    "prd": "产品方案已完成",
    "technical_design": "实现方案已完成",
    "database_design": "数据方案已完成",
    "test_plan": "质量检查计划已完成",
    "test_cases": "测试场景已准备",
    "prototype": "可体验预览已准备",
    "user_feedback": "预览方向已确认",
    "implementation": "功能实现已完成",
    "verification_report": "自动检查已完成",
    "journey_report": "核心用户流程已验证",
    "release_plan": "交付方案已完成",
    "delivery_report": "交付结果已整理",
    "delivery_confirmation": "交付结果已确认",
}

PROJECT_ACTION_LABELS = {
    "prototype": ("查看方向预览（不代表核心功能已完成）", "preview"),
    "implementation": ("查看实现结果", "implementation"),
    "verification_report": ("查看质量报告", "quality_report"),
    "journey_report": ("查看核心流程验证", "journey_report"),
    "delivery_report": ("查看交付结果", "delivery_report"),
}


def _project_goal(state: dict[str, Any]) -> str:
    goals = state.get("core_goals", {})
    descriptions = [
        str(item.get("description", "")).strip()
        for item in goals.values()
        if isinstance(item, dict) and str(item.get("description", "")).strip()
    ]
    if descriptions:
        return "；".join(descriptions)
    baseline = state.get("risk_assessment", {}).get("baseline", {})
    scope = str(baseline.get("scope", "")).strip()
    return scope or str(state["workflow"]["title"])


def _recent_project_results(root: Path, state: dict[str, Any]) -> list[str]:
    ready = set(completed_artifacts(root, state))
    candidates: list[tuple[str, str]] = []
    for name, label in PROJECT_RESULT_LABELS.items():
        if name not in ready:
            continue
        artifact = state.get("artifacts", {}).get(name, {})
        candidates.append((str(artifact.get("updated_at", "")), label))
    candidates.sort(reverse=True)
    return [label for _, label in candidates[:4]]


def _core_project_results(root: Path, state: dict[str, Any]) -> list[dict[str, str]]:
    workflow = state["workflow"]
    stage = workflow["current_stage"]
    stages = workflow_stages(state)
    implementation_ready = artifact_ready(root, state, "implementation")
    verification_ready = artifact_ready(root, state, "verification_report")

    def pending_status() -> str:
        if workflow["status"] == "completed":
            return "已完成"
        if verification_ready:
            return "已通过检查，待最终确认"
        if implementation_ready:
            return "等待验证"
        if "implementation" in stages and stages.index(stage) >= stages.index("implementation"):
            return "开发中"
        if state.get("risk_assessment", {}).get("status") == "current":
            return "已定义，等待开发"
        return "正在定义"

    goals = state.get("core_goals", {})
    outcomes = state.get("core_outcomes", {})
    if goals:
        result: list[dict[str, str]] = []
        outcome_labels = {
            "satisfied": "已实现并验证",
            "deferred": "已延期",
            "not_applicable": "已调整",
        }
        for goal_id, goal in goals.items():
            verdict = str(outcomes.get(goal_id, {}).get("verdict", ""))
            result.append(
                {
                    "id": str(goal_id),
                    "description": str(goal.get("description", "")).strip(),
                    "status": outcome_labels.get(verdict, pending_status()),
                }
            )
        return result

    baseline = state.get("risk_assessment", {}).get("baseline", {})
    description = str(baseline.get("acceptance", "")).strip() or _project_goal(state)
    return [{"id": "RESULT-001", "description": description, "status": pending_status()}]


def _project_actions(root: Path, state: dict[str, Any]) -> list[dict[str, str]]:
    actions: list[tuple[str, dict[str, str]]] = []
    for artifact_name, (label, kind) in PROJECT_ACTION_LABELS.items():
        if not artifact_ready(root, state, artifact_name):
            continue
        artifact = state.get("artifacts", {}).get(artifact_name, {})
        target = str(artifact.get("path", "")).strip()
        if not target:
            continue
        actions.append(
            (
                str(artifact.get("updated_at", "")),
                {"label": label, "kind": kind, "target": target},
            )
        )
    actions.sort(key=lambda item: item[0], reverse=True)
    return [action for _, action in actions[:4]]


def _resolved_project_issues(state: dict[str, Any]) -> list[dict[str, str]]:
    resolved: list[tuple[str, dict[str, str]]] = []
    for issue in state.get("issues", []):
        if issue.get("status") != "resolved":
            continue
        resolution_evidence = str(issue.get("resolution_evidence", ""))
        if "/_archive/" in resolution_evidence:
            continue
        resolved.append(
            (
                str(issue.get("resolved_at", "")),
                {
                    "problem": str(issue.get("summary", "")).strip(),
                    "resolution": str(issue.get("resolution", "")).strip(),
                },
            )
        )
    resolved.sort(key=lambda item: item[0], reverse=True)
    return [issue for _, issue in resolved[:3]]


def _project_decisions(root: Path, state: dict[str, Any]) -> list[str]:
    workflow = state["workflow"]
    stage = workflow["current_stage"]
    decisions: list[str] = []
    escalation = state.get("escalation", {})
    if escalation.get("status") == "required":
        decisions.append("发现了会影响交付可靠性的风险，需要你决定是否提高保障级别。")

    risk = state.get("risk_assessment", {})
    if stage in {"scope_check", "clarification"}:
        decisions.extend(
            str(gap).strip()
            for gap in risk.get("gaps", [])
            if str(gap).strip()
        )

    if stage == "requirement_confirmation" and not artifact_ready(
        root, state, "requirement_confirmation"
    ):
        decisions.append("请确认我理解的目标、范围和完成标准是否正确。")
    elif stage == "user_feedback" and not artifact_ready(root, state, "user_feedback"):
        decisions.append("请体验当前预览，并告诉我整体方向是否符合预期。")
    elif stage == "delivery_confirmation" and not artifact_ready(
        root, state, "delivery_confirmation"
    ):
        decisions.append("请体验已经验证的结果，并确认它是否达到了本次目标。")

    missing, _ = stage_requirements(root, state)
    if any(item.startswith("human_approval:") for item in missing):
        decisions.append("当前操作影响较大，需要你的明确授权后才能继续。")
    decisions.extend(
        str(issue.get("summary", "")).strip()
        for issue in outstanding_issues(state)
        if issue.get("owner") == "user" and str(issue.get("summary", "")).strip()
    )
    return list(dict.fromkeys(decisions))


def _journey_passed(state: dict[str, Any]) -> bool:
    journey = state.get("journey_validation", {})
    checks = journey.get("checks", {})
    required = JOURNEY_PROFILES.get(str(journey.get("profile", "")), ())
    return bool(required) and all(checks.get(check) == "pass" for check in required)


def _project_quality(root: Path, state: dict[str, Any]) -> dict[str, Any]:
    issues = outstanding_issues(state)
    blockers = [
        item for item in issues if item.get("severity") in {"blocker", "major"}
    ]
    criteria = state.get("acceptance_criteria", {})
    verdicts = state.get("criterion_verdicts", {})
    passed = sum(
        1
        for criterion_id in criteria
        if verdicts.get(criterion_id, {}).get("verdict") in {"pass", "not_applicable"}
    )
    journey_checks = state.get("journey_validation", {}).get("checks", {})
    journey_passed = _journey_passed(state)
    verification_ready = artifact_ready(root, state, "verification_report")
    if blockers:
        summary = f"发现 {len(blockers)} 个需要先处理的重要问题"
    elif journey_passed:
        summary = "核心用户流程已通过验证"
    elif verification_ready:
        summary = "已完成当前版本检查，未发现阻塞交付的问题"
    else:
        summary = "最终质量检查尚未完成"
    details: list[str] = []
    if criteria:
        details.append(f"已通过 {passed}/{len(criteria)} 项明确完成标准")
    if journey_checks:
        passed_journey_checks = sum(
            1 for result in journey_checks.values() if result in {"pass", "not_applicable"}
        )
        details.append(
            f"核心流程检查 {passed_journey_checks}/{len(journey_checks)} 项通过"
        )
    if blockers:
        details.append(f"仍有 {len(blockers)} 个重要问题待处理")
    return {
        "summary": summary,
        "details": details,
        "acceptance_checks_passed": passed,
        "acceptance_checks_total": len(criteria),
        "open_important_issues": len(blockers),
        "core_journey_passed": journey_passed,
    }


def _project_alignment(
    root: Path, state: dict[str, Any], decisions: list[str]
) -> dict[str, Any]:
    """Explain goal drift protection without exposing the internal delivery model."""
    workflow = state["workflow"]
    risk_status = state.get("risk_assessment", {}).get("status")
    important_issues = [
        item
        for item in outstanding_issues(state)
        if item.get("severity") in {"blocker", "major"}
    ]
    scope_changes = [
        item
        for item in state.get("scope_changes", [])
        if item.get("status") == "approved"
    ]

    stage = workflow["current_stage"]
    journey_passed = _journey_passed(state)
    verification_ready = artifact_ready(root, state, "verification_report")
    delivery_confirmed = artifact_ready(root, state, "delivery_confirmation")
    completion_verified = (
        journey_passed
        if workflow["mode"] == "strict"
        else verification_ready and delivery_confirmed
    )

    if workflow["status"] == "completed" and completion_verified:
        status = "completed"
        label = "已按目标完成"
        summary = "最终结果已经按记录的目标和完成标准核对。"
    elif workflow["status"] == "completed":
        status = "attention"
        label = "缺少真实结果核验"
        summary = "流程记录已经结束，但缺少完整的真实用户路径证据，不能宣称核心目标已兑现。"
    elif risk_status != "current":
        status = "defining"
        label = "正在确认方向"
        summary = "目标和边界仍在梳理，尚未把不确定内容当成已确认工作。"
    elif state.get("escalation", {}).get("status") == "required" or important_issues:
        status = "attention"
        label = "发现偏离风险"
        summary = "可能影响目标的事项已被拦下，处理或确认前不会继续推进。"
    elif decisions:
        status = "confirmation_needed"
        label = "等待你的方向确认"
        summary = "有一项决定可能影响最终结果，确认前不会替你改变目标。"
    elif scope_changes:
        latest = max(scope_changes, key=lambda item: str(item.get("approved_at", "")))
        reason = str(latest.get("reason", "")).strip()
        status = "realigned"
        label = "已重新对齐"
        summary = (
            f"已根据你确认的变化调整后续工作：{reason}"
            if reason
            else "已根据你确认的变化重新调整后续工作。"
        )
    elif stage in {"prototype", "user_feedback"}:
        status = "on_track"
        label = "方向预览中"
        summary = "当前成果只用于判断产品方向，尚不能证明核心功能已经实现。"
    elif stage == "implementation":
        status = "on_track"
        label = "实现中，等待验证"
        summary = "当前实现围绕目标推进，但核心价值仍需通过真实用户路径验证。"
    elif stage in {"verification", "acceptance", "delivery_confirmation"}:
        status = "on_track"
        label = "正在核对真实结果"
        summary = "正在用实际启动路径和核心用户任务检查成果是否真正兑现目标。"
    else:
        status = "on_track"
        label = "与目标一致"
        summary = "当前工作仍围绕已记录的目标和完成标准推进。"

    return {
        "status": status,
        "label": label,
        "summary": summary,
        "protection": "发现目标、范围或完成标准发生变化时，会先向你说明并确认。",
    }


def project_view_payload(root: Path, state: dict[str, Any]) -> dict[str, Any]:
    workflow = state["workflow"]
    stage = workflow["current_stage"]
    decisions = _project_decisions(root, state)
    baseline = state.get("risk_assessment", {}).get("baseline", {})
    if workflow["status"] == "completed":
        next_action = "本次目标已完成，可以继续提出调整或新的目标。"
    elif workflow["status"] == "paused":
        next_action = "项目已暂停；需要继续时告诉我即可。"
    elif workflow["status"] == "inactive":
        next_action = "项目当前未激活；明确告诉我继续这个项目即可恢复。"
    elif workflow["status"] == "abandoned":
        next_action = "这个项目已结束；如需恢复，需要明确重新开启。"
    elif decisions:
        next_action = "等待你的决定后继续推进。"
    else:
        next_action = "我会继续推进，并在出现可体验结果或需要你判断时更新你。"
    repository = state.get("repository_context", {})
    version_control = repository.get("version_control")
    if version_control == "git":
        if repository.get("git_baseline_status") == "missing":
            version_protection = {
                "status": "initialized_without_baseline",
                "summary": "Git 已初始化，但尚无基线提交；现有内容暂时不能通过版本历史恢复。",
            }
        else:
            version_protection = {
                "status": "enabled",
                "summary": "Git 版本保护已开启；不会自动覆盖现有分支、远程地址或未提交改动。",
            }
    else:
        version_protection = {
            "status": "unavailable",
            "summary": "Git 版本保护尚未开启，需要先解决本机 Git 环境问题。",
        }
    recent_results = _recent_project_results(root, state)
    stage_summary = {
        "completed": recent_results[:3] or ["已记录项目目标"],
        "current": PROJECT_FOCUS.get(stage, "正在推进当前工作"),
        "decision": decisions[0] if decisions else None,
    }
    return {
        "project_id": workflow["id"],
        "title": workflow["title"],
        "goal": _project_goal(state),
        "alignment": _project_alignment(root, state, decisions),
        "out_of_scope": str(baseline.get("out_of_scope", "")).strip() or None,
        "acceptance": str(baseline.get("acceptance", "")).strip() or None,
        "current_focus": PROJECT_FOCUS.get(stage, "正在推进当前工作"),
        "core_results": _core_project_results(root, state),
        "recent_results": recent_results,
        "stage_summary": stage_summary,
        "version_protection": version_protection,
        "available_actions": _project_actions(root, state),
        "resolved_issues": _resolved_project_issues(state),
        "quality": _project_quality(root, state),
        "needs_your_decision": decisions,
        "next_action": next_action,
        "updated_at": workflow.get("updated_at"),
    }


def print_project_view(payload: dict[str, Any]) -> None:
    print("Project Compass")
    print("项目守航已开启")
    print(f"{payload['title']}")
    print(f"目标：{payload['goal']}")
    alignment = payload["alignment"]
    print(f"项目方向：[{alignment['label']}] {alignment['summary']}")
    print(f"目标保护：{alignment['protection']}")
    print(f"版本保护：{payload['version_protection']['summary']}")
    if payload.get("out_of_scope"):
        print(f"暂不包含：{payload['out_of_scope']}")
    if payload.get("acceptance"):
        print(f"完成标准：{payload['acceptance']}")
    print(f"当前：{payload['current_focus']}")
    print("核心结果：")
    for result in payload["core_results"]:
        print(f"- [{result['status']}] {result['description']}")
    if payload["recent_results"]:
        print("最近完成：")
        for result in payload["recent_results"]:
            print(f"- {result}")
    else:
        print("最近完成：已记录初始目标")
    if payload["available_actions"]:
        print("可查看成果：")
        for action in payload["available_actions"]:
            print(f"- {action['label']}：{action['target']}")
    if payload["resolved_issues"]:
        print("已解决问题：")
        for issue in payload["resolved_issues"]:
            print(f"- {issue['problem']} → {issue['resolution']}")
    print(f"质量：{payload['quality']['summary']}")
    for detail in payload["quality"]["details"]:
        print(f"- {detail}")
    if payload["needs_your_decision"]:
        print("是否需要你操作：是")
        print("需要你决定：")
        for decision in payload["needs_your_decision"]:
            print(f"- {decision}")
    else:
        print("是否需要你操作：否，系统会继续推进")
        print("需要你决定：暂无")
    print(f"下一步：{payload['next_action']}")


def cmd_project(args: argparse.Namespace) -> None:
    root = repository_root(args.root)
    _, state = load_state(root, args.id)
    payload = project_view_payload(root, state)
    if args.json:
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        return
    print_project_view(payload)


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
