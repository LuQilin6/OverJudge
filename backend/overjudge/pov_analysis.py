"""Single-POV report contract shared with downstream handoff validation.

The public list-of-errors interface is preserved for Stage A submission callers.
Structural acceptance is not an assertion of visual accuracy or sufficient
coverage; the review/provenance record retains that distinction.
"""

from .contracts import ContractError, POV_HEADINGS, REF_PATTERN, validate_pov_report


HEADINGS = POV_HEADINGS
REF = REF_PATTERN


def validate_report(text, pov, start, end):
    # This standalone interface knows only the report's POV and requested
    # interval. Intake and the Stage A service separately validate video files.
    manifest = {
        'fight_start_timestamp': start,
        'fight_end_timestamp': end,
        'videos': [{'pov_id': pov, 'duration_seconds': end, 'missing_intervals': []}],
    }
    try:
        validate_pov_report(text, pov, manifest)
    except (ContractError, TypeError) as exc:
        return [str(exc)]
    return []
