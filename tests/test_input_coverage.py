from copy import deepcopy
import json
from pathlib import Path
import pytest
from src.intake import RunConfig, validate_inputs


def config_data():
    data = json.loads(Path('config/run.example.json').read_text())
    data['fight_end_timestamp'] = 30
    return data


def test_duplicate_pov_rejected():
    data = config_data()
    data['videos'][1]['pov_id'] = 'tank'
    with pytest.raises(ValueError):
        RunConfig.model_validate(data)


def test_missing_inputs_block(tmp_path):
    result = validate_inputs(RunConfig.model_validate(config_data()), tmp_path)
    assert result['status'] == 'BLOCKED'
    assert len(result['errors']) == 5


def test_short_video_records_gap(tmp_path, monkeypatch):
    cfg = RunConfig.model_validate(config_data())
    for video in cfg.videos:
        path = tmp_path / video.path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b'fixture')
    monkeypatch.setattr('src.intake.probe', lambda p: dict(duration_seconds=20, fps=30, width=640, height=480, audio_present=False))
    result = validate_inputs(cfg, tmp_path)
    assert result['status'] == 'BLOCKED'
    assert result['videos'][0]['missing_intervals'] == [[20, 30]]
