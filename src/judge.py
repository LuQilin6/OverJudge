"""Stage C's manual-response contract and evidence-preserving report renderer.

This module validates structure and provenance, not the truth of tactical claims.
Stage D must independently inspect footage before releasing adverse findings.
"""

from __future__ import annotations

import copy
import re
from typing import Any

from .contracts import ContractError, POV_IDS, supplied_povs, extract_evidence_refs, validate_references


SCHEMA_VERSION = "1.0"
PROMPT_VERSION = "stage-c-v1"
FINDING_LEVELS = ("primary", "secondary", "shared", "not_established")
ADVERSE_LEVELS = frozenset(("primary", "secondary", "shared"))
REQUIRED_SECTIONS = (
    "Fight Summary",
    "Confirmed Facts",
    "Candidate Mistakes",
    "Causal Analysis",
    "Alternative Explanations",
    "Player-by-Player Findings",
    "Verdict or Inconclusive",
    "Top 3 Evidence Clips",
    "Actionable Lessons",
    "Confidence and Limitations",
)

_PERCENTAGE = re.compile(r"\d+(?:\.\d+)?\s*[%％]|百分之\s*[零〇一二三四五六七八九十百千万\d.]+")
_ATTRIBUTION = re.compile(
    r"\b(?:blame|responsibilit(?:y|ies)|responsible|fault|confidence|probabilit(?:y|ies))\b"
    r"|责任|责备|背锅|归责|过错|置信|概率|贡献占比|贡献比例",
    re.IGNORECASE,
)


def _reject_attribution_percentage(value: str, path: str) -> None:
    """Keep HUD percentages while rejecting numerical blame/confidence claims.

    A factual HUD reading and a separate warning against blame may coexist.
    This is a narrow lexical guard; the independent audit still checks meaning.
    """
    clauses = re.split(r"[,，;；。!?！？\n]|(?<!\d)\.(?!\d)", value)
    if any(_PERCENTAGE.search(clause) and _ATTRIBUTION.search(clause) for clause in clauses):
        raise ContractError(f"{path} must not state numerical responsibility or confidence")


def _validate_prose_references(value: Any, manifest: dict, allowed_refs: set[str]) -> None:
    """Do not let a citation hidden in prose escape the evidence allowlist."""
    if isinstance(value, str):
        refs = extract_evidence_refs(value, manifest)
        if refs:
            validate_references([str(ref) for ref in refs], manifest, allowed_refs)
    elif isinstance(value, dict):
        for child in value.values():
            _validate_prose_references(child, manifest, allowed_refs)
    elif isinstance(value, list):
        for child in value:
            _validate_prose_references(child, manifest, allowed_refs)


def _object(value: Any, required: tuple[str, ...], path: str) -> dict:
    if not isinstance(value, dict):
        raise ContractError(f"{path} must be an object")
    missing = set(required) - value.keys()
    extra = value.keys() - set(required)
    if missing or extra:
        details = []
        if missing:
            details.append("missing " + ", ".join(sorted(missing)))
        if extra:
            details.append("unexpected " + ", ".join(sorted(map(str, extra))))
        raise ContractError(f"{path}: {'; '.join(details)}")
    return value


def _text(value: Any, path: str, *, qualitative: bool = False) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ContractError(f"{path} must be a nonempty string")
    value = value.strip()
    if qualitative and _PERCENTAGE.search(value):
        raise ContractError(
            f"{path} must use qualitative responsibility/confidence; "
            "put observed HUD percentages in confirmed_facts"
        )
    return value


def _list(value: Any, path: str, *, nonempty: bool = False) -> list:
    if not isinstance(value, list) or (nonempty and not value):
        raise ContractError(f"{path} must be {'a nonempty' if nonempty else 'an'} array")
    return value


def _texts(value: Any, path: str, *, nonempty: bool = False) -> list[str]:
    return [
        _text(item, f"{path}[{index}]", qualitative=True)
        for index, item in enumerate(_list(value, path, nonempty=nonempty))
    ]


def _enum(value: Any, choices: tuple[str, ...], path: str) -> str:
    if not isinstance(value, str) or value not in choices:
        raise ContractError(f"{path} must be one of {', '.join(choices)}")
    return value


def _refs(value: Any, path: str, manifest: dict, allowed_refs: set[str], *, empty: bool = False) -> list[str]:
    _list(value, path)
    if not value and empty:
        return []
    result = validate_references(value, manifest, allowed_refs)
    if len(result) != len(set(result)):
        raise ContractError(f"{path} contains duplicate references")
    return result


def validate_result(payload: dict, manifest: dict, allowed_refs: set[str]) -> dict:
    """Return a normalized copy of an imported Stage C response.

    All evidence is checked against the upstream allowlist and aligned interval.
    The narrative itself still requires the independent Stage D evidence audit.
    """
    result = copy.deepcopy(payload)
    _object(result, (
        "schema_version", "fight_summary", "confirmed_facts", "findings",
        "player_findings", "alternative_explanations", "verdict",
        "top_evidence_clips", "actionable_lessons", "confidence",
    ), "Stage C response")
    if result["schema_version"] != SCHEMA_VERSION:
        raise ContractError(f"schema_version must be {SCHEMA_VERSION}")

    summary = _object(result["fight_summary"], ("outcome", "summary", "evidence_refs"), "fight_summary")
    _enum(summary["outcome"], ("loss", "win", "draw", "unknown"), "fight_summary.outcome")
    summary["summary"] = _text(summary["summary"], "fight_summary.summary", qualitative=True)
    summary["evidence_refs"] = _refs(
        summary["evidence_refs"], "fight_summary.evidence_refs", manifest,
        allowed_refs, empty=summary["outcome"] == "unknown",
    )
    used_refs = set(summary["evidence_refs"])
    fact_ids = set()
    for index, fact in enumerate(_list(result["confirmed_facts"], "confirmed_facts")):
        path = f"confirmed_facts[{index}]"
        _object(fact, ("id", "claim", "evidence_refs"), path)
        fact["id"] = _text(fact["id"], path + ".id")
        if fact["id"] in fact_ids:
            raise ContractError(f"duplicate confirmed fact id: {fact['id']}")
        fact_ids.add(fact["id"])
        fact["claim"] = _text(fact["claim"], path + ".claim")
        _reject_attribution_percentage(fact["claim"], path + ".claim")
        fact["evidence_refs"] = _refs(fact["evidence_refs"], path + ".evidence_refs", manifest, allowed_refs)
        used_refs.update(fact["evidence_refs"])

    findings = {}
    adverse = []
    for index, finding in enumerate(_list(result["findings"], "findings")):
        path = f"findings[{index}]"
        _object(finding, (
            "id", "pov_id", "level", "claim", "evidence_refs",
            "player_information", "alternative_action", "plausible_consequence",
            "causal_reasoning", "alternative_explanation",
        ), path)
        finding["id"] = _text(finding["id"], path + ".id")
        if finding["id"] in findings:
            raise ContractError(f"duplicate finding id: {finding['id']}")
        _enum(finding["pov_id"], tuple(supplied_povs(manifest)), path + ".pov_id")
        _enum(finding["level"], FINDING_LEVELS, path + ".level")
        for field in (
            "claim", "player_information", "alternative_action", "plausible_consequence",
            "causal_reasoning", "alternative_explanation",
        ):
            finding[field] = _text(finding[field], path + "." + field, qualitative=True)
        finding["evidence_refs"] = _refs(finding["evidence_refs"], path + ".evidence_refs", manifest, allowed_refs)
        findings[finding["id"]] = finding
        used_refs.update(finding["evidence_refs"])
        if finding["level"] in ADVERSE_LEVELS:
            adverse.append(finding)

    players = _object(result["player_findings"], tuple(supplied_povs(manifest)), "player_findings")
    linked_findings = set()
    for pov_id in supplied_povs(manifest):
        path = "player_findings." + pov_id
        player = _object(players[pov_id], ("status", "summary", "finding_ids"), path)
        _enum(player["status"], ("findings", "no_supported_mistake"), path + ".status")
        player["summary"] = _text(player["summary"], path + ".summary", qualitative=True)
        ids = _list(player["finding_ids"], path + ".finding_ids")
        player_adverse = False
        for index, finding_id in enumerate(ids):
            _text(finding_id, f"{path}.finding_ids[{index}]")
            if finding_id not in findings:
                raise ContractError(f"{path} refers to unknown finding {finding_id}")
            if finding_id in linked_findings:
                raise ContractError(f"finding {finding_id} is linked more than once")
            if findings[finding_id]["pov_id"] != pov_id:
                raise ContractError(f"finding {finding_id} belongs to a different POV")
            linked_findings.add(finding_id)
            player_adverse |= findings[finding_id]["level"] in ADVERSE_LEVELS
        if player["status"] == "findings" and not player_adverse:
            raise ContractError(f"{path}.status findings requires an adverse finding")
        if player["status"] == "no_supported_mistake" and player_adverse:
            raise ContractError(f"{path}: no_supported_mistake contradicts an adverse finding")
    if linked_findings != set(findings):
        raise ContractError("every finding must appear in its player's finding_ids")

    result["alternative_explanations"] = _texts(
        result["alternative_explanations"], "alternative_explanations", nonempty=True,
    )
    verdict = _object(result["verdict"], ("outcome", "summary", "limitations"), "verdict")
    _enum(verdict["outcome"], ("inconclusive", "shared", "supported"), "verdict.outcome")
    verdict["summary"] = _text(verdict["summary"], "verdict.summary", qualitative=True)
    verdict["limitations"] = _texts(verdict["limitations"], "verdict.limitations", nonempty=True)
    if verdict["outcome"] == "inconclusive" and adverse:
        raise ContractError("inconclusive must not establish adverse findings; use not_established")
    if summary["outcome"] == "unknown" and verdict["outcome"] != "inconclusive":
        raise ContractError("an unknown fight outcome requires an inconclusive verdict")
    if verdict["outcome"] == "shared":
        if any(finding["level"] == "primary" for finding in adverse):
            raise ContractError("shared verdict must not single out a primary finding")
        if len({finding["pov_id"] for finding in adverse}) < 2:
            raise ContractError("shared verdict requires adverse findings for at least two players")
    if verdict["outcome"] == "supported" and not any(
        finding["level"] in ("primary", "secondary") for finding in adverse
    ):
        raise ContractError("supported verdict requires a primary or secondary finding")

    clips = _list(result["top_evidence_clips"], "top_evidence_clips")
    if len(clips) > 3:
        raise ContractError("top_evidence_clips allows at most three references")
    result["top_evidence_clips"] = _refs(
        clips, "top_evidence_clips", manifest, allowed_refs, empty=not adverse,
    )
    if not set(result["top_evidence_clips"]).issubset(used_refs):
        raise ContractError("top_evidence_clips must cite evidence used in the summary, facts or findings")
    primary_refs = {ref for finding in adverse if finding["level"] == "primary" for ref in finding["evidence_refs"]}
    if primary_refs and not primary_refs.intersection(result["top_evidence_clips"]):
        raise ContractError("top_evidence_clips must include evidence for a primary finding")

    for index, lesson in enumerate(_list(result["actionable_lessons"], "actionable_lessons")):
        path = f"actionable_lessons[{index}]"
        _object(lesson, ("pov_ids", "lesson", "evidence_refs"), path)
        pov_ids = _list(lesson["pov_ids"], path + ".pov_ids", nonempty=True)
        for pov_id in pov_ids:
            _enum(pov_id, tuple(supplied_povs(manifest)), path + ".pov_ids")
        if len(set(pov_ids)) != len(pov_ids):
            raise ContractError(f"{path}.pov_ids contains duplicates")
        lesson["lesson"] = _text(lesson["lesson"], path + ".lesson", qualitative=True)
        lesson["evidence_refs"] = _refs(lesson["evidence_refs"], path + ".evidence_refs", manifest, allowed_refs)
    if adverse and not result["actionable_lessons"]:
        raise ContractError("established adverse findings require at least one actionable lesson")

    confidence = _object(result["confidence"], ("label", "rationale"), "confidence")
    _enum(confidence["label"], ("low", "medium", "high"), "confidence.label")
    confidence["rationale"] = _text(confidence["rationale"], "confidence.rationale", qualitative=True)
    _validate_prose_references(result, manifest, allowed_refs)
    return result


def _inline(value: Any) -> str:
    return " ".join(str(value).split())


def _citations(refs: list[str]) -> str:
    return ", ".join(f"`{ref}`" for ref in refs) or "None established."


def render_report(payload: dict, metadata: dict) -> str:
    """Render a validated response, preserving all reasons and uncertainties."""
    summary = payload["fight_summary"]
    verdict = payload["verdict"]
    lines = [
        "# Tactical Verdict — Stage C", "", "## Metadata", "",
        f"- Run: {_inline(metadata.get('run_id', 'unknown'))}",
        f"- Fight: {_inline(metadata.get('fight_id', 'unknown'))}",
        f"- Prompt version: {_inline(metadata.get('prompt_version', PROMPT_VERSION))}",
        f"- Prompt SHA-256: {_inline(metadata.get('prompt_sha256', 'not recorded'))}",
        "- Timeline: original pre-aligned video seconds; no offsets applied.",
        "- Validation: structure and citation provenance checked; tactical claims await Stage D footage review.",
        "", "## Fight Summary", "",
        f"- Observed outcome: {summary['outcome']}",
        _inline(summary["summary"]),
        f"- Evidence: {_citations(summary['evidence_refs'])}",
        "", "## Confirmed Facts", "",
    ]
    if payload["confirmed_facts"]:
        for fact in payload["confirmed_facts"]:
            lines.append(f"- **{_inline(fact['id'])}**: {_inline(fact['claim'])} Evidence: {_citations(fact['evidence_refs'])}")
    else:
        lines.append("No confirmed facts established in this response.")
    lines.extend(("", "## Candidate Mistakes", ""))
    if payload["findings"]:
        for finding in payload["findings"]:
            lines.extend((
                f"### {_inline(finding['id'])} — {finding['pov_id']} ({finding['level']})", "",
                _inline(finding["claim"]),
                f"- Evidence: {_citations(finding['evidence_refs'])}",
                f"- Information available to the player: {_inline(finding['player_information'])}",
                f"- Realistic alternative: {_inline(finding['alternative_action'])}",
                f"- Plausible consequence (hypothesis): {_inline(finding['plausible_consequence'])}", "",
            ))
    else:
        lines.append("No supported candidate mistake is established.")
    lines.extend(("", "## Causal Analysis", "", "Causal contributions below are hypotheses, not automatic causal proof.", ""))
    for finding in payload["findings"]:
        lines.append(f"- **{_inline(finding['id'])}** ({finding['level']}): {_inline(finding['causal_reasoning'])} Evidence: {_citations(finding['evidence_refs'])}")
    if not payload["findings"]:
        lines.append("The available findings do not establish a causal contributor.")
    lines.extend(("", "## Alternative Explanations", ""))
    lines.extend(f"- {_inline(explanation)}" for explanation in payload["alternative_explanations"])
    for finding in payload["findings"]:
        lines.append(f"- **{_inline(finding['id'])}**: {_inline(finding['alternative_explanation'])}")
    lines.extend(("", "## Player-by-Player Findings", ""))
    for pov_id in payload["player_findings"]:
        player = payload["player_findings"][pov_id]
        lines.append(f"- **{pov_id}** — {player['status']}: {_inline(player['summary'])}")
        if player["finding_ids"]:
            lines.append("  - Findings: " + ", ".join(_inline(item) for item in player["finding_ids"]))
    lines.extend(("", "## Verdict or Inconclusive", "", f"**{verdict['outcome']}**", "", _inline(verdict["summary"])))
    lines.extend(("", "## Top 3 Evidence Clips", ""))
    if payload["top_evidence_clips"]:
        lines.extend(f"{index}. `{ref}`" for index, ref in enumerate(payload["top_evidence_clips"], 1))
    else:
        lines.append("No reviewable evidence clip has been selected; no clip is fabricated.")
    lines.extend(("", "## Actionable Lessons", ""))
    if payload["actionable_lessons"]:
        for lesson in payload["actionable_lessons"]:
            lines.append(f"- **{', '.join(lesson['pov_ids'])}**: {_inline(lesson['lesson'])} Evidence: {_citations(lesson['evidence_refs'])}")
    else:
        lines.append("No evidence-supported tactical lesson is established; obtain the missing evidence first.")
    confidence = payload["confidence"]
    lines.extend((
        "", "## Confidence and Limitations", "",
        f"- Qualitative confidence: {confidence['label']} (not a calibrated probability).",
        f"- Basis: {_inline(confidence['rationale'])}",
    ))
    lines.extend(f"- {_inline(limitation)}" for limitation in verdict["limitations"])
    lines.extend((
        "", "## Agent Handoff", "", "- Stage: C",
        f"- Status: {_inline(metadata.get('status', 'PASS'))}",
        "- Inputs consumed: Stage B fusion, original cited Stage A observations, manifest coverage and shared timeline.",
        "- Outputs produced: verdict.json; verdict.md.",
        f"- Prompt/model/tool versions: {_inline(metadata.get('prompt_version', PROMPT_VERSION))}; {_inline(metadata.get('executor', 'manual Codex response'))}.",
        "- Evidence coverage: " + (", ".join(sorted({ref for finding in payload["findings"] for ref in finding["evidence_refs"]})) or "No adverse finding established."),
        "- Unresolved questions: " + "; ".join(_inline(item) for item in verdict["limitations"]),
        "- Known limitations: Structural validation cannot verify footage, actor identity, player knowledge, or causal truth.",
        "- Recommended next action: Independently inspect the cited original video windows in Stage D before publishing.", "",
    ))
    return "\n".join(lines)


def example_response(pov_ids=POV_IDS) -> dict:
    """A complete abstention template, containing no invented gameplay evidence."""
    return {
        "schema_version": SCHEMA_VERSION,
        "fight_summary": {
            "outcome": "unknown",
            "summary": "Example only: the supplied evidence has not established the fight outcome.",
            "evidence_refs": [],
        },
        "confirmed_facts": [],
        "findings": [],
        "player_findings": {
            pov_id: {
                "status": "no_supported_mistake",
                "summary": "Example only: no supported mistake is established for this player.",
                "finding_ids": [],
            }
            for pov_id in pov_ids
        },
        "alternative_explanations": ["Missing or conflicting evidence could prevent reliable attribution."],
        "verdict": {
            "outcome": "inconclusive",
            "summary": "Example only: replace this template with an evidence-grounded response, or explicitly abstain.",
            "limitations": ["This is a response template, not an analysis of an actual fight."],
        },
        "top_evidence_clips": [],
        "actionable_lessons": [],
        "confidence": {"label": "low", "rationale": "No gameplay evidence is asserted by this template."},
    }


def response_schema(pov_ids=POV_IDS) -> dict:
    """JSON Schema for task-package authoring; validate_result adds cross-field gates."""
    text = {"type": "string", "minLength": 1}
    ref = {"type": "string", "description": "Exact canonical citation from the task's allowed_refs; no offsets or new intervals."}

    def array(items: dict, minimum: int = 0, **extra: Any) -> dict:
        return {"type": "array", "items": items, "minItems": minimum, **extra}

    def obj(properties: dict) -> dict:
        return {"type": "object", "properties": properties, "required": list(properties), "additionalProperties": False}

    def enum(choices: tuple[str, ...]) -> dict:
        return {"type": "string", "enum": list(choices)}

    references = array(ref, 1, uniqueItems=True)
    schema = obj({
        "schema_version": {"const": SCHEMA_VERSION},
        "fight_summary": obj({
            "outcome": enum(("loss", "win", "draw", "unknown")), "summary": text,
            "evidence_refs": array(ref, uniqueItems=True),
        }),
        "confirmed_facts": array(obj({"id": text, "claim": text, "evidence_refs": references})),
        "findings": array(obj({
            "id": text, "pov_id": enum(tuple(pov_ids)), "level": enum(FINDING_LEVELS),
            "claim": text, "evidence_refs": references, "player_information": text,
            "alternative_action": text, "plausible_consequence": text,
            "causal_reasoning": text, "alternative_explanation": text,
        })),
        "player_findings": obj({
            pov_id: obj({
                "status": enum(("findings", "no_supported_mistake")), "summary": text,
                "finding_ids": array(text, uniqueItems=True),
            })
            for pov_id in pov_ids
        }),
        "alternative_explanations": array(text, 1),
        "verdict": obj({
            "outcome": enum(("inconclusive", "shared", "supported")),
            "summary": text, "limitations": array(text, 1),
        }),
        "top_evidence_clips": array(ref, maxItems=3, uniqueItems=True),
        "actionable_lessons": array(obj({
            "pov_ids": array(enum(tuple(pov_ids)), 1, uniqueItems=True),
            "lesson": text, "evidence_refs": references,
        })),
        "confidence": obj({"label": enum(("low", "medium", "high")), "rationale": text}),
    })
    schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
    schema["title"] = "OverJudge Stage C manual response"
    schema["description"] = (
        "Qualitative evidence-grounded judgment. Every finding is linked to its player. "
        "An unknown fight outcome requires an inconclusive verdict. "
        "Inconclusive establishes no adverse findings; shared requires at least two players and no primary. "
        "Confidence labels are not calibrated probabilities. Program validation also enforces citation and verdict consistency."
    )
    return schema
