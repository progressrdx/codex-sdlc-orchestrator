"""Deterministic plugin identity and source/runtime provenance diagnostics.

The payload digest deliberately excludes the generated provenance record and
normalizes the Codex cachebuster in ``plugin.json``.  This makes it possible to
derive a cachebuster from the payload without making the digest depend on
itself.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import unicodedata
from enum import Enum
from pathlib import Path
from typing import Any, Mapping, Sequence


SCHEMA_VERSION = 1
MANIFEST_PATH = Path(".codex-plugin/plugin.json")
PROVENANCE_FILENAME = "provenance.json"
PROVENANCE_PATH = Path(".codex-plugin") / PROVENANCE_FILENAME
PROVENANCE_TEMP_PREFIX = ".provenance."
DEFAULT_ENTRY_PATH = Path("skills/sdlc-orchestrator/scripts/workflow.py")
NORMALIZED_CACHEBUSTER = "<codex-payload>"

STATUS_OK = "OK"
STATUS_SOURCE_NEWER = "SOURCE_NEWER"
STATUS_VERSION_COLLISION = "VERSION_COLLISION"
STATUS_RUNTIME_TAMPERED = "RUNTIME_TAMPERED"
STATUS_SOURCE_UNAVAILABLE = "SOURCE_UNAVAILABLE"
STATUS_RESTART_REQUIRED = "RESTART_REQUIRED"

HARD_FAILURE_STATUSES = frozenset(
    {STATUS_VERSION_COLLISION, STATUS_RUNTIME_TAMPERED}
)
_HEX_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_TRANSIENT_DIRECTORY_NAMES = frozenset(
    {".git", "__pycache__", ".pytest_cache", ".mypy_cache"}
)
_TRANSIENT_FILE_NAMES = frozenset({".DS_Store"})


class ProvenanceError(RuntimeError):
    """The plugin identity or provenance record cannot be inspected safely."""


class ProvenanceHardFailure(ProvenanceError):
    """The runtime must not continue because its identity is ambiguous."""


class DoctorStatus(str, Enum):
    OK = STATUS_OK
    SOURCE_NEWER = STATUS_SOURCE_NEWER
    VERSION_COLLISION = STATUS_VERSION_COLLISION
    RUNTIME_TAMPERED = STATUS_RUNTIME_TAMPERED
    SOURCE_UNAVAILABLE = STATUS_SOURCE_UNAVAILABLE
    RESTART_REQUIRED = STATUS_RESTART_REQUIRED


def default_plugin_root() -> Path:
    """Return the packaged plugin root containing this module."""
    return Path(__file__).resolve().parents[3]


def find_plugin_root(start: Path | str) -> Path:
    """Find the closest ancestor containing ``.codex-plugin/plugin.json``."""
    candidate = Path(start).expanduser().resolve()
    if candidate.is_file():
        candidate = candidate.parent
    for path in (candidate, *candidate.parents):
        if (path / MANIFEST_PATH).is_file():
            return path
    raise ProvenanceError(f"No plugin manifest found from: {candidate}")


def _plugin_root(value: Path | str) -> Path:
    root = Path(value).expanduser().resolve()
    if not root.is_dir():
        raise ProvenanceError(f"Plugin root is unavailable: {root}")
    if not (root / MANIFEST_PATH).is_file():
        raise ProvenanceError(f"Plugin manifest is unavailable: {root / MANIFEST_PATH}")
    return root


def _manifest(root: Path) -> dict[str, Any]:
    path = root / MANIFEST_PATH
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ProvenanceError(f"Unable to read plugin manifest: {path}") from exc
    if not isinstance(value, dict):
        raise ProvenanceError(f"Plugin manifest must contain a JSON object: {path}")
    for field in ("name", "version"):
        if not isinstance(value.get(field), str) or not value[field].strip():
            raise ProvenanceError(f"Plugin manifest has no valid {field!r}: {path}")
    return value


def normalized_version_for_payload(version: str) -> str:
    """Replace only the Codex cachebuster while preserving the base version."""
    marker = "+codex."
    if marker not in version:
        return version
    prefix, _cachebuster = version.split(marker, 1)
    return f"{prefix}+codex.{NORMALIZED_CACHEBUSTER}"


def _canonical_manifest_bytes(root: Path) -> bytes:
    manifest = _manifest(root)
    manifest["version"] = normalized_version_for_payload(manifest["version"])
    return (
        json.dumps(
            manifest,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode("utf-8")


def _excluded(relative: Path) -> bool:
    if relative == PROVENANCE_PATH:
        return True
    if (
        relative.parent == PROVENANCE_PATH.parent
        and relative.name.startswith(PROVENANCE_TEMP_PREFIX)
    ):
        return True
    if any(part in _TRANSIENT_DIRECTORY_NAMES for part in relative.parts):
        return True
    if relative.name in _TRANSIENT_FILE_NAMES or relative.suffix == ".pyc":
        return True
    return False


def _payload_paths(root: Path) -> list[Path]:
    paths: list[Path] = []
    for path in root.rglob("*"):
        relative = path.relative_to(root)
        if _excluded(relative):
            continue
        if path.is_symlink() or path.is_file():
            paths.append(path)
    return sorted(
        paths,
        key=lambda item: unicodedata.normalize(
            "NFC", item.relative_to(root).as_posix()
        ).encode("utf-8"),
    )


def _payload_bytes(root: Path, path: Path) -> tuple[bytes, bytes]:
    relative = path.relative_to(root)
    if path.is_symlink():
        try:
            return b"symlink", os.readlink(path).encode("utf-8", errors="surrogateescape")
        except OSError as exc:
            raise ProvenanceError(f"Unable to read plugin symlink: {relative}") from exc
    if relative == MANIFEST_PATH:
        return b"file", _canonical_manifest_bytes(root)
    try:
        return b"file", path.read_bytes()
    except OSError as exc:
        raise ProvenanceError(f"Unable to read plugin payload: {relative}") from exc


def compute_payload_sha256(plugin_root: Path | str) -> str:
    """Hash a plugin tree using stable path framing and canonical manifest data."""
    root = _plugin_root(plugin_root)
    digest = hashlib.sha256()
    digest.update(b"codex-plugin-payload-v1\0")
    for path in _payload_paths(root):
        relative = unicodedata.normalize(
            "NFC", path.relative_to(root).as_posix()
        ).encode("utf-8", errors="surrogateescape")
        kind, payload = _payload_bytes(root, path)
        digest.update(len(relative).to_bytes(8, "big"))
        digest.update(relative)
        digest.update(len(kind).to_bytes(8, "big"))
        digest.update(kind)
        digest.update(len(payload).to_bytes(8, "big"))
        digest.update(payload)
    return digest.hexdigest()


def _relative_entry(root: Path, entry_path: Path | str | None) -> tuple[Path, Path]:
    raw = Path(entry_path) if entry_path is not None else DEFAULT_ENTRY_PATH
    if raw.is_absolute():
        resolved = raw.expanduser().resolve()
    else:
        if ".." in raw.parts:
            raise ProvenanceError(f"Entry path must remain within the plugin: {raw}")
        resolved = (root / raw).resolve()
    try:
        relative = resolved.relative_to(root)
    except ValueError as exc:
        raise ProvenanceError(f"Entry path is outside the plugin root: {resolved}") from exc
    if not resolved.is_file():
        raise ProvenanceError(f"Plugin entry is unavailable: {resolved}")
    return relative, resolved


def _run_git(root: Path, *args: str) -> str | None:
    try:
        result = subprocess.run(
            ["git", "-C", str(root), *args],
            check=False,
            capture_output=True,
            text=True,
        )
    except OSError:
        return None
    if result.returncode != 0:
        return None
    return result.stdout


def _git_metadata(root: Path) -> tuple[str | None, bool | None]:
    repository_text = _run_git(root, "rev-parse", "--show-toplevel")
    revision_text = _run_git(root, "rev-parse", "HEAD")
    if repository_text is None or revision_text is None:
        return None, None
    repository = Path(repository_text.strip()).resolve()
    try:
        scoped_path = root.relative_to(repository).as_posix()
    except ValueError:
        return None, None
    status = _run_git(
        repository,
        "status",
        "--porcelain=v1",
        "--untracked-files=all",
        "--",
        scoped_path,
    )
    if status is None:
        return revision_text.strip(), None
    provenance_suffix = PROVENANCE_PATH.as_posix()
    material_lines = []
    for line in status.splitlines():
        # The generated record is outside the payload by definition and must not
        # make an otherwise reproducible build report itself as dirty.
        if line.replace("\\", "/").endswith(provenance_suffix):
            continue
        material_lines.append(line)
    return revision_text.strip(), bool(material_lines)


def inspect_runtime(
    plugin_root: Path | str,
    *,
    entry_path: Path | str | None = None,
) -> dict[str, Any]:
    """Return the observable identity of a source or installed plugin tree."""
    root = _plugin_root(plugin_root)
    manifest = _manifest(root)
    relative_entry, entry = _relative_entry(root, entry_path)
    revision, dirty = _git_metadata(root)
    return {
        "schema_version": SCHEMA_VERSION,
        "plugin_name": manifest["name"],
        "version": manifest["version"],
        "runtime_root": str(root),
        "entry_path": relative_entry.as_posix(),
        "entry_sha256": hashlib.sha256(entry.read_bytes()).hexdigest(),
        "payload_sha256": compute_payload_sha256(root),
        "git_revision": revision,
        "dirty": dirty,
    }


def build_embedded_provenance(
    plugin_root: Path | str,
    *,
    entry_path: Path | str | None = None,
) -> dict[str, Any]:
    """Build the relocatable record embedded in an installed plugin package."""
    identity = inspect_runtime(plugin_root, entry_path=entry_path)
    return {
        "schema_version": SCHEMA_VERSION,
        "plugin_name": identity["plugin_name"],
        "version": identity["version"],
        "entry_path": identity["entry_path"],
        "entry_sha256": identity["entry_sha256"],
        "payload_sha256": identity["payload_sha256"],
        "git_revision": identity["git_revision"],
        "dirty": identity["dirty"],
    }


def _json_bytes(value: Mapping[str, Any]) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    ).encode("utf-8")


def write_embedded_provenance(
    plugin_root: Path | str,
    *,
    output_path: Path | str | None = None,
    entry_path: Path | str | None = None,
) -> dict[str, Any]:
    """Atomically write a relocatable provenance record and return its data."""
    root = _plugin_root(plugin_root)
    value = build_embedded_provenance(root, entry_path=entry_path)
    output = Path(output_path).expanduser() if output_path else root / PROVENANCE_PATH
    if not output.is_absolute():
        output = root / output
    output = output.resolve()
    try:
        output_relative = output.relative_to(root)
    except ValueError:
        output_relative = None
    if output_relative is not None and output_relative != PROVENANCE_PATH:
        raise ProvenanceError(
            "An embedded provenance record inside the plugin must use "
            f"{PROVENANCE_PATH.as_posix()}"
        )
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=str(output.parent),
            prefix=PROVENANCE_TEMP_PREFIX,
            delete=False,
        ) as handle:
            temporary = Path(handle.name)
            handle.write(_json_bytes(value))
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, output)
    except OSError as exc:
        if temporary is not None:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass
        raise ProvenanceError(f"Unable to write provenance record: {output}") from exc
    return value


def load_embedded_provenance(plugin_root: Path | str) -> dict[str, Any] | None:
    root = _plugin_root(plugin_root)
    path = root / PROVENANCE_PATH
    if not path.exists():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ProvenanceError(f"Unable to read embedded provenance: {path}") from exc
    if not isinstance(value, dict):
        raise ProvenanceError(f"Embedded provenance must contain a JSON object: {path}")
    required_strings = (
        "plugin_name",
        "version",
        "entry_path",
        "entry_sha256",
        "payload_sha256",
    )
    if value.get("schema_version") != SCHEMA_VERSION or any(
        not isinstance(value.get(field), str) or not value[field]
        for field in required_strings
    ):
        raise ProvenanceError(f"Embedded provenance has an invalid schema: {path}")
    for field in ("entry_sha256", "payload_sha256"):
        if not _HEX_SHA256.fullmatch(value[field]):
            raise ProvenanceError(f"Embedded provenance has an invalid {field}: {path}")
    return value


def _runtime_matches_embedded(
    runtime: Mapping[str, Any], embedded: Mapping[str, Any]
) -> bool:
    return all(
        runtime.get(field) == embedded.get(field)
        for field in (
            "plugin_name",
            "version",
            "entry_path",
            "entry_sha256",
            "payload_sha256",
        )
    )


def _report(
    status: str,
    message: str,
    *,
    runtime: Mapping[str, Any],
    source: Mapping[str, Any] | None,
    embedded: Mapping[str, Any] | None,
    loaded_identity: Mapping[str, Any] | None,
) -> dict[str, Any]:
    return {
        "status": status,
        "hard_failure": status in HARD_FAILURE_STATUSES,
        "message": message,
        "runtime": dict(runtime),
        "source": dict(source) if source is not None else None,
        "embedded": dict(embedded) if embedded is not None else None,
        "loaded_identity": (
            dict(loaded_identity) if loaded_identity is not None else None
        ),
    }


def doctor_runtime(
    runtime_root: Path | str,
    *,
    source_root: Path | str | None = None,
    entry_path: Path | str | None = None,
    loaded_version: str | None = None,
    loaded_payload_sha256: str | None = None,
    loaded_entry_sha256: str | None = None,
) -> dict[str, Any]:
    """Compare source, installed runtime, embedded, and already-loaded identities.

    Status precedence is intentional: an installed tree that no longer matches
    its embedded record is tampered regardless of source state; equal declared
    versions with unequal payloads are a version collision and cannot be
    repaired by guessing which tree is authoritative.
    """
    runtime = inspect_runtime(runtime_root, entry_path=entry_path)
    embedded = load_embedded_provenance(runtime_root)
    loaded_items = {
        key: value
        for key, value in {
            "version": loaded_version,
            "payload_sha256": loaded_payload_sha256,
            "entry_sha256": loaded_entry_sha256,
        }.items()
        if value is not None
    }
    loaded_identity: dict[str, Any] | None = loaded_items or None

    if embedded is not None and not _runtime_matches_embedded(runtime, embedded):
        return _report(
            STATUS_RUNTIME_TAMPERED,
            "The installed runtime no longer matches its embedded provenance.",
            runtime=runtime,
            source=None,
            embedded=embedded,
            loaded_identity=loaded_identity,
        )

    if source_root is None:
        return _report(
            STATUS_SOURCE_UNAVAILABLE,
            "No editable plugin source was supplied for comparison.",
            runtime=runtime,
            source=None,
            embedded=embedded,
            loaded_identity=loaded_identity,
        )
    source_path = Path(source_root).expanduser().resolve()
    if not source_path.is_dir() or not (source_path / MANIFEST_PATH).is_file():
        return _report(
            STATUS_SOURCE_UNAVAILABLE,
            f"The editable plugin source is unavailable: {source_path}",
            runtime=runtime,
            source=None,
            embedded=embedded,
            loaded_identity=loaded_identity,
        )
    source = inspect_runtime(source_path, entry_path=entry_path)

    if source["version"] == runtime["version"] and (
        source["payload_sha256"] != runtime["payload_sha256"]
    ):
        return _report(
            STATUS_VERSION_COLLISION,
            "Source and runtime declare the same version for different payloads.",
            runtime=runtime,
            source=source,
            embedded=embedded,
            loaded_identity=loaded_identity,
        )

    if (
        source["version"] != runtime["version"]
        or source["payload_sha256"] != runtime["payload_sha256"]
    ):
        return _report(
            STATUS_SOURCE_NEWER,
            "Editable source and installed runtime differ; reinstall the plugin.",
            runtime=runtime,
            source=source,
            embedded=embedded,
            loaded_identity=loaded_identity,
        )

    if loaded_identity is not None and any(
        runtime.get(field) != value for field, value in loaded_identity.items()
    ):
        return _report(
            STATUS_RESTART_REQUIRED,
            "The installed runtime is current, but the loaded identity is stale.",
            runtime=runtime,
            source=source,
            embedded=embedded,
            loaded_identity=loaded_identity,
        )

    return _report(
        STATUS_OK,
        "Source, installed runtime, and loaded identity are consistent.",
        runtime=runtime,
        source=source,
        embedded=embedded,
        loaded_identity=loaded_identity,
    )


def mutation_runtime_report(
    runtime_root: Path | str,
    *,
    recorded_identity: Mapping[str, Any] | None = None,
    loaded_identity: Mapping[str, Any] | None = None,
    entry_path: Path | str | None = None,
) -> dict[str, Any]:
    """Audit a runtime before it is allowed to persist workflow state.

    The runtime tree is compared with its embedded record and with the identity
    captured when the command module was loaded.  A previously recorded state
    mutator supplies the source/version comparison when no editable checkout is
    discoverable from an installed plugin.  Reusing a declared version for new
    payload bytes is therefore a collision even when the old runtime directory
    is no longer present.
    """
    root = _plugin_root(runtime_root)
    loaded = dict(loaded_identity or {})
    report = doctor_runtime(
        root,
        source_root=root,
        entry_path=entry_path,
        loaded_version=loaded.get("version"),
        loaded_payload_sha256=loaded.get("payload_sha256"),
        loaded_entry_sha256=loaded.get("entry_sha256"),
    )
    if report["status"] in HARD_FAILURE_STATUSES:
        return report

    runtime = report["runtime"]
    recorded = dict(recorded_identity or {})
    if not recorded:
        return report
    if recorded.get("plugin_name") not in {None, runtime.get("plugin_name")}:
        return _report(
            STATUS_VERSION_COLLISION,
            "The workflow was last mutated by a different plugin identity.",
            runtime=runtime,
            source=recorded,
            embedded=report.get("embedded"),
            loaded_identity=report.get("loaded_identity"),
        )

    recorded_version = recorded.get("version")
    recorded_payload = recorded.get("payload_sha256")
    runtime_version = runtime.get("version")
    runtime_payload = runtime.get("payload_sha256")
    if (
        isinstance(recorded_version, str)
        and isinstance(recorded_payload, str)
        and recorded_version == runtime_version
        and recorded_payload != runtime_payload
    ):
        return _report(
            STATUS_VERSION_COLLISION,
            "The loaded runtime reuses the recorded plugin version for different payload bytes.",
            runtime=runtime,
            source=recorded,
            embedded=report.get("embedded"),
            loaded_identity=report.get("loaded_identity"),
        )

    # A stale in-process module requires a restart even if the persisted state
    # was produced by an older, otherwise legitimate plugin release.
    if report["status"] == STATUS_RESTART_REQUIRED:
        return report
    if (
        isinstance(recorded_version, str)
        and isinstance(recorded_payload, str)
        and (
            recorded_version != runtime_version
            or recorded_payload != runtime_payload
        )
    ):
        return _report(
            STATUS_SOURCE_NEWER,
            "The current runtime is a different declared plugin release than the last state mutator.",
            runtime=runtime,
            source=recorded,
            embedded=report.get("embedded"),
            loaded_identity=report.get("loaded_identity"),
        )
    return report


def require_mutation_runtime(
    runtime_root: Path | str,
    *,
    recorded_identity: Mapping[str, Any] | None = None,
    loaded_identity: Mapping[str, Any] | None = None,
    entry_path: Path | str | None = None,
) -> dict[str, Any]:
    """Return an auditable runtime identity or reject an unsafe mutation."""
    report = mutation_runtime_report(
        runtime_root,
        recorded_identity=recorded_identity,
        loaded_identity=loaded_identity,
        entry_path=entry_path,
    )
    status = str(report.get("status", ""))
    if status in HARD_FAILURE_STATUSES:
        raise ProvenanceHardFailure(
            f"Runtime provenance {status}: {report.get('message')} Mutation refused."
        )
    if status == STATUS_RESTART_REQUIRED:
        raise ProvenanceHardFailure(
            "Runtime provenance RESTART_REQUIRED: restart Codex before mutating workflow state."
        )
    if status not in {STATUS_OK, STATUS_SOURCE_NEWER}:
        raise ProvenanceHardFailure(
            f"Runtime provenance {status or 'UNKNOWN'} is not safe for mutation: "
            f"{report.get('message')}"
        )
    return report


def require_healthy_runtime(report: Mapping[str, Any]) -> Mapping[str, Any]:
    """Raise when a doctor report represents an identity hard failure."""
    status = str(report.get("status", ""))
    if status in HARD_FAILURE_STATUSES:
        raise ProvenanceHardFailure(
            str(report.get("message") or f"Plugin provenance failure: {status}")
        )
    return report


def doctor_exit_code(report: Mapping[str, Any]) -> int:
    status = str(report.get("status", ""))
    if status in HARD_FAILURE_STATUSES:
        return 2
    return 0 if status == STATUS_OK else 1


def _print_json(value: Mapping[str, Any]) -> None:
    print(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    version = subparsers.add_parser("version", help="Print runtime provenance")
    version.add_argument("--runtime-root", default=str(default_plugin_root()))
    version.add_argument("--entry", default=DEFAULT_ENTRY_PATH.as_posix())

    doctor = subparsers.add_parser("doctor", help="Compare source and runtime provenance")
    doctor.add_argument("--runtime-root", default=str(default_plugin_root()))
    doctor.add_argument("--source-root")
    doctor.add_argument("--entry", default=DEFAULT_ENTRY_PATH.as_posix())
    doctor.add_argument("--loaded-version")
    doctor.add_argument("--loaded-payload-sha256")
    doctor.add_argument("--loaded-entry-sha256")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "version":
            _print_json(inspect_runtime(args.runtime_root, entry_path=args.entry))
            return 0
        report = doctor_runtime(
            args.runtime_root,
            source_root=args.source_root,
            entry_path=args.entry,
            loaded_version=args.loaded_version,
            loaded_payload_sha256=args.loaded_payload_sha256,
            loaded_entry_sha256=args.loaded_entry_sha256,
        )
        _print_json(report)
        return doctor_exit_code(report)
    except ProvenanceError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
