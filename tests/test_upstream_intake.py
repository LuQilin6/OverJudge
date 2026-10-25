"""S0 metadata and original-time sampling tests; gameplay remains unreviewed."""

from pathlib import Path
import json
import math
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from src.contracts import sha256_file, validate_manifest
from src.intake import POVS, RunConfig, load_config, probe, validate_inputs
from src.video_inspection import extract_frames


def config_data():
    return {
        "run_id": "upstream-test", "fight_id": "synthetic-fight", "game": "Overwatch 2",
        "prealigned_input_assumed": True,
        "fight_start_timestamp": 10.0, "fight_end_timestamp": 30.0,
        "videos": [{"pov_id": pov, "path": f"inputs/videos/{pov}.mp4", "hero": "unknown"} for pov in POVS],
        "prompts": {"A": "prompts/stage_a.md", "B": "prompts/stage_b.md"},
        "stage_tools": {"A": "codex_manual", "B": {"method": "manual", "tool": "Codex"}},
        "inspection_settings": {"method": "codex_manual", "frame_sampling_fps": 2.0, "inspect_audio": False},
    }


class IntakeTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name).resolve()

    def tearDown(self):
        self.temporary.cleanup()

    def create_sources(self, config):
        for video in config.videos:
            path = self.root / video.path
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"synthetic metadata fixture; not a decodable video")

    def test_shared_downstream_configuration_fields_are_accepted(self):
        data = config_data()
        data.update(manifest_path="outputs/upstream-test/manifest.json",
                    pov_reports_directory="outputs/pov_reports",
                    stage_a_handoff_path="outputs/upstream-test/handoff.json")
        parsed = RunConfig.model_validate(data)
        self.assertEqual(parsed.stage_tools["B"]["method"], "manual")
        self.assertEqual(parsed.manifest_path, "outputs/upstream-test/manifest.json")

    def test_duplicate_ids_and_wrong_game_rejected(self):
        data = config_data()
        data["videos"][1]["pov_id"] = "tank"
        with self.assertRaises(ValueError):
            RunConfig.model_validate(data)
        data = config_data()
        data["game"] = "Another game"
        with self.assertRaises(ValueError):
            RunConfig.model_validate(data)

    def test_whitespace_only_values_cannot_produce_an_incompatible_manifest(self):
        for field in ("fight_id", "output_directory", "manifest_path", "pov_reports_directory", "stage_a_handoff_path"):
            with self.subTest(field=field):
                data = config_data()
                data[field] = "  "
                with self.assertRaises(ValueError):
                    RunConfig.model_validate(data)
        for field in ("path", "hero"):
            with self.subTest(video_field=field):
                data = config_data()
                data["videos"][0][field] = "  "
                with self.assertRaises(ValueError):
                    RunConfig.model_validate(data)
    def test_numbers_are_finite_and_not_boolean_or_numeric_strings(self):
        for field, value in (("fight_start_timestamp", True), ("fight_end_timestamp", math.inf),
                             ("fight_end_timestamp", math.nan), ("fight_end_timestamp", "30")):
            with self.subTest(field=field, value=value):
                data = config_data()
                data[field] = value
                with self.assertRaises(ValueError):
                    RunConfig.model_validate(data)
        data = config_data()
        data["inspection_settings"]["frame_sampling_fps"] = False
        with self.assertRaises(ValueError):
            RunConfig.model_validate(data)
        for field, value in (("prealigned_input_assumed", 1),):
            data = config_data()
            data[field] = value
            with self.assertRaises(ValueError):
                RunConfig.model_validate(data)

    def test_configuration_resolves_explicit_and_conventional_roots(self):
        conventional = self.root / "config/run.json"
        conventional.parent.mkdir()
        conventional.write_text(json.dumps(config_data()))
        _, inferred = load_config(conventional)
        self.assertEqual(inferred, self.root)
        _, explicit = load_config("config/run.json", project_root=self.root)
        self.assertEqual(explicit, self.root)

    def test_missing_inputs_are_blocked_without_fabricated_metadata(self):
        result = validate_inputs(RunConfig.model_validate(config_data()), self.root)
        self.assertEqual(result["status"], "BLOCKED")
        self.assertEqual(len(result["errors"]), 5)
        self.assertTrue(all(video["coverage_status"] == "blocked" for video in result["videos"]))
        self.assertTrue(all("sha256" not in video for video in result["videos"]))

    def test_short_recording_uses_shared_missing_interval_objects(self):
        config = RunConfig.model_validate(config_data())
        self.create_sources(config)
        metadata = dict(duration_seconds=20.0, fps=30.0, width=640, height=480, audio_present=False)
        with patch("src.intake.probe", return_value=metadata):
            result = validate_inputs(config, self.root)
        self.assertEqual(result["status"], "BLOCKED")
        self.assertEqual(result["videos"][0]["missing_intervals"], [
            {"start_timestamp": 20.0, "end_timestamp": 30.0},
        ])

    def test_complete_manifest_is_directly_accepted_by_downstream_contract(self):
        config = RunConfig.model_validate(config_data())
        self.create_sources(config)
        metadata = dict(duration_seconds=30.0, fps=30.0, width=640, height=480, audio_present=False)
        with patch("src.intake.probe", return_value=metadata):
            manifest = validate_inputs(config, self.root)
        self.assertEqual(manifest["status"], "PASS")
        self.assertEqual(validate_manifest(manifest), manifest)
        self.assertIn("does not verify synchronization", manifest["limitations"][0])

    def test_duplicate_resolved_recording_paths_are_blocked(self):
        data = config_data()
        data["videos"][1]["path"] = "inputs/videos/./tank.mp4"
        config = RunConfig.model_validate(data)
        self.create_sources(config)
        metadata = dict(duration_seconds=30.0, fps=30.0, width=640, height=480, audio_present=False)
        with patch("src.intake.probe", return_value=metadata):
            manifest = validate_inputs(config, self.root)
        self.assertEqual(manifest["status"], "BLOCKED")
        self.assertTrue(all(manifest["videos"][i]["coverage_status"] == "blocked" for i in (0, 1)))
        self.assertIn("distinct resolved recording path", manifest["videos"][0]["error"])

    def test_probe_rejects_nonfinite_metadata(self):
        document = {"streams": [{"codec_type": "video", "avg_frame_rate": "30/1", "duration": "nan", "width": 64, "height": 64}], "format": {}}
        completed = subprocess.CompletedProcess([], 0, stdout=json.dumps(document))
        with patch("src.intake.subprocess.run", return_value=completed):
            with self.assertRaises(ValueError):
                probe(self.root / "synthetic.mp4")


class FrameSamplingTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.video = self.root / "source.mp4"
        self.video.write_bytes(b"synthetic frame extraction test input")

    def tearDown(self):
        self.temporary.cleanup()

    def test_absolute_times_hashes_and_pending_inspection_are_recorded(self):
        def fake_run(args, **kwargs):
            self.assertIn("-n", args)
            self.assertNotIn("-y", args)
            self.assertIn("timeout", kwargs)
            Path(args[-1]).write_bytes(b"synthetic extracted image for hashing only")

        with patch("src.video_inspection.subprocess.run", side_effect=fake_run):
            inspection = extract_frames(self.video, 12.0, 13.0, 2.0, self.root / "frames")
        self.assertEqual([frame["timestamp"] for frame in inspection["frames"]], [12.0, 12.5])
        self.assertTrue(all(not frame["inspected"] for frame in inspection["frames"]))
        self.assertEqual(inspection["status"], "AWAITING_INSPECTION")
        self.assertFalse(inspection["audio_inspected"])
        for frame in inspection["frames"]:
            self.assertEqual(frame["sha256"], sha256_file(frame["path"]))
        saved = json.loads((self.root / "frames/inspection.json").read_text())
        self.assertEqual(saved, inspection)

    def test_existing_frame_set_is_not_overwritten(self):
        directory = self.root / "frames"
        directory.mkdir()
        existing = directory / "frame_000000.jpg"
        existing.write_bytes(b"preserve this image")
        with patch("src.video_inspection.subprocess.run") as process:
            with self.assertRaises(ValueError):
                extract_frames(self.video, 0.0, 1.0, 2.0, directory)
        process.assert_not_called()
        self.assertEqual(existing.read_bytes(), b"preserve this image")

    def test_invalid_sampling_or_empty_output_blocks(self):
        for arguments in ((True, 1.0, 2.0), (0.0, math.inf, 2.0), (0.0, 1.0, 0.0)):
            with self.subTest(arguments=arguments), self.assertRaises(ValueError):
                extract_frames(self.video, *arguments, self.root / "frames")

        def empty_output(args, **kwargs):
            Path(args[-1]).touch()
        with patch("src.video_inspection.subprocess.run", side_effect=empty_output):
            with self.assertRaises(ValueError):
                extract_frames(self.video, 0.0, 1.0, 2.0, self.root / "empty-frames")


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "FFmpeg/ffprobe required")
class RealMediaTests(unittest.TestCase):
    def test_real_metadata_and_nonzero_original_time_extraction(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.mp4"
            subprocess.run([
                "ffmpeg", "-v", "error", "-nostdin", "-f", "lavfi", "-i",
                "color=c=blue:s=64x64:r=10:d=2", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(source),
            ], check=True, capture_output=True, timeout=120)
            metadata = probe(source)
            self.assertAlmostEqual(metadata["duration_seconds"], 2.0, delta=0.1)
            self.assertEqual((metadata["width"], metadata["height"]), (64, 64))
            self.assertFalse(metadata["audio_present"])
            original_hash = sha256_file(source)
            inspection = extract_frames(source, 1.0, 2.0, 2.0, root / "frames")
            self.assertEqual([frame["timestamp"] for frame in inspection["frames"]], [1.0, 1.5])
            self.assertTrue(all(Path(frame["path"]).stat().st_size > 0 for frame in inspection["frames"]))
            self.assertEqual(sha256_file(source), original_hash)


if __name__ == "__main__":
    unittest.main()
