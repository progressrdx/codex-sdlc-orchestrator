"""Atomic, checksummed workflow state persistence."""

from __future__ import annotations

import hashlib
import json
import math
import os
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

try:
    import fcntl  # type: ignore
except ImportError:  # pragma: no cover - Windows fallback is exercised on Windows.
    fcntl = None

try:
    import msvcrt  # type: ignore
except ImportError:  # pragma: no cover - POSIX uses fcntl.
    msvcrt = None

try:
    import yaml  # type: ignore
except ImportError:  # JSON is valid YAML 1.2 and is the dependency-free fallback.
    yaml = None


class WorkflowError(RuntimeError):
    pass


def load_data(path: Path) -> dict[str, Any]:
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise WorkflowError(f"Data file not found: {path}") from exc
    try:
        data = yaml.safe_load(text) if yaml else json.loads(text)
    except (ValueError, yaml.YAMLError if yaml else ValueError) as exc:
        raise WorkflowError(f"Cannot parse data file {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise WorkflowError(f"Invalid mapping in {path}")
    return data


def state_checksum(state: dict[str, Any]) -> str:
    payload = {key: value for key, value in state.items() if key != "state_checksum"}
    rendered = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(rendered.encode("utf-8")).hexdigest()


def verify_state_checksum(
    state: dict[str, Any],
    path: Path,
    current_schema_version: int,
) -> None:
    if state.get("schema_version") != current_schema_version:
        return
    expected = state.get("state_checksum")
    if not isinstance(expected, str) or expected != state_checksum(state):
        raise WorkflowError(
            f"Workflow state integrity check failed for {path}. "
            "Do not edit state.yaml directly; use workflow commands."
        )


def atomic_write_text(path: Path, rendered: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=path.parent,
        text=True,
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(rendered)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        try:
            directory = os.open(path.parent, os.O_RDONLY)
        except OSError:
            return
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        temporary.unlink(missing_ok=True)


def save_data(path: Path, data: dict[str, Any]) -> None:
    if yaml:
        rendered = yaml.safe_dump(data, sort_keys=False, allow_unicode=True)
    else:
        rendered = json.dumps(data, indent=2, ensure_ascii=False) + "\n"
    atomic_write_text(path, rendered)


def claim_owned_data(
    path: Path,
    data: dict[str, Any],
    *,
    owner_key: str,
    owner: str,
) -> None:
    """Create or refresh a small owner record without replacing another owner."""
    if path.exists():
        current = load_data(path)
        current_owner = current.get(owner_key)
        if current_owner != owner:
            raise WorkflowError(
                f"Cannot replace {path.name} owned by {current_owner!r} with owner {owner!r}."
            )
    save_data(path, data)


def remove_owned_data(path: Path, *, owner_key: str, owner: str) -> bool:
    """Remove an owner record only when it still names the expected owner."""
    if not path.exists():
        return False
    current = load_data(path)
    if current.get(owner_key) != owner:
        return False
    path.unlink()
    try:
        directory = os.open(path.parent, os.O_RDONLY)
    except OSError:
        return True
    try:
        os.fsync(directory)
    finally:
        os.close(directory)
    return True


@contextmanager
def workflow_lock(root: Path) -> Iterator[None]:
    lock_key = hashlib.sha256(str(root).encode("utf-8")).hexdigest()
    lock_path = Path(tempfile.gettempdir()) / "multi-agent-role-work-locks" / f"{lock_key}.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    raw_timeout = os.environ.get("SDLC_LOCK_TIMEOUT", "5")
    try:
        timeout = float(raw_timeout)
    except ValueError as exc:
        raise WorkflowError(
            "SDLC_LOCK_TIMEOUT must be a non-negative finite number of seconds."
        ) from exc
    if not math.isfinite(timeout) or timeout < 0:
        raise WorkflowError(
            "SDLC_LOCK_TIMEOUT must be a non-negative finite number of seconds."
        )
    descriptor = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
    deadline = time.monotonic() + timeout
    acquired = False
    try:
        while not acquired:
            try:
                if fcntl is not None:
                    fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
                elif msvcrt is not None:  # pragma: no cover - Windows only.
                    if os.fstat(descriptor).st_size == 0:
                        os.write(descriptor, b"\0")
                    os.lseek(descriptor, 0, os.SEEK_SET)
                    msvcrt.locking(descriptor, msvcrt.LK_NBLCK, 1)
                else:  # pragma: no cover - supported Python platforms provide one.
                    raise WorkflowError("No supported file-lock implementation is available.")
                acquired = True
            except (BlockingIOError, OSError):
                if time.monotonic() >= deadline:
                    raise WorkflowError(
                        "Another workflow update is in progress. Retry after it completes."
                    )
                time.sleep(0.05)
        yield
    finally:
        if acquired:
            if fcntl is not None:
                fcntl.flock(descriptor, fcntl.LOCK_UN)
            elif msvcrt is not None:  # pragma: no cover - Windows only.
                os.lseek(descriptor, 0, os.SEEK_SET)
                msvcrt.locking(descriptor, msvcrt.LK_UNLCK, 1)
        os.close(descriptor)
