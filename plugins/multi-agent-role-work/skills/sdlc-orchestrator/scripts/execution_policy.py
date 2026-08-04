"""Cost-aware execution policy and deterministic verification runtime."""

from __future__ import annotations

import hashlib
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from state_store import WorkflowError, atomic_write_text


MAX_VERIFICATION_LOG_BYTES = 2_000_000
EXECUTION_POLICIES = {
    "auto": {
        "context": "scope-only",
        "testing": "Do not test before mode selection.",
        "roles": "Use no delivery role until scope and risk are understood.",
    },
    "micro": {
        "context": "changed files and acceptance only",
        "testing": "Run one focused deterministic test; stop on first failure.",
        "roles": "Use engineering once and one independent tester; no role meeting.",
    },
    "quick": {
        "context": "delta plus affected evidence paths",
        "testing": "Run smoke tests first, then only affected tests; stop on failure.",
        "roles": "Invoke only roles required by the enabled gate.",
    },
    "standard": {
        "context": "decision summary, delta, and affected criteria",
        "testing": "Run smoke, affected integration, then final journey in that order.",
        "roles": "Reuse concise artifacts; do not send transcripts or full passing logs.",
    },
    "strict": {
        "context": "current baselines, delta, and unresolved findings",
        "testing": "Fail fast through build, scoped tests, and semantic journey.",
        "roles": "Keep independent gates but share hashes and summaries, not raw logs.",
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


def execute_verification_commands(
    root: Path,
    state: dict[str, Any],
    commands: tuple[tuple[str, str], ...],
    timeout_seconds: int = 300,
) -> dict[str, Any]:
    """Execute verification and persist bounded logs outside model context."""
    normalized = tuple((label, command.strip()) for label, command in commands if command.strip())
    if not normalized:
        raise WorkflowError("At least one deterministic verification command is required.")
    if timeout_seconds < 1 or timeout_seconds > 3600:
        raise WorkflowError("Verification command timeout must be between 1 and 3600 seconds.")
    workflow_id = state["workflow"]["id"]
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    log_path = root / ".ai-workflow" / workflow_id / "test-runs" / f"{run_id}.log"
    sections: list[str] = []
    results: list[dict[str, Any]] = []
    failed_reason = ""
    for label, command in normalized:
        started = time.monotonic()
        timed_out = False
        try:
            completed = subprocess.run(
                command,
                cwd=root,
                shell=True,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                timeout=timeout_seconds,
                check=False,
            )
            output = completed.stdout or ""
            exit_code = int(completed.returncode)
        except subprocess.TimeoutExpired as exc:
            output = str(exc.stdout or "")
            exit_code = 124
            timed_out = True
        duration_ms = int((time.monotonic() - started) * 1000)
        encoded_output = output.encode("utf-8")
        results.append(
            {
                "label": label,
                "command": command,
                "exit_code": exit_code,
                "duration_ms": duration_ms,
                "timed_out": timed_out,
                "output_sha256": hashlib.sha256(encoded_output).hexdigest(),
                "output_bytes": len(encoded_output),
            }
        )
        sections.append(
            f"## {label}\ncommand: {command}\nexit_code: {exit_code}\n"
            f"duration_ms: {duration_ms}\ntimed_out: {str(timed_out).lower()}\n\n{output}\n"
        )
        if exit_code != 0:
            failed_reason = f"{label} exited with {exit_code}"
            break
    rendered = "# Deterministic verification run\n\n" + "\n".join(sections)
    encoded = rendered.encode("utf-8")
    if len(encoded) > MAX_VERIFICATION_LOG_BYTES:
        rendered = (encoded[:MAX_VERIFICATION_LOG_BYTES] + b"\n\n[log truncated]\n").decode(
            "utf-8", errors="replace"
        )
    atomic_write_text(log_path, rendered)
    relative_log = log_path.relative_to(root)
    execution = {
        "status": "pass" if not failed_reason else "fail",
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
