"""Integration checks for manual task imports, stale sources and release gates."""

from contextlib import redirect_stderr, redirect_stdout
import io
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

from src.cli import main
from src.contracts import ContractError, read_json
from tests.downstream_support import (
    REPOSITORY, b_response, c_response, create_project, d_response, finish_bc, import_response, write_json,
)


class PipelineTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.pipeline = create_project(self.root)

    def tearDown(self):
        self.temp.cleanup()

    def test_c_before_b_is_blocked(self):
        with self.assertRaises(ContractError):
            self.pipeline.prepare("C")

    def test_bc_round_trip_immutable_history_and_c_cache(self):
        finish_bc(self.pipeline)
        c = self.pipeline.store.latest("C")
        self.assertTrue(Path(c["report_path"]).is_file())
        self.assertEqual(self.pipeline.prepare("C")["record"]["revision_id"], c["revision_id"])
        old_b = self.pipeline.store.latest("B")
        self.pipeline.prepare("B", force=True)
        self.assertIsNone(self.pipeline.store.latest("C"))
        self.assertTrue(Path(old_b["result_path"]).is_file())
        self.assertTrue(Path(c["report_path"]).is_file())

    def test_changed_stage_c_prompt_preserves_b_and_invalidates_c(self):
        finish_bc(self.pipeline)
        b = self.pipeline.store.latest("B")
        prompt = self.root / "prompts/stage_c.md"
        prompt.write_text(prompt.read_text() + "\nSynthetic test prompt revision.\n")
        status = self.pipeline.status()
        self.assertEqual(status["stages"]["B"]["latest"]["revision_id"], b["revision_id"])
        self.assertIsNone(status["stages"]["C"]["latest"])

    def test_source_edit_rejects_old_response_and_invalidates_downstream(self):
        request = self.pipeline.prepare("B")["request_path"]
        path = self.root / "outputs/pov_reports/tank.md"
        path.write_text(path.read_text() + "\nSynthetic revision.\n")
        with self.assertRaises(ContractError):
            import_response(self.pipeline, "B", request, b_response())
        self.assertIsNone(self.pipeline.store.latest("B"))

    def test_tampered_bundle_and_superseded_task_rejected(self):
        request = Path(self.pipeline.prepare("B")["request_path"])
        (request / "prompt.md").write_text("Modified prompt")
        with self.assertRaises(ContractError):
            import_response(self.pipeline, "B", request, b_response())
        old = self.pipeline.prepare("B", force=True)["request_path"]
        self.pipeline.prepare("B", force=True)
        with self.assertRaises(ContractError):
            import_response(self.pipeline, "B", old, b_response())

    def test_upstream_limitations_need_coordinator_acceptance(self):
        path = self.root / "outputs/pov_reports/tank.md"
        path.write_text(path.read_text().replace("- Status: PASS", "- Status: PASS_WITH_LIMITATIONS"))
        with self.assertRaises(ContractError):
            self.pipeline.prepare("B")
        request = self.pipeline.prepare("B", accept_limitations=True)["request_path"]
        result = import_response(self.pipeline, "B", request, b_response(), accept_limitations=True)
        self.assertEqual(result["status"], "PASS_WITH_LIMITATIONS")
        report = Path(result["record"]["report_path"]).read_text()
        self.assertIn("- Status: PASS_WITH_LIMITATIONS", report)
        with self.assertRaises(ContractError):
            self.pipeline.prepare("C")

    def test_cli_help_and_actionable_failure(self):
        error, output = io.StringIO(), io.StringIO()
        with redirect_stderr(error), redirect_stdout(output):
            code = main(["prepare", "--stage", "C", "--project-root", str(self.root)])
        self.assertEqual(code, 2)
        self.assertIn("requires a passed Stage B", error.getvalue())

    def test_cli_process_prepares_imports_and_uses_custom_project_root(self):
        def run(command, *args):
            process = subprocess.run([
                sys.executable, str(REPOSITORY / "main.py"), command,
                "--project-root", str(self.root), *args,
            ], capture_output=True, text=True)
            self.assertEqual(process.returncode, 0, process.stderr)
            return json.loads(process.stdout)

        self.assertEqual(run("validate", "--stage", "B")["status"], "PASS")
        request = run("prepare", "--stage", "B")["request_path"]
        task = (Path(request) / "task.md").read_text()
        self.assertIn("--project-root", task)
        response_path = self.root / "cli-response.json"
        write_json(response_path, {
            "execution": {"tool": "synthetic CLI test", "model": "none", "operator": "software test"},
            "result": b_response(),
        })
        imported = run("import-result", "--stage", "B", "--request", request, "--response", str(response_path))
        self.assertEqual(imported["status"], "PASS")
        c = run("run", "--stage", "C")
        self.assertTrue(Path(c["request_path"]).is_dir())
        self.assertEqual(run("status")["stages"]["C"]["status"], "RUNNING")


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "FFmpeg integration requires system tools")
class ReleaseIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.pipeline = create_project(self.root, real_video=True)

    def tearDown(self):
        self.temp.cleanup()

    def audit(self, *, adverse=False, fail=False, no_refs=False):
        finish_bc(self.pipeline, adverse=adverse, no_refs=no_refs)
        request = Path(self.pipeline.prepare("D", accept_limitations=True)["request_path"])
        clips = read_json(request / "clip_index.json")["clips"]
        result = import_response(self.pipeline, "D", request, d_response(clips, adverse=adverse, fail=fail), accept_limitations=True)
        return result, request, clips

    def test_real_clip_bc_d_roundtrip_and_inconclusive_release(self):
        result, _, clips = self.audit()
        self.assertEqual(result["status"], "PASS")
        final = Path(result["release"]["final_path"]).read_text()
        self.assertIn("inconclusive", final)
        self.assertIn("SYNTHETIC tank", final)
        self.assertIn("Stage B uncertainty", final)
        self.assertTrue(Path(clips[0]["path"]).is_file())
        self.assertTrue(self.pipeline.prepare("D", accept_limitations=True)["cached"])

    def test_adverse_finding_requires_actual_review_attestation(self):
        result, _, _ = self.audit(adverse=True, fail=True)
        self.assertEqual(result["status"], "FAIL")
        self.assertIsNone(result["release"]["final_path"])
        self.assertIn("FAIL", Path(result["release"]["qa_path"]).read_text())

    def test_empty_c_claims_still_review_abstention_against_a(self):
        result, request, clips = self.audit(no_refs=True)
        self.assertEqual(len(clips), 5)
        self.assertIn("C established no cited claim", read_json(request / "context.json")["audit_scope"]["reason"])
        self.assertIsNotNone(result["release"]["final_path"])

    def test_changed_clip_revokes_cached_release(self):
        _, _, clips = self.audit()
        Path(clips[0]["path"]).write_bytes(b"changed evidence")
        status = self.pipeline.status()
        self.assertIsNone(status["release"]["latest"])
        self.assertEqual(status["stages"]["D"]["status"], "BLOCKED")

    def test_changed_original_revokes_cached_release(self):
        self.audit()
        (self.root / "inputs/videos/tank.mp4").write_bytes(b"changed original")
        with self.assertRaises(ContractError):
            self.pipeline.prepare("D", accept_limitations=True)
        self.assertIsNone(self.pipeline.status()["release"]["latest"])

    def test_failed_rereview_does_not_reuse_old_final(self):
        result, _, _ = self.audit()
        old_final = Path(result["release"]["final_path"])
        request = Path(self.pipeline.prepare("D", accept_limitations=True, force=True)["request_path"])
        clips = read_json(request / "clip_index.json")["clips"]
        failed = import_response(self.pipeline, "D", request, d_response(clips, fail=True), accept_limitations=True)
        self.assertEqual(failed["status"], "FAIL")
        self.assertIsNone(self.pipeline.status()["release"]["latest"]["final_path"])
        self.assertTrue(old_final.is_file(), "previous report must remain in immutable history")

    def test_cli_returns_nonzero_for_saved_failed_audit(self):
        finish_bc(self.pipeline)
        request = Path(self.pipeline.prepare("D")["request_path"])
        clips = read_json(request / "clip_index.json")["clips"]
        response = self.root / "failed-d.json"
        write_json(response, {
            "execution": {"tool": "synthetic CLI test", "model": "none", "operator": "software test"},
            "result": d_response(clips, fail=True),
        })
        output = io.StringIO()
        with redirect_stdout(output):
            code = main(["import-result", "--stage", "D", "--project-root", str(self.root),
                         "--request", str(request), "--response", str(response)])
        self.assertEqual(code, 1)
        result = json.loads(output.getvalue())
        self.assertEqual(result["status"], "FAIL")
        self.assertTrue(Path(result["release"]["qa_path"]).is_file())
        self.assertIsNone(result["release"]["final_path"])
