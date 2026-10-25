"""Stage D evidence extraction and explicit, reviewable manual audit gates.

An imported review is an attestation by its named reviewer. Hash/shape checks
establish provenance; they do not establish that a model or person watched it.
"""

from __future__ import annotations

import copy
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
import tempfile

from .contracts import (
    ContractError, EvidenceRef, POV_IDS, extract_evidence_refs,
    sha256_file, validate_references,
)


ADVERSE_LEVELS = {"primary", "secondary", "shared"}
SCHEMA_VERSION = "1.0"
PROMPT_VERSION = "stage-d-v1"
QA_STATUSES = {"PASS", "PASS_WITH_LIMITATIONS", "FAIL"}
CHECK_STATUSES = {"supported", "qualified", "unsupported", "unverified"}
CHECK_FLAGS = (
    "identity_verified", "timestamp_verified", "ability_verified",
    "hindsight_checked", "source_consistency_checked",
)


def _text(value, name):
    if not isinstance(value, str) or not value.strip():
        raise ContractError(f"{name} must be a non-empty string")
    return value.strip()


def _list(value, name):
    if not isinstance(value, list):
        raise ContractError(f"{name} must be a list")
    return value


def _object(value, name):
    if not isinstance(value, dict):
        raise ContractError(f"{name} must be an object")
    return value


def _run(argv):
    try:
        result = subprocess.run(argv, check=False, capture_output=True, text=True, timeout=300)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ContractError(f"Evidence tool failed ({argv[0]}): {exc}") from exc
    if result.returncode:
        detail = (result.stderr or result.stdout or "no diagnostic")[-2000:]
        raise ContractError(f"Evidence tool failed ({argv[0]}): {detail}")
    return result.stdout


def _probe(path, ffprobe="ffprobe"):
    try:
        data = json.loads(_run([
            ffprobe, "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path),
        ]))
        video = next(stream for stream in data["streams"] if stream.get("codec_type") == "video")
        duration = float(data.get("format", {}).get("duration") or video.get("duration"))
    except (ValueError, TypeError, KeyError, StopIteration) as exc:
        raise ContractError(f"No readable video stream/duration in {path}") from exc
    if not math.isfinite(duration) or duration <= 0:
        raise ContractError(f"Invalid video duration in {path}")
    return duration


def _adverse_findings(verdict):
    findings = _list(_object(verdict, "verdict result").get("findings"), "findings")
    for finding in findings:
        _object(finding, "finding")
        _text(finding.get("id"), "finding.id")
    return [finding for finding in findings if finding.get("level") in ADVERSE_LEVELS]


def required_evidence_refs(verdict, manifest=None):
    """Evidence that must be reopened, including abstention's cited basis."""
    refs = set()
    for finding in _adverse_findings(verdict):
        refs.update(validate_references(finding.get("evidence_refs"), manifest))
    # The conclusion's factual basis is reviewed even when no adverse finding
    # exists. Include all cited facts/summary rather than inventing a clip or
    # treating abstention as an exemption from evidence review.
    def walk(value):
        if isinstance(value, dict):
            for key, child in value.items():
                if key == "evidence_refs" and isinstance(child, list) and child:
                    refs.update(validate_references(child, manifest))
                else:
                    walk(child)
        elif isinstance(value, list):
            for child in value:
                walk(child)
        elif isinstance(value, str):
            refs.update(str(ref) for ref in extract_evidence_refs(value, manifest))
    walk(verdict)
    return sorted(refs)


def extract_evidence_clips(manifest, verdict, output_dir, project_root, ffmpeg="ffmpeg"):
    """Extract precise original-video windows without modifying source files.

    ``path`` in the returned index is absolute, so reviewers can open it from
    any working directory. Timestamps always describe the original aligned
    videos; each generated clip begins locally at zero.
    """
    output_dir = Path(output_dir).resolve()
    project_root = Path(project_root).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    videos = {video["pov_id"]: video for video in manifest["videos"]}
    refs = required_evidence_refs(verdict, manifest)
    if not refs:
        raise ContractError("Stage D needs cited original-video evidence, including for inconclusive verdicts")
    # A custom ffmpeg binary may have a companion ffprobe in the same directory.
    executable = Path(ffmpeg)
    companion = executable.with_name("ffprobe")
    ffprobe = str(companion) if executable.parent != Path(".") and companion.is_file() else "ffprobe"
    versions = {
        "ffmpeg": _run([str(ffmpeg), "-version"]).splitlines()[0],
        "ffprobe": _run([ffprobe, "-version"]).splitlines()[0],
    }
    sources = {}
    for ref_text in refs:
        ref = EvidenceRef.parse(ref_text, manifest)
        if ref.pov_id in sources:
            continue
        video = videos[ref.pov_id]
        source = Path(video["path"])
        if not source.is_absolute():
            source = project_root / source
        source = source.resolve()
        if not source.is_file():
            raise ContractError(f"Missing original video: {source}")
        expected_hash = _text(video.get("sha256"), f"{ref.pov_id}.sha256").lower()
        actual_hash = sha256_file(source)
        if actual_hash != expected_hash:
            raise ContractError(f"Original video hash mismatch: {ref.pov_id}")
        duration = _probe(source, ffprobe)
        sources[ref.pov_id] = (source, actual_hash, duration)

    index = []
    for ref_text in refs:
        ref = EvidenceRef.parse(ref_text, manifest)
        source, source_hash, source_duration = sources[ref.pov_id]
        if ref.end_timestamp > source_duration + 0.001:
            raise ContractError(f"Evidence exceeds actual original-video duration: {ref_text}")
        duration = ref.end_timestamp - ref.start_timestamp
        token = hashlib.sha256(f"{source_hash}:{ref_text}".encode()).hexdigest()[:20]
        target = output_dir / f"{ref.pov_id}_{token}.mp4"
        handle, temporary = tempfile.mkstemp(prefix=".extract-", suffix=".mp4", dir=output_dir)
        os.close(handle)
        temporary = Path(temporary)
        try:
            # Output-side -ss decodes to the requested timestamp instead of
            # copying the preceding keyframe. Original files are always inputs.
            _run([
                str(ffmpeg), "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
                "-i", str(source), "-ss", str(ref.start_timestamp), "-t", str(duration),
                "-map", "0:v:0", "-map", "0:a?", "-c:v", "libx264", "-preset", "veryfast",
                "-crf", "18", "-c:a", "aac", "-map_metadata", "-1", "-movflags", "+faststart",
                str(temporary),
            ])
            extracted_duration = _probe(temporary, ffprobe)
            fps = float(videos[ref.pov_id].get("fps") or 30)
            tolerance = max(0.1, 2 / fps)
            if abs(extracted_duration - duration) > tolerance:
                raise ContractError(f"Extracted clip duration differs from requested interval: {ref_text}")
            _run([str(ffmpeg), "-v", "error", "-nostdin", "-i", str(temporary), "-f", "null", "-"])
            if sha256_file(source) != source_hash:
                raise ContractError(f"Original video changed during extraction: {ref.pov_id}")
            clip_hash = sha256_file(temporary)
            if target.exists():
                if not target.is_file() or sha256_file(target) != clip_hash:
                    raise ContractError(f"Existing evidence clip differs; use a fresh output revision: {target}")
            else:
                temporary.replace(target)
            index.append({
                "evidence_ref": ref_text, "path": str(target), "sha256": clip_hash,
                "source_sha256": source_hash, "source_path": str(source),
                "start_timestamp": ref.start_timestamp, "end_timestamp": ref.end_timestamp,
                "duration_seconds": extracted_duration,
                "extraction_method": "ffmpeg output-side seek; H.264/AAC; full decode verified",
                "tool_versions": versions.copy(),
                "model": "none; deterministic local video extraction",
            })
        finally:
            temporary.unlink(missing_ok=True)
    return index


def _validated_clip_index(clip_index, manifest, allowed_refs):
    clips = {}
    videos = {video["pov_id"]: video for video in manifest["videos"]}
    for item in _list(clip_index, "clip_index"):
        _object(item, "clip_index item")
        ref = validate_references([item.get("evidence_ref")], manifest, allowed_refs)[0]
        if ref in clips:
            raise ContractError(f"Duplicate evidence clip: {ref}")
        parsed = EvidenceRef.parse(ref, manifest)
        if item.get("source_sha256") != videos[parsed.pov_id]["sha256"].lower():
            raise ContractError(f"Evidence clip source hash differs from manifest: {ref}")
        path = Path(_text(item.get("path"), "clip.path"))
        if not path.is_file() or sha256_file(path) != item.get("sha256"):
            raise ContractError(f"Evidence clip missing or changed: {ref}")
        source_path = Path(_text(item.get("source_path"), "clip.source_path"))
        if not source_path.is_file() or sha256_file(source_path) != item["source_sha256"]:
            raise ContractError(f"Original evidence missing or changed since extraction: {ref}")
        if item.get("start_timestamp") != parsed.start_timestamp or item.get("end_timestamp") != parsed.end_timestamp:
            raise ContractError(f"Evidence clip interval differs from citation: {ref}")
        clips[ref] = item
    return clips


def validate_result(payload, manifest, allowed_refs, verdict, clip_index):
    """Validate a review and compute a fail-closed publication status.

    Malformed submissions raise ContractError. A well-formed but unsuccessful
    review returns qa_status=FAIL, allowing its issue log to be preserved.
    """
    result = copy.deepcopy(_object(payload, "audit result"))
    # Narrative strings are not a loophole around the source allowlist. This
    # also rejects malformed citation-looking tokens instead of dropping them.
    def check_inline_references(value):
        if isinstance(value, str):
            refs = extract_evidence_refs(value, manifest)
            if refs:
                validate_references([str(ref) for ref in refs], manifest, allowed_refs)
        elif isinstance(value, dict):
            for child in value.values():
                check_inline_references(child)
        elif isinstance(value, list):
            for child in value:
                check_inline_references(child)
    check_inline_references(result)
    claimed_status = result.get("qa_status")
    if claimed_status not in QA_STATUSES:
        raise ContractError("qa_status must be PASS, PASS_WITH_LIMITATIONS, or FAIL")
    reviewer = _object(result.get("reviewer"), "reviewer")
    for key in ("name", "tool", "method"):
        reviewer[key] = _text(reviewer.get(key), f"reviewer.{key}")
    limitations = [_text(item, "limitation") for item in _list(result.get("limitations"), "limitations")]
    result["limitations"] = limitations
    issues = _list(result.get("issues"), "issues")
    for issue in issues:
        _object(issue, "issue")
        if issue.get("severity") not in {"critical", "major", "minor"}:
            raise ContractError("Issue severity must be critical, major, or minor")
        for key in ("claim", "source", "finding", "required_fix", "owner"):
            issue[key] = _text(issue.get(key), f"issue.{key}")
    clips = _validated_clip_index(clip_index, manifest, allowed_refs)
    inspected = {}
    for item in _list(result.get("inspected_evidence"), "inspected_evidence"):
        _object(item, "inspected_evidence item")
        ref = validate_references([item.get("evidence_ref")], manifest, allowed_refs)[0]
        if ref in inspected:
            raise ContractError(f"Duplicate inspection attestation: {ref}")
        if type(item.get("inspected")) is not bool:
            raise ContractError("inspected must be a boolean")
        item["notes"] = _text(item.get("notes"), "inspection.notes")
        item["evidence_ref"] = ref
        if ref not in clips:
            raise ContractError(f"No extracted clip for inspection attestation: {ref}")
        if item.get("clip_sha256") != clips[ref]["sha256"] or item.get("source_sha256") != clips[ref]["source_sha256"]:
            raise ContractError(f"Inspection attestation hashes do not match evidence clip: {ref}")
        inspected[ref] = item

    finding_ids = {finding["id"] for finding in verdict["findings"]}
    checks = {}
    for check in _list(result.get("finding_checks"), "finding_checks"):
        _object(check, "finding check")
        finding_id = _text(check.get("finding_id"), "finding_id")
        if finding_id not in finding_ids or finding_id in checks:
            raise ContractError(f"Unknown or duplicate finding check: {finding_id}")
        if check.get("status") not in CHECK_STATUSES:
            raise ContractError("Finding check status must be supported, qualified, unsupported, or unverified")
        for flag in CHECK_FLAGS:
            if type(check.get(flag)) is not bool:
                raise ContractError(f"{flag} must be a boolean")
        check["notes"] = _text(check.get("notes"), "finding check notes")
        checks[finding_id] = check

    conclusion = _object(result.get("conclusion_review"), "conclusion_review")
    if type(conclusion.get("inspected")) is not bool:
        raise ContractError("conclusion_review.inspected must be a boolean")
    conclusion["notes"] = _text(conclusion.get("notes"), "conclusion_review.notes")
    conclusion["evidence_refs"] = validate_references(conclusion.get("evidence_refs"), manifest, allowed_refs)
    failures = []
    if not conclusion["inspected"]:
        failures.append("Verdict conclusion has not been reviewed against original-video evidence")
    for ref in conclusion["evidence_refs"]:
        if ref not in inspected or not inspected[ref]["inspected"]:
            failures.append(f"Conclusion evidence has not been inspected: {ref}")
    for ref in required_evidence_refs(verdict, manifest):
        if ref not in inspected or not inspected[ref]["inspected"]:
            failures.append(f"Cited verdict evidence has not been inspected: {ref}")
    adverse = _adverse_findings(verdict)
    qualified = False
    for finding in adverse:
        finding_id = finding["id"]
        refs = validate_references(finding.get("evidence_refs"), manifest, allowed_refs)
        for ref in refs:
            if ref not in inspected or not inspected[ref]["inspected"]:
                failures.append(f"Adverse finding evidence has not been inspected: {finding_id} / {ref}")
        check = checks.get(finding_id)
        if check is None:
            failures.append(f"Missing adverse finding check: {finding_id}")
            continue
        if check["status"] in {"unsupported", "unverified"}:
            failures.append(f"Adverse finding is {check['status']}: {finding_id}")
        if not all(check[flag] for flag in CHECK_FLAGS):
            failures.append(f"Identity/timestamp/ability/hindsight/source checks incomplete: {finding_id}")
        if check["status"] == "qualified":
            qualified = True
            limitations.append(f"Finding {finding_id} is qualified: {check['notes']}")
    if any(issue["severity"] in {"critical", "major"} for issue in issues):
        failures.append("Unresolved critical or major audit issues require an upstream revision")
    if claimed_status == "PASS_WITH_LIMITATIONS" and not limitations and not issues:
        raise ContractError("PASS_WITH_LIMITATIONS requires recorded limitations or issues")
    if failures or claimed_status == "FAIL":
        result["qa_status"] = "FAIL"
    elif limitations or issues or qualified:
        result["qa_status"] = "PASS_WITH_LIMITATIONS"
    else:
        result["qa_status"] = "PASS"
    result["requested_qa_status"] = claimed_status
    result["publication_allowed"] = result["qa_status"] != "FAIL"
    result["gate_failures"] = list(dict.fromkeys(failures))
    result["reviewed_adverse_findings"] = len(adverse)
    result["evidence_coverage"] = {
        "required": len(required_evidence_refs(verdict, manifest)),
        "inspected": sum(1 for ref in required_evidence_refs(verdict, manifest) if ref in inspected and inspected[ref]["inspected"]),
    }
    return result


def _metadata_lines(metadata, status):
    lines = [
        f"- Run: {metadata.get('run_id', 'unknown')}",
        f"- Fight: {metadata.get('fight_id', 'unknown')}",
        f"- prompt_version: {metadata.get('prompt_version', 'unknown')}",
        f"- Prompt SHA-256: {metadata.get('prompt_sha256', 'unknown')}",
        f"- Status: {status}",
    ]
    if metadata.get("execution"):
        lines.append("- Actual execution: " + json.dumps(metadata["execution"], ensure_ascii=False, sort_keys=True))
    if metadata.get("input_hashes"):
        lines.append("- Input SHA-256: " + json.dumps(metadata["input_hashes"], ensure_ascii=False, sort_keys=True))
    return lines


def _upstream_limitations(metadata):
    value = metadata.get("upstream_limitations", [])
    if isinstance(value, str):
        return [value] if value.strip() else []
    if isinstance(value, list):
        return [str(item) for item in value if str(item).strip()]
    return [json.dumps(value, ensure_ascii=False, sort_keys=True)] if value else []


def render_qa_report(payload, metadata):
    lines = ["# Evidence Audit — Stage D", "", "## Metadata", *_metadata_lines(metadata, payload["qa_status"]), "", "## Review Method"]
    lines.extend(f"- {key}: {value}" for key, value in payload["reviewer"].items())
    lines.extend(["", "Manual inspection statements below are reviewer attestations; file validation alone does not verify their truth.", "", "## Finding Checks"])
    for item in payload["finding_checks"]:
        flags = ", ".join(f"{flag}={item[flag]}" for flag in CHECK_FLAGS)
        lines.append(f"- {item['finding_id']}: **{item['status']}**; {flags}. {item['notes']}")
    if not payload["finding_checks"]:
        lines.append("No adverse findings; the inconclusive conclusion still requires the evidence review below.")
    lines.extend(["", "## Inspected Evidence"])
    for item in payload["inspected_evidence"]:
        lines.append(f"- {item['evidence_ref']}: inspected={item['inspected']}; clip SHA-256 `{item['clip_sha256']}`; source SHA-256 `{item['source_sha256']}`. {item['notes']}")
    lines.extend(["", "## Conclusion Review", payload["conclusion_review"]["notes"], "", "Evidence: " + ", ".join(payload["conclusion_review"]["evidence_refs"]), "", "## Issue Log"])
    if not payload["issues"]:
        lines.append("No issues reported by the reviewer.")
    for issue in payload["issues"]:
        lines.extend([f"### {issue['severity'].upper()}: {issue['claim']}", *[f"- {key}: {issue[key]}" for key in ("source", "finding", "required_fix", "owner")], ""])
    lines.extend(["", "## Publication Gate", f"**{payload['qa_status']}**"])
    lines.extend(f"- {failure}" for failure in payload.get("gate_failures", []))
    lines.extend(["", "## Limitations", *[f"- {item}" for item in payload["limitations"]]])
    upstream_limitations = _upstream_limitations(metadata)
    if upstream_limitations:
        lines.extend(["", "## Source Coverage, Conflicts, and Limitations", *[f"- {item}" for item in upstream_limitations]])
    lines.extend(["", "## Agent Handoff", "- Stage: D", f"- Status: {payload['qa_status']}", "- Inputs consumed: manifest, original videos, POV reports, fusion, verdict, evidence clip index", "- Outputs produced: qa_report.md; final_report.md only if publication gate passes", f"- Prompt/model/tool versions: {metadata.get('prompt_version', 'unknown')}; {payload['reviewer']['tool']}", f"- Evidence coverage: {payload.get('evidence_coverage', {})}", "- Unresolved questions: see Issue Log and Limitations", "- Known limitations: manual review attestations are not independently machine-verifiable", "- Recommended next action: " + ("publish supported report" if payload.get("publication_allowed") else "revise owning stage and rerun dependent stages"), ""])
    return "\n".join(lines)


def render_final_report(verdict, qa_result, metadata, clip_index):
    if qa_result.get("qa_status") not in {"PASS", "PASS_WITH_LIMITATIONS"} or qa_result.get("publication_allowed") is not True:
        raise ContractError("Stage D FAIL blocks final report publication")
    conclusion = verdict["verdict"]
    lines = ["# Teamfight Review", "", "## Metadata", *_metadata_lines(metadata, qa_result["qa_status"]), "", "## Verdict", f"**{conclusion['outcome']}**", "", conclusion["summary"]]
    summary = verdict.get("fight_summary")
    if isinstance(summary, dict):
        lines.extend(["", "## Fight Summary", summary.get("summary", "unknown"), "Evidence: " + ", ".join(summary.get("evidence_refs", []))])
    facts = verdict.get("confirmed_facts", [])
    if facts:
        lines.extend(["", "## Confirmed Facts"])
        lines.extend(f"- {item['claim']} Evidence: {', '.join(item['evidence_refs'])}" for item in facts)
    lines.extend(["", "## Player-by-Player Findings"])
    for pov_id in verdict["player_findings"]:
        item = verdict["player_findings"][pov_id]
        lines.append(f"### {pov_id}")
        if isinstance(item, dict):
            lines.extend(f"- {key}: {value}" for key, value in item.items())
        else:
            lines.append(str(item))
        lines.append("")
    lines.extend(["## Supported Findings", ""])
    for item in verdict["findings"]:
        if item.get("level") not in ADVERSE_LEVELS:
            continue
        lines.extend([f"### {item['id']} — {item['pov_id']} ({item['level']})", item["claim"], f"- Evidence: {', '.join(item['evidence_refs'])}", f"- Information available to player: {item['player_information']}", f"- Alternative action: {item['alternative_action']}", f"- Plausible causal contribution: {item['causal_reasoning']}", f"- Alternative explanation: {item['alternative_explanation']}", ""])
    if not _adverse_findings(verdict):
        lines.append("No supported individual adverse finding is established.")
    unestablished = [item for item in verdict["findings"] if item.get("level") == "not_established"]
    if unestablished:
        lines.extend(["", "## Unestablished Candidates", "These are unresolved hypotheses, not adverse findings."])
        for item in unestablished:
            lines.append(f"- {item['pov_id']}: {item['claim']} Not established. Alternative explanation: {item['alternative_explanation']}. Evidence: {', '.join(item['evidence_refs'])}")
    alternatives = verdict.get("alternative_explanations", [])
    if alternatives:
        lines.extend(["", "## Alternative Explanations", *[f"- {item}" for item in alternatives]])
    lessons = verdict.get("actionable_lessons", [])
    if lessons:
        lines.extend(["", "## Actionable Lessons"])
        lines.extend(f"- {', '.join(item['pov_ids'])}: {item['lesson']} Evidence: {', '.join(item['evidence_refs'])}" for item in lessons)
    lines.extend(["", "## Evidence Clips"])
    for item in clip_index:
        path = str(item["path"]).replace(" ", "%20")
        lines.append(f"- [{item['evidence_ref']}]({path}) — original aligned-video seconds; clip local zero corresponds to {item.get('start_timestamp', 'the interval start')} s.")
    lines.extend(["", "## Confidence and Limitations", "Evidence-grounded causal hypotheses are not causal proof. Self-reported confidence is not a calibrated probability."])
    confidence = verdict.get("confidence")
    if isinstance(confidence, dict):
        lines.append(f"- Qualitative confidence: {confidence.get('label', 'unknown')}. {confidence.get('rationale', '')}")
    limitations = list(conclusion.get("limitations", [])) + list(qa_result.get("limitations", []))
    limitations.extend(_upstream_limitations(metadata))
    # Preserve source-level limitations even if they are outside verdict{}.
    for key in ("limitations", "confidence_and_limitations"):
        value = verdict.get(key)
        if isinstance(value, list):
            limitations.extend(str(item) for item in value)
        elif isinstance(value, str) and value.strip():
            limitations.append(value)
    lines.extend(f"- {item}" for item in dict.fromkeys(limitations))
    for issue in qa_result["issues"]:
        lines.append(f"- Remaining {issue['severity']} issue: {issue['finding']} Required fix: {issue['required_fix']}")
    lines.extend(["", "## Audit", f"QA status: **{qa_result['qa_status']}**. Reviewer: {qa_result['reviewer']['name']}. Tool: {qa_result['reviewer']['tool']}.", "See qa_report.md for review method, evidence hashes, and the full issue log.", ""])
    return "\n".join(lines)


def example_response():
    """Shape example only. False attestations deliberately cannot publish."""
    return {
        "qa_status": "FAIL",
        "reviewer": {"name": "REPLACE_WITH_REVIEWER", "tool": "REPLACE_WITH_ACTUAL_TOOL_VERSION", "method": "Describe actual clips, frames, HUD and audio inspected"},
        "inspected_evidence": [{"evidence_ref": "tank@12.0-13.4", "clip_sha256": "COPY_FROM_CLIP_INDEX", "source_sha256": "COPY_FROM_CLIP_INDEX", "inspected": False, "notes": "Replace only after actual inspection"}],
        "finding_checks": [{"finding_id": "finding_1", "status": "unverified", **{flag: False for flag in CHECK_FLAGS}, "notes": "Actual identity, timing, abilities, player knowledge, and source consistency checks"}],
        "conclusion_review": {"inspected": False, "evidence_refs": ["tank@12.0-13.4"], "notes": "Review the full conclusion, including an inconclusive verdict, against footage"},
        "issues": [], "limitations": ["Example response only; no footage has been inspected"],
    }


def response_schema():
    return {
        "qa_status": "PASS | PASS_WITH_LIMITATIONS | FAIL; computed gate can downgrade",
        "reviewer": {"name": "nonempty actual identity", "tool": "actual tool/model and version", "method": "actual visual/audio review method and coverage"},
        "inspected_evidence": "list of {evidence_ref, clip_sha256, source_sha256, inspected: boolean, notes}; exact extracted-clip hashes",
        "finding_checks": {"finding_id": "existing finding ID; one per adverse finding", "status": "supported | qualified | unsupported | unverified", **{flag: "boolean; false blocks adverse-finding publication" for flag in CHECK_FLAGS}, "notes": "specific source-based check and limitations"},
        "conclusion_review": {"inspected": "boolean", "evidence_refs": "nonempty allowed references actually inspected", "notes": "audit of conclusion and source-report consistency"},
        "issues": "list of {severity: critical|major|minor, claim, source, finding, required_fix, owner}; all open critical/major issues block publication",
        "limitations": "list of nonempty strings; retained in final report",
    }
