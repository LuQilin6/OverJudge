import json
from typer.testing import CliRunner
from src.cli import app
from src.video_inspection import extract_frames


def test_invalid_configuration_blocks(tmp_path):
    path = tmp_path / 'run.json'
    path.write_text('{}')
    result = CliRunner().invoke(app, ['run', '--config', str(path)])
    assert result.exit_code == 1
    assert 'BLOCKED' in result.output


def test_extraction_preserves_absolute_time(tmp_path, monkeypatch):
    def fake_run(args, **kwargs):
        from pathlib import Path
        Path(args[-1]).write_bytes(b'image')
    monkeypatch.setattr('src.video_inspection.subprocess.run', fake_run)
    data = extract_frames(tmp_path / 'video.mp4', 12, 13, 2, tmp_path / 'frames')
    assert [f['timestamp'] for f in data['frames']] == [12, 12.5]
    assert not any(f['inspected'] for f in data['frames'])
    assert data['status'] == 'AWAITING_INSPECTION'


def test_pilot_prepares_job_but_remains_blocked(tmp_path, monkeypatch):
    from pathlib import Path
    from tests.test_input_coverage import config_data
    data = config_data()
    data['fight_start_timestamp'] = 12
    data['fight_end_timestamp'] = 13
    path = tmp_path / 'run.json'
    path.write_text(json.dumps(data))
    video = tmp_path / 'inputs/videos/tank.mp4'
    video.parent.mkdir(parents=True)
    video.write_bytes(b'fixture')
    prompt = tmp_path / 'prompts/stage_a.md'
    prompt.parent.mkdir()
    prompt.write_text('prompt_version: 1.0')
    monkeypatch.setattr('src.intake.probe', lambda p: dict(duration_seconds=30, fps=30, width=640, height=480, audio_present=False))
    def fake_run(args, **kwargs):
        if '-frames:v' in args:
            Path(args[-1]).write_bytes(b'image')
        return type('Result', (), {'stdout': 'test tool version\n'})()
    monkeypatch.setattr('subprocess.run', fake_run)
    result = CliRunner().invoke(app, ['run', '--config', str(path), '--pov', 'tank'])
    assert result.exit_code == 1, result.output
    jobs = list((tmp_path / 'outputs').rglob('job.json'))
    assert len(jobs) == 1
    assert json.loads(jobs[0].read_text())['interval'] == [12, 13]
    assert not list((tmp_path / 'outputs').rglob('report.md'))
    result = CliRunner().invoke(app, ['run', '--config', str(path), '--pov', 'tank'])
    assert result.exit_code == 1
    assert len(list((tmp_path / 'outputs').rglob('job.json'))) == 1
