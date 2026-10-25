"""Shared, provider-independent contracts for the Stage A -> B/C/D boundary.

These checks establish provenance and shape, not the truth of a video claim.
All timestamps remain seconds from the start of the original aligned videos.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
import hashlib
import json
import math
from pathlib import Path
import re
from typing import Any


POV_IDS = ("tank", "dps1", "dps2", "support1", "support2")
STAGES = ("B", "C", "D")
REF_PATTERN = re.compile(
    r"(?<![\w@])([A-Za-z][A-Za-z0-9_]*)@"
    r"(\d+(?:\.\d+)?)-(\d+(?:\.\d+)?)(?!\w|\.\d)"
)


class ContractError(ValueError):
    """An input or handoff does not meet a documented stage contract."""


def sha256_file(path: Path | str) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_json(path: Path | str) -> dict[str, Any]:
    def reject_constant(value: str) -> None:
        raise ContractError(f"Non-finite JSON number: {value}")

    def unique_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ContractError(f"Duplicate JSON key: {key}")
            result[key] = value
        return result

    try:
        value = json.loads(
            Path(path).read_text(encoding="utf-8"),
            parse_constant=reject_constant,
            object_pairs_hook=unique_keys,
        )
    except (OSError, ValueError) as exc:
        raise ContractError(f"Cannot read JSON {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ContractError(f"JSON object required: {path}")
    return value


def finite_number(value: Any, name: str, *, minimum: float = 0) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ContractError(f"{name} must be a number")
    try:
        value = float(value)
    except OverflowError as exc:
        raise ContractError(f"{name} is outside the finite numeric range") from exc
    if not math.isfinite(value) or value < minimum:
        raise ContractError(f"{name} must be finite and >= {minimum}")
    return value


def validate_manifest(manifest: dict[str, Any]) -> dict[str, Any]:
    """Validate an S0 handoff without claiming to perform S0 video inspection."""
    if not isinstance(manifest, dict):
        raise ContractError("manifest must be an object")
    for field in ("run_id", "fight_id", "game"):
        if not isinstance(manifest.get(field), str) or not manifest[field].strip():
            raise ContractError(f"manifest.{field} must be a nonempty string")
    if manifest["game"] != "Overwatch 2":
        raise ContractError("Only Overwatch 2 is supported")
    if manifest.get("prealigned_input_assumed") is not True:
        raise ContractError("The five inputs must already be aligned")
    if manifest.get("status", "PASS") not in ("PASS", "PASS_WITH_LIMITATIONS"):
        raise ContractError("S0 is BLOCKED or FAIL")
    start = finite_number(manifest.get("fight_start_timestamp"), "fight_start_timestamp")
    end = finite_number(manifest.get("fight_end_timestamp"), "fight_end_timestamp")
    if end <= start:
        raise ContractError("fight_end_timestamp must exceed fight_start_timestamp")
    videos = manifest.get("videos")
    if not isinstance(videos, list) or len(videos) != len(POV_IDS):
        raise ContractError("manifest requires exactly five videos")
    ids = [video.get("pov_id") for video in videos if isinstance(video, dict)]
    if len(ids) != len(POV_IDS) or any(not isinstance(pov, str) for pov in ids) or set(ids) != set(POV_IDS):
        raise ContractError(f"manifest POV IDs must be exactly {POV_IDS}")
    paths = []
    for video in videos:
        pov = video["pov_id"]
        path = video.get("path")
        if not isinstance(path, str) or not path.strip():
            raise ContractError(f"{pov}.path must be a nonempty string")
        paths.append(path)
        if not re.fullmatch(r"[a-fA-F0-9]{64}", str(video.get("sha256", ""))):
            raise ContractError(f"{pov}.sha256 must be a SHA-256 hex digest")
        duration = finite_number(video.get("duration_seconds"), f"{pov}.duration_seconds")
        if duration <= 0 or finite_number(video.get("fps"), f"{pov}.fps") <= 0:
            raise ContractError(f"{pov} duration and fps must be positive")
        for field in ("width", "height"):
            if type(video.get(field)) is not int or video[field] <= 0:
                raise ContractError(f"{pov}.{field} must be a positive integer")
        if type(video.get("audio_present")) is not bool:
            raise ContractError(f"{pov}.audio_present must be boolean")
        if not isinstance(video.get("hero"), str) or not video["hero"].strip():
            raise ContractError(f"{pov}.hero must be a name or 'unknown'")
        status = video.get("coverage_status")
        if status not in ("complete", "limited"):
            raise ContractError(f"{pov}.coverage_status must be complete or limited")
        missing = video.get("missing_intervals", [])
        if not isinstance(missing, list):
            raise ContractError(f"{pov}.missing_intervals must be a list")
        for interval in missing:
            if not isinstance(interval, dict):
                raise ContractError(f"{pov} missing interval must be an object")
            left = finite_number(interval.get("start_timestamp"), "missing interval start")
            right = finite_number(interval.get("end_timestamp"), "missing interval end")
            if not start <= left < right <= end:
                raise ContractError(f"{pov} missing interval is outside the fight")
        if status == "complete" and (duration < end or missing):
            raise ContractError(f"{pov} claims complete coverage but has gaps")
    if len(set(paths)) != len(paths):
        raise ContractError("Each POV must use a distinct recording path")
    return manifest


@dataclass(frozen=True, order=True)
class EvidenceRef:
    pov_id: str
    start_timestamp: float
    end_timestamp: float

    @classmethod
    def parse(cls, value: str, manifest: dict[str, Any] | None = None) -> "EvidenceRef":
        if not isinstance(value, str):
            raise ContractError("Evidence reference must be a string")
        match = REF_PATTERN.fullmatch(value)
        if not match or match[1] not in POV_IDS:
            raise ContractError(f"Invalid evidence reference: {value!r}")
        start = finite_number(float(match[2]), "evidence start")
        end = finite_number(float(match[3]), "evidence end")
        if end <= start:
            raise ContractError(f"Evidence interval must have positive duration: {value}")
        ref = cls(match[1], start, end)
        if manifest is not None:
            left, right = manifest["fight_start_timestamp"], manifest["fight_end_timestamp"]
            if not left <= start < end <= right:
                raise ContractError(f"Evidence outside fight interval: {value}")
            video = next((v for v in manifest["videos"] if v["pov_id"] == ref.pov_id), None)
            if video is None or end > video["duration_seconds"]:
                raise ContractError(f"Evidence outside available video: {value}")
            for gap in video.get("missing_intervals", []):
                if start < gap["end_timestamp"] and end > gap["start_timestamp"]:
                    raise ContractError(f"Evidence overlaps missing coverage: {value}")
        return ref

    def __str__(self) -> str:
        def decimal(value: float) -> str:
            # Shortest round-trip spelling, expanded without scientific notation.
            # Do not round sub-frame values or tiny intervals to a different time.
            text = format(Decimal(str(float(value))), "f")
            return text if "." in text else text + ".0"

        return f"{self.pov_id}@{decimal(self.start_timestamp)}-{decimal(self.end_timestamp)}"


def extract_evidence_refs(text: str, manifest: dict[str, Any] | None = None) -> list[EvidenceRef]:
    refs = [EvidenceRef.parse(match[0], manifest) for match in REF_PATTERN.finditer(text)]
    # A malformed known-POV token must not quietly disappear from the ledger.
    # Other nonnumeric @ tokens can be ordinary file names or reviewer emails;
    # numeric citation-shaped tokens above still validate arbitrary/unknown IDs.
    pov_pattern = "|".join(re.escape(pov) for pov in POV_IDS)
    for token in re.findall(r"\b(?:" + pov_pattern + r")@[^\s`\]\[<>,;()]+", text):
        refs.append(EvidenceRef.parse(token.rstrip("."), manifest))
    return list(dict.fromkeys(refs))


def validate_references(
    refs: Any,
    manifest: dict[str, Any],
    allowed_refs: set[str] | None = None,
) -> list[str]:
    if not isinstance(refs, list) or not refs:
        raise ContractError("At least one evidence reference is required")
    parsed = [str(EvidenceRef.parse(value, manifest)) for value in refs]
    if len(parsed) != len(set(parsed)):
        raise ContractError("Duplicate evidence references")
    if allowed_refs is not None:
        canonical_allowed = {str(EvidenceRef.parse(value, manifest)) for value in allowed_refs}
        unknown = set(parsed) - canonical_allowed
        if unknown:
            raise ContractError(f"Evidence not present in upstream sources: {sorted(unknown)}")
    return parsed


POV_HEADINGS = (
    "Metadata", "Gameplay Context", "Timestamped Behavioral Timeline",
    "Player Information State", "Cross-POV Verification Questions",
    "Neutral Behavioral Summary", "Coverage and Limitations", "Agent Handoff",
)

_EVENT_HEADING = re.compile(
    r"\[[ \t]*(\d+(?:\.\d+)?)[ \t]*[-\u2013\u2014][ \t]*"
    r"(\d+(?:\.\d+)?)[ \t]*s[ \t]*\](?:[ \t]+[^\n]+)?"
)
_EVENT_FIELDS = ("Observed", "Immediate outcome", "Evidence", "Evidence quality", "Inference/unknown")
_JUDGMENT_LABEL = re.compile(
    r"\b(?:bad play|to blame|blame|primary responsibility|secondary responsibility|scapegoat|"
    r"throw(?:ing)? (?:the |this )?(?:fight|game))\b|背锅|甩锅|主要责任|次要责任|操作评分|送人头",
    re.I,
)


def _report_field(section: str, name: str, label: str) -> str:
    """Read one nonempty bullet value without letting whitespace cross lines."""
    matches = re.findall(r"^- " + re.escape(name) + r":[ \t]*([^\n]*)$", section, re.M)
    if len(matches) != 1 or not matches[0].strip():
        raise ContractError(f"{label}: expected exactly one nonempty '- {name}: ...' field")
    return matches[0].strip()


def _neutral_observation(text: str, label: str) -> None:
    # Declining to assign blame is permitted. This small lexical check catches
    # overt grading labels; it cannot determine whether a narrative is neutral.
    without_negations = re.sub(
        r"\b(?:no|without|not assigning|do not assign|does not assign)[ \t]+(?:tactical[ \t]+)?(?:blame|judgment)\b",
        "", text, flags=re.I,
    )
    if _JUDGMENT_LABEL.search(without_negations) or without_negations.strip().lower() in {"throw", "throwing"}:
        raise ContractError(f"{label}: Stage A observations must remain neutral; tactical grading belongs to Stage C")


def validate_pov_report(text: str, pov_id: str, manifest: dict[str, Any]) -> dict[str, Any]:
    """Check the documented natural-language Stage A handoff, not event correctness."""
    if not isinstance(text, str) or pov_id not in POV_IDS:
        raise ContractError("A POV report requires text and a known POV ID")
    # Normalize line endings only. Do not silently rewrite source prose or its
    # timestamp/citation conventions while checking the handoff.
    text = text.replace("\r\n", "\n")
    parsed_sections = re.findall(r"^## ([^\n]+)\n(.*?)(?=^## |\Z)", text, re.M | re.S)
    sections = dict(parsed_sections)
    for heading in POV_HEADINGS:
        if sum(1 for name, _ in parsed_sections if name == heading) > 1:
            raise ContractError(f"{pov_id}: duplicate heading '## {heading}'")
        if not sections.get(heading, "").strip():
            raise ContractError(f"{pov_id}: missing or empty heading '## {heading}'")
    handoff = sections["Agent Handoff"]
    if _report_field(handoff, "Stage", pov_id) != "A":
        raise ContractError(f"{pov_id}: expected an independent Stage A handoff")
    for field in ("Inputs consumed", "Outputs produced", "Prompt/model/tool versions", "Evidence coverage", "Unresolved questions", "Known limitations", "Recommended next action"):
        _report_field(handoff, field, pov_id)
    status = _report_field(handoff, "Status", pov_id)
    if status not in ("PASS", "PASS_WITH_LIMITATIONS"):
        raise ContractError(f"{pov_id}: Stage A must explicitly hand off PASS or PASS_WITH_LIMITATIONS")
    prompt_version = _report_field(sections["Metadata"], "prompt_version", pov_id)
    method = _report_field(sections["Metadata"], "Inspection coverage / method", pov_id)
    if method.lower() in ("unknown", "none", "...", "todo"):
        raise ContractError(f"{pov_id}: actual inspection coverage / method is required")
    refs = extract_evidence_refs(text, manifest)
    if not refs or any(ref.pov_id != pov_id for ref in refs):
        raise ContractError(f"{pov_id}: citations must reference this POV only")
    timeline = sections["Timestamped Behavioral Timeline"]
    events = re.split(r"^### ", timeline, flags=re.M)[1:]
    if not events:
        raise ContractError(f"{pov_id}: timeline requires timestamped ### event entries")
    event_intervals = []
    for event in events:
        heading, separator, body = event.partition("\n")
        match = _EVENT_HEADING.fullmatch(heading.strip())
        if not match or not separator:
            raise ContractError(f"{pov_id}: event heading must be '### [start\u2013end s]'")
        start = finite_number(float(match[1]), "event start")
        end = finite_number(float(match[2]), "event end")
        if not manifest["fight_start_timestamp"] <= start < end <= manifest["fight_end_timestamp"]:
            raise ContractError(f"{pov_id}: event heading lies outside the fight interval")
        fields = {field: _report_field(body, field, f"{pov_id} event {heading}") for field in _EVENT_FIELDS}
        if fields["Evidence quality"].lower() not in {"high", "medium", "low"}:
            raise ContractError(f"{pov_id}: Evidence quality must be high, medium, or low")
        evidence = extract_evidence_refs(fields["Evidence"], manifest)
        if not evidence:
            raise ContractError(f"{pov_id}: every timeline event needs an Evidence field with a source reference")
        for ref in extract_evidence_refs(event, manifest):
            if ref.end_timestamp <= start or ref.start_timestamp >= end:
                raise ContractError(f"{pov_id}: event citation must overlap its heading interval")
        for field in ("Observed", "Immediate outcome"):
            _neutral_observation(fields[field], f"{pov_id} {field}")
        event_intervals.append({"start_timestamp": start, "end_timestamp": end,
                                "evidence_refs": [str(ref) for ref in evidence]})
    _neutral_observation(sections["Neutral Behavioral Summary"], f"{pov_id} summary")
    return {
        "pov_id": pov_id, "status": status, "prompt_version": prompt_version,
        "inspection_method": method, "evidence_refs": [str(ref) for ref in refs],
        "event_intervals": event_intervals,
    }
