"""Extract timestamped images. Extraction is not visual inspection."""
import subprocess
from src.artifacts import save_json


def extract_frames(video, start, end, fps, directory):
    directory.mkdir(parents=True, exist_ok=True)
    frames = []
    index = 0
    while (timestamp := start + index / fps) < end:
        target = directory / f'frame_{index:06d}.jpg'
        subprocess.run(['ffmpeg', '-v', 'error', '-nostdin', '-ss', str(timestamp), '-i', str(video), '-frames:v', '1', '-q:v', '2', '-y', str(target)], capture_output=True, text=True, check=True)
        if not target.is_file():
            raise ValueError(f'No decoded frame at {timestamp}')
        frames.append(dict(path=str(target.resolve()), timestamp=timestamp, inspected=False))
        index += 1
    result = dict(method='timestamped frame sampling', frame_sampling_fps=fps, interval=[start, end], frames=frames, audio_inspected=False, status='AWAITING_INSPECTION', limitations=['Events between samples may be missed.'])
    save_json(directory / 'inspection.json', result)
    return result
