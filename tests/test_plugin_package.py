from __future__ import annotations

import json
import os
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
            2000,
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

        for content in (skill, contract, agent):
            self.assertIn("团队开发", content)
        self.assertIn("ordinary questions", skill)
        self.assertIn("继续团队开发", skill)
        self.assertIn("bare ambiguous 继续", skill)
        self.assertIn("bare “继续” is ordinary conversation", contract)
        self.assertIn("$sdlc-orchestrator", agent)

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

        self.assertEqual("AI Project Manager", manifest["interface"]["displayName"])
        self.assertIn("User-friendly project view", manifest["interface"]["capabilities"])
        self.assertIn("overview --json", skill)
        self.assertIn("Use `project` for user communication", contract)
        self.assertIn('subparsers.add_parser(\n        "project"', cli)

    def test_plugin_does_not_package_lifecycle_hooks(self) -> None:
        self.assertFalse((PLUGIN / "hooks").exists())
        manifest = json.loads(
            (PLUGIN / ".codex-plugin" / "plugin.json").read_text(encoding="utf-8")
        )
        capabilities = manifest["interface"]["capabilities"]
        self.assertNotIn("Active-workflow lifecycle guards", capabilities)
        self.assertIn("Optional external design-skill routing", capabilities)

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

    def test_current_plugin_tree_is_self_contained_after_git_archive(self) -> None:
        """Validate the exact candidate formed from the current plugin worktree.

        The project checkout may contain uncommitted implementation work, so this
        test intentionally creates a clean, temporary commit from ``PLUGIN`` and
        validates the archive of that commit instead of the project's ``HEAD``.
        """
        validator = (
            Path(os.environ.get("CODEX_HOME", Path.home() / ".codex"))
            / "skills"
            / ".system"
            / "skill-creator"
            / "scripts"
            / "quick_validate.py"
        )
        self.assertTrue(validator.is_file(), f"Skill validator unavailable: {validator}")

        with tempfile.TemporaryDirectory() as temporary:
            temp_root = Path(temporary)
            repository = temp_root / "candidate-repository"
            unpacked = temp_root / "unpacked-plugin"
            archive = temp_root / "plugin.tar"
            shutil.copytree(PLUGIN, repository, symlinks=True)

            git_environment = {
                **os.environ,
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
