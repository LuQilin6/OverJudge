"""S0/A handoff validation; these are not S0 video-inspection tests."""

import copy
from pathlib import Path
import tempfile
import unittest

from src.contracts import ContractError, read_json, validate_manifest, validate_pov_report
from src.pipeline import DownstreamPipeline
from tests.downstream_support import create_project, source_report, write_json


class HandoffTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.pipeline = create_project(Path(self.temp.name))
        self.manifest = self.pipeline.manifest

    def tearDown(self):
        self.temp.cleanup()

    def test_all_five_reports_validate_and_cite_only_their_pov(self):
        output = self.pipeline.validate()
        self.assertEqual(output["status"], "PASS")
        self.assertEqual(output["evidence_reference_count"], 5)
        with self.assertRaises(ContractError):
            validate_pov_report(source_report("dps1"), "tank", self.manifest)

    def test_missing_pov_coverage_and_bad_interval_block(self):
        for mutate in (lambda m: m["videos"].pop(), lambda m: m.update(fight_end_timestamp=None),
                       lambda m: m["videos"][0].update(duration_seconds=1.0),
                       lambda m: m["videos"][0].update(sha256="not-a-hash"),
                       lambda m: m.update(prealigned_input_assumed=False)):
            manifest = copy.deepcopy(self.manifest)
            mutate(manifest)
            with self.assertRaises(ContractError):
                validate_manifest(manifest)

    def test_missing_section_or_blocked_handoff_cannot_start_b(self):
        for text in (source_report("tank").replace("## Player Information State", "## Other"),
                     source_report("tank").replace("- Status: PASS", "- Status: BLOCKED"),
                     source_report("tank").replace("- Stage: A", "- Stage: B"),
                     source_report("tank").replace("- Evidence coverage:", "- Missing field:"),
                     source_report("tank").replace("- prompt_version:", "- ignored_version:")):
            with self.assertRaises(ContractError):
                validate_pov_report(text, "tank", self.manifest)

    def test_config_recording_changes_require_new_manifest(self):
        config = copy.deepcopy(self.pipeline.config)
        config["videos"] = [{"pov_id": video["pov_id"], "path": video["path"]} for video in self.manifest["videos"]]
        config["videos"][0]["path"] = "inputs/videos/new-tank.mp4"
        write_json(self.pipeline.config_path, config)
        with self.assertRaises(ContractError):
            DownstreamPipeline(self.pipeline.config_path, self.pipeline.root)

    def test_failed_or_unevidenced_timeline_does_not_silently_pass(self):
        with self.assertRaises(ContractError):
            validate_pov_report(source_report("tank").replace("- Evidence: tank@1.0-2.0", "- Evidence: unavailable"), "tank", self.manifest)

    def test_json_rejects_duplicate_keys_and_nan(self):
        path = Path(self.temp.name) / "bad.json"
        for text in ('{"run_id":"one","run_id":"two"}', '{"value":NaN}'):
            path.write_text(text)
            with self.assertRaises(ContractError):
                read_json(path)
