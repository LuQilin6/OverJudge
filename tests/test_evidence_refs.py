from src.pov_analysis import HEADINGS, validate_report


def report(ref='tank@12.0-13.4'):
    return '\n'.join('## ' + h + ('\n### [12.0–13.4 s]\nObserved: movement\nImmediate outcome: unknown\nEvidence quality: low\nInference/unknown: unknown\n' + ref if h == 'Timestamped Behavioral Timeline' else '') for h in HEADINGS) + '\nprompt_version: 1.0\n'


def test_valid_structure():
    assert validate_report(report(), 'tank', 10, 20) == []


def test_foreign_or_out_of_bounds_evidence():
    assert validate_report(report('dps1@12-13'), 'tank', 10, 20)
    assert validate_report(report('tank@0-13'), 'tank', 10, 20)
    assert validate_report(report('tank@13-12'), 'tank', 10, 20)
