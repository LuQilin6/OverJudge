"""Stage B contracts and deterministic rendering for manually authored fusion.

These checks establish structure and provenance, not whether prose is true. A
Codex analyst must still compare the five reports and preserve disagreements.
"""

from __future__ import annotations

from copy import deepcopy
import math
import re
from typing import Any

from .contracts import ContractError, EvidenceRef, POV_IDS, supplied_povs, extract_evidence_refs, validate_references


SCHEMA_VERSION = "1.0"
PROMPT_VERSION = "stage-b-1.0"
PHASE_NAMES = ("setup", "initiation", "first_major_exchange", "turning_points", "outcome")
EPISTEMIC_STATES = {"observed", "inferred", "unknown", "conflicted"}
SOURCE_STATES = {"corroborated", "single_source", "conflicting", "unresolved"}
_JUDGMENT = re.compile(
    r"\b(?:bad play|to blame|blame percentage|primary responsibility|"
    r"secondary responsibility|throwing the fight|tactical grade|scapegoat)\b"
    r"|背锅|甩锅|责任占比|主要责任|次要责任|操作评分",
    re.IGNORECASE,
)


def _object(value: Any, label: str, keys: set[str]) -> dict:
    if not isinstance(value, dict) or set(value) != keys:
        actual = set(value) if isinstance(value, dict) else set()
        raise ContractError(f"{label}: expected fields {sorted(keys)}; missing={sorted(keys-actual)}, extra={sorted(actual-keys)}")
    return value


def _text(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ContractError(f"{label}: expected nonempty text; use 'unknown' when evidence is absent")
    if _JUDGMENT.search(value):
        raise ContractError(f"{label}: Stage B must remain neutral and cannot assign blame or tactical grades")
    return value.strip()


def _list(value: Any, label: str, *, nonempty: bool = False) -> list:
    if not isinstance(value, list) or (nonempty and not value):
        raise ContractError(f"{label}: expected {'nonempty ' if nonempty else ''}list")
    return value


def _strings(value: Any, label: str, *, nonempty: bool = False) -> list[str]:
    return [_text(item, label) for item in _list(value, label, nonempty=nonempty)]


def _interval(item: dict, manifest: dict, label: str) -> None:
    start, end = item["start_timestamp"], item["end_timestamp"]
    for value in (start, end):
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            raise ContractError(f"{label}: interval timestamps must be finite numbers")
    if not manifest["fight_start_timestamp"] <= start < end <= manifest["fight_end_timestamp"]:
        raise ContractError(f"{label}: interval must lie within the common fight interval")


def _refs(value: Any, manifest: dict, allowed_refs: set[str], label: str, *, allow_empty: bool = False) -> list[str]:
    _list(value, label)
    if not value and allow_empty:
        return []
    return validate_references(value, manifest, allowed_refs)


def _claim(value: Any, manifest: dict, allowed_refs: set[str], label: str) -> dict:
    value = _object(value, label, {"description", "epistemic_status", "evidence_refs"})
    value["description"] = _text(value["description"], label)
    if not isinstance(value["epistemic_status"], str) or value["epistemic_status"] not in EPISTEMIC_STATES:
        raise ContractError(f"{label}: invalid epistemic_status")
    value["evidence_refs"] = _refs(
        value["evidence_refs"], manifest, allowed_refs, label,
        allow_empty=value["epistemic_status"] == "unknown",
    )
    return value


def validate_result(payload: dict, manifest: dict, allowed_refs: set[str]) -> dict:
    """Validate a Stage B response and return a normalized independent copy.

    Allowed citations must come from the original Stage A reports. No timestamp
    conversion, new observation, or silent conflict resolution is performed.
    """
    result = deepcopy(payload)
    _object(result, "B response", {
        "schema_version", "status", "shared_context", "events", "phases", "action_matrix",
        "team_coordination", "turning_points", "player_knowledge_limits", "conflicts",
        "uncertainties", "reinspection_requests", "revision_log", "neutral_summary", "limitations",
    })
    if result["schema_version"] != SCHEMA_VERSION:
        raise ContractError(f"B schema_version must be {SCHEMA_VERSION}")
    if not isinstance(result["status"], str) or result["status"] not in {"PASS", "PASS_WITH_LIMITATIONS"}:
        raise ContractError("B response status must be PASS or PASS_WITH_LIMITATIONS")
    result["shared_context"] = _claim(result["shared_context"], manifest, allowed_refs, "shared_context")
    events = _list(result["events"], "events", nonempty=True)
    event_by_id: dict[str, dict] = {}
    previous_start = -1.0
    for event in events:
        _object(event, "event", {"event_id", "start_timestamp", "end_timestamp", "description", "epistemic_status", "source_status", "evidence_refs"})
        event_id = _text(event["event_id"], "event_id")
        event["event_id"] = event_id
        if event_id in event_by_id:
            raise ContractError(f"duplicate event_id: {event_id}")
        _interval(event, manifest, event_id)
        if event["start_timestamp"] < previous_start:
            raise ContractError("events must be ordered by start_timestamp")
        previous_start = event["start_timestamp"]
        event["description"] = _text(event["description"], event_id)
        if (not isinstance(event["epistemic_status"], str) or event["epistemic_status"] not in EPISTEMIC_STATES
                or not isinstance(event["source_status"], str) or event["source_status"] not in SOURCE_STATES):
            raise ContractError(f"{event_id}: invalid epistemic/source status")
        unknown = event["epistemic_status"] == "unknown"
        event["evidence_refs"] = _refs(event["evidence_refs"], manifest, allowed_refs, event_id, allow_empty=unknown)
        parsed = [EvidenceRef.parse(ref, manifest) for ref in event["evidence_refs"]]
        source_count = len({ref.pov_id for ref in parsed})
        if event["source_status"] == "corroborated" and source_count < 2:
            raise ContractError(f"{event_id}: corroborated events require at least two POVs")
        if event["source_status"] == "single_source" and source_count != 1:
            raise ContractError(f"{event_id}: single_source must cite exactly one POV")
        if (event["source_status"] == "conflicting") != (event["epistemic_status"] == "conflicted"):
            raise ContractError(f"{event_id}: conflicting sources and conflicted epistemic status must agree")
        if unknown and event["source_status"] != "unresolved":
            raise ContractError(f"{event_id}: unknown events must remain unresolved")
        for ref in parsed:
            if ref.end_timestamp <= event["start_timestamp"] or ref.start_timestamp >= event["end_timestamp"]:
                raise ContractError(f"{event_id}: cited evidence must overlap the event interval")
        event_by_id[event_id] = event

    phases = _list(result["phases"], "phases", nonempty=True)
    phase_by_id: dict[str, dict] = {}
    for phase in phases:
        _object(phase, "phase", {"phase_id", "name", "start_timestamp", "end_timestamp", "summary"})
        phase_id = _text(phase["phase_id"], "phase_id")
        phase["phase_id"] = phase_id
        if phase_id in phase_by_id:
            raise ContractError(f"duplicate phase_id: {phase_id}")
        if phase["name"] not in PHASE_NAMES:
            raise ContractError(f"{phase_id}: invalid phase name")
        _interval(phase, manifest, phase_id)
        phase["summary"] = _claim(phase["summary"], manifest, allowed_refs, f"{phase_id} summary")
        phase_by_id[phase_id] = phase
    if {phase["name"] for phase in phases} != set(PHASE_NAMES):
        raise ContractError("phases must represent setup, initiation, first_major_exchange, turning_points and outcome; unknown is permitted")

    rows = _list(result["action_matrix"], "action_matrix", nonempty=True)
    covered_phases: set[str] = set()
    for row in rows:
        _object(row, "action matrix row", {"phase_id", "players"})
        phase_id = _text(row["phase_id"], "action matrix phase_id")
        row["phase_id"] = phase_id
        if phase_id not in phase_by_id or phase_id in covered_phases:
            raise ContractError("action matrix must have exactly one row per phase_id")
        covered_phases.add(phase_id)
        _object(row["players"], f"{phase_id} players", set(supplied_povs(manifest)))
        for pov_id in supplied_povs(manifest):
            row["players"][pov_id] = _claim(row["players"][pov_id], manifest, allowed_refs, f"{phase_id}/{pov_id}")
    if covered_phases != set(phase_by_id):
        raise ContractError("action matrix is missing a phase")

    for field in ("team_coordination", "neutral_summary"):
        result[field] = [_claim(item, manifest, allowed_refs, field) for item in _list(result[field], field, nonempty=True)]
    turning_points = _strings(result["turning_points"], "turning_points")
    result["turning_points"] = turning_points
    if len(turning_points) != len(set(turning_points)) or not set(turning_points) <= set(event_by_id):
        raise ContractError(f"turning_points must contain unique known event IDs as strings, chosen from {sorted(event_by_id)}; got {turning_points}")
    _object(result["player_knowledge_limits"], "player_knowledge_limits", set(supplied_povs(manifest)))
    for pov_id in supplied_povs(manifest):
        result["player_knowledge_limits"][pov_id] = _strings(result["player_knowledge_limits"][pov_id], f"{pov_id} knowledge limits", nonempty=True)

    conflicts = _list(result["conflicts"], "conflicts")
    conflict_by_id: dict[str, dict] = {}
    conflicting_events: set[str] = set()
    critical_unresolved: set[str] = set()
    for conflict in conflicts:
        _object(conflict, "conflict", {"conflict_id", "description", "event_ids", "evidence_refs", "severity", "status", "resolution", "resolution_evidence_refs"})
        conflict_id = _text(conflict["conflict_id"], "conflict_id")
        conflict["conflict_id"] = conflict_id
        if conflict_id in conflict_by_id:
            raise ContractError(f"duplicate conflict_id: {conflict_id}")
        conflict["description"] = _text(conflict["description"], conflict_id)
        conflict["event_ids"] = _strings(conflict["event_ids"], "conflict event_ids", nonempty=True)
        if not set(conflict["event_ids"]) <= set(event_by_id):
            raise ContractError(f"{conflict_id}: unknown event IDs")
        conflicting_events.update(conflict["event_ids"])
        conflict["evidence_refs"] = _refs(conflict["evidence_refs"], manifest, allowed_refs, conflict_id)
        if (not isinstance(conflict["severity"], str) or conflict["severity"] not in {"critical", "minor"}
                or not isinstance(conflict["status"], str) or conflict["status"] not in {"resolved", "unresolved"}):
            raise ContractError(f"{conflict_id}: invalid conflict severity/status")
        conflict["resolution"] = _text(conflict["resolution"], f"{conflict_id} resolution")
        conflict["resolution_evidence_refs"] = _refs(conflict["resolution_evidence_refs"], manifest, allowed_refs, f"{conflict_id} resolution", allow_empty=conflict["status"] == "unresolved")
        if conflict["status"] == "unresolved" and conflict["severity"] == "critical":
            critical_unresolved.add(conflict_id)
        conflict_by_id[conflict_id] = conflict
    for event_id, event in event_by_id.items():
        if event["source_status"] == "conflicting" and event_id not in conflicting_events:
            raise ContractError(f"{event_id}: conflicting event must be retained in conflicts ledger")

    requests = _list(result["reinspection_requests"], "reinspection_requests")
    requested_conflicts: set[str] = set()
    for request in requests:
        _object(request, "reinspection request", {"conflict_id", "pov_id", "start_timestamp", "end_timestamp", "question"})
        conflict_id = _text(request["conflict_id"], "reinspection conflict_id")
        request["conflict_id"] = conflict_id
        if conflict_id not in conflict_by_id:
            raise ContractError("reinspection request must identify a known conflict")
        if request["pov_id"] not in supplied_povs(manifest):
            raise ContractError("reinspection request has unknown POV")
        _interval(request, manifest, "reinspection request")
        request["question"] = _text(request["question"], "reinspection question")
        requested_conflicts.add(conflict_id)
    if not critical_unresolved <= requested_conflicts:
        raise ContractError("every unresolved critical conflict requires targeted Stage A reinspection")
    if critical_unresolved and result["status"] != "PASS_WITH_LIMITATIONS":
        raise ContractError("unresolved critical conflicts require PASS_WITH_LIMITATIONS and remain unresolved for Stage C")
    for field in ("uncertainties", "revision_log", "limitations"):
        result[field] = _strings(result[field], field, nonempty=field == "limitations" and result["status"] == "PASS_WITH_LIMITATIONS")
    def check_inline_references(value: Any) -> None:
        if isinstance(value, str):
            inline = extract_evidence_refs(value, manifest)
            if inline:
                validate_references([str(ref) for ref in inline], manifest, allowed_refs)
        elif isinstance(value, list):
            for child in value:
                check_inline_references(child)
        elif isinstance(value, dict):
            for child in value.values():
                check_inline_references(child)
    check_inline_references(result)
    return result


def _claim_text(claim: dict) -> str:
    references = ", ".join(claim["evidence_refs"]) or "no evidence; unknown"
    return f"**{claim['epistemic_status']}**: {claim['description']} ({references})"


def _cell(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", "<br>")


def render_report(payload: dict, metadata: dict) -> str:
    """Render an already validated payload without adding analytical claims."""
    lines = ["# Cross-POV Fusion", "", "## Metadata", ""]
    for key in ("run_id", "fight_id", "prompt_version", "prompt_sha256", "status"):
        lines.append(f"- {key}: {metadata.get(key, payload.get(key, 'unknown'))}")
    lines += ["", "## Shared Context", "", _claim_text(payload["shared_context"]),
              "", "## Input Coverage and Alignment Assumption", "",
              "Inputs are assumed pre-aligned. All timestamps use the original aligned-video zero point; Stage B applies no offset or time conversion.",
              "Structural citation checks do not establish factual or semantic correctness."]
    lines += [f"- {item}" for item in payload["limitations"]] or ["- No additional limitations reported by the analyst."]
    lines += ["", "## Unified Timeline", ""]
    for event in payload["events"]:
        lines += [f"### {event['event_id']} [{event['start_timestamp']}–{event['end_timestamp']} s]",
                  f"- {event['epistemic_status']} / {event['source_status']}: {event['description']}",
                  f"- Evidence: {', '.join(event['evidence_refs']) or 'unknown'}", ""]
    lines += ["### Fight Phases", ""]
    for phase in payload["phases"]:
        lines.append(f"- {phase['phase_id']} — {phase['name']} [{phase['start_timestamp']}–{phase['end_timestamp']} s]: {_claim_text(phase['summary'])}")
    lines += ["", ("## Five-Player Action Matrix" if len(payload["player_knowledge_limits"]) == 5 else "## Supplied-Perspective Action Matrix"), "", "| Phase | " + " | ".join(payload["player_knowledge_limits"]) + " |", "|---|" + "---|" * len(payload["player_knowledge_limits"])]
    for row in payload["action_matrix"]:
        cells = [row["phase_id"]] + [_claim_text(row["players"][pov]) for pov in payload["player_knowledge_limits"]]
        lines.append("| " + " | ".join(_cell(cell) for cell in cells) + " |")
    lines += ["", "## Team Coordination", ""] + [f"- {_claim_text(claim)}" for claim in payload["team_coordination"]]
    lines += ["", "## Turning Points", ""]
    lines += [f"- {event_id}: {next(event['description'] for event in payload['events'] if event['event_id'] == event_id)}" for event_id in payload["turning_points"]] or ["- No supported turning point established."]
    lines += ["", "## Player Knowledge Limits", "", "Global reconstruction must not be treated as information each player possessed at the time."]
    for pov_id in payload["player_knowledge_limits"]:
        lines.append(f"- {pov_id}: {'; '.join(payload['player_knowledge_limits'][pov_id])}")
    lines += ["", "## Conflicts and Uncertainties", ""]
    for conflict in payload["conflicts"]:
        lines += [f"- {conflict['conflict_id']} ({conflict['severity']}, {conflict['status']}): {conflict['description']}",
                  f"  - Events: {', '.join(conflict['event_ids'])}; evidence: {', '.join(conflict['evidence_refs'])}",
                  f"  - Resolution: {conflict['resolution']}; evidence: {', '.join(conflict['resolution_evidence_refs']) or 'none; remains unresolved'}"]
    lines += [f"- Uncertainty: {item}" for item in payload["uncertainties"]]
    if not payload["conflicts"] and not payload["uncertainties"]:
        lines.append("- No conflicts or uncertainties reported by the analyst; this is not an independent verification.")
    lines += ["", "### Stage A Reinspection Requests", ""]
    lines += [f"- {item['conflict_id']}: {item['pov_id']}@{item['start_timestamp']}-{item['end_timestamp']} — {item['question']}" for item in payload["reinspection_requests"]] or ["- None."]
    lines += ["", "### Revision Log", ""] + [f"- {item}" for item in payload["revision_log"]]
    refs: set[str] = set()
    def collect(value: Any) -> None:
        if isinstance(value, dict):
            for key, child in value.items():
                if key in {"evidence_refs", "resolution_evidence_refs"}:
                    refs.update(child)
                else:
                    collect(child)
        elif isinstance(value, list):
            for child in value:
                collect(child)
    collect(payload)
    lines += ["", "## Evidence Index", ""] + [f"- {ref}" for ref in sorted(refs)]
    lines += ["", "## Neutral Summary", ""] + [f"- {_claim_text(claim)}" for claim in payload["neutral_summary"]]
    lines += ["", "## Agent Handoff", "", "- Stage: B", f"- Status: {payload['status']}",
              "- Inputs consumed: supplied original POV reports and manifest; see task input hashes.",
              "- Outputs produced: fusion.json and fusion.md",
              f"- Prompt/model/tool versions: {metadata.get('prompt_version', PROMPT_VERSION)}; {metadata.get('model', 'manual Codex workflow')}",
              f"- Evidence coverage: {len(refs)} distinct source intervals; semantics require human/agent review.",
              f"- Unresolved questions: {'; '.join(payload['uncertainties']) or 'see conflict ledger'}",
              f"- Known limitations: {'; '.join(payload['limitations']) or 'structural checks do not establish factual correctness'}",
              "- Recommended next action: review reinspection requests and limitations before Stage C.", ""]
    return "\n".join(lines)


def example_response(pov_ids=POV_IDS) -> dict:
    """Synthetic shape example; it is not an analysis of any real recording."""
    unknown = {"description": "not observed; unknown", "epistemic_status": "unknown", "evidence_refs": []}
    observed = {"description": "Synthetic example only: a visible movement is reported.", "epistemic_status": "observed", "evidence_refs": [f"{pov_ids[0]}@1.0-2.0"]}
    phases = [{"phase_id": f"p{index+1}", "name": name, "start_timestamp": float(index), "end_timestamp": float(index+1), "summary": deepcopy(unknown)} for index, name in enumerate(PHASE_NAMES)]
    return {
        "schema_version": SCHEMA_VERSION, "status": "PASS_WITH_LIMITATIONS",
        "shared_context": deepcopy(unknown),
        "events": [{"event_id": "e1", "start_timestamp": 1.0, "end_timestamp": 2.0, "description": observed["description"], "epistemic_status": "observed", "source_status": "single_source", "evidence_refs": [f"{pov_ids[0]}@1.0-2.0"]}],
        "phases": phases,
        "action_matrix": [{"phase_id": phase["phase_id"], "players": {pov: deepcopy(unknown) for pov in pov_ids}} for phase in phases],
        "team_coordination": [deepcopy(unknown)], "turning_points": [],
        "player_knowledge_limits": {pov: ["Only this player's visible/audible information may be attributed to them; other information is unknown."] for pov in pov_ids},
        "conflicts": [], "uncertainties": ["Synthetic example only; no video has been inspected."],
        "reinspection_requests": [], "revision_log": [], "neutral_summary": [deepcopy(observed)],
        "limitations": ["Synthetic example only; replace every field using the supplied Stage A reports."],
    }


def response_schema(pov_ids=POV_IDS) -> dict:
    """Machine-readable field guide included with every manual Stage B task."""
    return {
        "schema_version": SCHEMA_VERSION,
        "prompt_version": PROMPT_VERSION,
        "response_fields": list(example_response(pov_ids)),
        "example": example_response(pov_ids),
        "claim": {"description": "nonempty neutral text", "epistemic_status": sorted(EPISTEMIC_STATES), "evidence_refs": "source POV@start-end list; required unless epistemic_status=unknown"},
        "list_item_contracts": {
            "turning_points": "Array of unique existing event_id STRINGS, e.g. ['e1']; never claim objects. Empty is allowed.",
            "conflicts": {"conflict_id": "unique string", "description": "text", "event_ids": ["existing event_id"], "evidence_refs": ["exact source reference"], "severity": "critical|minor", "status": "resolved|unresolved", "resolution": "text or unknown", "resolution_evidence_refs": "reference array, may be empty only when unresolved"},
            "reinspection_requests": {"conflict_id": "existing conflict_id", "pov_id": "supplied POV", "start_timestamp": "number", "end_timestamp": "number", "question": "nonempty text"},
            "uncertainties_revision_log_limitations": "Each is an array of nonempty STRINGS, never objects.",
        },
        "phase_names": list(PHASE_NAMES),
        "event_source_status": sorted(SOURCE_STATES),
        "constraints": [
            "Return one JSON object with exactly the example's top-level fields; never return example facts as real observations.",
            "Every consequential event and non-unknown claim requires an exact citation from the original reports; preserve every supporting source.",
            "Represent every supplied perspective in one matrix row per phase; use unknown, never infer inactivity from missing observations.",
            "Every conflicting event must appear in the conflict ledger; unresolved critical conflicts require a targeted reinspection request and PASS_WITH_LIMITATIONS.",
            "Do not assign tactical grades, player blame, responsibility rankings or percentages.",
            "Do not shift or convert timestamps. Preserve observed/inferred/unknown/conflicted distinctions and player knowledge limits.",
        ],
    }
