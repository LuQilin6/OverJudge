"""Explicitly synthetic handoffs used only by software tests."""

from pathlib import Path
import json
import shutil
import subprocess

from src import audit, fusion, judge
from src.contracts import POV_IDS, sha256_file
from src.pipeline import DownstreamPipeline


REPOSITORY = Path(__file__).resolve().parents[1]
REF = "tank@1.0-2.0"


def write_json(path, value):
    Path(path).write_text(json.dumps(value, indent=2), encoding="utf-8")


def source_report(pov):
    return f"""# POV Report — {pov}
## Metadata
- Video: inputs/videos/{pov}.mp4
- Hero: unknown
- Aligned-video interval: 0.0–6.0
- prompt_version: synthetic-test-a-v1
- Inspection coverage / method: SYNTHETIC TEST ONLY; generated fixture, no gameplay inspected
## Gameplay Context
Synthetic test context; real game and hero identity are unknown.
## Timestamped Behavioral Timeline
### [1.0–2.0 s]
- Observed: Synthetic fixture represents an observation; no real gameplay claim.
- Immediate outcome: unknown
- Evidence: {pov}@1.0-2.0
- Evidence quality: low
- Inference/unknown: actual gameplay is not represented
## Player Information State
Only the synthetic assigned input is supplied.
## Cross-POV Verification Questions
No game-specific question can be answered from this synthetic fixture.
## Neutral Behavioral Summary
Synthetic test; no tactical conclusion.
## Coverage and Limitations
SYNTHETIC {pov}: no real gameplay has been analyzed.
## Agent Handoff
- Stage: A
- Status: PASS
- Inputs consumed: synthetic test fixture
- Outputs produced: this report
- Prompt/model/tool versions: synthetic-test-a-v1; no model call
- Evidence coverage: synthetic interval 1.0–2.0
- Unresolved questions: all game-specific interpretation
- Known limitations: software test only
- Recommended next action: test contracts only
"""


def create_project(root, *, real_video=False):
    root = Path(root)
    for directory in ("config", "prompts", "inputs/videos", "outputs/pov_reports"):
        (root / directory).mkdir(parents=True, exist_ok=True)
    for stage in "bcd":
        shutil.copyfile(REPOSITORY / f"prompts/stage_{stage}.md", root / f"prompts/stage_{stage}.md")
    seed = root / "seed.mp4"
    if real_video:
        subprocess.run([
            "ffmpeg", "-v", "error", "-nostdin", "-f", "lavfi", "-i",
            "color=c=blue:s=64x64:r=10:d=6", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(seed),
        ], check=True, capture_output=True)
    else:
        seed.write_bytes(b"SYNTHETIC ONLY; this is not a decodable video")
    videos = []
    for pov in POV_IDS:
        path = root / f"inputs/videos/{pov}.mp4"
        shutil.copyfile(seed, path)
        videos.append({
            "pov_id": pov, "path": f"inputs/videos/{pov}.mp4", "sha256": sha256_file(path),
            "duration_seconds": 6.0, "fps": 10.0, "width": 64, "height": 64,
            "audio_present": False, "hero": "unknown", "coverage_status": "complete", "missing_intervals": [],
        })
        (root / f"outputs/pov_reports/{pov}.md").write_text(source_report(pov), encoding="utf-8")
    manifest = {
        "run_id": "synthetic-test", "game": "Overwatch 2", "fight_id": "synthetic-fight",
        "prealigned_input_assumed": True, "fight_start_timestamp": 0.0, "fight_end_timestamp": 6.0,
        "videos": videos,
    }
    write_json(root / "config/manifest.json", manifest)
    config = {
        key: manifest[key] for key in ("run_id", "game", "fight_id", "prealigned_input_assumed", "fight_start_timestamp", "fight_end_timestamp")
    }
    config.update({"output_directory": "outputs", "prompts": {stage: f"prompts/stage_{stage.lower()}.md" for stage in "BCD"}})
    write_json(root / "config/run.json", config)
    return DownstreamPipeline("config/run.json", root)


def b_response():
    response = fusion.example_response()
    response["status"] = "PASS"
    response["limitations"] = []
    response["uncertainties"] = ["Synthetic fixture has no game-specific interpretation."]
    return response


def c_response(*, adverse=False, no_refs=False):
    response = judge.example_response()
    response["verdict"]["limitations"] = ["SYNTHETIC fixture; no actual gameplay claim."]
    if not no_refs:
        response["fight_summary"]["evidence_refs"] = [REF]
        response["confirmed_facts"] = [{"id": "fact_1", "claim": "Synthetic recording supplies a blue frame", "evidence_refs": [REF]}]
    if adverse:
        response["fight_summary"]["outcome"] = "loss"
        response["fight_summary"]["summary"] = "Synthetic assumed loss for testing software gates only."
        response["findings"] = [{
            "id": "finding_1", "pov_id": "tank", "level": "primary",
            "claim": "Synthetic candidate finding, not real player criticism",
            "evidence_refs": [REF], "player_information": "Only the synthetic view was available",
            "alternative_action": "Synthetic alternative", "plausible_consequence": "Synthetic possible effect",
            "causal_reasoning": "Synthetic uncertain causal hypothesis", "alternative_explanation": "Synthetic alternative cause",
        }]
        response["player_findings"]["tank"].update(status="findings", finding_ids=["finding_1"])
        response["verdict"].update(outcome="supported", summary="Synthetic hypothesis for testing only")
        response["top_evidence_clips"] = [REF]
        response["actionable_lessons"] = [{"pov_ids": ["tank"], "lesson": "Synthetic test lesson", "evidence_refs": [REF]}]
    return response


def d_response(clips, *, adverse=False, fail=False):
    return {
        "qa_status": "PASS", "reviewer": {"name": "Synthetic software test", "tool": "unittest; not an actual visual reviewer", "method": "Synthetic attestation exercises software gates only"},
        "inspected_evidence": [{
            "evidence_ref": clip["evidence_ref"], "clip_sha256": clip["sha256"], "source_sha256": clip["source_sha256"],
            "inspected": not fail, "notes": "Synthetic attestation, no gameplay inspected",
        } for clip in clips],
        "finding_checks": ([{"finding_id": "finding_1", "status": "supported", **{flag: True for flag in audit.CHECK_FLAGS}, "notes": "Synthetic check only"}] if adverse else []),
        "conclusion_review": {"inspected": not fail, "evidence_refs": [clip["evidence_ref"] for clip in clips], "notes": "Synthetic conclusion gate test"},
        "issues": [], "limitations": [],
    }


def import_response(pipeline, stage, request, payload, **kwargs):
    path = pipeline.root / f"response-{stage}.json"
    write_json(path, {"execution": {"tool": "unittest synthetic fixture", "model": "none", "operator": "automated software test only"}, "result": payload})
    return pipeline.import_result(stage, request, path, **kwargs)


def finish_bc(pipeline, *, adverse=False, no_refs=False):
    b = pipeline.prepare("B")
    import_response(pipeline, "B", b["request_path"], b_response())
    c = pipeline.prepare("C")
    return import_response(pipeline, "C", c["request_path"], c_response(adverse=adverse, no_refs=no_refs))
