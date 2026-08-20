from __future__ import annotations

import copy
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

from stage_submission import (  # noqa: E402
    IdempotencyConflict,
    RevisionConflict,
    StageSubmissionError,
    finalize_stage_submission,
    meeting_stable_key,
    prepare_stage_submission,
    risk_stable_key,
    store_submission_receipt,
    upsert_stable_record,
)
from work_items import (  # noqa: E402
    StaleBaselineError,
    WorkItemError,
    WorkItemExpiredError,
    WorkItemStateError,
    assert_output_acceptable,
    cancel_work_item,
    complete_work_item,
    create_work_item,
    fail_work_item,
    heartbeat_work_item,
    supersede_work_item,
    timeout_work_item,
    validate_work_item,
)


HASH_A = "a" * 64
HASH_B = "b" * 64
HASH_C = "c" * 64


class WorkItemTests(unittest.TestCase):
    def make_item(self, **overrides):
        values = {
            "work_item_id": "WI-design-engineering-001",
            "stage": "design",
            "role": "engineering",
            "attempt": 1,
            "actor_ref": "agent:engineering-001",
            "input_revision": 7,
            "input_hashes": {"prd": HASH_A, "requirements": HASH_B},
            "dispatched_at": "2026-08-13T10:00:00Z",
            "deadline_at": "2026-08-13T10:10:00Z",
            "lease_seconds": 120,
        }
        values.update(overrides)
        return create_work_item(**values)

    def test_create_and_validate_work_item_canonicalizes_a_lease(self) -> None:
        item = self.make_item(input_hashes={"requirements": HASH_B, "prd": HASH_A})

        self.assertEqual("dispatched", item["status"])
        self.assertEqual("2026-08-13T10:02:00Z", item["lease_expires_at"])
        self.assertEqual("2026-08-13T10:00:00Z", item["heartbeat_at"])
        self.assertEqual(["prd", "requirements"], list(item["input_hashes"]))
        self.assertEqual(item, validate_work_item(item))

    def test_invalid_identity_revision_hash_and_time_fields_are_rejected(self) -> None:
        invalid_values = (
            {"work_item_id": "x"},
            {"stage": "Design Stage"},
            {"role": ""},
            {"attempt": 0},
            {"actor_ref": "x"},
            {"input_revision": -1},
            {"input_hashes": {"prd": "not-a-sha256"}},
            {"deadline_at": "2026-08-13T09:59:59Z"},
            {"lease_seconds": 0},
        )
        for override in invalid_values:
            with self.subTest(override=override), self.assertRaises(WorkItemError):
                self.make_item(**override)

    def test_heartbeat_renews_the_lease_without_mutating_the_input(self) -> None:
        original = self.make_item()
        snapshot = copy.deepcopy(original)

        renewed = heartbeat_work_item(
            original,
            at="2026-08-13T10:01:00Z",
        )

        self.assertEqual(snapshot, original)
        self.assertEqual("running", renewed["status"])
        self.assertEqual("2026-08-13T10:03:00Z", renewed["lease_expires_at"])
        self.assertEqual(1, renewed["heartbeat_count"])

    def test_heartbeat_after_lease_expiry_is_rejected(self) -> None:
        with self.assertRaises(WorkItemExpiredError):
            heartbeat_work_item(
                self.make_item(),
                at="2026-08-13T10:02:00Z",
            )

    def test_completion_accepts_same_baseline_and_records_output_hashes(self) -> None:
        item = self.make_item()

        completed = complete_work_item(
            item,
            at="2026-08-13T10:01:00Z",
            current_revision=7,
            current_input_hashes={"requirements": HASH_B, "prd": HASH_A},
            output_hashes={"technical_design": HASH_C},
            output_paths={"technical_design": "docs/technical-design.md"},
        )

        self.assertEqual("completed", completed["status"])
        self.assertEqual(7, completed["completed_against_revision"])
        self.assertEqual({"technical_design": HASH_C}, completed["output_hashes"])
        self.assertEqual(
            completed,
            assert_output_acceptable(
                completed,
                at="2026-08-13T10:01:30Z",
                current_revision=7,
                current_input_hashes={"prd": HASH_A, "requirements": HASH_B},
            ),
        )

    def test_newer_revision_is_allowed_only_when_bound_inputs_are_unchanged(self) -> None:
        item = self.make_item()
        completed = complete_work_item(
            item,
            at="2026-08-13T10:01:00Z",
            current_revision=9,
            current_input_hashes={
                "prd": HASH_A,
                "requirements": HASH_B,
                "unrelated": HASH_C,
            },
            output_hashes={"technical_design": HASH_C},
            output_paths={"technical_design": "docs/technical-design.md"},
        )
        self.assertEqual(9, completed["completed_against_revision"])

        with self.assertRaises(StaleBaselineError):
            complete_work_item(
                item,
                at="2026-08-13T10:01:00Z",
                current_revision=9,
                current_input_hashes={"prd": HASH_C, "requirements": HASH_B},
                output_hashes={"technical_design": HASH_C},
                output_paths={"technical_design": "docs/technical-design.md"},
            )

        unbound = self.make_item(input_hashes={})
        with self.assertRaises(StaleBaselineError):
            complete_work_item(
                unbound,
                at="2026-08-13T10:01:00Z",
                current_revision=9,
                current_input_hashes={},
                output_hashes={"technical_design": HASH_C},
                output_paths={"technical_design": "docs/technical-design.md"},
            )

    def test_late_output_is_rejected_even_when_the_baseline_matches(self) -> None:
        with self.assertRaises(WorkItemExpiredError):
            complete_work_item(
                self.make_item(),
                at="2026-08-13T10:02:00Z",
                current_revision=7,
                current_input_hashes={"prd": HASH_A, "requirements": HASH_B},
                output_hashes={"technical_design": HASH_C},
                output_paths={"technical_design": "docs/technical-design.md"},
            )

    def test_cancel_timeout_and_supersede_are_terminal_for_output(self) -> None:
        item = self.make_item()
        cancelled = cancel_work_item(
            item,
            at="2026-08-13T10:01:00Z",
            reason="Coordinator cancelled the attempt.",
        )
        timed_out = timeout_work_item(
            item,
            at="2026-08-13T10:02:00Z",
            reason="Heartbeat lease expired.",
        )
        completed = complete_work_item(
            item,
            at="2026-08-13T10:01:00Z",
            current_revision=7,
            current_input_hashes={"prd": HASH_A, "requirements": HASH_B},
            output_hashes={"technical_design": HASH_C},
            output_paths={"technical_design": "docs/technical-design.md"},
        )
        superseded = supersede_work_item(
            completed,
            at="2026-08-13T10:01:30Z",
            reason="The PRD baseline changed.",
            superseded_by_revision=8,
        )

        self.assertEqual("cancelled", cancelled["status"])
        self.assertEqual("timed_out", timed_out["status"])
        self.assertEqual("superseded", superseded["status"])
        for terminal in (cancelled, timed_out, superseded):
            with self.subTest(status=terminal["status"]), self.assertRaises(
                WorkItemStateError
            ):
                assert_output_acceptable(
                    terminal,
                    at="2026-08-13T10:01:30Z",
                    current_revision=7,
                    current_input_hashes={"prd": HASH_A, "requirements": HASH_B},
                )

    def test_timeout_cannot_be_recorded_before_the_lease_or_deadline(self) -> None:
        with self.assertRaises(WorkItemStateError):
            timeout_work_item(
                self.make_item(),
                at="2026-08-13T10:01:00Z",
                reason="Too early.",
            )

    def test_completed_output_cannot_be_accepted_after_lease_expiry(self) -> None:
        completed = complete_work_item(
            self.make_item(),
            at="2026-08-13T10:01:00Z",
            current_revision=7,
            current_input_hashes={"prd": HASH_A, "requirements": HASH_B},
            output_hashes={"technical_design": HASH_C},
            output_paths={"technical_design": "docs/technical-design.md"},
        )

        with self.assertRaises(WorkItemExpiredError):
            assert_output_acceptable(
                completed,
                at="2026-08-13T10:02:00Z",
                current_revision=7,
                current_input_hashes={"prd": HASH_A, "requirements": HASH_B},
            )

    def test_serialized_lease_progress_paths_and_override_are_fail_closed(self) -> None:
        base = self.make_item()
        invalid_active = []

        forged_lease = copy.deepcopy(base)
        forged_lease["lease_expires_at"] = "2026-08-13T10:03:00Z"
        invalid_active.append(forged_lease)

        forged_dispatched = copy.deepcopy(base)
        forged_dispatched["heartbeat_count"] = 1
        invalid_active.append(forged_dispatched)

        invalid_override = copy.deepcopy(base)
        invalid_override["handoff_budget_override"] = {
            "path": "../outside.md",
            "evidence_sha256": HASH_A,
        }
        invalid_active.append(invalid_override)

        for item in invalid_active:
            with self.subTest(item=item), self.assertRaises(WorkItemError):
                validate_work_item(item)

        completed = complete_work_item(
            base,
            at="2026-08-13T10:01:00Z",
            current_revision=7,
            current_input_hashes={"prd": HASH_A, "requirements": HASH_B},
            output_hashes={"technical_design": HASH_C},
            output_paths={"technical_design": "docs/technical-design.md"},
        )
        mismatched_names = copy.deepcopy(completed)
        mismatched_names["output_paths"] = {"test_plan": "docs/test-plan.md"}
        noncanonical_path = copy.deepcopy(completed)
        noncanonical_path["output_paths"]["technical_design"] = "docs/../design.md"
        for item in (mismatched_names, noncanonical_path):
            with self.subTest(item=item), self.assertRaises(WorkItemError):
                validate_work_item(item)

    def test_fail_transition_is_terminal_and_requires_an_unexpired_attempt(self) -> None:
        failed = fail_work_item(
            self.make_item(),
            at="2026-08-13T10:01:00Z",
            reason="Role execution failed independently.",
        )

        self.assertEqual("failed", failed["status"])
        with self.assertRaises(WorkItemStateError):
            heartbeat_work_item(failed, at="2026-08-13T10:01:30Z")
        with self.assertRaises(WorkItemExpiredError):
            fail_work_item(
                self.make_item(),
                at="2026-08-13T10:02:00Z",
                reason="Too late to report failure.",
            )


class StageSubmissionTests(unittest.TestCase):
    def submission(self, **overrides):
        values = {
            "stage": "design",
            "current_stage": "design",
            "expected_revision": 10,
            "current_revision": 10,
            "idempotency_key": "REQ-001:design:round-1",
            "payload": {
                "artifacts": [
                    {"name": "technical_design", "sha256": HASH_A},
                    {"name": "test_plan", "sha256": HASH_B},
                ]
            },
            "receipts": {},
        }
        values.update(overrides)
        return prepare_stage_submission(**values)

    def test_new_submission_requires_current_stage_and_exact_revision(self) -> None:
        plan = self.submission()
        self.assertEqual("apply", plan["action"])
        self.assertEqual(10, plan["expected_revision"])
        self.assertEqual(64, len(plan["payload_sha256"]))

        with self.assertRaises(RevisionConflict):
            self.submission(current_revision=11)
        with self.assertRaises(StageSubmissionError):
            self.submission(current_stage="readiness_review")

    def test_successful_receipt_replays_after_the_workflow_has_advanced(self) -> None:
        plan = self.submission()
        receipt = finalize_stage_submission(
            plan,
            applied_revision=11,
            result={"next_stage": "readiness_review", "meeting_id": "MTG-001"},
        )
        receipts, action = store_submission_receipt({}, receipt)
        self.assertEqual("inserted", action)

        replay = self.submission(
            current_stage="acceptance",
            current_revision=18,
            receipts=receipts,
        )

        self.assertEqual("replay", replay["action"])
        self.assertEqual(receipt, replay["receipt"])

    def test_reused_idempotency_key_with_different_payload_conflicts(self) -> None:
        plan = self.submission()
        receipt = finalize_stage_submission(plan, applied_revision=11, result={})
        receipts, _ = store_submission_receipt({}, receipt)

        with self.assertRaises(IdempotencyConflict):
            self.submission(
                payload={"artifacts": [{"name": "technical_design", "sha256": HASH_C}]},
                receipts=receipts,
                current_revision=11,
            )

    def test_receipts_are_immutable_and_idempotently_stored(self) -> None:
        receipt = finalize_stage_submission(
            self.submission(),
            applied_revision=11,
            result={"next_stage": "readiness_review"},
        )
        stored, action = store_submission_receipt({}, receipt)
        self.assertEqual("inserted", action)
        replayed, action = store_submission_receipt(stored, copy.deepcopy(receipt))
        self.assertEqual("replayed", action)
        self.assertEqual(stored, replayed)

        conflicting = {**receipt, "result": {"next_stage": "acceptance"}}
        with self.assertRaises(IdempotencyConflict):
            store_submission_receipt(stored, conflicting)

    def test_finalize_requires_one_atomic_revision_increment(self) -> None:
        with self.assertRaises(RevisionConflict):
            finalize_stage_submission(
                self.submission(),
                applied_revision=12,
                result={},
            )

    def test_meeting_and_risk_keys_are_order_independent(self) -> None:
        first_meeting = meeting_stable_key(
            workflow_id="REQ-001",
            stage="readiness_review",
            meeting_type="readiness_review",
            baseline_hashes={"design": HASH_A, "test_plan": HASH_B},
            review_round=2,
        )
        second_meeting = meeting_stable_key(
            workflow_id="REQ-001",
            stage="readiness_review",
            meeting_type="readiness_review",
            baseline_hashes={"test_plan": HASH_B, "design": HASH_A},
            review_round=2,
        )
        self.assertEqual(first_meeting, second_meeting)
        self.assertTrue(first_meeting.startswith("meeting:"))

        first_risk = risk_stable_key(
            workflow_id="REQ-001",
            flags=["external_dependency", "weak_verification"],
            affected_scope=["api", "ui"],
            baseline_hashes={"prd": HASH_A},
            origin_work_item_id="WI-testing-001",
        )
        second_risk = risk_stable_key(
            workflow_id="REQ-001",
            flags=["weak_verification", "external_dependency", "weak_verification"],
            affected_scope=["ui", "api", "ui"],
            baseline_hashes={"prd": HASH_A},
            origin_work_item_id="WI-testing-001",
        )
        self.assertEqual(first_risk, second_risk)
        self.assertTrue(first_risk.startswith("risk:"))

    def test_stable_record_upsert_does_not_append_duplicate_rounds(self) -> None:
        stable_key = meeting_stable_key(
            workflow_id="REQ-001",
            stage="readiness_review",
            meeting_type="readiness_review",
            baseline_hashes={"design": HASH_A},
            review_round=1,
        )
        initial = {"stable_key": stable_key, "outcome": "actions_required"}
        records, action = upsert_stable_record([], initial)
        self.assertEqual("inserted", action)

        replayed, action = upsert_stable_record(records, copy.deepcopy(initial))
        self.assertEqual("replayed", action)
        self.assertEqual(1, len(replayed))

        updated, action = upsert_stable_record(
            replayed,
            {"stable_key": stable_key, "outcome": "approved"},
        )
        self.assertEqual("updated", action)
        self.assertEqual(1, len(updated))
        self.assertEqual("approved", updated[0]["outcome"])


if __name__ == "__main__":
    unittest.main()
