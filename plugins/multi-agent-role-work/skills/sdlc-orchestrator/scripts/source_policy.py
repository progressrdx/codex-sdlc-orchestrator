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


def _relevant(path: str, ignored_paths: tuple[str, ...]) -> bool:
    normalized = path.strip()
    ignored_roots = {item.rstrip("/") for item in ignored_paths}
    ignored_prefixes = tuple(f"{item}/" for item in ignored_roots)
    return (
        bool(normalized)
        and not normalized.startswith(DEFAULT_IGNORED_PREFIXES)
        and Path(normalized).name not in DEFAULT_IGNORED_NAMES
        and normalized not in ignored_roots
        and not normalized.startswith(ignored_prefixes)
    )


def _dirty_paths(
    root: Path,
    scope_paths: tuple[str, ...],
    ignored_paths: tuple[str, ...],
) -> list[str]:
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
        if _relevant(path, ignored_paths):
            dirty.append(path)
    return sorted(set(dirty))


def _scoped_tree_hash(
    root: Path,
    scope_paths: tuple[str, ...],
    ignored_paths: tuple[str, ...],
) -> str:
    args = ["ls-files", "-s", "-z"]
    if scope_paths:
        args.extend(("--", *scope_paths))
    raw = _git(root, *args, binary=True)
    relevant_entries = []
    for entry in bytes(raw).split(b"\0"):
        if not entry or b"\t" not in entry:
            continue
        path = entry.split(b"\t", 1)[1].decode("utf-8", errors="surrogateescape")
        if _relevant(path, ignored_paths):
            relevant_entries.append(entry)
    if not relevant_entries:
        raise SourcePolicyError("The configured delivery scope contains no tracked files.")
    digest = hashlib.sha256()
    for entry in sorted(relevant_entries):
        digest.update(entry)
        digest.update(b"\0")
    return digest.hexdigest()


def source_binding(
    root: Path,
    scope_paths: tuple[str, ...] = (),
    ignored_paths: tuple[str, ...] = (),
) -> dict[str, Any]:
    """Return a Git object binding without reading every source file."""
    head = str(_git(root, "rev-parse", "HEAD")).strip()
    if not head:
        raise SourcePolicyError("Strict verification requires at least one Git commit.")
    normalized_scope = tuple(dict.fromkeys(path.strip() for path in scope_paths if path.strip()))
    normalized_ignored = tuple(
        dict.fromkeys(path.strip().rstrip("/") for path in ignored_paths if path.strip())
    )
    for raw_path in (*normalized_scope, *normalized_ignored):
        candidate = Path(raw_path)
        if (
            candidate.is_absolute()
            or ".." in candidate.parts
            or raw_path.startswith(":")
            or raw_path.startswith("-")
        ):
            raise SourcePolicyError(f"Invalid delivery scope path: {raw_path}")
    tree_hash = _scoped_tree_hash(root, normalized_scope, normalized_ignored)
    return {
        "git_head": head,
        "source_tree_sha256": tree_hash,
        "scope_paths": list(normalized_scope),
        "ignored_paths": list(normalized_ignored),
        "dirty_paths": _dirty_paths(root, normalized_scope, normalized_ignored),
    }
