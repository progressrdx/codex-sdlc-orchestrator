"""Command-line parser for the SDLC workflow state tool."""

from __future__ import annotations

import argparse
from typing import Any


MUTATING_COMMANDS = frozenset(
    {
        "init",
        "start",
        "pause",
        "resume",
        "activate",
        "deactivate",
        "abandon",
        "begin-work",
        "heartbeat-work",
        "complete-work",
        "cancel-work",
        "fail-work",
        "timeout-work",
        "repair-state",
        "assess-risk",
        "report-risk",
        "resolve-risk",
        "withdraw-risk",
        "accept-escalation-risk",
        "escalate-mode",
        "record-artifact",
        "record-artifact-bundle",
        "record-core-goals",
        "register-acceptance-criteria",
        "approve-scope-change",
        "submit-verification",
        "record-source-revision",
        "record-criterion-verdict",
        "record-user-journey",
        "record-core-outcome",
        "record-user-feedback",
        "record-delivery-confirmation",
        "add-issue",
        "resolve-issue",
        "disposition-issue",
        "decide",
        "submit-gate-review",
        "record-meeting",
        "record-human-approval",
        "advance",
        "reopen",
    }
)


def build_parser(api: Any) -> argparse.ArgumentParser:
    globals().update(
        {
            name: getattr(api, name)
            for name in dir(api)
            if name.isupper() or name.startswith("cmd_")
        }
    )
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", help="Repository root; defaults to git root or current directory")
    parser.add_argument("--id", help="Workflow ID; defaults to the active workflow")
    subparsers = parser.add_subparsers(dest="command", required=True)

    version = subparsers.add_parser("version", help="Print the loaded workflow plugin identity")
    version.add_argument("--runtime-root", default=str(api.default_plugin_root()))
    version.add_argument("--json", action="store_true")
    version.set_defaults(func=cmd_version)

    doctor = subparsers.add_parser(
        "doctor", help="Compare editable source, installed runtime, and loaded plugin identities"
    )
    doctor.add_argument("--runtime-root", default=str(api.default_plugin_root()))
    doctor.add_argument("--source-root")
    doctor.add_argument("--entry", default="skills/sdlc-orchestrator/scripts/workflow.py")
    doctor.add_argument("--json", action="store_true")
    doctor.set_defaults(func=cmd_doctor)

    init = subparsers.add_parser("init", help="Initialize and activate a workflow")
    init.add_argument(
        "--id",
        default=argparse.SUPPRESS,
        help="Workflow ID; generated from the title when omitted",
    )
    init.add_argument("--title", required=True)
    init.add_argument("--mode", choices=tuple(FLOWS), default="standard")
    init.add_argument("--request", required=True)
    init.add_argument(
        "--require-human-approval",
        action="append",
        choices=GATES,
        help="Require a separately evidenced human approval at this gate; repeat as needed",
    )
    init.add_argument(
        "--force",
        action="store_true",
        help="Deprecated and fail-closed; use deactivate/abandon plus a new ID",
    )
    init.set_defaults(func=cmd_init)

    start = subparsers.add_parser(
        "start",
        help="Start from a plain-language requirement and print the user-facing project view",
    )
    start.add_argument(
        "--id",
        default=argparse.SUPPRESS,
        help="Workflow ID; generated from the title when omitted",
    )
    start.add_argument("--request", required=True)
    start.add_argument("--title", help="Optional short title; defaults to the first request sentence")
    start.add_argument("--mode", choices=tuple(FLOWS), default="auto")
    start.add_argument(
        "--require-human-approval",
        action="append",
        choices=GATES,
        help="Require a separately evidenced human approval at this gate; repeat as needed",
    )
    start.add_argument(
        "--force",
        action="store_true",
        help="Deprecated and fail-closed; use deactivate/abandon plus a new ID",
    )
    start.set_defaults(func=cmd_start)

    status = subparsers.add_parser("status", help="Show workflow status")
    status.add_argument("--json", action="store_true")
    status.set_defaults(func=cmd_status)

    audit = subparsers.add_parser(
        "audit-state",
        help="Diagnose state integrity even when normal status loading is blocked",
    )
    audit.add_argument("--json", action="store_true")
    audit.set_defaults(func=cmd_audit_state)

    repair = subparsers.add_parser(
        "repair-state",
        help="Restore the last valid automatic state backup",
    )
    repair.add_argument("--from-backup", action="store_true", required=True)
    repair.add_argument("--confirm", required=True)
    repair.set_defaults(func=cmd_repair_state)

    overview = subparsers.add_parser(
        "overview", help="Show advanced internal workflow diagnostics"
    )
    overview.add_argument("--json", action="store_true")
    overview.set_defaults(func=cmd_overview)

    project = subparsers.add_parser(
        "project",
        help="Show the user-facing project view without internal workflow terminology",
    )
    project.add_argument("--json", action="store_true")
    project.set_defaults(func=cmd_project)

    list_cmd = subparsers.add_parser("list", help="List persisted workflows and pointer ownership")
    list_cmd.add_argument("--json", action="store_true")
    list_cmd.set_defaults(func=cmd_list)

    pause = subparsers.add_parser(
        "pause", help="Pause workflow routing without discarding state or evidence"
    )
    pause.add_argument("--reason", required=True)
    pause.set_defaults(func=cmd_pause)

    resume = subparsers.add_parser("resume", help="Resume a paused workflow at the same stage")
    resume.set_defaults(func=cmd_resume)

    activate = subparsers.add_parser("activate", help="Activate an inactive workflow by explicit ID")
    activate.set_defaults(func=cmd_activate)

    deactivate = subparsers.add_parser(
        "deactivate", help="Release routing ownership while preserving resumable evidence"
    )
    deactivate.add_argument("--reason", required=True)
    deactivate.set_defaults(func=cmd_deactivate)

    abandon = subparsers.add_parser(
        "abandon", help="Terminate a workflow without treating it as delivered"
    )
    abandon.add_argument("--reason", required=True)
    abandon.set_defaults(func=cmd_abandon)

    next_cmd = subparsers.add_parser("next", help="Show the next required evidence or transition")
    next_cmd.set_defaults(func=cmd_next)

    begin_work = subparsers.add_parser(
        "begin-work",
        help="Dispatch one role attempt against the current immutable input baseline",
    )
    begin_work.add_argument("--work-item-id", required=True)
    begin_work.add_argument("--role", choices=ROLES, required=True)
    begin_work.add_argument(
        "--actor-ref",
        required=True,
        help="Stable task/agent reference responsible for this attempt",
    )
    begin_work.add_argument(
        "--deadline-at",
        required=True,
        help="Hard ISO-8601 deadline with timezone",
    )
    begin_work.add_argument(
        "--lease-seconds",
        type=int,
        default=900,
        help="Renewable heartbeat lease in seconds (default: 900)",
    )
    begin_work.add_argument(
        "--override-evidence",
        help="Repository evidence authorizing a handoff beyond the stage budget",
    )
    begin_work.set_defaults(func=cmd_begin_work)

    heartbeat_work = subparsers.add_parser(
        "heartbeat-work", help="Renew an active role attempt lease"
    )
    heartbeat_work.add_argument("--work-item-id", required=True)
    heartbeat_work.add_argument(
        "--lease-seconds",
        type=int,
        help="Optional new lease duration in seconds",
    )
    heartbeat_work.set_defaults(func=cmd_heartbeat_work)

    complete_work = subparsers.add_parser(
        "complete-work",
        help="Complete a role attempt with content-addressed repository outputs",
    )
    complete_work.add_argument("--work-item-id", required=True)
    complete_work.add_argument(
        "--output",
        action="append",
        required=True,
        help="NAME=repository/path; repeat for multiple outputs",
    )
    complete_work.set_defaults(func=cmd_complete_work)

    cancel_work = subparsers.add_parser(
        "cancel-work", help="Cancel an active role attempt"
    )
    cancel_work.add_argument("--work-item-id", required=True)
    cancel_work.add_argument("--reason", required=True)
    cancel_work.set_defaults(func=cmd_cancel_work)

    fail_work = subparsers.add_parser(
        "fail-work", help="Record an active role attempt as failed"
    )
    fail_work.add_argument("--work-item-id", required=True)
    fail_work.add_argument("--reason", required=True)
    fail_work.set_defaults(func=cmd_fail_work)

    timeout_work = subparsers.add_parser(
        "timeout-work", help="Record an expired role attempt as timed out"
    )
    timeout_work.add_argument("--work-item-id", required=True)
    timeout_work.add_argument("--reason", required=True)
    timeout_work.set_defaults(func=cmd_timeout_work)

    risk = subparsers.add_parser(
        "assess-risk",
        help="Record structured requirement gaps, recommend a mode, and configure conditional gates",
    )
    risk.add_argument("--selected-mode", choices=tuple(MODE_RANK), required=True)
    risk.add_argument(
        "--checked-area",
        action="append",
        choices=REQUIREMENT_AREAS,
        help="Requirement category that was explicitly checked; all categories are required",
    )
    risk.add_argument("--risk", action="append", choices=RISK_FLAGS)
    risk.add_argument("--gap", action="append", help="Unresolved requirement gap; repeat as needed")
    risk.add_argument("--reason", action="append", help="Mode-selection reason; repeat as needed")
    risk.add_argument("--scope", required=True)
    risk.add_argument("--out-of-scope", required=True)
    risk.add_argument("--acceptance", required=True)
    risk.add_argument("--verification", required=True)
    risk.add_argument(
        "--evidence",
        required=True,
        help="Existing repository scope/risk document authored before state registration",
    )
    risk.add_argument(
        "--needs-clarification", choices=("auto", "yes", "no"), default="auto"
    )
    risk.add_argument(
        "--needs-confirmation", choices=("auto", "yes", "no"), default="auto"
    )
    risk.add_argument("--needs-preview", choices=("auto", "yes", "no"), default="auto")
    risk.set_defaults(func=cmd_assess_risk)

    report_risk = subparsers.add_parser(
        "report-risk",
        help="Record newly discovered risk and automatically require a safer mode when needed",
    )
    report_risk.add_argument(
        "--source",
        choices=("product", "engineering", "testing", "user", "coordinator"),
        required=True,
    )
    report_risk.add_argument("--risk", action="append", choices=RISK_FLAGS, required=True)
    report_risk.add_argument("--summary", required=True)
    report_risk.add_argument("--evidence", required=True)
    report_risk.add_argument(
        "--scope-kind",
        choices=("workflow", "stage", "capability"),
        default="workflow",
        help="Isolate optional external capabilities from the core product workflow.",
    )
    report_risk.add_argument(
        "--affected-scope",
        action="append",
        help="Stable affected stage/path/capability identifier; repeat as needed.",
    )
    report_risk.add_argument(
        "--origin-work-item",
        help="Optional work-item ID that discovered this risk.",
    )
    report_risk.set_defaults(func=cmd_report_risk)

    resolve_risk = subparsers.add_parser(
        "resolve-risk",
        help="Close a risk with separate resolution evidence and independent verification",
    )
    resolve_risk.add_argument("--risk-id", required=True)
    resolve_risk.add_argument("--resolution", required=True)
    resolve_risk.add_argument(
        "--resolved-by",
        choices=("product", "engineering", "testing", "user", "coordinator"),
        required=True,
    )
    resolve_risk.add_argument(
        "--verified-by",
        choices=("product", "engineering", "testing", "user", "coordinator"),
        required=True,
    )
    resolve_risk.add_argument("--evidence", required=True)
    resolve_risk.set_defaults(func=cmd_resolve_risk)

    withdraw_risk = subparsers.add_parser(
        "withdraw-risk",
        help="Withdraw a mistaken risk report with explicit reporter or user evidence",
    )
    withdraw_risk.add_argument("--risk-id", required=True)
    withdraw_risk.add_argument("--reason", required=True)
    withdraw_risk.add_argument(
        "--withdrawn-by",
        choices=("product", "engineering", "testing", "user", "coordinator"),
        required=True,
    )
    withdraw_risk.add_argument("--evidence", required=True)
    withdraw_risk.set_defaults(func=cmd_withdraw_risk)

    accept_risk = subparsers.add_parser(
        "accept-escalation-risk",
        help="Accept a waivable escalation risk with named human evidence and an expiry",
    )
    accept_risk.add_argument("--approved-by", required=True)
    accept_risk.add_argument("--reason", required=True)
    accept_risk.add_argument("--expires-on", required=True, help="YYYY-MM-DD")
    accept_risk.add_argument("--evidence", required=True)
    accept_risk.set_defaults(func=cmd_accept_escalation_risk)

    escalate = subparsers.add_parser(
        "escalate-mode",
        help="Apply a user-approved mode escalation and rewind to scope_check",
    )
    escalate.add_argument("--to-mode", choices=tuple(MODE_RANK), required=True)
    escalate.add_argument("--approved-by", required=True)
    escalate.add_argument("--reason", required=True)
    escalate.add_argument("--evidence", required=True)
    escalate.set_defaults(func=cmd_escalate_mode)

    artifact = subparsers.add_parser("record-artifact", help="Record an existing repository artifact")
    artifact.add_argument("--name", choices=ARTIFACTS, required=True)
    artifact.add_argument("--path", required=True)
    artifact.add_argument(
        "--work-item-id",
        help="Completed role work item that produced this artifact when role-owned.",
    )
    artifact.add_argument("--status", choices=("ready", "not_applicable", "superseded"), default="ready")
    artifact.add_argument("--notes")
    artifact.add_argument(
        "--build-command",
        help="Optional deterministic build/smoke command executed before a non-strict verification report is accepted",
    )
    artifact.add_argument(
        "--test-command",
        help="Deterministic test command required for a non-strict verification report",
    )
    artifact.add_argument(
        "--command-timeout",
        type=int,
        default=300,
        help="Per-command timeout in seconds for verification execution",
    )
    artifact.add_argument(
        "--output-path",
        action="append",
        help="Explicit generated-output directory allowed to change in isolated verification.",
    )
    artifact.set_defaults(func=cmd_record_artifact)

    artifact_bundle = subparsers.add_parser(
        "record-artifact-bundle",
        help="Atomically record multiple artifacts from one design baseline",
    )
    artifact_bundle.add_argument(
        "--manifest",
        required=True,
        help="Repository YAML or JSON manifest containing an artifacts list",
    )
    artifact_bundle.set_defaults(func=cmd_record_artifact_bundle)

    goals = subparsers.add_parser(
        "record-core-goals",
        help="Lock explicit user-confirmed outcomes before strict design work",
    )
    goals.add_argument("--goal", action="append", required=True, help="GOAL-001=outcome")
    goals.add_argument("--evidence", required=True)
    goals.set_defaults(func=cmd_record_core_goals)

    criteria = subparsers.add_parser(
        "register-acceptance-criteria",
        help="Register Must acceptance criteria from the current PRD",
    )
    criteria.add_argument("--criterion", action="append", required=True, help="AC-001=behavior")
    criteria.set_defaults(func=cmd_register_acceptance_criteria)

    scope_change = subparsers.add_parser(
        "approve-scope-change",
        help="Record explicit user authorization to reduce or defer a core goal or criterion",
    )
    scope_change.add_argument("--item", action="append", required=True, help="GOAL-001 or AC-001")
    scope_change.add_argument(
        "--disposition", choices=("removed", "deferred", "replaced"), required=True
    )
    scope_change.add_argument("--approved-by", required=True)
    scope_change.add_argument("--reason", required=True)
    scope_change.add_argument(
        "--impact-stage",
        choices=tuple(STAGE_LABELS),
        help="User-approved earliest affected stage; defaults to the conservative baseline.",
    )
    scope_change.add_argument(
        "--impact-reason",
        help="Why stages before --impact-stage remain valid; required with --impact-stage.",
    )
    scope_change.add_argument("--evidence", required=True)
    scope_change.set_defaults(func=cmd_approve_scope_change)

    verification_bundle = subparsers.add_parser(
        "submit-verification",
        help="Atomically register strict source, criterion, and journey evidence from one manifest",
    )
    verification_bundle.add_argument("--manifest", required=True)
    verification_bundle.set_defaults(func=cmd_submit_verification)

    source_revision = subparsers.add_parser(
        "record-source-revision",
        help="Bind strict verification to a committed source tree",
    )
    source_revision.add_argument("--evidence", required=True)
    source_revision.add_argument("--build-command", required=True)
    source_revision.add_argument("--test-command", required=True)
    source_revision.add_argument(
        "--source-path",
        action="append",
        help="Delivery path or module to bind; repeat as needed. Defaults to the whole Git tree.",
    )
    source_revision.add_argument(
        "--ignore-source-path",
        action="append",
        help="Tracked generated/vendor path to exclude from the binding; repeat as needed.",
    )
    source_revision.add_argument(
        "--output-path",
        action="append",
        help="Explicit generated-output directory allowed to change; repeat as needed.",
    )
    source_revision.set_defaults(func=cmd_record_source_revision)

    criterion_verdict = subparsers.add_parser(
        "record-criterion-verdict",
        help="Record independent testing verdict for one acceptance criterion",
    )
    criterion_verdict.add_argument("--criterion-id", required=True)
    criterion_verdict.add_argument(
        "--verdict", choices=("pass", "fail", "blocked", "not_applicable"), required=True
    )
    criterion_verdict.add_argument("--scope-change-id")
    criterion_verdict.add_argument("--evidence", required=True)
    criterion_verdict.add_argument(
        "--work-item-id",
        required=True,
        help="Completed testing work item with output criterion_verdict:<criterion-id>",
    )
    criterion_verdict.set_defaults(func=cmd_record_criterion_verdict)

    journey = subparsers.add_parser(
        "record-user-journey",
        help="Record semantic end-to-end testing against the final source revision",
    )
    journey.add_argument("--profile", choices=tuple(JOURNEY_PROFILES), default="web")
    journey.add_argument(
        "--check",
        action="append",
        required=True,
        help="check_name=pass|fail|blocked|not_applicable",
    )
    journey.add_argument("--evidence", required=True)
    journey.add_argument(
        "--work-item-id",
        required=True,
        help="Completed testing work item with exact journey_report output",
    )
    journey.set_defaults(func=cmd_record_user_journey)

    outcome = subparsers.add_parser(
        "record-core-outcome",
        help="Record product assessment of a user-confirmed core goal",
    )
    outcome.add_argument("--goal-id", required=True)
    outcome.add_argument(
        "--verdict", choices=("satisfied", "not_applicable", "deferred"), required=True
    )
    outcome.add_argument("--scope-change-id")
    outcome.add_argument("--evidence", required=True)
    outcome.add_argument(
        "--work-item-id",
        required=True,
        help="Completed testing work item with output core_outcome:<goal-id>",
    )
    outcome.set_defaults(func=cmd_record_core_outcome)

    feedback = subparsers.add_parser(
        "record-user-feedback",
        help="Record an explicit user preview verdict and rewind on requested changes",
    )
    feedback.add_argument(
        "--verdict", choices=("approve", "request_changes", "reject"), required=True
    )
    feedback.add_argument("--summary", required=True)
    feedback.add_argument("--evidence", required=True)
    feedback.add_argument("--affected-stage", choices=tuple(STAGE_LABELS))
    feedback.set_defaults(func=cmd_record_user_feedback)

    delivery = subparsers.add_parser(
        "record-delivery-confirmation",
        help="Record explicit user approval or requested changes for a verified delivery",
    )
    delivery.add_argument(
        "--verdict", choices=("approve", "request_changes", "reject"), required=True
    )
    delivery.add_argument("--summary", required=True)
    delivery.add_argument("--evidence", required=True)
    delivery.add_argument("--affected-stage", choices=tuple(STAGE_LABELS))
    delivery.set_defaults(func=cmd_record_delivery_confirmation)

    issue = subparsers.add_parser("add-issue", help="Add a tracked review issue")
    issue.add_argument("--source", choices=("product", "engineering", "testing", "user", "coordinator"), required=True)
    issue.add_argument("--owner", choices=("product", "engineering", "testing", "user", "coordinator"), default="coordinator")
    issue.add_argument("--severity", choices=("blocker", "major", "minor"), required=True)
    issue.add_argument("--summary", required=True)
    issue.set_defaults(func=cmd_add_issue)

    resolve = subparsers.add_parser("resolve-issue", help="Resolve a tracked issue")
    resolve.add_argument("--issue-id", required=True)
    resolve.add_argument("--resolution", required=True)
    resolve.add_argument("--resolved-by", choices=("product", "engineering", "testing", "user", "coordinator"), required=True)
    resolve.add_argument("--evidence", required=True, help="Repository file documenting the resolution")
    resolve.set_defaults(func=cmd_resolve_issue)

    disposition = subparsers.add_parser(
        "disposition-issue",
        help="Record an evidenced human acceptance or scheduled deferral for a major issue",
    )
    disposition.add_argument("--issue-id", required=True)
    disposition.add_argument("--disposition", choices=("accepted_risk", "deferred"), required=True)
    disposition.add_argument("--approved-by", required=True)
    disposition.add_argument("--rationale", required=True)
    disposition.add_argument("--evidence", required=True)
    disposition.add_argument("--due-date", help="Required for deferred issues; YYYY-MM-DD")
    disposition.set_defaults(func=cmd_disposition_issue)

    decide = subparsers.add_parser("decide", help="Record an independent role verdict at the current gate")
    decide.add_argument("--gate", choices=GATES, required=True)
    decide.add_argument("--role", choices=ROLES, required=True)
    decide.add_argument(
        "--actor-ref",
        required=True,
        help="Stable subagent task/session reference; provides traceability, not authentication.",
    )
    decide.add_argument(
        "--work-item-id",
        required=True,
        help="Completed independent review work item for this role and gate.",
    )
    decide.add_argument("--verdict", choices=("approve", "reject"), required=True)
    decide.add_argument("--evidence", required=True, help="Unique repository review record for this role and gate")
    decide.add_argument("--notes")
    decide.add_argument(
        "--finding",
        action="append",
        help="Structured finding as severity:owner:summary; required for reject.",
    )
    decide.set_defaults(func=cmd_decide)

    gate_review = subparsers.add_parser(
        "submit-gate-review",
        help="Atomically register every role verdict and the gate meeting from one manifest",
    )
    gate_review.add_argument("--manifest", required=True)
    gate_review.set_defaults(func=cmd_submit_gate_review)

    meeting = subparsers.add_parser(
        "record-meeting", help="Index structured notes for a cross-role communication"
    )
    meeting.add_argument("--type", choices=MEETING_TYPES, required=True)
    meeting.add_argument("--title", required=True)
    meeting.add_argument(
        "--participants",
        required=True,
        help="Comma-separated roles, for example product,engineering,testing",
    )
    meeting.add_argument("--outcome", choices=MEETING_OUTCOMES, required=True)
    meeting.add_argument("--path", required=True)
    meeting.set_defaults(func=cmd_record_meeting)

    human = subparsers.add_parser(
        "record-human-approval",
        help="Record a human authorization bound to current reviews and meeting evidence",
    )
    human.add_argument("--gate", choices=GATES, required=True)
    human.add_argument("--approved-by", required=True)
    human.add_argument("--evidence", required=True)
    human.add_argument("--notes")
    human.set_defaults(func=cmd_record_human_approval)

    advance = subparsers.add_parser("advance", help="Advance only when deterministic gate requirements pass")
    advance.set_defaults(func=cmd_advance)

    reopen = subparsers.add_parser("reopen", help="Reopen at an earlier stage and invalidate downstream decisions")
    reopen.add_argument("--stage", required=True)
    reopen.add_argument("--reason", required=True)
    reopen.set_defaults(func=cmd_reopen)
    return parser
