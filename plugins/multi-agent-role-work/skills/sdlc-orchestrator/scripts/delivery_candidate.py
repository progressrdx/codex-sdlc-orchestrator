"""Immutable delivery candidates and filesystem mutation manifests.

Verification must execute the exact candidate described here.  A Git candidate
is identified by one commit, its root tree, and a canonical path/mode/blob
manifest.  A lightweight workflow may use a content-addressed workspace
candidate, but materialization still goes through its frozen manifest rather
than copying the ambient worktree.
"""

from __future__ import annotations

import hashlib
import os
import re
import stat
import subprocess
import unicodedata
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Iterable, Iterator, Mapping


DEFAULT_EXCLUDED_PATHS = (".ai-workflow", "docs/requirements", ".idea")
DEFAULT_EXCLUDED_NAMES = frozenset({".DS_Store"})
FALLBACK_EXCLUDED_PARTS = frozenset(
    {".git", "__pycache__", ".pytest_cache", ".mypy_cache"}
)
SUPPORTED_BLOB_MODES = frozenset({"100644", "100755", "120000"})
WINDOWS_RESERVED_NAMES = frozenset(
    {"CON", "PRN", "AUX", "NUL"}
    | {f"COM{index}" for index in range(1, 10)}
    | {f"LPT{index}" for index in range(1, 10)}
)
WINDOWS_DRIVE_PATH = re.compile(r"^[A-Za-z]:")


class CandidateError(RuntimeError):
    """The requested candidate cannot be represented or materialized safely."""


@dataclass(frozen=True, order=True)
class CandidateEntry:
    """One immutable path/mode/blob record."""

    path: str
    mode: str
    blob_oid: str


@dataclass(frozen=True)
class DeliveryCandidate:
    """A content-addressed candidate that can be materialized without copytree."""

    kind: str
    repository: Path
    commit_oid: str | None
    tree_oid: str
    entries: tuple[CandidateEntry, ...]
    manifest_sha256: str

    @classmethod
    def from_repository(cls, root: Path) -> "DeliveryCandidate":
        """Build a candidate from the immutable tree referenced by ``HEAD``."""
        repository = root.resolve()
        commit_oid = _git_text(repository, "rev-parse", "--verify", "HEAD^{commit}").strip()
        if not commit_oid:
            raise CandidateError("Delivery verification requires at least one Git commit.")
        tree_oid = _git_text(repository, "rev-parse", f"{commit_oid}^{{tree}}").strip()
        raw = _git_bytes(
            repository,
            "ls-tree",
            "-rz",
            "--full-tree",
            commit_oid,
        )
        entries: list[CandidateEntry] = []
        symlink_entries: list[CandidateEntry] = []
        for record in raw.split(b"\0"):
            if not record:
                continue
            try:
                metadata, raw_path = record.split(b"\t", 1)
                raw_mode, object_type, raw_oid = metadata.split(b" ", 2)
            except ValueError as exc:
                raise CandidateError("Git returned a malformed candidate tree entry.") from exc
            mode = raw_mode.decode("ascii")
            object_kind = object_type.decode("ascii")
            blob_oid = raw_oid.decode("ascii")
            path = raw_path.decode("utf-8", errors="surrogateescape")
            _validate_manifest_path(path)
            if object_kind != "blob" or mode not in SUPPORTED_BLOB_MODES:
                if mode == "160000" or object_kind == "commit":
                    raise CandidateError(
                        f"Candidate contains an unmaterialized Git submodule: {path}"
                    )
                raise CandidateError(
                    f"Candidate contains unsupported Git entry {path}: {mode} {object_kind}"
                )
            entry = CandidateEntry(path=path, mode=mode, blob_oid=blob_oid)
            entries.append(entry)
            if mode == "120000":
                symlink_entries.append(entry)
        frozen_entries = tuple(sorted(entries))
        _validate_entry_paths(frozen_entries)
        symlinks = {
            entry.path: _git_blob(repository, entry.blob_oid).decode(
                "utf-8", errors="surrogateescape"
            )
            for entry in symlink_entries
        }
        _validate_symlink_closure(frozen_entries, symlinks)
        return cls(
            kind="git_commit",
            repository=repository,
            commit_oid=commit_oid,
            tree_oid=tree_oid,
            entries=frozen_entries,
            manifest_sha256=_manifest_digest(frozen_entries),
        )

    @classmethod
    def from_workspace(
        cls,
        root: Path,
        excluded_paths: tuple[str, ...] = (),
    ) -> "DeliveryCandidate":
        """Freeze current non-ignored workspace content into a candidate manifest.

        This compatibility path is used by lightweight modes that do not require
        a commit.  Each blob is content-addressed and rechecked at materialization,
        so later worktree changes cannot silently enter the verification snapshot.
        """
        repository = root.resolve()
        normalized_excluded = normalize_relative_paths(excluded_paths)
        try:
            hidden = hidden_index_paths(repository, (), normalized_excluded)
        except CandidateError:
            # Non-Git lightweight projects use the full-content fallback below.
            hidden = []
        if hidden:
            raise CandidateError(
                "Workspace candidate cannot use assume-unchanged or skip-worktree "
                "index flags: " + ",".join(hidden)
            )
        paths = _workspace_paths(repository, normalized_excluded)
        try:
            index_entries = _workspace_index_entries(repository, normalized_excluded)
            dirty_paths = set(
                git_status_paths(
                    repository,
                    excluded_paths=normalized_excluded,
                    include_ignored=False,
                )
            )
        except CandidateError:
            index_entries = {}
            dirty_paths = set(paths)
        entries: list[CandidateEntry] = []
        symlinks: dict[str, str] = {}
        for relative in paths:
            path = repository / relative
            clean_index_entry = index_entries.get(relative)
            if clean_index_entry is not None and relative not in dirty_paths:
                mode, blob_oid = clean_index_entry
                if mode not in SUPPORTED_BLOB_MODES:
                    raise CandidateError(
                        f"Unsupported workspace candidate Git entry: {relative} ({mode})"
                    )
                if mode == "120000":
                    payload = _git_blob(repository, blob_oid)
                    symlinks[relative] = payload.decode(
                        "utf-8", errors="surrogateescape"
                    )
                entries.append(
                    CandidateEntry(path=relative, mode=mode, blob_oid=blob_oid)
                )
                continue
            try:
                metadata = path.lstat()
            except OSError as exc:
                raise CandidateError(
                    f"Unable to inspect workspace candidate path: {relative}"
                ) from exc
            if stat.S_ISLNK(metadata.st_mode):
                target = os.readlink(path)
                payload = os.fsencode(target)
                mode = "120000"
                symlinks[relative] = target
            elif stat.S_ISREG(metadata.st_mode):
                payload = _read_file(path, relative)
                mode = "100755" if metadata.st_mode & 0o111 else "100644"
            else:
                raise CandidateError(f"Unsupported workspace candidate file type: {relative}")
            entries.append(
                CandidateEntry(
                    path=relative,
                    mode=mode,
                    blob_oid="sha256:" + hashlib.sha256(payload).hexdigest(),
                )
            )
        frozen_entries = tuple(sorted(entries))
        _validate_entry_paths(frozen_entries)
        _validate_symlink_closure(frozen_entries, symlinks)
        manifest_sha256 = _manifest_digest(frozen_entries)
        return cls(
            kind="workspace_content",
            repository=repository,
            commit_oid=None,
            tree_oid="sha256:" + manifest_sha256,
            entries=frozen_entries,
            manifest_sha256=manifest_sha256,
        )

    def metadata(self) -> dict[str, object]:
        return {
            "kind": self.kind,
            "commit_oid": self.commit_oid,
            "tree_oid": self.tree_oid,
            "manifest_sha256": self.manifest_sha256,
            "file_count": len(self.entries),
        }

    def selected_entries(
        self,
        scope_paths: tuple[str, ...] = (),
        excluded_paths: tuple[str, ...] = (),
    ) -> tuple[CandidateEntry, ...]:
        normalized_scope = normalize_relative_paths(scope_paths)
        normalized_excluded = normalize_relative_paths(excluded_paths)
        return tuple(
            entry
            for entry in self.entries
            if path_is_selected(entry.path, normalized_scope)
            and path_is_relevant(entry.path, normalized_excluded)
        )

    def selected_manifest_sha256(
        self,
        scope_paths: tuple[str, ...] = (),
        excluded_paths: tuple[str, ...] = (),
    ) -> str:
        selected = self.selected_entries(scope_paths, excluded_paths)
        if not selected:
            raise CandidateError("The configured delivery scope contains no candidate files.")
        return _manifest_digest(selected)

    def hidden_index_paths(
        self,
        scope_paths: tuple[str, ...] = (),
        excluded_paths: tuple[str, ...] = (),
    ) -> list[str]:
        if self.kind != "git_commit":
            return []
        return hidden_index_paths(self.repository, scope_paths, excluded_paths)

    def worktree_changes(
        self,
        scope_paths: tuple[str, ...] = (),
        excluded_paths: tuple[str, ...] = (),
    ) -> list[str]:
        """Return tracked, untracked, ignored, and hidden-index candidate gaps."""
        if self.kind != "git_commit":
            return []
        changed = set(
            git_status_paths(
                self.repository,
                scope_paths=scope_paths,
                excluded_paths=excluded_paths,
                include_ignored=True,
            )
        )
        changed.update(self.hidden_index_paths(scope_paths, excluded_paths))
        return sorted(changed)

    def materialize(self, destination: Path) -> None:
        """Write exactly this manifest to a new directory."""
        _validate_entry_paths(self.entries)
        if _manifest_digest(self.entries) != self.manifest_sha256:
            raise CandidateError("Candidate manifest digest does not match its entries.")
        destination.mkdir(parents=True, exist_ok=False)
        try:
            if self.kind == "git_commit":
                payloads = self._materialize_git_blobs(destination)
            elif self.kind == "workspace_content":
                payloads = self._materialize_workspace_blobs(destination)
            else:  # pragma: no cover - dataclass construction is public and defensive.
                raise CandidateError(f"Unknown delivery candidate kind: {self.kind}")
            _verify_materialized_tree(destination, self.entries, payloads)
        except Exception:
            _remove_partial_tree(destination)
            raise

    def _materialize_git_blobs(self, destination: Path) -> dict[str, bytes]:
        payloads: dict[str, bytes] = {}
        process = subprocess.Popen(
            ["git", "-C", str(self.repository), "cat-file", "--batch"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        try:
            if process.stdin is None or process.stdout is None:
                raise CandidateError(
                    "Unable to open Git object stream for candidate materialization."
                )
            for entry in self.entries:
                process.stdin.write(entry.blob_oid.encode("ascii") + b"\n")
                process.stdin.flush()
                header = process.stdout.readline().rstrip(b"\n")
                fields = header.split(b" ")
                if len(fields) != 3 or fields[1] != b"blob":
                    raise CandidateError(
                        f"Candidate blob is unavailable during materialization: {entry.path}"
                    )
                try:
                    size = int(fields[2])
                except ValueError as exc:
                    raise CandidateError("Git returned an invalid candidate blob size.") from exc
                payload = process.stdout.read(size)
                delimiter = process.stdout.read(1)
                if len(payload) != size or delimiter != b"\n":
                    raise CandidateError(
                        f"Git returned a truncated candidate blob: {entry.path}"
                    )
                _write_candidate_entry(destination, entry, payload)
                payloads[entry.path] = payload
        finally:
            if process.stdin is not None:
                process.stdin.close()
            try:
                return_code = process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
                return_code = -1
            if process.stdout is not None:
                process.stdout.close()
            if process.stderr is not None:
                process.stderr.close()
            if return_code != 0:
                raise CandidateError("Unable to materialize candidate Git objects.")
        return payloads

    def _materialize_workspace_blobs(self, destination: Path) -> dict[str, bytes]:
        payloads: dict[str, bytes] = {}
        for entry in self.entries:
            if entry.blob_oid.startswith("sha256:"):
                source = self.repository / entry.path
                try:
                    if entry.mode == "120000":
                        payload = os.fsencode(os.readlink(source))
                    else:
                        payload = _read_file(source, entry.path)
                except OSError as exc:
                    raise CandidateError(
                        f"Workspace candidate changed before materialization: {entry.path}"
                    ) from exc
                actual_oid = "sha256:" + hashlib.sha256(payload).hexdigest()
                if actual_oid != entry.blob_oid:
                    raise CandidateError(
                        f"Workspace candidate changed before materialization: {entry.path}"
                    )
            else:
                payload = _git_blob(self.repository, entry.blob_oid)
            _write_candidate_entry(destination, entry, payload)
            payloads[entry.path] = payload
        return payloads


def normalize_relative_paths(paths: tuple[str, ...]) -> tuple[str, ...]:
    normalized: list[str] = []
    collision_keys: dict[str, str] = {}
    for raw in paths:
        source = str(raw)
        if source != source.strip():
            raise CandidateError(f"Invalid repository-relative path: {raw}")
        rendered = source.replace("\\", "/").rstrip("/")
        if not rendered:
            continue
        _validate_repository_relative_path(rendered, label="repository-relative path")
        collision_key = _portable_path_key(rendered)
        existing = collision_keys.get(collision_key)
        if existing is not None and existing != rendered:
            raise CandidateError(
                "Repository-relative paths collide on a portable filesystem: "
                f"{existing}, {rendered}"
            )
        collision_keys[collision_key] = rendered
        if rendered not in normalized:
            normalized.append(rendered)
    return tuple(normalized)


def path_is_relevant(path: str, excluded_paths: tuple[str, ...] = ()) -> bool:
    normalized = path.strip().rstrip("/")
    if not normalized or Path(normalized).name in DEFAULT_EXCLUDED_NAMES:
        return False
    exclusions = tuple(DEFAULT_EXCLUDED_PATHS) + tuple(excluded_paths)
    return not any(
        normalized == excluded or normalized.startswith(excluded.rstrip("/") + "/")
        for excluded in exclusions
        if excluded
    )


def path_is_selected(path: str, scope_paths: tuple[str, ...] = ()) -> bool:
    if not scope_paths:
        return True
    normalized = path.rstrip("/")
    return any(
        normalized == scope
        or normalized.startswith(scope.rstrip("/") + "/")
        or scope.startswith(normalized + "/")
        for scope in scope_paths
    )


def git_status_paths(
    root: Path,
    *,
    scope_paths: tuple[str, ...] = (),
    excluded_paths: tuple[str, ...] = (),
    include_ignored: bool = False,
) -> list[str]:
    normalized_scope = normalize_relative_paths(scope_paths)
    normalized_excluded = normalize_relative_paths(excluded_paths)
    arguments = ["status", "--porcelain=v1", "-z", "--untracked-files=all"]
    if include_ignored:
        arguments.append("--ignored=matching")
    if normalized_scope:
        arguments.extend(("--", *normalized_scope))
    raw = _git_bytes(root.resolve(), *arguments)
    records = raw.split(b"\0")
    changed: list[str] = []
    index = 0
    while index < len(records):
        record = records[index]
        index += 1
        if not record:
            continue
        path = record[3:].decode("utf-8", errors="surrogateescape") if len(record) > 3 else ""
        paths = [path]
        if any(marker in record[:2] for marker in (b"R", b"C")) and index < len(records):
            paths.append(records[index].decode("utf-8", errors="surrogateescape"))
            index += 1
        changed.extend(
            item
            for item in paths
            if path_is_selected(item, normalized_scope)
            and path_is_relevant(item, normalized_excluded)
        )
    return sorted(set(changed))


def hidden_index_paths(
    root: Path,
    scope_paths: tuple[str, ...] = (),
    excluded_paths: tuple[str, ...] = (),
) -> list[str]:
    normalized_scope = normalize_relative_paths(scope_paths)
    normalized_excluded = normalize_relative_paths(excluded_paths)
    arguments = ["ls-files", "-v", "-z"]
    if normalized_scope:
        arguments.extend(("--", *normalized_scope))
    raw = _git_bytes(root.resolve(), *arguments)
    hidden: list[str] = []
    for record in raw.split(b"\0"):
        if len(record) < 3 or record[1:2] != b" ":
            continue
        marker = chr(record[0])
        if marker != "S" and not marker.islower():
            continue
        path = record[2:].decode("utf-8", errors="surrogateescape")
        if path_is_selected(path, normalized_scope) and path_is_relevant(
            path, normalized_excluded
        ):
            hidden.append(path)
    return sorted(set(hidden))


def filesystem_manifest(
    root: Path,
    excluded_paths: tuple[str, ...] = (),
) -> dict[str, tuple[str, int, str]]:
    """Hash a materialized tree without consulting mutable Git metadata."""
    normalized_excluded = normalize_relative_paths(excluded_paths)
    base = root.resolve()
    manifest: dict[str, tuple[str, int, str]] = {}
    collision_paths: dict[str, str] = {}
    pending = [base]
    while pending:
        directory = pending.pop()
        try:
            children = list(os.scandir(directory))
        except OSError as exc:
            raise CandidateError(f"Unable to inspect verification snapshot: {directory}") from exc
        for child in children:
            path = Path(child.path)
            relative = path.relative_to(base).as_posix()
            collision_key = _portable_path_key(relative)
            existing = collision_paths.get(collision_key)
            if existing is not None and existing != relative:
                raise CandidateError(
                    "Verification snapshot paths collide by case or Unicode normalization: "
                    f"{existing}, {relative}"
                )
            collision_paths[collision_key] = relative
            if _path_is_explicitly_excluded(relative, normalized_excluded):
                continue
            try:
                metadata = child.stat(follow_symlinks=False)
            except OSError as exc:
                raise CandidateError(
                    f"Unable to inspect verification snapshot path: {relative}"
                ) from exc
            permissions = stat.S_IMODE(metadata.st_mode)
            if stat.S_ISDIR(metadata.st_mode):
                pending.append(path)
            elif stat.S_ISLNK(metadata.st_mode):
                target = os.fsencode(os.readlink(path))
                manifest[relative] = (
                    "symlink",
                    permissions,
                    hashlib.sha256(target).hexdigest(),
                )
            elif stat.S_ISREG(metadata.st_mode):
                manifest[relative] = (
                    "file",
                    permissions,
                    _file_sha256(path, relative),
                )
            else:
                manifest[relative] = (
                    "special",
                    permissions,
                    hashlib.sha256(str(metadata.st_mode).encode("ascii")).hexdigest(),
                )
    return manifest


def prepare_output_subtrees(root: Path, output_paths: tuple[str, ...]) -> tuple[Path, ...]:
    """Create empty output directories without following repository links."""
    normalized = normalize_relative_paths(output_paths)
    base = root.resolve()
    roots: list[Path] = []
    for relative in normalized:
        output = base.joinpath(*relative.split("/"))
        current = base
        for part in relative.split("/"):
            current = current / part
            if current.exists() or current.is_symlink():
                try:
                    metadata = current.lstat()
                except OSError as exc:
                    raise CandidateError(
                        f"Unable to inspect generated output path: {relative}"
                    ) from exc
                if not stat.S_ISDIR(metadata.st_mode) or stat.S_ISLNK(metadata.st_mode):
                    raise CandidateError(
                        f"Generated output path must be a real directory: {relative}"
                    )
            else:
                try:
                    current.mkdir()
                except OSError as exc:
                    raise CandidateError(
                        f"Unable to create generated output directory: {relative}"
                    ) from exc
        resolved = Path(os.path.realpath(output))
        try:
            resolved.relative_to(Path(os.path.realpath(base)))
        except ValueError as exc:
            raise CandidateError(
                f"Generated output path escapes the verification snapshot: {relative}"
            ) from exc
        roots.append(output)
    return tuple(roots)


def validate_output_subtrees(root: Path, output_paths: tuple[str, ...]) -> None:
    """Fail closed on output links, aliases, special files, or escaped roots.

    The OS sandbox prevents writes through links.  This audit is deliberately
    stricter: outputs may contain only real directories and single-link regular
    files, making that property independently checkable before and after every
    command.
    """
    normalized = normalize_relative_paths(output_paths)
    base = root.resolve()
    base_real = Path(os.path.realpath(base))
    collision_paths: dict[str, str] = {}
    for relative_root in normalized:
        output = base.joinpath(*relative_root.split("/"))
        try:
            root_metadata = output.lstat()
        except OSError as exc:
            raise CandidateError(
                f"Generated output directory is unavailable: {relative_root}"
            ) from exc
        if not stat.S_ISDIR(root_metadata.st_mode) or stat.S_ISLNK(root_metadata.st_mode):
            raise CandidateError(
                f"Generated output root must remain a real directory: {relative_root}"
            )
        try:
            Path(os.path.realpath(output)).relative_to(base_real)
        except ValueError as exc:
            raise CandidateError(
                f"Generated output root escapes the verification snapshot: {relative_root}"
            ) from exc
        pending = [output]
        while pending:
            directory = pending.pop()
            try:
                children = list(os.scandir(directory))
            except OSError as exc:
                raise CandidateError(
                    f"Unable to inspect generated output directory: {relative_root}"
                ) from exc
            for child in children:
                path = Path(child.path)
                relative = path.relative_to(base).as_posix()
                collision_key = _portable_path_key(relative)
                existing = collision_paths.get(collision_key)
                if existing is not None and existing != relative:
                    raise CandidateError(
                        "Generated outputs collide by case or Unicode normalization: "
                        f"{existing}, {relative}"
                    )
                collision_paths[collision_key] = relative
                try:
                    metadata = child.stat(follow_symlinks=False)
                except OSError as exc:
                    raise CandidateError(
                        f"Unable to inspect generated output path: {relative}"
                    ) from exc
                if stat.S_ISDIR(metadata.st_mode):
                    pending.append(path)
                elif stat.S_ISLNK(metadata.st_mode):
                    raise CandidateError(
                        f"Generated outputs may not contain symbolic links: {relative}"
                    )
                elif stat.S_ISREG(metadata.st_mode):
                    if metadata.st_nlink != 1:
                        raise CandidateError(
                            f"Generated outputs may not contain hard links: {relative}"
                        )
                else:
                    raise CandidateError(
                        f"Generated outputs may not contain special files: {relative}"
                    )


def changed_manifest_paths(
    baseline: Mapping[str, tuple[str, int, str]],
    current: Mapping[str, tuple[str, int, str]],
) -> list[str]:
    return sorted(
        path
        for path in set(baseline) | set(current)
        if baseline.get(path) != current.get(path)
    )


def _git_text(root: Path, *arguments: str) -> str:
    try:
        return subprocess.check_output(
            ["git", "-C", str(root), *arguments],
            text=True,
            stderr=subprocess.DEVNULL,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise CandidateError(
            "Unable to inspect candidate Git state: " + " ".join(arguments)
        ) from exc


def _git_bytes(root: Path, *arguments: str) -> bytes:
    try:
        return subprocess.check_output(
            ["git", "-C", str(root), *arguments],
            stderr=subprocess.DEVNULL,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise CandidateError(
            "Unable to inspect candidate Git state: " + " ".join(arguments)
        ) from exc


def _git_blob(root: Path, blob_oid: str) -> bytes:
    return _git_bytes(root, "cat-file", "blob", blob_oid)


def _workspace_paths(root: Path, excluded_paths: tuple[str, ...]) -> list[str]:
    try:
        raw = _git_bytes(
            root,
            "ls-files",
            "--cached",
            "--others",
            "--exclude-standard",
            "-z",
        )
        candidates = [
            record.decode("utf-8", errors="surrogateescape")
            for record in raw.split(b"\0")
            if record
        ]
    except CandidateError:
        candidates = [
            path.relative_to(root).as_posix()
            for path in root.rglob("*")
            if (path.is_file() or path.is_symlink())
            and not any(
                part in FALLBACK_EXCLUDED_PARTS
                for part in path.relative_to(root).parts
            )
        ]
    return sorted(
        {
            path
            for path in candidates
            if path_is_relevant(path, excluded_paths)
        }
    )


def _workspace_index_entries(
    root: Path,
    excluded_paths: tuple[str, ...],
) -> dict[str, tuple[str, str]]:
    raw = _git_bytes(root, "ls-files", "-s", "-z")
    entries: dict[str, tuple[str, str]] = {}
    for record in raw.split(b"\0"):
        if not record or b"\t" not in record:
            continue
        metadata, raw_path = record.split(b"\t", 1)
        fields = metadata.split(b" ")
        if len(fields) != 3 or fields[2] != b"0":
            continue
        path = raw_path.decode("utf-8", errors="surrogateescape")
        if path_is_relevant(path, excluded_paths):
            entries[path] = (fields[0].decode("ascii"), fields[1].decode("ascii"))
    return entries


def _manifest_digest(entries: Iterable[CandidateEntry]) -> str:
    digest = hashlib.sha256()
    for entry in sorted(entries):
        digest.update(entry.path.encode("utf-8", errors="surrogateescape"))
        digest.update(b"\0")
        digest.update(entry.mode.encode("ascii"))
        digest.update(b"\0")
        digest.update(entry.blob_oid.encode("ascii"))
        digest.update(b"\0")
    return digest.hexdigest()


def _portable_path_key(path: str) -> str:
    """Return the conservative identity shared by macOS and Windows filesystems."""
    return "/".join(
        unicodedata.normalize("NFC", part).casefold() for part in path.split("/")
    )


def _validate_windows_segment(segment: str, path: str) -> None:
    if not segment or segment[-1:] in {" ", "."}:
        raise CandidateError(f"Candidate contains a Windows-unsafe path: {path}")
    if any(ord(character) < 32 for character in segment):
        raise CandidateError(f"Candidate contains a control character in its path: {path}")
    if any(character in '<>:"|?*' for character in segment):
        raise CandidateError(f"Candidate contains a Windows-unsafe path: {path}")
    stem = segment.split(".", 1)[0].upper()
    if stem in WINDOWS_RESERVED_NAMES:
        raise CandidateError(f"Candidate contains a Windows-reserved path: {path}")


def _validate_repository_relative_path(path: str, *, label: str) -> None:
    if (
        not path
        or "\x00" in path
        or "\\" in path
        or path.startswith(("/", "//", "-", ":"))
        or WINDOWS_DRIVE_PATH.match(path)
    ):
        raise CandidateError(f"Invalid {label}: {path}")
    raw_parts = path.split("/")
    if any(part in {"", ".", ".."} for part in raw_parts):
        raise CandidateError(f"Invalid {label}: {path}")
    candidate = PurePosixPath(path)
    if candidate.is_absolute() or tuple(candidate.parts) != tuple(raw_parts):
        raise CandidateError(f"Invalid {label}: {path}")
    for segment in raw_parts:
        _validate_windows_segment(segment, path)


def _validate_entry_paths(entries: tuple[CandidateEntry, ...]) -> None:
    """Reject paths that cannot be materialized uniquely on supported hosts."""
    seen_nodes: dict[str, tuple[str, str]] = {}
    for entry in entries:
        _validate_manifest_path(entry.path)
        parts = entry.path.split("/")
        for index in range(1, len(parts) + 1):
            node = "/".join(parts[:index])
            node_type = "entry" if index == len(parts) else "directory"
            key = _portable_path_key(node)
            existing = seen_nodes.get(key)
            if existing is None:
                seen_nodes[key] = (node, node_type)
                continue
            existing_node, existing_type = existing
            if existing_node != node:
                raise CandidateError(
                    "Candidate paths collide by case or Unicode normalization: "
                    f"{existing_node}, {node}"
                )
            if existing_type != node_type and "entry" in {existing_type, node_type}:
                raise CandidateError(
                    f"Candidate path is both a file and a directory: {node}"
                )
            if existing_type == node_type == "entry":
                raise CandidateError(f"Candidate contains a duplicate path: {node}")
        if entry.mode not in SUPPORTED_BLOB_MODES:
            raise CandidateError(
                f"Candidate contains an unsupported entry mode: {entry.path} ({entry.mode})"
            )


def _validate_manifest_path(path: str) -> None:
    try:
        _validate_repository_relative_path(path, label="candidate path")
    except CandidateError as exc:
        raise CandidateError(f"Candidate contains an unsafe path: {path}") from exc


def _validate_symlink_closure(
    entries: tuple[CandidateEntry, ...],
    symlinks: Mapping[str, str],
) -> None:
    nodes = {""}
    for entry in entries:
        nodes.add(entry.path)
        parts = entry.path.split("/")
        nodes.update("/".join(parts[:index]) for index in range(1, len(parts)))
    for path, target in symlinks.items():
        if (
            not target
            or "\x00" in target
            or "\\" in target
            or PurePosixPath(target).is_absolute()
            or target.startswith(("/", "//"))
            or WINDOWS_DRIVE_PATH.match(target)
        ):
            raise CandidateError(
                "Isolated verification cannot safely materialize a symbolic link outside "
                f"the repository candidate tree: {path} -> {target}"
            )
        for segment in target.split("/"):
            if segment in {"", ".", ".."}:
                continue
            _validate_windows_segment(segment, target)
        initial = _normalize_virtual_path(path.rpartition("/")[0], target)
        resolved = _expand_virtual_symlinks(initial, symlinks)
        if resolved not in nodes:
            raise CandidateError(
                "Candidate symbolic link target is not present in the candidate: "
                f"{path} -> {target}"
            )


def _normalize_virtual_path(base: str, target: str, remainder: tuple[str, ...] = ()) -> str:
    parts = [item for item in base.split("/") if item]
    for item in tuple(target.split("/")) + remainder:
        if item in {"", "."}:
            continue
        if item == "..":
            if not parts:
                raise CandidateError(
                    "Isolated verification cannot safely materialize a symbolic link outside "
                    "the repository candidate tree."
                )
            parts.pop()
        else:
            parts.append(item)
    return "/".join(parts)


def _expand_virtual_symlinks(path: str, symlinks: Mapping[str, str]) -> str:
    current = path
    seen: set[str] = set()
    while True:
        parts = tuple(item for item in current.split("/") if item)
        replaced = False
        for index in range(len(parts)):
            prefix = "/".join(parts[: index + 1])
            target = symlinks.get(prefix)
            if target is None:
                continue
            if prefix in seen:
                raise CandidateError(f"Candidate symbolic link cycle detected at: {prefix}")
            seen.add(prefix)
            base = prefix.rpartition("/")[0]
            current = _normalize_virtual_path(base, target, parts[index + 1 :])
            replaced = True
            break
        if not replaced:
            return current


def _write_candidate_entry(destination: Path, entry: CandidateEntry, payload: bytes) -> None:
    target = destination / entry.path
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        if entry.mode == "120000":
            os.symlink(os.fsdecode(payload), target)
        else:
            target.write_bytes(payload)
            target.chmod(0o755 if entry.mode == "100755" else 0o644)
    except OSError as exc:
        raise CandidateError(f"Unable to materialize candidate path: {entry.path}") from exc


def _blob_oid(payload: bytes, expected: str) -> str:
    framed = b"blob " + str(len(payload)).encode("ascii") + b"\0" + payload
    if expected.startswith("sha256:"):
        return "sha256:" + hashlib.sha256(payload).hexdigest()
    if len(expected) == 40:
        return hashlib.sha1(framed).hexdigest()
    if len(expected) == 64:
        return hashlib.sha256(framed).hexdigest()
    raise CandidateError(f"Candidate contains an unsupported blob identifier: {expected}")


def _verify_materialized_tree(
    destination: Path,
    entries: tuple[CandidateEntry, ...],
    payloads: Mapping[str, bytes],
) -> None:
    """Re-read every materialized path and reject any omitted or extra object."""
    expected = {entry.path: entry for entry in entries}
    expected_directories = {
        "/".join(entry.path.split("/")[:index])
        for entry in entries
        for index in range(1, len(entry.path.split("/")))
    }
    if set(payloads) != set(expected):
        raise CandidateError("Candidate materialization did not produce every manifest payload.")

    seen: set[str] = set()
    collision_nodes: dict[str, str] = {}
    pending = [destination]
    while pending:
        directory = pending.pop()
        try:
            children = list(os.scandir(directory))
        except OSError as exc:
            raise CandidateError(
                f"Unable to re-inspect materialized candidate directory: {directory}"
            ) from exc
        for child in children:
            path = Path(child.path)
            relative = path.relative_to(destination).as_posix()
            key = _portable_path_key(relative)
            other = collision_nodes.get(key)
            if other is not None and other != relative:
                raise CandidateError(
                    "Materialized paths collide by case or Unicode normalization: "
                    f"{other}, {relative}"
                )
            collision_nodes[key] = relative
            try:
                metadata = child.stat(follow_symlinks=False)
            except OSError as exc:
                raise CandidateError(
                    f"Unable to re-inspect materialized candidate path: {relative}"
                ) from exc
            if stat.S_ISDIR(metadata.st_mode):
                if relative in expected:
                    raise CandidateError(
                        f"Materialized candidate path has the wrong type: {relative}"
                    )
                if relative not in expected_directories:
                    raise CandidateError(
                        f"Materialized candidate contains an extra directory: {relative}"
                    )
                pending.append(path)
                continue
            entry = expected.get(relative)
            if entry is None:
                raise CandidateError(
                    f"Materialized candidate contains an extra path: {relative}"
                )
            payload = payloads[relative]
            if _blob_oid(payload, entry.blob_oid) != entry.blob_oid:
                raise CandidateError(
                    f"Candidate blob content does not match its identifier: {relative}"
                )
            if entry.mode == "120000":
                if not stat.S_ISLNK(metadata.st_mode):
                    raise CandidateError(
                        f"Materialized candidate path has the wrong type: {relative}"
                    )
                actual_payload = os.fsencode(os.readlink(path))
            else:
                if not stat.S_ISREG(metadata.st_mode):
                    raise CandidateError(
                        f"Materialized candidate path has the wrong type: {relative}"
                    )
                expected_permissions = 0o755 if entry.mode == "100755" else 0o644
                if stat.S_IMODE(metadata.st_mode) != expected_permissions:
                    raise CandidateError(
                        f"Materialized candidate path has the wrong mode: {relative}"
                    )
                actual_payload = _read_file(path, relative)
            if actual_payload != payload:
                raise CandidateError(
                    f"Materialized candidate path has the wrong content: {relative}"
                )
            seen.add(relative)
    missing = sorted(set(expected) - seen)
    if missing:
        raise CandidateError(
            "Materialized candidate omitted manifest paths: " + ",".join(missing)
        )


def _read_file(path: Path, relative: str) -> bytes:
    try:
        return path.read_bytes()
    except OSError as exc:
        raise CandidateError(f"Unable to read candidate file: {relative}") from exc


def _file_sha256(path: Path, relative: str) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            while True:
                block = handle.read(64 * 1024)
                if not block:
                    break
                digest.update(block)
    except OSError as exc:
        raise CandidateError(f"Unable to hash verification snapshot path: {relative}") from exc
    return digest.hexdigest()


def _path_is_explicitly_excluded(path: str, excluded_paths: tuple[str, ...]) -> bool:
    normalized = path.rstrip("/")
    return any(
        normalized == excluded or normalized.startswith(excluded + "/")
        for excluded in excluded_paths
    )


def _remove_partial_tree(root: Path) -> None:
    if not root.exists():
        return
    for directory, directories, files in os.walk(root, topdown=False, followlinks=False):
        for name in files:
            (Path(directory) / name).unlink(missing_ok=True)
        for name in directories:
            path = Path(directory) / name
            if path.is_symlink():
                path.unlink(missing_ok=True)
            else:
                path.rmdir()
    root.rmdir()
