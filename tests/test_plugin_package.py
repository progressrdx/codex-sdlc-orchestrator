from __future__ import annotations

import json
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
            "workflow.py",
            "workflow_cli.py",
            "state_store.py",
            "command_runtime.py",
            "risk_policy.py",
            "risk_commands.py",
            "review_commands.py",
            "assurance_commands.py",
            "delivery_commands.py",
            "source_policy.py",
            "execution_policy.py",
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
        self.assertIn("merely discusses team development", skill)
        self.assertIn("$sdlc-orchestrator", agent)

    def test_active_workflow_hooks_are_packaged(self) -> None:
        hooks = json.loads((PLUGIN / "hooks" / "hooks.json").read_text(encoding="utf-8"))
        self.assertNotIn("UserPromptSubmit", hooks["hooks"])
        self.assertIn("PreToolUse", hooks["hooks"])
        self.assertEqual({"PreToolUse"}, set(hooks["hooks"]))
        self.assertEqual(
            "^(apply_patch|Edit|Write)$",
            hooks["hooks"]["PreToolUse"][0]["matcher"],
        )
        guard = PLUGIN / "hooks" / "workflow_guard.py"
        self.assertTrue(guard.is_file())
        self.assertIn("permissionDecision", guard.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
