"""Stage B provenance, conflict handoff and five-player coverage tests."""

from copy import deepcopy
import unittest

from src.contracts import ContractError, POV_IDS
from src.fusion import example_response, render_report, response_schema, validate_result


def manifest():
    return {
        "fight_start_timestamp": 0.0, "fight_end_timestamp": 10.0,
        "videos": [{"pov_id": pov, "duration_seconds": 10.0} for pov in POV_IDS],
    }


class FusionTests(unittest.TestCase):
    def setUp(self):
        self.payload = example_response()
        self.allowed = {"tank@1.0-2.0", "dps1@1.0-2.0"}

    def validate(self):
        return validate_result(self.payload, manifest(), self.allowed)

    def make_conflict(self):
        event = self.payload["events"][0]
        event.update(epistemic_status="conflicted", source_status="conflicting", evidence_refs=list(sorted(self.allowed)))
        self.payload["conflicts"] = [{
            "conflict_id": "c1", "description": "Reports disagree about the visible actor.",
            "event_ids": ["e1"], "evidence_refs": list(sorted(self.allowed)),
            "severity": "critical", "status": "unresolved", "resolution": "unknown; reinspection needed", "resolution_evidence_refs": [],
        }]
        self.payload["reinspection_requests"] = [{
            "conflict_id": "c1", "pov_id": "tank", "start_timestamp": 1.0, "end_timestamp": 2.0,
            "question": "Which actor is directly visible?",
        }]

    def test_accepts_neutral_evidence_and_unknown_actions(self):
        validated = self.validate()
        self.assertEqual(validated["action_matrix"][0]["players"]["support2"]["epistemic_status"], "unknown")
        self.assertEqual(self.payload, example_response(), "validation must not mutate its input")

    def test_corroboration_requires_independent_povs(self):
        self.payload["events"][0]["source_status"] = "corroborated"
        with self.assertRaises(ContractError):
            self.validate()
        self.payload["events"][0]["evidence_refs"].append("dps1@1.0-2.0")
        self.validate()

    def test_rejects_missing_player_in_any_phase(self):
        del self.payload["action_matrix"][2]["players"]["support2"]
        with self.assertRaises(ContractError):
            self.validate()

    def test_rejects_phase_omission(self):
        self.payload["phases"].pop()
        self.payload["action_matrix"].pop()
        with self.assertRaises(ContractError):
            self.validate()

    def test_requires_citation_on_observed_event(self):
        self.payload["events"][0]["evidence_refs"] = []
        with self.assertRaises(ContractError):
            self.validate()

    def test_rejects_citation_not_in_original_reports(self):
        self.payload["events"][0]["evidence_refs"] = ["tank@1.1-1.9"]
        with self.assertRaises(ContractError):
            self.validate()

    def test_cannot_hide_new_citation_in_prose(self):
        self.payload["events"][0]["description"] = "A movement is reported at support2@3.0-4.0."
        with self.assertRaises(ContractError):
            self.validate()

    def test_rejects_out_of_bounds_timestamp(self):
        self.payload["events"][0]["end_timestamp"] = 10.1
        with self.assertRaises(ContractError):
            self.validate()

    def test_rejects_shifted_citation_window(self):
        self.payload["events"][0].update(start_timestamp=4.0, end_timestamp=5.0)
        with self.assertRaises(ContractError):
            self.validate()

    def test_critical_conflict_is_retained_and_requires_reinspection(self):
        self.make_conflict()
        self.validate()
        self.payload["reinspection_requests"] = []
        with self.assertRaises(ContractError):
            self.validate()

    def test_critical_conflict_cannot_claim_unlimited_pass(self):
        self.make_conflict()
        self.payload["status"] = "PASS"
        with self.assertRaises(ContractError):
            self.validate()

    def test_conflicting_event_cannot_drop_conflict_ledger(self):
        self.make_conflict()
        self.payload["conflicts"] = []
        self.payload["reinspection_requests"] = []
        with self.assertRaises(ContractError):
            self.validate()

    def test_resolved_conflict_requires_evidence(self):
        self.make_conflict()
        self.payload["conflicts"][0]["status"] = "resolved"
        with self.assertRaises(ContractError):
            self.validate()

    def test_blame_and_numerical_responsibility_are_rejected(self):
        for text in ("Tank has primary responsibility for defeat.", "tank 70% blame percentage", "坦克应承担主要责任"):
            with self.subTest(text=text):
                self.payload = example_response()
                self.payload["events"][0]["description"] = text
                with self.assertRaises(ContractError):
                    self.validate()
        self.payload = example_response()
        self.payload["blame_percentage"] = {"tank": 70}
        with self.assertRaises(ContractError):
            self.validate()

    def test_malformed_enum_types_raise_contract_errors(self):
        for field in ("epistemic_status", "source_status"):
            with self.subTest(field=field):
                self.payload = example_response()
                self.payload["events"][0][field] = []
                with self.assertRaises(ContractError):
                    self.validate()
        self.payload = example_response()
        self.payload["status"] = {}
        with self.assertRaises(ContractError):
            self.validate()

    def test_render_required_sections_and_preserve_unknowns(self):
        validated = self.validate()
        report = render_report(validated, {"run_id": "test", "prompt_version": "stage-b-1.0"})
        for section in ("Shared Context", "Input Coverage and Alignment Assumption", "Unified Timeline", "Five-Player Action Matrix", "Team Coordination", "Turning Points", "Player Knowledge Limits", "Conflicts and Uncertainties", "Evidence Index", "Neutral Summary", "Agent Handoff"):
            self.assertIn(f"## {section}", report)
        self.assertIn("tank@1.0-2.0", report)
        self.assertIn("not observed; unknown", report)
        self.assertIn("schema_version", response_schema()["response_fields"])


if __name__ == "__main__":
    unittest.main()
