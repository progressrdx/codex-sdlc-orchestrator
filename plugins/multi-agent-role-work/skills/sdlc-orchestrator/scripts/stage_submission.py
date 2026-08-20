"""Pure planning primitives for atomic, idempotent stage submissions.

Persistence remains the caller's responsibility.  A caller prepares a plan
against the current state revision, applies its complete stage mutation once,
then stores the immutable receipt in the same state write.  Reusing the same
idempotency key and payload returns that receipt even after the workflow moves
on; reusing the key for different work fails closed.
"""

from __future__ import annotations

import copy
import hashlib
import json
import re
from typing import Any, Mapping, Sequence

from work_items import WorkItemError, normalize_hashes


STAGE_SUBMISSION_SCHEMA_VERSION = 1
_STABLE_REF = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/-]{2,127}")
_TOKEN = re.compile(r"[a-z][a-z0-9_-]{0,63}")
_STABLE_KEY = re.compile(r"[a-z][a-z0-9_-]*:[0-9a-f]{64}")


class StageSubmissionError(ValueError):
    """Base class for invalid stage-submission data."""


class RevisionConflict(StageSubmissionError):
    """Raised when a new submission was prepared against a stale revision."""


class IdempotencyConflict(StageSubmissionError):
    """Raised when an idempotency key is reused for different work."""


def _integer(value: Any, label: str, *, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise StageSubmissionError(f"{label} must be an integer >= {minimum}.")
    return value


def _text(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise StageSubmissionError(f"{label} must be non-empty text.")
    return value.strip()


def _stable_ref(value: Any, label: str) -> str:
    rendered = _text(value, label)
    if not _STABLE_REF.fullmatch(rendered):
        raise StageSubmissionError(
            f"{label} must be 3-128 stable-reference characters."
        )
    return rendered


def _token(value: Any, label: str) -> str:
    rendered = _text(value, label)
    if not _TOKEN.fullmatch(rendered):
        raise StageSubmissionError(
            f"{label} must start with a lowercase letter and contain only "
            "lowercase letters, digits, underscores, or hyphens."
        )
    return rendered


def _json_copy(value: Any, label: str) -> Any:
    try:
        rendered = json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
        return json.loads(rendered)
    except (TypeError, ValueError) as exc:
        raise StageSubmissionError(f"{label} must be finite JSON data.") from exc


def canonical_sha256(value: Any) -> str:
    """Hash JSON data with deterministic key ordering and no NaN values."""

    normalized = _json_copy(value, "value")
    rendered = json.dumps(
        normalized,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )
    return hashlib.sha256(rendered.encode("utf-8")).hexdigest()


def validate_submission_receipt(raw_receipt: Mapping[str, Any]) -> dict[str, Any]:
    """Validate and detach a stored idempotency receipt."""

    if not isinstance(raw_receipt, Mapping):
        raise StageSubmissionError("submission receipt must be a mapping.")
    receipt = copy.deepcopy(dict(raw_receipt))
    if receipt.get("schema_version") != STAGE_SUBMISSION_SCHEMA_VERSION:
        raise StageSubmissionError(
            "Unsupported stage-submission receipt schema_version: "
            f"{receipt.get('schema_version')!r}."
        )
    if receipt.get("status") != "applied":
        raise StageSubmissionError("submission receipt status must be applied.")
    receipt["idempotency_key"] = _stable_ref(
        receipt.get("idempotency_key"), "idempotency_key"
    )
    receipt["stage"] = _token(receipt.get("stage"), "stage")
    receipt["expected_revision"] = _integer(
        receipt.get("expected_revision"), "expected_revision"
    )
    receipt["applied_revision"] = _integer(
        receipt.get("applied_revision"), "applied_revision"
    )
    if receipt["applied_revision"] != receipt["expected_revision"] + 1:
        raise RevisionConflict(
            "An atomic stage submission must increment revision exactly once."
        )
    payload_sha256 = receipt.get("payload_sha256")
    if not isinstance(payload_sha256, str) or not re.fullmatch(
        r"[0-9a-f]{64}", payload_sha256
    ):
        raise StageSubmissionError("payload_sha256 must be a lowercase SHA-256 digest.")
    receipt["result"] = _json_copy(receipt.get("result", {}), "result")
    return receipt


def prepare_stage_submission(
    *,
    stage: str,
    current_stage: str,
    expected_revision: int,
    current_revision: int,
    idempotency_key: str,
    payload: Mapping[str, Any],
    receipts: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    """Return an ``apply`` plan or a prior successful ``replay`` receipt.

    Receipt lookup intentionally happens before checking current stage and
    revision.  A client retrying an already committed request therefore gets
    the original result even when the workflow has since advanced.
    """

    target_stage = _token(stage, "stage")
    active_stage = _token(current_stage, "current_stage")
    expected = _integer(expected_revision, "expected_revision")
    current = _integer(current_revision, "current_revision")
    key = _stable_ref(idempotency_key, "idempotency_key")
    if not isinstance(payload, Mapping) or not payload:
        raise StageSubmissionError("payload must be a non-empty mapping.")
    normalized_payload = _json_copy(dict(payload), "payload")
    payload_hash = canonical_sha256(normalized_payload)
    if not isinstance(receipts, Mapping):
        raise StageSubmissionError("receipts must be a mapping keyed by idempotency key.")

    existing = receipts.get(key)
    if existing is not None:
        receipt = validate_submission_receipt(existing)
        if (
            receipt["idempotency_key"] != key
            or receipt["stage"] != target_stage
            or receipt["expected_revision"] != expected
            or receipt["payload_sha256"] != payload_hash
        ):
            raise IdempotencyConflict(
                f"Idempotency key {key} is already bound to a different submission."
            )
        return {
            "action": "replay",
            "idempotency_key": key,
            "stage": target_stage,
            "expected_revision": expected,
            "payload_sha256": payload_hash,
            "receipt": receipt,
        }

    if active_stage != target_stage:
        raise StageSubmissionError(
            f"Cannot submit stage {target_stage} while current stage is {active_stage}."
        )
    if current != expected:
        raise RevisionConflict(
            f"Stage submission expected revision {expected}, found {current}."
        )
    return {
        "action": "apply",
        "idempotency_key": key,
        "stage": target_stage,
        "expected_revision": expected,
        "payload_sha256": payload_hash,
        "payload": normalized_payload,
    }


def finalize_stage_submission(
    raw_plan: Mapping[str, Any],
    *,
    applied_revision: int,
    result: Mapping[str, Any],
) -> dict[str, Any]:
    """Create the immutable receipt stored with a successful atomic mutation."""

    if not isinstance(raw_plan, Mapping) or raw_plan.get("action") != "apply":
        raise StageSubmissionError("Only an apply plan can be finalized.")
    expected = _integer(raw_plan.get("expected_revision"), "expected_revision")
    applied = _integer(applied_revision, "applied_revision")
    if applied != expected + 1:
        raise RevisionConflict(
            "An atomic stage submission must increment revision exactly once."
        )
    if not isinstance(result, Mapping):
        raise StageSubmissionError("result must be a mapping.")
    receipt = {
        "schema_version": STAGE_SUBMISSION_SCHEMA_VERSION,
        "status": "applied",
        "idempotency_key": _stable_ref(
            raw_plan.get("idempotency_key"), "idempotency_key"
        ),
        "stage": _token(raw_plan.get("stage"), "stage"),
        "expected_revision": expected,
        "payload_sha256": raw_plan.get("payload_sha256"),
        "applied_revision": applied,
        "result": _json_copy(dict(result), "result"),
    }
    return validate_submission_receipt(receipt)


def store_submission_receipt(
    raw_receipts: Mapping[str, Mapping[str, Any]],
    raw_receipt: Mapping[str, Any],
) -> tuple[dict[str, dict[str, Any]], str]:
    """Insert an immutable receipt or report an exact replay without mutation."""

    if not isinstance(raw_receipts, Mapping):
        raise StageSubmissionError("receipts must be a mapping.")
    receipts = copy.deepcopy(dict(raw_receipts))
    receipt = validate_submission_receipt(raw_receipt)
    key = receipt["idempotency_key"]
    existing = receipts.get(key)
    if existing is not None:
        validated_existing = validate_submission_receipt(existing)
        if validated_existing != receipt:
            raise IdempotencyConflict(
                f"Idempotency key {key} already has a different receipt."
            )
        receipts[key] = validated_existing
        return receipts, "replayed"
    receipts[key] = receipt
    return receipts, "inserted"


def _stable_key(prefix: str, payload: Mapping[str, Any]) -> str:
    return f"{prefix}:{canonical_sha256(payload)}"


def meeting_stable_key(
    *,
    workflow_id: str,
    stage: str,
    meeting_type: str,
    baseline_hashes: Mapping[str, str],
    review_round: int,
) -> str:
    """Key one meeting per workflow, baseline, type, and explicit review round."""

    try:
        hashes = normalize_hashes(
            baseline_hashes, "baseline_hashes", require_nonempty=True
        )
    except WorkItemError as exc:
        raise StageSubmissionError(str(exc)) from exc
    return _stable_key(
        "meeting",
        {
            "workflow_id": _stable_ref(workflow_id, "workflow_id"),
            "stage": _token(stage, "stage"),
            "meeting_type": _token(meeting_type, "meeting_type"),
            "baseline_hashes": hashes,
            "review_round": _integer(review_round, "review_round", minimum=1),
        },
    )


def _normalized_values(values: Any, label: str) -> list[str]:
    if isinstance(values, (str, bytes)) or not isinstance(values, Sequence):
        raise StageSubmissionError(f"{label} must be a sequence of non-empty values.")
    normalized = sorted({_text(value, label) for value in values})
    if not normalized:
        raise StageSubmissionError(f"{label} must contain at least one value.")
    return normalized


def risk_stable_key(
    *,
    workflow_id: str,
    flags: Sequence[str],
    affected_scope: Sequence[str],
    baseline_hashes: Mapping[str, str],
    origin_work_item_id: str,
) -> str:
    """Key a risk by semantic flags, affected scope, origin, and input baseline."""

    try:
        hashes = normalize_hashes(
            baseline_hashes, "baseline_hashes", require_nonempty=True
        )
    except WorkItemError as exc:
        raise StageSubmissionError(str(exc)) from exc
    return _stable_key(
        "risk",
        {
            "workflow_id": _stable_ref(workflow_id, "workflow_id"),
            "flags": _normalized_values(flags, "flags"),
            "affected_scope": _normalized_values(affected_scope, "affected_scope"),
            "baseline_hashes": hashes,
            "origin_work_item_id": _stable_ref(
                origin_work_item_id, "origin_work_item_id"
            ),
        },
    )


def upsert_stable_record(
    raw_records: Sequence[Mapping[str, Any]],
    raw_record: Mapping[str, Any],
    *,
    key_field: str = "stable_key",
) -> tuple[list[dict[str, Any]], str]:
    """Insert, replay, or replace one stable-keyed record without appending duplicates."""

    if isinstance(raw_records, (str, bytes)) or not isinstance(raw_records, Sequence):
        raise StageSubmissionError("records must be a sequence of mappings.")
    if not isinstance(raw_record, Mapping):
        raise StageSubmissionError("record must be a mapping.")
    field = _text(key_field, "key_field")
    record = _json_copy(dict(raw_record), "record")
    stable_key = record.get(field)
    if not isinstance(stable_key, str) or not _STABLE_KEY.fullmatch(stable_key):
        raise StageSubmissionError(
            f"record[{field!r}] must be a generated meeting/risk stable key."
        )

    records: list[dict[str, Any]] = []
    matching_indexes: list[int] = []
    for index, raw_existing in enumerate(raw_records):
        if not isinstance(raw_existing, Mapping):
            raise StageSubmissionError(f"records[{index}] must be a mapping.")
        existing = _json_copy(dict(raw_existing), f"records[{index}]")
        if existing.get(field) == stable_key:
            matching_indexes.append(index)
        records.append(existing)
    if len(matching_indexes) > 1:
        raise StageSubmissionError(
            f"Existing records contain duplicate stable key: {stable_key}."
        )
    if not matching_indexes:
        records.append(record)
        return records, "inserted"
    index = matching_indexes[0]
    if records[index] == record:
        return records, "replayed"
    records[index] = record
    return records, "updated"
