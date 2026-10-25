"""Manual Stage A services with explicit synthetic video/review fixtures."""

from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from src.artifacts import ArtifactStore, digest
from src.contracts import ContractError, read_json
from src.stage_a import StageAService, validate_job
from tests.downstream_support import REPOSITORY, source_report, write_json


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "FFmpeg is required for Stage A integration tests")
class StageAServiceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.seed_temp = tempfile.TemporaryDirectory()
        cls.seed = Path(cls.seed_temp.name) / "synthetic.mp4"
        subprocess.run([
            "ffmpeg", "-v", "error", "-nostdin", "-f", "lavfi", "-i",
            "color=c=blue:s=64x64:r=10:d=3", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(cls.seed),
        ], check=True, capture_output=True)

    @classmethod
    def tearDownClass(cls):
        cls.seed_temp.cleanup()

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        for directory in ("config", "prompts", "inputs/videos"):
            (self.root / directory).mkdir(parents=True)
        data = json.loads((REPOSITORY / "config/run.example.json").read_text())
        data.update(run_id="stage-a-synthetic", fight_id="synthetic-fight", fight_start_timestamp=0.0, fight_end_timestamp=2.0)
        data["inspection_settings"] = {"method": "codex_manual", "frame_sampling_fps": 2, "inspect_audio": False}
        data["stage_tools"]["A"] = "codex_manual"
        self.config_path = self.root / "config/run.json"
        write_json(self.config_path, data)
        for video in data["videos"]:
            shutil.copyfile(self.seed, self.root / video["path"])
        shutil.copyfile(REPOSITORY / "prompts/stage_a.md", self.root / "prompts/stage_a.md")
        self.service = StageAService(self.config_path, self.root)

    def tearDown(self):
        self.temp.cleanup()

    def prepare(self, pov="tank", **kwargs):
        result = self.service.prepare(pov, **kwargs)
        self.assertEqual(result["status"], "BLOCKED")
        self.assertIsNotNone(result["job_path"], result.get("reason"))
        return Path(result["job_path"]), result

    def input_report(self, job, pov="tank", reviewer="Synthetic reviewer one"):
        data = read_json(job / "job.json")
        report = self.root / f"submitted-{pov}.md"
        report.write_text(source_report(pov).replace("synthetic-test-a-v1", data["prompt_version"]).replace("0.0–6.0", "0.0–2.0"))
        review = self.root / f"review-{pov}.json"
        write_json(review, {
            "reviewer": reviewer, "model_or_tool": "unittest synthetic attestation, no real gameplay review",
            "reviewed_frame_timestamps": [frame["timestamp"] for frame in data["inspection"]["frames"]],
            "audio_inspected": False, "limitations": ["Synthetic test only; no actual gameplay analysis"],
        })
        return report, review

    def test_prepare_preserves_original_timestamps_and_cache_provenance(self):
        source = self.root / "inputs/videos/tank.mp4"
        before = digest(source)
        job, first = self.prepare()
        data = validate_job(job, self.service.config, self.root, "tank")
        self.assertEqual(data["interval"], [0.0, 2.0])
        self.assertEqual([frame["timestamp"] for frame in data["inspection"]["frames"]], [0.0, 0.5, 1.0, 1.5])
        self.assertFalse(any(frame["inspected"] for frame in data["inspection"]["frames"]))
        cached_job, cached = self.prepare()
        self.assertEqual(cached_job, job)
        self.assertTrue(cached["cached"])
        self.assertEqual(digest(source), before)
        self.assertFalse(first["cached"])

    def test_missing_or_modified_frame_creates_new_revision(self):
        first, _ = self.prepare()
        data = read_json(first / "job.json")
        Path(data["inspection"]["frames"][0]["path"]).unlink()
        second, response = self.prepare()
        self.assertNotEqual(first, second)
        self.assertFalse(response["cached"])
        self.assertTrue((first / "job.json").is_file(), "failed cache must remain in history")
        second_data = read_json(second / "job.json")
        Path(second_data["inspection"]["frames"][0]["path"]).write_bytes(b"modified evidence")
        third, _ = self.prepare()
        self.assertNotEqual(second, third)

    def test_force_creates_new_job_without_overwriting_old(self):
        first, _ = self.prepare()
        before = digest(first / "job.json")
        second, result = self.prepare(force=True)
        self.assertNotEqual(first, second)
        self.assertFalse(result["cached"])
        self.assertEqual(before, digest(first / "job.json"))

    def test_inspection_or_prompt_snapshot_changes_invalidate_cache(self):
        first, _ = self.prepare()
        (first / "prompt.md").write_text("modified prompt snapshot")
        with self.assertRaises(ContractError):
            validate_job(first, self.service.config, self.root, "tank")
        second, _ = self.prepare()
        inspection = second / "frames/inspection.json"
        inspection.write_text('{"frames":[]}')
        with self.assertRaises(ContractError):
            validate_job(second, self.service.config, self.root, "tank")
        third, _ = self.prepare()
        self.assertNotEqual(second, third)

    def test_stale_sampling_job_cannot_be_submitted(self):
        job, _ = self.prepare()
        report, review = self.input_report(job)
        config = read_json(self.config_path)
        config["inspection_settings"]["frame_sampling_fps"] = 4
        write_json(self.config_path, config)
        with self.assertRaisesRegex(ContractError, "Stale Stage A"):
            self.service.submit("tank", job, report, review)
        new_job, _ = self.prepare()
        self.assertNotEqual(job, new_job)
        self.assertEqual(len(read_json(new_job / "job.json")["inspection"]["frames"]), 8)

    def test_source_or_frame_change_blocks_report_import(self):
        job, _ = self.prepare()
        report, review = self.input_report(job)
        data = read_json(job / "job.json")
        Path(data["inspection"]["frames"][1]["path"]).unlink()
        with self.assertRaisesRegex(ContractError, "frame is missing or changed"):
            self.service.submit("tank", job, report, review)
        new_job, _ = self.prepare()
        report, review = self.input_report(new_job)
        source = self.root / "inputs/videos/tank.mp4"
        source.write_bytes(source.read_bytes() + b"changed source")
        with self.assertRaisesRegex(ContractError, "Stale Stage A"):
            self.service.submit("tank", new_job, report, review)

    def test_different_reviews_are_immutable_and_exact_import_is_idempotent(self):
        job, _ = self.prepare()
        report, review = self.input_report(job)
        first = self.service.submit("tank", job, report, review)
        index_before = digest(self.service.output / "stage_a_index.json")
        self.assertEqual(first, self.service.submit("tank", job, report, review))
        self.assertEqual(index_before, digest(self.service.output / "stage_a_index.json"))
        original_review = Path(first["review_path"]).read_bytes()
        record = read_json(review)
        record["reviewer"] = "Synthetic reviewer two"
        write_json(review, record)
        second = self.service.submit("tank", job, report, review)
        self.assertNotEqual(first["revision_id"], second["revision_id"])
        self.assertEqual(Path(first["review_path"]).read_bytes(), original_review)
        index = read_json(self.service.output / "stage_a_index.json")
        self.assertEqual(index["reports"]["tank"], second)
        self.assertEqual(len(index["history"]["tank"]), 2)
        provenance = read_json(second["provenance_path"])
        self.assertEqual(provenance["human_evidence_audit"], "PENDING")
        self.assertEqual(provenance["status"], "PASS_WITH_LIMITATIONS")

    def test_existing_revision_tamper_is_never_overwritten(self):
        job, _ = self.prepare()
        report, review = self.input_report(job)
        record = self.service.submit("tank", job, report, review)
        Path(record["review_path"]).write_text("changed historical review")
        with self.assertRaisesRegex(ContractError, "refusing to overwrite history"):
            self.service.submit("tank", job, report, review)

    def test_new_review_revokes_downstream_under_index_lock_and_preserves_history(self):
        import fcntl

        job, _ = self.prepare()
        report, review = self.input_report(job)
        original_a = self.service.submit("tank", job, report, review)
        downstream_index = self.service.output.parent / "runs" / self.service.config.run_id / "run_metadata.json"
        self.assertFalse(downstream_index.exists(), "A-only work must not create unused downstream metadata")
        store = ArtifactStore(self.service.output.parent, self.service.config.run_id)
        saved = {}
        for stage in ("B", "C", "D"):
            store.save_request(stage, {"synthetic": True}, f"Synthetic {stage} prompt")
            saved[stage] = store.save_result(stage, {"synthetic": True}, f"# Synthetic {stage}", {"status": "PASS"})
        release = store.write_release("Synthetic QA", "Synthetic final report", {"status": "PASS"})
        original_a_hashes = {name: digest(original_a[name]) for name in ("report_path", "review_path", "provenance_path")}
        # Identical replay is idempotent and keeps the current accepted results.
        self.assertEqual(self.service.submit("tank", job, report, review), original_a)
        self.assertEqual(read_json(store.metadata_path)["release"]["latest"], release)
        self.assertTrue(all(store.latest(stage) is not None for stage in ("B", "C", "D")))

        new_review = read_json(review)
        new_review["reviewer"] = "Synthetic reviewer with a new revision"
        write_json(review, new_review)
        invalidate = ArtifactStore.invalidate_from
        def assert_a_lock_held(current_store, stage):
            with (self.service.output / ".stage_a_index.lock").open("rb") as lock:
                try:
                    fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError:
                    pass
                else:
                    fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
                    self.fail("downstream invalidation must occur before releasing the A index lock")
            return invalidate(current_store, stage)
        with patch("src.stage_a.ArtifactStore.invalidate_from", autospec=True, side_effect=assert_a_lock_held) as invalidation:
            updated = self.service.submit("tank", job, report, review)
        invalidation.assert_called_once()
        self.assertNotEqual(updated["revision_id"], original_a["revision_id"])
        index = read_json(store.metadata_path)
        self.assertIsNone(index["release"]["latest"])
        self.assertTrue(all(store.latest(stage) is None for stage in ("B", "C", "D")))
        self.assertTrue(all(index["stages"][stage]["status"] == "PENDING" for stage in ("B", "C", "D")))
        self.assertTrue(Path(release["final_path"]).is_file())
        self.assertTrue(all(Path(record["result_path"]).is_file() for record in saved.values()))
        self.assertEqual(original_a_hashes, {name: digest(original_a[name]) for name in original_a_hashes})

    def test_review_types_and_actual_frame_membership_are_checked(self):
        job, _ = self.prepare()
        report, review = self.input_report(job)
        original = read_json(review)
        variants = [
            {**original, "reviewer": 123}, {**original, "model_or_tool": ""},
            {**original, "reviewed_frame_timestamps": [True]},
            {**original, "reviewed_frame_timestamps": [0.1]},
            {**original, "reviewed_frame_timestamps": [10 ** 1000]},
            {**original, "reviewed_frame_timestamps": [0.0, 0.0]},
            {**original, "audio_inspected": True}, {**original, "limitations": "not a list"},
        ]
        for record in variants:
            with self.subTest(record=record):
                write_json(review, record)
                with self.assertRaises(ContractError):
                    self.service.submit("tank", job, report, review)

    def test_report_cannot_claim_unreviewed_event_or_evidence_window(self):
        job, _ = self.prepare()
        report, review = self.input_report(job)
        record = read_json(review)
        record["reviewed_frame_timestamps"] = [0.0]
        write_json(review, record)
        with self.assertRaisesRegex(ContractError, "event interval"):
            self.service.submit("tank", job, report, review)
        record["reviewed_frame_timestamps"] = [1.0]
        write_json(review, record)
        self.service.submit("tank", job, report, review)
        # A wider event heading cannot hide the fact that its specific cited
        # window has never been reviewed.
        report.write_text(report.read_text().replace("### [1.0–2.0 s]", "### [0.0–2.0 s]"))
        record["reviewed_frame_timestamps"] = [0.0]
        write_json(review, record)
        with self.assertRaisesRegex(ContractError, "evidence interval"):
            self.service.submit("tank", job, report, review)

    def test_manifest_path_cannot_overwrite_inputs_configuration_or_history(self):
        original = read_json(self.config_path)
        evidence = self.root / "inputs/videos/tank.mp4"
        evidence_hash = digest(evidence)
        other_store = ArtifactStore(self.service.output.parent, "another-run")
        metadata_hash = digest(other_store.metadata_path)
        for target in ("inputs/videos/tank.mp4", "config/run.json", "prompts/stage_a.md",
                       "outputs/stage-a-synthetic/stage_a_index.json",
                       "outputs/stage-a-synthetic/pov_reports/history/report.md",
                       "outputs/runs/another-run/run_metadata.json",
                       "outputs/runs/another-run/stages/B/results/revision/result.json"):
            with self.subTest(target=target):
                data = {**original, "manifest_path": target}
                write_json(self.config_path, data)
                with self.assertRaisesRegex(ContractError, "must not overwrite"):
                    StageAService(self.config_path, self.root)
                self.assertEqual(digest(evidence), evidence_hash)
                self.assertEqual(digest(other_store.metadata_path), metadata_hash)
        write_json(self.config_path, original)

    def test_report_prompt_and_blocked_handoff_are_rejected(self):
        job, _ = self.prepare()
        report, review = self.input_report(job)
        original = report.read_text()
        report.write_text(original.replace("- prompt_version:", "- prompt_version: wrong-"))
        with self.assertRaises(ContractError):
            self.service.submit("tank", job, report, review)
        report.write_text(original.replace("- Status: PASS", "- Status: BLOCKED"))
        with self.assertRaises(ContractError):
            self.service.submit("tank", job, report, review)

    def test_pilot_prepares_one_pov_while_retaining_blocked_full_intake(self):
        (self.root / "inputs/videos/dps1.mp4").unlink()
        job, result = self.prepare()
        self.assertEqual(result["intake_status"], "BLOCKED")
        self.assertTrue((job / "job.json").is_file())
        manifest = read_json(self.service.manifest_path)
        self.assertEqual(manifest["status"], "BLOCKED")
        self.assertEqual(manifest["videos"][0]["coverage_status"], "complete")

    def test_concurrent_pov_imports_preserve_both_index_entries(self):
        inputs = []
        for pov in ("tank", "dps1"):
            job, _ = self.prepare(pov)
            report, review = self.input_report(job, pov)
            inputs.append((pov, job, report, review))
        def submit(values):
            return StageAService(self.config_path, self.root).submit(*values)
        with ThreadPoolExecutor(max_workers=2) as pool:
            records = list(pool.map(submit, inputs))
        index = read_json(self.service.output / "stage_a_index.json")
        self.assertEqual(set(index["reports"]), {"tank", "dps1"})
        self.assertTrue(all(Path(record["report_path"]).is_file() for record in records))
