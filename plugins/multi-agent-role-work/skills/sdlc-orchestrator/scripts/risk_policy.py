"""Deterministic risk taxonomy and escalation policy for the SDLC workflow."""

from __future__ import annotations

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
    """Combine baseline flags with reports that still affect mode selection."""
    flags = list(state.get("risk_assessment", {}).get("flags", []))
    for report in state.get("risk_reports", []):
        if report.get("status") not in CLOSED_RISK_STATUSES:
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
    if previous.get("status") == "required":
        state["escalation"] = {
            **previous,
            "status": "cleared",
            "recommended_mode": recommended,
            "cleared_reason": summary,
            "cleared_by": detected_by,
            "resolved_at": timestamp(),
        }
    return False
