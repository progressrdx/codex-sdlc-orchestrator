"""Pure work-item lifecycle and baseline validation for role assignments.

The workflow CLI deliberately owns persistence and runtime orchestration.  This
module only validates serialized records and returns updated copies, making it
safe to use before a state write or from tests without touching the filesystem.
"""

from __future__ import annotations

import copy
import re
from datetime import datetime, timedelta, timezone
from pathlib import PurePosixPath
from typing import Any, Mapping


WORK_ITEM_SCHEMA_VERSION = 1
ACTIVE_WORK_ITEM_STATUSES = frozenset({"dispatched", "running"})
TERMINAL_WORK_ITEM_STATUSES = frozenset(
    {"completed", "failed", "cancelled", "timed_out", "superseded"}
)
WORK_ITEM_STATUSES = ACTIVE_WORK_ITEM_STATUSES | TERMINAL_WORK_ITEM_STATUSES

_STABLE_REF = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/-]{2,127}")
_TOKEN = re.compile(r"[a-z][a-z0-9_-]{0,63}")
_HASH_KEY = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,255}")
_SHA256 = re.compile(r"[0-9a-fA-F]{64}")


class WorkItemError(ValueError):
    """Base class for invalid work-item data."""


class WorkItemStateError(WorkItemError):
    """Raised when a lifecycle transition is not valid for the current state."""


class WorkItemExpiredError(WorkItemStateError):
    """Raised when a lease or hard deadline has expired."""


class StaleBaselineError(WorkItemError):
    """Raised when role output no longer matches its dispatched input baseline."""


def _integer(value: Any, label: str, *, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise WorkItemError(f"{label} must be an integer >= {minimum}.")
    return value


def _text(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise WorkItemError(f"{label} must be non-empty text.")
    return value.strip()


def _stable_ref(value: Any, label: str) -> str:
    rendered = _text(value, label)
    if not _STABLE_REF.fullmatch(rendered):
        raise WorkItemError(
            f"{label} must be 3-128 stable-reference characters."
        )
    return rendered


def _token(value: Any, label: str) -> str:
    rendered = _text(value, label)
    if not _TOKEN.fullmatch(rendered):
        raise WorkItemError(
            f"{label} must start with a lowercase letter and contain only "
            "lowercase letters, digits, underscores, or hyphens."
        )
    return rendered


def _parse_timestamp(value: Any, label: str) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str) and value.strip():
        rendered = value.strip()
        if rendered.endswith("Z"):
            rendered = rendered[:-1] + "+00:00"
        try:
            parsed = datetime.fromisoformat(rendered)
        except ValueError as exc:
            raise WorkItemError(f"{label} must be an ISO-8601 timestamp.") from exc
    else:
        raise WorkItemError(f"{label} must be an ISO-8601 timestamp.")
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise WorkItemError(f"{label} must include a timezone.")
    return parsed.astimezone(timezone.utc)


def _timestamp(value: Any, label: str) -> str:
    return _parse_timestamp(value, label).isoformat().replace("+00:00", "Z")


def normalize_hashes(
    values: Any,
    label: str,
    *,
    require_nonempty: bool = False,
) -> dict[str, str]:
    """Validate and deterministically order a name-to-SHA256 mapping."""

    if not isinstance(values, Mapping):
        raise WorkItemError(f"{label} must be a mapping of names to SHA-256 hashes.")
    normalized: dict[str, str] = {}
    for raw_key, raw_hash in values.items():
        if not isinstance(raw_key, str) or not _HASH_KEY.fullmatch(raw_key.strip()):
            raise WorkItemError(f"{label} contains an invalid name: {raw_key!r}.")
        if not isinstance(raw_hash, str) or not _SHA256.fullmatch(raw_hash.strip()):
            raise WorkItemError(f"{label}[{raw_key!r}] must be a SHA-256 hex digest.")
        normalized[raw_key.strip()] = raw_hash.strip().lower()
    if require_nonempty and not normalized:
        raise WorkItemError(f"{label} must contain at least one SHA-256 hash.")
    return {key: normalized[key] for key in sorted(normalized)}


def _repository_path(value: Any, label: str) -> str:
    rendered = _text(value, label)
    if "\\" in rendered:
        raise WorkItemError(f"{label} must use canonical repository POSIX syntax.")
    candidate = PurePosixPath(rendered)
    normalized = candidate.as_posix()
    if (
        candidate.is_absolute()
        or ".." in candidate.parts
        or normalized in {"", "."}
        or normalized != rendered
    ):
        raise WorkItemError(f"{label} must be a canonical relative repository path.")
    return normalized


def normalize_output_paths(
    values: Any,
    label: str = "output_paths",
    *,
    require_nonempty: bool = False,
) -> dict[str, str]:
    """Validate and deterministically order output-name to repository-path bindings."""

    if not isinstance(values, Mapping):
        raise WorkItemError(f"{label} must be a mapping of output names to repository paths.")
    normalized: dict[str, str] = {}
    for raw_key, raw_path in values.items():
        if not isinstance(raw_key, str) or not _HASH_KEY.fullmatch(raw_key.strip()):
            raise WorkItemError(f"{label} contains an invalid name: {raw_key!r}.")
        key = raw_key.strip()
        normalized[key] = _repository_path(raw_path, f"{label}[{key!r}]")
    if require_nonempty and not normalized:
        raise WorkItemError(f"{label} must contain at least one repository path.")
    return {key: normalized[key] for key in sorted(normalized)}


def _validate_handoff_override(value: Any) -> dict[str, str]:
    if not isinstance(value, Mapping) or set(value) != {"path", "evidence_sha256"}:
        raise WorkItemError(
            "handoff_budget_override must contain only path and evidence_sha256."
        )
    digest = value.get("evidence_sha256")
    if not isinstance(digest, str) or not _SHA256.fullmatch(digest.strip()):
        raise WorkItemError("handoff_budget_override.evidence_sha256 must be SHA-256.")
    return {
        "path": _repository_path(value.get("path"), "handoff_budget_override.path"),
        "evidence_sha256": digest.strip().lower(),
    }


def create_work_item(
    *,
    work_item_id: str,
    stage: str,
    role: str,
    attempt: int,
    actor_ref: str,
    input_revision: int,
    input_hashes: Mapping[str, str],
    dispatched_at: str,
    deadline_at: str,
    lease_seconds: int,
) -> dict[str, Any]:
    """Create a dispatched work item with a renewable lease and hard deadline."""

    dispatched = _parse_timestamp(dispatched_at, "dispatched_at")
    deadline = _parse_timestamp(deadline_at, "deadline_at")
    if deadline <= dispatched:
        raise WorkItemError("deadline_at must be later than dispatched_at.")
    lease = _integer(lease_seconds, "lease_seconds", minimum=1)
    lease_expires = min(dispatched + timedelta(seconds=lease), deadline)
    item = {
        "schema_version": WORK_ITEM_SCHEMA_VERSION,
        "work_item_id": _stable_ref(work_item_id, "work_item_id"),
        "stage": _token(stage, "stage"),
        "role": _token(role, "role"),
        "attempt": _integer(attempt, "attempt", minimum=1),
        "actor_ref": _stable_ref(actor_ref, "actor_ref"),
        "input_revision": _integer(input_revision, "input_revision"),
        "input_hashes": normalize_hashes(input_hashes, "input_hashes"),
        "status": "dispatched",
        "dispatched_at": _timestamp(dispatched, "dispatched_at"),
        "heartbeat_at": _timestamp(dispatched, "heartbeat_at"),
        "heartbeat_count": 0,
        "lease_seconds": lease,
        "lease_expires_at": _timestamp(lease_expires, "lease_expires_at"),
        "deadline_at": _timestamp(deadline, "deadline_at"),
    }
    return validate_work_item(item)


def validate_work_item(raw_item: Mapping[str, Any]) -> dict[str, Any]:
    """Validate a serialized work item and return a normalized detached copy."""

    if not isinstance(raw_item, Mapping):
        raise WorkItemError("work item must be a mapping.")
    item = copy.deepcopy(dict(raw_item))
    if item.get("schema_version") != WORK_ITEM_SCHEMA_VERSION:
        raise WorkItemError(
            f"Unsupported work-item schema_version: {item.get('schema_version')!r}."
        )
    item["work_item_id"] = _stable_ref(item.get("work_item_id"), "work_item_id")
    item["stage"] = _token(item.get("stage"), "stage")
    item["role"] = _token(item.get("role"), "role")
    item["attempt"] = _integer(item.get("attempt"), "attempt", minimum=1)
    item["actor_ref"] = _stable_ref(item.get("actor_ref"), "actor_ref")
    item["input_revision"] = _integer(item.get("input_revision"), "input_revision")
    item["input_hashes"] = normalize_hashes(item.get("input_hashes"), "input_hashes")
    status = item.get("status")
    if status not in WORK_ITEM_STATUSES:
        raise WorkItemError(f"Unknown work-item status: {status!r}.")

    item["dispatched_at"] = _timestamp(item.get("dispatched_at"), "dispatched_at")
    item["heartbeat_at"] = _timestamp(item.get("heartbeat_at"), "heartbeat_at")
    item["lease_expires_at"] = _timestamp(
        item.get("lease_expires_at"), "lease_expires_at"
    )
    item["deadline_at"] = _timestamp(item.get("deadline_at"), "deadline_at")
    item["heartbeat_count"] = _integer(
        item.get("heartbeat_count"), "heartbeat_count"
    )
    item["lease_seconds"] = _integer(
        item.get("lease_seconds"), "lease_seconds", minimum=1
    )
    dispatched = _parse_timestamp(item["dispatched_at"], "dispatched_at")
    heartbeat = _parse_timestamp(item["heartbeat_at"], "heartbeat_at")
    lease_expires = _parse_timestamp(item["lease_expires_at"], "lease_expires_at")
    deadline = _parse_timestamp(item["deadline_at"], "deadline_at")
    if not dispatched <= heartbeat <= lease_expires <= deadline:
        raise WorkItemError(
            "Work-item timestamps must satisfy dispatched <= heartbeat <= lease <= deadline."
        )
    if deadline <= dispatched:
        raise WorkItemError("deadline_at must be later than dispatched_at.")

    expected_lease_expires = min(
        heartbeat + timedelta(seconds=item["lease_seconds"]), deadline
    )
    if lease_expires != expected_lease_expires:
        raise WorkItemError(
            "lease_expires_at must equal min(heartbeat_at + lease_seconds, deadline_at)."
        )
    if item["heartbeat_count"] == 0 and heartbeat != dispatched:
        raise WorkItemError("A work item without a heartbeat must retain dispatched_at.")
    if status == "dispatched" and (
        item["heartbeat_count"] != 0 or heartbeat != dispatched
    ):
        raise WorkItemError("A dispatched work item cannot contain heartbeat progress.")
    if status == "running" and item["heartbeat_count"] < 1:
        raise WorkItemError("A running work item requires at least one heartbeat.")
    if "handoff_budget_override" in item:
        item["handoff_budget_override"] = _validate_handoff_override(
            item["handoff_budget_override"]
        )

    if status == "completed":
        item["completed_at"] = _timestamp(item.get("completed_at"), "completed_at")
        completed = _parse_timestamp(item["completed_at"], "completed_at")
        if not dispatched <= completed < min(lease_expires, deadline):
            raise WorkItemError("completed_at must be before lease and deadline expiry.")
        item["completed_against_revision"] = _integer(
            item.get("completed_against_revision"),
            "completed_against_revision",
        )
        if item["completed_against_revision"] < item["input_revision"]:
            raise WorkItemError(
                "completed_against_revision cannot predate input_revision."
            )
        item["output_hashes"] = normalize_hashes(
            item.get("output_hashes"), "output_hashes", require_nonempty=True
        )
        item["output_paths"] = normalize_output_paths(
            item.get("output_paths"), require_nonempty=True
        )
        if set(item["output_hashes"]) != set(item["output_paths"]):
            raise WorkItemError("output_hashes and output_paths must bind the same names.")
        if any(
            key in item
            for key in ("terminal_at", "terminal_reason", "previous_status")
        ):
            raise WorkItemError("A completed work item cannot contain terminal fields.")
    elif status in {"failed", "cancelled", "timed_out", "superseded"}:
        item["terminal_at"] = _timestamp(item.get("terminal_at"), "terminal_at")
        terminal = _parse_timestamp(item["terminal_at"], "terminal_at")
        if terminal < dispatched:
            raise WorkItemError("terminal_at cannot predate dispatched_at.")
        item["terminal_reason"] = _text(item.get("terminal_reason"), "terminal_reason")
        if status == "timed_out" and terminal < min(lease_expires, deadline):
            raise WorkItemError("timed_out cannot be recorded before expiry.")
        if status in {"failed", "cancelled"} and terminal >= min(
            lease_expires, deadline
        ):
            raise WorkItemError(f"{status} must be recorded before expiry.")
        if status == "superseded":
            item["superseded_by_revision"] = _integer(
                item.get("superseded_by_revision"),
                "superseded_by_revision",
            )
            if item["superseded_by_revision"] <= item["input_revision"]:
                raise WorkItemError(
                    "superseded_by_revision must be newer than input_revision."
                )
            previous_status = item.get("previous_status")
            if previous_status not in ACTIVE_WORK_ITEM_STATUSES | {"completed"}:
                raise WorkItemError("superseded work item has an invalid previous_status.")
            if previous_status == "completed" and "completed_at" not in item:
                raise WorkItemError(
                    "A superseded completed work item must retain its completed output."
                )
            if "completed_at" in item:
                item["completed_at"] = _timestamp(
                    item.get("completed_at"), "completed_at"
                )
                item["completed_against_revision"] = _integer(
                    item.get("completed_against_revision"),
                    "completed_against_revision",
                )
                item["output_hashes"] = normalize_hashes(
                    item.get("output_hashes"),
                    "output_hashes",
                    require_nonempty=True,
                )
                item["output_paths"] = normalize_output_paths(
                    item.get("output_paths"), require_nonempty=True
                )
                if set(item["output_hashes"]) != set(item["output_paths"]):
                    raise WorkItemError(
                        "output_hashes and output_paths must bind the same names."
                    )
            elif any(
                key in item
                for key in ("completed_at", "completed_against_revision", "output_hashes", "output_paths")
            ):
                raise WorkItemError(
                    "A work item superseded before completion cannot contain outputs."
                )
        elif any(
            key in item
            for key in ("completed_at", "completed_against_revision", "output_hashes", "output_paths")
        ):
            raise WorkItemError(f"A {status} work item cannot contain completed outputs.")
    else:
        forbidden = (
            "completed_at",
            "completed_against_revision",
            "output_hashes",
            "output_paths",
            "terminal_at",
            "terminal_reason",
            "previous_status",
            "superseded_by_revision",
        )
        if any(key in item for key in forbidden):
            raise WorkItemError(f"An active {status} work item contains terminal fields.")
    return item


def _active(item: Mapping[str, Any], action: str) -> dict[str, Any]:
    validated = validate_work_item(item)
    if validated["status"] not in ACTIVE_WORK_ITEM_STATUSES:
        raise WorkItemStateError(
            f"Cannot {action} work item in {validated['status']} status."
        )
    return validated


def _expiration(item: Mapping[str, Any]) -> datetime:
    return min(
        _parse_timestamp(item["lease_expires_at"], "lease_expires_at"),
        _parse_timestamp(item["deadline_at"], "deadline_at"),
    )


def _on_time(item: Mapping[str, Any], at: Any) -> datetime:
    instant = _parse_timestamp(at, "at")
    heartbeat = _parse_timestamp(item["heartbeat_at"], "heartbeat_at")
    if instant < heartbeat:
        raise WorkItemStateError("A lifecycle event cannot predate the last heartbeat.")
    if instant >= _expiration(item):
        raise WorkItemExpiredError(
            f"Work item {item['work_item_id']} lease or deadline has expired."
        )
    return instant


def heartbeat_work_item(
    raw_item: Mapping[str, Any],
    *,
    at: str,
    lease_seconds: int | None = None,
) -> dict[str, Any]:
    """Renew an active work item's lease, clipped by its hard deadline."""

    item = _active(raw_item, "heartbeat")
    instant = _on_time(item, at)
    lease = (
        item["lease_seconds"]
        if lease_seconds is None
        else _integer(lease_seconds, "lease_seconds", minimum=1)
    )
    deadline = _parse_timestamp(item["deadline_at"], "deadline_at")
    item.update(
        {
            "status": "running",
            "heartbeat_at": _timestamp(instant, "heartbeat_at"),
            "heartbeat_count": item["heartbeat_count"] + 1,
            "lease_seconds": lease,
            "lease_expires_at": _timestamp(
                min(instant + timedelta(seconds=lease), deadline),
                "lease_expires_at",
            ),
        }
    )
    return validate_work_item(item)


def assert_current_baseline(
    raw_item: Mapping[str, Any],
    *,
    current_revision: int,
    current_input_hashes: Mapping[str, str],
) -> dict[str, Any]:
    """Reject output based on a changed or unverifiable input baseline.

    State revision drift is safe only when the work item bound at least one
    semantic input and every bound hash is still current.  This permits
    independent parallel roles to finish after an unrelated state write while
    still rejecting unbound work from an older revision.
    """

    item = validate_work_item(raw_item)
    revision = _integer(current_revision, "current_revision")
    if revision < item["input_revision"]:
        raise StaleBaselineError(
            "Current revision predates the work item's input revision."
        )
    current = normalize_hashes(current_input_hashes, "current_input_hashes")
    expected = item["input_hashes"]
    mismatched = [name for name, digest in expected.items() if current.get(name) != digest]
    if mismatched:
        raise StaleBaselineError(
            "Work-item input baseline changed: " + ",".join(mismatched)
        )
    if revision != item["input_revision"] and not expected:
        raise StaleBaselineError(
            "Revision changed and the work item has no input hashes to prove freshness."
        )
    return item


def complete_work_item(
    raw_item: Mapping[str, Any],
    *,
    at: str,
    current_revision: int,
    current_input_hashes: Mapping[str, str],
    output_hashes: Mapping[str, str],
    output_paths: Mapping[str, str],
) -> dict[str, Any]:
    """Complete an active attempt only while its lease and baseline are current."""

    item = _active(raw_item, "complete")
    instant = _on_time(item, at)
    item = assert_current_baseline(
        item,
        current_revision=current_revision,
        current_input_hashes=current_input_hashes,
    )
    item.update(
        {
            "status": "completed",
            "completed_at": _timestamp(instant, "completed_at"),
            "completed_against_revision": _integer(
                current_revision, "current_revision"
            ),
            "output_hashes": normalize_hashes(
                output_hashes, "output_hashes", require_nonempty=True
            ),
            "output_paths": normalize_output_paths(
                output_paths, require_nonempty=True
            ),
        }
    )
    return validate_work_item(item)


def assert_output_acceptable(
    raw_item: Mapping[str, Any],
    *,
    at: str,
    current_revision: int,
    current_input_hashes: Mapping[str, str],
) -> dict[str, Any]:
    """Validate completed output immediately before a stage submission uses it."""

    item = validate_work_item(raw_item)
    if item["status"] != "completed":
        raise WorkItemStateError(
            f"Output from a {item['status']} work item cannot be accepted."
        )
    instant = _parse_timestamp(at, "at")
    completed = _parse_timestamp(item["completed_at"], "completed_at")
    if instant < completed:
        raise WorkItemStateError("Output acceptance cannot predate completion.")
    if instant >= _expiration(item):
        raise WorkItemExpiredError(
            f"Work item {item['work_item_id']} output acceptance window has expired."
        )
    return assert_current_baseline(
        item,
        current_revision=current_revision,
        current_input_hashes=current_input_hashes,
    )


def cancel_work_item(
    raw_item: Mapping[str, Any],
    *,
    at: str,
    reason: str,
) -> dict[str, Any]:
    """Cancel an active, non-expired attempt."""

    item = _active(raw_item, "cancel")
    instant = _on_time(item, at)
    item.update(
        {
            "status": "cancelled",
            "terminal_at": _timestamp(instant, "terminal_at"),
            "terminal_reason": _text(reason, "reason"),
        }
    )
    return validate_work_item(item)


def fail_work_item(
    raw_item: Mapping[str, Any],
    *,
    at: str,
    reason: str,
) -> dict[str, Any]:
    """Record an active role attempt as failed before its lease expires."""

    item = _active(raw_item, "fail")
    instant = _on_time(item, at)
    item.update(
        {
            "status": "failed",
            "terminal_at": _timestamp(instant, "terminal_at"),
            "terminal_reason": _text(reason, "reason"),
        }
    )
    return validate_work_item(item)


def timeout_work_item(
    raw_item: Mapping[str, Any],
    *,
    at: str,
    reason: str,
) -> dict[str, Any]:
    """Mark an active attempt timed out once its lease or deadline expires."""

    item = _active(raw_item, "time out")
    instant = _parse_timestamp(at, "at")
    if instant < _expiration(item):
        raise WorkItemStateError("Cannot time out a work item before lease or deadline expiry.")
    item.update(
        {
            "status": "timed_out",
            "terminal_at": _timestamp(instant, "terminal_at"),
            "terminal_reason": _text(reason, "reason"),
        }
    )
    return validate_work_item(item)


def supersede_work_item(
    raw_item: Mapping[str, Any],
    *,
    at: str,
    reason: str,
    superseded_by_revision: int,
) -> dict[str, Any]:
    """Invalidate active or completed work after its input baseline changes."""

    item = validate_work_item(raw_item)
    if item["status"] not in ACTIVE_WORK_ITEM_STATUSES | {"completed"}:
        raise WorkItemStateError(
            f"Cannot supersede work item in {item['status']} status."
        )
    instant = _parse_timestamp(at, "at")
    earliest = _parse_timestamp(item["dispatched_at"], "dispatched_at")
    if item["status"] == "completed":
        earliest = _parse_timestamp(item["completed_at"], "completed_at")
    if instant < earliest:
        raise WorkItemStateError("Supersession cannot predate the current work-item state.")
    revision = _integer(
        superseded_by_revision, "superseded_by_revision"
    )
    if revision <= item["input_revision"]:
        raise WorkItemError(
            "superseded_by_revision must be newer than input_revision."
        )
    previous_status = item["status"]
    item.update(
        {
            "status": "superseded",
            "previous_status": previous_status,
            "superseded_by_revision": revision,
            "terminal_at": _timestamp(instant, "terminal_at"),
            "terminal_reason": _text(reason, "reason"),
        }
    )
    return validate_work_item(item)
