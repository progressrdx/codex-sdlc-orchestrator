from __future__ import annotations

import hashlib
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


SCRIPTS = (
    Path(__file__).resolve().parents[1]
    / "plugins"
    / "multi-agent-role-work"
    / "skills"
    / "sdlc-orchestrator"
    / "scripts"
)
sys.path.insert(0, str(SCRIPTS))

import delivery_candidate as candidate_module  # noqa: E402
from delivery_candidate import (  # noqa: E402
    CandidateEntry,
    CandidateError,
    DeliveryCandidate,
    normalize_relative_paths,
)
from execution_policy import execute_verification_commands  # noqa: E402
from source_policy import source_binding  # noqa: E402
from state_store import WorkflowError  # noqa: E402


class DeliveryCandidateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name).resolve()
        self.git("init", "-q")
        self.git("config", "user.name", "Candidate Tests")
        self.git("config", "user.email", "candidate@example.com")

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def git(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["git", "-C", str(self.root), *args],
            check=True,
            capture_output=True,
            text=True,
        )

    def commit_file(self, relative: str, content: str = "committed\n") -> Path:
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        self.git("add", relative)
        self.git("commit", "-qm", f"add {relative}")
        return path

    def state(self, mode: str = "strict") -> dict[str, object]:
        return {
            "workflow": {"id": "REQ-candidate", "mode": mode},
            "source_revision": {},
            "verification_snapshot": {},
        }

    def test_candidate_is_an_immutable_commit_tree_manifest(self) -> None:
        source = self.commit_file("app.sh", "#!/bin/sh\necho committed\n")
        source.chmod(0o755)
        self.git("add", "app.sh")
        self.git("commit", "-qm", "make executable")

        candidate = DeliveryCandidate.from_repository(self.root)

        self.assertEqual(self.git("rev-parse", "HEAD").stdout.strip(), candidate.commit_oid)
        self.assertEqual(
            self.git("rev-parse", "HEAD^{tree}").stdout.strip(),
            candidate.tree_oid,
        )
        entry = next(item for item in candidate.entries if item.path == "app.sh")
        self.assertEqual("100755", entry.mode)
        self.assertEqual(40, len(entry.blob_oid))
        with self.assertRaises((AttributeError, TypeError)):
            candidate.commit_oid = "replacement"  # type: ignore[misc]

    def test_materialization_uses_commit_blobs_not_the_worktree(self) -> None:
        source = self.commit_file("app.txt", "committed\n")
        candidate = DeliveryCandidate.from_repository(self.root)
        source.write_text("worktree-only\n", encoding="utf-8")
        destination = self.root.parent / f"{self.root.name}-materialized"
        try:
            candidate.materialize(destination)
            self.assertEqual(
                "committed\n",
                (destination / "app.txt").read_text(encoding="utf-8"),
            )
        finally:
            if destination.exists():
                for child in sorted(destination.rglob("*"), reverse=True):
                    if child.is_symlink() or child.is_file():
                        child.unlink()
                    elif child.is_dir():
                        child.rmdir()
                destination.rmdir()

    def test_strict_binding_reports_ignored_and_untracked_candidate_gaps(self) -> None:
        self.commit_file("app.txt")
        (self.root / ".gitignore").write_text("vendor/\npublic/\n", encoding="utf-8")
        self.git("add", ".gitignore")
        self.git("commit", "-qm", "ignore generated assets")
        (self.root / "vendor").mkdir()
        (self.root / "vendor" / "runtime.dat").write_text("runtime\n", encoding="utf-8")
        (self.root / "public").mkdir()
        (self.root / "public" / "bundle.js").write_text("bundle\n", encoding="utf-8")
        (self.root / "loose.txt").write_text("loose\n", encoding="utf-8")

        binding = source_binding(self.root)

        self.assertIn("vendor/", binding["dirty_paths"])
        self.assertIn("public/", binding["dirty_paths"])
        self.assertIn("loose.txt", binding["dirty_paths"])

    def test_strict_execution_rejects_hidden_index_flags(self) -> None:
        source = self.commit_file("app.txt", "committed\n")
        self.git("update-index", "--assume-unchanged", "app.txt")
        source.write_text("hidden-worktree-change\n", encoding="utf-8")

        with self.assertRaises(WorkflowError) as raised:
            execute_verification_commands(
                self.root,
                self.state(),
                (("test", "grep -q hidden-worktree-change app.txt"),),
            )

        self.assertIn("index flag", str(raised.exception))

    def test_candidate_rejects_internal_symlink_to_missing_candidate_target(self) -> None:
        (self.root / ".gitignore").write_text("ignored/\n", encoding="utf-8")
        (self.root / "ignored").mkdir()
        (self.root / "ignored" / "runtime.dat").write_text("runtime\n", encoding="utf-8")
        (self.root / "runtime-link").symlink_to("ignored/runtime.dat")
        self.git("add", ".gitignore", "runtime-link")
        self.git("commit", "-qm", "add incomplete symlink")

        with self.assertRaises(CandidateError) as raised:
            DeliveryCandidate.from_repository(self.root)

        self.assertIn("not present in the candidate", str(raised.exception))

    def test_snapshot_commit_cannot_hide_candidate_mutation(self) -> None:
        self.commit_file("app.txt", "original\n")

        with self.assertRaises(WorkflowError) as raised:
            execute_verification_commands(
                self.root,
                self.state(),
                (
                    (
                        "build",
                        "echo tampered > app.txt && git add app.txt && "
                        "git -c user.name=Verifier -c user.email=v@example.com "
                        "commit -qm tamper",
                    ),
                    ("test", "grep -q tampered app.txt"),
                ),
            )

        self.assertIn("exited with", str(raised.exception))

    def test_explicit_output_directory_may_change_between_commands(self) -> None:
        self.commit_file("app.txt")

        execution = execute_verification_commands(
            self.root,
            self.state(),
            (
                ("build", "mkdir -p build && echo artifact > build/result.txt"),
                ("test", "grep -q artifact build/result.txt"),
            ),
            output_paths=("build",),
        )

        self.assertEqual("pass", execution["status"])
        self.assertEqual("git_commit", execution["candidate"]["kind"])
        self.assertEqual(
            self.git("rev-parse", "HEAD^{tree}").stdout.strip(),
            execution["candidate"]["tree_oid"],
        )

    def test_source_exclusion_does_not_grant_output_write_access(self) -> None:
        self.commit_file("app.txt")
        self.commit_file("vendor/runtime.dat", "trusted\n")

        with self.assertRaises(WorkflowError) as raised:
            execute_verification_commands(
                self.root,
                self.state(),
                (("test", "printf tampered > vendor/runtime.dat"),),
                ignored_paths=("vendor",),
            )

        self.assertIn("exited with", str(raised.exception))

    def test_output_allowlist_cannot_overlap_frozen_candidate_input(self) -> None:
        self.commit_file("build/checked-in.txt", "trusted\n")

        with self.assertRaises(WorkflowError) as raised:
            execute_verification_commands(
                self.root,
                self.state(),
                (("build", "printf tampered > build/checked-in.txt"),),
                output_paths=("build",),
            )

        self.assertIn("must not overlap frozen candidate inputs", str(raised.exception))

    def test_same_uid_command_cannot_modify_then_restore_candidate_input(self) -> None:
        source = self.commit_file("app.txt", "original\n")

        with self.assertRaises(WorkflowError) as raised:
            execute_verification_commands(
                self.root,
                self.state(),
                (
                    (
                        "temporary-tamper",
                        "chmod u+w app.txt 2>/dev/null || true; "
                        "printf temporary > app.txt 2>/dev/null || true; "
                        "grep -q temporary app.txt; "
                        "printf 'original\\n' > app.txt; chmod u-w app.txt",
                    ),
                ),
            )

        self.assertIn("exited with", str(raised.exception))
        self.assertEqual("original\n", source.read_text(encoding="utf-8"))

    def test_candidate_rejects_case_and_unicode_normalization_collisions(self) -> None:
        payload = b"content\n"
        oid = "sha256:" + hashlib.sha256(payload).hexdigest()
        collisions = (
            ("Assets/icon.txt", "assets/other.txt"),
            ("caf\u00e9.txt", "cafe\u0301.txt"),
        )
        for first, second in collisions:
            with self.subTest(first=first, second=second):
                candidate = DeliveryCandidate(
                    kind="workspace_content",
                    repository=self.root,
                    commit_oid=None,
                    tree_oid="sha256:unused",
                    entries=(
                        CandidateEntry(first, "100644", oid),
                        CandidateEntry(second, "100644", oid),
                    ),
                    manifest_sha256="unused",
                )
                with self.assertRaises(CandidateError) as raised:
                    candidate.materialize(self.root.parent / f"collision-{len(first)}")
                self.assertIn("collide", str(raised.exception))

    def test_materialization_rechecks_type_mode_and_content(self) -> None:
        self.commit_file("app.txt", "trusted\n")
        candidate = DeliveryCandidate.from_repository(self.root)
        original_write = candidate_module._write_candidate_entry

        def corrupt(kind: str):
            def write(destination: Path, entry: CandidateEntry, payload: bytes) -> None:
                original_write(destination, entry, payload)
                target = destination / entry.path
                if kind == "content":
                    target.write_text("tampered\n", encoding="utf-8")
                elif kind == "mode":
                    target.chmod(0o600)
                else:
                    target.unlink()
                    target.mkdir()

            return write

        for kind in ("content", "mode", "type"):
            with self.subTest(kind=kind):
                destination = self.root.parent / f"materialized-{kind}"
                with mock.patch.object(
                    candidate_module,
                    "_write_candidate_entry",
                    side_effect=corrupt(kind),
                ):
                    with self.assertRaises(CandidateError) as raised:
                        candidate.materialize(destination)
                self.assertIn(f"wrong {kind}", str(raised.exception))
                self.assertFalse(destination.exists())

    def test_windows_drive_unc_reserved_and_separator_paths_fail_closed(self) -> None:
        unsafe_paths = (
            r"C:\\outside",
            r"\\\\server\\share\\artifact",
            r"folder\\..\\outside",
            "CON/output.txt",
            "folder/NUL.txt",
            "file.txt:stream",
            "trailing./file",
        )
        for unsafe in unsafe_paths:
            with self.subTest(path=unsafe):
                with self.assertRaises(CandidateError):
                    normalize_relative_paths((unsafe,))

    def test_output_symlink_escape_fails_closed(self) -> None:
        self.commit_file("app.txt", "trusted\n")

        with self.assertRaises(WorkflowError) as raised:
            execute_verification_commands(
                self.root,
                self.state(),
                (("build", "ln -s ../app.txt build/escape"),),
                output_paths=("build",),
            )

        self.assertIn("symbolic links", str(raised.exception))

    def test_output_hardlink_alias_fails_closed(self) -> None:
        self.commit_file("app.txt", "trusted\n")

        with self.assertRaises(WorkflowError) as raised:
            execute_verification_commands(
                self.root,
                self.state(),
                (("build", "printf artifact > build/one && ln build/one build/two"),),
                output_paths=("build",),
            )

        self.assertIn("hard links", str(raised.exception))


if __name__ == "__main__":
    unittest.main()
