"""Protected baselines, scope changes, and strict verification commands."""

from __future__ import annotations

from typing import Any

from command_runtime import invoke as invoke_bound


def invoke(name: str, api: Any, args: Any) -> Any:
    return invoke_bound(globals(), name, api, args)


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
    current = current_source_fingerprint(
        root,
        tuple(source.get("scope_paths", [])),
        tuple(source.get("ignored_paths", [])),
    )
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
    ignored_paths = tuple(
        str(item) for item in source_spec.get("ignore_paths", []) if str(item).strip()
    )
    source_evidence, source_relative, source_hash = indexed_document(
        root, str(source_spec.get("evidence", ""))
    )
    del source_evidence
    build_command = str(source_spec.get("build_command", "")).strip()
    test_command = str(source_spec.get("test_command", "")).strip()
    if not build_command or not test_command:
        raise WorkflowError("Verification manifest source requires build_command and test_command.")
    current = current_source_fingerprint(root, scope_paths, ignored_paths)
    if current["dirty_paths"]:
        raise WorkflowError(
            "Commit the scoped source under verification first: "
            + ",".join(current["dirty_paths"])
        )

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

    execution = execute_verification_commands(
        root,
        state,
        (("build", build_command), ("test", test_command)),
        parse_verification_timeout(source_spec.get("command_timeout", 300)),
        scope_paths=scope_paths,
        ignored_paths=ignored_paths,
    )
    after_execution = current_source_fingerprint(root, scope_paths, ignored_paths)
    if after_execution["dirty_paths"] or any(
        after_execution.get(key) != current.get(key)
        for key in ("git_head", "source_tree_sha256")
    ):
        raise WorkflowError(
            "Verification commands changed the scoped source; restore or commit intentionally, "
            "then rerun verification."
        )
    current = after_execution
    timestamp = now()
    state["source_revision"] = {
        **current,
        "evidence": str(source_relative),
        "evidence_sha256": source_hash,
        "build_command": build_command,
        "test_command": test_command,
        "test_execution": execution,
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
    current = current_source_fingerprint(
        root,
        tuple(args.source_path or ()),
        tuple(args.ignore_source_path or ()),
    )
    if current["dirty_paths"]:
        raise WorkflowError(
            "Commit the exact source under verification first: " + ",".join(current["dirty_paths"])
        )
    execution = execute_verification_commands(
        root,
        state,
        (("build", args.build_command), ("test", args.test_command)),
        scope_paths=tuple(args.source_path or ()),
        ignored_paths=tuple(args.ignore_source_path or ()),
    )
    after_execution = current_source_fingerprint(
        root,
        tuple(args.source_path or ()),
        tuple(args.ignore_source_path or ()),
    )
    if after_execution["dirty_paths"] or any(
        after_execution.get(key) != current.get(key)
        for key in ("git_head", "source_tree_sha256")
    ):
        raise WorkflowError("Verification commands changed the scoped source.")
    current = after_execution
    state["source_revision"] = {
        **current,
        "evidence": str(relative),
        "evidence_sha256": evidence_hash,
        "build_command": args.build_command.strip(),
        "test_command": args.test_command.strip(),
        "test_execution": execution,
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
