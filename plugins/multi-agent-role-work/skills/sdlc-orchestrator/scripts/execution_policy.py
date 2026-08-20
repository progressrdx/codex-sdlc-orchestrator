"""Cost-aware execution policy and deterministic verification runtime."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from delivery_candidate import (
    CandidateError,
    DeliveryCandidate,
    changed_manifest_paths,
    filesystem_manifest,
    normalize_relative_paths,
    prepare_output_subtrees,
    validate_output_subtrees,
)
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


def _create_snapshot(candidate: DeliveryCandidate, destination: Path) -> None:
    """Materialize only the frozen candidate manifest."""
    try:
        candidate.materialize(destination)
    except CandidateError as exc:
        raise WorkflowError("Unable to create an isolated verification workspace.") from exc


def _snapshot_manifest(
    snapshot: Path,
    output_paths: tuple[str, ...],
) -> dict[str, tuple[str, int, str]]:
    try:
        return filesystem_manifest(snapshot, output_paths)
    except CandidateError as exc:
        raise WorkflowError("Unable to verify the isolated workspace after testing.") from exc


def _snapshot_changes(
    baseline: dict[str, tuple[str, int, str]],
    snapshot: Path,
    output_paths: tuple[str, ...],
) -> list[str]:
    return changed_manifest_paths(
        baseline,
        _snapshot_manifest(snapshot, output_paths),
    )


def _output_roots(snapshot: Path, output_paths: tuple[str, ...]) -> tuple[Path, ...]:
    try:
        roots = prepare_output_subtrees(snapshot, output_paths)
        validate_output_subtrees(snapshot, output_paths)
        return roots
    except CandidateError as exc:
        raise WorkflowError(str(exc)) from exc


def _audit_outputs(snapshot: Path, output_paths: tuple[str, ...]) -> None:
    try:
        validate_output_subtrees(snapshot, output_paths)
    except CandidateError as exc:
        raise WorkflowError(str(exc)) from exc


def _portable_components(path: str) -> tuple[str, ...]:
    return tuple(
        unicodedata.normalize("NFC", part).casefold() for part in path.split("/")
    )


def _portable_paths_overlap(left: str, right: str) -> bool:
    left_parts = _portable_components(left)
    right_parts = _portable_components(right)
    shorter = min(len(left_parts), len(right_parts))
    return left_parts[:shorter] == right_parts[:shorter]


def _sandbox_profile_path(path: Path) -> str:
    return json.dumps(os.path.realpath(path))


def _isolation_launcher(
    snapshot: Path,
    output_roots: tuple[Path, ...],
    scratch: Path,
    profile_path: Path,
) -> tuple[list[str], dict[str, str], str]:
    """Return an OS-enforced launcher or fail closed.

    File modes alone are not a boundary because a process running under the
    owning UID can chmod them back.  Seatbelt (macOS) and mount namespaces
    (bubblewrap/Linux) enforce the denial in the kernel for the whole process
    tree, including commands running as the same UID.
    """
    environment = dict(os.environ)
    environment.update(
        {
            "HOME": str(scratch / "home"),
            "TMPDIR": str(scratch),
            "TMP": str(scratch),
            "TEMP": str(scratch),
            "PYTHONDONTWRITEBYTECODE": "1",
        }
    )
    (scratch / "home").mkdir()
    if sys.platform == "darwin":
        executable = shutil.which("sandbox-exec")
        if not executable:
            raise WorkflowError(
                "Immutable verification requires macOS sandbox-exec; refusing an unisolated run."
            )
        rules = [
            "(version 1)",
            "(allow default)",
            '(deny file-write* (subpath "/"))',
            '(allow file-write* (literal "/dev/null"))',
            f"(allow file-write* (subpath {_sandbox_profile_path(scratch)}))",
        ]
        rules.extend(
            f"(allow file-write* (subpath {_sandbox_profile_path(path)}))"
            for path in output_roots
        )
        profile_path.write_text("\n".join(rules) + "\n", encoding="utf-8")
        return (
            [executable, "-f", str(profile_path), "/bin/sh", "-c"],
            environment,
            "macos_seatbelt",
        )
    if sys.platform.startswith("linux"):
        executable = shutil.which("bwrap")
        if not executable:
            raise WorkflowError(
                "Immutable verification requires bubblewrap on Linux; refusing an unisolated run."
            )
        launcher = [
            executable,
            "--die-with-parent",
            "--ro-bind", "/", "/",
            "--proc", "/proc",
            "--dev", "/dev",
            "--bind", str(scratch), str(scratch),
        ]
        for path in output_roots:
            launcher.extend(("--bind", str(path), str(path)))
        launcher.extend(("--chdir", str(snapshot), "/bin/sh", "-c"))
        return launcher, environment, "linux_mount_namespace"
    raise WorkflowError(
        "This platform has no supported immutable verification sandbox; refusing an unisolated run."
    )


def _verify_isolation_boundary(
    launcher: list[str],
    environment: dict[str, str],
    snapshot: Path,
    protected_probe: Path,
    scratch: Path,
) -> None:
    protected_probe.write_text("unchanged\n", encoding="utf-8")
    protected_probe.chmod(0o444)
    writable_probe = scratch / "isolation-write-probe"
    probe_environment = dict(environment)
    probe_environment.update(
        {
            "SDLC_PROTECTED_PROBE": str(protected_probe),
            "SDLC_WRITABLE_PROBE": str(writable_probe),
        }
    )
    probe = subprocess.run(
        [
            *launcher,
            'if chmod u+w "$SDLC_PROTECTED_PROBE" 2>/dev/null; then exit 90; fi; '
            'if printf compromised >> "$SDLC_PROTECTED_PROBE" 2>/dev/null; then exit 91; fi; '
            'printf writable > "$SDLC_WRITABLE_PROBE" || exit 92',
        ],
        cwd=snapshot,
        env=probe_environment,
        capture_output=True,
        text=True,
        timeout=10,
    )
    unchanged = protected_probe.read_text(encoding="utf-8") == "unchanged\n"
    protected_mode = protected_probe.stat().st_mode & 0o777
    writable = (
        writable_probe.read_text(encoding="utf-8") == "writable"
        if writable_probe.exists()
        else False
    )
    if probe.returncode != 0 or not unchanged or protected_mode != 0o444 or not writable:
        raise WorkflowError(
            "The verification OS sandbox failed its same-UID write-denial probe; refusing to run."
        )


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
    launcher: list[str],
    environment: dict[str, str],
) -> tuple[int, bool, int, str, int, str]:
    started = time.monotonic()
    timed_out = False
    with tempfile.TemporaryFile(mode="w+b") as output_file:
        process = subprocess.Popen(
            [*launcher, command],
            cwd=snapshot,
            shell=False,
            env=environment,
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
    output_paths: tuple[str, ...] = (),
) -> dict[str, Any]:
    """Execute verification against one immutable delivery candidate."""
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
    try:
        normalized_scope = normalize_relative_paths(scope_paths)
        normalized_ignored = normalize_relative_paths(ignored_paths)
        # Source exclusions and mutable command outputs are different trust
        # boundaries.  An ignored source path must never become writable merely
        # because it was excluded from a selected binding.
        normalized_outputs = normalize_relative_paths(output_paths)
    except CandidateError as exc:
        raise WorkflowError(str(exc)) from exc
    if any(
        path == ".git" or path.startswith(".git/")
        for path in normalized_outputs
    ):
        raise WorkflowError("The snapshot Git metadata path cannot be an allowed output.")
    try:
        if mode == "strict":
            candidate = DeliveryCandidate.from_repository(root)
            hidden_paths = candidate.hidden_index_paths(
                normalized_scope,
                normalized_ignored,
            )
            if hidden_paths:
                raise WorkflowError(
                    "Delivery candidate rejects assume-unchanged or skip-worktree index flags: "
                    + ",".join(hidden_paths)
                )
            changed_source = candidate.worktree_changes(
                normalized_scope,
                normalized_ignored,
            )
            if changed_source:
                raise WorkflowError(
                    "Delivery candidate differs from the scoped worktree; commit or remove "
                    "untracked/ignored inputs first: " + ",".join(changed_source)
                )
        else:
            candidate = DeliveryCandidate.from_workspace(root, normalized_ignored)
    except CandidateError as exc:
        raise WorkflowError(str(exc)) from exc
    overlapping_outputs = sorted(
        {
            output
            for output in normalized_outputs
            if any(
                _portable_paths_overlap(entry.path, output)
                for entry in candidate.entries
            )
        }
    )
    if overlapping_outputs:
        raise WorkflowError(
            "Generated output paths must not overlap frozen candidate inputs: "
            + ",".join(overlapping_outputs)
        )
    workflow_id = state["workflow"]["id"]
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    log_path = root / ".ai-workflow" / workflow_id / "test-runs" / f"{run_id}.log"
    sections: list[str] = []
    results: list[dict[str, Any]] = []
    failed_reason = ""
    with tempfile.TemporaryDirectory(prefix="sdlc-verification-") as temporary:
        temporary_root = Path(temporary)
        snapshot = temporary_root / "workspace"
        _create_snapshot(candidate, snapshot)
        output_roots = _output_roots(snapshot, normalized_outputs)
        scratch = temporary_root / "scratch"
        scratch.mkdir()
        profile_path = temporary_root / "verification.sb"
        launcher, command_environment, isolation_backend = _isolation_launcher(
            snapshot,
            output_roots,
            scratch,
            profile_path,
        )
        _verify_isolation_boundary(
            launcher,
            command_environment,
            snapshot,
            temporary_root / "protected-probe",
            scratch,
        )
        baseline_manifest = _snapshot_manifest(snapshot, normalized_outputs)
        for label, command in normalized:
            _audit_outputs(snapshot, normalized_outputs)
            exit_code, timed_out, duration_ms, output, output_bytes, output_hash = _run_command(
                snapshot,
                command,
                timeout_seconds,
                launcher,
                command_environment,
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
            _audit_outputs(snapshot, normalized_outputs)
            # The oracle is an external content manifest, not the mutable Git index
            # or refs inside the command's workspace.  A command cannot hide source
            # mutation with git add/commit/reset or ignore rules.
            changed_paths = _snapshot_changes(
                baseline_manifest,
                snapshot,
                normalized_outputs,
            )
            if changed_paths:
                failed_reason = (
                    "verification command changed product files; changed candidate inputs "
                    "in the isolated workspace; "
                    "original workspace was not modified: " + ",".join(changed_paths[:20])
                )
                break
            if exit_code != 0:
                failed_reason = f"{label} exited with {exit_code}"
                break
    rendered = (
        f"# Deterministic verification run\n\nisolation: {isolation_backend}\n\n"
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
        "isolation_backend": isolation_backend,
        "candidate": candidate.metadata(),
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
