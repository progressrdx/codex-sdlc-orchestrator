from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any, Callable


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = (
    ROOT
    / "plugins"
    / "multi-agent-role-work"
    / "skills"
    / "sdlc-orchestrator"
    / "scripts"
    / "workflow.py"
)
sys.path.insert(0, str(SCRIPT.parent))
try:
    import workflow as workflow_module
finally:
    sys.path.pop(0)


class LifecycleIntegrityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()

    def tearDown(self) -> None:
        self.temp.cleanup()

    def run_tool(
        self,
        *args: str,
        expected: int = 0,
    ) -> subprocess.CompletedProcess[str]:
        command = [sys.executable, str(SCRIPT), "--root", str(self.root), *args]
        result = subprocess.run(command, text=True, capture_output=True, check=False)
        self.assertEqual(
            expected,
            result.returncode,
            msg=f"command={command}\nstdout={result.stdout}\nstderr={result.stderr}",
        )
        return result

    def init(self, workflow_id: str = "REQ-lifecycle-one", mode: str = "micro") -> None:
        self.run_tool(
            "init",
            "--id",
            workflow_id,
            "--title",
            workflow_id,
            "--mode",
            mode,
            "--request",
            f"Build the bounded requirement {workflow_id}.",
        )

    def state_path(self, workflow_id: str = "REQ-lifecycle-one") -> Path:
        return self.root / ".ai-workflow" / workflow_id / "state.yaml"

    def pointer_path(self) -> Path:
        return self.root / ".ai-workflow" / "active.yaml"

    def state(self, workflow_id: str = "REQ-lifecycle-one") -> dict[str, Any]:
        result = self.run_tool("--id", workflow_id, "status", "--json")
        return json.loads(result.stdout)

    def rewrite_state(
        self,
        update: Callable[[dict[str, Any]], None],
        workflow_id: str = "REQ-lifecycle-one",
    ) -> dict[str, Any]:
        path = self.state_path(workflow_id)
        state = workflow_module.load_data(path)
        update(state)
        state["state_checksum"] = workflow_module.state_checksum(state)
        workflow_module.save_data(path, state)
        return state

    def mark_completed(self, workflow_id: str = "REQ-lifecycle-one") -> None:
        def update(state: dict[str, Any]) -> None:
            state["workflow"]["current_stage"] = "completed"
            state["workflow"]["status"] = "completed"

        self.rewrite_state(update, workflow_id)

    def create_backup(self, workflow_id: str = "REQ-lifecycle-one") -> dict[str, Any]:
        state = workflow_module.load_data(self.state_path(workflow_id))
        workflow_module.save_data(
            self.state_path(workflow_id).with_name("state.backup.yaml"), state
        )
        return state

    def test_reopen_rejects_forward_stage_but_completed_can_explicitly_reopen(self) -> None:
        self.init()
        rejected = self.run_tool(
            "reopen",
            "--stage",
            "verification",
            "--reason",
            "This must not skip the scope and implementation gates.",
            expected=2,
        )
        self.assertIn("cannot move forward", rejected.stderr)
        self.assertEqual("intake", self.state()["workflow"]["current_stage"])

        self.mark_completed()
        self.pointer_path().unlink(missing_ok=True)
        reopened = self.run_tool(
            "--id",
            "REQ-lifecycle-one",
            "reopen",
            "--stage",
            "scope_check",
            "--reason",
            "The user explicitly requested another delivery iteration.",
        )
        self.assertIn("Reopened workflow", reopened.stdout)
        state = self.state()
        self.assertEqual("active", state["workflow"]["status"])
        self.assertEqual("scope_check", state["workflow"]["current_stage"])
        self.assertEqual("REQ-lifecycle-one", workflow_module.load_data(self.pointer_path())["workflow_id"])

    def test_completed_is_immutable_except_for_explicit_reopen(self) -> None:
        self.init()
        self.mark_completed()
        self.pointer_path().unlink(missing_ok=True)
        before = self.state()

        rejected = self.run_tool(
            "--id",
            "REQ-lifecycle-one",
            "add-issue",
            "--source",
            "testing",
            "--severity",
            "minor",
            "--summary",
            "A completed workflow must remain immutable.",
            expected=2,
        )
        self.assertTrue(
            "completed workflow is immutable" in rejected.stderr.lower()
            or "no active workflow" in rejected.stderr.lower()
        )
        after = self.state()
        self.assertEqual(before["revision"], after["revision"])
        self.assertEqual([], after["issues"])

    def test_repair_refuses_to_roll_back_any_valid_lifecycle_state(self) -> None:
        for status in ("active", "completed", "abandoned"):
            with self.subTest(status=status):
                workflow_id = f"REQ-repair-{status}"
                if self.pointer_path().exists():
                    owner = workflow_module.load_data(self.pointer_path())["workflow_id"]
                    self.run_tool(
                        "--id",
                        owner,
                        "deactivate",
                        "--reason",
                        "Prepare an isolated repair-state fixture.",
                    )
                self.init(workflow_id)
                self.create_backup(workflow_id)
                if status == "completed":
                    self.mark_completed(workflow_id)
                    self.pointer_path().unlink(missing_ok=True)
                elif status == "abandoned":
                    self.run_tool(
                        "--id",
                        workflow_id,
                        "abandon",
                        "--reason",
                        "Prepare a valid terminal fixture.",
                    )
                before = self.state_path(workflow_id).read_bytes()
                audit = json.loads(
                    self.run_tool(
                        "--id", workflow_id, "audit-state", "--json"
                    ).stdout
                )
                self.assertTrue(audit["state_valid"])
                self.assertFalse(audit["repair_available"])
                rejected = self.run_tool(
                    "--id",
                    workflow_id,
                    "repair-state",
                    "--from-backup",
                    "--confirm",
                    "RESTORE",
                    expected=2,
                )
                self.assertIn("cannot be used to roll back valid state", rejected.stderr)
                self.assertEqual(before, self.state_path(workflow_id).read_bytes())

    def test_repair_of_corrupt_state_refreshes_provenance_and_pointer(self) -> None:
        self.init()
        backup = self.create_backup()
        path = self.state_path()
        path.write_text("not: [valid\n", encoding="utf-8")

        repaired = self.run_tool(
            "repair-state",
            "--from-backup",
            "--confirm",
            "RESTORE",
        )
        self.assertIn("Restored workflow state", repaired.stdout)
        state = workflow_module.load_data(path)
        workflow_module.verify_state_checksum(
            state, path, workflow_module.CURRENT_SCHEMA_VERSION
        )
        self.assertGreater(state["revision"], backup["revision"])
        self.assertEqual(
            workflow_module.current_tool_identity()["payload_sha256"],
            state["runtime_provenance"]["last_mutated_by_tool"]["payload_sha256"],
        )
        pointer = workflow_module.load_data(self.pointer_path())
        self.assertEqual(state["workflow"]["id"], pointer["workflow_id"])
        self.assertEqual(state["revision"], pointer["state_revision"])
        self.assertEqual(state["workflow"]["status"], pointer["status"])

    def test_repair_fails_closed_if_backup_would_create_two_live_workflows(self) -> None:
        self.init()
        backup = self.create_backup()
        self.run_tool("deactivate", "--reason", "Activate another workflow.")
        self.init("REQ-lifecycle-two")

        path = self.state_path()
        path.write_text("corrupt: [", encoding="utf-8")
        pointer_before = self.pointer_path().read_bytes()
        rejected = self.run_tool(
            "--id",
            "REQ-lifecycle-one",
            "repair-state",
            "--from-backup",
            "--confirm",
            "RESTORE",
            expected=2,
        )
        self.assertIn("already live", rejected.stderr)
        self.assertEqual("corrupt: [", path.read_text(encoding="utf-8"))
        self.assertEqual(pointer_before, self.pointer_path().read_bytes())
        self.assertEqual("active", backup["workflow"]["status"])

    def test_advance_rejects_an_active_work_item_for_current_stage(self) -> None:
        self.init()
        self.run_tool(
            "begin-work",
            "--work-item-id",
            "product-intake-running",
            "--role",
            "product",
            "--actor-ref",
            "product-agent-running",
            "--deadline-at",
            "2099-01-01T00:00:00Z",
        )
        before = self.state()
        blocked = self.run_tool("advance", expected=2)
        self.assertIn("active_work_items:product-intake-running", blocked.stderr)
        after = self.state()
        self.assertEqual(before["revision"], after["revision"])
        self.assertEqual("intake", after["workflow"]["current_stage"])

    def test_stage_and_status_cross_invariant_is_validated(self) -> None:
        self.init()

        def make_inconsistent(state: dict[str, Any]) -> None:
            state["workflow"]["status"] = "completed"

        self.rewrite_state(make_inconsistent)
        rejected = self.run_tool("--id", "REQ-lifecycle-one", "status", expected=2)
        self.assertIn("completed status", rejected.stderr)
        self.assertIn("completed stage", rejected.stderr)

    def test_force_is_fail_closed_and_never_overwrites_or_switches(self) -> None:
        self.init()
        state_before = self.state_path().read_bytes()
        request = self.root / "docs" / "requirements" / "REQ-lifecycle-one" / "00-original-request.md"
        request_before = request.read_bytes()

        same_id = self.run_tool(
            "init",
            "--id",
            "REQ-lifecycle-one",
            "--title",
            "Replacement",
            "--mode",
            "micro",
            "--request",
            "Overwrite the existing workflow.",
            "--force",
            expected=2,
        )
        self.assertIn("--force is disabled", same_id.stderr)
        self.assertEqual(state_before, self.state_path().read_bytes())
        self.assertEqual(request_before, request.read_bytes())

        other_id = self.run_tool(
            "init",
            "--id",
            "REQ-lifecycle-two",
            "--title",
            "Second workflow",
            "--mode",
            "micro",
            "--request",
            "Silently replace the active pointer.",
            "--force",
            expected=2,
        )
        self.assertIn("deactivate or abandon", other_id.stderr)
        self.assertFalse(self.state_path("REQ-lifecycle-two").exists())
        self.assertEqual("REQ-lifecycle-one", workflow_module.load_data(self.pointer_path())["workflow_id"])

    def test_deactivate_activate_abandon_and_list_form_a_closed_lifecycle(self) -> None:
        self.init()
        self.run_tool("deactivate", "--reason", "Work on another requirement first.")
        self.assertFalse(self.pointer_path().exists())
        self.assertEqual("inactive", self.state()["workflow"]["status"])

        self.init("REQ-lifecycle-two")
        conflict = self.run_tool("--id", "REQ-lifecycle-one", "activate", expected=2)
        self.assertIn("REQ-lifecycle-two", conflict.stderr)

        listing = json.loads(self.run_tool("list", "--json").stdout)
        by_id = {item["workflow_id"]: item for item in listing["workflows"]}
        self.assertEqual("inactive", by_id["REQ-lifecycle-one"]["status"])
        self.assertEqual("active", by_id["REQ-lifecycle-two"]["status"])
        self.assertTrue(by_id["REQ-lifecycle-two"]["is_active_pointer"])

        self.run_tool("deactivate", "--reason", "Return to the first requirement.")
        self.run_tool("--id", "REQ-lifecycle-one", "activate")
        pointer = workflow_module.load_data(self.pointer_path())
        active = self.state()
        self.assertEqual("REQ-lifecycle-one", pointer["workflow_id"])
        self.assertEqual(active["revision"], pointer["state_revision"])

        self.run_tool("abandon", "--reason", "The user cancelled this requirement.")
        self.assertFalse(self.pointer_path().exists())
        abandoned = self.state()
        self.assertEqual("abandoned", abandoned["workflow"]["status"])
        abandoned_before = self.state_path().read_bytes()
        blocked = self.run_tool(
            "--id",
            "REQ-lifecycle-one",
            "add-issue",
            "--source",
            "testing",
            "--severity",
            "minor",
            "--summary",
            "Terminal state should not accept mutations.",
            expected=2,
        )
        self.assertTrue(
            "abandoned workflow is immutable" in blocked.stderr.lower()
            or "no active workflow" in blocked.stderr.lower()
        )
        self.assertEqual(abandoned_before, self.state_path().read_bytes())

    def test_pointer_validates_identity_revision_status_and_reconciles_stale_terminal(self) -> None:
        self.init()
        state = self.state()
        pointer = workflow_module.load_data(self.pointer_path())
        self.assertEqual("REQ-lifecycle-one", pointer["workflow_id"])
        self.assertEqual("active", pointer["status"])
        self.assertEqual(state["revision"], pointer["state_revision"])

        pointer["state_revision"] = 0
        workflow_module.save_data(self.pointer_path(), pointer)
        self.run_tool("status")
        reconciled = workflow_module.load_data(self.pointer_path())
        self.assertEqual(state["revision"], reconciled["state_revision"])

        pointer = dict(reconciled)
        pointer["workflow_id"] = "REQ-wrong-owner"
        workflow_module.save_data(self.pointer_path(), pointer)
        mismatch = self.run_tool("status", expected=2)
        self.assertIn("does not match workflow_id", mismatch.stderr)

        pointer["workflow_id"] = "REQ-lifecycle-one"
        workflow_module.save_data(self.pointer_path(), pointer)
        self.mark_completed()
        no_active = self.run_tool("status", expected=2)
        self.assertIn("No active workflow", no_active.stderr)
        self.assertFalse(self.pointer_path().exists())

    def test_pointer_owner_cas_does_not_remove_another_workflow(self) -> None:
        self.init()
        self.run_tool("deactivate", "--reason", "Temporarily inactive.")
        self.init("REQ-lifecycle-two")
        self.run_tool(
            "--id",
            "REQ-lifecycle-one",
            "abandon",
            "--reason",
            "Cancel only the inactive first workflow.",
        )
        pointer = workflow_module.load_data(self.pointer_path())
        self.assertEqual("REQ-lifecycle-two", pointer["workflow_id"])

    def test_missing_pointer_recovers_the_unique_live_workflow(self) -> None:
        self.init()
        expected = self.state()
        self.pointer_path().unlink()

        recovered = json.loads(self.run_tool("status", "--json").stdout)
        pointer = workflow_module.load_data(self.pointer_path())
        self.assertEqual(expected["workflow"]["id"], recovered["workflow"]["id"])
        self.assertEqual("REQ-lifecycle-one", pointer["workflow_id"])
        self.assertEqual(recovered["revision"], pointer["state_revision"])
        self.assertEqual("active", pointer["status"])

        self.run_tool("pause", "--reason", "Verify paused recovery as well.")
        self.pointer_path().unlink()
        self.run_tool("resume")
        resumed = self.state()
        pointer = workflow_module.load_data(self.pointer_path())
        self.assertEqual("active", resumed["workflow"]["status"])
        self.assertEqual(resumed["revision"], pointer["state_revision"])

    def test_multiple_live_workflows_fail_closed_without_choosing_an_owner(self) -> None:
        self.init()
        self.run_tool("deactivate", "--reason", "Create a second lifecycle fixture.")
        self.init("REQ-lifecycle-two")

        def make_live(state: dict[str, Any]) -> None:
            state["workflow"]["status"] = "active"
            state["workflow"].pop("deactivated_at", None)
            state["workflow"].pop("deactivation_reason", None)

        self.rewrite_state(make_live)
        pointer_before = self.pointer_path().read_bytes()
        rejected = self.run_tool("status", expected=2)
        self.assertIn("Multiple live workflows", rejected.stderr)
        self.assertEqual(pointer_before, self.pointer_path().read_bytes())

        init_rejected = self.run_tool(
            "init",
            "--id",
            "REQ-lifecycle-three",
            "--title",
            "Third workflow",
            "--mode",
            "micro",
            "--request",
            "A third workflow must not hide the lifecycle conflict.",
            expected=2,
        )
        self.assertIn("Multiple live workflows", init_rejected.stderr)
        self.assertFalse(self.state_path("REQ-lifecycle-three").exists())

    def test_activate_reopen_and_resume_conflicts_do_not_mutate_target_state(self) -> None:
        self.init()
        self.run_tool("deactivate", "--reason", "Activate another workflow.")
        self.init("REQ-lifecycle-two")

        inactive_before = self.state_path().read_bytes()
        activate = self.run_tool("--id", "REQ-lifecycle-one", "activate", expected=2)
        self.assertIn("REQ-lifecycle-two", activate.stderr)
        self.assertEqual(inactive_before, self.state_path().read_bytes())

        self.mark_completed()
        completed_before = self.state_path().read_bytes()
        reopen = self.run_tool(
            "--id",
            "REQ-lifecycle-one",
            "reopen",
            "--stage",
            "scope_check",
            "--reason",
            "This must fail before changing the completed state.",
            expected=2,
        )
        self.assertIn("REQ-lifecycle-two", reopen.stderr)
        self.assertEqual(completed_before, self.state_path().read_bytes())

        def make_paused(state: dict[str, Any]) -> None:
            state["workflow"]["status"] = "paused"
            state["workflow"]["current_stage"] = "intake"
            state["workflow"].pop("completed_at", None)
            state["workflow"]["paused_at"] = "2026-08-13T00:00:00+00:00"
            state["workflow"]["pause_reason"] = "Crash-recovery fixture."

        self.rewrite_state(make_paused)
        paused_before = self.state_path().read_bytes()
        resume = self.run_tool("--id", "REQ-lifecycle-one", "resume", expected=2)
        self.assertIn("Multiple live workflows", resume.stderr)
        self.assertEqual(paused_before, self.state_path().read_bytes())

    def test_overview_and_next_prioritize_lifecycle_state(self) -> None:
        self.init()
        self.run_tool("pause", "--reason", "Awaiting an explicit continuation request.")
        paused = json.loads(self.run_tool("overview", "--json").stdout)
        self.assertFalse(paused["can_advance"])
        self.assertEqual("paused", paused["status"])
        self.assertEqual("Resume this workflow before continuing.", paused["next_action"])
        self.assertEqual([], paused["stage_missing_after_resume"])
        next_result = self.run_tool("next")
        self.assertIn("Workflow is paused", next_result.stdout)
        self.assertNotIn("Ready to advance", next_result.stdout)

        self.run_tool("deactivate", "--reason", "Switch requirements.")
        inactive = json.loads(
            self.run_tool("--id", "REQ-lifecycle-one", "overview", "--json").stdout
        )
        self.assertEqual("Activate this workflow before continuing.", inactive["next_action"])
        self.assertFalse(inactive["can_advance"])

        self.mark_completed()
        completed = json.loads(
            self.run_tool("--id", "REQ-lifecycle-one", "overview", "--json").stdout
        )
        self.assertEqual("No next workflow action is required.", completed["next_action"])
        self.assertFalse(completed["can_advance"])

    def test_quick_flow_has_unique_stages(self) -> None:
        self.init(mode="quick")
        stages = self.state()["workflow"]["flow_stages"]
        self.assertEqual(len(stages), len(set(stages)))
        self.assertEqual(1, stages.count("clarification"))


if __name__ == "__main__":
    unittest.main()
