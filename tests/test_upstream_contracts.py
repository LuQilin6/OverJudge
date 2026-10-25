"""One Stage A report contract at submission and at the downstream boundary."""

import unittest

from src.contracts import ContractError, extract_evidence_refs, validate_pov_report
from src.pov_analysis import HEADINGS, validate_report


def complete_report(pov="tank"):
    """Synthetic shape fixture; no real gameplay or inspection is asserted."""
    return f"""# POV Report — {pov}
## Metadata
- Video: synthetic/{pov}.mp4
- Hero: unknown
- prompt_version: stage-a-v1.1
- Inspection coverage / method: Synthetic contract test; no real gameplay inspected
## Gameplay Context
Actual gameplay context is unknown; this is a software fixture.
## Timestamped Behavioral Timeline
### [12.0–13.4 s]
- Observed: Synthetic fixture represents movement; no actual gameplay claim.
- Immediate outcome: unknown
- Evidence: {pov}@12.0-13.4
- Evidence quality: low
- Inference/unknown: actual gameplay and continuous activity are unknown
## Player Information State
Unknown beyond the assigned synthetic source.
## Cross-POV Verification Questions
No real question can be answered using this software fixture.
## Neutral Behavioral Summary
No tactical finding is made from this synthetic source.
## Coverage and Limitations
Software contract test only; no actual video has been inspected.
## Agent Handoff
- Stage: A
- Status: PASS_WITH_LIMITATIONS
- Inputs consumed: synthetic software fixture
- Outputs produced: this synthetic report
- Prompt/model/tool versions: stage-a-v1.1; unittest; no model call
- Evidence coverage: synthetic interval 12.0–13.4
- Unresolved questions: every actual gameplay interpretation
- Known limitations: software test only
- Recommended next action: validate software behavior only
"""


def own_manifest():
    return {
        "fight_start_timestamp": 10.0, "fight_end_timestamp": 20.0,
        "videos": [{"pov_id": "tank", "duration_seconds": 20.0, "missing_intervals": []}],
    }


class SharedReportContractTests(unittest.TestCase):
    def test_submission_and_downstream_accept_the_same_complete_format(self):
        text = complete_report()
        self.assertEqual(validate_report(text, "tank", 10.0, 20.0), [])
        handoff = validate_pov_report(text, "tank", own_manifest())
        self.assertEqual(handoff["status"], "PASS_WITH_LIMITATIONS")
        self.assertEqual(handoff["evidence_refs"], ["tank@12.0-13.4"])
        self.assertEqual(handoff["event_intervals"], [{"start_timestamp": 12.0, "end_timestamp": 13.4,
                                                       "evidence_refs": ["tank@12.0-13.4"]}])

    def test_invalid_report_value_is_an_error_list_not_an_exception(self):
        self.assertTrue(validate_report(None, "tank", 10, 20))
        self.assertTrue(validate_report(complete_report(), "unknown_pov", 10, 20))

    def test_metadata_emails_and_noncitation_at_filenames_are_not_references(self):
        text = complete_report().replace("- Video: synthetic/tank.mp4",
                                         "- Video: synthetic/foo@bar.mp4\n- Reviewer: person@example.com")
        self.assertEqual(validate_report(text, "tank", 10, 20), [])
        self.assertEqual([str(ref) for ref in extract_evidence_refs(text, own_manifest())], ["tank@12.0-13.4"])

    def test_known_pov_malformed_tokens_and_unknown_numeric_citations_still_fail(self):
        for citation in ("tank@one-two", "unknown@12.0-13.4"):
            with self.subTest(citation=citation), self.assertRaises(ContractError):
                extract_evidence_refs(citation, own_manifest())

    def test_all_sections_are_required_and_nonempty(self):
        for heading in HEADINGS:
            with self.subTest(heading=heading):
                text = complete_report().replace("## " + heading, "## Other " + heading)
                self.assertTrue(validate_report(text, "tank", 10, 20))
        text = complete_report().replace("Actual gameplay context is unknown; this is a software fixture.\n", "")
        self.assertTrue(validate_report(text, "tank", 10, 20))

    def test_duplicate_section_or_handoff_status_is_rejected(self):
        text = complete_report() + "\n## Metadata\n- prompt_version: duplicate\n"
        self.assertTrue(validate_report(text, "tank", 10, 20))
        text = complete_report().replace("- Status: PASS_WITH_LIMITATIONS", "- Status: PASS\n- Status: BLOCKED")
        self.assertTrue(validate_report(text, "tank", 10, 20))

    def test_blocked_and_wrong_stage_reports_do_not_become_passed_handoffs(self):
        for replacement in ("- Status: BLOCKED", "- Status: FAIL"):
            text = complete_report().replace("- Status: PASS_WITH_LIMITATIONS", replacement)
            self.assertTrue(validate_report(text, "tank", 10, 20))
        text = complete_report().replace("- Stage: A", "- Stage: B")
        self.assertTrue(validate_report(text, "tank", 10, 20))

    def test_heading_must_contain_an_actual_in_bounds_interval(self):
        for heading in ("### [200.0–300.0 s]", "### [14.0–12.0 s]", "### [12.0–12.0 s]",
                        "### unknown", "### [nan–13.4 s]", "### [9.9–13.4 s]"):
            with self.subTest(heading=heading):
                text = complete_report().replace("### [12.0–13.4 s]", heading)
                self.assertTrue(validate_report(text, "tank", 10, 20))

    def test_heading_and_citation_must_overlap(self):
        text = complete_report().replace("### [12.0–13.4 s]", "### [15.0–16.0 s]")
        with self.assertRaises(ContractError):
            validate_pov_report(text, "tank", own_manifest())

    def test_partial_regex_match_cannot_admit_malformed_or_foreign_citations(self):
        for citation in ("tank@12.0-13.4.999", "tank@12.0-13.4suffix", "other@12.0-13.4",
                         "tank@-12.0-13.4", "tank@one-two", "dps1@12.0-13.4"):
            with self.subTest(citation=citation):
                text = complete_report().replace("tank@12.0-13.4", citation)
                self.assertTrue(validate_report(text, "tank", 10, 20))

    def test_each_event_requires_all_five_nonempty_bullet_fields(self):
        for field in ("Observed", "Immediate outcome", "Evidence", "Evidence quality", "Inference/unknown"):
            with self.subTest(field=field):
                text = complete_report().replace("- " + field + ":", "- Other " + field + ":")
                self.assertTrue(validate_report(text, "tank", 10, 20))
        # A missing value must not borrow the following line as its content.
        text = complete_report().replace("- Immediate outcome: unknown", "- Immediate outcome:")
        self.assertTrue(validate_report(text, "tank", 10, 20))

    def test_metadata_values_and_handoff_fields_cannot_be_empty(self):
        for original, replacement in (
            ("- prompt_version: stage-a-v1.1", "- prompt_version:"),
            ("- Inputs consumed: synthetic software fixture", "- Inputs consumed:"),
            ("- Inspection coverage / method: Synthetic contract test; no real gameplay inspected",
             "- Inspection coverage / method: unknown"),
        ):
            with self.subTest(field=original):
                self.assertTrue(validate_report(complete_report().replace(original, replacement), "tank", 10, 20))

    def test_overt_grading_is_rejected_but_observation_and_abstention_are_allowed(self):
        original = "Synthetic fixture represents movement; no actual gameplay claim."
        for grading in ("That was bad play.", "Tank is to blame.", "Tank is throwing the fight.", "坦克应该背锅。"):
            with self.subTest(grading=grading):
                self.assertTrue(validate_report(complete_report().replace(original, grading), "tank", 10, 20))
        text = complete_report().replace(original, "A visible character throws a grenade; its identity is unknown.")
        text = text.replace("No tactical finding is made from this synthetic source.", "No blame is assigned; this report describes observations only.")
        self.assertEqual(validate_report(text, "tank", 10, 20), [])

    def test_quality_is_qualitative_and_crlf_is_supported(self):
        self.assertTrue(validate_report(complete_report().replace("- Evidence quality: low", "- Evidence quality: 90%"), "tank", 10, 20))
        self.assertEqual(validate_report(complete_report().replace("\n", "\r\n"), "tank", 10, 20), [])

    def test_invalid_second_event_cannot_hide_behind_first_valid_event(self):
        event = """### [18.0–19.0 s]
- Observed: unknown
- Immediate outcome: unknown
- Evidence: tank@12.0-13.4
- Evidence quality: low
- Inference/unknown: unknown
"""
        text = complete_report().replace("## Player Information State", event + "## Player Information State")
        self.assertTrue(validate_report(text, "tank", 10, 20))


if __name__ == "__main__":
    unittest.main()
