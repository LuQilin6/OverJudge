"""Prepare isolated manual analysis jobs and validate submitted reports."""
import re

HEADINGS = ('Metadata', 'Gameplay Context', 'Timestamped Behavioral Timeline', 'Player Information State', 'Cross-POV Verification Questions', 'Neutral Behavioral Summary', 'Coverage and Limitations', 'Agent Handoff')
REF = re.compile(r'\b(tank|dps1|dps2|support1|support2)@(\d+(?:\.\d+)?)-(\d+(?:\.\d+)?)\b')


def validate_report(text, pov, start, end):
    errors = []
    for heading in HEADINGS:
        if f'## {heading}' not in text.splitlines():
            errors.append(f'Missing section: {heading}')
    refs = list(REF.finditer(text))
    if not refs:
        errors.append('No evidence references')
    for match in refs:
        actor, a, b = match.groups()
        if actor != pov or not start <= float(a) < float(b) <= end:
            errors.append(f'Invalid evidence reference: {match.group()}')
    if re.search(r'\b(bad play|throw|blame)\b', text, re.I):
        errors.append('Judgment language requires revision')
    timeline = text.partition('## Timestamped Behavioral Timeline')[2].partition('\n## ')[0]
    events = re.split(r'^### ', timeline, flags=re.M)[1:]
    if not events:
        errors.append('No timestamped events')
    for event in events:
        if not REF.search(event) or any(label not in event for label in ('Observed:', 'Immediate outcome:', 'Evidence quality:', 'Inference/unknown:')):
            errors.append('Event lacks evidence or required observation fields')
    if 'prompt_version:' not in text:
        errors.append('Missing prompt_version')
    return errors
