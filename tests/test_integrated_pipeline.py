"""Native Stage A -> B/C/D integration with explicitly synthetic recordings."""

from contextlib import redirect_stderr, redirect_stdout
import io
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from src import fusion
from src.cli import main
from src.contracts import ContractError, POV_IDS, read_json
from src.pipeline import DownstreamPipeline
from src.stage_a import StageAService
from tests.downstream_support import (
    REPOSITORY, b_response, c_response, d_response, import_response, source_report, write_json,
)


def integrated_project(root):
    """Create real decodable video; all gameplay/review statements are test data."""
    root = Path(root).resolve()
    for directory in ("config", "prompts", "inputs/videos", "submissions"):
        (root / directory).mkdir(parents=True, exist_ok=True)
    for stage in "abcd":
        shutil.copyfile(REPOSITORY / f"prompts/stage_{stage}.md", root / f"prompts/stage_{stage}.md")
    seed = root / "seed.mp4"
    subprocess.run([
        "ffmpeg", "-v", "error", "-nostdin", "-f", "lavfi", "-i",
        "color=c=blue:s=64x64:r=10:d=6", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(seed),
    ], check=True, capture_output=True)
    config = read_json(REPOSITORY / "config/run.example.json")
    config.update(run_id="native-test", fight_id="synthetic-fight", fight_start_timestamp=0.0, fight_end_timestamp=6.0)
    config["inspection_settings"]["frame_sampling_fps"] = 1
    for video in config["videos"]:
        shutil.copyfile(seed, root / video["path"])
    write_json(root / "config/run.json", config)
    return StageAService(root / "config/run.json", root)


def submit_synthetic_report(service, pov, *, reviewer="synthetic software test", job=None):
    prepared = service.prepare(pov) if job is None else {"job_path": str(job)}
    job_path = Path(prepared["job_path"])
    data = read_json(job_path / "job.json")
    report_path = service.root / "submissions" / f"{pov}.md"
    text = source_report(pov).replace("synthetic-test-a-v1", data["prompt_version"])
    report_path.write_text(text, encoding="utf-8")
    review_path = service.root / "submissions" / f"{pov}-review.json"
    write_json(review_path, {
        "reviewer": reviewer, "model_or_tool": "unittest synthetic attestation; no actual gameplay review",
        "reviewed_frame_timestamps": [1.0], "audio_inspected": False,
        "limitations": ["SYNTHETIC software fixture only; no real gameplay assertion."],
    })
    return service.submit(pov, job_path, report_path, review_path)


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "requires real FFmpeg tools")
class NativePipelineTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()
        self.service = integrated_project(self.root)

    def tearDown(self):
        self.temp.cleanup()

    def command(self, *arguments, expected=0):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = main([*arguments, "--config", str(self.service.config_path), "--project-root", str(self.root)])
        self.assertEqual(code, expected, err.getvalue() or out.getvalue())
        return json.loads(out.getvalue()) if out.getvalue() else {"error": err.getvalue()}

    def submit_five(self):
        return {pov: submit_synthetic_report(self.service, pov) for pov in POV_IDS}

    def finish_b(self):
        pipeline = DownstreamPipeline(self.service.config_path, self.root)
        request = pipeline.prepare("B", accept_limitations=True)["request_path"]
        import_response(pipeline, "B", request, b_response(), accept_limitations=True)
        return pipeline

    def test_cli_s0_a_b_c_d_round_trip_preserves_pending_audit_and_releases(self):
        self.assertEqual(self.command("validate")["status"], "PASS")
        for pov in POV_IDS:
            prepared = self.command("run", "--stage", "A", "--pov", pov, expected=1)
            self.assertEqual(prepared["status"], "BLOCKED")
            self.assertTrue(Path(prepared["job_path"]).is_dir())
            job = read_json(Path(prepared["job_path"]) / "job.json")
            report = self.root / "submissions" / f"{pov}.md"
            report.write_text(source_report(pov).replace("synthetic-test-a-v1", job["prompt_version"]), encoding="utf-8")
            review = self.root / "submissions" / f"{pov}-review.json"
            write_json(review, {
                "reviewer": "synthetic CLI integration test", "model_or_tool": "unittest; no actual gameplay review",
                "reviewed_frame_timestamps": [1.0], "audio_inspected": False,
                "limitations": ["Synthetic observation/attestation for software test only"],
            })
            record = self.command("submit", "--pov", pov, "--job", prepared["job_path"], "--report", str(report), "--review", str(review))
            self.assertEqual(record["status"], "PASS_WITH_LIMITATIONS")
        exported = self.command("handoff")
        self.assertEqual(exported["status"], "PASS_WITH_LIMITATIONS")
        inferred = DownstreamPipeline(self.service.config_path)
        self.assertEqual(inferred.root, self.root)
        self.command("validate", "--stage", "B", expected=2)
        validated = self.command("validate", "--stage", "B", "--accept-limitations")
        self.assertEqual(validated["status"], "PASS_WITH_LIMITATIONS")
        pipeline = self.finish_b()
        context = pipeline._context("C")
        self.assertEqual(set(context["pov_reports"]), set(POV_IDS))
        self.assertIn("stage_a_handoff", context)
        self.assertEqual(context["stage_a_handoff"]["human_evidence_audit"], "PENDING")
        for report in context["pov_reports"].values():
            self.assertEqual(report["provenance"]["human_evidence_audit"], "PENDING")
            self.assertEqual(report["handoff"]["status"], "PASS_WITH_LIMITATIONS")
        c_request = pipeline.prepare("C", accept_limitations=True)["request_path"]
        import_response(pipeline, "C", c_request, c_response(), accept_limitations=True)
        d_request = Path(pipeline.prepare("D", accept_limitations=True)["request_path"])
        clips = read_json(d_request / "clip_index.json")["clips"]
        result = import_response(pipeline, "D", d_request, d_response(clips), accept_limitations=True)
        self.assertEqual(result["status"], "PASS_WITH_LIMITATIONS")
        final = Path(result["release"]["final_path"]).read_text()
        self.assertIn("PENDING", final)
        self.assertIn("SYNTHETIC", final)
        self.assertIn("inconclusive", final)
        self.assertEqual(self.command("status")["stages"]["D"]["status"], "PASS_WITH_LIMITATIONS")

    def test_missing_fifth_report_blocks_handoff_and_b(self):
        for pov in POV_IDS[:-1]:
            submit_synthetic_report(self.service, pov)
        with self.assertRaises(ContractError):
            self.service.export_handoff()
        with self.assertRaises(ContractError):
            DownstreamPipeline(self.service.config_path, self.root)

    def test_new_review_invalidates_old_handoff_and_downstream(self):
        records = self.submit_five()
        self.service.export_handoff()
        pipeline = self.finish_b()
        old = pipeline.store.latest("B")
        submit_synthetic_report(self.service, "tank", reviewer="second synthetic reviewer")
        with self.assertRaises(ContractError):
            DownstreamPipeline(self.service.config_path, self.root)
        self.assertIsNone(pipeline.store.latest("B"))
        self.assertTrue(Path(old["report_path"]).exists())
        self.assertTrue(Path(records["tank"]["review_path"]).exists())
        self.service.export_handoff()
        refreshed = DownstreamPipeline(self.service.config_path, self.root)
        self.assertEqual(refreshed.validate(True)["status"], "PASS_WITH_LIMITATIONS")

    def test_edited_review_record_cannot_keep_b_current(self):
        records = self.submit_five()
        self.service.export_handoff()
        pipeline = self.finish_b()
        review = Path(records["tank"]["review_path"])
        data = read_json(review)
        data["reviewer"] = "modified without a new revision"
        write_json(review, data)
        with self.assertRaises(ContractError):
            pipeline.prepare("C", accept_limitations=True)
        self.assertIsNone(pipeline.store.latest("B"))

    def test_review_revision_changes_b_cache_even_when_report_text_is_identical(self):
        self.submit_five()
        self.service.export_handoff()
        pipeline = self.finish_b()
        first_context = pipeline._context("B")
        first_report_hash = first_context["pov_reports"]["tank"]["sha256"]
        submit_synthetic_report(self.service, "tank", reviewer="new synthetic observer record")
        self.service.export_handoff()
        updated = DownstreamPipeline(self.service.config_path, self.root)
        context = updated._context("B")
        self.assertEqual(context["pov_reports"]["tank"]["sha256"], first_report_hash)
        self.assertNotEqual(context["stage_a_handoff"]["source_hashes"], first_context["stage_a_handoff"]["source_hashes"])
        self.assertFalse(updated.prepare("B", accept_limitations=True)["cached"])

    def test_a_changes_after_validation_reject_stale_result_before_commit(self):
        self.submit_five()
        self.service.export_handoff()
        pipeline = DownstreamPipeline(self.service.config_path, self.root)
        request = pipeline.prepare("B", accept_limitations=True)["request_path"]
        render = fusion.render_report

        def render_then_change_a(payload, metadata):
            text = render(payload, metadata)
            submit_synthetic_report(self.service, "tank", reviewer="new A revision before commit guard")
            return text

        with patch("src.pipeline.fusion.render_report", side_effect=render_then_change_a):
            with self.assertRaises(ContractError):
                import_response(pipeline, "B", request, b_response(), accept_limitations=True)
        self.assertIsNone(pipeline.store.latest("B"))

    def test_intake_change_revokes_b_but_identical_revalidation_preserves_it(self):
        self.submit_five()
        self.service.export_handoff()
        pipeline = self.finish_b()
        original = pipeline.store.latest("B")
        self.service.validate()
        self.assertEqual(pipeline.store.latest("B")["revision_id"], original["revision_id"])
        config = read_json(self.service.config_path)
        config["fight_end_timestamp"] = 5.5
        write_json(self.service.config_path, config)
        self.service.validate()
        self.assertIsNone(pipeline.store.latest("B"))
        self.assertTrue(Path(original["report_path"]).exists())
