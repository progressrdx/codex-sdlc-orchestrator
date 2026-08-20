from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = (
    ROOT
    / "plugins"
    / "multi-agent-role-work"
    / "skills"
    / "sdlc-orchestrator"
    / "scripts"
)
WORKFLOW_CLI = SCRIPTS / "workflow.py"
sys.path.insert(0, str(SCRIPTS))
try:
    import runtime_provenance as provenance
finally:
    sys.path.pop(0)


class RuntimeProvenanceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()

    def tearDown(self) -> None:
        self.temp.cleanup()

    def make_plugin(
        self,
        name: str,
        *,
        version: str = "1.2.3+codex.first",
        entry_content: str = "print('ready')\n",
    ) -> Path:
        plugin = self.root / name
        manifest_dir = plugin / ".codex-plugin"
        entry = plugin / provenance.DEFAULT_ENTRY_PATH
        manifest_dir.mkdir(parents=True)
        entry.parent.mkdir(parents=True)
        (manifest_dir / "plugin.json").write_text(
            json.dumps(
                {
                    "name": name,
                    "version": version,
                    "description": "fixture",
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        entry.write_text(entry_content, encoding="utf-8")
        (plugin / "skills" / "example.txt").write_text("payload\n", encoding="utf-8")
        return plugin

    @staticmethod
    def set_version(plugin: Path, version: str) -> None:
        manifest_path = plugin / ".codex-plugin" / "plugin.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["version"] = version
        manifest_path.write_text(
            json.dumps(manifest, indent=2) + "\n",
            encoding="utf-8",
        )

    def test_payload_hash_is_deterministic_and_normalizes_self_references(self) -> None:
        first = self.make_plugin("first", version="1.2.3+codex.aaa")
        second = self.make_plugin("second", version="1.2.3+codex.bbb")

        # Plugin name is payload, so make both manifests semantically identical except
        # for their cachebuster before comparing the canonical payloads.
        second_manifest = second / ".codex-plugin" / "plugin.json"
        data = json.loads(second_manifest.read_text(encoding="utf-8"))
        data["name"] = "first"
        second_manifest.write_text(json.dumps(data, separators=(",", ":")), encoding="utf-8")
        (first / ".codex-plugin" / provenance.PROVENANCE_FILENAME).write_text(
            '{"payload_sha256":"stale-first"}\n', encoding="utf-8"
        )
        (second / ".codex-plugin" / provenance.PROVENANCE_FILENAME).write_text(
            '{"payload_sha256":"stale-second"}\n', encoding="utf-8"
        )

        self.assertEqual(
            provenance.compute_payload_sha256(first),
            provenance.compute_payload_sha256(second),
        )

        (second / "skills" / "example.txt").write_text("changed\n", encoding="utf-8")
        self.assertNotEqual(
            provenance.compute_payload_sha256(first),
            provenance.compute_payload_sha256(second),
        )

    def test_runtime_info_reports_identity_and_git_state(self) -> None:
        plugin = self.make_plugin("fixture")
        subprocess.run(["git", "init", "-q", str(self.root)], check=True)
        subprocess.run(
            ["git", "-C", str(self.root), "config", "user.email", "fixture@example.com"],
            check=True,
        )
        subprocess.run(
            ["git", "-C", str(self.root), "config", "user.name", "Fixture"],
            check=True,
        )
        subprocess.run(["git", "-C", str(self.root), "add", "."], check=True)
        subprocess.run(["git", "-C", str(self.root), "commit", "-qm", "fixture"], check=True)
        revision = subprocess.check_output(
            ["git", "-C", str(self.root), "rev-parse", "HEAD"], text=True
        ).strip()

        info = provenance.inspect_runtime(plugin)

        self.assertEqual("1.2.3+codex.first", info["version"])
        self.assertEqual(str(plugin), info["runtime_root"])
        self.assertEqual(revision, info["git_revision"])
        self.assertFalse(info["dirty"])
        self.assertEqual(
            hashlib.sha256((plugin / provenance.DEFAULT_ENTRY_PATH).read_bytes()).hexdigest(),
            info["entry_sha256"],
        )
        self.assertEqual(provenance.compute_payload_sha256(plugin), info["payload_sha256"])

        (plugin / "skills" / "example.txt").write_text("dirty\n", encoding="utf-8")
        self.assertTrue(provenance.inspect_runtime(plugin)["dirty"])

    def test_doctor_reports_ok_for_identical_source_and_runtime(self) -> None:
        source = self.make_plugin("source")
        runtime = self.root / "runtime"
        shutil.copytree(source, runtime)
        provenance.write_embedded_provenance(runtime)

        report = provenance.doctor_runtime(runtime, source_root=source)

        self.assertEqual(provenance.STATUS_OK, report["status"])
        self.assertFalse(report["hard_failure"])

    def test_doctor_reports_source_newer_for_a_new_declared_version(self) -> None:
        source = self.make_plugin("source", version="1.2.4+codex.new")
        runtime = self.root / "runtime"
        shutil.copytree(source, runtime)
        self.set_version(runtime, "1.2.3+codex.old")
        provenance.write_embedded_provenance(runtime)

        report = provenance.doctor_runtime(runtime, source_root=source)

        self.assertEqual(provenance.STATUS_SOURCE_NEWER, report["status"])
        self.assertFalse(report["hard_failure"])

    def test_doctor_reports_version_collision_as_a_hard_failure(self) -> None:
        source = self.make_plugin("source")
        runtime = self.root / "runtime"
        shutil.copytree(source, runtime)
        provenance.write_embedded_provenance(runtime)
        (source / "skills" / "example.txt").write_text("new source bytes\n", encoding="utf-8")

        report = provenance.doctor_runtime(runtime, source_root=source)

        self.assertEqual(provenance.STATUS_VERSION_COLLISION, report["status"])
        self.assertTrue(report["hard_failure"])
        with self.assertRaises(provenance.ProvenanceHardFailure):
            provenance.require_healthy_runtime(report)

    def test_doctor_cli_exits_two_for_a_version_collision(self) -> None:
        source = self.make_plugin("source")
        runtime = self.root / "runtime"
        shutil.copytree(source, runtime)
        (source / "skills" / "example.txt").write_text("new source bytes\n", encoding="utf-8")

        result = subprocess.run(
            [
                sys.executable,
                str(SCRIPTS / "runtime_provenance.py"),
                "doctor",
                "--runtime-root",
                str(runtime),
                "--source-root",
                str(source),
            ],
            check=False,
            capture_output=True,
            text=True,
        )

        self.assertEqual(2, result.returncode, msg=result.stderr)
        self.assertEqual(
            provenance.STATUS_VERSION_COLLISION,
            json.loads(result.stdout)["status"],
        )

    def test_workflow_cli_version_reports_requested_runtime(self) -> None:
        runtime = self.make_plugin("runtime")

        result = subprocess.run(
            [
                sys.executable,
                str(WORKFLOW_CLI),
                "version",
                "--runtime-root",
                str(runtime),
                "--json",
            ],
            check=False,
            capture_output=True,
            text=True,
        )

        self.assertEqual(0, result.returncode, msg=result.stderr)
        identity = json.loads(result.stdout)
        self.assertEqual("runtime", identity["plugin_name"])
        self.assertEqual("1.2.3+codex.first", identity["version"])
        self.assertEqual(str(runtime), identity["runtime_root"])

    def test_workflow_cli_doctor_propagates_hard_failure_exit_code(self) -> None:
        source = self.make_plugin("source")
        runtime = self.root / "runtime"
        shutil.copytree(source, runtime)
        (source / "skills" / "example.txt").write_text(
            "different source payload\n", encoding="utf-8"
        )

        result = subprocess.run(
            [
                sys.executable,
                str(WORKFLOW_CLI),
                "doctor",
                "--runtime-root",
                str(runtime),
                "--source-root",
                str(source),
                "--json",
            ],
            check=False,
            capture_output=True,
            text=True,
        )

        self.assertEqual(2, result.returncode, msg=result.stderr)
        self.assertEqual(
            provenance.STATUS_VERSION_COLLISION,
            json.loads(result.stdout)["status"],
        )

    def test_init_records_tool_identity_and_status_is_read_only(self) -> None:
        repository = self.root / "repository"
        repository.mkdir()
        init = subprocess.run(
            [
                sys.executable,
                str(WORKFLOW_CLI),
                "--root",
                str(repository),
                "init",
                "--id",
                "REQ-provenance",
                "--title",
                "Provenance fixture",
                "--mode",
                "standard",
                "--request",
                "Record the workflow tool identity.",
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(0, init.returncode, msg=init.stderr)
        state_path = repository / ".ai-workflow" / "REQ-provenance" / "state.yaml"
        before = state_path.read_bytes()

        status = subprocess.run(
            [
                sys.executable,
                str(WORKFLOW_CLI),
                "--root",
                str(repository),
                "--id",
                "REQ-provenance",
                "status",
                "--json",
            ],
            check=False,
            capture_output=True,
            text=True,
        )

        self.assertEqual(0, status.returncode, msg=status.stderr)
        state = json.loads(status.stdout)
        recorded = state["runtime_provenance"]
        self.assertEqual(recorded["created_by_tool"], recorded["last_mutated_by_tool"])
        self.assertEqual("multi-agent-role-work", recorded["created_by_tool"]["plugin_name"])
        self.assertRegex(recorded["created_by_tool"]["payload_sha256"], r"^[0-9a-f]{64}$")
        self.assertEqual(before, state_path.read_bytes())

    def test_every_state_write_refreshes_last_mutator_without_rewriting_creator(self) -> None:
        repository = self.root / "repository"
        repository.mkdir()
        init = subprocess.run(
            [
                sys.executable,
                str(WORKFLOW_CLI),
                "--root",
                str(repository),
                "init",
                "--id",
                "REQ-mutator",
                "--title",
                "Mutator fixture",
                "--mode",
                "standard",
                "--request",
                "Record each workflow mutator identity.",
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(0, init.returncode, msg=init.stderr)

        sys.path.insert(0, str(SCRIPTS))
        try:
            import workflow

            state_path, state = workflow.load_state(repository, "REQ-mutator")
            creator = dict(state["runtime_provenance"]["created_by_tool"])
            replacement = {
                **creator,
                "version": "9.9.9+codex.replacement",
                "payload_sha256": "a" * 64,
                "entry_sha256": "b" * 64,
            }
            state["history"].append(
                {
                    "at": "2099-01-01T00:00:00Z",
                    "event": "test_mutation",
                    "detail": "refresh the mutator identity",
                }
            )
            healthy_report = {
                "status": provenance.STATUS_SOURCE_NEWER,
                "runtime": replacement,
            }
            with mock.patch.object(
                workflow,
                "require_mutation_runtime_health",
                return_value=healthy_report,
            ):
                workflow.save_state(state_path, state)
            _, recorded = workflow.load_state(repository, "REQ-mutator")
        finally:
            sys.path.pop(0)

        self.assertEqual(creator, recorded["runtime_provenance"]["created_by_tool"])
        self.assertEqual(replacement, recorded["runtime_provenance"]["last_mutated_by_tool"])

    def test_mutation_report_rejects_recorded_same_version_with_new_payload(self) -> None:
        runtime = self.make_plugin("runtime")
        observed = provenance.inspect_runtime(runtime)
        recorded = {**observed, "payload_sha256": "0" * 64}

        report = provenance.mutation_runtime_report(
            runtime,
            recorded_identity=recorded,
            loaded_identity=observed,
        )

        self.assertEqual(provenance.STATUS_VERSION_COLLISION, report["status"])
        self.assertTrue(report["hard_failure"])

    def test_mutation_report_rejects_embedded_runtime_tampering(self) -> None:
        runtime = self.make_plugin("runtime")
        provenance.write_embedded_provenance(runtime)
        loaded = provenance.inspect_runtime(runtime)
        (runtime / "skills" / "example.txt").write_text("tampered\n", encoding="utf-8")

        report = provenance.mutation_runtime_report(
            runtime,
            loaded_identity=loaded,
        )

        self.assertEqual(provenance.STATUS_RUNTIME_TAMPERED, report["status"])
        self.assertTrue(report["hard_failure"])

    def test_save_state_does_not_record_a_hard_failure_runtime(self) -> None:
        repository = self.root / "repository"
        repository.mkdir()
        init = subprocess.run(
            [
                sys.executable,
                str(WORKFLOW_CLI),
                "--root",
                str(repository),
                "init",
                "--id",
                "REQ-hard-failure",
                "--title",
                "Hard failure fixture",
                "--mode",
                "standard",
                "--request",
                "Do not persist a compromised mutator.",
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(0, init.returncode, msg=init.stderr)

        sys.path.insert(0, str(SCRIPTS))
        try:
            import workflow

            state_path, state = workflow.load_state(repository, "REQ-hard-failure")
            before = state_path.read_bytes()
            failure = workflow.WorkflowError(
                "Runtime provenance RUNTIME_TAMPERED: Mutation refused."
            )
            with mock.patch.object(
                workflow, "require_mutation_runtime_health", side_effect=failure
            ):
                with self.assertRaises(workflow.WorkflowError):
                    workflow.save_state(state_path, state)
        finally:
            sys.path.pop(0)

        self.assertEqual(before, state_path.read_bytes())

    def test_doctor_reports_runtime_tampering_as_a_hard_failure(self) -> None:
        source = self.make_plugin("source")
        runtime = self.root / "runtime"
        shutil.copytree(source, runtime)
        provenance.write_embedded_provenance(runtime)
        (runtime / "skills" / "example.txt").write_text("tampered\n", encoding="utf-8")

        report = provenance.doctor_runtime(runtime, source_root=source)

        self.assertEqual(provenance.STATUS_RUNTIME_TAMPERED, report["status"])
        self.assertTrue(report["hard_failure"])

    def test_doctor_reports_source_unavailable(self) -> None:
        runtime = self.make_plugin("runtime")
        provenance.write_embedded_provenance(runtime)

        report = provenance.doctor_runtime(
            runtime,
            source_root=self.root / "does-not-exist",
        )

        self.assertEqual(provenance.STATUS_SOURCE_UNAVAILABLE, report["status"])
        self.assertFalse(report["hard_failure"])

    def test_doctor_reports_restart_required_for_stale_loaded_identity(self) -> None:
        source = self.make_plugin("source")
        runtime = self.root / "runtime"
        shutil.copytree(source, runtime)
        provenance.write_embedded_provenance(runtime)

        report = provenance.doctor_runtime(
            runtime,
            source_root=source,
            loaded_payload_sha256="0" * 64,
            loaded_entry_sha256="1" * 64,
        )

        self.assertEqual(provenance.STATUS_RESTART_REQUIRED, report["status"])
        self.assertFalse(report["hard_failure"])

    def test_generator_writes_reproducible_embedded_provenance(self) -> None:
        plugin = self.make_plugin("fixture")
        generator = ROOT / "tools" / "generate-plugin-provenance.py"

        first = subprocess.run(
            [sys.executable, str(generator), str(plugin)],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(0, first.returncode, msg=first.stderr)
        output = plugin / ".codex-plugin" / provenance.PROVENANCE_FILENAME
        first_bytes = output.read_bytes()
        second = subprocess.run(
            [sys.executable, str(generator), str(plugin), "--check"],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(0, second.returncode, msg=second.stderr)
        self.assertEqual(first_bytes, output.read_bytes())


if __name__ == "__main__":
    unittest.main()
