"""Persisted role work-item lifecycle commands.

The pure transition rules live in :mod:`work_items`.  This module binds those
rules to repository evidence and workflow state; the top-level workflow CLI
owns the process-wide workflow lock around every command here.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from command_runtime import invoke as invoke_bound
from state_store import WorkflowError
from work_items import (
    WorkItemError,
    assert_output_acceptable,
    cancel_work_item,
    complete_work_item,
    create_work_item,
    fail_work_item,
    heartbeat_work_item,
    timeout_work_item,
)


def invoke(name: str, api: Any, args: Any) -> Any:
    return invoke_bound(globals(), name, api, args)


def _canonical_sha256(value: Any) -> str:
    rendered = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return hashlib.sha256(rendered.encode("utf-8")).hexdigest()


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _bound_repository_file(root: Any, raw_path: str) -> tuple[Path, str]:
    repository = Path(root).resolve()
    candidate = Path(raw_path)
    absolute = (candidate if candidate.is_absolute() else repository / candidate).resolve()
    try:
        absolute.relative_to(repository)
    except ValueError as exc:
        raise WorkflowError("Work output must remain inside the repository root.") from exc
    if not absolute.is_file():
        raise WorkflowError(f"Work output is not a repository file: {raw_path}")
    return absolute, absolute.relative_to(repository).as_posix()


def capture_input_hashes(state: Mapping[str, Any]) -> dict[str, str]:
    """Capture the semantic inputs a dispatched role is allowed to rely on."""

    hashes: dict[str, str] = {}
    artifacts = state.get("artifacts", {})
    if isinstance(artifacts, Mapping):
        for name, raw_artifact in artifacts.items():
            if not isinstance(raw_artifact, Mapping):
                continue
            if raw_artifact.get("status") not in {"ready", "current"}:
                continue
            digest = raw_artifact.get("evidence_sha256")
            if isinstance(digest, str) and len(digest) == 64:
                hashes[f"artifact:{name}"] = digest.lower()

    # These mappings are protected semantic baselines even when their evidence
    # is already represented by an artifact.  Hashing their canonical value
    # also catches state-only changes such as a changed criterion description.
    for key in (
        "risk_assessment",
        "risk_reports",
        "source_revision",
        "acceptance_criteria",
        "core_goals",
    ):
        value = state.get(key)
        if value not in (None, {}, []):
            hashes[key] = _canonical_sha256(value)

    if "artifact:original_request" not in hashes:
        raise WorkflowError(
            "Cannot dispatch role work without the original_request evidence baseline."
        )
    return {key: hashes[key] for key in sorted(hashes)}


def current_input_hashes(root: Any, state: Mapping[str, Any]) -> dict[str, str]:
    """Public gate helper returning the workflow's current semantic baseline."""
    hashes = capture_input_hashes(state)
    artifacts = state.get("artifacts", {})
    if isinstance(artifacts, Mapping):
        for name, raw_artifact in artifacts.items():
            key = f"artifact:{name}"
            if key not in hashes or not isinstance(raw_artifact, Mapping):
                continue
            raw_path = raw_artifact.get("path")
            if not isinstance(raw_path, str) or not raw_path:
                raise WorkflowError(f"Current artifact {name} has no repository path.")
            absolute, _ = _bound_repository_file(root, raw_path)
            actual = hashlib.sha256(absolute.read_bytes()).hexdigest()
            if actual != hashes[key]:
                raise WorkflowError(
                    f"Cannot use stale artifact baseline {name}; its repository bytes changed."
                )
    return hashes


def _work_items(state: dict[str, Any]) -> dict[str, Any]:
    items = state.setdefault("work_items", {})
    if not isinstance(items, dict):
        raise WorkflowError("Workflow work_items must be a mapping.")
    return items


def _existing_work_item(state: dict[str, Any], work_item_id: str) -> dict[str, Any]:
    item = _work_items(state).get(work_item_id)
    if not isinstance(item, dict):
        raise WorkflowError(f"Unknown work item: {work_item_id}")
    return item


def require_completed_output(
    root: Any,
    state: dict[str, Any],
    work_item_id: str,
    stage: str,
    role: str,
    output_name: str,
    evidence_sha256: str,
    evidence_path: str,
) -> dict[str, Any]:
    """Require a fresh completed role output matching current repository evidence."""

    item = _existing_work_item(state, work_item_id)
    if item.get("stage") != stage:
        raise WorkflowError(
            f"Work item {work_item_id} belongs to stage {item.get('stage')!r}, not {stage!r}."
        )
    if item.get("role") != role:
        raise WorkflowError(
            f"Work item {work_item_id} belongs to role {item.get('role')!r}, not {role!r}."
        )
    checked = _translate_work_item_error(
        "accept output from",
        lambda: assert_output_acceptable(
            item,
            at=_utc_now(),
            current_revision=state["revision"],
            current_input_hashes=current_input_hashes(root, state),
        ),
    )
    expected_hash = checked.get("output_hashes", {}).get(output_name)
    if expected_hash != evidence_sha256.lower():
        raise WorkflowError(
            f"Work item {work_item_id} output {output_name!r} does not match submitted evidence."
        )
    raw_output_path = checked.get("output_paths", {}).get(output_name)
    if not isinstance(raw_output_path, str) or not raw_output_path:
        raise WorkflowError(
            f"Work item {work_item_id} output {output_name!r} has no repository path binding."
        )
    absolute, canonical_output_path = _bound_repository_file(root, raw_output_path)
    submitted_absolute, canonical_evidence_path = _bound_repository_file(
        root, evidence_path
    )
    if canonical_output_path != canonical_evidence_path:
        raise WorkflowError(
            f"Work item {work_item_id} output {output_name!r} is bound to "
            f"{canonical_output_path}, not submitted path {canonical_evidence_path}."
        )
    if submitted_absolute != absolute:
        raise WorkflowError(
            f"Work item {work_item_id} output {output_name!r} resolves to a different file."
        )
    if hashlib.sha256(absolute.read_bytes()).hexdigest() != expected_hash:
        raise WorkflowError(
            f"Work item {work_item_id} output {output_name!r} changed after completion."
        )
    return checked


def _translate_work_item_error(action: str, callback: Any) -> Any:
    try:
        return callback()
    except WorkItemError as exc:
        raise WorkflowError(f"Cannot {action} work item: {exc}") from exc


def _record_transition(
    path: Any,
    state: dict[str, Any],
    *,
    work_item_id: str,
    item: dict[str, Any],
    event: str,
    detail: str,
) -> None:
    _work_items(state)[work_item_id] = item
    add_history(state, event, detail)
    save_state(path, state)


def cmd_begin_work(args: Any) -> None:
    root = repository_root(args.root)
    path, state = load_state(root, args.id)
    items = _work_items(state)
    if args.work_item_id in items:
        raise WorkflowError(f"Work item already exists: {args.work_item_id}")

    workflow = state["workflow"]
    stage = workflow["current_stage"]
    mode = workflow["mode"]
    policy = EXECUTION_POLICIES[mode]
    budget = int(policy["recommended_max_role_handoffs_per_stage"])
    stage_handoffs = sum(
        1
        for item in items.values()
        if isinstance(item, Mapping)
        and item.get("stage") == stage
        and item.get("status") != "superseded"
    )
    override: dict[str, str] | None = None
    if stage_handoffs >= budget:
        if not args.override_evidence:
            raise WorkflowError(
                f"Role handoff budget exhausted for {stage}: {stage_handoffs}/{budget}. "
                "Provide --override-evidence with repository evidence to dispatch another attempt."
            )
        override_path, override_relative = repository_evidence_path(
            root, args.override_evidence, minimum_chars=1
        )
        if not override_path.is_file():
            raise WorkflowError("Handoff budget override evidence must be a repository file.")
        override = {
            "path": str(override_relative),
            "evidence_sha256": content_sha256(override_path),
        }
    elif args.override_evidence:
        raise WorkflowError(
            "--override-evidence is only valid after the stage handoff budget is exhausted."
        )

    attempt = 1 + sum(
        1
        for item in items.values()
        if isinstance(item, Mapping)
        and item.get("stage") == stage
        and item.get("role") == args.role
    )
    timestamp = now()
    baseline = current_input_hashes(root, state)
    item = _translate_work_item_error(
        "begin",
        lambda: create_work_item(
            work_item_id=args.work_item_id,
            stage=stage,
            role=args.role,
            attempt=attempt,
            actor_ref=args.actor_ref,
            input_revision=state["revision"],
            input_hashes=baseline,
            dispatched_at=timestamp,
            deadline_at=args.deadline_at,
            lease_seconds=args.lease_seconds,
        ),
    )
    if override is not None:
        item["handoff_budget_override"] = override
    _record_transition(
        path,
        state,
        work_item_id=args.work_item_id,
        item=item,
        event="work_item_dispatched",
        detail=f"{args.work_item_id}:{stage}:{args.role}:attempt-{attempt}",
    )
    print(
        f"Dispatched {args.work_item_id}: stage={stage} role={args.role} "
        f"attempt={attempt} baseline={len(baseline)}"
    )


def cmd_heartbeat_work(args: Any) -> None:
    root = repository_root(args.root)
    path, state = load_state(root, args.id)
    current = _existing_work_item(state, args.work_item_id)
    item = _translate_work_item_error(
        "heartbeat",
        lambda: heartbeat_work_item(
            current,
            at=now(),
            lease_seconds=args.lease_seconds,
        ),
    )
    _record_transition(
        path,
        state,
        work_item_id=args.work_item_id,
        item=item,
        event="work_item_heartbeat",
        detail=f"{args.work_item_id}:heartbeat-{item['heartbeat_count']}",
    )
    print(f"Heartbeat renewed for {args.work_item_id} until {item['lease_expires_at']}")


def _parse_output_hashes(root: Any, values: list[str]) -> tuple[dict[str, str], dict[str, str]]:
    hashes: dict[str, str] = {}
    paths: dict[str, str] = {}
    for value in values:
        name, separator, raw_path = value.partition("=")
        name, raw_path = name.strip(), raw_path.strip()
        if not separator or not name or not raw_path:
            raise WorkflowError(f"Work output must use NAME=repository/path: {value!r}")
        if name in hashes:
            raise WorkflowError(f"Duplicate work output name: {name}")
        absolute, relative = repository_evidence_path(root, raw_path)
        if not absolute.is_file():
            raise WorkflowError(f"Work output must be a repository file: {relative}")
        hashes[name] = content_sha256(absolute)
        paths[name] = str(relative)
    return hashes, paths


def cmd_complete_work(args: Any) -> None:
    root = repository_root(args.root)
    path, state = load_state(root, args.id)
    current = _existing_work_item(state, args.work_item_id)
    output_hashes, output_paths = _parse_output_hashes(root, args.output)
    item = _translate_work_item_error(
        "complete",
        lambda: complete_work_item(
            current,
            at=now(),
            current_revision=state["revision"],
            current_input_hashes=current_input_hashes(root, state),
            output_hashes=output_hashes,
            output_paths=output_paths,
        ),
    )
    _record_transition(
        path,
        state,
        work_item_id=args.work_item_id,
        item=item,
        event="work_item_completed",
        detail=f"{args.work_item_id}:{','.join(sorted(output_hashes))}",
    )
    print(f"Completed {args.work_item_id}: outputs={','.join(sorted(output_hashes))}")


def cmd_cancel_work(args: Any) -> None:
    root = repository_root(args.root)
    path, state = load_state(root, args.id)
    current = _existing_work_item(state, args.work_item_id)
    item = _translate_work_item_error(
        "cancel",
        lambda: cancel_work_item(current, at=now(), reason=args.reason),
    )
    _record_transition(
        path,
        state,
        work_item_id=args.work_item_id,
        item=item,
        event="work_item_cancelled",
        detail=f"{args.work_item_id}:{args.reason.strip()}",
    )
    print(f"Cancelled {args.work_item_id}")


def cmd_fail_work(args: Any) -> None:
    root = repository_root(args.root)
    path, state = load_state(root, args.id)
    current = _existing_work_item(state, args.work_item_id)
    item = _translate_work_item_error(
        "fail",
        lambda: fail_work_item(current, at=now(), reason=args.reason),
    )
    _record_transition(
        path,
        state,
        work_item_id=args.work_item_id,
        item=item,
        event="work_item_failed",
        detail=f"{args.work_item_id}:{args.reason.strip()}",
    )
    print(f"Failed {args.work_item_id}")


def cmd_timeout_work(args: Any) -> None:
    root = repository_root(args.root)
    path, state = load_state(root, args.id)
    current = _existing_work_item(state, args.work_item_id)
    item = _translate_work_item_error(
        "time out",
        lambda: timeout_work_item(current, at=now(), reason=args.reason),
    )
    _record_transition(
        path,
        state,
        work_item_id=args.work_item_id,
        item=item,
        event="work_item_timed_out",
        detail=f"{args.work_item_id}:{args.reason.strip()}",
    )
    print(f"Timed out {args.work_item_id}")
