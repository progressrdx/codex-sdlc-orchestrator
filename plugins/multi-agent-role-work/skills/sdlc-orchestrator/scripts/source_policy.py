"""Cheap, scope-aware Git source bindings for workflow verification."""

from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path
from typing import Any


DEFAULT_IGNORED_PREFIXES = (".ai-workflow/", "docs/requirements/", ".idea/")
DEFAULT_IGNORED_NAMES = {".DS_Store"}


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


def _relevant(path: str) -> bool:
    normalized = path.strip()
    return bool(normalized) and not normalized.startswith(
        DEFAULT_IGNORED_PREFIXES
    ) and Path(normalized).name not in DEFAULT_IGNORED_NAMES


def _dirty_paths(root: Path, scope_paths: tuple[str, ...]) -> list[str]:
    args = ["status", "--porcelain=v1", "-z"]
    if scope_paths:
        args.extend(("--", *scope_paths))
    raw = str(_git(root, *args))
    entries = raw.split("\0")
    dirty: list[str] = []
    index = 0
    while index < len(entries):
        entry = entries[index]
        index += 1
        if not entry:
            continue
        path = entry[3:] if len(entry) > 3 else ""
        if entry[:2] in {"R ", "C "} and index < len(entries):
            path = entries[index]
            index += 1
        if _relevant(path):
            dirty.append(path)
    return sorted(set(dirty))


def _scoped_tree_hash(root: Path, scope_paths: tuple[str, ...]) -> str:
    raw = _git(root, "ls-files", "-s", "-z", "--", *scope_paths, binary=True)
    if not bytes(raw):
        raise SourcePolicyError("The configured delivery scope contains no tracked files.")
    digest = hashlib.sha256()
    for entry in sorted(bytes(raw).split(b"\0")):
        if entry:
            digest.update(entry)
            digest.update(b"\0")
    return digest.hexdigest()


def source_binding(root: Path, scope_paths: tuple[str, ...] = ()) -> dict[str, Any]:
    """Return a Git object binding without reading every source file."""
    head = str(_git(root, "rev-parse", "HEAD")).strip()
    if not head:
        raise SourcePolicyError("Strict verification requires at least one Git commit.")
    normalized_scope = tuple(dict.fromkeys(path.strip() for path in scope_paths if path.strip()))
    for raw_path in normalized_scope:
        candidate = Path(raw_path)
        if (
            candidate.is_absolute()
            or ".." in candidate.parts
            or raw_path.startswith(":")
            or raw_path.startswith("-")
        ):
            raise SourcePolicyError(f"Invalid delivery scope path: {raw_path}")
    tree_hash = (
        _scoped_tree_hash(root, normalized_scope)
        if normalized_scope
        else str(_git(root, "rev-parse", "HEAD^{tree}")).strip()
    )
    return {
        "git_head": head,
        "source_tree_sha256": tree_hash,
        "scope_paths": list(normalized_scope),
        "dirty_paths": _dirty_paths(root, normalized_scope),
    }
