"""Stage D gate and extraction tests; no model calls are made."""

import copy
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from overjudge.audit import (
    CHECK_FLAGS,
    extract_evidence_clips,
    render_final_report,
    render_qa_report,
    required_evidence_refs,
    validate_result,
)
from overjudge.contracts import ContractError, POV_IDS, sha256_file


REF = "tank@1.0-2.0"


def fixture_manifest(source, digest):
    return {
        "run_id": "test", "game": "Overwatch 2", "fight_id": "fight",
        "prealigned_input_assumed": True,
        "fight_start_timestamp": 0.0, "fight_end_timestamp": 3.0,
        "videos": [{
            "pov_id": pov_id, "path": str(source), "sha256": digest,
            "duration_seconds": 3.0, "fps": 10.0, "width": 64, "height": 64,
            "audio_present": False, "hero": "unknown", "coverage_status": "complete",
            "missing_intervals": [],
        } for pov_id in POV_IDS],
    }


def fixture_verdict():
    return {
        "findings": [{
            "id": "finding_1", "pov_id": "tank", "level": "primary",
            "claim": "A supported candidate action, not causal proof",
            "evidence_refs": [REF], "player_information": "Visible own POV only",
            "alternative_action": "Consider available cover",
            "causal_reasoning": "Might have reduced exposure",
            "alternative_explanation": "Enemy outplay remains possible",
        }],
        "verdict": {"outcome": "supported", "summary": "Qualified causal hypothesis", "limitations": ["No voice chat available"]},
        "player_findings": {pov: {"status": "no_supported_mistake", "reason": "No additional evidence"} for pov in POV_IDS},
    }


def fixture_review(clip):
    return {
        "qa_status": "PASS",
        "reviewer": {"name": "Unit test fixture", "tool": "Synthetic test only", "method": "No real gameplay was reviewed"},
        "inspected_evidence": [{"evidence_ref": REF, "clip_sha256": clip["sha256"], "source_sha256": clip["source_sha256"], "inspected": True, "notes": "Synthetic attestation for gate validation"}],
        "finding_checks": [{"finding_id": "finding_1", "status": "supported", **{flag: True for flag in CHECK_FLAGS}, "notes": "Synthetic checks for software behavior only"}],
        "conclusion_review": {"inspected": True, "evidence_refs": [REF], "notes": "Synthetic conclusion review"},
        "issues": [], "limitations": [],
    }


class AuditGateTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        source = self.root / "source.mp4"
        source.write_bytes(b"synthetic source; not real video")
        clip = self.root / "clip.mp4"
        clip.write_bytes(b"synthetic evidence; not real video")
        self.manifest = fixture_manifest(source, sha256_file(source))
        self.clip = {"evidence_ref": REF, "path": str(clip), "source_path": str(source), "sha256": sha256_file(clip), "source_sha256": sha256_file(source), "start_timestamp": 1.0, "end_timestamp": 2.0}
        self.verdict = fixture_verdict()
        self.payload = fixture_review(self.clip)

    def tearDown(self):
        self.temporary.cleanup()

    def validate(self):
        return validate_result(self.payload, self.manifest, {REF}, self.verdict, [self.clip])

    def test_successful_gate_and_evidence_metadata_are_rendered(self):
        result = self.validate()
        self.assertEqual(result["qa_status"], "PASS")
        self.assertTrue(result["publication_allowed"])
        self.assertEqual(result["evidence_coverage"], {"required": 1, "inspected": 1})
        qa = render_qa_report(result, {"prompt_version": "d-test"})
        final = render_final_report(self.verdict, result, {}, [self.clip])
        self.assertIn(self.clip["sha256"], qa)
        self.assertIn("reviewer attestations", qa)
        self.assertIn("No voice chat available", final)
        self.assertIn("Enemy outplay remains possible", final)

    def test_uninspected_evidence_forces_fail_and_blocks_publication(self):
        self.payload["inspected_evidence"][0]["inspected"] = False
        result = self.validate()
        self.assertEqual(result["qa_status"], "FAIL")
        self.assertFalse(result["publication_allowed"])
        self.assertTrue(result["gate_failures"])
        with self.assertRaises(ContractError):
            render_final_report(self.verdict, result, {}, [self.clip])

    def test_missing_finding_check_forces_fail(self):
        self.payload["finding_checks"] = []
        self.assertEqual(self.validate()["qa_status"], "FAIL")

    def test_timestamp_error_cannot_pass_even_if_status_claims_pass(self):
        self.payload["finding_checks"][0]["timestamp_verified"] = False
        self.assertEqual(self.validate()["qa_status"], "FAIL")

    def test_unsupported_and_unverified_findings_cannot_publish(self):
        for status in ("unsupported", "unverified"):
            with self.subTest(status=status):
                self.payload["finding_checks"][0]["status"] = status
                self.assertEqual(self.validate()["qa_status"], "FAIL")

    def test_shared_and_secondary_findings_require_same_review(self):
        self.payload["inspected_evidence"] = []
        for level in ("secondary", "shared"):
            with self.subTest(level=level):
                self.verdict["findings"][0]["level"] = level
                self.assertEqual(self.validate()["qa_status"], "FAIL")

    def test_qualified_findings_preserve_qualification(self):
        self.payload["finding_checks"][0]["status"] = "qualified"
        self.payload["finding_checks"][0]["notes"] = "Ability timing only resolves to one frame"
        result = self.validate()
        self.assertEqual(result["qa_status"], "PASS_WITH_LIMITATIONS")
        self.assertIn("Ability timing", render_final_report(self.verdict, result, {}, [self.clip]))

    def test_critical_and_major_issues_force_fail(self):
        for severity in ("critical", "major"):
            with self.subTest(severity=severity):
                self.payload["issues"] = [{"severity": severity, "claim": "Wrong actor", "source": REF, "finding": "Identity contradicts source", "required_fix": "Revise C", "owner": "C"}]
                self.assertEqual(self.validate()["qa_status"], "FAIL")

    def test_minor_issue_remains_in_final_limitations(self):
        self.payload["issues"] = [{"severity": "minor", "claim": "Display label", "source": REF, "finding": "Hero remains unknown", "required_fix": "Retain unknown", "owner": "C"}]
        result = self.validate()
        self.assertEqual(result["qa_status"], "PASS_WITH_LIMITATIONS")
        self.assertIn("Hero remains unknown", render_final_report(self.verdict, result, {}, [self.clip]))

    def test_hash_mismatch_and_file_changes_are_rejected(self):
        self.payload["inspected_evidence"][0]["clip_sha256"] = "0" * 64
        with self.assertRaises(ContractError):
            self.validate()
        self.payload = fixture_review(self.clip)
        Path(self.clip["path"]).write_bytes(b"modified clip")
        with self.assertRaises(ContractError):
            self.validate()

    def test_source_modified_after_extraction_is_rejected(self):
        Path(self.clip["source_path"]).write_bytes(b"modified source")
        with self.assertRaises(ContractError):
            self.validate()

    def test_nonadverse_factual_basis_also_requires_inspection(self):
        other_ref = "support1@0.0-1.0"
        self.verdict["confirmed_facts"] = [{"id": "fact_1", "claim": "Visible factual basis", "evidence_refs": [other_ref]}]
        self.assertEqual(set(required_evidence_refs(self.verdict, self.manifest)), {REF, other_ref})
        result = validate_result(self.payload, self.manifest, {REF, other_ref}, self.verdict, [self.clip])
        self.assertEqual(result["qa_status"], "FAIL")
        self.assertTrue(any(other_ref in reason for reason in result["gate_failures"]))

    def test_inline_reference_cannot_evade_allowlist(self):
        self.payload["finding_checks"][0]["notes"] = "Unsupported extra source support1@0.0-1.0"
        with self.assertRaises(ContractError):
            self.validate()

    def test_malformed_reference_inside_narrative_is_rejected(self):
        self.payload["limitations"] = ["Unreviewed source tank@1.0-invented"]
        with self.assertRaises(ContractError):
            self.validate()

    def test_inline_verdict_citation_is_extracted_for_review(self):
        self.verdict["verdict"]["summary"] += " Additional evidence support1@0.0-1.0."
        self.assertIn("support1@0.0-1.0", required_evidence_refs(self.verdict, self.manifest))

    def test_original_source_limitations_survive_both_renderers(self):
        result = self.validate()
        metadata = {
            "upstream_limitations": ["Stage A tank: HUD unreadable from 1 to 2 seconds", "Stage B: unresolved actor conflict"],
            "execution": {"tool": "test reviewer", "model": "test-model-v1", "operator": "test only"},
            "input_hashes": {"tank": "test-hash"},
        }
        qa = render_qa_report(result, metadata)
        final = render_final_report(self.verdict, result, metadata, [self.clip])
        for text in metadata["upstream_limitations"]:
            self.assertIn(text, qa)
            self.assertIn(text, final)
        self.assertIn("test-model-v1", qa)
        self.assertIn("test-hash", final)

    def test_duplicate_attestation_is_rejected(self):
        self.payload["inspected_evidence"].append(copy.deepcopy(self.payload["inspected_evidence"][0]))
        with self.assertRaises(ContractError):
            self.validate()

    def test_boolean_strings_are_rejected(self):
        self.payload["finding_checks"][0]["identity_verified"] = "true"
        with self.assertRaises(ContractError):
            self.validate()

    def test_inconclusive_still_requires_actual_conclusion_evidence(self):
        self.verdict["findings"] = []
        self.verdict["verdict"]["outcome"] = "inconclusive"
        self.verdict["confirmed_facts"] = [{"claim": "Only limited evidence", "evidence_refs": [REF]}]
        self.payload["finding_checks"] = []
        self.assertEqual(required_evidence_refs(self.verdict, self.manifest), [REF])
        self.assertEqual(self.validate()["qa_status"], "PASS")
        self.payload["conclusion_review"]["inspected"] = False
        self.assertEqual(self.validate()["qa_status"], "FAIL")

    def test_limitations_status_cannot_be_empty(self):
        self.payload["qa_status"] = "PASS_WITH_LIMITATIONS"
        with self.assertRaises(ContractError):
            self.validate()

    def test_unknown_finding_id_is_rejected(self):
        self.payload["finding_checks"][0]["finding_id"] = "invented"
        with self.assertRaises(ContractError):
            self.validate()


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "FFmpeg and ffprobe required")
class EvidenceExtractionTests(unittest.TestCase):
    def test_extracts_real_video_without_changing_original_and_detects_bad_hash(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.mp4"
            subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc=size=64x64:rate=10", "-t", "3", "-pix_fmt", "yuv420p", "-c:v", "libx264", str(source)], check=True, capture_output=True)
            digest = sha256_file(source)
            manifest = fixture_manifest(source, digest)
            clips = extract_evidence_clips(manifest, fixture_verdict(), root / "clips", root)
            self.assertEqual(len(clips), 1)
            self.assertEqual(clips[0]["source_sha256"], digest)
            self.assertEqual(clips[0]["sha256"], sha256_file(clips[0]["path"]))
            self.assertIn("ffmpeg version", clips[0]["tool_versions"]["ffmpeg"])
            self.assertIn("ffprobe version", clips[0]["tool_versions"]["ffprobe"])
            self.assertIn("deterministic", clips[0]["model"])
            self.assertAlmostEqual(clips[0]["duration_seconds"], 1.0, delta=0.1)
            self.assertEqual(sha256_file(source), digest)
            repeat = extract_evidence_clips(manifest, fixture_verdict(), root / "clips", root)
            self.assertEqual(repeat[0]["sha256"], clips[0]["sha256"])
            manifest["videos"][0]["sha256"] = "0" * 64
            with self.assertRaises(ContractError):
                extract_evidence_clips(manifest, fixture_verdict(), root / "new", root)

    def test_truncated_original_fails_actual_duration_check(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "short.mp4"
            subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", "color=size=64x64:rate=10", "-t", "1.5", "-c:v", "libx264", str(source)], check=True, capture_output=True)
            manifest = fixture_manifest(source, sha256_file(source))
            with self.assertRaises(ContractError):
                extract_evidence_clips(manifest, fixture_verdict(), root / "clips", root)


if __name__ == "__main__":
    unittest.main()
