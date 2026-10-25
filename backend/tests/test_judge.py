"""Stage C contract tests; every gameplay statement in fixtures is synthetic."""

import copy
import json
import unittest

from overjudge.contracts import ContractError, POV_IDS
from overjudge.judge import REQUIRED_SECTIONS, example_response, render_report, response_schema, validate_result


def manifest():
    return {
        "run_id": "synthetic-run", "fight_id": "synthetic-fight", "game": "Overwatch 2",
        "prealigned_input_assumed": True,
        "fight_start_timestamp": 0.0, "fight_end_timestamp": 20.0,
        "videos": [{
            "pov_id": pov_id, "path": f"inputs/videos/{pov_id}.mp4", "sha256": "0" * 64,
            "duration_seconds": 20.0, "fps": 30.0, "width": 1920, "height": 1080,
            "audio_present": True, "hero": "unknown", "coverage_status": "complete", "missing_intervals": [],
        } for pov_id in POV_IDS],
    }


def supported_response():
    payload = example_response()
    payload["fight_summary"] = {
        "outcome": "loss", "summary": "Synthetic visible fight loss.", "evidence_refs": ["tank@1.0-2.0"],
    }
    payload["confirmed_facts"] = [{
        "id": "fact-1", "claim": "Synthetic HUD observation shows ultimate charge at 50%.",
        "evidence_refs": ["tank@1.0-2.0"],
    }]
    payload["findings"] = [{
        "id": "finding-1", "pov_id": "tank", "level": "primary",
        "claim": "Synthetic candidate: advancing exposed the player to an avoidable crossfire.",
        "evidence_refs": ["tank@1.0-2.0"],
        "player_information": "Synthetic own-POV HUD shows the visible support position.",
        "alternative_action": "Synthetic alternative: hold the corner until the visible support arrives.",
        "plausible_consequence": "Holding might have preserved cover; success is not guaranteed.",
        "causal_reasoning": "Exposure plausibly contributed; this is a hypothesis beyond temporal order.",
        "alternative_explanation": "Enemy aim may have produced the same outcome despite holding.",
    }]
    payload["player_findings"]["tank"] = {
        "status": "findings", "summary": "One synthetic primary contribution is proposed.", "finding_ids": ["finding-1"],
    }
    payload["verdict"] = {
        "outcome": "supported", "summary": "Synthetic evidence supports the stated contributor.",
        "limitations": ["Synthetic fixtures cannot establish real gameplay conclusions."],
    }
    payload["top_evidence_clips"] = ["tank@1.0-2.0"]
    payload["actionable_lessons"] = [{
        "pov_ids": ["tank"], "lesson": "Synthetic lesson: check visible support before leaving cover.",
        "evidence_refs": ["tank@1.0-2.0"],
    }]
    payload["confidence"] = {"label": "medium", "rationale": "Synthetic source supports visibility, not causal certainty."}
    return payload


class StageCContractTests(unittest.TestCase):
    def setUp(self):
        self.manifest = manifest()
        self.allowed = {f"{pov_id}@1.0-2.0" for pov_id in POV_IDS}

    def validate(self, payload):
        return validate_result(payload, self.manifest, self.allowed)

    def test_abstention_is_complete(self):
        result = self.validate(example_response())
        self.assertEqual(result["verdict"]["outcome"], "inconclusive")
        self.assertFalse(result["findings"])
        self.assertEqual(set(result["player_findings"]), set(POV_IDS))

    def test_supported_finding_valid_and_hud_percentage_allowed(self):
        result = self.validate(supported_response())
        self.assertEqual(result["findings"][0]["evidence_refs"], ["tank@1.0-2.0"])
        self.assertIn("50%", result["confirmed_facts"][0]["claim"])

    def test_validation_does_not_mutate_response(self):
        payload = supported_response()
        payload["findings"][0]["claim"] = "  Synthetic claim.  "
        original = copy.deepcopy(payload)
        self.assertEqual(self.validate(payload)["findings"][0]["claim"], "Synthetic claim.")
        self.assertEqual(payload, original)

    def test_missing_or_extra_player_rejected(self):
        for mode in ("missing", "extra"):
            with self.subTest(mode=mode):
                payload = example_response()
                if mode == "missing":
                    del payload["player_findings"]["support2"]
                else:
                    payload["player_findings"]["opponent"] = payload["player_findings"]["tank"]
                with self.assertRaises(ContractError):
                    self.validate(payload)

    def test_finding_requires_supported_nonempty_evidence(self):
        for refs in ([], ["tank@3.0-4.0"], ["tank@1.0-2.0", "tank@1.0-2.0"]):
            with self.subTest(refs=refs):
                payload = supported_response()
                payload["findings"][0]["evidence_refs"] = refs
                with self.assertRaises(ContractError):
                    self.validate(payload)

    def test_out_of_bounds_reference_rejected_even_if_allowlisted(self):
        payload = supported_response()
        payload["findings"][0]["evidence_refs"] = ["tank@19.0-22.0"]
        with self.assertRaises(ContractError):
            validate_result(payload, self.manifest, self.allowed | {"tank@19.0-22.0"})

    def test_information_alternatives_and_causal_reasoning_required(self):
        for field in ("player_information", "alternative_action", "plausible_consequence", "causal_reasoning", "alternative_explanation"):
            with self.subTest(field=field):
                payload = supported_response()
                payload["findings"][0][field] = " "
                with self.assertRaises(ContractError):
                    self.validate(payload)

    def test_responsibility_percentages_rejected(self):
        for claim in ("Tank carries 70% of the blame.", "该玩家负百分之七十责任。", "置信度为90％。"):
            with self.subTest(claim=claim):
                payload = supported_response()
                payload["findings"][0]["claim"] = claim
                with self.assertRaises(ContractError):
                    self.validate(payload)

    def test_percentage_cannot_be_extra_field(self):
        payload = supported_response()
        payload["findings"][0]["blame_percentage"] = 70
        with self.assertRaises(ContractError):
            self.validate(payload)

    def test_numerical_confidence_rejected(self):
        payload = example_response()
        payload["confidence"]["label"] = 0.9
        with self.assertRaises(ContractError):
            self.validate(payload)

    def test_inconclusive_cannot_establish_blame(self):
        payload = supported_response()
        payload["verdict"]["outcome"] = "inconclusive"
        with self.assertRaises(ContractError):
            self.validate(payload)

    def test_not_established_candidate_allowed_inconclusive(self):
        payload = supported_response()
        payload["findings"][0]["level"] = "not_established"
        payload["player_findings"]["tank"]["status"] = "no_supported_mistake"
        payload["verdict"]["outcome"] = "inconclusive"
        self.assertEqual(self.validate(payload)["verdict"]["outcome"], "inconclusive")

    def test_supported_verdict_requires_contributor(self):
        payload = example_response()
        payload["verdict"]["outcome"] = "supported"
        with self.assertRaises(ContractError):
            self.validate(payload)

    def test_no_supported_mistake_cannot_hide_adverse_finding(self):
        payload = supported_response()
        payload["player_findings"]["tank"]["status"] = "no_supported_mistake"
        with self.assertRaises(ContractError):
            self.validate(payload)

    def test_finding_linkage_and_identity_checked(self):
        for change in ("missing", "duplicate", "wrong_player", "unknown"):
            with self.subTest(change=change):
                payload = supported_response()
                if change == "missing":
                    payload["player_findings"]["tank"]["finding_ids"] = []
                elif change == "duplicate":
                    payload["player_findings"]["tank"]["finding_ids"].append("finding-1")
                elif change == "wrong_player":
                    payload["findings"][0]["pov_id"] = "dps1"
                else:
                    payload["player_findings"]["tank"]["finding_ids"] = ["absent"]
                with self.assertRaises(ContractError):
                    self.validate(payload)

    def test_duplicate_finding_ids_rejected(self):
        payload = supported_response()
        payload["findings"].append(copy.deepcopy(payload["findings"][0]))
        with self.assertRaises(ContractError):
            self.validate(payload)

    def test_shared_requires_two_players_and_no_primary(self):
        payload = supported_response()
        payload["verdict"]["outcome"] = "shared"
        with self.assertRaises(ContractError):
            self.validate(payload)
        payload["findings"][0]["level"] = "shared"
        with self.assertRaises(ContractError):
            self.validate(payload)
        second = copy.deepcopy(payload["findings"][0])
        second.update({"id": "finding-2", "pov_id": "dps1", "evidence_refs": ["dps1@1.0-2.0"]})
        payload["findings"].append(second)
        payload["player_findings"]["dps1"] = {
            "status": "findings", "summary": "Synthetic shared contribution.", "finding_ids": ["finding-2"],
        }
        self.assertEqual(self.validate(payload)["verdict"]["outcome"], "shared")

    def test_alternative_explanations_and_limitations_mandatory(self):
        for target in ("alternative_explanations", "limitations"):
            with self.subTest(target=target):
                payload = supported_response()
                if target == "limitations":
                    payload["verdict"]["limitations"] = []
                else:
                    payload[target] = []
                with self.assertRaises(ContractError):
                    self.validate(payload)

    def test_adverse_finding_needs_lesson_and_clip(self):
        for field in ("actionable_lessons", "top_evidence_clips"):
            with self.subTest(field=field):
                payload = supported_response()
                payload[field] = []
                with self.assertRaises(ContractError):
                    self.validate(payload)

    def test_top_clip_must_support_used_claim(self):
        payload = supported_response()
        payload["top_evidence_clips"] = ["dps1@1.0-2.0"]
        with self.assertRaises(ContractError):
            self.validate(payload)

    def test_known_outcome_requires_citation(self):
        payload = example_response()
        payload["fight_summary"]["outcome"] = "loss"
        with self.assertRaises(ContractError):
            self.validate(payload)

    def test_unknown_outcome_requires_inconclusive_verdict(self):
        payload = supported_response()
        payload["fight_summary"] = {
            "outcome": "unknown", "summary": "The supplied evidence does not establish an outcome.",
            "evidence_refs": [],
        }
        with self.assertRaisesRegex(ContractError, "unknown fight outcome"):
            self.validate(payload)
        payload["verdict"]["outcome"] = "inconclusive"
        payload["findings"][0]["level"] = "not_established"
        payload["player_findings"]["tank"]["status"] = "no_supported_mistake"
        self.assertEqual(self.validate(payload)["fight_summary"]["outcome"], "unknown")

    def test_narrative_cannot_hide_new_or_malformed_citation(self):
        for citation in ("tank@3.0-4.0", "tank@19.0-22.0", "tank@2.0-1.0", "tank@bad"):
            with self.subTest(citation=citation):
                payload = supported_response()
                payload["findings"][0]["claim"] += " See " + citation + "."
                with self.assertRaises(ContractError):
                    self.validate(payload)

    def test_narrative_allows_citation_already_in_source_allowlist(self):
        payload = supported_response()
        payload["findings"][0]["claim"] += " See tank@1.0-2.0."
        self.assertIn("tank@1.0-2.0", self.validate(payload)["findings"][0]["claim"])

    def test_fact_cannot_smuggle_numerical_attribution(self):
        for claim in ("Tank carries 70% of the blame.", "该玩家负百分之七十责任。", "Confidence is 90%."):
            with self.subTest(claim=claim):
                payload = supported_response()
                payload["confirmed_facts"][0]["claim"] = claim
                with self.assertRaisesRegex(ContractError, "numerical responsibility or confidence"):
                    self.validate(payload)

    def test_observed_hud_percentages_are_not_rejected_as_blame(self):
        for claim in (
            "The tank's HUD showed 50% ultimate charge and 40% health.",
            "坦克大招充能为百分之七十。",
            "The tank had 50% health; this alone does not establish responsibility.",
        ):
            with self.subTest(claim=claim):
                payload = supported_response()
                payload["confirmed_facts"][0]["claim"] = claim
                self.assertEqual(self.validate(payload)["confirmed_facts"][0]["claim"], claim)

    def test_report_preserves_all_sections_and_uncertainty(self):
        payload = self.validate(supported_response())
        report = render_report(payload, {"run_id": "test-run", "fight_id": "test-fight"})
        for heading in REQUIRED_SECTIONS:
            self.assertEqual(report.count(f"## {heading}\n"), 1)
        for pov_id in POV_IDS:
            self.assertIn(f"**{pov_id}**", report)
        for field in ("player_information", "alternative_action", "plausible_consequence", "causal_reasoning", "alternative_explanation"):
            self.assertIn(payload["findings"][0][field], report)
        self.assertIn("not a calibrated probability", report)
        self.assertIn("await Stage D footage review", report)
        self.assertIn("tank@1.0-2.0", report)

    def test_schema_serializable_and_disallows_extra_fields(self):
        schema = json.loads(json.dumps(response_schema()))
        self.assertFalse(schema["additionalProperties"])
        self.assertEqual(set(schema["required"]), set(example_response()))


if __name__ == "__main__":
    unittest.main()
