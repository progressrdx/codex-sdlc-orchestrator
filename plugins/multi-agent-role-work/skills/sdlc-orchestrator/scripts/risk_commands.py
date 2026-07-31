"""Risk assessment, escalation, and disposition commands."""

from __future__ import annotations

from typing import Any

from command_runtime import invoke as invoke_bound


def invoke(name: str, api: Any, args: Any) -> Any:
    return invoke_bound(globals(), name, api, args)


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
