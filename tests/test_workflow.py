from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

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
    ARTIFACT_ROLES = {
        "clarification_questions": "product",
        "prd": "product",
        "technical_design": "engineering",
        "database_design": "engineering",
        "test_plan": "testing",
        "test_cases": "testing",
        "release_plan": "engineering",
        "prototype": "engineering",
        "implementation": "engineering",
        "verification_report": "testing",
        "journey_report": "testing",
        "traceability": "testing",
    }

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()
        self.meeting_counter = 0
        self.risk_assessment_counter = 0
        self.work_counter = 0

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
        scope: str = "Deliver the explicitly bounded workflow behavior.",
        out_of_scope: str = "No unrelated platform or deployment changes.",
        acceptance: str = "The requested behavior is observable and satisfies the recorded criteria.",
        verification: str = "Run focused automated checks and independent behavior verification.",
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
            scope,
            "--out-of-scope",
            out_of_scope,
            "--acceptance",
            acceptance,
            "--verification",
            verification,
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

    def initialize_git_source(self) -> Path:
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
        return source

    def workflow_module(self):
        sys.path.insert(0, str(SCRIPT.parent))
        try:
            import workflow as workflow_module
        finally:
            sys.path.pop(0)
        return workflow_module

    def record(
        self,
        name: str,
        filename: str,
        status: str = "ready",
        notes: str | None = None,
        text: str | None = None,
    ) -> None:
        path = self.write_artifact(filename, text) if text is not None else self.write_artifact(filename)
        work_item_id = None
        role = self.ARTIFACT_ROLES.get(name)
        if role and status in {"ready", "not_applicable"}:
            work_item_id, _ = self.complete_role_work(
                role,
                {name: path},
            )
        self.run_tool(
            "record-artifact",
            "--name",
            name,
            "--path",
            str(path.relative_to(self.root)),
            "--status",
            status,
            *(["--work-item-id", work_item_id] if work_item_id else []),
            *(["--notes", notes] if notes else []),
            *(["--test-command", "true"] if name == "verification_report" and status == "ready" else []),
        )

    def complete_role_work(
        self,
        role: str,
        outputs: dict[str, Path],
        *,
        actor_ref: str | None = None,
    ) -> tuple[str, str]:
        self.work_counter += 1
        work_item_id = f"{role}-work-{self.work_counter:03d}"
        actor = actor_ref or f"{role}-agent-{self.work_counter:03d}"
        state = json.loads(self.run_tool("status", "--json").stdout)
        stage = state["workflow"]["current_stage"]
        budget = {"micro": 2, "quick": 3, "standard": 3, "strict": 3}[
            state["workflow"]["mode"]
        ]
        used = sum(
            1
            for item in state.get("work_items", {}).values()
            if item.get("stage") == stage and item.get("status") != "superseded"
        )
        override_args: list[str] = []
        if used >= budget:
            override = self.write_artifact(
                f"requirements/REQ-test-flow/work-overrides/{work_item_id}.md",
                "# Role handoff override\n\nA further independent attempt is required by the current test baseline.\n",
            )
            override_args = ["--override-evidence", str(override.relative_to(self.root))]
        self.run_tool(
            "begin-work",
            "--work-item-id",
            work_item_id,
            "--role",
            role,
            "--actor-ref",
            actor,
            "--deadline-at",
            "2099-01-01T00:00:00Z",
            "--lease-seconds",
            "3600",
            *override_args,
        )
        self.run_tool(
            "complete-work",
            "--work-item-id",
            work_item_id,
            *(
                item
                for name, path in outputs.items()
                for item in ("--output", f"{name}={path.relative_to(self.root)}")
            ),
        )
        return work_item_id, actor

    def record_implementation_while_editing_source(self, source: Path, content: str) -> None:
        """Model the real implementation order: claim the work before editing source."""
        self.work_counter += 1
        work_item_id = f"engineering-work-{self.work_counter:03d}"
        self.run_tool(
            "begin-work",
            "--work-item-id",
            work_item_id,
            "--role",
            "engineering",
            "--actor-ref",
            f"engineering-agent-{self.work_counter:03d}",
            "--deadline-at",
            "2099-01-01T00:00:00Z",
            "--lease-seconds",
            "3600",
        )
        source.write_text(content, encoding="utf-8")
        artifact = self.write_artifact("requirements/REQ-test-flow/implementation.md")
        self.run_tool(
            "complete-work",
            "--work-item-id",
            work_item_id,
            "--output",
            f"implementation={artifact.relative_to(self.root)}",
        )
        self.run_tool(
            "record-artifact",
            "--name",
            "implementation",
            "--path",
            str(artifact.relative_to(self.root)),
            "--status",
            "ready",
            "--work-item-id",
            work_item_id,
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
        evidence = self.write_artifact(
            "requirements/REQ-test-flow/00-requirement-confirmation.md",
            (
                "confirmation_verdict: approve\n\n"
                "# User requirement confirmation\n\n"
                "## User decision\n\nThe user confirmed and approved the clarified scope for this workflow.\n\n"
                "## Confirmed scope\n\nProduct may proceed to PRD or design using the documented clarification.\n\n"
                "## Open items\n\nNo unresolved business decision blocks the next stage.\n"
            ),
        )
        self.run_tool(
            "record-requirement-confirmation",
            "--verdict", "approve",
            "--summary", "The user approved the clarified requirement baseline.",
            "--evidence", str(evidence.relative_to(self.root)),
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
                "feedback_verdict: approve\n\n"
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
                f"delivery_verdict: {verdict}\n\n"
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
                f"review_verdict: approve\n\n# Review: {gate.replace('_', ' ')} / {role}\n\nInputs were checked against the gate criteria. "
                "No blocking findings remain.\n\n## Verdict\n\napprove\n",
            )
            work_item_id, actor_ref = self.complete_role_work(
                role,
                {f"review:{gate}:{role}": evidence},
                actor_ref=f"{role}-agent-{self.work_counter + 1:03d}",
            )
            self.run_tool(
                "decide",
                "--gate",
                gate,
                "--role",
                role,
                "--actor-ref",
                actor_ref,
                "--work-item-id",
                work_item_id,
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

    def test_start_accepts_plain_request_and_prints_user_project_view(self) -> None:
        started = self.run_tool(
            "start",
            "--request",
            "实现会员积分过期功能。需要产品、研发和测试评审。",
        )
        self.assertIn("Project:", started.stdout)
        self.assertIn("Project Compass\n项目守航已开启", started.stdout)
        self.assertIn("目标：", started.stdout)
        self.assertIn("项目方向：[正在确认方向]", started.stdout)
        self.assertIn("目标保护：", started.stdout)
        self.assertIn("当前：正在理解你的目标和项目背景", started.stdout)
        self.assertIn("需要你决定：暂无", started.stdout)
        self.assertNotIn("Mode:", started.stdout)
        self.assertNotIn("Stage:", started.stdout)
        self.assertNotIn("Can advance:", started.stdout)
        self.assertNotIn(" mode", started.stdout)
        self.assertNotIn("State:", started.stdout)

        overview = self.run_tool("overview", "--json")
        payload = json.loads(overview.stdout)
        self.assertEqual("auto", payload["mode"])
        self.assertEqual("intake", payload["stage"])
        self.assertTrue(payload["can_advance"])
        self.assertIn("original_request", payload["completed_artifacts"])

        project_payload = json.loads(self.run_tool("project", "--json").stdout)
        self.assertEqual(
            "initialized_without_baseline",
            project_payload["version_protection"]["status"],
        )
        state = self.workflow_module().load_state(self.root, None)[1]
        self.assertEqual("zh-CN", state["user_preferences"]["language"])
        self.assertIsNone(project_payload["stage_summary"]["decision"])
        self.assertIn("是否需要你操作：否", started.stdout)
        self.assertEqual(
            "true",
            subprocess.run(
                ["git", "-C", str(self.root), "rev-parse", "--is-inside-work-tree"],
                text=True, capture_output=True, check=True,
            ).stdout.strip(),
        )
        self.assertNotEqual(
            0,
            subprocess.run(
                ["git", "-C", str(self.root), "rev-parse", "--verify", "HEAD"],
                text=True, capture_output=True, check=False,
            ).returncode,
            "starting Project Compass must not create an unsolicited baseline commit",
        )

    def test_start_preserves_existing_git_branch_remote_and_uncommitted_work(self) -> None:
        source = self.initialize_git_source()
        subprocess.run(["git", "-C", str(self.root), "checkout", "-qb", "user-work"], check=True)
        subprocess.run(
            ["git", "-C", str(self.root), "remote", "add", "origin", "https://example.invalid/user/repo.git"],
            check=True,
        )
        source.write_text("print('user work in progress')\n", encoding="utf-8")
        self.run_tool("start", "--request", "继续完成已有项目，但不要改动版本管理配置。")
        branch = subprocess.run(
            ["git", "-C", str(self.root), "branch", "--show-current"],
            text=True, capture_output=True, check=True,
        ).stdout.strip()
        remote = subprocess.run(
            ["git", "-C", str(self.root), "remote", "get-url", "origin"],
            text=True, capture_output=True, check=True,
        ).stdout.strip()
        status = subprocess.run(
            ["git", "-C", str(self.root), "status", "--short", "app.py"],
            text=True, capture_output=True, check=True,
        ).stdout
        self.assertEqual("user-work", branch)
        self.assertEqual("https://example.invalid/user/repo.git", remote)
        self.assertIn(" M app.py", status)

    def test_chinese_artifacts_and_review_preflight_do_not_require_english_headings(self) -> None:
        self.init()
        self.run_tool("advance")
        self.assess_risk()
        self.run_tool("advance")
        self.record(
            "clarification_questions",
            "requirements/REQ-test-flow/00-clarification-zh.md",
            text=(
                "# 需求澄清\n\n## 需要确认的问题\n\n用户希望支持哪些角色和权限？\n\n"
                "## 缺失信息\n\n失败状态和边界情况仍是缺口。\n\n"
                "## 临时假设与验收标准\n\n假设先确认范围；验收结果必须可以实际观察。\n"
            ),
        )
        self.run_tool("advance")
        confirmation = self.write_artifact(
            "requirements/REQ-test-flow/00-confirmation-zh.md",
            (
                "确认结论: approve\n\n"
                "# 需求确认\n\n## 用户决定\n\n用户已经确认并同意上述目标和范围。\n\n"
                "## 已确认范围\n\n可以继续准备产品方案，并按记录的完成标准进行后续核验。\n\n"
                "## 未决事项\n\n当前没有阻塞项，若目标发生变化仍需先向用户说明。\n"
            ),
        )
        self.run_tool(
            "record-requirement-confirmation",
            "--verdict", "approve",
            "--summary", "用户已确认目标和范围。",
            "--evidence", str(confirmation.relative_to(self.root)),
        )
        review = self.write_artifact(
            "requirements/REQ-test-flow/reviews/readiness-testing-zh.md",
            "评审结论: approve\n\n# 开发前检查\n\n## 测试复核\n\n已经按用户实际启动方式核对方案和测试计划。\n\n"
            "## 结论\n\n通过。当前没有阻塞开发的质量问题，后续仍需验证核心用户结果和真实数据来源。\n",
        )
        checked = self.run_tool(
            "check-review-evidence", "--gate", "readiness_review", "--role", "testing",
            "--verdict", "approve", "--path", str(review.relative_to(self.root)),
        )
        self.assertIn("Review evidence is ready", checked.stdout)
        weak_review = self.write_artifact(
            "requirements/REQ-test-flow/reviews/readiness-testing-weak.md",
            "# 开发前检查\n\n## 测试复核\n\n材料已经阅读，但这里没有记录最终决定。\n\n"
            "## 后续\n\n等待补充正式决定后再继续处理；目前只能说明材料已阅读，不能据此推进实现或交付。\n",
        )
        rejected = self.run_tool(
            "check-review-evidence", "--gate", "readiness_review", "--role", "testing",
            "--verdict", "approve", "--path", str(weak_review.relative_to(self.root)), expected=2,
        )
        self.assertIn("review_verdict: approve", rejected.stderr)

        negative_review = self.write_artifact(
            "requirements/REQ-test-flow/reviews/readiness-testing-negative.md",
            "评审结论: reject\n\n# 开发前检查\n\n## 测试复核\n\n"
            "测试已完成，但关键路径仍然失败，当前证据不足以支持进入实现或交付阶段。\n\n"
            "## 结论\n\n不通过，必须先修复核心用户路径并重新执行完整评审。\n",
        )
        mismatch = self.run_tool(
            "check-review-evidence", "--gate", "readiness_review", "--role", "testing",
            "--verdict", "approve", "--path", str(negative_review.relative_to(self.root)),
            expected=2,
        )
        self.assertIn("review_verdict: approve", mismatch.stderr)

    def test_requirement_confirmation_requires_an_explicit_matching_verdict(self) -> None:
        self.init()
        self.run_tool("advance")
        self.assess_risk()
        self.run_tool("advance")
        self.record_clarification()
        self.run_tool("advance")
        evidence = self.write_artifact(
            "requirements/REQ-test-flow/00-rejected-confirmation.md",
            "confirmation_verdict: reject\n\n# 需求确认\n\n"
            "## 用户决定\n\n用户不同意当前范围，要求补充异常处理和验收结果。\n\n"
            "## 后续处理\n\n回到澄清阶段，完成补充后再请用户确认。\n\n"
            "## 影响\n\n当前方案不得进入设计或开发。\n",
        )
        mismatch = self.run_tool(
            "record-requirement-confirmation", "--verdict", "approve",
            "--summary", "错误地尝试把拒绝记为批准。",
            "--evidence", str(evidence.relative_to(self.root)), expected=2,
        )
        self.assertIn("confirmation_verdict: approve", mismatch.stderr)
        self.run_tool(
            "record-requirement-confirmation", "--verdict", "reject",
            "--summary", "用户拒绝当前范围并要求补充澄清。",
            "--evidence", str(evidence.relative_to(self.root)),
        )
        state = json.loads(self.run_tool("status", "--json").stdout)
        self.assertEqual("clarification", state["workflow"]["current_stage"])
        self.assertNotIn("requirement_confirmation", state["artifacts"])

    def test_project_view_uses_plain_language_and_keeps_overview_technical(self) -> None:
        self.init()
        self.run_tool("advance")
        self.assess_risk(
            scope="Members keep earned points until the configured expiration date.",
            out_of_scope="No changes to earning rules or membership tiers.",
            acceptance="Expired points are excluded from the usable balance.",
        )

        project = self.run_tool("project")
        self.assertTrue(project.stdout.startswith("Project Compass\n项目守航已开启\n"))
        self.assertIn(
            "目标：Members keep earned points until the configured expiration date.",
            project.stdout,
        )
        self.assertIn("暂不包含：No changes to earning rules", project.stdout)
        self.assertIn("完成标准：Expired points are excluded", project.stdout)
        self.assertIn("当前：正在梳理范围、验收结果和潜在风险", project.stdout)
        self.assertIn("项目方向：[与目标一致]", project.stdout)
        self.assertIn("质量：最终质量检查尚未完成", project.stdout)
        self.assertIn("版本保护：Git 已初始化，但尚无基线提交", project.stdout)
        self.assertIn("是否需要你操作：否", project.stdout)
        self.assertIn("需要你决定：暂无", project.stdout)
        for internal_term in (
            "Mode:",
            "Stage:",
            "Can advance:",
            "Meeting notes:",
            "Cost policy:",
            "Human approval gates:",
        ):
            self.assertNotIn(internal_term, project.stdout)

        project_json = json.loads(self.run_tool("project", "--json").stdout)
        self.assertEqual(
            "Members keep earned points until the configured expiration date.",
            project_json["goal"],
        )
        self.assertNotIn("mode", project_json)
        self.assertNotIn("stage", project_json)
        self.assertEqual("on_track", project_json["alignment"]["status"])
        self.assertEqual(
            "initialized_without_baseline",
            project_json["version_protection"]["status"],
        )
        self.assertEqual("正在梳理范围、验收结果和潜在风险", project_json["stage_summary"]["current"])
        self.assertEqual("已定义，等待开发", project_json["core_results"][0]["status"])
        self.assertEqual([], project_json["available_actions"])

        overview = self.run_tool("overview")
        self.assertIn("Mode: standard", overview.stdout)
        self.assertIn("Stage: scope_check", overview.stdout)

    def test_project_view_surfaces_only_the_user_decision(self) -> None:
        self.init()
        self.run_tool("advance")
        self.assess_risk()
        self.run_tool("advance")
        self.record_clarification()
        self.run_tool("advance")

        project = self.run_tool("project")
        self.assertIn("当前：已整理目标和范围，准备与你确认", project.stdout)
        self.assertIn("项目方向：[等待你的方向确认]", project.stdout)
        self.assertIn("需要你决定：", project.stdout)
        self.assertIn("请确认我理解的目标、范围和完成标准是否正确。", project.stdout)
        self.assertIn("下一步：等待你的决定后继续推进。", project.stdout)
        self.assertNotIn("requirement_confirmation", project.stdout)
        self.assertNotIn("artifact:", project.stdout)
        payload = json.loads(self.run_tool("project", "--json").stdout)
        self.assertEqual("confirmation_needed", payload["alignment"]["status"])

    def test_project_view_shows_result_status_actions_and_resolved_problems(self) -> None:
        self.init("micro")
        self.run_tool("advance")
        self.assess_risk("micro")
        self.run_tool("advance")
        self.record("implementation", "requirements/REQ-test-flow/implementation.md")
        self.run_tool(
            "add-issue",
            "--source",
            "testing",
            "--owner",
            "engineering",
            "--severity",
            "minor",
            "--summary",
            "Button copy used the old label in one state.",
        )
        resolution = self.write_artifact(
            "requirements/REQ-test-flow/issues/ISSUE-001-resolution.md",
            "# ISSUE-001 resolution\n\nThe old button label was replaced in the remaining state.\n\n"
            "## Verification\n\nThe focused rendering check now shows the new label consistently.\n",
        )
        self.run_tool(
            "resolve-issue",
            "--issue-id",
            "ISSUE-001",
            "--resolved-by",
            "engineering",
            "--resolution",
            "Updated the remaining button state and reran the focused check.",
            "--evidence",
            str(resolution.relative_to(self.root)),
        )

        project = self.run_tool("project")
        self.assertIn("核心结果：", project.stdout)
        self.assertIn("[等待验证]", project.stdout)
        self.assertIn("可查看成果：", project.stdout)
        self.assertIn("查看实现结果：docs/requirements/REQ-test-flow/implementation.md", project.stdout)
        self.assertIn("已解决问题：", project.stdout)
        self.assertIn("Button copy used the old label", project.stdout)

        payload = json.loads(self.run_tool("project", "--json").stdout)
        self.assertEqual("on_track", payload["alignment"]["status"])
        self.assertEqual("等待验证", payload["core_results"][0]["status"])
        self.assertEqual("implementation", payload["available_actions"][0]["kind"])
        self.assertEqual(1, len(payload["resolved_issues"]))

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
            "--name", "requirement_confirmation",
            "--path", str(unconfirmed.relative_to(self.root)), expected=2,
        )
        self.assertIn("record-requirement-confirmation", rejected.stderr)

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
        preview_state = json.loads(self.run_tool("project", "--json").stdout)
        self.assertEqual("方向预览中", preview_state["alignment"]["label"])
        self.assertIn("尚不能证明核心功能已经实现", preview_state["alignment"]["summary"])
        self.record_prototype()
        preview_ready = json.loads(self.run_tool("project", "--json").stdout)
        self.assertEqual("preview", preview_ready["available_actions"][0]["kind"])
        self.assertIn("不代表核心功能已完成", preview_ready["available_actions"][0]["label"])
        self.run_tool("advance")
        self.record_user_feedback()
        self.run_tool("advance")
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
        self.assertIn("must be recorded through record-user-feedback", rejected.stderr)

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
        generic_confirmation = self.write_artifact(
            "requirements/REQ-test-flow/generic-delivery-confirmation.md"
        )
        rejected = self.run_tool(
            "record-artifact",
            "--name",
            "delivery_confirmation",
            "--path",
            str(generic_confirmation.relative_to(self.root)),
            expected=2,
        )
        self.assertIn(
            "must be recorded through record-delivery-confirmation",
            rejected.stderr,
        )
        state = json.loads(self.run_tool("status", "--json").stdout)
        self.assertEqual([], state["delivery_confirmation_records"])
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

    def test_non_strict_source_change_invalidates_verification_before_delivery(self) -> None:
        self.init("micro")
        self.run_tool("advance")
        self.assess_risk("micro")
        self.run_tool("advance")
        source = self.root / "app.py"
        self.record_implementation_while_editing_source(source, "print('first version')\n")
        self.run_tool("advance")
        self.record("verification_report", "requirements/REQ-test-flow/verification.md")
        self.run_tool("advance")

        verified_state = json.loads(self.run_tool("status", "--json").stdout)
        test_log = self.root / verified_state["verification_snapshot"]["test_execution"]["log_path"]
        original_log = test_log.read_text(encoding="utf-8")
        test_log.write_text(original_log + "\ntampered\n", encoding="utf-8")
        stale_log = self.run_tool("advance", expected=2)
        self.assertIn("verification_snapshot:test_execution", stale_log.stderr)
        test_log.write_text(original_log, encoding="utf-8")

        source.write_text("print('changed after testing')\n", encoding="utf-8")
        blocked = self.run_tool("advance", expected=2)
        self.assertTrue(
            "Project continuity blocked" in blocked.stderr
            or "verification_snapshot:source_changed_after_verification" in blocked.stderr
        )

        self.confirm_delivery("request_changes")
        self.record("implementation", "requirements/REQ-test-flow/implementation-v2.md")
        self.run_tool("advance")
        self.record("verification_report", "requirements/REQ-test-flow/verification.md")
        refreshed = json.loads(self.run_tool("status", "--json").stdout)
        self.assertEqual(
            refreshed["artifacts"]["verification_report"]["evidence_sha256"],
            refreshed["verification_snapshot"]["verification_evidence_sha256"],
        )
        self.assertEqual("pass", refreshed["verification_snapshot"]["test_execution"]["status"])
        self.assertTrue(
            (self.root / refreshed["verification_snapshot"]["test_execution"]["log_path"]).is_file()
        )

    def test_failed_verification_command_stops_without_recording_report(self) -> None:
        self.init("micro")
        self.run_tool("advance")
        self.assess_risk("micro")
        self.run_tool("advance")
        self.record("implementation", "requirements/REQ-test-flow/implementation.md")
        self.run_tool("advance")
        report = self.write_artifact("requirements/REQ-test-flow/verification-failed.md")
        failed = self.run_tool(
            "record-artifact",
            "--name",
            "verification_report",
            "--path",
            str(report.relative_to(self.root)),
            "--test-command",
            "echo TOKEN_HEAVY_FAILURE_DETAIL; exit 7",
            expected=2,
        )
        self.assertIn("test exited with 7", failed.stderr)
        self.assertNotIn("TOKEN_HEAVY_FAILURE_DETAIL", failed.stderr)
        state = json.loads(self.run_tool("status", "--json").stdout)
        self.assertNotIn("verification_report", state["artifacts"])
        self.assertEqual(1, len(list((self.root / ".ai-workflow/REQ-test-flow/test-runs").glob("*.log"))))

    def test_verification_command_cannot_silently_change_product_source(self) -> None:
        self.init("micro")
        self.run_tool("advance")
        self.assess_risk("micro")
        self.run_tool("advance")
        source = self.root / "app.py"
        self.record_implementation_while_editing_source(source, "original\n")
        self.run_tool("advance")
        report = self.write_artifact("requirements/REQ-test-flow/verification-mutating.md")
        rejected = self.run_tool(
            "record-artifact",
            "--name",
            "verification_report",
            "--path",
            str(report.relative_to(self.root)),
            "--test-command",
            "echo changed > app.py",
            expected=2,
        )
        self.assertIn("test exited with", rejected.stderr)
        self.assertEqual("original\n", source.read_text(encoding="utf-8"))
        state = json.loads(self.run_tool("status", "--json").stdout)
        self.assertNotIn("verification_report", state["artifacts"])

    def test_scoped_verification_cannot_rewrite_files_outside_scope(self) -> None:
        workflow_module = self.workflow_module()
        self.initialize_git_source()
        helper = self.root / "test_helper.py"
        helper.write_text("ORIGINAL = True\n", encoding="utf-8")
        subprocess.run(
            ["git", "-C", str(self.root), "add", "test_helper.py"],
            check=True,
        )
        subprocess.run(
            ["git", "-C", str(self.root), "commit", "-qm", "test helper"],
            check=True,
        )
        state = {
            "workflow": {"id": "REQ-test-flow", "mode": "strict"},
            "verification_snapshot": {},
            "source_revision": {},
        }
        with self.assertRaises(workflow_module.WorkflowError) as raised:
            workflow_module.execute_verification_commands(
                self.root,
                state,
                (
                    ("build", "echo 'TAMPERED = True' > test_helper.py"),
                    ("test", "grep -q TAMPERED test_helper.py"),
                ),
                scope_paths=("app.py",),
            )
        self.assertIn("build exited with", str(raised.exception))
        self.assertEqual("ORIGINAL = True\n", helper.read_text(encoding="utf-8"))

    def test_failed_mutating_verification_leaves_original_workspace_unchanged(self) -> None:
        self.init("micro")
        self.run_tool("advance")
        self.assess_risk("micro")
        self.run_tool("advance")
        source = self.root / "app.py"
        self.record_implementation_while_editing_source(source, "original\n")
        self.run_tool("advance")
        report = self.write_artifact("requirements/REQ-test-flow/verification-mutating-fail.md")
        rejected = self.run_tool(
            "record-artifact",
            "--name",
            "verification_report",
            "--path",
            str(report.relative_to(self.root)),
            "--test-command",
            "echo changed > app.py; exit 7",
            expected=2,
        )
        self.assertIn("test exited with 7", rejected.stderr)
        self.assertEqual("original\n", source.read_text(encoding="utf-8"))

    def test_timed_out_verification_terminates_background_processes(self) -> None:
        self.init("micro")
        self.run_tool("advance")
        self.assess_risk("micro")
        self.run_tool("advance")
        self.record("implementation", "requirements/REQ-test-flow/implementation.md")
        self.run_tool("advance")
        report = self.write_artifact("requirements/REQ-test-flow/verification-timeout.md")
        marker = self.root / "background-process-survived.txt"
        timed_out = self.run_tool(
            "record-artifact",
            "--name",
            "verification_report",
            "--path",
            str(report.relative_to(self.root)),
            "--test-command",
            f"(sleep 2; echo survived > '{marker}') & wait",
            "--command-timeout",
            "1",
            expected=2,
        )
        self.assertIn("exited with 124", timed_out.stderr)
        time.sleep(2)
        self.assertFalse(marker.exists())

    def test_successful_shell_cannot_leave_background_processes_running(self) -> None:
        self.init("micro")
        self.run_tool("advance")
        self.assess_risk("micro")
        self.run_tool("advance")
        self.record("implementation", "requirements/REQ-test-flow/implementation.md")
        self.run_tool("advance")
        report = self.write_artifact("requirements/REQ-test-flow/verification-background.md")
        marker = self.root / "detached-process-survived.txt"
        verification_work, _ = self.complete_role_work(
            "testing", {"verification_report": report}
        )
        self.run_tool(
            "record-artifact",
            "--name",
            "verification_report",
            "--path",
            str(report.relative_to(self.root)),
            "--work-item-id",
            verification_work,
            "--test-command",
            f"(sleep 2; echo survived > '{marker}') &",
        )
        time.sleep(2)
        self.assertFalse(marker.exists())

    @unittest.skipUnless(os.name == "posix", "symbolic-link behavior is platform-specific")
    def test_verification_rejects_symlink_that_escapes_snapshot(self) -> None:
        self.init("micro")
        self.run_tool("advance")
        self.assess_risk("micro")
        self.run_tool("advance")
        external = self.root.parent / f"{self.root.name}-external.txt"
        external.write_text("do not modify\n", encoding="utf-8")
        (self.root / "external-link.txt").symlink_to(external)
        try:
            self.record("implementation", "requirements/REQ-test-flow/implementation.md")
            self.run_tool("advance")
            report = self.write_artifact("requirements/REQ-test-flow/verification-symlink.md")
            rejected = self.run_tool(
                "record-artifact",
                "--name",
                "verification_report",
                "--path",
                str(report.relative_to(self.root)),
                "--test-command",
                "echo changed > external-link.txt",
                expected=2,
            )
            self.assertIn("symbolic link outside the repository", rejected.stderr)
            self.assertEqual("do not modify\n", external.read_text(encoding="utf-8"))
        finally:
            external.unlink(missing_ok=True)

    def test_verification_log_is_bounded_and_redacts_common_secrets(self) -> None:
        self.init("micro")
        self.run_tool("advance")
        self.assess_risk("micro")
        self.run_tool("advance")
        self.record("implementation", "requirements/REQ-test-flow/implementation.md")
        self.run_tool("advance")
        report = self.write_artifact("requirements/REQ-test-flow/verification-large.md")
        verification_work, _ = self.complete_role_work(
            "testing", {"verification_report": report}
        )
        self.run_tool(
            "record-artifact",
            "--name",
            "verification_report",
            "--path",
            str(report.relative_to(self.root)),
            "--work-item-id",
            verification_work,
            "--test-command",
            "python3 -c \"print('password=do-not-store'); print('x' * 2100000)\"",
        )
        state = json.loads(self.run_tool("status", "--json").stdout)
        execution = state["verification_snapshot"]["test_execution"]
        self.assertEqual("temporary_snapshot", execution["isolation"])
        self.assertGreater(execution["commands"][0]["output_bytes"], 2_000_000)
        self.assertNotIn("do-not-store", execution["commands"][0]["command"])
        log = self.root / execution["log_path"]
        self.assertLessEqual(log.stat().st_size, 2_000_000)
        log_text = log.read_text(encoding="utf-8")
        self.assertIn("[REDACTED]", log_text)
        self.assertNotIn("do-not-store", log_text)

    def test_verification_prunes_old_unreferenced_logs(self) -> None:
        self.init("micro")
        workflow_module = self.workflow_module()
        _, state = workflow_module.load_state(self.root)
        for _ in range(22):
            workflow_module.execute_verification_commands(
                self.root,
                state,
                (("test", "true"),),
                10,
            )
        logs = list((self.root / ".ai-workflow/REQ-test-flow/test-runs").glob("*.log"))
        self.assertEqual(20, len(logs))

    def test_workspace_binding_does_not_reread_clean_tracked_files(self) -> None:
        source = self.initialize_git_source()
        workflow_module = self.workflow_module()
        original_read_bytes = Path.read_bytes

        def guarded_read_bytes(path: Path) -> bytes:
            if path.resolve() == source.resolve():
                raise AssertionError("clean tracked source was read from disk")
            return original_read_bytes(path)

        with mock.patch.object(Path, "read_bytes", guarded_read_bytes):
            binding = workflow_module.workspace_binding(self.root)
        self.assertEqual(1, binding["file_count"])

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
        invalid_expiry = self.run_tool(
            "accept-escalation-risk",
            "--approved-by",
            "Alice",
            "--reason",
            "The reversible dependency risk is acceptable for this bounded change.",
            "--expires-on",
            "2099-99-99",
            "--evidence",
            str(acceptance.relative_to(self.root)),
            expected=2,
        )
        self.assertIn("valid YYYY-MM-DD date", invalid_expiry.stderr)
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
        workflow_module = self.workflow_module()
        state_path, state = workflow_module.load_state(self.root)
        state["escalation"]["acceptance_expires_on"] = "2000-01-01"
        workflow_module.save_state(state_path, state)
        expired = self.run_tool("advance", expected=2)
        self.assertIn("escalation_acceptance_expired:RSK-001", expired.stderr)
        resolution = self.write_artifact(
            "requirements/REQ-test-flow/risks/RSK-001-resolution.md",
            "# RSK-001 resolved\n\n## Resolver\n\nProduct resolved the dependency risk.\n\n"
            "## Independent verifier\n\nTesting independently verified the resolution.\n\n"
            "## Outcome\n\nThe external dependency is no longer required.\n",
        )
        self.run_tool(
            "resolve-risk",
            "--risk-id",
            "RSK-001",
            "--resolution",
            "Removed the external dependency.",
            "--resolved-by",
            "product",
            "--verified-by",
            "testing",
            "--evidence",
            str(resolution.relative_to(self.root)),
        )
        state = json.loads(self.run_tool("status", "--json").stdout)
        self.assertEqual("resolved", state["risk_reports"][0]["status"])
        self.assertEqual("cleared", state["escalation"]["status"])
        no_longer_expired = self.run_tool("advance", expected=2)
        self.assertNotIn("escalation_acceptance_expired", no_longer_expired.stderr)

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
            "feedback_verdict: request_changes\n\n# User feedback\n\n## Decision\n\nThe user requested a different interaction direction.\n\n"
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

    def test_user_feedback_verdict_must_match_the_evidence(self) -> None:
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
            "requirements/REQ-test-flow/07-user-feedback-rejected.md",
            "feedback_verdict: reject\n\n# User feedback\n\n## Decision\n\n"
            "The user rejected the preview direction.\n\n## Reason\n\nThe core interaction is wrong.\n\n"
            "## Next step\n\nReturn to design before implementation.\n",
        )
        rejected = self.run_tool(
            "record-user-feedback", "--verdict", "approve",
            "--summary", "Incorrect approval attempt.",
            "--evidence", str(evidence.relative_to(self.root)), expected=2,
        )
        self.assertIn("feedback_verdict: approve", rejected.stderr)
        state = json.loads(self.run_tool("status", "--json").stdout)
        self.assertEqual("user_feedback", state["workflow"]["current_stage"])
        self.assertEqual([], state["user_feedback_records"])

    def test_delivery_verdict_must_match_the_evidence(self) -> None:
        self.init("micro")
        self.run_tool("advance")
        self.assess_risk("micro")
        self.run_tool("advance")
        self.record("implementation", "requirements/REQ-test-flow/implementation.md")
        self.run_tool("advance")
        self.record("verification_report", "requirements/REQ-test-flow/verification.md")
        self.run_tool("advance")
        evidence = self.write_artifact(
            "requirements/REQ-test-flow/delivery-rejected.md",
            "delivery_verdict: reject\n\n# User delivery confirmation\n\n## User verdict\n\n"
            "The user rejected the verified delivery.\n\n## Evidence reviewed\n\n"
            "The implementation and test report were inspected.\n\n## Next step\n\nRevise implementation.\n",
        )
        rejected = self.run_tool(
            "record-delivery-confirmation", "--verdict", "approve",
            "--summary", "Incorrect approval attempt.",
            "--evidence", str(evidence.relative_to(self.root)), expected=2,
        )
        self.assertIn("delivery_verdict: approve", rejected.stderr)
        state = json.loads(self.run_tool("status", "--json").stdout)
        self.assertEqual("delivery_confirmation", state["workflow"]["current_stage"])
        self.assertEqual([], state["delivery_confirmation_records"])

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
            "--actor-ref",
            "product-agent",
            "--work-item-id",
            "product-review-work",
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
        design_work, _ = self.complete_role_work("engineering", {"technical_design": design})
        self.run_tool(
            "record-artifact",
            "--name",
            "technical_design",
            "--path",
            str(design.relative_to(self.root)),
            "--work-item-id",
            design_work,
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
            "review_verdict: approve\n\n# readiness_review engineering testing\n\nBoth role labels are intentionally present.\n\n"
            "## Findings\n\nNo blockers remain after independent verification of the supplied evidence.\n\n"
            "## Verdict\n\napprove\n"
        )
        engineering = self.write_artifact(
            "requirements/REQ-test-flow/reviews/engineering.md", shared_review_text
        )
        testing = self.write_artifact(
            "requirements/REQ-test-flow/reviews/testing.md", shared_review_text
        )
        engineering_work, engineering_actor = self.complete_role_work(
            "engineering",
            {"review:readiness_review:engineering": engineering},
        )
        self.run_tool(
            "decide",
            "--gate",
            "readiness_review",
            "--role",
            "engineering",
            "--actor-ref",
            engineering_actor,
            "--work-item-id",
            engineering_work,
            "--verdict",
            "approve",
            "--evidence",
            str(engineering.relative_to(self.root)),
        )
        unique_testing = self.write_artifact(
            "requirements/REQ-test-flow/reviews/testing-unique.md",
            "review_verdict: approve\n\n# readiness_review testing\n\nThe test plan was reviewed independently.\n\n"
            "## Findings\n\nNo blocking verification risk remains.\n\n"
            "## Verdict\n\napprove\n",
        )
        reused_actor = self.run_tool(
            "decide",
            "--gate",
            "readiness_review",
            "--role",
            "testing",
            "--actor-ref",
            engineering_actor,
            "--work-item-id",
            "missing-testing-work",
            "--verdict",
            "approve",
            "--evidence",
            str(unique_testing.relative_to(self.root)),
            expected=2,
        )
        self.assertIn("already used by engineering", reused_actor.stderr)
        testing_work, testing_actor = self.complete_role_work(
            "testing",
            {"review:readiness_review:testing": testing},
        )
        reused_review = self.run_tool(
            "decide",
            "--gate",
            "readiness_review",
            "--role",
            "testing",
            "--actor-ref",
            testing_actor,
            "--work-item-id",
            testing_work,
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
            "review_verdict: approve\n\n# readiness_review engineering\n\nISSUE-001 is mentioned for this adversarial test.\n\n"
            "## Findings\n\nThe design evidence was reviewed from the engineering perspective.\n\n"
            "## Verdict\n\napprove\n",
        )
        review_work, review_actor = self.complete_role_work(
            "engineering",
            {"review:readiness_review:engineering": review},
        )
        self.run_tool(
            "decide",
            "--gate",
            "readiness_review",
            "--role",
            "engineering",
            "--actor-ref",
            review_actor,
            "--work-item-id",
            review_work,
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
        evidence = self.write_artifact(
            "requirements/REQ-test-flow/00-requirement-confirmation.md",
            (
                "confirmation_verdict: approve\n\n"
                "# User requirement confirmation\n\n"
                "## User decision\n\nThe user confirmed and approved the clarified scope.\n\n"
                "## Confirmed scope\n\nProceed with the real requested outcome.\n\n"
                "## Open items\n\nNo unresolved decision remains.\n"
            ),
        )
        self.run_tool(
            "record-requirement-confirmation",
            "--verdict", "approve",
            "--summary", "The user approved the clarified requirement baseline.",
            "--evidence", str(evidence.relative_to(self.root)),
        )
        blocked = self.run_tool("advance", expected=2)
        self.assertIn("artifact:core_goals", blocked.stderr)
        self.assertIn("core_goals:user_confirmed_baseline", blocked.stderr)

    def test_direct_state_edit_fails_integrity_check(self) -> None:
        self.init("quick")
        state_path = self.root / ".ai-workflow" / "REQ-test-flow" / "state.yaml"
        state = json.loads(self.run_tool("status", "--json").stdout)
        state["workflow"]["title"] = "Unsupported manual edit"
        state_path.write_text(json.dumps(state), encoding="utf-8")
        rejected = self.run_tool("status", expected=2)
        self.assertIn("integrity check failed", rejected.stderr)

    def test_state_audit_and_backup_repair_recover_from_corruption(self) -> None:
        self.init("quick")
        self.run_tool("advance")
        state_path = self.root / ".ai-workflow" / "REQ-test-flow" / "state.yaml"
        state = json.loads(self.run_tool("status", "--json").stdout)
        state["workflow"]["title"] = "Corrupted manually"
        state_path.write_text(json.dumps(state), encoding="utf-8")

        audit = json.loads(self.run_tool("audit-state", "--json").stdout)
        self.assertFalse(audit["checksum_valid"])
        self.assertTrue(audit["backup_valid"])
        self.assertTrue(audit["repair_available"])
        self.run_tool(
            "repair-state",
            "--from-backup",
            "--confirm",
            "RESTORE",
        )
        restored = json.loads(self.run_tool("status", "--json").stdout)
        self.assertEqual("Test workflow", restored["workflow"]["title"])

        state_path.write_text("{ malformed", encoding="utf-8")
        malformed_audit = json.loads(self.run_tool("audit-state", "--json").stdout)
        self.assertFalse(malformed_audit["checksum_valid"])
        self.assertTrue(malformed_audit["parse_error"])
        self.assertTrue(malformed_audit["repair_available"])
        self.run_tool(
            "repair-state",
            "--from-backup",
            "--confirm",
            "RESTORE",
        )
        self.run_tool("status")

    def test_source_fingerprint_detects_post_verification_code_change(self) -> None:
        workflow_module = self.workflow_module()
        source = self.initialize_git_source()
        other = self.root / "other-module" / "other.py"
        other.parent.mkdir()
        other.write_text("VALUE = 1\n", encoding="utf-8")
        generated = self.root / "generated" / "cache.txt"
        generated.parent.mkdir()
        generated.write_text("cache-v1\n", encoding="utf-8")
        subprocess.run(
            [
                "git",
                "-C",
                str(self.root),
                "add",
                str(other.relative_to(self.root)),
                str(generated.relative_to(self.root)),
            ],
            check=True,
        )
        subprocess.run(["git", "-C", str(self.root), "commit", "-qm", "other module"], check=True)

        verified = workflow_module.current_source_fingerprint(self.root)
        self.assertEqual([], verified["dirty_paths"])
        ignored_before = workflow_module.current_source_fingerprint(
            self.root, (), ("generated",)
        )
        generated.write_text("cache-v2\n", encoding="utf-8")
        ignored_dirty = workflow_module.current_source_fingerprint(
            self.root, (), ("generated",)
        )
        self.assertEqual([], ignored_dirty["dirty_paths"])
        subprocess.run(
            ["git", "-C", str(self.root), "add", str(generated.relative_to(self.root))],
            check=True,
        )
        subprocess.run(["git", "-C", str(self.root), "commit", "-qm", "generated update"], check=True)
        ignored_after = workflow_module.current_source_fingerprint(
            self.root, (), ("generated",)
        )
        self.assertEqual(
            ignored_before["source_tree_sha256"],
            ignored_after["source_tree_sha256"],
        )
        verified = workflow_module.current_source_fingerprint(self.root)
        source.write_text("print('changed after verification')\n", encoding="utf-8")
        changed = workflow_module.current_source_fingerprint(self.root)
        self.assertIn("app.py", changed["dirty_paths"])
        self.assertEqual(
            verified["source_tree_sha256"],
            changed["source_tree_sha256"],
        )
        scoped = workflow_module.current_source_fingerprint(self.root, ("other-module",))
        self.assertEqual([], scoped["dirty_paths"])

    def test_source_fingerprint_detects_rename_from_ignored_to_product_path(self) -> None:
        workflow_module = self.workflow_module()
        self.initialize_git_source()
        ignored_source = self.root / "docs" / "requirements" / "legacy-helper.py"
        ignored_source.parent.mkdir(parents=True, exist_ok=True)
        ignored_source.write_text("VALUE = 'staged'\n", encoding="utf-8")
        subprocess.run(
            [
                "git",
                "-C",
                str(self.root),
                "add",
                "-f",
                str(ignored_source.relative_to(self.root)),
            ],
            check=True,
        )
        subprocess.run(
            ["git", "-C", str(self.root), "commit", "-qm", "ignored source"],
            check=True,
        )
        subprocess.run(
            [
                "git",
                "-C",
                str(self.root),
                "mv",
                str(ignored_source.relative_to(self.root)),
                "renamed-product.py",
            ],
            check=True,
        )

        fingerprint = workflow_module.current_source_fingerprint(self.root)

        self.assertIn("renamed-product.py", fingerprint["dirty_paths"])

    def test_journey_can_record_blocked_result_without_claiming_success(self) -> None:
        self.init("strict")
        source = self.initialize_git_source()
        workflow_module = self.workflow_module()
        state_path, state = workflow_module.load_state(self.root)
        state["workflow"]["current_stage"] = "verification"
        workflow_module.save_state(state_path, state)
        source_evidence = self.write_artifact(
            "requirements/REQ-test-flow/source.md",
            "# Source verification\n\n## Build\n\nThe build command completed.\n\n"
            "## Tests\n\nThe focused test command completed.\n\n## Revision\n\nThe committed source is under test.\n",
        )
        source.write_text("print('dirty')\n", encoding="utf-8")
        dirty = self.run_tool(
            "record-source-revision",
            "--evidence",
            str(source_evidence.relative_to(self.root)),
            "--build-command",
            "true",
            "--test-command",
            "true",
            "--source-path",
            "app.py",
            expected=2,
        )
        self.assertTrue(
            "Project continuity blocked" in dirty.stderr
            or "Commit the exact source" in dirty.stderr
        )
        source.write_text("print('verified')\n", encoding="utf-8")
        self.run_tool(
            "record-source-revision",
            "--evidence",
            str(source_evidence.relative_to(self.root)),
            "--build-command",
            "true",
            "--test-command",
            "true",
            "--source-path",
            "app.py",
        )
        journey = self.write_artifact(
            "requirements/REQ-test-flow/journey-blocked.md",
            "# CLI journey\n\n## launch and core_outcomes\n\nlaunch pass; core_outcomes pass.\n\n"
            "## content_semantics and interactions\n\ncontent_semantics pass; interactions blocked.\n\n"
            "## release_hygiene and source_truth\n\nrelease_hygiene pass; source_truth pass.\n",
        )
        journey_work, _ = self.complete_role_work(
            "testing", {"journey_report": journey}
        )
        recorded = self.run_tool(
            "record-user-journey",
            "--profile",
            "cli",
            "--check",
            "launch=pass",
            "--check",
            "core_outcomes=pass",
            "--check",
            "content_semantics=pass",
            "--check",
            "interactions=blocked",
            "--check",
            "release_hygiene=pass",
            "--check",
            "source_truth=pass",
            "--evidence",
            str(journey.relative_to(self.root)),
            "--work-item-id",
            journey_work,
        )
        self.assertIn("non-passing checks: interactions", recorded.stdout)
        state = json.loads(self.run_tool("status", "--json").stdout)
        self.assertEqual("blocked", state["journey_validation"]["checks"]["interactions"])
        blocked = self.run_tool("advance", expected=2)
        self.assertIn("journey_validation:final_user_journey", blocked.stderr)

    def test_submit_verification_registers_one_atomic_bundle(self) -> None:
        self.init("strict")
        self.initialize_git_source()
        workflow_module = self.workflow_module()
        state_path, state = workflow_module.load_state(self.root)
        state["workflow"]["current_stage"] = "verification"
        state["acceptance_criteria"] = {
            "AC-001": {
                "description": "The CLI reports the correct result.",
                "priority": "must",
                "prd_sha256": "test-prd",
            }
        }
        workflow_module.save_state(state_path, state)
        source_evidence = self.write_artifact(
            "requirements/REQ-test-flow/source-bundle.md",
            "# Source evidence\n\n## Build\n\nBuild passed.\n\n## Tests\n\nTests passed.\n\n"
            "## Revision\n\nThe committed app.py source is the verified delivery scope.\n",
        )
        criterion = self.write_artifact(
            "requirements/REQ-test-flow/ac-001.md",
            "# AC-001 verification\n\n## Expected\n\nThe CLI reports the correct result.\n\n"
            "## Executed\n\nThe behavior was exercised.\n\n## Verdict\n\nAC-001 pass.\n",
        )
        verification_report = self.write_artifact(
            "requirements/REQ-test-flow/verification-bundle.md",
            "# Independent verification report\n\n## Source candidate\n\nThe exact committed candidate was built and tested.\n\n"
            "## Acceptance results\n\nAC-001 passed against the same candidate.\n\n"
            "## Conclusion\n\nIndependent verification passed without replacing the delivery source.\n",
        )
        journey = self.write_artifact(
            "requirements/REQ-test-flow/journey-bundle.md",
            "# CLI journey\n\n## launch and core_outcomes\n\nlaunch pass; core_outcomes pass.\n\n"
            "## content_semantics and interactions\n\ncontent_semantics pass; interactions pass.\n\n"
            "## release_hygiene and source_truth\n\nrelease_hygiene pass; source_truth pass.\n",
        )
        verification_work, _ = self.complete_role_work(
            "testing",
            {
                "verification_report": verification_report,
                "journey_report": journey,
            },
        )
        manifest = self.root / "docs" / "requirements" / "REQ-test-flow" / "verification.json"
        manifest.write_text(
            json.dumps(
                {
                    "work_item_id": verification_work,
                    "source": {
                        "evidence": str(source_evidence.relative_to(self.root)),
                        "build_command": "true",
                        "test_command": "true",
                        "paths": ["app.py"],
                        "ignore_paths": ["generated"],
                    },
                    "criteria": [
                        {
                            "id": "AC-001",
                            "verdict": "pass",
                            "evidence": str(criterion.relative_to(self.root)),
                        }
                    ],
                    "report": {
                        "evidence": str(verification_report.relative_to(self.root)),
                    },
                    "journey": {
                        "profile": "cli",
                        "evidence": str(journey.relative_to(self.root)),
                        "checks": {
                            "launch": "pass",
                            "core_outcomes": "pass",
                            "content_semantics": "pass",
                            "interactions": "pass",
                            "release_hygiene": "pass",
                            "source_truth": "pass",
                        },
                    },
                }
            ),
            encoding="utf-8",
        )
        invalid_manifest = json.loads(manifest.read_text(encoding="utf-8"))
        invalid_manifest["source"]["command_timeout"] = "not-a-number"
        manifest.write_text(json.dumps(invalid_manifest), encoding="utf-8")
        invalid = self.run_tool(
            "submit-verification",
            "--manifest",
            str(manifest.relative_to(self.root)),
            expected=2,
        )
        self.assertIn("whole number of seconds", invalid.stderr)
        self.assertNotIn("Traceback", invalid.stderr)
        invalid_manifest["source"]["command_timeout"] = 300
        before = json.loads(self.run_tool("status", "--json").stdout)["revision"]
        invalid_manifest["idempotency_key"] = "verification-round-001"
        invalid_manifest["expected_revision"] = before
        manifest.write_text(json.dumps(invalid_manifest), encoding="utf-8")
        self.run_tool(
            "submit-verification",
            "--manifest",
            str(manifest.relative_to(self.root)),
        )
        after = json.loads(self.run_tool("status", "--json").stdout)
        self.assertEqual(before + 1, after["revision"])
        self.assertEqual("pass", after["criterion_verdicts"]["AC-001"]["verdict"])
        self.assertEqual("cli", after["journey_validation"]["profile"])
        self.assertEqual(["app.py"], after["source_revision"]["scope_paths"])
        self.assertEqual(["generated"], after["source_revision"]["ignored_paths"])
        self.assertEqual("pass", after["source_revision"]["test_execution"]["status"])
        self.assertEqual(
            str(verification_report.relative_to(self.root)),
            after["artifacts"]["verification_report"]["path"],
        )
        self.assertEqual(
            str(journey.relative_to(self.root)),
            after["artifacts"]["journey_report"]["path"],
        )
        replayed = self.run_tool(
            "submit-verification",
            "--manifest",
            str(manifest.relative_to(self.root)),
        )
        self.assertIn("already submitted", replayed.stdout)
        replay_state = json.loads(self.run_tool("status", "--json").stdout)
        self.assertEqual(after["revision"], replay_state["revision"])

    def test_submit_gate_review_registers_decisions_and_meeting_atomically(self) -> None:
        self.init("quick")
        self.complete_discovery()
        self.record("technical_design", "requirements/REQ-test-flow/03-design.md")
        self.record("test_plan", "requirements/REQ-test-flow/05-test-plan.md")
        self.run_tool("advance")
        engineering = self.write_artifact(
            "requirements/REQ-test-flow/reviews/readiness-engineering-bundle.md",
            "review_verdict: approve\n\n# readiness_review engineering\n\nThe approved design is feasible and implementation-ready.\n\n"
            "## Findings\n\nNo blocking engineering findings remain.\n\n## Verdict\n\napprove\n",
        )
        testing = self.write_artifact(
            "requirements/REQ-test-flow/reviews/readiness-testing-bundle.md",
            "review_verdict: approve\n\n# readiness_review testing\n\nThe test plan is executable against the approved scope.\n\n"
            "## Findings\n\nNo blocking testing findings remain.\n\n## Verdict\n\napprove\n",
        )
        engineering_work, _ = self.complete_role_work(
            "engineering",
            {"review:readiness_review:engineering": engineering},
            actor_ref="engineering-agent",
        )
        testing_work, _ = self.complete_role_work(
            "testing",
            {"review:readiness_review:testing": testing},
            actor_ref="testing-agent",
        )
        bundle = {
            "idempotency_key": "readiness-review-round-001",
            "gate": "readiness_review",
            "decisions": [
                {
                    "role": "engineering",
                    "actor_ref": "engineering-agent",
                    "work_item_id": engineering_work,
                    "verdict": "approve",
                    "evidence": str(engineering.relative_to(self.root)),
                    "findings": [],
                },
                {
                    "role": "testing",
                    "actor_ref": "engineering-agent",
                    "work_item_id": testing_work,
                    "verdict": "approve",
                    "evidence": str(testing.relative_to(self.root)),
                    "findings": [],
                },
            ],
            "meeting": {
                "title": "Readiness review",
                "participants": ["engineering", "testing"],
                "outcome": "approved",
                "summary": "Engineering and testing reviewed the same readiness baseline.",
                "decision": "Proceed to implementation after retaining both approvals.",
                "rationale": "The design is feasible and the planned verification is executable.",
                "action_owners": ["engineering: implementation", "testing: verification"],
                "open_questions": [],
                "next_step": "Advance the readiness gate.",
            },
        }
        manifest = self.write_artifact(
            "requirements/REQ-test-flow/readiness-bundle.json",
            json.dumps(bundle),
        )
        before = json.loads(self.run_tool("status", "--json").stdout)["revision"]
        bundle["expected_revision"] = before
        manifest.write_text(json.dumps(bundle), encoding="utf-8")
        rejected = self.run_tool(
            "submit-gate-review",
            "--manifest",
            str(manifest.relative_to(self.root)),
            expected=2,
        )
        self.assertIn("Actor reference is reused", rejected.stderr)
        unchanged = json.loads(self.run_tool("status", "--json").stdout)
        self.assertEqual(before, unchanged["revision"])
        self.assertEqual({}, unchanged["decisions"])

        bundle["decisions"][1]["actor_ref"] = "testing-agent"
        manifest.write_text(json.dumps(bundle), encoding="utf-8")
        self.run_tool(
            "submit-gate-review",
            "--manifest",
            str(manifest.relative_to(self.root)),
        )
        recorded = json.loads(self.run_tool("status", "--json").stdout)
        self.assertEqual(before + 1, recorded["revision"])
        self.assertEqual(
            {"engineering", "testing"},
            set(recorded["decisions"]["readiness_review"]),
        )
        self.assertEqual("readiness_review", recorded["meetings"][-1]["type"])
        self.assertTrue(recorded["meetings"][-1]["inline"])
        self.assertEqual(
            str(manifest.relative_to(self.root)),
            recorded["meetings"][-1]["path"],
        )
        meeting_count = len(recorded["meetings"])
        replayed = self.run_tool(
            "submit-gate-review",
            "--manifest",
            str(manifest.relative_to(self.root)),
        )
        self.assertIn("already submitted", replayed.stdout)
        replay_state = json.loads(self.run_tool("status", "--json").stdout)
        self.assertEqual(recorded["revision"], replay_state["revision"])
        self.assertEqual(meeting_count, len(replay_state["meetings"]))
        self.run_tool("advance")

    def test_scope_change_authorizes_not_applicable_criterion(self) -> None:
        self.init("strict")
        self.initialize_git_source()
        workflow_module = self.workflow_module()
        state_path, state = workflow_module.load_state(self.root)
        state["workflow"]["current_stage"] = "verification"
        state["acceptance_criteria"] = {
            "AC-001": {
                "description": "Optional integration behavior.",
                "priority": "must",
                "prd_sha256": "test-prd",
            }
        }
        workflow_module.save_state(state_path, state)
        approval = self.write_artifact(
            "requirements/REQ-test-flow/scope-change.md",
            "# Scope change\n\n## User approval\n\nUser Alice approved deferring AC-001.\n\n"
            "## Reason\n\nThe optional integration is removed from this delivery.\n\n"
            "## Decision\n\nAC-001 is explicitly not applicable for this version.\n",
        )
        self.run_tool(
            "approve-scope-change",
            "--item",
            "AC-001",
            "--disposition",
            "deferred",
            "--approved-by",
            "Alice",
            "--reason",
            "User approved deferral.",
            "--evidence",
            str(approval.relative_to(self.root)),
        )
        rewound = json.loads(self.run_tool("status", "--json").stdout)
        self.assertEqual("prd", rewound["workflow"]["current_stage"])
        state_path, state = workflow_module.load_state(self.root)
        state["workflow"]["current_stage"] = "verification"
        workflow_module.save_state(state_path, state)
        source_evidence = self.write_artifact(
            "requirements/REQ-test-flow/source-na.md",
            "# Source verification\n\n## Build\n\nBuild passed.\n\n## Tests\n\nTests passed.\n\n"
            "## Revision\n\nThe committed source is ready for criterion disposition.\n",
        )
        self.run_tool(
            "record-source-revision",
            "--evidence",
            str(source_evidence.relative_to(self.root)),
            "--build-command",
            "true",
            "--test-command",
            "true",
            "--source-path",
            "app.py",
        )
        verdict = self.write_artifact(
            "requirements/REQ-test-flow/ac-001-na.md",
            "# AC-001 verdict\n\n## Scope decision\n\nSC-001 covers AC-001.\n\n"
            "## Evidence\n\nThe user-approved deferral was reviewed.\n\n"
            "## Verdict\n\nAC-001 not applicable.\n",
        )
        verdict_work, _ = self.complete_role_work(
            "testing", {"criterion_verdict:AC-001": verdict}
        )
        self.run_tool(
            "record-criterion-verdict",
            "--criterion-id",
            "AC-001",
            "--verdict",
            "not_applicable",
            "--scope-change-id",
            "SC-001",
            "--evidence",
            str(verdict.relative_to(self.root)),
            "--work-item-id",
            verdict_work,
        )
        final_state = json.loads(self.run_tool("status", "--json").stdout)
        self.assertEqual(
            "not_applicable",
            final_state["criterion_verdicts"]["AC-001"]["verdict"],
        )

    def test_scope_change_can_rewind_only_the_approved_impact_area(self) -> None:
        self.init("strict")
        workflow_module = self.workflow_module()
        state_path, state = workflow_module.load_state(self.root)
        state["workflow"]["current_stage"] = "acceptance"
        state["acceptance_criteria"] = {
            "AC-001": {
                "description": "External integration is available.",
                "priority": "must",
                "prd_sha256": "test-prd",
            }
        }
        state["artifacts"]["prd"] = {"status": "ready"}
        state["artifacts"]["implementation"] = {"status": "ready"}
        state["artifacts"]["journey_report"] = {"status": "ready"}
        state["criterion_verdicts"] = {
            "AC-001": {"verdict": "pass", "actor_ref": "tester-agent"}
        }
        state["journey_validation"] = {
            "profile": "api",
            "checks": {"launch": "pass"},
        }
        state["core_outcomes"] = {
            "GOAL-001": {"verdict": "satisfied"}
        }
        state["decisions"]["acceptance"] = {
            "testing": {"verdict": "approve"},
        }
        workflow_module.save_state(state_path, state)
        approval = self.write_artifact(
            "requirements/REQ-test-flow/local-scope-change.md",
            "# Scope change\n\n"
            "## User approval\n\nUser Alice approved deferring AC-001.\n\n"
            "## Impact analysis\n\nThe approved earliest affected stage is verification; "
            "the PRD, design, and implementation remain valid.\n\n"
            "## Decision\n\nAC-001 is not applicable for this delivery.\n",
        )
        self.run_tool(
            "approve-scope-change",
            "--item",
            "AC-001",
            "--disposition",
            "deferred",
            "--approved-by",
            "Alice",
            "--reason",
            "External service is unavailable.",
            "--impact-stage",
            "verification",
            "--impact-reason",
            "Only verification and later acceptance evidence depends on the integration.",
            "--evidence",
            str(approval.relative_to(self.root)),
        )
        _, changed = workflow_module.load_state(self.root)
        self.assertEqual("verification", changed["workflow"]["current_stage"])
        self.assertEqual("ready", changed["artifacts"]["prd"]["status"])
        self.assertEqual("ready", changed["artifacts"]["implementation"]["status"])
        self.assertEqual("superseded", changed["artifacts"]["journey_report"]["status"])
        self.assertNotIn("acceptance", changed["decisions"])
        self.assertEqual({}, changed["criterion_verdicts"])
        self.assertEqual({}, changed["journey_validation"])
        self.assertEqual({}, changed["core_outcomes"])
        scope_change = changed["scope_changes"][-1]
        self.assertEqual("prd", scope_change["baseline_stage"])
        self.assertEqual("verification", scope_change["impact_stage"])

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
        delivery_stage = self.run_tool("advance")
        self.assertIn("acceptance -> delivery_confirmation", delivery_stage.stdout)
        self.confirm_delivery()
        completed = self.run_tool("advance")
        self.assertIn("delivery_confirmation -> completed", completed.stdout)
        self.assertFalse((self.root / ".ai-workflow" / "active.yaml").exists())
        project = json.loads(self.run_tool("--id", "REQ-test-flow", "project", "--json").stdout)
        self.assertEqual("completed", project["alignment"]["status"])
        self.assertEqual("已按目标完成", project["alignment"]["label"])

    def test_state_revision_increments_and_schema_is_validated(self) -> None:
        self.init("quick")
        initial = json.loads(self.run_tool("status", "--json").stdout)
        self.assertEqual(11, initial["schema_version"])
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

    def test_history_events_refresh_workflow_updated_at(self) -> None:
        self.init("micro")
        workflow_module = self.workflow_module()
        state_path, state = workflow_module.load_state(self.root)
        state["workflow"]["updated_at"] = "2000-01-01T00:00:00+00:00"
        workflow_module.save_state(state_path, state)
        self.run_tool("advance")
        refreshed = json.loads(self.run_tool("status", "--json").stdout)
        self.assertNotEqual(
            "2000-01-01T00:00:00+00:00",
            refreshed["workflow"]["updated_at"],
        )

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
        self.assertEqual(11, migrated["schema_version"])
        self.assertNotIn("scope_check", migrated["workflow"]["flow_stages"])
        self.run_tool("advance")
        self.assertIn("Stage: clarification", self.run_tool("status").stdout)

    def test_schema_v5_micro_migration_adds_delivery_confirmation(self) -> None:
        self.init("micro")
        state_path = self.root / ".ai-workflow" / "REQ-test-flow" / "state.yaml"
        state = json.loads(self.run_tool("status", "--json").stdout)
        state["schema_version"] = 5
        state["workflow"]["flow_stages"].remove("delivery_confirmation")
        state_path.write_text(json.dumps(state), encoding="utf-8")
        migrated = json.loads(self.run_tool("status", "--json").stdout)
        self.assertEqual(11, migrated["schema_version"])
        self.assertEqual(
            ["intake", "scope_check", "implementation", "verification", "delivery_confirmation", "completed"],
            migrated["workflow"]["flow_stages"],
        )

    def test_schema_v9_migration_preserves_state_and_adds_new_defaults(self) -> None:
        self.init("standard")
        state_path = self.root / ".ai-workflow" / "REQ-test-flow" / "state.yaml"
        state = json.loads(self.run_tool("status", "--json").stdout)
        state["schema_version"] = 9
        state.pop("verification_snapshot", None)
        state.pop("repository_context", None)
        state_path.write_text(json.dumps(state), encoding="utf-8")
        migrated = json.loads(self.run_tool("status", "--json").stdout)
        self.assertEqual(11, migrated["schema_version"])
        self.assertEqual({}, migrated["verification_snapshot"])
        self.assertEqual({}, migrated["repository_context"])

    def test_schema_v10_role_evidence_is_preserved_but_cannot_pass_v11_gate(self) -> None:
        self.init("standard")
        state_path = self.root / ".ai-workflow" / "REQ-test-flow" / "state.yaml"
        state = json.loads(self.run_tool("status", "--json").stdout)
        legacy_prd = self.write_artifact(
            "requirements/REQ-test-flow/legacy-prd.md",
            "# Legacy PRD\n\n## Scope\n\nLegacy role output.\n\n## Acceptance\n\nLegacy acceptance criteria.\n",
        )
        state["schema_version"] = 10
        state["workflow"]["current_stage"] = "prd"
        state["artifacts"]["prd"] = {
            "path": str(legacy_prd.relative_to(self.root)),
            "status": "ready",
            "evidence_sha256": hashlib.sha256(legacy_prd.read_bytes()).hexdigest(),
        }
        state_path.write_text(json.dumps(state), encoding="utf-8")

        overview = json.loads(self.run_tool("overview", "--json").stdout)

        self.assertIn("artifact:prd", overview["missing"])
        migrated = json.loads(self.run_tool("status", "--json").stdout)
        self.assertTrue(migrated["artifacts"]["prd"]["legacy_unbound"])

    def test_explicit_id_cannot_mutate_a_non_active_workflow(self) -> None:
        self.init("micro")
        self.run_tool("deactivate", "--reason", "Switch workflow.")
        self.run_tool(
            "init",
            "--id",
            "REQ-active-two",
            "--title",
            "Second workflow",
            "--mode",
            "micro",
            "--request",
            "Own the active pointer.",
        )
        first_path = self.root / ".ai-workflow" / "REQ-test-flow" / "state.yaml"
        before = first_path.read_bytes()

        rejected = self.run_tool(
            "--id", "REQ-test-flow", "advance", expected=2
        )

        self.assertIn("refusing to mutate non-active workflow", rejected.stderr)
        self.assertEqual(before, first_path.read_bytes())

    def test_pause_suppresses_mutations_until_resume(self) -> None:
        self.init("micro")
        self.run_tool("pause", "--reason", "User is discussing an unrelated question.")
        paused = json.loads(self.run_tool("overview", "--json").stdout)
        self.assertEqual("paused", paused["status"])
        self.assertIn("workflow:paused", paused["missing"])
        self.assertIn("changed files", paused["execution_policy"]["context"])
        blocked = self.run_tool("advance", expected=2)
        self.assertIn("Workflow is paused", blocked.stderr)
        self.run_tool("resume")
        resumed = json.loads(self.run_tool("status", "--json").stdout)
        self.assertEqual("active", resumed["workflow"]["status"])

    def test_overview_warns_when_git_branch_changes(self) -> None:
        self.initialize_git_source()
        self.init("micro")
        subprocess.run(["git", "-C", str(self.root), "checkout", "-qb", "other"], check=True)
        overview = json.loads(self.run_tool("overview", "--json").stdout)
        self.assertTrue(
            any("Git branch changed" in warning for warning in overview["health_warnings"])
        )

    def test_prepare_turn_initializes_git_for_an_existing_unprotected_project(self) -> None:
        self.init("micro")
        shutil.rmtree(self.root / ".git")

        prepared = json.loads(self.run_tool("prepare-turn", "--json").stdout)

        self.assertEqual("ready", prepared["status"])
        self.assertEqual("git", prepared["version_control"]["version_control"])
        self.assertEqual(
            "initialized", prepared["version_control"]["version_control_status"]
        )
        self.assertTrue((self.root / ".git").is_dir())
        state = json.loads(self.run_tool("status", "--json").stdout)
        self.assertEqual(
            "missing", state["repository_context"]["git_baseline_status"]
        )
        project = json.loads(self.run_tool("project", "--json").stdout)
        self.assertEqual(
            "initialized_without_baseline", project["version_protection"]["status"]
        )

    def test_prepare_turn_rejects_source_work_newer_than_recorded_state(self) -> None:
        self.init("micro")
        state_path = self.root / ".ai-workflow" / "REQ-test-flow" / "state.yaml"
        before = state_path.read_bytes()
        source = self.root / "app" / "main.py"
        source.parent.mkdir()
        source.write_text("print('outside workflow')\n", encoding="utf-8")
        future = time.time() + 5
        os.utime(source, (future, future))

        rejected = self.run_tool("prepare-turn", "--json", expected=2)
        payload = json.loads(rejected.stdout)

        self.assertEqual("reconciliation_required", payload["status"])
        self.assertEqual(["app/main.py"], payload["unrecorded_source_paths"])
        self.assertEqual(before, state_path.read_bytes())
        overview = json.loads(self.run_tool("overview", "--json").stdout)
        self.assertIn("workspace:unreconciled_source_activity", overview["missing"])
        blocked = self.run_tool("advance", expected=2)
        self.assertIn("Project continuity blocked", blocked.stderr)

    def test_prepare_turn_rejects_a_committed_source_change_after_the_baseline(self) -> None:
        source = self.initialize_git_source()
        self.init("micro")
        source.write_text("print('committed outside workflow')\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(self.root), "add", "app.py"], check=True)
        subprocess.run(
            ["git", "-C", str(self.root), "commit", "-m", "outside workflow change"],
            check=True,
            stdout=subprocess.DEVNULL,
        )

        rejected = self.run_tool("prepare-turn", "--json", expected=2)

        payload = json.loads(rejected.stdout)
        self.assertEqual("reconciliation_required", payload["status"])
        self.assertEqual(["app.py"], payload["unrecorded_source_paths"])

    def test_archive_documents_moves_only_superseded_files_and_writes_index(self) -> None:
        self.init("micro")
        workflow_dir = self.root / "docs/requirements/REQ-test-flow"
        obsolete = self.write_artifact(
            "requirements/REQ-test-flow/old-design.md",
            "# 旧设计\n\n该设计已经由当前方案替代，仅保留用于历史追溯。\n",
        )
        replacement = self.write_artifact(
            "requirements/REQ-test-flow/current-design.md",
            "# 当前设计\n\n这是当前有效的替代设计。\n",
        )
        workflow_module = self.workflow_module()
        state_path, state = workflow_module.load_state(self.root)
        state["history"].append(
            {
                "at": workflow_module.now(),
                "event": "legacy_document",
                "detail": str(obsolete.relative_to(self.root)),
            }
        )
        workflow_module.save_state(state_path, state)
        manifest = self.write_artifact(
            "requirements/REQ-test-flow/changes/ARC-001.json",
            json.dumps(
                {
                    "archive_id": "ARC-001-old-design",
                    "reason": "当前设计已经替代旧设计，旧文件仅保留用于历史追溯。",
                    "documents": [
                        {
                            "path": str(obsolete.relative_to(self.root)),
                            "replaced_by": str(replacement.relative_to(self.root)),
                        }
                    ],
                },
                ensure_ascii=False,
            ),
        )
        self.run_tool("archive-documents", "--manifest", str(manifest.relative_to(self.root)))
        archived = workflow_dir / "_archive/ARC-001-old-design/old-design.md"
        index = workflow_dir / "_archive/ARC-001-old-design/INDEX.md"
        self.assertFalse(obsolete.exists())
        self.assertTrue(archived.is_file())
        self.assertIn("current-design.md", index.read_text(encoding="utf-8"))
        archived_state = json.loads(self.run_tool("status", "--json").stdout)
        self.assertIn(
            "docs/requirements/REQ-test-flow/_archive/ARC-001-old-design/old-design.md",
            {item["detail"] for item in archived_state["history"]},
        )

        active_manifest = self.write_artifact(
            "requirements/REQ-test-flow/changes/ARC-002.json",
            json.dumps(
                {
                    "archive_id": "ARC-002-active",
                    "reason": "此操作必须拒绝，因为当前请求文档仍是有效基线。",
                    "documents": [
                        {
                            "path": "docs/requirements/REQ-test-flow/00-original-request.md",
                            "replaced_by": str(replacement.relative_to(self.root)),
                        }
                    ],
                },
                ensure_ascii=False,
            ),
        )
        rejected = self.run_tool(
            "archive-documents",
            "--manifest",
            str(active_manifest.relative_to(self.root)),
            expected=2,
        )
        self.assertIn("current active document", rejected.stderr)
        self.assertTrue((workflow_dir / "00-original-request.md").is_file())

        superseded = self.write_artifact(
            "requirements/REQ-test-flow/old-notes.md",
            "# 旧记录\n\n这是待归档的历史记录。\n",
        )
        current = self.write_artifact(
            "requirements/REQ-test-flow/current-notes.md",
            "# 当前记录\n\n这是旧记录指向的当前替代文档。\n",
        )
        circular_manifest = self.write_artifact(
            "requirements/REQ-test-flow/changes/ARC-003.json",
            json.dumps(
                {
                    "archive_id": "ARC-003-invalid-batch",
                    "reason": "替代文档必须在归档后仍然作为当前有效的追溯目标。",
                    "documents": [
                        {
                            "path": str(superseded.relative_to(self.root)),
                            "replaced_by": str(current.relative_to(self.root)),
                        },
                        {"path": str(current.relative_to(self.root))},
                    ],
                },
                ensure_ascii=False,
            ),
        )
        same_batch = self.run_tool(
            "archive-documents",
            "--manifest",
            str(circular_manifest.relative_to(self.root)),
            expected=2,
        )
        self.assertIn("cannot be archived in the same batch", same_batch.stderr)
        self.assertTrue(superseded.is_file())
        self.assertTrue(current.is_file())

    def test_project_view_omits_resolutions_whose_evidence_is_archived(self) -> None:
        sys.path.insert(0, str(SCRIPT.parent))
        try:
            import lifecycle_commands
        finally:
            sys.path.pop(0)
        state = {
            "issues": [
                {
                    "status": "resolved",
                    "resolved_at": "2026-08-25T12:00:00+00:00",
                    "summary": "旧方案问题",
                    "resolution": "旧方案下的处理",
                    "resolution_evidence": "docs/requirements/REQ/_archive/ARC-001/old.md",
                },
                {
                    "status": "resolved",
                    "resolved_at": "2026-08-26T12:00:00+00:00",
                    "summary": "当前方案问题",
                    "resolution": "当前方案下的处理",
                    "resolution_evidence": "docs/requirements/REQ/issues/current.md",
                },
            ]
        }
        self.assertEqual(
            ["当前方案问题"],
            [item["problem"] for item in lifecycle_commands._resolved_project_issues(state)],
        )

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

        self.run_tool("reopen", "--stage", "prd", "--reason", "Replace stale PRD evidence")
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

    def test_changed_upstream_artifact_requires_explicit_reopen(self) -> None:
        self.init()
        self.complete_discovery()
        self.record("prd", "requirements/REQ-test-flow/01-prd.md")
        self.run_tool("advance")
        self.approve("prd_review", ("product", "engineering", "testing"))
        self.run_tool("advance")
        self.record("technical_design", "requirements/REQ-test-flow/03-design.md")
        self.record("test_plan", "requirements/REQ-test-flow/05-test-plan.md")
        self.run_tool("advance")
        rejected = self.run_tool(
            "record-artifact",
            "--name",
            "prd",
            "--path",
            str(self.write_artifact("requirements/REQ-test-flow/01-prd-late.md").relative_to(self.root)),
            expected=2,
        )
        self.assertIn("Reopen explicitly", rejected.stderr)
        self.run_tool("reopen", "--stage", "prd", "--reason", "Business scope changed")
        self.record("prd", "requirements/REQ-test-flow/01-prd-v2.md")

        status = self.run_tool("status", "--json")
        state = json.loads(status.stdout)
        self.assertEqual("prd", state["workflow"]["current_stage"])
        self.assertEqual("superseded", state["artifacts"]["technical_design"]["status"])
        self.assertEqual("superseded", state["artifacts"]["test_plan"]["status"])
        self.assertIn("reopened", [event["event"] for event in state["history"]])

    def test_role_owned_artifact_requires_completed_work_and_replays_idempotently(self) -> None:
        self.init("quick")
        self.complete_discovery()
        artifact = self.write_artifact("requirements/REQ-test-flow/03-role-owned.md")

        missing = self.run_tool(
            "record-artifact",
            "--name",
            "technical_design",
            "--path",
            str(artifact.relative_to(self.root)),
            expected=2,
        )
        self.assertIn("work-item-id", missing.stderr)

        self.run_tool(
            "begin-work",
            "--work-item-id",
            "engineering-cancelled",
            "--role",
            "engineering",
            "--actor-ref",
            "engineering-cancelled-agent",
            "--deadline-at",
            "2099-01-01T00:00:00Z",
        )
        self.run_tool(
            "cancel-work",
            "--work-item-id",
            "engineering-cancelled",
            "--reason",
            "The attempt was intentionally cancelled.",
        )
        cancelled = self.run_tool(
            "record-artifact",
            "--name",
            "technical_design",
            "--path",
            str(artifact.relative_to(self.root)),
            "--work-item-id",
            "engineering-cancelled",
            expected=2,
        )
        self.assertIn("cancelled work item", cancelled.stderr)

        work_item_id, _ = self.complete_role_work(
            "engineering", {"technical_design": artifact}
        )
        self.run_tool(
            "record-artifact",
            "--name",
            "technical_design",
            "--path",
            str(artifact.relative_to(self.root)),
            "--work-item-id",
            work_item_id,
        )
        recorded = json.loads(self.run_tool("status", "--json").stdout)
        revision = recorded["revision"]
        self.assertEqual(
            work_item_id,
            recorded["artifacts"]["technical_design"]["producer_work_item_id"],
        )

        replay = self.run_tool(
            "record-artifact",
            "--name",
            "technical_design",
            "--path",
            str(artifact.relative_to(self.root)),
            "--work-item-id",
            work_item_id,
        )
        self.assertIn("already recorded", replay.stdout)
        self.assertEqual(
            revision,
            json.loads(self.run_tool("status", "--json").stdout)["revision"],
        )

    def test_rejected_review_creates_one_stable_issue_and_replays_idempotently(self) -> None:
        self.init("quick")
        self.complete_discovery()
        self.record("technical_design", "requirements/REQ-test-flow/03-design.md")
        self.record("test_plan", "requirements/REQ-test-flow/05-test-plan.md")
        self.run_tool("advance")
        evidence = self.write_artifact(
            "requirements/REQ-test-flow/reviews/readiness-engineering-reject.md",
            "review_verdict: reject\n\n# readiness_review engineering review\n\n"
            "The frozen interface cannot be implemented safely.\n\n"
            "## Verdict\n\nreject\n",
        )
        work_item_id, actor_ref = self.complete_role_work(
            "engineering",
            {"review:readiness_review:engineering": evidence},
        )

        missing = self.run_tool(
            "decide",
            "--gate",
            "readiness_review",
            "--role",
            "engineering",
            "--actor-ref",
            actor_ref,
            "--work-item-id",
            work_item_id,
            "--verdict",
            "reject",
            "--evidence",
            str(evidence.relative_to(self.root)),
            expected=2,
        )
        self.assertIn("requires at least one finding", missing.stderr)

        decision_args = (
            "decide",
            "--gate",
            "readiness_review",
            "--role",
            "engineering",
            "--actor-ref",
            actor_ref,
            "--work-item-id",
            work_item_id,
            "--verdict",
            "reject",
            "--evidence",
            str(evidence.relative_to(self.root)),
            "--finding",
            "blocker:engineering:Implementation cannot satisfy the frozen interface.",
        )
        self.run_tool(*decision_args)
        recorded = json.loads(self.run_tool("status", "--json").stdout)
        revision = recorded["revision"]
        self.assertEqual(1, len(recorded["issues"]))
        issue = recorded["issues"][0]
        self.assertEqual("blocker", issue["severity"])
        self.assertEqual("engineering", issue["owner"])
        self.assertEqual("readiness_review", issue["review_gate"])
        self.assertTrue(issue["stable_key"].startswith("review-finding:"))

        replay = self.run_tool(*decision_args)
        self.assertIn("already recorded", replay.stdout)
        replayed = json.loads(self.run_tool("status", "--json").stdout)
        self.assertEqual(revision, replayed["revision"])
        self.assertEqual(1, len(replayed["issues"]))

    def test_design_artifact_bundle_rewinds_once_and_preserves_complete_baseline(self) -> None:
        self.init("strict")
        self.complete_discovery()
        self.record(
            "prd",
            "requirements/REQ-test-flow/01-prd.md",
            text=(
                "# Product requirements\n\n"
                "## User outcome\n\nDeliver the confirmed workflow behavior.\n\n"
                "## Acceptance criteria\n\nAC-001: The complete user journey works.\n\n"
                "## Exclusions\n\nNo core outcome may be replaced by a mock.\n"
            ),
        )
        self.run_tool(
            "register-acceptance-criteria",
            "--criterion",
            "AC-001=The complete user journey works.",
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
        self.record("test_cases", "requirements/REQ-test-flow/05-test-cases.md")
        self.record("release_plan", "requirements/REQ-test-flow/06-release-plan.md")
        self.run_tool("advance")
        self.approve("readiness_review", ("product", "engineering", "testing"))

        self.run_tool("reopen", "--stage", "design", "--reason", "Replace design baseline")

        bundle_items = []
        artifact_paths: dict[str, Path] = {}
        for name, filename, status, notes in (
            ("technical_design", "03-design-v2.md", "ready", ""),
            (
                "database_design",
                "04-database-v2.md",
                "not_applicable",
                "The revised design still has no persistence changes.",
            ),
            ("test_plan", "05-test-plan-v2.md", "ready", ""),
            ("test_cases", "05-test-cases-v2.md", "ready", ""),
            ("release_plan", "06-release-plan-v2.md", "ready", ""),
        ):
            artifact = self.write_artifact(f"requirements/REQ-test-flow/{filename}")
            artifact_paths[name] = artifact
            bundle_items.append(
                {
                    "name": name,
                    "path": str(artifact.relative_to(self.root)),
                    "status": status,
                    "notes": notes,
                }
            )
        engineering_work, _ = self.complete_role_work(
            "engineering",
            {
                name: artifact_paths[name]
                for name in ("technical_design", "database_design", "release_plan")
            },
        )
        testing_work, _ = self.complete_role_work(
            "testing",
            {
                name: artifact_paths[name]
                for name in ("test_plan", "test_cases")
            },
        )
        for item in bundle_items:
            item["work_item_id"] = (
                testing_work
                if item["name"] in {"test_plan", "test_cases"}
                else engineering_work
            )
        manifest = self.root / "docs" / "requirements" / "REQ-test-flow" / "design-v2.json"
        manifest.write_text(json.dumps({"artifacts": bundle_items}), encoding="utf-8")

        result = self.run_tool(
            "record-artifact-bundle",
            "--manifest",
            str(manifest.relative_to(self.root)),
        )

        self.assertIn("Recorded artifact bundle", result.stdout)
        state = json.loads(self.run_tool("status", "--json").stdout)
        self.assertEqual("design", state["workflow"]["current_stage"])
        self.assertNotIn("readiness_review", state["decisions"])
        self.assertEqual("not_applicable", state["artifacts"]["database_design"]["status"])
        for item in bundle_items:
            self.assertEqual(item["path"], state["artifacts"][item["name"]]["path"])
            self.assertIn(
                state["artifacts"][item["name"]]["status"],
                {"ready", "not_applicable"},
            )
        change_events = [
            event
            for event in state["history"]
            if event["event"] == "reopened"
            and "readiness_review->design" in event["detail"]
        ]
        self.assertEqual(1, len(change_events))

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
        self.confirm_delivery()
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

    def test_invalid_lock_timeout_is_reported_without_traceback(self) -> None:
        env = dict(os.environ)
        env["SDLC_LOCK_TIMEOUT"] = "invalid"
        rejected = self.run_tool(
            "init",
            "--id",
            "REQ-invalid-lock-timeout",
            "--title",
            "Invalid lock timeout",
            "--request",
            "The invalid environment setting should produce a controlled error.",
            expected=2,
            env=env,
        )
        self.assertIn("non-negative finite number", rejected.stderr)
        self.assertNotIn("Traceback", rejected.stderr)


if __name__ == "__main__":
    unittest.main()
