from __future__ import annotations

import hashlib
import os
import subprocess
import sys
import tempfile
import time
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = (
    ROOT
    / "plugins"
    / "multi-agent-role-work"
    / "skills"
    / "sdlc-orchestrator"
    / "scripts"
)
SCRIPT = SCRIPTS / "workflow.py"
sys.path.insert(0, str(SCRIPTS))

from state_store import load_data, workflow_lock  # noqa: E402
from state_store import WorkflowError  # noqa: E402
from work_commands import current_input_hashes, require_completed_output  # noqa: E402
from work_items import supersede_work_item  # noqa: E402
import workflow as workflow_module  # noqa: E402


class WorkItemCliTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()
        self.run_cli(
            "init",
            "--id",
            "REQ-work-items",
            "--title",
            "Work item CLI",
            "--mode",
            "standard",
            "--request",
            "Verify persisted role work attempts.",
        )

    def tearDown(self) -> None:
        self.temp.cleanup()

    @property
    def state_path(self) -> Path:
        return self.root / ".ai-workflow" / "REQ-work-items" / "state.yaml"

    def state(self) -> dict:
        return load_data(self.state_path)

    def run_cli(
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

    def deadline(self, seconds: int = 120) -> str:
        return (
            datetime.now(timezone.utc) + timedelta(seconds=seconds)
        ).replace(microsecond=0).isoformat().replace("+00:00", "Z")

    def begin(
        self,
        work_item_id: str,
        *,
        lease_seconds: int = 60,
        override: Path | None = None,
        expected: int = 0,
    ) -> subprocess.CompletedProcess[str]:
        return self.run_cli(
            "begin-work",
            "--work-item-id",
            work_item_id,
            "--role",
            "product",
            "--actor-ref",
            f"agent:{work_item_id}",
            "--deadline-at",
            self.deadline(),
            "--lease-seconds",
            str(lease_seconds),
            *(
                ("--override-evidence", str(override.relative_to(self.root)))
                if override
                else ()
            ),
            expected=expected,
        )

    def output(self, name: str = "result.md") -> Path:
        path = self.root / "docs" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("# Result\n\nThe completed role output.\n", encoding="utf-8")
        return path

    def test_begin_captures_nonempty_original_request_baseline(self) -> None:
        self.begin("WI-intake-product-001")

        state = self.state()
        item = state["work_items"]["WI-intake-product-001"]
        original = state["artifacts"]["original_request"]["evidence_sha256"]
        self.assertEqual("intake", item["stage"])
        self.assertEqual("product", item["role"])
        self.assertEqual(
            original,
            item["input_hashes"]["artifact:original_request"],
        )
        self.assertTrue(item["input_hashes"])
        self.assertEqual(1, item["input_revision"])

    def test_heartbeat_and_complete_persist_transition_and_output_hash(self) -> None:
        self.begin("WI-intake-product-001")
        self.run_cli(
            "heartbeat-work",
            "--work-item-id",
            "WI-intake-product-001",
            "--lease-seconds",
            "90",
        )
        output = self.output()
        self.run_cli(
            "complete-work",
            "--work-item-id",
            "WI-intake-product-001",
            "--output",
            f"brief={output.relative_to(self.root)}",
        )

        item = self.state()["work_items"]["WI-intake-product-001"]
        self.assertEqual("completed", item["status"])
        self.assertEqual(1, item["heartbeat_count"])
        self.assertEqual(90, item["lease_seconds"])
        self.assertEqual(
            hashlib.sha256(output.read_bytes()).hexdigest(),
            item["output_hashes"]["brief"],
        )
        self.assertEqual("docs/result.md", item["output_paths"]["brief"])

        checked = require_completed_output(
            self.root,
            self.state(),
            "WI-intake-product-001",
            "intake",
            "product",
            "brief",
            item["output_hashes"]["brief"],
            str(output.relative_to(self.root)),
        )
        self.assertEqual("completed", checked["status"])
        self.assertIn(
            "artifact:original_request",
            current_input_hashes(self.root, self.state()),
        )

        same_bytes = self.root / "docs" / "same-bytes.md"
        same_bytes.write_bytes(output.read_bytes())
        with self.assertRaises(WorkflowError):
            require_completed_output(
                self.root,
                self.state(),
                "WI-intake-product-001",
                "intake",
                "product",
                "brief",
                item["output_hashes"]["brief"],
                str(same_bytes.relative_to(self.root)),
            )

        output.write_text("changed after completion\n", encoding="utf-8")
        with self.assertRaises(WorkflowError):
            require_completed_output(
                self.root,
                self.state(),
                "WI-intake-product-001",
                "intake",
                "product",
                "brief",
                item["output_hashes"]["brief"],
                str(output.relative_to(self.root)),
            )

    def test_cancel_and_timeout_are_enforced_terminal_transitions(self) -> None:
        self.begin("WI-intake-product-001")
        self.run_cli(
            "cancel-work",
            "--work-item-id",
            "WI-intake-product-001",
            "--reason",
            "No longer needed.",
        )
        output = self.output()
        failed = self.run_cli(
            "complete-work",
            "--work-item-id",
            "WI-intake-product-001",
            "--output",
            f"brief={output.relative_to(self.root)}",
            expected=2,
        )
        self.assertIn("cancelled", failed.stderr)

        self.begin("WI-intake-product-002", lease_seconds=1)
        item = self.state()["work_items"]["WI-intake-product-002"]
        expiry = datetime.fromisoformat(item["lease_expires_at"].replace("Z", "+00:00"))
        while datetime.now(timezone.utc) < expiry:
            time.sleep(0.03)
        self.run_cli(
            "timeout-work",
            "--work-item-id",
            "WI-intake-product-002",
            "--reason",
            "Lease expired.",
        )
        self.assertEqual(
            "timed_out",
            self.state()["work_items"]["WI-intake-product-002"]["status"],
        )

    def test_fail_work_records_the_declared_terminal_status(self) -> None:
        self.begin("WI-intake-product-001")

        self.run_cli(
            "fail-work",
            "--work-item-id",
            "WI-intake-product-001",
            "--reason",
            "The delegated role failed its execution.",
        )

        item = self.state()["work_items"]["WI-intake-product-001"]
        self.assertEqual("failed", item["status"])
        self.assertEqual(
            "The delegated role failed its execution.", item["terminal_reason"]
        )

    def test_stage_handoff_budget_requires_repository_override_evidence(self) -> None:
        for number in range(1, 4):
            self.begin(f"WI-intake-product-{number:03d}")

        failed = self.begin("WI-intake-product-004", expected=2)
        self.assertIn("handoff budget exhausted", failed.stderr)
        self.assertNotIn("WI-intake-product-004", self.state()["work_items"])

        override = self.root / "docs" / "handoff-override.md"
        override.parent.mkdir(parents=True, exist_ok=True)
        override.write_text("Approved additional role handoff.\n", encoding="utf-8")
        self.begin("WI-intake-product-004", override=override)
        recorded = self.state()["work_items"]["WI-intake-product-004"]
        self.assertEqual(
            "docs/handoff-override.md",
            recorded["handoff_budget_override"]["path"],
        )
        self.assertEqual(
            hashlib.sha256(override.read_bytes()).hexdigest(),
            recorded["handoff_budget_override"]["evidence_sha256"],
        )

    def test_visual_direction_supports_three_role_design_handoff(self) -> None:
        state = self.state()
        state["workflow"]["current_stage"] = "design"
        workflow_module.save_state(self.state_path, state)

        self.begin("WI-design-product-001")
        direction = self.output("visual-direction.md")
        self.run_cli(
            "complete-work",
            "--work-item-id",
            "WI-design-product-001",
            "--output",
            f"visual_direction={direction.relative_to(self.root)}",
        )
        product_item = self.state()["work_items"]["WI-design-product-001"]
        direction_hash = hashlib.sha256(direction.read_bytes()).hexdigest()
        self.assertEqual(direction_hash, product_item["output_hashes"]["visual_direction"])
        require_completed_output(
            self.root,
            self.state(),
            "WI-design-product-001",
            "design",
            "product",
            "visual_direction",
            direction_hash,
            str(direction.relative_to(self.root)),
        )

        for role in ("engineering", "testing"):
            self.run_cli(
                "begin-work",
                "--work-item-id",
                f"WI-design-{role}-001",
                "--role",
                role,
                "--actor-ref",
                f"agent:design-{role}",
                "--deadline-at",
                self.deadline(),
            )
        self.assertEqual(3, len(self.state()["work_items"]))
        self.assertTrue(
            all("handoff_budget_override" not in item for item in self.state()["work_items"].values())
        )

        direction.write_text("changed visual direction\n", encoding="utf-8")
        with self.assertRaises(WorkflowError):
            require_completed_output(
                self.root,
                self.state(),
                "WI-design-product-001",
                "design",
                "product",
                "visual_direction",
                direction_hash,
                str(direction.relative_to(self.root)),
            )

    def test_superseded_history_does_not_permanently_consume_handoff_budget(self) -> None:
        for number in range(1, 4):
            self.begin(f"WI-intake-product-{number:03d}")
        state = self.state()
        state["work_items"]["WI-intake-product-001"] = supersede_work_item(
            state["work_items"]["WI-intake-product-001"],
            at=datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
            reason="The input baseline was replaced.",
            superseded_by_revision=state["revision"] + 1,
        )
        workflow_module.save_state(self.state_path, state)

        result = self.begin("WI-intake-product-004")

        self.assertIn("Dispatched WI-intake-product-004", result.stdout)

    def test_work_item_mutation_obeys_the_shared_workflow_lock(self) -> None:
        environment = os.environ.copy()
        environment["SDLC_LOCK_TIMEOUT"] = "0"
        with workflow_lock(self.root):
            blocked = self.run_cli(
                "begin-work",
                "--work-item-id",
                "WI-intake-product-001",
                "--role",
                "product",
                "--actor-ref",
                "agent:locked-work",
                "--deadline-at",
                self.deadline(),
                env=environment,
                expected=2,
            )
        self.assertIn("Another workflow update is in progress", blocked.stderr)
        self.assertNotIn("WI-intake-product-001", self.state()["work_items"])


if __name__ == "__main__":
    unittest.main()
