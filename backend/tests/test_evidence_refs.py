"""Evidence identities must survive handoffs without new or shifted windows."""

import copy
import unittest

from overjudge.contracts import ContractError, EvidenceRef, extract_evidence_refs, validate_references


class EvidenceReferenceTests(unittest.TestCase):
    def setUp(self):
        self.manifest = {"fight_start_timestamp": 0.0, "fight_end_timestamp": 10.0,
                         "videos": [{"pov_id": "tank", "duration_seconds": 10.0, "missing_intervals": []}]}

    def test_canonical_decimals_without_timestamp_shift(self):
        self.assertEqual(str(EvidenceRef.parse("tank@1-2.500", self.manifest)), "tank@1.0-2.5")
        self.assertEqual(validate_references(["tank@1-2"], self.manifest, {"tank@1.0-2.0"}), ["tank@1.0-2.0"])

    def test_sentence_punctuation_and_deduplication(self):
        refs = extract_evidence_refs("See tank@1.0-2.0. Again `tank@1.0-2.0`.", self.manifest)
        self.assertEqual([str(ref) for ref in refs], ["tank@1.0-2.0"])

    def test_canonicalization_preserves_finite_decimal_time(self):
        ref = EvidenceRef.parse("tank@0.0000000000000001-0.0000000000000002")
        self.assertEqual(EvidenceRef.parse(str(ref)), ref)
        ref = EvidenceRef.parse("tank@1.1234567890123457-2.1234567890123457")
        self.assertEqual(EvidenceRef.parse(str(ref)), ref)

    def test_rejects_malformed_reversed_nonfinite_and_unknown(self):
        for ref in ("tank@2-1", "tank@1-1", "tank@-1-2", "tank@nan-2", "other@1-2", "tank@1.0-2.0.3"):
            with self.subTest(ref=ref), self.assertRaises(ContractError):
                EvidenceRef.parse(ref, self.manifest)

    def test_missing_or_short_video_and_gap_invalidate_citations(self):
        for mutate in (lambda m: m["videos"][0].update(duration_seconds=1.5),
                       lambda m: m["videos"][0].update(missing_intervals=[{"start_timestamp": 1.5, "end_timestamp": 1.6}])):
            manifest = copy.deepcopy(self.manifest)
            mutate(manifest)
            with self.assertRaises(ContractError):
                EvidenceRef.parse("tank@1-2", manifest)

    def test_duplicate_and_shifted_refs_rejected(self):
        with self.assertRaises(ContractError):
            validate_references(["tank@1-2", "tank@1.0-2.0"], self.manifest)
        with self.assertRaises(ContractError):
            validate_references(["tank@1.1-1.9"], self.manifest, {"tank@1.0-2.0"})

    def test_malformed_token_in_prose_does_not_disappear(self):
        with self.assertRaises(ContractError):
            extract_evidence_refs("Citation tank@one-two is malformed", self.manifest)
