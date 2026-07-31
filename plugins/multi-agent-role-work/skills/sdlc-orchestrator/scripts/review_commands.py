"""Role verdict, gate bundle, meeting, and human approval commands."""

from __future__ import annotations

from typing import Any

from command_runtime import invoke as invoke_bound


def invoke(name: str, api: Any, args: Any) -> Any:
    return invoke_bound(globals(), name, api, args)


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


def cmd_submit_gate_review(args: argparse.Namespace) -> None:
    """Atomically replace a gate's role decisions and record its meeting."""
    root = repository_root(args.root)
    path, state = load_state(root, args.id)
    manifest_path, manifest_relative = repository_evidence_path(root, args.manifest)
    manifest = load_data(manifest_path)
    gate = str(manifest.get("gate", ""))
    current = state["workflow"]["current_stage"]
    if gate not in GATES or gate != current:
        raise WorkflowError(f"Gate-review bundle targets {gate or 'unknown'} while current stage is {current}.")

    required_roles = tuple(required_gate_roles(state, gate))
    decisions_spec = manifest.get("decisions")
    meeting_spec = manifest.get("meeting")
    if not isinstance(decisions_spec, list) or not isinstance(meeting_spec, dict):
        raise WorkflowError("Gate-review manifest requires decisions list and meeting mapping.")

    pending: dict[str, dict[str, Any]] = {}
    actor_refs: set[str] = set()
    evidence_hashes: set[str] = set()
    for item in decisions_spec:
        if not isinstance(item, dict):
            raise WorkflowError("Each gate-review decision must be a mapping.")
        role = str(item.get("role", ""))
        verdict = str(item.get("verdict", ""))
        actor_ref = str(item.get("actor_ref", "")).strip()
        if role not in required_roles:
            raise WorkflowError(f"Role {role or 'unknown'} is not required for {gate}.")
        if role in pending:
            raise WorkflowError(f"Duplicate gate-review role: {role}")
        if verdict not in {"approve", "reject"}:
            raise WorkflowError(f"Invalid verdict for {role}: {verdict}")
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:/-]{2,127}", actor_ref):
            raise WorkflowError(f"Invalid actor reference for {role}.")
        if actor_ref in actor_refs:
            raise WorkflowError(f"Actor reference is reused in gate-review bundle: {actor_ref}")
        evidence_path, evidence = repository_evidence_path(
            root, str(item.get("evidence", "")), minimum_chars=MIN_DOCUMENT_CHARS
        )
        evidence_text = evidence_path.read_text(encoding="utf-8")
        for required_text in (gate, role, "verdict", verdict):
            if not contains_marker(evidence_text, required_text):
                raise WorkflowError(
                    f"Review evidence for {role} must identify: {required_text.replace('_', ' ')}"
                )
        evidence_hash = content_sha256(evidence_path)
        if evidence_hash in evidence_hashes:
            raise WorkflowError("Gate-review decisions require distinct evidence content.")
        for other_gate, decisions in state.get("decisions", {}).items():
            for other_role, decision in decisions.items():
                if (
                    evidence_hash == decision.get("evidence_sha256")
                    and (other_gate, other_role) != (gate, role)
                ):
                    raise WorkflowError(
                        f"Review evidence content is already used by {other_gate}:{other_role}."
                    )
        actor_refs.add(actor_ref)
        evidence_hashes.add(evidence_hash)
        pending[role] = {
            "verdict": verdict,
            "notes": str(item.get("notes", "")),
            "actor_ref": actor_ref,
            "evidence": str(evidence),
            "evidence_sha256": evidence_hash,
            "at": now(),
        }

    missing_roles = sorted(set(required_roles) - set(pending))
    if missing_roles:
        raise WorkflowError("Gate-review bundle is missing roles: " + ",".join(missing_roles))

    participants_value = meeting_spec.get("participants", [])
    if isinstance(participants_value, str):
        participants = tuple(
            dict.fromkeys(item.strip() for item in participants_value.split(",") if item.strip())
        )
    elif isinstance(participants_value, list):
        participants = tuple(dict.fromkeys(str(item).strip() for item in participants_value if str(item).strip()))
    else:
        raise WorkflowError("Gate-review meeting participants must be a list or comma-separated text.")
    if not set(required_roles).issubset(set(participants)):
        missing = sorted(set(required_roles) - set(participants))
        raise WorkflowError("Gate-review meeting is missing participants: " + ",".join(missing))
    unknown = sorted(set(participants) - set(MEETING_PARTICIPANTS))
    if unknown:
        raise WorkflowError("Unknown meeting participants: " + ",".join(unknown))
    outcome = str(meeting_spec.get("outcome", ""))
    if outcome not in MEETING_OUTCOMES:
        raise WorkflowError(f"Invalid gate-review meeting outcome: {outcome}")
    if outcome == "approved" and {item["verdict"] for item in pending.values()} != {"approve"}:
        raise WorkflowError("An approved gate-review meeting requires every role to approve.")
    meeting_path, meeting_relative = repository_evidence_path(
        root, str(meeting_spec.get("path", "")), minimum_chars=MIN_DOCUMENT_CHARS
    )
    require_markdown_structure(meeting_path)
    meeting_content = meeting_path.read_text(encoding="utf-8")
    if not contains_marker(meeting_content, gate):
        raise WorkflowError(f"Gate-review meeting notes must identify: {gate.replace('_', ' ')}")
    for participant in participants:
        if not contains_marker(meeting_content, participant):
            raise WorkflowError(f"Gate-review meeting notes must identify participant: {participant}")
    meeting_hash = content_sha256(meeting_path)
    if meeting_hash in evidence_hashes:
        raise WorkflowError("Meeting notes must be distinct from role review evidence.")
    for meeting in state.get("meetings", []):
        if meeting.get("evidence_sha256") == meeting_hash:
            raise WorkflowError(f"Meeting-note content is already used by {meeting.get('id')}.")

    invalidated_meetings = invalidate_gate_meetings(
        state, (gate,), f"Atomic gate-review bundle replaced {gate} evidence"
    )
    state.setdefault("decisions", {})[gate] = pending
    meeting_id = next_meeting_id(state)
    state.setdefault("meetings", []).append(
        {
            "id": meeting_id,
            "type": gate,
            "title": str(meeting_spec.get("title", f"{gate} review")),
            "stage": gate,
            "participants": list(participants),
            "outcome": outcome,
            "path": str(meeting_relative),
            "evidence_sha256": meeting_hash,
            "decision_snapshot": gate_decision_snapshot(state, gate),
            "status": "current",
            "created_at": now(),
        }
    )
    add_history(state, "gate_review_bundle_submitted", f"{gate}:{manifest_relative}:{meeting_id}")
    if invalidated_meetings:
        add_history(state, "meetings_invalidated", ",".join(invalidated_meetings))
    save_state(path, state)
    print(f"Recorded atomic {gate} review bundle as {meeting_id}")


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
