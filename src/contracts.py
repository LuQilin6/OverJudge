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
    # A malformed token must not quietly disappear from the citation ledger.
    for token in re.findall(r"\b[A-Za-z][A-Za-z0-9_]*@[^\s`\]\[<>,;()]+", text):
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


def validate_pov_report(text: str, pov_id: str, manifest: dict[str, Any]) -> dict[str, Any]:
    """Check the documented natural-language Stage A handoff, not event correctness."""
    sections = dict(re.findall(r"^## ([^\n]+)\n(.*?)(?=^## |\Z)", text, re.M | re.S))
    for heading in POV_HEADINGS:
        if not sections.get(heading, "").strip():
            raise ContractError(f"{pov_id}: missing or empty heading '## {heading}'")
    handoff = sections["Agent Handoff"]
    if not re.search(r"^- Stage:\s*A\s*$", handoff, re.M):
        raise ContractError(f"{pov_id}: expected an independent Stage A handoff")
    for field in ("Inputs consumed", "Outputs produced", "Prompt/model/tool versions", "Evidence coverage", "Unresolved questions", "Known limitations", "Recommended next action"):
        if not re.search(r"^- " + re.escape(field) + r":\s*\S[^\n]*", handoff, re.M):
            raise ContractError(f"{pov_id}: missing Agent Handoff field '{field}'")
    status_match = re.search(r"^- Status:\s*(PASS_WITH_LIMITATIONS|PASS|BLOCKED|FAIL)\s*$", sections["Agent Handoff"], re.M)
    if not status_match or status_match[1] not in ("PASS", "PASS_WITH_LIMITATIONS"):
        raise ContractError(f"{pov_id}: Stage A must explicitly hand off PASS or PASS_WITH_LIMITATIONS")
    prompt_match = re.search(r"^- prompt_version:\s*(\S[^\n]*)", sections["Metadata"], re.M)
    if not prompt_match:
        raise ContractError(f"{pov_id}: Metadata needs '- prompt_version: ...'")
    method_match = re.search(r"^- Inspection coverage / method:\s*(\S[^\n]*)", sections["Metadata"], re.M)
    if not method_match or method_match[1].strip().lower() in ("unknown", "none", "...", "todo"):
        raise ContractError(f"{pov_id}: actual inspection coverage / method is required")
    refs = extract_evidence_refs(text, manifest)
    if not refs or any(ref.pov_id != pov_id for ref in refs):
        raise ContractError(f"{pov_id}: citations must reference this POV only")
    timeline = sections["Timestamped Behavioral Timeline"]
    events = re.split(r"^### ", timeline, flags=re.M)[1:]
    if not events:
        raise ContractError(f"{pov_id}: timeline requires timestamped ### event entries")
    for event in events:
        if not extract_evidence_refs(event, manifest):
            raise ContractError(f"{pov_id}: every timeline event needs an evidence reference")
    return {
        "pov_id": pov_id, "status": status_match[1], "prompt_version": prompt_match[1],
        "inspection_method": method_match[1], "evidence_refs": [str(ref) for ref in refs],
    }
