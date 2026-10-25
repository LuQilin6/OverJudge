"""Metadata validation for pre-aligned inputs; no synchronization is performed."""

from __future__ import annotations

from collections import Counter
import json
import math
import subprocess
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .contracts import read_json, sha256_file, POV_IDS

POVS = POV_IDS


class Video(BaseModel):
    model_config = ConfigDict(extra='forbid')
    pov_id: str = Field(pattern=r'^(tank|dps1|dps2|support1|support2|pov[1-5])$')
    path: str = Field(min_length=1)
    hero: str = Field(default='unknown', min_length=1)

    @field_validator('path', 'hero')
    @classmethod
    def require_visible_text(cls, value):
        if not value.strip():
            raise ValueError('video paths and hero names cannot contain only whitespace')
        return value


class Inspection(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)
    method: Literal['codex_manual'] = 'codex_manual'
    frame_sampling_fps: float = Field(default=2.0, gt=0, le=30, strict=True)
    inspect_audio: Literal[False] = False

    @field_validator('inspect_audio', mode='before')
    @classmethod
    def no_audio_inspection(cls, value):
        if value is not False:
            raise ValueError('inspect_audio must be false; audio inspection is not implemented')
        return value


class RunConfig(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)
    run_id: str = Field(pattern=r'^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$')
    game: Literal['Overwatch 2'] = 'Overwatch 2'
    fight_id: str = Field(min_length=1)
    prealigned_input_assumed: Literal[True]
    fight_start_timestamp: float = Field(ge=0, strict=True)
    fight_end_timestamp: float = Field(gt=0, strict=True)
    allow_partial_povs: bool = False
    videos: list[Video]
    prompts: dict[str, str]
    output_directory: str = Field(default='outputs', min_length=1)
    manifest_path: str | None = Field(default=None, min_length=1)
    pov_reports_directory: str | None = Field(default=None, min_length=1)
    stage_a_handoff_path: str | None = Field(default=None, min_length=1)
    max_retries: int = Field(default=2, ge=0, le=2, strict=True)
    stage_tools: dict = Field(default_factory=dict)
    inspection_settings: Inspection = Field(default_factory=Inspection)

    @field_validator('fight_id', 'output_directory', 'manifest_path', 'pov_reports_directory', 'stage_a_handoff_path')
    @classmethod
    def require_visible_text(cls, value):
        if value is not None and not value.strip():
            raise ValueError('run identifiers and configured paths cannot contain only whitespace')
        return value

    @field_validator('prealigned_input_assumed', mode='before')
    @classmethod
    def require_prealigned_input(cls, value):
        if value is not True:
            raise ValueError('prealigned_input_assumed must be true; automatic synchronization is not implemented')
        return value

    @model_validator(mode='after')
    def check_contract(self):
        if self.fight_end_timestamp <= self.fight_start_timestamp:
            raise ValueError('fight end must be after start')
        ids = [v.pov_id for v in self.videos]
        if not 1 <= len(ids) <= 5 or len(set(ids)) != len(ids):
            raise ValueError("one to five unique POV IDs required")
        if not self.allow_partial_povs and sorted(ids) != sorted(POVS[:5]):
            raise ValueError('exactly five unique POV IDs required')
        return self


def load_config(path, project_root=None):
    """Load one shared configuration, resolving relative paths from its project."""
    path = Path(path)
    if project_root is not None:
        root = Path(project_root).resolve()
        path = path if path.is_absolute() else root / path
    path = path.resolve()
    if project_root is None:
        root = path.parent.parent if path.parent.name == 'config' else path.parent
    return RunConfig.model_validate(read_json(path)), root


def probe(path):
    result = subprocess.run(
        ['ffprobe', '-v', 'error', '-show_streams', '-show_format', '-of', 'json', str(path)],
        capture_output=True, text=True, check=True, timeout=60,
    )
    data = json.loads(result.stdout)
    stream = next(s for s in data['streams'] if s['codec_type'] == 'video')
    a, b = map(float, stream['avg_frame_rate'].split('/'))
    duration = float(stream.get('duration') or data['format']['duration'])
    fps = a / b
    width, height = int(stream['width']), int(stream['height'])
    if not all(math.isfinite(x) and x > 0 for x in (duration, fps)) or width <= 0 or height <= 0:
        raise ValueError('invalid video duration, fps or dimensions')
    return dict(duration_seconds=duration, fps=fps, width=width, height=height,
                audio_present=any(s['codec_type'] == 'audio' for s in data['streams']))


def validate_inputs(config, root):
    root = Path(root).resolve()
    videos, errors = [], []
    paths = [(root / video.path).resolve() for video in config.videos]
    duplicate_paths = {path for path, count in Counter(paths).items() if count > 1}
    for video in config.videos:
        path = (root / video.path).resolve()
        item = dict(pov_id=video.pov_id, path=str(path), hero=video.hero,
                    coverage_status='blocked', missing_intervals=[])
        try:
            if path in duplicate_paths:
                raise ValueError('each POV must use a distinct resolved recording path')
            if not path.is_file():
                raise ValueError('file does not exist')
            item.update(probe(path))
            item['sha256'] = sha256_file(path)
            if item['duration_seconds'] < config.fight_end_timestamp:
                item['missing_intervals'] = [{
                    'start_timestamp': max(config.fight_start_timestamp, item['duration_seconds']),
                    'end_timestamp': config.fight_end_timestamp,
                }]
                raise ValueError('video does not cover fight interval')
            item['coverage_status'] = 'complete'
        except (OSError, ValueError, TypeError, KeyError, StopIteration, ZeroDivisionError,
                OverflowError, subprocess.SubprocessError) as exc:
            item['error'] = str(exc)
            errors.append(f'{video.pov_id}: {exc}')
        videos.append(item)
    return dict(run_id=config.run_id, game=config.game, fight_id=config.fight_id,
                prealigned_input_assumed=True, allow_partial_povs=config.allow_partial_povs,
                fight_start_timestamp=config.fight_start_timestamp,
                fight_end_timestamp=config.fight_end_timestamp, videos=videos,
                status='BLOCKED' if errors else 'PASS', errors=errors,
                limitations=['Metadata does not verify synchronization, frozen frames, or complete decode integrity.'] + ([f'Only {len(videos)} perspectives supplied. Missing perspectives are unavailable evidence, not evidence of inactivity.'] if len(videos) < 5 else []))
