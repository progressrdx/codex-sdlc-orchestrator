from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

try:
    import fcntl
except ImportError:  # pragma: no cover - Windows uses the runtime's msvcrt branch.
    fcntl = None


SCRIPT = (
    Path(__file__).resolve().parents[1]
    / "plugins"
    / "multi-agent-role-work"
    / "skills"
    / "sdlc-orchestrator"
    / "scripts"
    / "workflow.py"
)


class WorkflowToolTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.meeting_counter = 0
        self.risk_assessment_counter = 0

    def tearDown(self) -> None:
        self.temp.cleanup()

    def run_tool(
        self,
        *args: str,
        expected: int = 0,
        env: dict[str, str] | None = None,
    ) -> subprocess.CompletedProcess[str]:
        command = [sys.executable, str(SCRIPT), "--root", str(self.root), *args]
        result = subprocess.run(
            command,
            text=True,
            capture_output=True,
            check=False,
            env=env,
        )
        self.assertEqual(
            expected,
            result.returncode,
            msg=f"command={command}\nstdout={result.stdout}\nstderr={result.stderr}",
        )
        return result

    def init(
        self,
        mode: str = "standard",
        human_gates: tuple[str, ...] = (),
    ) -> None:
        self.workflow_mode = mode
        self.run_tool(
            "init",
            "--id",
            "REQ-test-flow",
            "--title",
            "Test workflow",
            "--mode",
            mode,
            "--request",
            "Build a deterministic example.",
            *(
                item
                for gate in human_gates
                for item in ("--require-human-approval", gate)
            ),
        )

    def assess_risk(
        self,
        selected_mode: str | None = None,
        *,
        risks: tuple[str, ...] | None = None,
        gaps: tuple[str, ...] | None = None,
        clarification: str | None = None,
        confirmation: str | None = None,
        preview: str | None = None,
        expected: int = 0,
    ) -> subprocess.CompletedProcess[str]:
        mode = selected_mode or self.workflow_mode
        default_risks = {
            "micro": (),
            "quick": ("user_visible",),
            "standard": ("cross_module",),
            "strict": ("data_migration",),
        }
        full_flow = mode in {"standard", "strict"}
        self.risk_assessment_counter += 1
        risk_evidence = self.write_artifact(
            f"requirements/REQ-test-flow/00-scope-and-risk-{self.risk_assessment_counter}.md",
            (
                "# Scope and risk assessment\n\n"
                "## Task baseline\n\nThe intended outcome, scope, exclusions, acceptance, and verification are explicit.\n\n"
                "## Requirement gaps\n\nAll eight required categories were checked and material gaps are listed in state.\n\n"
                "## Risk flags\n\nApplicable flags and their evidence were independently assessed.\n\n"
                "## Workflow decision\n\nThe recommended and selected modes plus conditional gates are documented.\n"
            ),
        )
        return self.run_tool(
            "assess-risk",
            "--selected-mode",
            mode,
            *(
                item
                for area in (
                    "actors_permissions",
                    "goals_scope",
                    "business_rules_states",
                    "data_api",
                    "failures_edges",
                    "compatibility_rollout",
                    "subjective_choices",
                    "acceptance_verification",
                )
                for item in ("--checked-area", area)
            ),
            "--scope",
            "Deliver the explicitly bounded workflow behavior.",
            "--out-of-scope",
            "No unrelated platform or deployment changes.",
            "--acceptance",
            "The requested behavior is observable and satisfies the recorded criteria.",
            "--verification",
            "Run focused automated checks and independent behavior verification.",
            "--evidence",
            str(risk_evidence.relative_to(self.root)),
            *(item for flag in (risks if risks is not None else default_risks[mode]) for item in ("--risk", flag)),
            *(item for gap in (gaps or ()) for item in ("--gap", gap)),
            "--needs-clarification",
            clarification or ("yes" if full_flow or mode == "quick" else "no"),
            "--needs-confirmation",
            confirmation or ("yes" if full_flow or mode == "quick" else "no"),
            "--needs-preview",
            preview or ("yes" if full_flow or mode == "quick" else "no"),
            expected=expected,
        )

    def write_artifact(
        self,
        filename: str,
        text: str = (
            "# Evidence\n\nThis file contains substantive workflow evidence for deterministic gate testing.\n\n"
            "## Scope\n\nThe relevant workflow scope is documented here.\n\n"
            "## Result\n\nThe required result and supporting details are recorded.\n"
        ),
    ) -> Path:
        path = self.root / "docs" / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path

    def record(
        self,
        name: str,
        filename: str,
        status: str = "ready",
        notes: str | None = None,
        text: str | None = None,
    ) -> None:
        path = self.write_artifact(filename, text) if text is not None else self.write_artifact(filename)
        self.run_tool(
            "record-artifact",
            "--name",
            name,
            "--path",
            str(path.relative_to(self.root)),
            "--status",
            status,
            *(["--notes", notes] if notes else []),
        )

    def record_clarification(self) -> None:
        self.record(
            "clarification_questions",
            "requirements/REQ-test-flow/00-clarification.md",
            text=(
                "# Clarification questions\n\n"
                "## Questions\n\nWhich user roles, business rules, and edge cases need explicit handling?\n\n"
                "## Missing details\n\nPermissions, empty states, failure behavior, and rollout expectations are missing.\n\n"
                "## Assumptions and acceptance\n\nAssumption: the user will confirm scope before PRD or implementation. "
                "Acceptance criteria must be observable before delivery.\n"
            ),
        )

    def confirm_requirements(self) -> None:
        self.record(
            "requirement_confirmation",
            "requirements/REQ-test-flow/00-requirement-confirmation.md",
            text=(
                "# User requirement confirmation\n\n"
                "## User decision\n\nThe user confirmed and approved the clarified scope for this workflow.\n\n"
                "## Confirmed scope\n\nProduct may proceed to PRD or design using the documented clarification.\n\n"
                "## Open items\n\nNo unresolved business decision blocks the next stage.\n"
            ),
        )
        if self.workflow_mode == "strict":
            goals = self.write_artifact(
                "requirements/REQ-test-flow/00-core-goals.md",
                (
                    "# User-confirmed core goals\n\n"
                    "## User confirmation\n\nThe user confirmed and approved GOAL-001 as the immutable outcome baseline.\n\n"
                    "## GOAL-001\n\nDeliver the real requested behavior, not a mock-only substitute.\n\n"
                    "## Scope integrity\n\nAny reduction requires a separate user-approved scope change.\n"
                ),
            )
            self.run_tool(
                "record-core-goals",
                "--goal",
                "GOAL-001=Deliver the real requested behavior.",
                "--evidence",
                str(goals.relative_to(self.root)),
            )

    def complete_discovery(self) -> None:
        self.run_tool("advance")
        self.assess_risk()
        self.run_tool("advance")
        self.record_clarification()
        self.run_tool("advance")
        self.confirm_requirements()
        self.run_tool("advance")

    def record_prototype(self) -> None:
        self.record(
            "prototype",
            "requirements/REQ-test-flow/07-prototype.md",
            text=(
                "# Prototype preview\n\n"
                "## Scope\n\nThe preview covers the approved workflow direction and the user-visible path.\n\n"
                "## How to inspect\n\nOpen the local demo or inspect the screenshot evidence before final implementation.\n\n"
                "## Notes\n\nThe prototype is intentionally small and exists to validate product direction.\n"
            ),
        )

    def record_user_feedback(self) -> None:
        evidence = self.write_artifact(
            "requirements/REQ-test-flow/07-user-feedback.md",
            (
                "# User feedback\n\n"
                "## User decision\n\nThe user reviewed the preview and approved the direction for implementation.\n\n"
                "## Feedback summary\n\nNo product-direction changes are requested before implementation.\n\n"
                "## Follow-up\n\nProceed with full implementation and verification.\n"
            ),
        )
        self.run_tool(
            "record-user-feedback",
            "--verdict",
            "approve",
            "--summary",
            "The user approved the preview direction.",
            "--evidence",
            str(evidence.relative_to(self.root)),
        )

    def complete_preview(self) -> None:
        self.record_prototype()
        self.run_tool("advance")
        self.record_user_feedback()
        self.run_tool("advance")

    def confirm_delivery(self, verdict: str = "approve") -> None:
        evidence = self.write_artifact(
            f"requirements/REQ-test-flow/delivery-{verdict}.md",
            (
                "# User delivery confirmation\n\n"
                f"## User verdict\n\nThe user recorded {verdict} after inspecting the verified result.\n\n"
                "## Evidence reviewed\n\nThe implementation summary and independent verification report were shown.\n\n"
                "## Next step\n\nComplete delivery when approved; otherwise revise the affected work.\n"
            ),
        )
        self.run_tool(
            "record-delivery-confirmation",
            "--verdict",
            verdict,
            "--summary",
            f"The user chose {verdict} after reviewing delivery evidence.",
            "--evidence",
            str(evidence.relative_to(self.root)),
        )

    def reach_strict_verification(self) -> None:
        subprocess.run(["git", "init", "-q", str(self.root)], check=True)
        subprocess.run(
            ["git", "-C", str(self.root), "config", "user.email", "tests@example.com"],
            check=True,
        )
        subprocess.run(
            ["git", "-C", str(self.root), "config", "user.name", "Workflow Tests"],
            check=True,
        )
        source = self.root / "app.py"
        source.write_text("print('verified')\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(self.root), "add", "app.py"], check=True)
        subprocess.run(["git", "-C", str(self.root), "commit", "-qm", "verified source"], check=True)

        self.init("strict")
        self.complete_discovery()
        self.record(
            "prd",
            "requirements/REQ-test-flow/01-prd.md",
            text=(
                "# Product requirements\n\n"
                "## User outcome\n\nDeliver the confirmed real workflow behavior.\n\n"
                "## Acceptance criteria\n\nAC-001: The final user journey works with semantically correct data.\n\n"
                "## Exclusions\n\nNo core goal may be silently replaced by a mock.\n"
            ),
        )
        self.run_tool(
            "register-acceptance-criteria",
            "--criterion",
            "AC-001=The final user journey works with semantically correct data.",
        )
        self.run_tool("advance")
        self.approve("prd_review", ("product", "engineering", "testing"))
        self.run_tool("advance")
        self.record("technical_design", "requirements/REQ-test-flow/03-design.md")
        self.record(
            "database_design",
            "requirements/REQ-test-flow/04-database.md",
            "not_applicable",
            "No persistence changes are needed.",
        )
        self.record("test_plan", "requirements/REQ-test-flow/05-test-plan.md")
        self.record("release_plan", "requirements/REQ-test-flow/07-release.md")
        self.run_tool("advance")
        self.approve("readiness_review", ("product", "engineering", "testing"))
        human = self.write_artifact(
            "requirements/REQ-test-flow/approvals/readiness-human.md",
            "# Human approval: readiness_review\n\n"
            "Alice reviewed the current role verdicts and meeting record.\n\n"
            "## Authorization\n\nAlice explicitly records approve for this readiness review.\n",
        )
        self.run_tool(
            "record-human-approval",
            "--gate",
            "readiness_review",
            "--approved-by",
            "Alice",
            "--evidence",
            str(human.relative_to(self.root)),
        )
        self.run_tool("advance")
        self.complete_preview()
        self.record("implementation", "requirements/REQ-test-flow/06-implementation.md")
        self.run_tool("advance")
        self.record("verification_report", "requirements/REQ-test-flow/08-verification.md")
        source_evidence = self.write_artifact(
            "requirements/REQ-test-flow/08-source-revision.md",
            "# Source revision binding\n\n"
            "## Revision\n\nThe committed working tree is the exact verification target.\n\n"
            "## Commands\n\nBuild and test commands are recorded in state.\n",
        )
        self.run_tool(
            "record-source-revision",
            "--evidence",
            str(source_evidence.relative_to(self.root)),
            "--build-command",
            "none",
            "--test-command",
            "python -m unittest",
        )
        verdict_doc = self.write_artifact(
            "requirements/REQ-test-flow/08-verdict-ac001.md",
            "# Verification verdict: AC-001\n\n"
            "AC-001: pass — the final user journey works with semantically correct data.\n\n"
            "## Method\n\nIndependent testing executed the recorded test command against the verified source.\n",
        )
        self.run_tool(
            "record-criterion-verdict",
            "--criterion-id",
            "AC-001",
            "--verdict",
            "pass",
            "--evidence",
            str(verdict_doc.relative_to(self.root)),
        )

    def record_gate_meeting(
        self,
        gate: str,
        roles: tuple[str, ...],
        outcome: str = "approved",
    ) -> None:
        self.meeting_counter += 1
        participants = ",".join(roles)
        role_sections = "\n\n".join(
            f"### {role}\n\n{role} provided the material position and supporting evidence."
            for role in roles
        )
        evidence = self.write_artifact(
            f"requirements/REQ-test-flow/meetings/MTG-draft-{self.meeting_counter:03d}-{gate}.md",
            f"# Meeting notes: {gate.replace('_', ' ')}\n\n"
            f"## Metadata\n\nDraft sequence: {self.meeting_counter}.\n\n"
            f"## Participants\n\n{participants}\n\n"
            f"## Key role positions\n\n{role_sections}\n\n"
            f"## Decisions and rationale\n\nAll current role verdicts were discussed and retained.\n\n"
            f"## Outcome\n\n{outcome}\n",
        )
        self.run_tool(
            "record-meeting",
            "--type",
            gate,
            "--title",
            f"{gate} meeting",
            "--participants",
            participants,
            "--outcome",
            outcome,
            "--path",
            str(evidence.relative_to(self.root)),
        )

    def approve(
        self,
        gate: str,
        roles: tuple[str, ...],
        *,
        record_meeting: bool = True,
    ) -> None:
        for role in roles:
            evidence = self.write_artifact(
                f"requirements/REQ-test-flow/reviews/{gate}-{role}.md",
                f"# Review: {gate.replace('_', ' ')} / {role}\n\nInputs were checked against the gate criteria. "
                "No blocking findings remain.\n\n## Verdict\n\napprove\n",
            )
            self.run_tool(
                "decide",
                "--gate",
                gate,
                "--role",
                role,
                "--verdict",
                "approve",
                "--evidence",
                str(evidence.relative_to(self.root)),
            )
        if record_meeting:
            self.record_gate_meeting(gate, roles)

    def test_standard_flow_requires_artifacts_and_three_role_prd_gate(self) -> None:
        self.init()
        self.complete_discovery()
        blocked = self.run_tool("advance", expected=2)
        self.assertIn("artifact:prd", blocked.stderr)

        self.record("prd", "requirements/REQ-test-flow/01-prd.md")
        self.run_tool("advance")
        blocked = self.run_tool("advance", expected=2)
        self.assertIn("approval:prd_review:product", blocked.stderr)
        self.approve("prd_review", ("product", "engineering", "testing"))
        self.run_tool("advance")
        status = self.run_tool("status")
        self.assertIn("Stage: design", status.stdout)

    def test_start_accepts_plain_request_and_prints_overview(self) -> None:
        started = self.run_tool(
            "start",
            "--request",
            "实现会员积分过期功能。需要产品、研发和测试评审。",
        )
        self.assertIn("Initialized REQ-", started.stdout)
        self.assertIn("Overview:", started.stdout)
        self.assertIn("Stage: intake (Intake)", started.stdout)
        self.assertIn("Next action: Advance to Scope and risk check.", started.stdout)

        overview = self.run_tool("overview", "--json")
        payload = json.loads(overview.stdout)
        self.assertEqual("auto", payload["mode"])
        self.assertEqual("intake", payload["stage"])
        self.assertTrue(payload["can_advance"])
        self.assertIn("original_request", payload["completed_artifacts"])

    def test_discovery_blocks_formal_work_until_user_confirms_requirements(self) -> None:
        self.init()
        self.run_tool("advance")
        blocked = self.run_tool("advance", expected=2)
        self.assertIn("artifact:risk_assessment", blocked.stderr)
        self.assess_risk()
        self.run_tool("advance")
        blocked = self.run_tool("advance", expected=2)
        self.assertIn("artifact:clarification_questions", blocked.stderr)
        weak = self.write_artifact(
            "requirements/REQ-test-flow/weak-clarification.md",
            "# Clarification\n\n## Questions\n\nOnly one question is listed.\n\n## Result\n\nInsufficient.\n",
        )
        rejected = self.run_tool(
            "record-artifact",
            "--name",
            "clarification_questions",
            "--path",
            str(weak.relative_to(self.root)),
            expected=2,
        )
        self.assertIn("missing: missing", rejected.stderr)

        self.record_clarification()
        self.run_tool("advance")
        blocked = self.run_tool("advance", expected=2)
        self.assertIn("artifact:requirement_confirmation", blocked.stderr)

        unconfirmed = self.write_artifact(
            "requirements/REQ-test-flow/unconfirmed.md",
            "# Requirement summary\n\n## User decision\n\nThe user has not decided yet.\n\n"
            "## Scope\n\nThe workflow cannot proceed.\n\n## Open items\n\nNeed confirmation.\n",
        )
        rejected = self.run_tool(
            "record-artifact",
            "--name",
            "requirement_confirmation",
            "--path",
            str(unconfirmed.relative_to(self.root)),
            expected=2,
        )
        self.assertIn("explicit user confirmation", rejected.stderr)

        self.confirm_requirements()
        self.run_tool("advance")
        self.assertIn("Stage: prd", self.run_tool("status").stdout)

    def test_overview_reports_missing_evidence_and_issues(self) -> None:
        self.init()
        self.complete_discovery()
        self.run_tool(
            "add-issue",
            "--source",
            "testing",
            "--owner",
            "product",
            "--severity",
            "blocker",
            "--summary",
            "Expiration policy is undefined.",
        )
        overview = self.run_tool("overview")
        self.assertIn("Stage: prd (PRD drafting)", overview.stdout)
        self.assertIn("Can advance: no", overview.stdout)
        self.assertIn("artifact:prd", overview.stdout)
        self.assertIn("ISSUE-001 blocker open owner=product", overview.stdout)

    def test_blocker_prevents_gate_until_resolved(self) -> None:
        self.init()
        self.complete_discovery()
        self.record("prd", "requirements/REQ-test-flow/01-prd.md")
        self.run_tool("advance")
        self.approve("prd_review", ("product", "engineering", "testing"))
        self.run_tool(
            "add-issue",
            "--source",
            "testing",
            "--owner",
            "product",
            "--severity",
            "blocker",
            "--summary",
            "Duplicate submission behavior is undefined.",
        )
        blocked = self.run_tool("advance", expected=2)
        self.assertIn("blocker:ISSUE-001", blocked.stderr)
        resolution_evidence = self.write_artifact(
            "requirements/REQ-test-flow/decisions/ISSUE-001.md",
            "# ISSUE-001 resolution\n\nProduct defined idempotent duplicate handling.\n\n"
            "## Decision\n\nRepeated submissions return the original result.\n\n"
            "## Evidence\n\nThe PRD was updated and will be reviewed again.\n",
        )
        self.run_tool(
            "resolve-issue",
            "--issue-id",
            "ISSUE-001",
            "--resolution",
            "PRD now defines idempotent duplicate handling.",
            "--resolved-by",
            "product",
            "--evidence",
            str(resolution_evidence.relative_to(self.root)),
        )
        self.record_gate_meeting("prd_review", ("product", "engineering", "testing"))
        self.run_tool("advance")

    def test_gate_requires_current_cross_role_meeting_notes(self) -> None:
        self.init()
        self.complete_discovery()
        self.record("prd", "requirements/REQ-test-flow/01-prd.md")
        self.run_tool("advance")
        roles = ("product", "engineering", "testing")
        self.approve("prd_review", roles, record_meeting=False)
        blocked = self.run_tool("advance", expected=2)
        self.assertIn("meeting:prd_review", blocked.stderr)
        self.record_gate_meeting("prd_review", roles)
        self.run_tool("advance")

    def test_quick_mode_skips_prd_and_requires_two_readiness_roles(self) -> None:
        self.init("quick")
        self.complete_discovery()
        status = self.run_tool("status")
        self.assertIn("Stage: design", status.stdout)
        self.record("technical_design", "requirements/REQ-test-flow/03-design.md")
        self.record("test_plan", "requirements/REQ-test-flow/05-test-plan.md")
        self.run_tool("advance")
        self.approve("readiness_review", ("engineering", "testing"))
        self.run_tool("advance")
        self.assertIn("Stage: prototype", self.run_tool("status").stdout)
        self.complete_preview()
        self.assertIn("Stage: implementation", self.run_tool("status").stdout)

    def test_user_feedback_blocks_final_implementation_until_preview_is_approved(self) -> None:
        self.init("quick")
        self.complete_discovery()
        self.record("technical_design", "requirements/REQ-test-flow/03-design.md")
        self.record("test_plan", "requirements/REQ-test-flow/05-test-plan.md")
        self.run_tool("advance")
        self.approve("readiness_review", ("engineering", "testing"))
        self.run_tool("advance")
        blocked = self.run_tool("advance", expected=2)
        self.assertIn("artifact:prototype", blocked.stderr)

        self.record_prototype()
        self.run_tool("advance")
        rejected_feedback = self.write_artifact(
            "requirements/REQ-test-flow/rejected-feedback.md",
            "# User feedback\n\n"
            "## User decision\n\nThe user reviewed the preview and requested changes.\n\n"
            "## Feedback summary\n\nThe direction does not match the intended workflow.\n\n"
            "## Follow-up\n\nReopen product or design work before implementation.\n",
        )
        rejected = self.run_tool(
            "record-artifact",
            "--name",
            "user_feedback",
            "--path",
            str(rejected_feedback.relative_to(self.root)),
            expected=2,
        )
        self.assertIn("explicit user approval", rejected.stderr)

        self.record_user_feedback()
        self.run_tool("advance")
        self.assertIn("Stage: implementation", self.run_tool("status").stdout)

    def test_auto_triage_selects_micro_for_clear_low_risk_work(self) -> None:
        self.run_tool(
            "start",
            "--id",
            "REQ-test-flow",
            "--request",
            "Replace one confirmed button label without changing behavior.",
        )
        self.run_tool("advance")
        risk_evidence = self.write_artifact(
            "requirements/REQ-test-flow/00-scope-and-risk.md",
            "# Scope and risk assessment\n\n## Task baseline\n\nThe label-only scope is bounded.\n\n"
            "## Requirement gaps\n\nAll required areas were checked with no material gap.\n\n"
            "## Risk flags\n\nNo listed risk applies.\n\n"
            "## Workflow decision\n\nMicro is the selected low-risk mode.\n",
        )
        self.run_tool(
            "assess-risk",
            "--selected-mode",
            "micro",
            *(
                item
                for area in (
                    "actors_permissions",
                    "goals_scope",
                    "business_rules_states",
                    "data_api",
                    "failures_edges",
                    "compatibility_rollout",
                    "subjective_choices",
                    "acceptance_verification",
                )
                for item in ("--checked-area", area)
            ),
            "--scope",
            "Replace the one identified button label.",
            "--out-of-scope",
            "No API, data, layout, or behavior changes.",
            "--acceptance",
            "The new label renders in the existing button.",
            "--verification",
            "Run the focused UI test and inspect the rendered label.",
            "--evidence",
            str(risk_evidence.relative_to(self.root)),
            "--needs-clarification",
            "no",
            "--needs-confirmation",
            "no",
            "--needs-preview",
            "no",
        )
        state = json.loads(self.run_tool("status", "--json").stdout)
        self.assertEqual("micro", state["workflow"]["mode"])
        self.assertEqual(
            [
                "intake",
                "scope_check",
                "implementation",
                "verification",
                "delivery_confirmation",
                "completed",
            ],
            state["workflow"]["flow_stages"],
        )
        self.run_tool("advance")
        self.record("implementation", "requirements/REQ-test-flow/implementation.md")
        self.run_tool("advance")
        self.record("verification_report", "requirements/REQ-test-flow/verification.md")
        self.run_tool("advance")
        blocked = self.run_tool("advance", expected=2)
        self.assertIn("artifact:delivery_confirmation", blocked.stderr)
        self.confirm_delivery()
        completed = self.run_tool("advance")
        self.assertIn("delivery_confirmation -> completed", completed.stdout)

    def test_micro_delivery_change_request_rewinds_implementation(self) -> None:
        self.init("micro")
        self.run_tool("advance")
        self.assess_risk("micro")
        self.run_tool("advance")
        self.record("implementation", "requirements/REQ-test-flow/implementation.md")
        self.run_tool("advance")
        self.record("verification_report", "requirements/REQ-test-flow/verification.md")
        self.run_tool("advance")
        self.confirm_delivery("request_changes")
        state = json.loads(self.run_tool("status", "--json").stdout)
        self.assertEqual("implementation", state["workflow"]["current_stage"])
        self.assertEqual("superseded", state["artifacts"]["implementation"]["status"])
        self.assertEqual("superseded", state["artifacts"]["verification_report"]["status"])
        self.assertEqual(
            "request_changes",
            state["delivery_confirmation_records"][0]["verdict"],
        )

    def test_quick_triage_can_skip_unneeded_questions_and_preview(self) -> None:
        self.init("quick")
        self.run_tool("advance")
        self.assess_risk(
            "quick",
            risks=("external_dependency",),
            clarification="no",
            confirmation="no",
            preview="no",
        )
        self.run_tool("advance")
        state = json.loads(self.run_tool("status", "--json").stdout)
        self.assertEqual("design", state["workflow"]["current_stage"])
        self.assertNotIn("clarification", state["workflow"]["flow_stages"])
        self.assertNotIn("requirement_confirmation", state["workflow"]["flow_stages"])
        self.assertNotIn("prototype", state["workflow"]["flow_stages"])
        self.assertNotIn("user_feedback", state["workflow"]["flow_stages"])
        self.assertIn("delivery_confirmation", state["workflow"]["flow_stages"])

    def test_combined_quick_risks_raise_the_minimum_to_standard(self) -> None:
        self.init("auto")
        self.run_tool("advance")
        rejected = self.assess_risk(
            "quick",
            risks=("scope_expansion", "user_visible", "external_dependency"),
            clarification="no",
            confirmation="no",
            preview="yes",
            expected=2,
        )
        self.assertIn("below the safe minimum standard", rejected.stderr)

        verification_pair = self.assess_risk(
            "quick",
            risks=("weak_verification", "user_visible"),
            clarification="no",
            confirmation="no",
            preview="yes",
            expected=2,
        )
        self.assertIn("below the safe minimum standard", verification_pair.stderr)

    def test_risk_triage_rejects_mode_below_safe_minimum(self) -> None:
        self.init("auto")
        self.run_tool("advance")
        rejected = self.run_tool(
            "assess-risk",
            "--selected-mode",
            "quick",
            *(
                item
                for area in (
                    "actors_permissions",
                    "goals_scope",
                    "business_rules_states",
                    "data_api",
                    "failures_edges",
                    "compatibility_rollout",
                    "subjective_choices",
                    "acceptance_verification",
                )
                for item in ("--checked-area", area)
            ),
            "--risk",
            "api_change",
            "--scope",
            "Change an API response field.",
            "--out-of-scope",
            "No database migration.",
            "--acceptance",
            "All callers handle the new response contract.",
            "--verification",
            "Run contract and compatibility tests.",
            "--evidence",
            "missing-risk-evidence.md",
            expected=2,
        )
        self.assertIn("below the safe minimum standard", rejected.stderr)

    def test_risk_triage_requires_every_requirement_area_to_be_checked(self) -> None:
        self.init("auto")
        self.run_tool("advance")
        rejected = self.run_tool(
            "assess-risk",
            "--selected-mode",
            "micro",
            "--checked-area",
            "goals_scope",
            "--scope",
            "Change one confirmed label.",
            "--out-of-scope",
            "No behavior changes.",
            "--acceptance",
            "The label renders.",
            "--verification",
            "Inspect the label.",
            "--evidence",
            "missing-risk-evidence.md",
            expected=2,
        )
        self.assertIn("Requirement-gap analysis is incomplete", rejected.stderr)
        self.assertIn("actors_permissions", rejected.stderr)

    def test_new_risk_can_reopen_scope_check_and_escalate_mode(self) -> None:
        self.init("micro")
        self.run_tool("advance")
        self.assess_risk("micro")
        self.run_tool("advance")
        self.run_tool(
            "reopen",
            "--stage",
            "scope_check",
            "--reason",
            "Implementation discovery revealed an API contract change.",
        )
        self.assess_risk(
            "standard",
            risks=("api_change",),
            gaps=("Existing callers need a compatibility decision.",),
        )
        state = json.loads(self.run_tool("status", "--json").stdout)
        self.assertEqual("standard", state["workflow"]["mode"])
        self.assertIn("prd_review", state["workflow"]["flow_stages"])
        self.run_tool("advance")
        self.assertIn("Stage: clarification", self.run_tool("status").stdout)

    def test_discovered_risk_automatically_blocks_and_suggests_escalation(self) -> None:
        self.init("micro")
        self.run_tool("advance")
        self.assess_risk("micro")
        self.run_tool("advance")
        self.record("implementation", "requirements/REQ-test-flow/implementation.md")
        risk_evidence = self.write_artifact(
            "requirements/REQ-test-flow/risks/RSK-api-change.md",
            "# Discovered API risk\n\n## Evidence\n\nImplementation requires changing a public response field.\n\n"
            "## Impact\n\nExisting callers may be incompatible and require contract verification.\n\n"
            "## Recommendation\n\nEscalate before expanding implementation scope.\n",
        )
        reported = self.run_tool(
            "report-risk",
            "--source",
            "engineering",
            "--risk",
            "api_change",
            "--summary",
            "The implementation requires a public API contract change.",
            "--evidence",
            str(risk_evidence.relative_to(self.root)),
        )
        self.assertIn("Escalation required: micro -> at least standard", reported.stdout)
        blocked = self.run_tool("advance", expected=2)
        self.assertIn("escalation_required:RSK-001", blocked.stderr)
        overview = self.run_tool("overview")
        self.assertIn("Escalation required: micro -> standard (RSK-001)", overview.stdout)

        approval = self.write_artifact(
            "requirements/REQ-test-flow/approvals/RSK-001-escalation.md",
            "# Mode escalation approval\n\n## User decision\n\nAlice approved escalation to standard.\n\n"
            "## Reason\n\nThe API compatibility risk requires product, engineering, and testing review.\n\n"
            "## Scope\n\nRefresh the task baseline before continuing.\n",
        )
        too_low = self.run_tool(
            "escalate-mode",
            "--to-mode",
            "quick",
            "--approved-by",
            "Alice",
            "--reason",
            "Attempt a mode below the recommendation.",
            "--evidence",
            str(approval.relative_to(self.root)),
            expected=2,
        )
        self.assertIn("below recommended mode standard", too_low.stderr)
        original_risk_evidence = risk_evidence.read_text(encoding="utf-8")
        risk_evidence.write_text(
            original_risk_evidence + "\nChanged after the escalation request.\n",
            encoding="utf-8",
        )
        stale = self.run_tool(
            "escalate-mode",
            "--to-mode",
            "standard",
            "--approved-by",
            "Alice",
            "--reason",
            "Try to approve stale evidence.",
            "--evidence",
            str(approval.relative_to(self.root)),
            expected=2,
        )
        self.assertIn("Escalation risk evidence is stale: RSK-001", stale.stderr)
        risk_evidence.write_text(original_risk_evidence, encoding="utf-8")
        escalated = self.run_tool(
            "escalate-mode",
            "--to-mode",
            "standard",
            "--approved-by",
            "Alice",
            "--reason",
            "The user approved full API compatibility review.",
            "--evidence",
            str(approval.relative_to(self.root)),
        )
        self.assertIn("micro -> standard", escalated.stdout)
        state = json.loads(self.run_tool("status", "--json").stdout)
        self.assertEqual("scope_check", state["workflow"]["current_stage"])
        self.assertEqual("standard", state["workflow"]["mode"])
        self.assertEqual("accepted", state["escalation"]["status"])
        self.assertEqual("escalated", state["risk_reports"][0]["status"])
        self.assertEqual("superseded", state["artifacts"]["implementation"]["status"])
        blocked_scope = self.run_tool("advance", expected=2)
        self.assertIn("artifact:risk_assessment", blocked_scope.stderr)
        self.assess_risk(
            "standard",
            risks=("api_change",),
            gaps=("Existing API callers need a compatibility decision.",),
        )
        self.run_tool("advance")
        self.assertIn("Stage: clarification", self.run_tool("status").stdout)

    def test_resolved_risk_clears_pending_escalation_with_independent_evidence(self) -> None:
        self.init("micro")
        self.run_tool("advance")
        self.assess_risk("micro")
        self.run_tool("advance")
        risk_evidence = self.write_artifact(
            "requirements/REQ-test-flow/risks/RSK-api.md",
            "# API risk\n\n## Evidence\n\nA public API response may need to change.\n\n"
            "## Impact\n\nCompatibility requires a decision.\n\n## Recommendation\n\nEscalate for review.\n",
        )
        self.run_tool(
            "report-risk",
            "--source",
            "engineering",
            "--risk",
            "api_change",
            "--summary",
            "A public API change appeared necessary.",
            "--evidence",
            str(risk_evidence.relative_to(self.root)),
        )
        resolution = self.write_artifact(
            "requirements/REQ-test-flow/risks/RSK-001-resolution.md",
            "# RSK-001 resolved\n\n## Resolver\n\nengineering removed the API contract change.\n\n"
            "## Independent verification\n\ntesting verified that the existing API remains unchanged.\n\n"
            "## Result\n\nThe reported escalation trigger no longer applies.\n",
        )
        result = self.run_tool(
            "resolve-risk",
            "--risk-id",
            "RSK-001",
            "--resolution",
            "Implementation now preserves the public API contract.",
            "--resolved-by",
            "engineering",
            "--verified-by",
            "testing",
            "--evidence",
            str(resolution.relative_to(self.root)),
        )
        self.assertIn("No escalation blocker remains", result.stdout)
        state = json.loads(self.run_tool("status", "--json").stdout)
        self.assertEqual("resolved", state["risk_reports"][0]["status"])
        self.assertEqual("cleared", state["escalation"]["status"])

    def test_only_reporter_or_user_can_withdraw_a_risk(self) -> None:
        self.init("micro")
        self.run_tool("advance")
        self.assess_risk("micro")
        self.run_tool("advance")
        risk_evidence = self.write_artifact(
            "requirements/REQ-test-flow/risks/RSK-api.md",
            "# API risk\n\n## Evidence\n\nA public API response may need to change.\n\n"
            "## Impact\n\nCompatibility requires a decision.\n\n## Recommendation\n\nEscalate for review.\n",
        )
        self.run_tool(
            "report-risk",
            "--source",
            "engineering",
            "--risk",
            "api_change",
            "--summary",
            "A public API change appeared necessary.",
            "--evidence",
            str(risk_evidence.relative_to(self.root)),
        )
        withdrawal = self.write_artifact(
            "requirements/REQ-test-flow/risks/RSK-001-withdrawal.md",
            "# RSK-001 withdrawn\n\n## Reporter\n\nengineering withdrew the report after correcting the analysis.\n\n"
            "## Reason\n\nThe referenced interface is private and unchanged.\n\n"
            "## Result\n\nThe mistaken escalation trigger is removed.\n",
        )
        unauthorized = self.run_tool(
            "withdraw-risk",
            "--risk-id",
            "RSK-001",
            "--reason",
            "The report was mistaken.",
            "--withdrawn-by",
            "testing",
            "--evidence",
            str(withdrawal.relative_to(self.root)),
            expected=2,
        )
        self.assertIn("original reporter or the user", unauthorized.stderr)
        self.run_tool(
            "withdraw-risk",
            "--risk-id",
            "RSK-001",
            "--reason",
            "The report was based on a private interface.",
            "--withdrawn-by",
            "engineering",
            "--evidence",
            str(withdrawal.relative_to(self.root)),
        )
        state = json.loads(self.run_tool("status", "--json").stdout)
        self.assertEqual("withdrawn", state["risk_reports"][0]["status"])
        self.assertEqual("cleared", state["escalation"]["status"])

    def test_user_can_accept_only_waivable_escalation_risk_with_expiry(self) -> None:
        self.init("micro")
        self.run_tool("advance")
        self.assess_risk("micro")
        self.run_tool("advance")
        risk_evidence = self.write_artifact(
            "requirements/REQ-test-flow/risks/RSK-external.md",
            "# External dependency risk\n\n## Evidence\n\nA non-critical external service is required.\n\n"
            "## Impact\n\nVerification is slower but no sensitive data or production action is involved.\n\n"
            "## Recommendation\n\nUse quick mode or obtain explicit risk acceptance.\n",
        )
        self.run_tool(
            "report-risk",
            "--source",
            "engineering",
            "--risk",
            "external_dependency",
            "--summary",
            "A non-critical external dependency was discovered.",
            "--evidence",
            str(risk_evidence.relative_to(self.root)),
        )
        acceptance = self.write_artifact(
            "requirements/REQ-test-flow/risks/RSK-001-acceptance.md",
            "# RSK-001 accepted_risk\n\n## Authority\n\nAlice explicitly accepted_risk for the external dependency.\n\n"
            "## Rationale\n\nThe delivery is reversible and independently verifiable.\n\n"
            "## Expiry\n\nThis decision expires on 2099-12-31 and must then be reassessed.\n",
        )
        accepted = self.run_tool(
            "accept-escalation-risk",
            "--approved-by",
            "Alice",
            "--reason",
            "The reversible dependency risk is acceptable for this bounded change.",
            "--expires-on",
            "2099-12-31",
            "--evidence",
            str(acceptance.relative_to(self.root)),
        )
        self.assertIn("assurance is reduced", accepted.stdout)
        state = json.loads(self.run_tool("status", "--json").stdout)
        self.assertEqual("micro", state["workflow"]["mode"])
        self.assertEqual("accepted_risk", state["escalation"]["status"])
        self.assertEqual("reduced", state["escalation"]["assurance"])
        self.assertEqual("accepted_risk", state["risk_reports"][0]["status"])

    def test_strict_escalation_adds_human_readiness_and_acceptance_gates(self) -> None:
        self.init("quick")
        self.run_tool("advance")
        self.assess_risk(
            "quick",
            risks=("user_visible",),
            clarification="no",
            confirmation="no",
            preview="yes",
        )
        self.run_tool("advance")
        risk_evidence = self.write_artifact(
            "requirements/REQ-test-flow/risks/RSK-migration.md",
            "# Migration risk\n\n## Evidence\n\nThe change requires an irreversible production data migration.\n\n"
            "## Impact\n\nRollback and data validation need explicit authorization.\n\n"
            "## Recommendation\n\nEscalate to strict with human checkpoints.\n",
        )
        self.run_tool(
            "report-risk",
            "--source",
            "engineering",
            "--risk",
            "data_migration",
            "--risk",
            "irreversible",
            "--summary",
            "An irreversible production data migration is required.",
            "--evidence",
            str(risk_evidence.relative_to(self.root)),
        )
        forbidden_acceptance = self.write_artifact(
            "requirements/REQ-test-flow/approvals/RSK-001-acceptance.md",
            "# RSK-001 accepted_risk request\n\n## Authority\n\nAlice requested accepted_risk.\n\n"
            "## Rationale\n\nThe migration would otherwise remain in quick mode.\n\n"
            "## Expiry\n\nThe requested exception expires on 2099-12-31.\n",
        )
        rejected = self.run_tool(
            "accept-escalation-risk",
            "--approved-by",
            "Alice",
            "--reason",
            "Attempt to waive migration controls.",
            "--expires-on",
            "2099-12-31",
            "--evidence",
            str(forbidden_acceptance.relative_to(self.root)),
            expected=2,
        )
        self.assertIn("cannot be accepted without upgrading mode", rejected.stderr)
        approval = self.write_artifact(
            "requirements/REQ-test-flow/approvals/RSK-001-strict.md",
            "# Strict escalation approval\n\n## User decision\n\nAlice approved strict mode.\n\n"
            "## Reason\n\nMigration and rollback require human checkpoints.\n\n"
            "## Scope\n\nReassess the complete delivery plan.\n",
        )
        self.run_tool(
            "escalate-mode",
            "--to-mode",
            "strict",
            "--approved-by",
            "Alice",
            "--reason",
            "The migration requires strict governance.",
            "--evidence",
            str(approval.relative_to(self.root)),
        )
        state = json.loads(self.run_tool("status", "--json").stdout)
        self.assertEqual("strict", state["workflow"]["mode"])
        self.assertEqual(
            ["readiness_review", "acceptance"],
            state["human_approval_policy"]["required_gates"],
        )

    def test_change_request_feedback_is_preserved_and_rewinds_design(self) -> None:
        self.init("quick")
        self.complete_discovery()
        self.record("technical_design", "requirements/REQ-test-flow/03-design.md")
        self.record("test_plan", "requirements/REQ-test-flow/05-test-plan.md")
        self.run_tool("advance")
        self.approve("readiness_review", ("engineering", "testing"))
        self.run_tool("advance")
        self.record_prototype()
        self.run_tool("advance")
        evidence = self.write_artifact(
            "requirements/REQ-test-flow/07-user-change-request.md",
            "# User feedback\n\n## Decision\n\nThe user requested a different interaction direction.\n\n"
            "## Requested changes\n\nRevise the design before producing another preview.\n\n"
            "## Reason\n\nThe current direction does not match the intended workflow.\n",
        )
        result = self.run_tool(
            "record-user-feedback",
            "--verdict",
            "request_changes",
            "--summary",
            "Revise the interaction design.",
            "--affected-stage",
            "design",
            "--evidence",
            str(evidence.relative_to(self.root)),
        )
        self.assertIn("workflow rewound to design", result.stdout)
        state = json.loads(self.run_tool("status", "--json").stdout)
        self.assertEqual("design", state["workflow"]["current_stage"])
        self.assertEqual("request_changes", state["user_feedback_records"][-1]["verdict"])
        self.assertEqual("superseded", state["artifacts"]["prototype"]["status"])

    def test_trivial_document_and_non_required_reviewer_are_rejected(self) -> None:
        self.init("quick")
        self.complete_discovery()
        placeholder = self.write_artifact("requirements/REQ-test-flow/placeholder.md", "# Placeholder\n")
        rejected = self.run_tool(
            "record-artifact",
            "--name",
            "test_plan",
            "--path",
            str(placeholder.relative_to(self.root)),
            expected=2,
        )
        self.assertIn("too small to be substantive", rejected.stderr)

        self.record("technical_design", "requirements/REQ-test-flow/03-design.md")
        self.record("test_plan", "requirements/REQ-test-flow/05-test-plan.md")
        self.run_tool("advance")
        product_review = self.write_artifact(
            "requirements/REQ-test-flow/reviews/readiness-product.md",
            "# Product review\n\nThe design was checked against scope and acceptance criteria.\n\nVerdict: approve\n",
        )
        rejected = self.run_tool(
            "decide",
            "--gate",
            "readiness_review",
            "--role",
            "product",
            "--verdict",
            "approve",
            "--evidence",
            str(product_review.relative_to(self.root)),
            expected=2,
        )
        self.assertIn("is not a reviewer", rejected.stderr)

    def test_issue_resolution_requires_owner_and_substantive_evidence(self) -> None:
        self.init("quick")
        self.run_tool(
            "add-issue",
            "--source",
            "testing",
            "--owner",
            "product",
            "--severity",
            "blocker",
            "--summary",
            "Business retry policy is undefined.",
        )
        evidence = self.write_artifact(
            "requirements/REQ-test-flow/decision.md",
            "# ISSUE-001 resolution\n\nThe retry policy is now explicit and testable.\n\n"
            "## Decision\n\nRetry at most three times with bounded backoff.\n\n"
            "## Evidence\n\nProduct recorded the policy for downstream review.\n",
        )
        wrong_owner = self.run_tool(
            "resolve-issue",
            "--issue-id",
            "ISSUE-001",
            "--resolution",
            "Retry policy documented.",
            "--resolved-by",
            "testing",
            "--evidence",
            str(evidence.relative_to(self.root)),
            expected=2,
        )
        self.assertIn("Issue owner is product", wrong_owner.stderr)
        tiny = self.write_artifact("requirements/REQ-test-flow/tiny.md", "ok")
        weak_evidence = self.run_tool(
            "resolve-issue",
            "--issue-id",
            "ISSUE-001",
            "--resolution",
            "Retry policy documented.",
            "--resolved-by",
            "product",
            "--evidence",
            str(tiny.relative_to(self.root)),
            expected=2,
        )
        self.assertIn("too small to be substantive", weak_evidence.stderr)

    def test_artifact_paths_and_review_content_cannot_be_reused(self) -> None:
        self.init("quick")
        self.complete_discovery()
        design = self.write_artifact("requirements/REQ-test-flow/shared.md")
        self.run_tool(
            "record-artifact",
            "--name",
            "technical_design",
            "--path",
            str(design.relative_to(self.root)),
        )
        reused_artifact = self.run_tool(
            "record-artifact",
            "--name",
            "test_plan",
            "--path",
            str(design.relative_to(self.root)),
            expected=2,
        )
        self.assertIn("already used by technical_design", reused_artifact.stderr)

        self.record("test_plan", "requirements/REQ-test-flow/05-test-plan.md")
        self.run_tool("advance")
        shared_review_text = (
            "# readiness_review engineering testing\n\nBoth role labels are intentionally present.\n\n"
            "## Findings\n\nNo blockers remain after independent verification of the supplied evidence.\n\n"
            "## Verdict\n\napprove\n"
        )
        engineering = self.write_artifact(
            "requirements/REQ-test-flow/reviews/engineering.md", shared_review_text
        )
        testing = self.write_artifact(
            "requirements/REQ-test-flow/reviews/testing.md", shared_review_text
        )
        self.run_tool(
            "decide",
            "--gate",
            "readiness_review",
            "--role",
            "engineering",
            "--verdict",
            "approve",
            "--evidence",
            str(engineering.relative_to(self.root)),
        )
        reused_review = self.run_tool(
            "decide",
            "--gate",
            "readiness_review",
            "--role",
            "testing",
            "--verdict",
            "approve",
            "--evidence",
            str(testing.relative_to(self.root)),
            expected=2,
        )
        self.assertIn("content is already used", reused_review.stderr)

    def test_issue_resolution_cannot_reuse_gate_review(self) -> None:
        self.init("quick")
        self.complete_discovery()
        self.record("technical_design", "requirements/REQ-test-flow/03-design.md")
        self.record("test_plan", "requirements/REQ-test-flow/05-test-plan.md")
        self.run_tool("advance")
        review = self.write_artifact(
            "requirements/REQ-test-flow/reviews/engineering.md",
            "# readiness_review engineering\n\nISSUE-001 is mentioned for this adversarial test.\n\n"
            "## Findings\n\nThe design evidence was reviewed from the engineering perspective.\n\n"
            "## Verdict\n\napprove\n",
        )
        self.run_tool(
            "decide",
            "--gate",
            "readiness_review",
            "--role",
            "engineering",
            "--verdict",
            "approve",
            "--evidence",
            str(review.relative_to(self.root)),
        )
        self.run_tool(
            "add-issue",
            "--source",
            "testing",
            "--owner",
            "engineering",
            "--severity",
            "blocker",
            "--summary",
            "A technical blocker needs resolution.",
        )
        reused = self.run_tool(
            "resolve-issue",
            "--issue-id",
            "ISSUE-001",
            "--resolution",
            "Claimed fixed.",
            "--resolved-by",
            "engineering",
            "--evidence",
            str(review.relative_to(self.root)),
            expected=2,
        )
        self.assertIn("reuses a gate review", reused.stderr)

    def test_strict_mode_requires_explicit_database_and_release_artifacts(self) -> None:
        self.init("strict")
        self.complete_discovery()
        strict_state = json.loads(self.run_tool("status", "--json").stdout)
        self.assertEqual(
            ["readiness_review", "acceptance"],
            strict_state["human_approval_policy"]["required_gates"],
        )
        self.record(
            "prd",
            "requirements/REQ-test-flow/01-prd.md",
            text=(
                "# Product requirements\n\n"
                "## User outcome\n\nDeliver the confirmed real workflow behavior.\n\n"
                "## Acceptance criteria\n\nAC-001: The final user journey works with semantically correct data.\n\n"
                "## Exclusions\n\nNo core goal may be silently replaced by a mock.\n"
            ),
        )
        blocked = self.run_tool("advance", expected=2)
        self.assertIn("acceptance_criteria:prd_baseline", blocked.stderr)
        self.run_tool(
            "register-acceptance-criteria",
            "--criterion",
            "AC-001=The final user journey works with semantically correct data.",
        )
        self.run_tool("advance")
        self.approve("prd_review", ("product", "engineering", "testing"))
        self.run_tool("advance")
        self.record("technical_design", "requirements/REQ-test-flow/03-design.md")
        self.record("test_plan", "requirements/REQ-test-flow/05-test-plan.md")
        blocked = self.run_tool("advance", expected=2)
        self.assertIn("artifact:database_design", blocked.stderr)
        self.assertIn("artifact:release_plan", blocked.stderr)

        invalid_na = self.run_tool(
            "record-artifact",
            "--name",
            "test_plan",
            "--path",
            "docs/requirements/REQ-test-flow/05-test-plan.md",
            "--status",
            "not_applicable",
            "--notes",
            "Attempted bypass",
            expected=2,
        )
        self.assertIn("cannot be marked not_applicable", invalid_na.stderr)

        self.record(
            "database_design",
            "requirements/REQ-test-flow/04-database.md",
            "not_applicable",
            "No persistence changes are needed.",
        )
        self.record("release_plan", "requirements/REQ-test-flow/07-release.md")
        self.run_tool("advance")

    def test_strict_requirement_confirmation_cannot_skip_core_goals(self) -> None:
        self.init("strict")
        self.run_tool("advance")
        self.assess_risk()
        self.run_tool("advance")
        self.record_clarification()
        self.run_tool("advance")
        self.record(
            "requirement_confirmation",
            "requirements/REQ-test-flow/00-requirement-confirmation.md",
            text=(
                "# User requirement confirmation\n\n"
                "## User decision\n\nThe user confirmed and approved the clarified scope.\n\n"
                "## Confirmed scope\n\nProceed with the real requested outcome.\n\n"
                "## Open items\n\nNo unresolved decision remains.\n"
            ),
        )
        blocked = self.run_tool("advance", expected=2)
        self.assertIn("artifact:core_goals", blocked.stderr)
        self.assertIn("core_goals:user_confirmed_baseline", blocked.stderr)

    def test_quick_without_preview_requires_user_delivery_confirmation(self) -> None:
        self.init("quick")
        self.run_tool("advance")
        self.assess_risk("quick", clarification="no", confirmation="no", preview="no")
        self.run_tool("advance")
        self.record("technical_design", "requirements/REQ-test-flow/03-design.md")
        self.record("test_plan", "requirements/REQ-test-flow/05-test-plan.md")
        self.run_tool("advance")
        self.approve("readiness_review", ("engineering", "testing"))
        self.run_tool("advance")
        self.record("implementation", "requirements/REQ-test-flow/06-implementation.md")
        self.run_tool("advance")
        self.record("verification_report", "requirements/REQ-test-flow/08-verification.md")
        self.run_tool("advance")
        self.record("delivery_report", "requirements/REQ-test-flow/09-delivery.md")
        self.approve("acceptance", ("product", "engineering", "testing"))
        advanced = self.run_tool("advance")
        self.assertIn("acceptance -> delivery_confirmation", advanced.stdout)
        blocked = self.run_tool("advance", expected=2)
        self.assertIn("artifact:delivery_confirmation", blocked.stderr)

        self.confirm_delivery()
        completed = self.run_tool("advance")
        self.assertIn("delivery_confirmation -> completed", completed.stdout)
        self.assertFalse((self.root / ".ai-workflow" / "active.yaml").exists())

    def test_v7_quick_without_preview_gains_delivery_confirmation_on_migrate(self) -> None:
        self.init("quick")
        self.run_tool("advance")
        self.assess_risk("quick", clarification="no", confirmation="no", preview="no")
        state_path = self.root / ".ai-workflow" / "REQ-test-flow" / "state.yaml"
        state = json.loads(self.run_tool("status", "--json").stdout)
        self.assertIn("delivery_confirmation", state["workflow"]["flow_stages"])

        state["schema_version"] = 7
        state["workflow"]["flow_stages"] = [
            stage
            for stage in state["workflow"]["flow_stages"]
            if stage != "delivery_confirmation"
        ]
        state_path.write_text(json.dumps(state), encoding="utf-8")

        migrated = json.loads(self.run_tool("status", "--json").stdout)
        self.assertEqual(8, migrated["schema_version"])
        stages = migrated["workflow"]["flow_stages"]
        self.assertIn("delivery_confirmation", stages)
        self.assertEqual(stages.index("completed") - 1, stages.index("delivery_confirmation"))

    def test_strict_flow_reaches_completed_with_na_journey_checks(self) -> None:
        self.reach_strict_verification()
        journey_doc = self.write_artifact(
            "requirements/REQ-test-flow/08-final-journey.md",
            "# Final user journey validation\n\n"
            "launch: pass — the CLI workflow initializes and runs against the verified source.\n"
            "core_outcomes: pass — GOAL-001 delivers the real requested behavior.\n"
            "content_semantics: pass — command output is semantically correct for users.\n"
            "interactions: pass — advance and record commands respond as designed.\n"
            "external_links: not applicable — this deliverable exposes no external links.\n"
            "ui_quality: not applicable — this deliverable has no graphical user interface.\n"
            "release_hygiene: pass — the working tree is committed and clean.\n"
            "source_truth: pass — the verified source hash matches the working tree.\n",
        )
        recorded = self.run_tool(
            "record-user-journey",
            "--check",
            "launch=pass",
            "--check",
            "core_outcomes=pass",
            "--check",
            "content_semantics=pass",
            "--check",
            "interactions=pass",
            "--check",
            "external_links=not_applicable",
            "--check",
            "ui_quality=not_applicable",
            "--check",
            "release_hygiene=pass",
            "--check",
            "source_truth=pass",
            "--evidence",
            str(journey_doc.relative_to(self.root)),
        )
        self.assertIn("not_applicable", recorded.stdout)
        self.assertIn("external_links", recorded.stdout)

        advanced = self.run_tool("advance")
        self.assertIn("verification -> acceptance", advanced.stdout)
        self.record("delivery_report", "requirements/REQ-test-flow/09-delivery.md")
        self.approve("acceptance", ("product", "engineering", "testing"))
        human = self.write_artifact(
            "requirements/REQ-test-flow/approvals/acceptance-human.md",
            "# Human approval: acceptance\n\n"
            "Alice reviewed the final acceptance evidence and meeting record.\n\n"
            "## Authorization\n\nAlice explicitly records approve for this acceptance gate.\n",
        )
        self.run_tool(
            "record-human-approval",
            "--gate",
            "acceptance",
            "--approved-by",
            "Alice",
            "--evidence",
            str(human.relative_to(self.root)),
        )
        outcome_doc = self.write_artifact(
            "requirements/REQ-test-flow/09-outcome-goal001.md",
            "# Core outcome: GOAL-001\n\n"
            "GOAL-001: satisfied — the delivered workflow produces the real requested behavior.\n",
        )
        self.run_tool(
            "record-core-outcome",
            "--goal-id",
            "GOAL-001",
            "--verdict",
            "satisfied",
            "--evidence",
            str(outcome_doc.relative_to(self.root)),
        )
        completed = self.run_tool("advance")
        self.assertIn("acceptance -> completed", completed.stdout)
        self.assertFalse((self.root / ".ai-workflow" / "active.yaml").exists())

    def test_journey_not_applicable_requires_report_justification(self) -> None:
        self.reach_strict_verification()
        unjustified = self.write_artifact(
            "requirements/REQ-test-flow/08-journey-unjustified.md",
            "# Final user journey validation\n\n"
            "launch: pass — runs against the verified source.\n"
            "core_outcomes: pass — GOAL-001 delivers real behavior.\n"
            "content_semantics: pass — output is semantically correct.\n"
            "interactions: pass — commands respond as designed.\n"
            "external_links: pass — links were exercised.\n"
            "ui_quality: pass — screens were inspected.\n"
            "release_hygiene: pass — the working tree is clean.\n"
            "source_truth: pass — hashes match the working tree.\n",
        )
        rejected = self.run_tool(
            "record-user-journey",
            "--check",
            "launch=pass",
            "--check",
            "core_outcomes=pass",
            "--check",
            "content_semantics=pass",
            "--check",
            "interactions=pass",
            "--check",
            "external_links=pass",
            "--check",
            "ui_quality=not_applicable",
            "--check",
            "release_hygiene=pass",
            "--check",
            "source_truth=pass",
            "--evidence",
            str(unjustified.relative_to(self.root)),
            expected=2,
        )
        self.assertIn("must justify the not_applicable check", rejected.stderr)

        invalid = self.run_tool(
            "record-user-journey",
            "--check",
            "launch=pass",
            "--check",
            "core_outcomes=pass",
            "--check",
            "content_semantics=pass",
            "--check",
            "interactions=pass",
            "--check",
            "external_links=pass",
            "--check",
            "ui_quality=blocked",
            "--check",
            "release_hygiene=pass",
            "--check",
            "source_truth=pass",
            "--evidence",
            str(unjustified.relative_to(self.root)),
            expected=2,
        )
        self.assertIn("pass or not_applicable", invalid.stderr)

    def test_direct_state_edit_fails_integrity_check(self) -> None:
        self.init("quick")
        state_path = self.root / ".ai-workflow" / "REQ-test-flow" / "state.yaml"
        state = json.loads(self.run_tool("status", "--json").stdout)
        state["workflow"]["title"] = "Unsupported manual edit"
        state_path.write_text(json.dumps(state), encoding="utf-8")
        rejected = self.run_tool("status", expected=2)
        self.assertIn("integrity check failed", rejected.stderr)

    def test_source_fingerprint_detects_post_verification_code_change(self) -> None:
        sys.path.insert(0, str(SCRIPT.parent))
        try:
            import workflow as workflow_module
        finally:
            sys.path.pop(0)
        subprocess.run(["git", "init", "-q", str(self.root)], check=True)
        subprocess.run(
            ["git", "-C", str(self.root), "config", "user.email", "tests@example.com"],
            check=True,
        )
        subprocess.run(
            ["git", "-C", str(self.root), "config", "user.name", "Workflow Tests"],
            check=True,
        )
        source = self.root / "app.py"
        source.write_text("print('verified')\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(self.root), "add", "app.py"], check=True)
        subprocess.run(["git", "-C", str(self.root), "commit", "-qm", "verified source"], check=True)

        verified = workflow_module.current_source_fingerprint(self.root)
        self.assertEqual([], verified["dirty_paths"])
        source.write_text("print('changed after verification')\n", encoding="utf-8")
        changed = workflow_module.current_source_fingerprint(self.root)
        self.assertIn("app.py", changed["dirty_paths"])
        self.assertNotEqual(
            verified["source_tree_sha256"],
            changed["source_tree_sha256"],
        )

    def test_reopen_invalidates_downstream_gate_decisions(self) -> None:
        self.init()
        self.complete_discovery()
        self.record("prd", "requirements/REQ-test-flow/01-prd.md")
        self.run_tool("advance")
        self.approve("prd_review", ("product", "engineering", "testing"))
        self.run_tool("advance")
        self.run_tool("reopen", "--stage", "prd", "--reason", "Business scope changed")
        blocked = self.run_tool("advance", expected=2)
        self.assertIn("artifact:prd", blocked.stderr)
        self.record("prd", "requirements/REQ-test-flow/01-prd-v2.md")
        self.run_tool("advance")
        blocked = self.run_tool("advance", expected=2)
        self.assertIn("approval:prd_review:product", blocked.stderr)

    def test_quick_flow_can_complete_and_clears_active_pointer(self) -> None:
        self.init("quick")
        self.complete_discovery()
        self.record("technical_design", "requirements/REQ-test-flow/03-design.md")
        self.record("test_plan", "requirements/REQ-test-flow/05-test-plan.md")
        self.run_tool("advance")
        self.approve("readiness_review", ("engineering", "testing"))
        self.run_tool("advance")
        self.complete_preview()
        self.record("implementation", "requirements/REQ-test-flow/06-implementation.md")
        self.run_tool("advance")
        self.record("verification_report", "requirements/REQ-test-flow/08-verification.md")
        self.run_tool("advance")
        self.record("delivery_report", "requirements/REQ-test-flow/09-delivery.md")
        self.approve("acceptance", ("product", "engineering", "testing"))
        completed = self.run_tool("advance")
        self.assertIn("acceptance -> completed", completed.stdout)
        self.assertFalse((self.root / ".ai-workflow" / "active.yaml").exists())

    def test_state_revision_increments_and_schema_is_validated(self) -> None:
        self.init("quick")
        initial = json.loads(self.run_tool("status", "--json").stdout)
        self.assertEqual(8, initial["schema_version"])
        self.assertEqual(1, initial["revision"])

        self.run_tool("advance")
        advanced = json.loads(self.run_tool("status", "--json").stdout)
        self.assertEqual(2, advanced["revision"])
        self.assertFalse(
            list((self.root / ".ai-workflow").rglob("*.tmp")),
            "Atomic writes must not leave temporary files behind.",
        )

        state_path = self.root / ".ai-workflow" / "REQ-test-flow" / "state.yaml"
        advanced["schema_version"] = 999
        state_path.write_text(json.dumps(advanced), encoding="utf-8")
        rejected = self.run_tool("status", expected=2)
        self.assertIn("Unsupported schema_version", rejected.stderr)

    def test_schema_v3_workflow_migrates_without_inserting_new_active_stages(self) -> None:
        self.init("quick")
        state_path = self.root / ".ai-workflow" / "REQ-test-flow" / "state.yaml"
        state = json.loads(self.run_tool("status", "--json").stdout)
        state["schema_version"] = 3
        state["workflow"].pop("requested_mode", None)
        state["workflow"].pop("flow_stages", None)
        state.pop("risk_assessment", None)
        state.pop("user_feedback_records", None)
        state_path.write_text(json.dumps(state), encoding="utf-8")

        migrated = json.loads(self.run_tool("status", "--json").stdout)
        self.assertEqual(8, migrated["schema_version"])
        self.assertNotIn("scope_check", migrated["workflow"]["flow_stages"])
        self.run_tool("advance")
        self.assertIn("Stage: clarification", self.run_tool("status").stdout)

    def test_workflow_ids_and_active_pointer_cannot_escape_repository(self) -> None:
        self.init("quick")
        invalid_id = self.run_tool(
            "--id",
            "../../outside",
            "status",
            expected=2,
        )
        self.assertIn("Workflow ID must be", invalid_id.stderr)

        pointer = self.root / ".ai-workflow" / "active.yaml"
        pointer.write_text(
            json.dumps(
                {
                    "workflow_id": "REQ-test-flow",
                    "state_path": "../../outside.yaml",
                }
            ),
            encoding="utf-8",
        )
        escaped = self.run_tool("status", expected=2)
        self.assertIn("must be inside the repository root", escaped.stderr)

    def test_configured_human_approval_blocks_gate_and_binds_evidence(self) -> None:
        self.init(human_gates=("prd_review",))
        self.complete_discovery()
        self.record("prd", "requirements/REQ-test-flow/01-prd.md")
        self.run_tool("advance")
        roles = ("product", "engineering", "testing")
        self.approve("prd_review", roles)

        blocked = self.run_tool("advance", expected=2)
        self.assertIn("human_approval:prd_review", blocked.stderr)

        evidence = self.write_artifact(
            "requirements/REQ-test-flow/approvals/prd-review-human.md",
            "# Human approval: prd_review\n\nAlice reviewed the current role verdicts and meeting record.\n\n"
            "## Authorization\n\nAlice explicitly records approve for this PRD review.\n\n"
            "## Scope\n\nThe approval applies only to the current evidence snapshot.\n",
        )
        self.run_tool(
            "record-human-approval",
            "--gate",
            "prd_review",
            "--approved-by",
            "Alice",
            "--evidence",
            str(evidence.relative_to(self.root)),
        )
        self.run_tool("advance")
        self.assertIn("Stage: design", self.run_tool("status").stdout)

    def test_mutated_artifact_and_review_evidence_block_progress(self) -> None:
        self.init()
        self.complete_discovery()
        self.record("prd", "requirements/REQ-test-flow/01-prd.md")
        prd_path = self.root / "docs" / "requirements" / "REQ-test-flow" / "01-prd.md"
        prd_path.write_text(prd_path.read_text(encoding="utf-8") + "\nChanged after recording.\n", encoding="utf-8")
        stale_artifact = self.run_tool("advance", expected=2)
        self.assertIn("artifact:prd", stale_artifact.stderr)

        self.record("prd", "requirements/REQ-test-flow/01-prd-v2.md")
        self.run_tool("advance")
        roles = ("product", "engineering", "testing")
        self.approve("prd_review", roles)
        review_path = self.root / "docs" / "requirements" / "REQ-test-flow" / "reviews" / "prd_review-product.md"
        review_path.write_text(
            review_path.read_text(encoding="utf-8") + "\nChanged after review.\n",
            encoding="utf-8",
        )
        stale_review = self.run_tool("advance", expected=2)
        self.assertIn("approval:prd_review:product", stale_review.stderr)

    def test_changed_upstream_artifact_automatically_rewinds_workflow(self) -> None:
        self.init()
        self.complete_discovery()
        self.record("prd", "requirements/REQ-test-flow/01-prd.md")
        self.run_tool("advance")
        self.approve("prd_review", ("product", "engineering", "testing"))
        self.run_tool("advance")
        self.record("technical_design", "requirements/REQ-test-flow/03-design.md")
        self.record("test_plan", "requirements/REQ-test-flow/05-test-plan.md")
        self.run_tool("advance")
        self.record("prd", "requirements/REQ-test-flow/01-prd-v2.md")

        status = self.run_tool("status", "--json")
        state = json.loads(status.stdout)
        self.assertEqual("prd", state["workflow"]["current_stage"])
        self.assertEqual("superseded", state["artifacts"]["technical_design"]["status"])
        self.assertEqual("superseded", state["artifacts"]["test_plan"]["status"])
        self.assertIn("change_control_required", [event["event"] for event in state["history"]])

    def test_major_issue_requires_resolution_or_explicit_disposition_at_acceptance(self) -> None:
        self.init("quick")
        self.complete_discovery()
        self.record("technical_design", "requirements/REQ-test-flow/03-design.md")
        self.record("test_plan", "requirements/REQ-test-flow/05-test-plan.md")
        self.run_tool("advance")
        self.approve("readiness_review", ("engineering", "testing"))
        self.run_tool("advance")
        self.complete_preview()
        self.record("implementation", "requirements/REQ-test-flow/06-implementation.md")
        self.run_tool("advance")
        self.record("verification_report", "requirements/REQ-test-flow/08-verification.md")
        self.run_tool("advance")
        self.record("delivery_report", "requirements/REQ-test-flow/09-delivery.md")
        self.approve("acceptance", ("product", "engineering", "testing"))
        self.run_tool(
            "add-issue",
            "--source",
            "testing",
            "--owner",
            "product",
            "--severity",
            "major",
            "--summary",
            "Accessibility remediation is scheduled after this release.",
        )
        blocked = self.run_tool("advance", expected=2)
        self.assertIn("major:ISSUE-001", blocked.stderr)
        evidence = self.write_artifact(
            "requirements/REQ-test-flow/decisions/ISSUE-001-risk.md",
            "# ISSUE-001 accepted risk\n\n"
            "## Authorization\n\nAlice accepts this accepted_risk for the documented release.\n\n"
            "## Rationale\n\nThe remediation is scheduled and its remaining impact is understood.\n",
        )
        self.run_tool(
            "disposition-issue",
            "--issue-id",
            "ISSUE-001",
            "--disposition",
            "accepted_risk",
            "--approved-by",
            "Alice",
            "--rationale",
            "Remediation is explicitly accepted for this release.",
            "--evidence",
            str(evidence.relative_to(self.root)),
        )
        self.approve("acceptance", ("product", "engineering", "testing"))
        self.run_tool("advance")
        self.assertIn("Status: completed", self.run_tool("--id", "REQ-test-flow", "status").stdout)

    @unittest.skipIf(fcntl is None, "POSIX lock test")
    def test_concurrent_writer_is_rejected(self) -> None:
        lock_key = hashlib.sha256(str(self.root.resolve()).encode("utf-8")).hexdigest()
        lock_path = (
            Path(tempfile.gettempdir())
            / "multi-agent-role-work-locks"
            / f"{lock_key}.lock"
        )
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        with lock_path.open("a+") as lock:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            env = dict(os.environ)
            env["SDLC_LOCK_TIMEOUT"] = "0.1"
            rejected = self.run_tool(
                "init",
                "--id",
                "REQ-locked",
                "--title",
                "Locked workflow",
                "--request",
                "This update should be rejected while another writer holds the lock.",
                expected=2,
                env=env,
            )
            self.assertIn("Another workflow update is in progress", rejected.stderr)


if __name__ == "__main__":
    unittest.main()
