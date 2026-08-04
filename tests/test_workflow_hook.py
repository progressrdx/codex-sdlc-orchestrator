from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HOOK = ROOT / "plugins" / "multi-agent-role-work" / "hooks" / "workflow_guard.py"


class WorkflowHookTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()
        state_path = self.root / ".ai-workflow" / "REQ-hook" / "state.yaml"
        state_path.parent.mkdir(parents=True)
        state_path.write_text(
            json.dumps(
                {
                    "workflow": {
                        "id": "REQ-hook",
                        "mode": "strict",
                        "status": "active",
                        "current_stage": "delivery_confirmation",
                    }
                }
            ),
            encoding="utf-8",
        )
        (self.root / ".ai-workflow" / "active.yaml").write_text(
            json.dumps(
                {
                    "workflow_id": "REQ-hook",
                    "state_path": ".ai-workflow/REQ-hook/state.yaml",
                }
            ),
            encoding="utf-8",
        )

    def tearDown(self) -> None:
        self.temp.cleanup()

    def run_hook(self, action: str, payload: dict) -> dict:
        result = subprocess.run(
            [sys.executable, str(HOOK), action],
            input=json.dumps({"cwd": str(self.root), **payload}),
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(0, result.returncode, result.stderr)
        return json.loads(result.stdout) if result.stdout else {}

    def test_product_patch_is_denied_during_delivery_confirmation(self) -> None:
        output = self.run_hook(
            "guard",
            {
                "tool_name": "apply_patch",
                "tool_input": {"command": "*** Begin Patch\n*** Update File: src/app.py\n*** End Patch"},
            },
        )
        decision = output["hookSpecificOutput"]
        self.assertEqual("deny", decision["permissionDecision"])
        self.assertIn("delivery_confirmation", decision["permissionDecisionReason"])

    def test_workflow_evidence_patch_remains_allowed(self) -> None:
        output = self.run_hook(
            "guard",
            {
                "tool_name": "apply_patch",
                "tool_input": {
                    "command": "*** Begin Patch\n*** Add File: docs/requirements/REQ-hook/change.md\n*** End Patch"
                },
            },
        )
        self.assertEqual({}, output)

    def test_product_patch_is_allowed_during_implementation(self) -> None:
        state = self.root / ".ai-workflow" / "REQ-hook" / "state.yaml"
        data = json.loads(state.read_text(encoding="utf-8"))
        data["workflow"]["current_stage"] = "implementation"
        state.write_text(json.dumps(data), encoding="utf-8")
        output = self.run_hook(
            "guard",
            {
                "tool_name": "apply_patch",
                "tool_input": {"command": "*** Begin Patch\n*** Update File: src/app.py\n*** End Patch"},
            },
        )
        self.assertEqual({}, output)

    def test_no_active_workflow_is_a_noop(self) -> None:
        (self.root / ".ai-workflow" / "active.yaml").unlink()
        self.assertEqual({}, self.run_hook("guard", {"tool_input": {}}))

    def test_paused_workflow_denies_product_patch_even_at_implementation(self) -> None:
        state = self.root / ".ai-workflow" / "REQ-hook" / "state.yaml"
        data = json.loads(state.read_text(encoding="utf-8"))
        data["workflow"]["status"] = "paused"
        data["workflow"]["current_stage"] = "implementation"
        state.write_text(json.dumps(data), encoding="utf-8")
        output = self.run_hook(
            "guard",
            {
                "tool_name": "apply_patch",
                "tool_input": {"command": "*** Begin Patch\n*** Update File: src/app.py\n*** End Patch"},
            },
        )
        self.assertEqual("deny", output["hookSpecificOutput"]["permissionDecision"])
        self.assertIn("paused", output["hookSpecificOutput"]["permissionDecisionReason"])


if __name__ == "__main__":
    unittest.main()
