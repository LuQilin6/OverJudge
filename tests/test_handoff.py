"""A handoffs bind actual files and explicit report/reviewer revisions.

The video and review statements here are synthetic software fixtures. These
tests exercise provenance and stage gates, not gameplay-analysis quality.
"""

import copy
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

from src.contracts import ContractError, POV_IDS, read_json, sha256_file
from src.artifacts import ArtifactStore
from src.handoff import export_handoff, load_stage_a_handoff
from src.stage_a import StageAService
from tests.downstream_support import REPOSITORY, create_project, source_report, write_json


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "A handoff integration requires FFmpeg")
class StageAHandoffTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        base = create_project(self.root, real_video=True)
        self.config = copy.deepcopy(base.config)
        self.config.update({
            "fight_start_timestamp": 1.0, "fight_end_timestamp": 2.0,
            "videos": [{"pov_id": video["pov_id"], "path": video["path"], "hero": "unknown"}
                       for video in base.manifest["videos"]],
            "inspection_settings": {"method": "codex_manual", "frame_sampling_fps": 2, "inspect_audio": False},
            "stage_tools": {"A": "codex_manual"},
        })
        shutil.copyfile(REPOSITORY / "prompts/stage_a.md", self.root / "prompts/stage_a.md")
        self.config["prompts"]["A"] = "prompts/stage_a.md"
        self.config_path = self.root / "config/run.json"
        write_json(self.config_path, self.config)
        self.service = StageAService(self.config_path, self.root)
        self.jobs = {}
        self.reports = {}
        self.reviews = {}
        prompt = (self.root / "prompts/stage_a.md").read_text()
        self.version = re.search(r"(?m)^prompt_version:\s*(\S+)", prompt)[1]
        for pov in POV_IDS:
            prepared = self.service.prepare(pov)
            self.assertIsNotNone(prepared.get("job_path"), prepared)
            self.jobs[pov] = Path(prepared["job_path"])
            self.reports[pov] = self.root / f"{pov}.report.md"
            self.reports[pov].write_text(
                source_report(pov).replace("synthetic-test-a-v1", self.version)
                .replace("Aligned-video interval: 0.0–6.0", "Aligned-video interval: 1.0–2.0"),
                encoding="utf-8",
            )
            self.reviews[pov] = self.root / f"{pov}.review.json"
            write_json(self.reviews[pov], {
                "reviewer": "Synthetic software-test reviewer", "model_or_tool": "unittest; no model call",
                "reviewed_frame_timestamps": [1.0, 1.5], "audio_inspected": False,
                "limitations": ["Synthetic test attestation only; no real gameplay was inspected."],
            })
            self.service.submit(pov, self.jobs[pov], self.reports[pov], self.reviews[pov])
        self.output = self.root / "outputs" / self.config["run_id"]

    def tearDown(self):
        self.temp.cleanup()

    def export(self):
        return export_handoff(self.config_path, self.root)

    def load(self, result):
        return load_stage_a_handoff(result["path"], self.config, self.root)

    def test_five_actual_jobs_export_without_promoting_pending_audit(self):
        result = self.export()
        loaded = self.load(result)
        self.assertEqual(result["status"], "PASS_WITH_LIMITATIONS")
        self.assertEqual(result["human_evidence_audit"], "PENDING")
        self.assertEqual(set(loaded["reports"]), set(POV_IDS))
        for pov in POV_IDS:
            report = loaded["reports"][pov]
            self.assertEqual(report["handoff"]["status"], "PASS_WITH_LIMITATIONS")
            self.assertEqual(report["handoff"]["reported_status"], "PASS")
            self.assertEqual(report["provenance"]["human_evidence_audit"], "PENDING")
            self.assertIn(f"{pov}/review", loaded["source_hashes"])
            self.assertIn(f"{pov}/frame/0", loaded["source_hashes"])
        self.assertTrue(all(isinstance(key, str) and isinstance(value, str)
                            for key, value in loaded["source_hashes"].items()))

    def test_identical_export_reuses_immutable_snapshot(self):
        first = self.export()
        before = Path(first["snapshot_path"]).stat().st_mtime_ns
        second = self.export()
        self.assertEqual(first["snapshot_path"], second["snapshot_path"])
        self.assertEqual(Path(first["snapshot_path"]).stat().st_mtime_ns, before)
        self.assertEqual(sha256_file(first["snapshot_path"]), first["sha256"])

    def test_missing_pov_does_not_export_a_partial_handoff(self):
        index_path = self.output / "stage_a_index.json"
        index = read_json(index_path)
        del index["reports"]["support2"]
        write_json(index_path, index)
        with self.assertRaises(ContractError):
            self.export()

    def test_blocked_s0_does_not_export_five_structurally_imported_reports(self):
        path = self.output / "manifest.json"
        manifest = read_json(path)
        manifest["status"] = "BLOCKED"
        write_json(path, manifest)
        with self.assertRaises(ContractError):
            self.export()

    def test_changed_report_review_or_provenance_is_not_silently_accepted(self):
        result = self.export()
        index = read_json(self.output / "stage_a_index.json")
        for field in ("report_path", "review_path", "provenance_path"):
            with self.subTest(field=field):
                path = Path(index["reports"]["tank"][field])
                original = path.read_bytes()
                path.write_bytes(original + b"\nchanged\n")
                with self.assertRaises(ContractError):
                    self.load(result)
                path.write_bytes(original)

    def test_changed_source_video_revokes_handoff(self):
        result = self.export()
        (self.root / "inputs/videos/tank.mp4").write_bytes(b"changed source")
        with self.assertRaises(ContractError):
            self.load(result)

    def test_missing_frame_revokes_handoff(self):
        result = self.export()
        (self.jobs["tank"] / "frames/frame_000000.jpg").unlink()
        with self.assertRaises(ContractError):
            self.load(result)

    def test_changed_sampling_or_hero_cannot_reuse_old_jobs(self):
        result = self.export()
        for change in ("sampling", "hero"):
            config = copy.deepcopy(self.config)
            if change == "sampling":
                config["inspection_settings"]["frame_sampling_fps"] = 4
            else:
                config["videos"][0]["hero"] = "A different hero"
            with self.subTest(change=change), self.assertRaises(ContractError):
                load_stage_a_handoff(result["path"], config, self.root)

    def test_new_review_requires_explicit_reexport_and_changes_source_hashes(self):
        first = self.export()
        old = self.load(first)
        review = read_json(self.reviews["tank"])
        review["reviewer"] = "Another synthetic reviewer"
        write_json(self.reviews["tank"], review)
        self.service.submit("tank", self.jobs["tank"], self.reports["tank"], self.reviews["tank"])
        with self.assertRaises(ContractError):
            self.load(first)
        second = self.export()
        new = self.load(second)
        self.assertNotEqual(first["snapshot_path"], second["snapshot_path"])
        self.assertEqual(old["reports"]["tank"]["sha256"], new["reports"]["tank"]["sha256"])
        self.assertNotEqual(old["source_hashes"]["tank/review"], new["source_hashes"]["tank/review"])
        self.assertTrue(Path(first["snapshot_path"]).is_file())

    def test_markdown_pass_cannot_override_blocked_provenance(self):
        index_path = self.output / "stage_a_index.json"
        index = read_json(index_path)
        record = index["reports"]["tank"]
        path = Path(record["provenance_path"])
        provenance = read_json(path)
        provenance["status"] = "BLOCKED"
        write_json(path, provenance)
        record["provenance_sha256"] = sha256_file(path)
        write_json(index_path, index)
        with self.assertRaises(ContractError):
            self.export()

    def test_handoff_file_cannot_claim_an_audit_pass(self):
        result = self.export()
        path = Path(result["path"])
        bundle = read_json(path)
        bundle["status"] = "PASS"
        bundle["human_evidence_audit"] = "PASS"
        write_json(path, bundle)
        with self.assertRaises(ContractError):
            self.load(result)

    def test_changed_manifest_or_current_prompt_is_rejected(self):
        result = self.export()
        manifest = self.output / "manifest.json"
        original = manifest.read_bytes()
        manifest.write_bytes(original + b"\n")
        with self.assertRaises(ContractError):
            self.load(result)
        manifest.write_bytes(original)
        prompt = self.root / "prompts/stage_a.md"
        prompt.write_text(prompt.read_text() + "\nChanged prompt.\n")
        with self.assertRaises(ContractError):
            self.load(result)

    def test_custom_pointer_cannot_overwrite_sources_config_or_history(self):
        result = self.export()
        paths = ["inputs/videos/tank.mp4", "prompts/stage_a.md", "config/run.json",
                 str(self.output / "manifest.json"), str(self.output / "stage_a_index.json"),
                 result["snapshot_path"]]
        for path in paths:
            with self.subTest(path=path):
                config = copy.deepcopy(self.config)
                config["stage_a_handoff_path"] = path
                write_json(self.config_path, config)
                target = Path(path)
                if not target.is_absolute():
                    target = self.root / target
                before = target.read_bytes()
                with self.assertRaises(ContractError):
                    self.export()
                self.assertEqual(target.read_bytes(), before)
        write_json(self.config_path, self.config)

    def test_loader_reuses_callers_index_lock_without_reacquiring_flock(self):
        result = self.export()
        # A subprocess timeout makes a future accidental nested flock fail
        # deterministically instead of hanging the entire test suite.
        script = """import json, sys
from pathlib import Path
from src.artifacts import file_lock
from src.handoff import load_stage_a_handoff
root = Path(sys.argv[1])
config = json.loads((root / 'config/run.json').read_text())
output = root / config['output_directory'] / config['run_id']
with file_lock(output / '.stage_a_index.lock'):
    loaded = load_stage_a_handoff(sys.argv[2], config, root, already_locked=True)
    print(loaded['status'])
"""
        completed = subprocess.run([sys.executable, "-c", script, str(self.root), result["path"]],
                                   cwd=REPOSITORY, capture_output=True, text=True, timeout=5)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(completed.stdout.strip(), "PASS_WITH_LIMITATIONS")

    def test_custom_pointer_cannot_overwrite_current_or_other_downstream_run(self):
        current = self.root / "outputs/runs" / self.config["run_id"] / "run_metadata.json"
        other = ArtifactStore(self.root / "outputs", "another-run").metadata_path
        for target in (current, other):
            with self.subTest(target=target):
                config = copy.deepcopy(self.config)
                config["stage_a_handoff_path"] = str(target)
                write_json(self.config_path, config)
                before = sha256_file(target)
                with self.assertRaises(ContractError):
                    self.export()
                self.assertEqual(sha256_file(target), before)
        write_json(self.config_path, self.config)

    def test_custom_pointer_cannot_overwrite_another_stage_a_run(self):
        target = self.root / "outputs/another-a-run/manifest.json"
        target.parent.mkdir()
        write_json(target, {"synthetic": "another run's manifest"})
        config = copy.deepcopy(self.config)
        config["stage_a_handoff_path"] = str(target)
        write_json(self.config_path, config)
        before = sha256_file(target)
        with self.assertRaises(ContractError):
            self.export()
        self.assertEqual(sha256_file(target), before)


if __name__ == "__main__":
    unittest.main()
