"""Single and atomic-bundle artifact recording commands."""

from __future__ import annotations

from typing import Any

from command_runtime import invoke as invoke_bound


def invoke(name: str, api: Any, args: Any) -> Any:
    return invoke_bound(globals(), name, api, args)


def _contains_marker(text: str, marker: str) -> bool:
    variants = {marker, marker.replace("_", " "), marker.replace("_", "-")}
    return any(variant.lower() in text.lower() for variant in variants)


def require_artifact_content(name: str, path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    groups: dict[str, dict[str, tuple[str, ...]]] = {
        "clarification_questions": {
            "question": ("question", "问题", "需确认"),
            "missing": ("missing", "缺失", "缺口", "待补充"),
            "assumption": ("assumption", "假设", "暂定"),
            "acceptance": ("acceptance", "验收", "完成标准"),
        },
        "prototype": {
            "preview": ("preview", "预览", "原型"),
            "scope": ("scope", "范围", "包含内容"),
            "how to inspect": ("how to inspect", "如何查看", "体验方式", "检查方式"),
        },
    }
    for marker, aliases in groups.get(name, {}).items():
        if not any(_contains_marker(text, alias) for alias in aliases):
            if name == "prototype":
                raise WorkflowError(f"Prototype evidence must identify: {marker}")
            raise WorkflowError(
                "Clarification evidence must cover questions, missing details, assumptions, "
                f"and acceptance criteria; missing: {marker}"
            )
    approvals = {
        "requirement_confirmation": (("user", "用户"), ("confirmed", "approve", "确认", "同意", "批准")),
        "user_feedback": (("user", "用户"), ("feedback", "反馈", "预览结论"), ("approve", "approved", "通过", "确认", "同意")),
    }
    if name in approvals and not all(
        any(_contains_marker(text, marker) for marker in group) for group in approvals[name]
    ):
        if name == "requirement_confirmation":
            raise WorkflowError(
                "Requirement confirmation evidence must record explicit user confirmation."
            )
        raise WorkflowError("User feedback evidence must record explicit user approval.")


def cmd_record_artifact(args: argparse.Namespace) -> None:
    root = repository_root(args.root)
    path, state = load_state(root, args.id)
    specialized_command = SPECIALIZED_ARTIFACT_COMMANDS.get(args.name)
    if specialized_command:
        raise WorkflowError(
            f"Artifact {args.name} must be recorded through {specialized_command}."
        )
    if args.status == "not_applicable" and args.name not in NOT_APPLICABLE_ALLOWED:
        raise WorkflowError(f"Artifact {args.name} cannot be marked not_applicable.")
    if args.status == "not_applicable" and not (args.notes or "").strip():
        raise WorkflowError("A not_applicable artifact requires a justification in --notes.")
    minimum = MIN_DOCUMENT_CHARS if args.name in DOCUMENT_ARTIFACTS and args.status == "ready" else 0
    absolute, relative = repository_evidence_path(root, args.path, minimum_chars=minimum)
    if args.status in {"ready", "not_applicable"} and not absolute.is_file():
        raise WorkflowError(f"Artifact evidence must be a repository file: {relative}")
    if args.name in DOCUMENT_ARTIFACTS and args.status == "ready":
        require_markdown_structure(absolute)
        require_artifact_content(args.name, absolute)
    for other_name, other in state.get("artifacts", {}).items():
        if other_name != args.name and other.get("path") == str(relative) and other.get("status") != "superseded":
            raise WorkflowError(f"Artifact path is already used by {other_name}: {relative}")
    previous = state.get("artifacts", {}).get(args.name, {})
    next_hash = (
        content_sha256(absolute)
        if args.status in {"ready", "not_applicable"}
        else None
    )
    unchanged = bool(previous) and (
        previous.get("path") == str(relative)
        and previous.get("status") == args.status
        and previous.get("evidence_sha256") == next_hash
        and previous.get("notes", "") == (args.notes or "")
    )
    if unchanged:
        print(f"Artifact already recorded: {args.name} ({relative})")
        return
    artifact_stage = ARTIFACT_STAGE.get(args.name)
    current_stage = state["workflow"]["current_stage"]
    if artifact_stage and current_stage != artifact_stage:
        raise WorkflowError(
            f"Artifact {args.name} belongs to {artifact_stage}; current stage is {current_stage}. "
            "Reopen explicitly before replacing an earlier baseline."
        )
    producer_role = ARTIFACT_ROLE.get(args.name)
    producer_work_item_id = str(args.work_item_id or "").strip()
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
            ignored_paths=ignored_paths,
            output_paths=tuple(args.output_path or ()),
        )
        execution_candidate = verification_execution.get("candidate", {})
        if not isinstance(execution_candidate, dict) or any(
            execution_candidate.get(key) != expected
            for key, expected in {
                "kind": "workspace_content",
                "tree_oid": before_execution.get("candidate_tree"),
                "manifest_sha256": before_execution.get("candidate_manifest_sha256"),
            }.items()
        ):
            raise WorkflowError(
                "Verification execution did not use the frozen workspace candidate."
            )
        try:
            verification_binding = workspace_binding(root, ignored_paths)
        except SourcePolicyError as exc:
            raise WorkflowError(str(exc)) from exc
        if any(
            before_execution.get(key) != verification_binding.get(key)
            for key in ("candidate_tree", "candidate_manifest_sha256", "source_tree_sha256")
        ):
            raise WorkflowError(
                "Verification commands changed product files. Exclude genuine generated output "
                "through repository ignore rules, or restore source and rerun."
            )
    if producer_role and args.status in {"ready", "not_applicable"}:
        if not producer_work_item_id:
            raise WorkflowError(
                f"Artifact {args.name} requires --work-item-id from role {producer_role}."
            )
        require_completed_output(
            root,
            state,
            producer_work_item_id,
            artifact_stage or current_stage,
            producer_role,
            args.name,
            content_sha256(absolute),
            str(relative),
        )
    changed = bool(previous)
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
        "producer_work_item_id": producer_work_item_id or None,
    }
    if verification_binding is not None:
        state["verification_snapshot"] = {
            **verification_binding,
            "output_paths": list(args.output_path or ()),
            "verification_evidence_sha256": next_hash,
            "test_execution": verification_execution,
            "recorded_at": now(),
        }
    invalidated: list[str] = []
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
    if invalidated:
        add_history(state, "decisions_invalidated", f"{args.name}:{','.join(invalidated)}")
    if invalidated_meetings:
        add_history(state, "meetings_invalidated", ",".join(invalidated_meetings))
    save_state(path, state)
    print(f"Recorded artifact {args.name} ({args.status}): {relative}")


def cmd_record_artifact_bundle(args: argparse.Namespace) -> None:
    root = repository_root(args.root)
    path, state = load_state(root, args.id)
    manifest_path, manifest_relative = repository_evidence_path(
        root,
        args.manifest,
        minimum_chars=2,
    )
    manifest = load_data(manifest_path)
    raw_artifacts = manifest.get("artifacts")
    if not isinstance(raw_artifacts, list) or len(raw_artifacts) < 2:
        raise WorkflowError("An artifact bundle manifest requires at least two artifacts.")

    prepared: dict[str, dict[str, Any]] = {}
    changed_names: list[str] = []
    added_names: list[str] = []
    relative_paths: dict[str, str] = {}
    bundle_stage = ""
    pending_work_outputs: list[tuple[str, str, str, str, str]] = []
    for index, raw_artifact in enumerate(raw_artifacts, start=1):
        if not isinstance(raw_artifact, dict):
            raise WorkflowError(f"Artifact bundle item {index} must be a mapping.")
        name = raw_artifact.get("name")
        raw_path = raw_artifact.get("path")
        status = raw_artifact.get("status", "ready")
        notes = raw_artifact.get("notes", "")
        work_item_id = str(raw_artifact.get("work_item_id", "")).strip()
        if not isinstance(name, str) or not name:
            raise WorkflowError(f"Artifact bundle item {index} requires a name.")
        if name in prepared:
            raise WorkflowError(f"Artifact bundle contains duplicate name: {name}")
        if not isinstance(raw_path, str) or not raw_path:
            raise WorkflowError(f"Artifact bundle item {name} requires a path.")
        if status not in {"ready", "not_applicable", "superseded"}:
            raise WorkflowError(f"Artifact {name} has invalid status: {status}")
        if not isinstance(notes, str):
            raise WorkflowError(f"Artifact {name} notes must be a string.")

        artifact_stage = ARTIFACT_CHANGE_STAGE.get(name, "")
        allowed_group = ATOMIC_ARTIFACT_BUNDLE_GROUPS.get(artifact_stage, frozenset())
        if name not in allowed_group:
            raise WorkflowError(
                f"Artifact {name} is not eligible for atomic bundle recording. "
                "Use its specialized or single-artifact command."
            )
        if bundle_stage and artifact_stage != bundle_stage:
            raise WorkflowError("All artifacts in a bundle must belong to the same baseline stage.")
        bundle_stage = artifact_stage
        if status == "not_applicable" and name not in NOT_APPLICABLE_ALLOWED:
            raise WorkflowError(f"Artifact {name} cannot be marked not_applicable.")
        if status == "not_applicable" and not notes.strip():
            raise WorkflowError(
                f"A not_applicable artifact requires a justification in notes: {name}"
            )

        minimum = MIN_DOCUMENT_CHARS if name in DOCUMENT_ARTIFACTS and status == "ready" else 0
        absolute, relative = repository_evidence_path(root, raw_path, minimum_chars=minimum)
        if status in {"ready", "not_applicable"} and not absolute.is_file():
            raise WorkflowError(f"Artifact evidence must be a repository file: {relative}")
        if name in DOCUMENT_ARTIFACTS and status == "ready":
            require_markdown_structure(absolute)
            require_artifact_content(name, absolute)
        relative_string = str(relative)
        other_bundle_name = relative_paths.get(relative_string)
        if other_bundle_name:
            raise WorkflowError(
                f"Artifact path is used twice in the bundle by {other_bundle_name} and {name}: "
                f"{relative}"
            )
        relative_paths[relative_string] = name

        next_hash = (
            content_sha256(absolute)
            if status in {"ready", "not_applicable"}
            else None
        )
        producer_role = ARTIFACT_ROLE.get(name)
        if producer_role and status in {"ready", "not_applicable"}:
            if not work_item_id:
                raise WorkflowError(
                    f"Artifact bundle item {name} requires work_item_id from {producer_role}."
                )
            pending_work_outputs.append(
                (
                    work_item_id,
                    producer_role,
                    name,
                    content_sha256(absolute),
                    relative_string,
                )
            )
        previous = state.get("artifacts", {}).get(name, {})
        differs = (
            previous.get("path") != relative_string
            or previous.get("status") != status
            or previous.get("evidence_sha256") != next_hash
            or previous.get("notes", "") != notes
        )
        if previous and differs:
            changed_names.append(name)
        elif not previous:
            added_names.append(name)
        prepared[name] = {
            "path": relative_string,
            "status": status,
            "evidence_sha256": next_hash,
            "updated_at": now(),
            "notes": notes,
            "producer_work_item_id": work_item_id or None,
        }

    bundle_names = set(prepared)
    for other_name, other in state.get("artifacts", {}).items():
        if other_name in bundle_names or other.get("status") == "superseded":
            continue
        other_path = str(other.get("path", ""))
        bundle_name = relative_paths.get(other_path)
        if bundle_name:
            raise WorkflowError(
                f"Artifact path for {bundle_name} is already used by {other_name}: {other_path}"
            )

    stages = workflow_stages(state)
    if bundle_stage not in stages:
        raise WorkflowError(
            f"Artifact bundles for stage {bundle_stage} are not valid in "
            f"{state['workflow']['mode']} mode."
        )
    if not changed_names and not added_names:
        print(
            "Artifact bundle already recorded: "
            f"{','.join(sorted(bundle_names))} ({manifest_relative})"
        )
        return
    current_stage = state["workflow"]["current_stage"]
    if current_stage != bundle_stage:
        raise WorkflowError(
            f"Artifact bundle belongs to {bundle_stage}; current stage is {current_stage}. "
            "Reopen explicitly before replacing an earlier baseline."
        )
    for (
        work_item_id,
        role,
        output_name,
        evidence_hash,
        evidence_path,
    ) in pending_work_outputs:
        require_completed_output(
            root,
            state,
            work_item_id,
            bundle_stage,
            role,
            output_name,
            evidence_hash,
            evidence_path,
        )
    state.setdefault("artifacts", {}).update(prepared)
    for name, artifact in prepared.items():
        add_history(
            state,
            "artifact_recorded",
            f"{name}={artifact['status']}:{artifact['path']}",
        )
    add_history(
        state,
        "artifact_bundle_recorded",
        f"{manifest_relative}:{','.join(sorted(bundle_names))}",
    )
    save_state(path, state)
    print(
        "Recorded artifact bundle: "
        f"{','.join(sorted(bundle_names))} ({manifest_relative})"
    )
