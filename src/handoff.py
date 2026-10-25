"""Explicit, provenance-checked Stage A -> B handoffs.

An imported observation report is still awaiting independent evidence audit.
Exporting it selects exact immutable revisions; it never upgrades review truth,
claims that frames were watched, or silently authorizes downstream execution.
"""

from __future__ import annotations

from contextlib import nullcontext
import hashlib
import json
from pathlib import Path
import re
from typing import Any

from .artifacts import file_lock, save_json
from .contracts import (
    ContractError, POV_IDS, supplied_povs, read_json, sha256_file, validate_manifest,
    validate_pov_report,
)


SCHEMA_VERSION = 1
STATUS = "PASS_WITH_LIMITATIONS"
AUDIT_STATUS = "PENDING"
_HASH = re.compile(r"[a-f0-9]{64}\Z")


def _resolve(root: Path, value: Path | str) -> Path:
    if not isinstance(value, (str, Path)) or not str(value):
        raise ContractError("Stage A handoff requires a nonempty path")
    path = Path(value)
    return (path if path.is_absolute() else root / path).resolve()


def _json_bytes(value: Any) -> bytes:
    return (json.dumps(value, sort_keys=True, ensure_ascii=False, indent=2,
                       allow_nan=False) + "\n").encode("utf-8")


def _text_list(value: Any, label: str, *, nonempty: bool = True) -> list[str]:
    if (not isinstance(value, list) or (nonempty and not value)
            or any(not isinstance(item, str) or not item.strip() for item in value)):
        raise ContractError(f"{label} must be {'a nonempty' if nonempty else 'a'} list of strings")
    return value


def _hash_file(path: Path, expected: Any, label: str) -> str:
    if not isinstance(expected, str) or not _HASH.fullmatch(expected):
        raise ContractError(f"{label} requires a SHA-256 digest")
    try:
        actual = sha256_file(path)
    except OSError as exc:
        raise ContractError(f"{label} is missing or unreadable: {path}") from exc
    if actual != expected:
        raise ContractError(f"{label} changed; submit/export a fresh Stage A handoff")
    return actual


def _storage_file(value: Any, expected: Path, label: str) -> Path:
    if not isinstance(value, str) or not value:
        raise ContractError(f"{label} must be an absolute artifact path")
    path = Path(value)
    if not path.is_absolute() or path.absolute() != path.resolve() or path.resolve() != expected.resolve():
        raise ContractError(f"{label} does not belong to the selected Stage A revision")
    return path


def _paths(config: Any, root: Path) -> tuple[Path, Path, Path, Path]:
    output_root = _resolve(root, config.output_directory)
    output = output_root / config.run_id
    manifest = _resolve(root, config.manifest_path) if config.manifest_path else output / "manifest.json"
    pointer = _resolve(root, config.stage_a_handoff_path) if config.stage_a_handoff_path else output / "handoff.json"
    protected = {manifest, output / "stage_a_index.json"}
    protected.update(_resolve(root, video.path) for video in config.videos)
    protected.update(_resolve(root, prompt) for prompt in config.prompts.values())
    if (pointer.is_relative_to(output_root / "runs")
            or (pointer.is_relative_to(output_root) and not pointer.is_relative_to(output))):
        raise ContractError("Handoff pointer cannot overwrite downstream storage or another Stage A run")
    if pointer in protected or any(pointer.is_relative_to(output / folder)
                                   for folder in ("stage_a", "pov_reports", "handoffs")):
        raise ContractError("Handoff pointer must not overwrite source evidence, metadata, or immutable history")
    return output, manifest, output / "stage_a_index.json", pointer


def _configuration(config: dict | Any) -> Any:
    # The import is intentionally lazy: Stage A's export method calls this
    # module, and this module in turn reuses its immutable-job validator.
    from .intake import RunConfig

    if isinstance(config, RunConfig):
        return config
    if not isinstance(config, dict):
        raise ContractError("Handoff configuration must be an object")
    try:
        return RunConfig.model_validate(config)
    except ValueError as exc:
        raise ContractError(f"Invalid Stage A handoff configuration: {exc}") from exc


def _validate_manifest_config(manifest: dict, config: Any, root: Path) -> None:
    validate_manifest(manifest)
    if manifest.get("status") != "PASS" or manifest.get("errors", []):
        raise ContractError("A full Stage A handoff requires a passed intake for every supplied POV")
    for key in ("run_id", "fight_id", "game", "prealigned_input_assumed",
                "fight_start_timestamp", "fight_end_timestamp"):
        if manifest.get(key) != getattr(config, key):
            raise ContractError(f"Stage A manifest {key} differs from current configuration")
    configured = {video.pov_id: video for video in config.videos}
    if set(configured) != set(supplied_povs(manifest)) or manifest.get("allow_partial_povs", False) != config.allow_partial_povs:
        raise ContractError("Manifest perspective selection differs from configuration")
    for video in manifest["videos"]:
        pov = video["pov_id"]
        current = configured[pov]
        if video["coverage_status"] != "complete":
            raise ContractError(f"Stage A handoff needs complete S0 interval coverage: {pov}")
        if (_resolve(root, video["path"]) != _resolve(root, current.path)
                or video["hero"] != current.hero):
            raise ContractError(f"Stage A source path/hero differs from configuration: {pov}")
        _hash_file(_resolve(root, current.path), video["sha256"], f"{pov} original video")


def _validated_report(pov: str, record: Any, config: Any, root: Path,
                      output: Path, manifest: dict) -> dict:
    from .stage_a import validate_job, validate_report_review

    if not isinstance(record, dict) or record.get("pov_id") != pov or record.get("status") != STATUS:
        raise ContractError(f"{pov}: a structurally accepted Stage A revision is required")
    revision = record.get("revision_id")
    if not isinstance(revision, str) or not _HASH.fullmatch(revision):
        raise ContractError(f"{pov}: invalid Stage A report revision")
    directory = output / "pov_reports" / pov / revision
    files = {}
    hashes = {}
    for field, name in (("report", "report.md"), ("review", "review.json"), ("provenance", "provenance.json")):
        files[field] = _storage_file(record.get(field + "_path"), directory / name, f"{pov} {field}")
        hashes[field] = _hash_file(files[field], record.get(field + "_sha256"), f"{pov} {field}")
    job_path = _resolve(root, record.get("job_path"))
    if not job_path.is_relative_to(output / "stage_a" / pov):
        raise ContractError(f"{pov}: job belongs to another run or POV")
    hashes["job"] = _hash_file(job_path / "job.json", record.get("job_sha256"), f"{pov} job")
    expected_revision = hashlib.sha256(_json_bytes({
        "report": hashes["report"], "review": hashes["review"], "job": hashes["job"],
    })).hexdigest()
    if revision != expected_revision:
        raise ContractError(f"{pov}: report/reviewer/job hashes do not identify this immutable revision")
    job = validate_job(job_path, config, root, pov)
    provenance = read_json(files["provenance"])
    expected = {
        "schema_version": SCHEMA_VERSION, "run_id": config.run_id, "fight_id": config.fight_id,
        "pov_id": pov, "cache_key": job["cache_key"], "status": STATUS,
        "human_evidence_audit": AUDIT_STATUS, "job_path": str(job_path),
        "job_sha256": hashes["job"], "report_sha256": hashes["report"], "review_sha256": hashes["review"],
    }
    if any(provenance.get(key) != value for key, value in expected.items()):
        raise ContractError(f"{pov}: Stage A provenance is stale, inconsistent, or incorrectly claims audit completion")
    _text_list(provenance.get("limitations"), f"{pov} provenance limitations")
    video = next(video for video in manifest["videos"] if video["pov_id"] == pov)
    if (job["video"]["sha256"] != video["sha256"]
            or _resolve(root, job["video"]["path"]) != _resolve(root, video["path"])):
        raise ContractError(f"{pov}: report job and S0 manifest refer to different evidence")
    review = read_json(files["review"])
    try:
        text = files["report"].read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise ContractError(f"{pov}: report must be readable UTF-8") from exc
    validate_report_review(text, pov, job, review)
    handoff = validate_pov_report(text, pov, manifest)
    if handoff["prompt_version"] != job.get("prompt_version"):
        raise ContractError(f"{pov}: report prompt_version differs from its inspected prompt snapshot")
    # A report's own Markdown cannot promote a structural import into an audit.
    handoff["reported_status"] = handoff["status"]
    handoff["status"] = STATUS
    handoff["human_evidence_audit"] = AUDIT_STATUS
    hashes.update({"video": video["sha256"], "prompt_snapshot": job["prompt_snapshot_sha256"],
                   "inspection": job["inspection_sha256"]})
    hashes.update({f"frame/{index}": frame["sha256"] for index, frame in enumerate(job["inspection"]["frames"])})
    return {
        "path": str(files["report"]), "sha256": hashes["report"], "text": text,
        "revision_id": revision, "handoff": handoff, "review": review,
        "provenance": provenance, "source_hashes": hashes,
    }


def _validate_bundle(bundle: dict, config: Any, root: Path) -> dict:
    output, manifest_path, index_path, _ = _paths(config, root)
    expected = {
        "schema_version": SCHEMA_VERSION, "run_id": config.run_id,
        "fight_id": config.fight_id, "game": config.game,
        "prealigned_input_assumed": True,
        "fight_start_timestamp": config.fight_start_timestamp,
        "fight_end_timestamp": config.fight_end_timestamp,
        "status": STATUS, "human_evidence_audit": AUDIT_STATUS,
        "manifest_path": str(manifest_path), "source_index_path": str(index_path),
    }
    if any(bundle.get(key) != value for key, value in expected.items()):
        raise ContractError("Stage A handoff identity, configuration, path, or audit state is inconsistent")
    _text_list(bundle.get("limitations"), "Stage A handoff limitations")
    manifest_hash = _hash_file(manifest_path, bundle.get("manifest_sha256"), "Stage A manifest")
    index_hash = _hash_file(index_path, bundle.get("source_index_sha256"), "Stage A source index")
    manifest = read_json(manifest_path)
    _validate_manifest_config(manifest, config, root)
    index = read_json(index_path)
    if (index.get("schema_version") != SCHEMA_VERSION or index.get("run_id") != config.run_id
            or index.get("fight_id") != config.fight_id):
        raise ContractError("Stage A source index belongs to a different run or fight")
    selected = bundle.get("reports")
    if (not isinstance(selected, dict) or set(selected) != set(supplied_povs(manifest))
            or not isinstance(index.get("reports"), dict) or set(index["reports"]) != set(supplied_povs(manifest))):
        raise ContractError("Stage A handoff requires one report for every explicitly supplied POV")
    if selected != index["reports"]:
        raise ContractError("A Stage A report selection changed; export a fresh handoff")
    reports = {pov: _validated_report(pov, selected[pov], config, root, output, manifest) for pov in supplied_povs(manifest)}
    hashes = {"manifest": manifest_hash, "stage_a_index": index_hash}
    limitations = list(bundle["limitations"])
    for pov, report in reports.items():
        hashes.update({f"{pov}/{key}": digest for key, digest in report["source_hashes"].items()})
        limitations.extend(f"Stage A {pov}: {item}" for item in report["provenance"]["limitations"])
        limitations.extend(f"Stage A {pov} reviewer: {item}" for item in report["review"]["limitations"])
    return {
        "manifest": manifest, "manifest_path": str(manifest_path), "reports": reports,
        "source_hashes": hashes, "limitations": list(dict.fromkeys(limitations)),
        "status": STATUS, "human_evidence_audit": AUDIT_STATUS,
    }


def load_stage_a_handoff(handoff_path: Path | str, config: dict | Any,
                         project_root: Path, *, already_locked: bool = False) -> dict:
    """Load a current A handoff and recheck every selected evidence dependency.

    ``already_locked`` is for the runner's A-index -> downstream-store commit
    guard. Its caller must hold this run's ``.stage_a_index.lock`` throughout
    validation and commit; reacquiring that flock through another descriptor
    could deadlock. Ordinary reads take the lock themselves.
    """
    if type(already_locked) is not bool:
        raise ContractError("already_locked must be a boolean")
    root = Path(project_root).resolve()
    cfg = _configuration(config)
    output, _, _, _ = _paths(cfg, root)
    path = _resolve(root, handoff_path)
    lock = nullcontext() if already_locked else file_lock(output / ".stage_a_index.lock")
    with lock:
        bundle = read_json(path)
        result = _validate_bundle(bundle, cfg, root)
        result["source_hashes"]["handoff"] = sha256_file(path)
        result["path"] = str(path)
        return result


def export_handoff(config_path: Path | str, project_root: Path | None = None) -> dict:
    """Select supplied imported A revisions without granting an evidence-audit PASS."""
    from .intake import load_config

    config, inferred = load_config(config_path, project_root)
    root = Path(project_root or inferred).resolve()
    output, manifest_path, index_path, pointer = _paths(config, root)
    configuration_path = _resolve(Path(project_root).resolve() if project_root is not None else Path.cwd(), config_path)
    if pointer == configuration_path:
        raise ContractError("Handoff pointer must not overwrite its run configuration")
    with file_lock(output / ".stage_a_index.lock"):
        index = read_json(index_path)
        manifest = read_json(manifest_path)
        limitations = [
            "Stage A reports are structurally accepted only; independent human evidence audit is PENDING.",
            "Downstream execution requires the coordinator's explicit acceptance of these limitations.",
        ]
        limitations.extend(_text_list(manifest.get("limitations", []), "S0 limitations", nonempty=False))
        bundle = {
            "schema_version": SCHEMA_VERSION, "run_id": config.run_id, "fight_id": config.fight_id,
            "game": config.game, "prealigned_input_assumed": True,
            "fight_start_timestamp": config.fight_start_timestamp, "fight_end_timestamp": config.fight_end_timestamp,
            "status": STATUS, "human_evidence_audit": AUDIT_STATUS,
            "manifest_path": str(manifest_path), "manifest_sha256": sha256_file(manifest_path),
            "source_index_path": str(index_path), "source_index_sha256": sha256_file(index_path),
            "reports": index.get("reports"), "limitations": list(dict.fromkeys(limitations)),
        }
        _validate_bundle(bundle, config, root)
        digest = hashlib.sha256(_json_bytes(bundle)).hexdigest()
        snapshot = output / "handoffs" / digest / "handoff.json"
        if snapshot.absolute() != snapshot.resolve() or not snapshot.resolve().is_relative_to(output):
            raise ContractError("Handoff snapshot storage is redirected outside its immutable run")
        if snapshot.exists():
            _hash_file(snapshot, digest, "Immutable Stage A handoff snapshot")
        else:
            save_json(snapshot, bundle)
        save_json(pointer, bundle)
        return {
            "status": STATUS, "path": str(pointer), "snapshot_path": str(snapshot),
            "sha256": digest, "report_count": len(config.videos),
            "human_evidence_audit": AUDIT_STATUS, "limitations": bundle["limitations"],
        }
