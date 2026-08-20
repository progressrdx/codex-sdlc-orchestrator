"""Source bindings for formal workflow verification."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

from delivery_candidate import (
    CandidateError,
    DEFAULT_EXCLUDED_NAMES,
    DEFAULT_EXCLUDED_PATHS,
    FALLBACK_EXCLUDED_PARTS,
    DeliveryCandidate,
    git_status_paths,
    hidden_index_paths,
    normalize_relative_paths,
    path_is_relevant,
)


# Keep the established names available to callers while sharing one path policy
# with candidate construction and snapshot materialization.
DEFAULT_IGNORED_PREFIXES = tuple(f"{path}/" for path in DEFAULT_EXCLUDED_PATHS)
DEFAULT_IGNORED_NAMES = set(DEFAULT_EXCLUDED_NAMES)
FALLBACK_IGNORED_PARTS = set(FALLBACK_EXCLUDED_PARTS)


class SourcePolicyError(RuntimeError):
    pass


def _git(root: Path, *args: str, binary: bool = False) -> str | bytes:
    try:
        return subprocess.check_output(
            ["git", "-C", str(root), *args],
            text=not binary,
            stderr=subprocess.DEVNULL,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise SourcePolicyError(f"Unable to inspect Git source state: {' '.join(args)}") from exc


def _relevant(path: str, ignored_paths: tuple[str, ...]) -> bool:
    try:
        normalized_ignored = normalize_relative_paths(ignored_paths)
    except CandidateError as exc:
        raise SourcePolicyError(str(exc)) from exc
    return path_is_relevant(path, normalized_ignored)


def _dirty_paths(
    root: Path,
    scope_paths: tuple[str, ...],
    ignored_paths: tuple[str, ...],
) -> list[str]:
    """Report every candidate/worktree difference, including hidden Git state."""
    try:
        changed = set(
            git_status_paths(
                root,
                scope_paths=scope_paths,
                excluded_paths=ignored_paths,
                include_ignored=True,
            )
        )
        changed.update(hidden_index_paths(root, scope_paths, ignored_paths))
    except CandidateError as exc:
        raise SourcePolicyError(str(exc)) from exc
    return sorted(changed)


def _scoped_tree_hash(
    root: Path,
    scope_paths: tuple[str, ...],
    ignored_paths: tuple[str, ...],
) -> str:
    try:
        candidate = DeliveryCandidate.from_repository(root)
        return candidate.selected_manifest_sha256(scope_paths, ignored_paths)
    except CandidateError as exc:
        raise SourcePolicyError(str(exc)) from exc


def source_binding(
    root: Path,
    scope_paths: tuple[str, ...] = (),
    ignored_paths: tuple[str, ...] = (),
) -> dict[str, Any]:
    """Bind strict verification to one commit and its path/mode/blob manifest."""
    try:
        normalized_scope = normalize_relative_paths(scope_paths)
        normalized_ignored = normalize_relative_paths(ignored_paths)
        candidate = DeliveryCandidate.from_repository(root)
        tree_hash = candidate.selected_manifest_sha256(
            normalized_scope,
            normalized_ignored,
        )
        dirty_paths = candidate.worktree_changes(
            normalized_scope,
            normalized_ignored,
        )
    except CandidateError as exc:
        raise SourcePolicyError(str(exc)) from exc
    return {
        "binding_type": "git_commit",
        "git_head": candidate.commit_oid,
        "git_tree": candidate.tree_oid,
        "candidate_manifest_sha256": candidate.manifest_sha256,
        "source_tree_sha256": tree_hash,
        "scope_paths": list(normalized_scope),
        "ignored_paths": list(normalized_ignored),
        "dirty_paths": dirty_paths,
    }


def _validate_relative_paths(paths: tuple[str, ...]) -> tuple[str, ...]:
    try:
        return normalize_relative_paths(paths)
    except CandidateError as exc:
        raise SourcePolicyError(str(exc)) from exc


def _workspace_paths(root: Path, ignored_paths: tuple[str, ...]) -> list[str]:
    """List paths in the frozen lightweight candidate manifest."""
    try:
        candidate = DeliveryCandidate.from_workspace(root, ignored_paths)
    except CandidateError as exc:
        raise SourcePolicyError(str(exc)) from exc
    return [entry.path for entry in candidate.entries]


def workspace_binding(
    root: Path,
    ignored_paths: tuple[str, ...] = (),
) -> dict[str, Any]:
    """Bind a lightweight workflow to a frozen path/mode/content manifest.

    Tracked and non-ignored untracked files are content-addressed.  Ignored files
    never leak into the execution snapshot, and hidden index flags fail closed.
    """
    try:
        normalized_ignored = normalize_relative_paths(ignored_paths)
        candidate = DeliveryCandidate.from_workspace(root, normalized_ignored)
    except CandidateError as exc:
        raise SourcePolicyError(str(exc)) from exc
    return {
        "binding_type": "workspace_content",
        "source_tree_sha256": candidate.manifest_sha256,
        "candidate_tree": candidate.tree_oid,
        "candidate_manifest_sha256": candidate.manifest_sha256,
        "file_count": len(candidate.entries),
        "ignored_paths": list(normalized_ignored),
    }
