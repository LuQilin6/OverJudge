"""Extract timestamped images. Extraction is not visual inspection."""

from __future__ import annotations

import math
from pathlib import Path
import subprocess

from .artifacts import save_json
from .contracts import sha256_file


def extract_frames(video, start, end, fps, directory):
    """Create a fresh immutable sampling set on the original video timeline."""
    for name, value in (('start', start), ('end', end), ('fps', fps)):
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            raise ValueError(f'{name} must be a finite number')
    if start < 0 or end <= start or not 0 < fps <= 30:
        raise ValueError('require 0 <= start < end and 0 < fps <= 30')
    video, directory = Path(video).resolve(), Path(directory).resolve()
    if not video.is_file():
        raise ValueError('source video does not exist')
    directory.mkdir(parents=True, exist_ok=True)
    if any(directory.iterdir()):
        raise ValueError('frame output directory must be empty; use a fresh job revision')
    frames = []
    index = 0
    while (timestamp := start + index / fps) < end:
        target = directory / f'frame_{index:06d}.jpg'
        subprocess.run(
            ['ffmpeg', '-v', 'error', '-nostdin', '-ss', str(timestamp), '-i', str(video),
             '-frames:v', '1', '-q:v', '2', '-n', str(target)],
            capture_output=True, text=True, check=True, timeout=120,
        )
        if not target.is_file() or target.stat().st_size == 0:
            raise ValueError(f'No decoded frame at {timestamp}')
        frames.append(dict(path=str(target), timestamp=timestamp,
                           sha256=sha256_file(target), inspected=False))
        index += 1
    result = dict(method='timestamped frame sampling', tool='ffmpeg',
                  frame_sampling_fps=fps, interval=[start, end], frames=frames,
                  audio_inspected=False, status='AWAITING_INSPECTION',
                  limitations=['Events between samples may be missed.',
                               'Frame extraction alone is not visual inspection; audio has not been inspected.'])
    save_json(directory / 'inspection.json', result)
    return result
