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
        }
        self.assertTrue(required_modules.issubset({path.name for path in scripts.glob("*.py")}))
        workflow_lines = (scripts / "workflow.py").read_text(encoding="utf-8").splitlines()
        self.assertLess(
            len(workflow_lines),
            2000,
            "workflow.py should remain a shared rules/facade module, not absorb command groups",
        )


if __name__ == "__main__":
    unittest.main()
