"""Manual Stage A preparation and immutable report imports.

Preparing frames never establishes that they have been inspected. Imported
reports retain their reviewer record and remain PASS_WITH_LIMITATIONS with an
independent evidence audit PENDING until the downstream workflow reviews them.
"""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import subprocess
from typing import Any
from uuid import uuid4

from .artifacts import ArtifactStore, digest, file_lock, save_json
from .contracts import (
    ContractError, EvidenceRef, finite_number, read_json, validate_pov_report,
)
from .intake import POVS, RunConfig, load_config, validate_inputs
from .pov_analysis import validate_report
from .video_inspection import extract_frames


def _json_bytes(value: Any) -> bytes:
    try:
        return (json.dumps(value, sort_keys=True, indent=2, ensure_ascii=False,
                           allow_nan=False) + "\n").encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ContractError("Stage A artifacts must contain finite JSON values") from exc


def _digest_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _storage_path(path: Path, root: Path) -> Path:
    """Prevent a storage symlink from redirecting one run's immutable artifacts."""
    path = path.absolute()
    if not path.resolve().is_relative_to(root.resolve()) or path.resolve() != path:
        raise ContractError("Stage A artifact path escapes or redirects its run")
    return path


def _resolve(root: Path, path: str | Path) -> Path:
    if not isinstance(path, (str, Path)):
        raise ContractError("Stage A expected a file path")
    candidate = Path(path)
    return (candidate if candidate.is_absolute() else root / candidate).resolve()


def _prompt_version(path: Path) -> str:
    text = path.read_text(encoding="utf-8")
    match = re.search(r"(?im)^\s*(?:[-*] )?(?:\*\*)?prompt_version(?:\*\*)?\s*:\s*(\S[^\n]*)", text)
    if not match:
        raise ContractError("Stage A prompt must declare prompt_version")
    return match[1].strip()


def _key_data(config: RunConfig, root: Path, pov_id: str) -> dict:
    if pov_id not in POVS:
        raise ContractError(f"Unknown POV ID: {pov_id}")
    video = next(video for video in config.videos if video.pov_id == pov_id)
    if "A" not in config.prompts:
        raise ContractError("Stage A prompt path is required")
    source = _resolve(root, video.path)
    prompt = _resolve(root, config.prompts["A"])
    return {
        "schema_version": 1,
        "run_id": config.run_id,
        "fight_id": config.fight_id,
        "game": config.game,
        "prealigned_input_assumed": config.prealigned_input_assumed,
        "pov_id": pov_id,
        "hero": video.hero,
        "video_path": str(source),
        "video_sha256": digest(source),
        "prompt_path": str(prompt),
        "prompt_sha256": digest(prompt),
        "settings": config.inspection_settings.model_dump(),
        "stage_tool": config.stage_tools.get("A", "codex_manual"),
        "interval": [config.fight_start_timestamp, config.fight_end_timestamp],
    }


def _cache_key(data: dict) -> str:
    return _digest_bytes(_json_bytes(data))


def validate_job(job_path: Path | str, config: RunConfig, root: Path,
                 pov_id: str) -> dict:
    """Revalidate a job's current dependencies and every prepared evidence file.

    This is also used by the A-to-B handoff loader. It validates immutable file
    provenance, not the reviewer's claim to have viewed a particular frame.
    """
    if pov_id not in POVS:
        raise ContractError(f"Unknown POV ID: {pov_id}")
    root = Path(root).resolve()
    job = _resolve(root, job_path)
    output = _resolve(root, config.output_directory) / config.run_id
    _storage_path(job, output / "stage_a" / pov_id)
    data = read_json(job / "job.json")
    expected = _key_data(config, root, pov_id)
    key = _cache_key(expected)
    if (data.get("schema_version") != 1 or data.get("run_id") != config.run_id
            or data.get("fight_id") != config.fight_id or data.get("pov_id") != pov_id
            or data.get("key_data") != expected or data.get("cache_key") != key
            or data.get("settings") != expected["settings"]
            or data.get("interval") != expected["interval"] or job.parent.name != key):
        raise ContractError("Stale Stage A input, prompt, sampling settings, or run; prepare a new job")
    video = data.get("video")
    if (not isinstance(video, dict) or video.get("pov_id") != pov_id
            or video.get("sha256") != expected["video_sha256"]
            or video.get("path") != expected["video_path"]):
        raise ContractError("Stage A job video provenance does not match the current source")
    if data.get("prompt_hash") != expected["prompt_sha256"]:
        raise ContractError("Stage A job prompt source changed")
    snapshot = _storage_path(job / "prompt.md", job)
    if (not snapshot.is_file() or digest(snapshot) != data.get("prompt_snapshot_sha256")
            or digest(snapshot) != expected["prompt_sha256"]
            or data.get("prompt_version") != _prompt_version(snapshot)):
        raise ContractError("Stage A prompt snapshot is missing, changed, or mislabeled")
    inspection_path = _storage_path(job / "frames" / "inspection.json", job)
    if (data.get("inspection_path") != str(inspection_path)
            or not inspection_path.is_file()
            or digest(inspection_path) != data.get("inspection_sha256")):
        raise ContractError("Stage A inspection manifest is missing or changed")
    inspection = read_json(inspection_path)
    if inspection != data.get("inspection"):
        raise ContractError("Stage A job and inspection manifest disagree")
    frames = inspection.get("frames")
    fps = config.inspection_settings.frame_sampling_fps
    start, end = expected["interval"]
    if (inspection.get("frame_sampling_fps") != fps
            or inspection.get("interval") != expected["interval"]
            or inspection.get("audio_inspected") is not False
            or not isinstance(frames, list) or not frames):
        raise ContractError("Invalid Stage A inspection method, interval or frame list")
    expected_times = []
    index = 0
    while (timestamp := start + index / fps) < end:
        expected_times.append(timestamp)
        index += 1
    if len(frames) != len(expected_times):
        raise ContractError("Stage A inspection frame coverage is incomplete")
    for index, (frame, timestamp) in enumerate(zip(frames, expected_times)):
        if (not isinstance(frame, dict)
                or finite_number(frame.get("timestamp"), "frame timestamp") != timestamp):
            raise ContractError("Stage A inspection timestamps do not match the configured sampling")
        path = _storage_path(job / "frames" / f"frame_{index:06d}.jpg", job)
        if frame.get("path") != str(path) or not path.is_file() or digest(path) != frame.get("sha256"):
            raise ContractError(f"Stage A frame is missing or changed: {index}")
    return data


def _validate_review(record: dict, data: dict) -> dict:
    expected = {"reviewer", "model_or_tool", "reviewed_frame_timestamps", "audio_inspected", "limitations"}
    if set(record) != expected:
        raise ContractError(f"Stage A review requires exactly {sorted(expected)}")
    for name in ("reviewer", "model_or_tool"):
        if not isinstance(record[name], str) or not record[name].strip():
            raise ContractError(f"Review {name} must identify the actual reviewer/tool")
    reviewed = record["reviewed_frame_timestamps"]
    available = {frame["timestamp"] for frame in data["inspection"]["frames"]}
    if not isinstance(reviewed, list) or not reviewed:
        raise ContractError("Review must list actual prepared frame timestamps")
    for value in reviewed:
        finite_number(value, "reviewed frame timestamp")
    if len(reviewed) != len(set(reviewed)) or any(value not in available for value in reviewed):
        raise ContractError("Review must list distinct, finite actual prepared frame timestamps")
    if record["audio_inspected"] is not False:
        raise ContractError("Audio is not supported; audio_inspected must be false")
    limitations = record["limitations"]
    if not isinstance(limitations, list) or not limitations or any(not isinstance(value, str) or not value.strip() for value in limitations):
        raise ContractError("Review limitations must be a nonempty list of strings")
    return record


def validate_report_review(text: str, pov_id: str, data: dict, review: dict) -> dict:
    """Check that each claimed event's evidence includes an actually reviewed frame.

    This checks an explicit attestation against the prepared sampling manifest;
    it cannot prove that a reviewer actually opened the images. Review windows
    use the same half-open [start, end) convention as frame extraction.
    """
    review = _validate_review(review, data)
    errors = validate_report(text, pov_id, *data["interval"])
    if errors:
        raise ContractError("; ".join(errors))
    manifest = {"fight_start_timestamp": data["interval"][0],
                "fight_end_timestamp": data["interval"][1], "videos": [data["video"]]}
    handoff = validate_pov_report(text, pov_id, manifest)
    if handoff["prompt_version"] != data["prompt_version"]:
        raise ContractError("Report prompt_version must match the actual Stage A prompt snapshot")
    reviewed = review["reviewed_frame_timestamps"]
    for event in handoff["event_intervals"]:
        start, end = event["start_timestamp"], event["end_timestamp"]
        if not any(start <= timestamp < end for timestamp in reviewed):
            raise ContractError("Every reported event interval must contain an actually reviewed frame")
        for text_ref in event["evidence_refs"]:
            ref = EvidenceRef.parse(text_ref, manifest)
            left, right = max(start, ref.start_timestamp), min(end, ref.end_timestamp)
            if not any(left <= timestamp < right for timestamp in reviewed):
                raise ContractError("Every event evidence interval must contain an actually reviewed frame")
    return handoff


class StageAService:
    """Prepare isolated manual jobs and retain immutable imported report revisions."""

    def __init__(self, config_path: Path | str, project_root: Path | None = None):
        self._root_override = Path(project_root).resolve() if project_root is not None else None
        self.config_path = _resolve(self._root_override or Path.cwd(), config_path)
        self._reload()

    def _reload(self) -> None:
        self.config, inferred_root = load_config(self.config_path)
        self.root = self._root_override or inferred_root.resolve()
        self.output = (_resolve(self.root, self.config.output_directory) / self.config.run_id).absolute()
        configured = getattr(self.config, "manifest_path", None)
        self.manifest_path = _resolve(self.root, configured) if configured else self.output / "manifest.json"
        protected_files = {
            self.config_path, *(_resolve(self.root, video.path) for video in self.config.videos),
            *(_resolve(self.root, path) for path in self.config.prompts.values()),
            self.output / "stage_a_index.json",
        }
        handoff = getattr(self.config, "stage_a_handoff_path", None)
        protected_files.add(_resolve(self.root, handoff) if handoff else self.output / "handoff.json")
        protected_directories = [
            self.output / name for name in ("stage_a", "pov_reports", "handoffs")
        ]
        # This path must never be usable as an S0 output, including another
        # run's current index or archived results.
        protected_directories.append(_resolve(self.root, self.config.output_directory) / "runs")
        if (self.manifest_path in protected_files
                or any(self.manifest_path.is_relative_to(path) for path in protected_directories)):
            raise ContractError("manifest_path must not overwrite configuration, input evidence, prompts, or immutable artifacts")

    def validate(self) -> dict:
        self._reload()
        manifest = validate_inputs(self.config, self.root)
        # S0 is a cooperating source writer too: serialize manifest replacement
        # with downstream commits and revoke results when its evidence changes.
        with file_lock(self.output / ".stage_a_index.lock"):
            try:
                previous = read_json(self.manifest_path) if self.manifest_path.exists() else None
            except ContractError:
                previous = None
            save_json(self.manifest_path, manifest)
            downstream_index = self.output.parent / "runs" / self.config.run_id / "run_metadata.json"
            if previous != manifest and downstream_index.exists():
                ArtifactStore(self.output.parent, self.config.run_id).invalidate_from("B")
        return manifest

    def prepare(self, pov_id: str, *, force: bool = False) -> dict:
        if pov_id not in POVS:
            raise ContractError(f"Unknown POV ID: {pov_id}")
        manifest = self.validate()
        video = next(video for video in manifest["videos"] if video["pov_id"] == pov_id)
        result = {"stage": "A", "pov_id": pov_id, "status": "BLOCKED",
                  "intake_status": manifest["status"], "job_path": None, "cached": False}
        try:
            if video.get("coverage_status") not in ("complete", "PASS"):
                raise ContractError(video.get("error", "Selected POV input is blocked"))
            data_for_key = _key_data(self.config, self.root, pov_id)
            key = _cache_key(data_for_key)
            cache_dir = _storage_path(self.output / "stage_a" / pov_id / key, self.output)
            with file_lock(self.output / "stage_a" / pov_id / ".prepare.lock"):
                job = None
                if cache_dir.exists() and not force:
                    for candidate in sorted(cache_dir.iterdir(), reverse=True):
                        if not candidate.is_dir():
                            continue
                        try:
                            validate_job(candidate, self.config, self.root, pov_id)
                        except (ContractError, OSError):
                            continue
                        job = candidate
                        result["cached"] = True
                        break
                if job is None:
                    revision = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ") + "-" + uuid4().hex[:12]
                    job = _storage_path(cache_dir / revision, self.output)
                    job.mkdir(parents=True, exist_ok=False)
                    prompt = _resolve(self.root, self.config.prompts["A"])
                    (job / "prompt.md").write_bytes(prompt.read_bytes())
                    inspection = extract_frames(
                        Path(video["path"]), self.config.fight_start_timestamp,
                        self.config.fight_end_timestamp,
                        self.config.inspection_settings.frame_sampling_fps, job / "frames",
                    )
                    if _key_data(self.config, self.root, pov_id) != data_for_key:
                        raise ContractError("Stage A source or prompt changed during preparation")
                    tools = {}
                    for name in ("ffmpeg", "ffprobe"):
                        version = subprocess.run([name, "-version"], capture_output=True, text=True,
                                                 check=True, timeout=30)
                        tools[name] = version.stdout.splitlines()[0]
                    job_data = {
                        "schema_version": 1, "run_id": self.config.run_id, "fight_id": self.config.fight_id,
                        "pov_id": pov_id, "video": video, "cache_key": key, "key_data": data_for_key,
                        "prompt_hash": data_for_key["prompt_sha256"],
                        "prompt_snapshot_sha256": digest(job / "prompt.md"),
                        "prompt_version": _prompt_version(job / "prompt.md"),
                        "settings": data_for_key["settings"], "inspection": inspection,
                        "inspection_path": str(job / "frames" / "inspection.json"),
                        "inspection_sha256": digest(job / "frames" / "inspection.json"),
                        "interval": data_for_key["interval"], "status": "AWAITING_INSPECTION", "tools": tools,
                    }
                    save_json(job / "job.json", job_data)
                    validate_job(job, self.config, self.root, pov_id)
                result.update(job_path=str(job), job=str(job), cache_key=key,
                              reason="Frames prepared; actual visual inspection and report submission are required.")
        except (OSError, ValueError, KeyError, subprocess.SubprocessError) as exc:
            result["reason"] = str(exc)
        save_json(self.output / f"stage_a_{pov_id}_status.json", result)
        return result

    def submit(self, pov_id: str, job_path: Path | str, report_path: Path | str,
               review_path: Path | str) -> dict:
        self._reload()
        data = validate_job(job_path, self.config, self.root, pov_id)
        job = _resolve(self.root, job_path)
        review = _validate_review(read_json(_resolve(self.root, review_path)), data)
        try:
            report_bytes = _resolve(self.root, report_path).read_bytes()
            text = report_bytes.decode("utf-8")
        except UnicodeError as exc:
            raise ContractError("Stage A report must be UTF-8 text") from exc
        validate_report_review(text, pov_id, data, review)
        report_hash = _digest_bytes(report_bytes)
        review_bytes = _json_bytes(review)
        review_hash = _digest_bytes(review_bytes)
        job_hash = digest(job / "job.json")
        revision = _digest_bytes(_json_bytes({"report": report_hash, "review": review_hash, "job": job_hash}))
        target = _storage_path(self.output / "pov_reports" / pov_id / revision, self.output)
        provenance = {
            "schema_version": 1, "run_id": self.config.run_id, "fight_id": self.config.fight_id,
            "pov_id": pov_id, "cache_key": data["cache_key"], "status": "PASS_WITH_LIMITATIONS",
            "human_evidence_audit": "PENDING", "job_path": str(job), "job_sha256": job_hash,
            "report_sha256": report_hash, "review_sha256": review_hash,
            "limitations": list(dict.fromkeys([
                "Structural validation does not establish factual accuracy or sufficient coverage; independent evidence audit is PENDING.",
                *review["limitations"], *data["inspection"].get("limitations", []),
            ])),
        }
        with file_lock(self.output / ".stage_a_index.lock"):
            # Recheck after obtaining the lock; do not bind a report to evidence
            # that was changed while its import was being validated.
            validate_job(job, self.config, self.root, pov_id)
            if digest(job / "job.json") != job_hash:
                raise ContractError("Stage A job changed during report import")
            provenance_bytes = _json_bytes(provenance)
            files = {"report.md": report_bytes, "review.json": review_bytes, "provenance.json": provenance_bytes}
            if target.exists():
                for name, content in files.items():
                    existing = _storage_path(target / name, self.output)
                    if not existing.is_file() or digest(existing) != _digest_bytes(content):
                        raise ContractError("Existing Stage A revision was changed; refusing to overwrite history")
            else:
                target.mkdir(parents=True, exist_ok=False)
                for name, content in files.items():
                    (target / name).write_bytes(content)
            record = {
                "pov_id": pov_id, "revision_id": revision,
                "report_path": str(target / "report.md"), "report_sha256": report_hash,
                "review_path": str(target / "review.json"), "review_sha256": review_hash,
                "provenance_path": str(target / "provenance.json"),
                "provenance_sha256": digest(target / "provenance.json"),
                "job_path": str(job), "job_sha256": job_hash, "status": "PASS_WITH_LIMITATIONS",
            }
            index_path = self.output / "stage_a_index.json"
            if index_path.exists():
                index = read_json(index_path)
                if (index.get("schema_version") != 1 or index.get("run_id") != self.config.run_id
                        or index.get("fight_id") != self.config.fight_id or not isinstance(index.get("reports"), dict)):
                    raise ContractError("Existing Stage A index does not match this run")
            else:
                index = {"schema_version": 1, "run_id": self.config.run_id, "fight_id": self.config.fight_id,
                         "reports": {}, "history": {}}
            if index["reports"].get(pov_id) != record:
                index["reports"][pov_id] = record
                history = index.setdefault("history", {}).setdefault(pov_id, [])
                if not any(item.get("revision_id") == revision for item in history):
                    history.append(record)
                save_json(index_path, index)
                # A new source revision revokes current downstream conclusions
                # before this index lock is released. Downstream commits take
                # the same A-index lock before their metadata lock, so an old
                # B/C/D response cannot be saved after this change unnoticed.
                downstream_index = self.output.parent / "runs" / self.config.run_id / "run_metadata.json"
                if downstream_index.exists():
                    ArtifactStore(self.output.parent, self.config.run_id).invalidate_from("B")
        return record

    def export_handoff(self) -> dict:
        from .handoff import export_handoff

        return export_handoff(self.config_path, self._root_override)
