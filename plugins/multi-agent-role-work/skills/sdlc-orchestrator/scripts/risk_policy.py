"""Deterministic risk taxonomy and escalation policy for the SDLC workflow."""

from __future__ import annotations

import hashlib
import json
from datetime import date
from typing import Any, Callable


MODE_RANK = {"micro": 0, "quick": 1, "standard": 2, "strict": 3}
RISK_FLAGS = (
    "scope_expansion",
    "user_visible",
    "subjective_judgment",
    "weak_verification",
    "external_dependency",
    "api_change",
    "data_schema",
    "cross_module",
    "business_ambiguity",
    "systemic_verification_failure",
    "security_privacy",
    "irreversible",
    "data_migration",
    "production_release",
)
REQUIREMENT_AREAS = (
    "actors_permissions",
    "goals_scope",
    "business_rules_states",
    "data_api",
    "failures_edges",
    "compatibility_rollout",
    "subjective_choices",
    "acceptance_verification",
)
RISK_MINIMUM_MODE = {
    "scope_expansion": "quick",
    "user_visible": "quick",
    "subjective_judgment": "quick",
    "weak_verification": "quick",
    "external_dependency": "quick",
    "api_change": "standard",
    "data_schema": "standard",
    "cross_module": "standard",
    "business_ambiguity": "standard",
    "systemic_verification_failure": "standard",
    "security_privacy": "strict",
    "irreversible": "strict",
    "data_migration": "strict",
    "production_release": "strict",
}
QUICK_RISK_FLAGS = {
    flag for flag, minimum in RISK_MINIMUM_MODE.items() if minimum == "quick"
}
NON_WAIVABLE_ESCALATION_FLAGS = {
    "security_privacy",
    "irreversible",
    "data_migration",
    "production_release",
}
CLOSED_RISK_STATUSES = {"resolved", "withdrawn", "accepted_risk"}
RISK_SCOPE_KINDS = ("workflow", "stage", "capability")


def risk_scope_key(
    flags: list[str],
    *,
    scope_kind: str = "workflow",
    affected_scope: str,
    baseline_hash: str,
    origin_work_item: str,
) -> str:
    """Return a stable identity for one risk against one reviewed baseline."""
    normalized_scope_kind = scope_kind.strip()
    if normalized_scope_kind not in RISK_SCOPE_KINDS:
        raise ValueError(f"Unknown risk scope kind: {scope_kind!r}")
    normalized_flags = sorted({str(flag) for flag in flags if flag in RISK_FLAGS})
    payload = {
        "scope_kind": normalized_scope_kind,
        "affected_scope": affected_scope.strip(),
        "baseline_hash": baseline_hash.strip(),
        "flags": normalized_flags,
        "origin_work_item": origin_work_item.strip(),
    }
    rendered = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return "risk:" + hashlib.sha256(rendered).hexdigest()


def escalation_acceptance_expired(
    escalation: dict[str, Any], current_date: date | None = None
) -> bool:
    """Return whether a recorded risk acceptance is no longer in force."""
    if escalation.get("status") != "accepted_risk":
        return False
    try:
        expiry = date.fromisoformat(str(escalation.get("acceptance_expires_on", "")))
    except ValueError:
        return True
    return expiry < (current_date or date.today())


def recommended_mode_for(flags: list[str]) -> str:
    """Return the explicit minimum mode, including auditable combination rules."""
    unique_flags = set(flags)
    minimum = "micro"
    for flag in unique_flags:
        candidate = RISK_MINIMUM_MODE[flag]
        if MODE_RANK[candidate] > MODE_RANK[minimum]:
            minimum = candidate
    quick_flags = unique_flags & QUICK_RISK_FLAGS
    risky_verification_pair = (
        "weak_verification" in quick_flags
        and bool(quick_flags & {"user_visible", "external_dependency"})
    )
    if minimum == "quick" and (len(quick_flags) >= 3 or risky_verification_pair):
        minimum = "standard"
    return minimum


def combined_risk_flags(state: dict[str, Any]) -> list[str]:
    """Combine risks that affect the product workflow's assurance mode.

    Capability-scoped risks (for example a later paid-advertising or production
    action) keep their own assurance boundary and must not force unrelated
    product implementation through the strict workflow.
    """
    flags = list(state.get("risk_assessment", {}).get("flags", []))
    for report in state.get("risk_reports", []):
        if (
            report.get("status") not in CLOSED_RISK_STATUSES
            and report.get("scope_kind", "workflow") != "capability"
        ):
            flags.extend(report.get("flags", []))
    return list(dict.fromkeys(str(flag) for flag in flags if flag in RISK_FLAGS))


def refresh_escalation(
    state: dict[str, Any],
    *,
    summary: str,
    detected_by: str,
    timestamp: Callable[[], str],
) -> bool:
    """Recompute the escalation blocker from currently active risk evidence."""
    workflow = state["workflow"]
    combined = combined_risk_flags(state)
    recommended = recommended_mode_for(combined)
    active_reports = [
        report
        for report in state.get("risk_reports", [])
        if report.get("status") not in CLOSED_RISK_STATUSES
        and report.get("scope_kind", "workflow") != "capability"
    ]
    requires_escalation = MODE_RANK[recommended] > MODE_RANK[workflow["mode"]]
    if requires_escalation:
        report_ids = [str(report["id"]) for report in active_reports]
        state["escalation"] = {
            "status": "required",
            "from_mode": workflow["mode"],
            "recommended_mode": recommended,
            "report_id": report_ids[-1] if report_ids else "initial-assessment",
            "report_ids": report_ids,
            "flags": combined,
            "summary": summary,
            "detected_by": detected_by,
            "at": timestamp(),
        }
        return True
    previous = state.get("escalation", {})
    previous_report_ids = {
        str(report_id) for report_id in previous.get("report_ids", [])
    }
    accepted_report_ids = {
        str(report.get("id"))
        for report in state.get("risk_reports", [])
        if report.get("status") == "accepted_risk"
        and (
            not previous_report_ids
            or str(report.get("id")) in previous_report_ids
        )
    }
    if previous.get("status") == "accepted_risk" and accepted_report_ids:
        return False
    if previous.get("status") in {"required", "accepted_risk"}:
        state["escalation"] = {
            **previous,
            "status": "cleared",
            "recommended_mode": recommended,
            "cleared_reason": summary,
            "cleared_by": detected_by,
            "resolved_at": timestamp(),
        }
    return False
