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


if __name__ == "__main__":
    unittest.main()
