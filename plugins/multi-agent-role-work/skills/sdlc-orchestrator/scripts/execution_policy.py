"""Cost-aware execution policy and deterministic verification runtime."""

from __future__ import annotations

import hashlib
import os
import re
import shutil
import signal
import subprocess
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from state_store import WorkflowError, atomic_write_text


MAX_VERIFICATION_LOG_BYTES = 2_000_000
MAX_VERIFICATION_LOG_FILES = 20
READ_CHUNK_BYTES = 64 * 1024
SENSITIVE_PATTERNS = (
    re.compile(r"(?i)\b(authorization\s*:\s*bearer\s+)([^\s]+)"),
    re.compile(
        r"(?i)\b((?:api[_-]?key|access[_-]?token|auth[_-]?token|password|passwd|secret)"
        r"\s*[=:]\s*)([^\s;&]+)"
    ),
    re.compile(r"\b(gh[opusr]_[A-Za-z0-9_]{20,}|github_pat_[A-Za-z0-9_]{20,})\b"),
)
EXECUTION_POLICIES = {
    "auto": {
        "context": "scope-only",
        "testing": "Do not test before mode selection.",
        "roles": "Use no delivery role until scope and risk are understood.",
        "recommended_max_role_handoffs_per_stage": 0,
        "max_verification_commands_per_run": 0,
    },
    "micro": {
        "context": "changed files and acceptance only",
        "testing": "Run one focused deterministic test; stop on first failure.",
        "roles": "Use engineering once and one independent tester; no role meeting.",
        "recommended_max_role_handoffs_per_stage": 2,
        "max_verification_commands_per_run": 2,
    },
    "quick": {
        "context": "delta plus affected evidence paths",
        "testing": "Run smoke tests first, then only affected tests; stop on failure.",
        "roles": "Invoke only roles required by the enabled gate.",
        "recommended_max_role_handoffs_per_stage": 3,
        "max_verification_commands_per_run": 2,
    },
    "standard": {
        "context": "decision summary, delta, and affected criteria",
        "testing": "Run smoke, affected integration, then final journey in that order.",
        "roles": "Reuse concise artifacts; do not send transcripts or full passing logs.",
        "recommended_max_role_handoffs_per_stage": 3,
        "max_verification_commands_per_run": 2,
    },
    "strict": {
        "context": "current baselines, delta, and unresolved findings",
        "testing": "Fail fast through build, scoped tests, and semantic journey.",
        "roles": "Keep independent gates but share hashes and summaries, not raw logs.",
        "recommended_max_role_handoffs_per_stage": 3,
        "max_verification_commands_per_run": 2,
    },
}


def repository_context(root: Path) -> dict[str, str]:
    try:
        branch = subprocess.check_output(
            ["git", "-C", str(root), "symbolic-ref", "--quiet", "--short", "HEAD"],
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        branch = ""
    return {"git_branch": branch} if branch else {}


def _timestamp() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _redact(text: str) -> str:
    rendered = text
    for index, pattern in enumerate(SENSITIVE_PATTERNS):
        if index < 2:
            rendered = pattern.sub(r"\1[REDACTED]", rendered)
        else:
            rendered = pattern.sub("[REDACTED]", rendered)
    return rendered


def _snapshot_ignore(source_root: Path):
    def ignore(directory: str, names: list[str]) -> set[str]:
        relative = Path(directory).resolve().relative_to(source_root.resolve())
        excluded = {name for name in names if name in {".git", ".ai-workflow", ".idea"}}
        for name in names:
            candidate = Path(directory) / name
            if not (candidate.is_file() or candidate.is_dir() or candidate.is_symlink()):
                excluded.add(name)
        if relative == Path("docs") and "requirements" in names:
            excluded.add("requirements")
        return excluded

    return ignore


def _reject_external_symlinks(root: Path) -> None:
    resolved_root = root.resolve()
    for candidate in root.rglob("*"):
        if not candidate.is_symlink():
            continue
        target = candidate.readlink()
        try:
            if target.is_absolute():
                raise ValueError("absolute symbolic link")
            resolved_target = candidate.resolve(strict=False)
            resolved_target.relative_to(resolved_root)
        except (OSError, RuntimeError, ValueError) as exc:
            relative = candidate.relative_to(root)
            raise WorkflowError(
                "Isolated verification cannot safely copy a symbolic link outside the "
                f"repository: {relative} -> {target}"
            ) from exc


def _create_snapshot(root: Path, destination: Path, ignored_paths: tuple[str, ...]) -> None:
    _reject_external_symlinks(root)
    shutil.copytree(
        root,
        destination,
        symlinks=True,
        ignore=_snapshot_ignore(root),
        dirs_exist_ok=True,
    )
    try:
        subprocess.run(
            ["git", "init", "--quiet"],
            cwd=destination,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=True,
        )
        info_exclude = destination / ".git" / "info" / "exclude"
        if ignored_paths:
            with info_exclude.open("a", encoding="utf-8") as handle:
                for item in ignored_paths:
                    handle.write(f"/{item.rstrip('/')}\n")
        subprocess.run(
            ["git", "add", "-A"],
            cwd=destination,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            check=True,
        )
        subprocess.run(
            [
                "git",
                "-c",
                "user.name=SDLC Verification",
                "-c",
                "user.email=verification@localhost",
                "commit",
                "--quiet",
                "--no-gpg-sign",
                "--allow-empty",
                "-m",
                "isolated verification baseline",
            ],
            cwd=destination,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            check=True,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise WorkflowError("Unable to create an isolated verification workspace.") from exc


def _snapshot_changes(snapshot: Path, scope_paths: tuple[str, ...]) -> list[str]:
    command = ["git", "status", "--porcelain=v1", "-z", "--untracked-files=all"]
    if scope_paths:
        command.extend(("--", *scope_paths))
    try:
        raw = subprocess.check_output(command, cwd=snapshot, stderr=subprocess.DEVNULL)
    except (OSError, subprocess.CalledProcessError) as exc:
        raise WorkflowError("Unable to verify the isolated workspace after testing.") from exc
    entries = raw.split(b"\0")
    changed: list[str] = []
    index = 0
    while index < len(entries):
        entry = entries[index]
        index += 1
        if not entry:
            continue
        path = entry[3:].decode("utf-8", errors="replace") if len(entry) > 3 else ""
        if entry[:2] in {b"R ", b"C "} and index < len(entries):
            path = entries[index].decode("utf-8", errors="replace")
            index += 1
        if path:
            changed.append(path)
    return sorted(set(changed))


def _terminate_process_group(process: subprocess.Popen[Any]) -> None:
    try:
        if os.name == "posix":
            os.killpg(process.pid, signal.SIGTERM)
        elif process.poll() is None:  # pragma: no cover - exercised on Windows.
            subprocess.run(
                ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            )
        if process.poll() is None:
            process.wait(timeout=2)
    except (OSError, subprocess.TimeoutExpired):
        try:
            if os.name == "posix":
                os.killpg(process.pid, signal.SIGKILL)
            else:  # pragma: no cover - exercised on Windows.
                process.kill()
        except OSError:
            pass
        try:
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:  # pragma: no cover - defensive host failure.
            pass


def _run_command(
    snapshot: Path,
    command: str,
    timeout_seconds: int,
) -> tuple[int, bool, int, str, int, str]:
    started = time.monotonic()
    timed_out = False
    with tempfile.TemporaryFile(mode="w+b") as output_file:
        process = subprocess.Popen(
            command,
            cwd=snapshot,
            shell=True,
            stdout=output_file,
            stderr=subprocess.STDOUT,
            start_new_session=os.name == "posix",
            creationflags=(
                subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
            ),
        )
        try:
            exit_code = int(process.wait(timeout=timeout_seconds))
        except subprocess.TimeoutExpired:
            timed_out = True
            exit_code = 124
            _terminate_process_group(process)
        else:
            # A shell can exit successfully after starting background children.
            # End the dedicated process group so verification cannot leak them.
            _terminate_process_group(process)
        duration_ms = int((time.monotonic() - started) * 1000)
        output_file.seek(0)
        digest = hashlib.sha256()
        captured = bytearray()
        output_bytes = 0
        while True:
            chunk = output_file.read(READ_CHUNK_BYTES)
            if not chunk:
                break
            digest.update(chunk)
            output_bytes += len(chunk)
            if len(captured) < MAX_VERIFICATION_LOG_BYTES:
                remaining = MAX_VERIFICATION_LOG_BYTES - len(captured)
                captured.extend(chunk[:remaining])
    output = _redact(captured.decode("utf-8", errors="replace"))
    if output_bytes > len(captured):
        output += "\n\n[output truncated]\n"
    return exit_code, timed_out, duration_ms, output, output_bytes, digest.hexdigest()


def parse_verification_timeout(value: Any) -> int:
    if isinstance(value, bool):
        raise WorkflowError("Verification command timeout must be a whole number of seconds.")
    try:
        timeout = int(value)
    except (TypeError, ValueError) as exc:
        raise WorkflowError(
            "Verification command timeout must be a whole number of seconds."
        ) from exc
    if str(value).strip() != str(timeout):
        raise WorkflowError("Verification command timeout must be a whole number of seconds.")
    if timeout < 1 or timeout > 3600:
        raise WorkflowError("Verification command timeout must be between 1 and 3600 seconds.")
    return timeout


def _retained_log_paths(root: Path, state: dict[str, Any]) -> set[Path]:
    retained: set[Path] = set()
    for container in (
        state.get("verification_snapshot", {}),
        state.get("source_revision", {}),
    ):
        execution = container.get("test_execution", {}) if isinstance(container, dict) else {}
        relative = execution.get("log_path") if isinstance(execution, dict) else None
        if isinstance(relative, str) and relative:
            retained.add((root / relative).resolve())
    return retained


def _cleanup_logs(root: Path, state: dict[str, Any], log_directory: Path) -> None:
    retained = _retained_log_paths(root, state)
    logs = sorted(
        log_directory.glob("*.log"),
        key=lambda item: item.stat().st_mtime,
        reverse=True,
    )
    for stale in logs[MAX_VERIFICATION_LOG_FILES:]:
        if stale.resolve() not in retained:
            stale.unlink(missing_ok=True)


def execute_verification_commands(
    root: Path,
    state: dict[str, Any],
    commands: tuple[tuple[str, str], ...],
    timeout_seconds: int = 300,
    *,
    scope_paths: tuple[str, ...] = (),
    ignored_paths: tuple[str, ...] = (),
) -> dict[str, Any]:
    """Execute verification in a disposable snapshot and persist bounded local logs."""
    normalized = tuple((label, command.strip()) for label, command in commands if command.strip())
    if not normalized:
        raise WorkflowError("At least one deterministic verification command is required.")
    timeout_seconds = parse_verification_timeout(timeout_seconds)
    mode = str(state.get("workflow", {}).get("mode", "auto"))
    maximum_commands = int(
        EXECUTION_POLICIES.get(mode, EXECUTION_POLICIES["auto"])[
            "max_verification_commands_per_run"
        ]
    )
    if maximum_commands and len(normalized) > maximum_commands:
        raise WorkflowError(
            f"Mode {mode} permits at most {maximum_commands} verification commands per run."
        )
    workflow_id = state["workflow"]["id"]
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    log_path = root / ".ai-workflow" / workflow_id / "test-runs" / f"{run_id}.log"
    sections: list[str] = []
    results: list[dict[str, Any]] = []
    failed_reason = ""
    with tempfile.TemporaryDirectory(prefix="sdlc-verification-") as temporary:
        snapshot = Path(temporary) / "workspace"
        _create_snapshot(root, snapshot, ignored_paths)
        for label, command in normalized:
            exit_code, timed_out, duration_ms, output, output_bytes, output_hash = _run_command(
                snapshot, command, timeout_seconds
            )
            sanitized_command = _redact(command)
            results.append(
                {
                    "label": label,
                    "command": sanitized_command,
                    "exit_code": exit_code,
                    "duration_ms": duration_ms,
                    "timed_out": timed_out,
                    "output_sha256": output_hash,
                    "output_bytes": output_bytes,
                }
            )
            sections.append(
                f"## {label}\ncommand: {sanitized_command}\nexit_code: {exit_code}\n"
                f"duration_ms: {duration_ms}\ntimed_out: {str(timed_out).lower()}\n\n{output}\n"
            )
            changed_paths = _snapshot_changes(snapshot, scope_paths)
            if changed_paths:
                failed_reason = (
                    "verification command changed product files in the isolated workspace; "
                    "original workspace was not modified: " + ",".join(changed_paths[:20])
                )
                break
            if exit_code != 0:
                failed_reason = f"{label} exited with {exit_code}"
                break
    rendered = (
        "# Deterministic verification run\n\nisolation: temporary_snapshot\n\n"
        + "\n".join(sections)
    )
    encoded = rendered.encode("utf-8")
    if len(encoded) > MAX_VERIFICATION_LOG_BYTES:
        marker = b"\n\n[log truncated]\n"
        rendered = (encoded[: MAX_VERIFICATION_LOG_BYTES - len(marker)] + marker).decode(
            "utf-8", errors="replace"
        )
    atomic_write_text(log_path, rendered)
    _cleanup_logs(root, state, log_path.parent)
    relative_log = log_path.relative_to(root)
    execution = {
        "status": "pass" if not failed_reason else "fail",
        "isolation": "temporary_snapshot",
        "commands": results,
        "log_path": str(relative_log),
        "log_sha256": hashlib.sha256(log_path.read_bytes()).hexdigest(),
        "completed_at": _timestamp(),
    }
    if failed_reason:
        raise WorkflowError(
            f"Verification command failed ({failed_reason}); inspect local log={relative_log}"
        )
    return execution
