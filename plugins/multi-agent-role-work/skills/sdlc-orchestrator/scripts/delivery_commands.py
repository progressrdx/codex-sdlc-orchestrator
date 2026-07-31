"""User feedback, delivery confirmation, and issue lifecycle commands."""

from __future__ import annotations

from typing import Any

from command_runtime import invoke as invoke_bound


def invoke(name: str, api: Any, args: Any) -> Any:
    return invoke_bound(globals(), name, api, args)


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
