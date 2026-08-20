from __future__ import annotations

import sys
import unittest
from pathlib import Path


SCRIPTS = (
    Path(__file__).resolve().parents[1]
    / "plugins"
    / "multi-agent-role-work"
    / "skills"
    / "sdlc-orchestrator"
    / "scripts"
)
sys.path.insert(0, str(SCRIPTS))

from risk_policy import (  # noqa: E402
    combined_risk_flags,
    recommended_mode_for,
    risk_scope_key,
)


class RiskScopingTests(unittest.TestCase):
    def test_capability_risk_does_not_escalate_unrelated_product_workflow(self) -> None:
        state = {
            "risk_assessment": {"flags": ["user_visible"]},
            "risk_reports": [
                {
                    "id": "RSK-001",
                    "status": "recorded",
                    "scope_kind": "capability",
                    "affected_scope": "paid-advertising",
                    "flags": ["production_release", "irreversible"],
                },
                {
                    "id": "RSK-002",
                    "status": "recorded",
                    "scope_kind": "workflow",
                    "affected_scope": "web-app",
                    "flags": ["cross_module"],
                },
            ],
        }

        self.assertEqual(
            ["user_visible", "cross_module"],
            combined_risk_flags(state),
        )

    def test_stage_and_workflow_risks_both_participate_in_escalation(self) -> None:
        state = {
            "risk_assessment": {"flags": ["user_visible"]},
            "risk_reports": [
                {
                    "id": "RSK-001",
                    "status": "recorded",
                    "scope_kind": "stage",
                    "affected_scope": "verification",
                    "flags": ["systemic_verification_failure"],
                },
                {
                    "id": "RSK-002",
                    "status": "recorded",
                    "scope_kind": "workflow",
                    "affected_scope": "whole-delivery",
                    "flags": ["api_change"],
                },
                {
                    "id": "RSK-003",
                    "status": "recorded",
                    "scope_kind": "capability",
                    "affected_scope": "paid-release",
                    "flags": ["production_release"],
                },
            ],
        }

        flags = combined_risk_flags(state)
        self.assertEqual(
            ["user_visible", "systemic_verification_failure", "api_change"],
            flags,
        )
        self.assertEqual("standard", recommended_mode_for(flags))

    def test_risk_scope_key_is_stable_across_flag_order(self) -> None:
        first = risk_scope_key(
            ["external_dependency", "weak_verification"],
            scope_kind="stage",
            affected_scope="model-conversion",
            baseline_hash="abc123",
            origin_work_item="WORK-007",
        )
        second = risk_scope_key(
            ["weak_verification", "external_dependency"],
            scope_kind="stage",
            affected_scope="model-conversion",
            baseline_hash="abc123",
            origin_work_item="WORK-007",
        )

        self.assertEqual(first, second)
        self.assertRegex(first, r"^risk:[0-9a-f]{64}$")

        different_kind = risk_scope_key(
            ["weak_verification", "external_dependency"],
            scope_kind="capability",
            affected_scope="model-conversion",
            baseline_hash="abc123",
            origin_work_item="WORK-007",
        )
        self.assertNotEqual(first, different_kind)

    def test_risk_scope_key_changes_when_baseline_changes(self) -> None:
        old = risk_scope_key(
            ["external_dependency"],
            affected_scope="assets",
            baseline_hash="revision-10",
            origin_work_item="WORK-002",
        )
        new = risk_scope_key(
            ["external_dependency"],
            affected_scope="assets",
            baseline_hash="revision-11",
            origin_work_item="WORK-002",
        )

        self.assertNotEqual(old, new)


if __name__ == "__main__":
    unittest.main()
