from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "plugins" / "multi-agent-role-work"


class PluginPackageTests(unittest.TestCase):
    def test_role_guidance_links_resolve_inside_packaged_plugin(self) -> None:
        """Packaged reference reachability, not a test of professional judgment."""
        references = {
            "sdlc-product": "interface-judgment.md",
            "sdlc-engineering": "engineering-judgment.md",
            "sdlc-testing": "verification-judgment.md",
            "sdlc-review": "review-judgment.md",
            "sdlc-orchestrator": "coordination-judgment.md",
        }
        for skill, reference in references.items():
            root = PLUGIN / "skills" / skill
            pending = [root / "SKILL.md"]
            visited = set()
            while pending:
                source = pending.pop().resolve()
                if source in visited:
                    continue
                visited.add(source)
                for link in re.findall(r"\[[^\]]*\]\(([^\s)]+)\)", source.read_text(encoding="utf-8")):
                    if "://" in link or link.startswith("#"):
                        continue
                    target = (source.parent / link.split("#", 1)[0]).resolve()
                    with self.subTest(skill=skill, source=source.name, link=link):
                        self.assertTrue(target.is_relative_to(PLUGIN.resolve()))
                        self.assertTrue(target.is_file(), f"Missing packaged reference: {link}")
                    if target.is_file() and target.suffix == ".md":
                        pending.append(target)
            with self.subTest(skill=skill, reference=reference):
                self.assertIn((root / "references" / reference).resolve(), visited)

    def test_manifest_and_marketplace_paths_are_consistent(self) -> None:
        manifest = json.loads(
            (PLUGIN / ".codex-plugin" / "plugin.json").read_text(encoding="utf-8")
        )
        marketplace = json.loads(
            (ROOT / ".agents" / "plugins" / "marketplace.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(PLUGIN.name, manifest["name"])
        entry = next(
            item
            for item in marketplace["plugins"]
            if item["name"] == manifest["name"]
        )
        self.assertEqual("./plugins/multi-agent-role-work", entry["source"]["path"])
        self.assertEqual("AVAILABLE", entry["policy"]["installation"])

    def test_all_required_skills_are_packaged(self) -> None:
        required = {
            "sdlc-orchestrator",
            "sdlc-product",
            "sdlc-engineering",
            "sdlc-testing",
            "sdlc-review",
        }
        found = {
            path.parent.name
            for path in (PLUGIN / "skills").glob("*/SKILL.md")
            if path.read_text(encoding="utf-8").startswith("---\n")
        }
        self.assertEqual(required, found)

    def test_workflow_command_architecture_stays_modular(self) -> None:
        scripts = PLUGIN / "skills" / "sdlc-orchestrator" / "scripts"
        required_modules = {
            "artifact_commands.py",
            "archive_commands.py",
            "workflow.py",
            "workflow_cli.py",
            "state_store.py",
            "command_runtime.py",
            "delivery_candidate.py",
            "risk_policy.py",
            "risk_commands.py",
            "review_commands.py",
            "assurance_commands.py",
            "delivery_commands.py",
            "lifecycle_commands.py",
            "runtime_provenance.py",
            "source_policy.py",
            "stage_submission.py",
            "execution_policy.py",
            "work_commands.py",
            "work_items.py",
        }
        self.assertTrue(required_modules.issubset({path.name for path in scripts.glob("*.py")}))
        workflow_lines = (scripts / "workflow.py").read_text(encoding="utf-8").splitlines()
        self.assertLess(
            len(workflow_lines),
            2050,
            "workflow.py should remain a shared rules/facade module, not absorb command groups",
        )

    def test_natural_language_entrypoint_is_packaged(self) -> None:
        orchestrator = PLUGIN / "skills" / "sdlc-orchestrator"
        skill = (orchestrator / "SKILL.md").read_text(encoding="utf-8")
        contract = (orchestrator / "references" / "workflow-contract.md").read_text(
            encoding="utf-8"
        )
        agent = (orchestrator / "agents" / "openai.yaml").read_text(
            encoding="utf-8"
        )

        for content in (skill, contract):
            self.assertIn("开始一个新项目", content)
        self.assertIn("开启一个新项目", agent)
        self.assertIn("开启一个新项目", skill)
        self.assertIn("创建新项目", skill)
        self.assertIn("### Project Compass", skill)
        self.assertIn("项目守航已开启", contract)
        self.assertIn("allow_implicit_invocation: true", agent)
        self.assertIn("团队开发", skill)
        self.assertIn("ordinary questions", skill)
        self.assertIn("every project follow-up", skill)
        self.assertIn("ordinary-sounding questions", contract)
        self.assertIn("继续推进当前项目", skill)
        self.assertIn("A bare “继续” remains ordinary conversation only when", skill)
        self.assertIn("a bare “继续” neither invokes the workflow", contract)
        self.assertIn("$sdlc-orchestrator", skill)
        self.assertIn("activation text exactly once", contract)
        self.assertIn("persistent Project Compass result card", contract)
        self.assertIn("commentary may collapse", contract)
        self.assertIn("Continue through safe internal steps", contract)
        self.assertIn("language of the original project request", contract)
        self.assertIn("safely initializes Git", contract)
        self.assertIn("check-review-evidence", skill)
        self.assertIn("prepare-turn --json", skill)
        self.assertIn("archive-documents", skill)
        self.assertIn("_archive/<change-or-archive-id>", skill)
        self.assertIn("Archived documents are history only", skill)
        self.assertIn("Fail closed", skill)

    def test_project_compass_keeps_qa_automation_owned_by_the_plugin(self) -> None:
        orchestrator = PLUGIN / "skills" / "sdlc-orchestrator"
        skill = (orchestrator / "SKILL.md").read_text(encoding="utf-8")
        contract = (orchestrator / "references" / "workflow-contract.md").read_text(
            encoding="utf-8"
        )
        testing = (PLUGIN / "skills" / "sdlc-testing" / "SKILL.md").read_text(
            encoding="utf-8"
        )

        self.assertIn("`自动验证`, `需要授权`, or `主观验收`", skill)
        self.assertIn("automatic verification", contract.lower())
        self.assertIn("subjective acceptance", contract.lower())
        self.assertIn("`automatic verification`", testing)
        self.assertIn("`subjective acceptance`", testing)
        self.assertIn("media decoding/playback", testing)
        self.assertIn("Do not ask the user to perform them", testing)
        self.assertIn("never substitutes user labor for QA", contract)

    def test_user_facing_project_view_is_the_default_product_surface(self) -> None:
        orchestrator = PLUGIN / "skills" / "sdlc-orchestrator"
        skill = (orchestrator / "SKILL.md").read_text(encoding="utf-8")
        contract = (orchestrator / "references" / "workflow-contract.md").read_text(
            encoding="utf-8"
        )
        cli = (orchestrator / "scripts" / "workflow_cli.py").read_text(
            encoding="utf-8"
        )
        manifest = json.loads(
            (PLUGIN / ".codex-plugin" / "plugin.json").read_text(encoding="utf-8")
        )

        self.assertEqual("Project Compass", manifest["interface"]["displayName"])
        self.assertIn(
            "Shows whether the project is still on track",
            manifest["interface"]["capabilities"],
        )
        self.assertIn("overview --json", skill)
        self.assertIn("Use `project` for user communication", contract)
        self.assertIn('subparsers.add_parser(\n        "project"', cli)
        self.assertIn('subparsers.add_parser(\n        "prepare-turn"', cli)
        self.assertIn('subparsers.add_parser(\n        "archive-documents"', cli)
        self.assertIn(
            "Keeps active-project follow-ups visibly routed",
            manifest["interface"]["capabilities"],
        )
        self.assertIn(
            "Archives superseded documents without losing history",
            manifest["interface"]["capabilities"],
        )

    def test_plugin_does_not_package_lifecycle_hooks(self) -> None:
        self.assertFalse((PLUGIN / "hooks").exists())
        manifest = json.loads(
            (PLUGIN / ".codex-plugin" / "plugin.json").read_text(encoding="utf-8")
        )
        capabilities = manifest["interface"]["capabilities"]
        self.assertNotIn("Active-workflow lifecycle guards", capabilities)
        self.assertIn("Flags changes that could shift the outcome", capabilities)

    def test_roles_document_optional_design_skill_handoffs(self) -> None:
        product = (PLUGIN / "skills" / "sdlc-product" / "SKILL.md").read_text(
            encoding="utf-8"
        )
        engineering = (PLUGIN / "skills" / "sdlc-engineering" / "SKILL.md").read_text(
            encoding="utf-8"
        )
        testing = (PLUGIN / "skills" / "sdlc-testing" / "SKILL.md").read_text(
            encoding="utf-8"
        )
        self.assertIn("$product-design:ideate", product)
        self.assertIn("$product-design:image-to-code", engineering)
        self.assertIn("$product-design:audit", testing)
        self.assertIn("$web-design-guidelines", testing)
        for content in (product, engineering, testing):
            self.assertIn("available in the current runtime", content)
        self.assertIn("ordinary frontend implementation", engineering)
        self.assertIn("supplemental evidence", testing)

    def test_roles_package_professional_practice_and_review_lenses(self) -> None:
        role_expectations = {
            "sdlc-product": (
                "references/professional-practice.md",
                ("Problem framing and discovery", "Product model", "Metrics and learning"),
            ),
            "sdlc-engineering": (
                "references/professional-practice.md",
                ("Repository and change diagnosis", "Contracts and data", "Delivery evidence"),
            ),
            "sdlc-testing": (
                "references/professional-practice.md",
                ("Risk model", "Test technique selection", "Oracles and evidence"),
            ),
        }

        for skill_name, (relative_reference, required_sections) in role_expectations.items():
            skill_root = PLUGIN / "skills" / skill_name
            skill = (skill_root / "SKILL.md").read_text(encoding="utf-8")
            self.assertIn("professional-practice.md", skill)
            self.assertIn("Professional quality bar", skill)
            reference = (skill_root / relative_reference).read_text(encoding="utf-8")
            for section in required_sections:
                self.assertIn(section, reference)

        review_root = PLUGIN / "skills" / "sdlc-review"
        review_skill = (review_root / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("role-review-lenses.md", review_skill)
        review_lenses = (
            review_root / "references" / "role-review-lenses.md"
        ).read_text(encoding="utf-8")
        for role_lens in ("Product lens", "Engineering lens", "Testing lens"):
            self.assertIn(role_lens, review_lenses)

    def test_visual_capability_chain_is_packaged_and_routed(self) -> None:
        orchestrator = PLUGIN / "skills" / "sdlc-orchestrator"
        orchestrator_skill = (orchestrator / "SKILL.md").read_text(encoding="utf-8")
        routing = (
            orchestrator / "references" / "visual-capability-routing.md"
        ).read_text(encoding="utf-8")
        self.assertIn("visual-capability-routing.md", orchestrator_skill)
        self.assertIn("visual-direction output", orchestrator_skill)
        self.assertIn("visual_direction=<path>", routing)
        self.assertIn("Missing optional Skills never block", routing)

        expected = {
            "sdlc-product": (
                "references/visual-direction.md",
                "assets/visual-direction-template.md",
                "$product-design:ideate",
            ),
            "sdlc-engineering": (
                "references/visual-prototype.md",
                "assets/prototype-evidence-template.md",
                "$frontend-design",
            ),
            "sdlc-testing": (
                "references/visual-quality.md",
                "assets/verification-report-template.md",
                "$product-design:audit",
            ),
        }
        for skill_name, (reference, asset, optional_skill) in expected.items():
            root = PLUGIN / "skills" / skill_name
            skill = (root / "SKILL.md").read_text(encoding="utf-8")
            self.assertTrue((root / reference).is_file())
            self.assertTrue((root / asset).is_file())
            self.assertIn(Path(reference).name, skill)
            self.assertIn(optional_skill, skill)

    def test_current_plugin_tree_is_self_contained_after_git_archive(self) -> None:
        """Validate the exact candidate formed from the current plugin worktree.

        The project checkout may contain uncommitted implementation work, so this
        test intentionally creates a clean, temporary commit from ``PLUGIN`` and
        validates the archive of that commit instead of the project's ``HEAD``.
        """
        validator = ROOT / "tools" / "validate_skill.py"
        self.assertTrue(validator.is_file(), f"Skill validator unavailable: {validator}")

        with tempfile.TemporaryDirectory() as temporary:
            temp_root = Path(temporary)
            repository = temp_root / "candidate-repository"
            unpacked = temp_root / "unpacked-plugin"
            archive = temp_root / "plugin.tar"
            shutil.copytree(PLUGIN, repository, symlinks=True)

            git_environment = {
                **os.environ,
                # Prove the archived package does not require a Codex install.
                "CODEX_HOME": str(temp_root / "no-codex-installation"),
                "GIT_AUTHOR_NAME": "Plugin Package Test",
                "GIT_AUTHOR_EMAIL": "plugin-package-test@example.invalid",
                "GIT_COMMITTER_NAME": "Plugin Package Test",
                "GIT_COMMITTER_EMAIL": "plugin-package-test@example.invalid",
            }

            def run(
                command: list[str],
                *,
                cwd: Path = repository,
                check: bool = True,
            ) -> subprocess.CompletedProcess[str]:
                return subprocess.run(
                    command,
                    cwd=cwd,
                    env=git_environment,
                    check=check,
                    capture_output=True,
                    text=True,
                )

            run(["git", "init", "--quiet"])
            run(["git", "add", "--all"])
            run(["git", "commit", "--quiet", "-m", "Package candidate"])
            run(["git", "archive", "--format=tar", "--output", str(archive), "HEAD"])

            unpacked.mkdir()
            with tarfile.open(archive, mode="r:") as bundle:
                members = bundle.getmembers()
                for member in members:
                    path = Path(member.name)
                    self.assertFalse(path.is_absolute())
                    self.assertNotIn("..", path.parts)
                bundle.extractall(unpacked)

            self.assertFalse((unpacked / ".git").exists())
            skill_files = sorted((unpacked / "skills").glob("*/SKILL.md"))
            self.assertTrue(skill_files, "Archived plugin contains no Skills")
            for skill_file in skill_files:
                validated = run(
                    [sys.executable, str(validator), str(skill_file.parent)],
                    cwd=unpacked,
                    check=False,
                )
                self.assertEqual(
                    0,
                    validated.returncode,
                    f"{skill_file.parent.name} failed validation:\n"
                    f"{validated.stdout}{validated.stderr}",
                )

            workflow = (
                unpacked
                / "skills"
                / "sdlc-orchestrator"
                / "scripts"
                / "workflow.py"
            )
            help_result = run(
                [sys.executable, str(workflow), "--help"],
                cwd=unpacked,
                check=False,
            )
            self.assertEqual(
                0,
                help_result.returncode,
                f"Archived workflow entrypoint failed:\n{help_result.stderr}",
            )

            version_result = run(
                [
                    sys.executable,
                    str(workflow),
                    "version",
                    "--runtime-root",
                    str(unpacked),
                    "--json",
                ],
                cwd=unpacked,
                check=False,
            )
            self.assertEqual(
                0,
                version_result.returncode,
                f"Archived workflow version failed:\n{version_result.stderr}",
            )
            identity = json.loads(version_result.stdout)
            manifest = json.loads(
                (unpacked / ".codex-plugin" / "plugin.json").read_text(encoding="utf-8")
            )
            self.assertEqual(manifest["name"], identity["plugin_name"])
            self.assertEqual(manifest["version"], identity["version"])
            self.assertEqual(str(unpacked.resolve()), identity["runtime_root"])
            self.assertRegex(identity["payload_sha256"], r"^[0-9a-f]{64}$")

            provenance = unpacked / ".codex-plugin" / "provenance.json"
            if provenance.exists():
                provenance_script = workflow.parent / "runtime_provenance.py"
                checked = run(
                    [
                        sys.executable,
                        str(provenance_script),
                        "doctor",
                        "--runtime-root",
                        str(unpacked),
                        "--source-root",
                        str(unpacked),
                    ],
                    cwd=unpacked,
                    check=False,
                )
                self.assertEqual(
                    0,
                    checked.returncode,
                    f"Archived provenance failed validation:\n"
                    f"{checked.stdout}{checked.stderr}",
                )
                self.assertEqual("OK", json.loads(checked.stdout)["status"])

if __name__ == "__main__":
    unittest.main()
