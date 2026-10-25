"""Immutable stage revisions and an atomic, hash-checked index for one run.

This module stores artifacts; the stage runner remains responsible for validating
their contents and deciding whether a stage is allowed to run. Only index files
are replaced. Requests, results, reports, and releases are retained as revisions.
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
from typing import Any, Iterator
from uuid import uuid4

from .contracts import ContractError, sha256_file


STAGES = ("B", "C", "D")
STATUSES = {"PENDING", "RUNNING", "PASS", "PASS_WITH_LIMITATIONS", "BLOCKED", "FAIL"}
_RUN_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")
_HASH = re.compile(r"[a-f0-9]{64}\Z")
_SECRET_NAME = re.compile(
    r"(?:^|_)(?:api_key|apikey|password|passwd|secret|client_secret|"
    r"access_token|refresh_token|authorization|private_key)$", re.I
)
_SECRET_VALUE = re.compile(
    r"\b(?:sk-[A-Za-z0-9_-]{20,}|gh[pousr]_[A-Za-z0-9]{20,}|"
    r"github_pat_[A-Za-z0-9_]{20,}|AKIA[0-9A-Z]{16})\b|"
    r"-----BEGIN (?:[A-Z ]+ )?PRIVATE KEY-----"
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _json_bytes(value: Any) -> bytes:
    try:
        return (json.dumps(value, sort_keys=True, ensure_ascii=False, indent=2,
                           allow_nan=False) + "\n").encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ContractError("Artifact data must be finite JSON values") from exc


def _digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _check_credentials(value: Any, location: str = "artifact") -> None:
    """Reject explicit credential fields and recognizable keys, without logging them.

    Caller-supplied configuration must contain environment-variable *names* only.
    This intentionally does not remove arbitrary fields from the saved context.
    """
    if isinstance(value, dict):
        for key, item in value.items():
            if isinstance(key, str) and _SECRET_NAME.search(key) and item not in (None, ""):
                raise ContractError(f"Credential field is not allowed in {location}: {key}")
            _check_credentials(item, location)
    elif isinstance(value, (list, tuple)):
        for item in value:
            _check_credentials(item, location)
    elif isinstance(value, str) and _SECRET_VALUE.search(value):
        raise ContractError(f"A recognizable credential is not allowed in {location}")


def digest(path: Path | str) -> str:
    """Public Stage A compatibility helper for an original file's SHA-256."""
    return sha256_file(path)


def save_json(path: Path | str, data: Any) -> None:
    """Atomically replace one JSON file using a private temporary file.

    Multiple POV processes may save the same manifest concurrently. Every
    writer owns a separate temporary file, so a rename cannot remove another
    writer's pending file. Compound read/update operations must additionally
    use ``file_lock`` around the entire operation.
    """
    content = _json_bytes(data)
    _check_credentials(data, "JSON artifact")
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=".writing-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


@contextmanager
def file_lock(path: Path | str) -> Iterator[None]:
    """Serialize a complete Stage A index read/update on macOS and Linux."""
    import fcntl

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+b") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _stage(stage: str) -> str:
    if not isinstance(stage, str) or stage.upper() not in STAGES:
        raise ContractError("Artifact stage must be B, C, or D")
    return stage.upper()


def compute_cache_key(stage: str, context: dict, prompt: str,
                      tool_config: dict | None = None) -> str:
    """Hash the exact supplied dependencies, prompt, and tool configuration.

    The caller should include only this stage's dependencies in context. In
    particular, a Stage C prompt must not be part of Stage B's context.
    """
    stage = _stage(stage)
    if not isinstance(context, dict) or not isinstance(prompt, str):
        raise ContractError("Cache context must be an object and prompt must be text")
    return _digest(_json_bytes({"stage": stage, "context": context,
                               "prompt": prompt, "tool_config": tool_config}))


class ArtifactStore:
    """Store B/C/D artifacts beneath ``output_directory/runs/run_id``."""

    def __init__(self, output_directory: Path, run_id: str):
        if not isinstance(run_id, str) or not _RUN_ID.fullmatch(run_id):
            raise ContractError("run_id must use 1–128 letters, digits, '.', '_' or '-' and start alphanumeric")
        self.output_directory = Path(output_directory).resolve()
        self.run_id = run_id
        self.run_dir = self.output_directory / "runs" / run_id
        self._safe_path(self.run_dir)
        self.run_dir.mkdir(parents=True, exist_ok=True)
        self.metadata_path = self.run_dir / "run_metadata.json"
        self._safe_path(self.metadata_path)
        with self._lock():
            if not self.metadata_path.exists():
                self._write_index({"schema_version": 1, "run_id": run_id,
                                   "created_at": _now(), "updated_at": _now(),
                                   "stages": {}, "release": {"latest": None, "history": []}})
            else:
                self._read_index()

    def _safe_path(self, path: Path) -> Path:
        resolved = path.resolve()
        if not resolved.is_relative_to(self.output_directory):
            raise ContractError("Artifact path escapes the output directory")
        # The output root was resolved once in __init__; nothing below it may
        # redirect writes into a different run or stage, even within that root.
        if resolved != path.absolute():
            raise ContractError("Artifact storage may not be redirected by symlinks")
        return path

    @contextmanager
    def _lock(self) -> Iterator[None]:
        """Serialize index changes across CLI processes on macOS/Linux."""
        import fcntl

        lock_path = self._safe_path(self.run_dir / ".metadata.lock")
        with lock_path.open("a+b") as handle:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    def _write(self, path: Path, content: bytes) -> None:
        self._safe_path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, name = tempfile.mkstemp(prefix=".writing-", dir=path.parent)
        try:
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(name, path)
        finally:
            if os.path.exists(name):
                os.unlink(name)

    def _write_index(self, data: dict) -> None:
        data["updated_at"] = _now()
        self._write(self.metadata_path, _json_bytes(data))

    def _read_index(self) -> dict:
        try:
            data = json.loads(self.metadata_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise ContractError("Run metadata is unreadable or invalid JSON") from exc
        if not isinstance(data, dict) or data.get("run_id") != self.run_id:
            raise ContractError("Run metadata does not match this run")
        if not isinstance(data.get("stages"), dict) or not isinstance(data.get("release"), dict):
            raise ContractError("Run metadata has an invalid artifact index")
        return data

    def stage_dir(self, stage: str) -> Path:
        path = self._safe_path(self.run_dir / "stages" / _stage(stage))
        path.mkdir(parents=True, exist_ok=True)
        return path

    def _revision_dir(self, parent: Path) -> tuple[str, Path]:
        revision = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ") + "-" + uuid4().hex[:12]
        path = self._safe_path(parent / revision)
        path.mkdir(parents=True, exist_ok=False)
        return revision, path

    def save_request(self, stage: str, context: dict, prompt: str) -> Path:
        stage = _stage(stage)
        if not isinstance(context, dict) or not isinstance(prompt, str) or not prompt.strip():
            raise ContractError("A request requires a context object and nonempty prompt")
        _check_credentials(context, "request context")
        _check_credentials(prompt, "request prompt")
        context_bytes = _json_bytes(context)
        prompt_bytes = prompt.encode("utf-8")
        record = {"stage": stage, "run_id": self.run_id, "created_at": _now(),
                  "cache_key": compute_cache_key(stage, context, prompt),
                  "context_sha256": _digest(context_bytes),
                  "prompt_sha256": _digest(prompt_bytes)}
        revision, path = self._revision_dir(self.stage_dir(stage) / "requests")
        record.update({"revision_id": revision, "request_path": str(path)})
        self._write(path / "context.json", context_bytes)
        self._write(path / "prompt.md", prompt_bytes)
        self._write(path / "request_metadata.json", _json_bytes(record))
        with self._lock():
            data = self._read_index()
            entry = data["stages"].setdefault(stage, {"status": "PENDING", "history": [], "events": []})
            entry["latest_request"] = record
            entry.setdefault("requests", []).append(record)
            self._write_index(data)
        return path

    def save_result(self, stage: str, result: dict, report_markdown: str,
                    metadata: dict) -> dict:
        """Save a validated result and revoke downstream results atomically.

        A caller importing a prepared task should supply both expected request
        and upstream revision IDs, so a concurrent import cannot revive a result
        built from superseded inputs.
        """
        stage = _stage(stage)
        if not isinstance(result, dict) or not isinstance(metadata, dict):
            raise ContractError("Result and metadata must be objects")
        if not isinstance(report_markdown, str) or not report_markdown.strip():
            raise ContractError("The rendered stage report must not be empty")
        _check_credentials(result, "stage result")
        _check_credentials(metadata, "stage metadata")
        _check_credentials(report_markdown, "stage report")
        status = metadata.get("status", "PASS")
        if status not in STATUSES:
            raise ContractError("Unknown stage status")
        with self._lock():
            data = self._read_index()
            entry = data["stages"].setdefault(stage, {"status": "PENDING", "history": [], "events": []})
            request = entry.get("latest_request", {})
            expected_request = metadata.get("expected_request_revision")
            if expected_request is not None and (
                    not isinstance(expected_request, str) or not expected_request or
                    request.get("revision_id") != expected_request):
                raise ContractError("Stage request changed; import the current request revision")
            expected_upstream = metadata.get("expected_stage_revisions")
            if expected_upstream is not None:
                allowed_upstream = set(STAGES[:STAGES.index(stage)])
                if (not isinstance(expected_upstream, dict) or
                        not set(expected_upstream).issubset(allowed_upstream) or
                        any(not isinstance(value, str) or not value
                            for value in expected_upstream.values())):
                    raise ContractError("Expected stage revisions must identify upstream stages only")
                for upstream, expected_revision in expected_upstream.items():
                    upstream_entry = data["stages"].get(upstream, {})
                    current = upstream_entry.get("latest")
                    if (not isinstance(current, dict) or
                            current.get("revision_id") != expected_revision or
                            upstream_entry.get("status") != current.get("status") or
                            current.get("status") not in {"PASS", "PASS_WITH_LIMITATIONS"}):
                        raise ContractError("Upstream revisions changed; prepare the stage again")
            cache_key = metadata.get("cache_key", request.get("cache_key"))
            prompt_sha256 = metadata.get("prompt_sha256", request.get("prompt_sha256"))
            if not isinstance(cache_key, str) or not _HASH.fullmatch(cache_key):
                raise ContractError("Result needs a SHA-256 cache_key or an existing request")
            if not isinstance(prompt_sha256, str) or not _HASH.fullmatch(prompt_sha256):
                raise ContractError("Result needs a prompt_sha256 or an existing request")
            revision, path = self._revision_dir(self.stage_dir(stage) / "results")
            report_name = {"B": "fusion.md", "C": "verdict.md", "D": "qa_report.md"}[stage]
            saved_metadata = dict(metadata)
            saved_metadata.update({"stage": stage, "run_id": self.run_id, "status": status,
                                   "cache_key": cache_key, "prompt_sha256": prompt_sha256,
                                   "created_at": _now(), "revision_id": revision})
            self._write(path / "result.json", _json_bytes(result))
            self._write(path / report_name, report_markdown.encode("utf-8"))
            self._write(path / "metadata.json", _json_bytes(saved_metadata))
            record = {"revision_id": revision, "stage": stage, "status": status,
                      "created_at": saved_metadata["created_at"], "cache_key": cache_key,
                      "prompt_sha256": prompt_sha256,
                      "request_path": metadata.get("request_path", request.get("request_path")),
                      "result_path": str(path / "result.json"),
                      "report_path": str(path / report_name),
                      "metadata_path": str(path / "metadata.json"),
                      "result_sha256": sha256_file(path / "result.json"),
                      "report_sha256": sha256_file(path / report_name),
                      "metadata_sha256": sha256_file(path / "metadata.json")}
            entry.update({"status": status, "latest": record})
            entry.setdefault("history", []).append(record)
            self._invalidate_data(data, STAGES[STAGES.index(stage) + 1:], stage)
            self._write_index(data)
        return record

    def _verify_record(self, record: dict, pairs: tuple[tuple[str, str], ...]) -> None:
        for path_key, hash_key in pairs:
            value = record.get(path_key)
            if not isinstance(value, str) or not isinstance(record.get(hash_key), str):
                raise ContractError("Artifact index contains an invalid path or hash")
            path = Path(value)
            if not path.resolve().is_relative_to(self.run_dir.resolve()):
                raise ContractError("Artifact index path escapes this run")
            try:
                digest = sha256_file(path)
            except OSError as exc:
                raise ContractError(f"Indexed artifact is missing: {path.name}") from exc
            if digest != record[hash_key]:
                raise ContractError(f"Indexed artifact hash mismatch: {path.name}")

    def latest(self, stage: str) -> dict | None:
        stage = _stage(stage)
        with self._lock():
            entry = self._read_index()["stages"].get(stage, {})
            record = entry.get("latest")
        if record is None:
            return None
        if not isinstance(record, dict) or record.get("stage") != stage:
            raise ContractError("Stage index contains an invalid latest record")
        # A later BLOCKED/FAIL/RUNNING event must not expose an old PASS as current.
        if entry.get("status") != record.get("status"):
            return None
        self._verify_record(record, (("result_path", "result_sha256"),
                                     ("report_path", "report_sha256"),
                                     ("metadata_path", "metadata_sha256")))
        return record

    def load_result(self, stage: str) -> dict:
        record = self.latest(stage)
        if record is None:
            raise ContractError(f"No current result for Stage {_stage(stage)}")
        try:
            result = json.loads(Path(record["result_path"]).read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise ContractError("Stored stage result is unreadable") from exc
        if not isinstance(result, dict):
            raise ContractError("Stored stage result must be a JSON object")
        return result

    def record_status(self, stage: str, status: str, details: dict) -> None:
        stage = _stage(stage)
        if status not in STATUSES or not isinstance(details, dict):
            raise ContractError("A status event needs a valid status and details object")
        _check_credentials(details, "status details")
        with self._lock():
            data = self._read_index()
            entry = data["stages"].setdefault(stage, {"history": [], "events": []})
            entry["status"] = status
            entry.setdefault("events", []).append({"status": status, "timestamp": _now(), "details": details})
            self._write_index(data)

    def invalidate_from(self, stage: str) -> None:
        """Invalidate current/downstream pointers and release; keep every revision."""
        stage = _stage(stage)
        with self._lock():
            data = self._read_index()
            self._invalidate_data(data, STAGES[STAGES.index(stage):], stage)
            self._write_index(data)

    def _invalidate_data(self, data: dict, stages: tuple[str, ...], stage: str) -> None:
        for affected in stages:
            entry = data["stages"].setdefault(affected, {"history": [], "events": []})
            entry.update({"status": "PENDING", "latest": None})
            entry.setdefault("events", []).append({"status": "PENDING", "timestamp": _now(),
                                                     "details": {"invalidated_from": stage}})
        data["release"]["latest"] = None
        data["release"].setdefault("events", []).append({"timestamp": _now(), "invalidated_from": stage})

    def write_release(self, qa_markdown: str, final_markdown: str | None,
                      metadata: dict) -> dict:
        if not isinstance(metadata, dict) or not isinstance(qa_markdown, str) or not qa_markdown.strip():
            raise ContractError("Release needs nonempty QA text and metadata")
        status = metadata.get("status")
        if status not in {"PASS", "PASS_WITH_LIMITATIONS", "FAIL", "BLOCKED"}:
            raise ContractError("Release metadata needs a QA status")
        if final_markdown is not None and (
                status not in {"PASS", "PASS_WITH_LIMITATIONS"} or
                not isinstance(final_markdown, str) or not final_markdown.strip()):
            raise ContractError("A final report requires passing QA and nonempty text")
        _check_credentials(metadata, "release metadata")
        _check_credentials(qa_markdown, "QA report")
        _check_credentials(final_markdown, "final report")
        expected = metadata.get("expected_stage_revisions")
        if expected is not None and (
                not isinstance(expected, dict) or set(expected) != set(STAGES) or
                any(not isinstance(value, str) or not value for value in expected.values())):
            raise ContractError("expected_stage_revisions must identify B, C, and D revisions")
        revision, path = self._revision_dir(self.run_dir / "releases")
        self._write(path / "qa_report.md", qa_markdown.encode("utf-8"))
        if final_markdown is not None:
            self._write(path / "final_report.md", final_markdown.encode("utf-8"))
        self._write(path / "metadata.json", _json_bytes({**metadata, "run_id": self.run_id,
                                                        "created_at": _now(), "revision_id": revision}))
        record = {"revision_id": revision, "status": status, "created_at": _now(),
                  "published": final_markdown is not None,
                  "qa_path": str(path / "qa_report.md"),
                  "qa_sha256": sha256_file(path / "qa_report.md"),
                  "final_path": str(path / "final_report.md") if final_markdown is not None else None,
                  "final_sha256": sha256_file(path / "final_report.md") if final_markdown is not None else None,
                  "metadata_path": str(path / "metadata.json"),
                  "metadata_sha256": sha256_file(path / "metadata.json")}
        with self._lock():
            data = self._read_index()
            if expected is not None:
                for stage, expected_revision in expected.items():
                    entry = data["stages"].get(stage, {})
                    current = entry.get("latest")
                    if (not isinstance(current, dict) or
                            current.get("revision_id") != expected_revision or
                            entry.get("status") != current.get("status")):
                        raise ContractError("Release inputs changed; prepare and audit the current revisions")
                    allowed = {"PASS", "PASS_WITH_LIMITATIONS"}
                    if stage == "D" and final_markdown is None:
                        allowed.update({"FAIL", "BLOCKED"})
                    if current.get("status") not in allowed:
                        raise ContractError("Release inputs do not have passing upstream gates")
                    if stage == "D" and current.get("status") != status:
                        raise ContractError("Release QA status differs from the audited D revision")
            data["release"]["latest"] = record
            data["release"].setdefault("history", []).append(record)
            self._write_index(data)
        return record
