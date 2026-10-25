"""Metadata validation; never synchronizes or shifts footage."""
import json
import math
import subprocess
from pathlib import Path
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator
from src.artifacts import digest

POVS = ('tank', 'dps1', 'dps2', 'support1', 'support2')


class Video(BaseModel):
    pov_id: Literal['tank', 'dps1', 'dps2', 'support1', 'support2']
    path: str
    hero: str = 'unknown'


class Inspection(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)
    method: Literal['codex_manual'] = 'codex_manual'
    frame_sampling_fps: float = Field(default=2, gt=0, le=30)
    inspect_audio: Literal[False] = False


class RunConfig(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)
    run_id: str = Field(pattern=r'^[A-Za-z0-9_-]+$')
    game: str = 'Overwatch 2'
    fight_id: str
    prealigned_input_assumed: Literal[True]
    fight_start_timestamp: float = Field(ge=0)
    fight_end_timestamp: float = Field(gt=0)
    videos: list[Video]
    prompts: dict[str, str]
    output_directory: str = 'outputs'
    max_retries: int = Field(default=2, ge=0, le=2)
    stage_tools: dict = Field(default_factory=dict)
    inspection_settings: Inspection = Field(default_factory=Inspection)

    @model_validator(mode='after')
    def check_contract(self):
        if self.fight_end_timestamp <= self.fight_start_timestamp:
            raise ValueError('fight end must be after start')
        if sorted(v.pov_id for v in self.videos) != sorted(POVS):
            raise ValueError('exactly five unique POV IDs required')
        return self


def load_config(path):
    path = Path(path).resolve()
    root = path.parent.parent if path.parent.name == 'config' else path.parent
    return RunConfig.model_validate_json(path.read_text()), root


def probe(path):
    result = subprocess.run(['ffprobe', '-v', 'error', '-show_streams', '-show_format', '-of', 'json', str(path)], capture_output=True, text=True, check=True)
    data = json.loads(result.stdout)
    stream = next(s for s in data['streams'] if s['codec_type'] == 'video')
    a, b = map(float, stream['avg_frame_rate'].split('/'))
    duration = float(stream.get('duration') or data['format']['duration'])
    fps = a / b
    if not all(math.isfinite(x) and x > 0 for x in (duration, fps)):
        raise ValueError('invalid video duration or fps')
    return dict(duration_seconds=duration, fps=fps, width=int(stream['width']), height=int(stream['height']), audio_present=any(s['codec_type'] == 'audio' for s in data['streams']))


def validate_inputs(config, root):
    videos, errors = [], []
    for video in config.videos:
        path = (root / video.path).resolve()
        item = dict(pov_id=video.pov_id, path=str(path), hero=video.hero, coverage_status='BLOCKED', missing_intervals=[])
        try:
            if not path.is_file():
                raise ValueError('file does not exist')
            item.update(probe(path))
            item['sha256'] = digest(path)
            if item['duration_seconds'] < config.fight_end_timestamp:
                item['missing_intervals'] = [[max(config.fight_start_timestamp, item['duration_seconds']), config.fight_end_timestamp]]
                raise ValueError('video does not cover fight interval')
            item['coverage_status'] = 'PASS'
        except (OSError, ValueError, KeyError, StopIteration, ZeroDivisionError, subprocess.SubprocessError) as exc:
            item['error'] = str(exc)
            errors.append(f'{video.pov_id}: {exc}')
        videos.append(item)
    return dict(run_id=config.run_id, game=config.game, fight_id=config.fight_id, prealigned_input_assumed=True, fight_start_timestamp=config.fight_start_timestamp, fight_end_timestamp=config.fight_end_timestamp, videos=videos, status='BLOCKED' if errors else 'PASS', errors=errors, limitations=['Metadata does not verify synchronization, frozen frames, or complete decode integrity.'])
