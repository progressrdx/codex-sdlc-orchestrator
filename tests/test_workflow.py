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
    ) -> None:
        path = self.write_artifact(filename)
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
        self.run_tool("advance")
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
        self.assertIn("Next action: Advance to PRD drafting.", started.stdout)

        overview = self.run_tool("overview", "--json")
        payload = json.loads(overview.stdout)
        self.assertEqual("standard", payload["mode"])
        self.assertEqual("intake", payload["stage"])
        self.assertTrue(payload["can_advance"])
        self.assertIn("original_request", payload["completed_artifacts"])

    def test_overview_reports_missing_evidence_and_issues(self) -> None:
        self.init()
        self.run_tool("advance")
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
        self.run_tool("advance")
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
        self.run_tool("advance")
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
        self.run_tool("advance")
        status = self.run_tool("status")
        self.assertIn("Stage: design", status.stdout)
        self.record("technical_design", "requirements/REQ-test-flow/03-design.md")
        self.record("test_plan", "requirements/REQ-test-flow/05-test-plan.md")
        self.run_tool("advance")
        self.approve("readiness_review", ("engineering", "testing"))
        self.run_tool("advance")
        self.assertIn("Stage: implementation", self.run_tool("status").stdout)

    def test_trivial_document_and_non_required_reviewer_are_rejected(self) -> None:
        self.init("quick")
        self.run_tool("advance")
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
        self.run_tool("advance")
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
        self.run_tool("advance")
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
        self.run_tool("advance")
        self.record("prd", "requirements/REQ-test-flow/01-prd.md")
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

    def test_reopen_invalidates_downstream_gate_decisions(self) -> None:
        self.init()
        self.run_tool("advance")
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
        completed = self.run_tool("advance")
        self.assertIn("acceptance -> completed", completed.stdout)
        self.assertFalse((self.root / ".ai-workflow" / "active.yaml").exists())

    def test_state_revision_increments_and_schema_is_validated(self) -> None:
        self.init("quick")
        initial = json.loads(self.run_tool("status", "--json").stdout)
        self.assertEqual(2, initial["schema_version"])
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
        self.run_tool("advance")
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
        self.run_tool("advance")
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
        self.run_tool("advance")
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
