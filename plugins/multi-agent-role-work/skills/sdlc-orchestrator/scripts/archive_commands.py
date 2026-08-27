"""Controlled archival for superseded project documents."""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

from command_runtime import invoke as invoke_bound


ARCHIVE_ID_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{2,80}")


def invoke(name: str, api: Any, args: Any) -> Any:
    return invoke_bound(globals(), name, api, args)


def _replace_exact_paths(value: Any, replacements: dict[str, str]) -> Any:
    if isinstance(value, str):
        return replacements.get(value, value)
    if isinstance(value, list):
        return [_replace_exact_paths(item, replacements) for item in value]
    if isinstance(value, dict):
        return {key: _replace_exact_paths(item, replacements) for key, item in value.items()}
    return value


def _archive_index(
    archive_id: str,
    reason: str,
    entries: list[dict[str, str]],
) -> str:
    lines = [
        f"# 归档索引：{archive_id}",
        "",
        "## 归档原因",
        "",
        reason,
        "",
        "## 已归档文档",
        "",
    ]
    for entry in entries:
        replacement = entry.get("replaced_by") or "未指定；仅保留历史追溯"
        lines.extend(
            (
                f"- 原路径：`{entry['source']}`",
                f"  - 归档路径：`{entry['destination']}`",
                f"  - 当前替代文档：`{replacement}`",
            )
        )
    lines.extend(
        (
            "",
            "本目录仅用于历史追溯，不属于当前有效方案，也不应参与项目摘要或目标判断。",
            "",
        )
    )
    return "\n".join(lines)


def cmd_archive_documents(args: Any) -> None:
    root = repository_root(args.root)
    state_path, state = load_state(root, args.id)
    manifest_path, manifest_relative = repository_evidence_path(root, args.manifest)
    manifest = load_data(manifest_path)
    archive_id = str(manifest.get("archive_id", "")).strip()
    reason = str(manifest.get("reason", "")).strip()
    documents = manifest.get("documents")
    if not ARCHIVE_ID_PATTERN.fullmatch(archive_id):
        raise WorkflowError("Archive manifest requires a safe archive_id.")
    if len(reason) < 10:
        raise WorkflowError("Archive manifest requires a substantive reason.")
    if not isinstance(documents, list) or not documents:
        raise WorkflowError("Archive manifest requires a non-empty documents list.")

    workflow_relative = Path("docs") / "requirements" / state["workflow"]["id"]
    workflow_directory = (root / workflow_relative).resolve()
    archive_relative = workflow_relative / "_archive" / archive_id
    active_paths = {
        str(item.get("path"))
        for item in state.get("artifacts", {}).values()
        if item.get("status") in {"ready", "not_applicable"}
    }
    entries: list[dict[str, str]] = []
    replacements: dict[str, str] = {}
    seen: set[str] = set()
    for raw in documents:
        if not isinstance(raw, dict):
            raise WorkflowError("Every archive document entry must be a mapping.")
        source_path, source_relative = repository_evidence_path(root, str(raw.get("path", "")))
        source_text = source_relative.as_posix()
        if source_text in seen:
            raise WorkflowError(f"Archive manifest repeats a document: {source_text}")
        seen.add(source_text)
        if source_text in active_paths:
            raise WorkflowError(f"Cannot archive a current active document: {source_text}")
        if source_path.is_symlink() or not source_path.is_file():
            raise WorkflowError(f"Archive source must be a regular file: {source_text}")
        try:
            within_workflow = source_path.resolve().relative_to(workflow_directory)
        except ValueError as exc:
            raise WorkflowError(f"Archive source is outside the active workflow: {source_text}") from exc
        if within_workflow.parts and within_workflow.parts[0] == "_archive":
            raise WorkflowError(f"Document is already archived: {source_text}")
        destination_relative = archive_relative / within_workflow
        destination = root / destination_relative
        if destination.exists():
            raise WorkflowError(f"Archive destination already exists: {destination_relative}")
        replaced_by = str(raw.get("replaced_by", "")).strip()
        if replaced_by:
            replacement_path, replacement_relative = repository_evidence_path(root, replaced_by)
            if not replacement_path.is_file():
                raise WorkflowError(f"Replacement document must be a file: {replacement_relative}")
            replaced_by = replacement_relative.as_posix()
        replacements[source_text] = destination_relative.as_posix()
        entries.append(
            {
                "source": source_text,
                "destination": destination_relative.as_posix(),
                "replaced_by": replaced_by,
            }
        )

    archived_sources = set(replacements)
    invalid_replacements = sorted(
        entry["replaced_by"]
        for entry in entries
        if entry["replaced_by"] in archived_sources
    )
    if invalid_replacements:
        raise WorkflowError(
            "Replacement documents cannot be archived in the same batch: "
            + ", ".join(invalid_replacements)
        )

    index_path = root / archive_relative / "INDEX.md"
    if index_path.exists():
        raise WorkflowError(f"Archive index already exists: {index_path.relative_to(root)}")
    moved: list[tuple[Path, Path]] = []
    try:
        for entry in entries:
            source = root / entry["source"]
            destination = root / entry["destination"]
            destination.parent.mkdir(parents=True, exist_ok=True)
            os.replace(source, destination)
            moved.append((source, destination))
        atomic_write_text(index_path, _archive_index(archive_id, reason, entries))
        updated_state = _replace_exact_paths(state, replacements)
        add_history(
            updated_state,
            "documents_archived",
            f"{archive_id}:{len(entries)} documents via {manifest_relative.as_posix()}",
        )
        save_state(state_path, updated_state)
    except Exception:
        index_path.unlink(missing_ok=True)
        for source, destination in reversed(moved):
            source.parent.mkdir(parents=True, exist_ok=True)
            if destination.exists():
                os.replace(destination, source)
        raise
    print(f"Archived {len(entries)} documents under {archive_relative.as_posix()}")
