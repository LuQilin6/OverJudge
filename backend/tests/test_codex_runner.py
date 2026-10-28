"""Adapter tests use a fake Codex process, never network/model calls."""
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from overjudge.codex_runner import execute_stage_a
from overjudge.cli import main


@pytest.fixture
def fixture(tmp_path, monkeypatch):
    job = tmp_path / 'job'
    job.mkdir()
    (job / 'prompt.md').write_text('prompt_version: test-v1')
    image = job / 'frame.jpg'
    image.write_bytes(b'test-image')
    data = dict(video={'pov_id': 'tank'}, interval=[12, 13], prompt_version='test-v1', inspection={'frame_sampling_fps': 2, 'frames': [{'path': str(image), 'timestamp': 12}]})
    service = SimpleNamespace(output=tmp_path / 'output', root=tmp_path, config=None,
                              prepare=Mock(return_value={'job_path': str(job)}),
                              submit=Mock(return_value={'revision_id': 'synthetic'}))
    monkeypatch.setattr('overjudge.codex_runner.validate_job', lambda *a: data)
    monkeypatch.setattr('overjudge.codex_runner.shutil.which', lambda b: '/fake/codex')
    return service


def fake_process(payload, calls):
    def run(command, **kw):
        calls.append((command, kw))
        if command[1:3] == ['login', 'status']:
            return SimpleNamespace(returncode=0, stdout='', stderr='Logged in using ChatGPT')
        if command[1] == '--version':
            return SimpleNamespace(returncode=0, stdout='codex test')
        Path(command[command.index('--output-last-message') + 1]).write_text(json.dumps(payload))
        return SimpleNamespace(returncode=0)
    return run


def test_success_attaches_images_and_submits(fixture, monkeypatch):
    calls = []
    monkeypatch.setenv('CODEX_API_KEY', 'do-not-use')
    monkeypatch.setenv('OPENAI_API_KEY', 'do-not-use-either')
    monkeypatch.setattr('overjudge.codex_runner.subprocess.run', fake_process(dict(status='PASS_WITH_LIMITATIONS', reason='', report_markdown='synthetic report', reviewed_frame_timestamps=[12], limitations=['sampled frames']), calls))
    result = execute_stage_a(fixture, 'tank', model='explicit-test-model')
    assert result['status'] == 'PASS_WITH_LIMITATIONS'
    fixture.submit.assert_called_once()
    command, kwargs = calls[-1]
    assert '--image' in command and '--output-schema' in command
    assert command[-2:] == ['--', '-']  # End variadic image arguments before stdin.
    assert command[command.index('--sandbox') + 1] == 'read-only'
    assert 'CODEX_API_KEY' not in kwargs['env'] and 'OPENAI_API_KEY' not in kwargs['env']
    assert '"timestamp": 12' in kwargs['input']
    assert result['human_evidence_audit'] == 'PENDING'


def test_blocked_response_does_not_submit(fixture, monkeypatch):
    monkeypatch.setattr('overjudge.codex_runner.subprocess.run', fake_process({'status': 'BLOCKED', 'reason': 'unreadable images'}, []))
    result = execute_stage_a(fixture, 'tank')
    assert result['status'] == 'BLOCKED'
    fixture.submit.assert_not_called()
    assert 'unreadable images' in result['reason']


def test_api_auth_rejected(fixture, monkeypatch):
    monkeypatch.setattr('overjudge.codex_runner.subprocess.run', lambda *a, **k: SimpleNamespace(returncode=0, stdout='Logged in using API key', stderr=''))
    assert execute_stage_a(fixture, 'tank')['status'] == 'BLOCKED'
    fixture.submit.assert_not_called()


def test_timeout_does_not_submit(fixture, monkeypatch):
    import subprocess
    run = fake_process({}, [])
    def process(command, **kwargs):
        if command[1] == 'exec':
            raise subprocess.TimeoutExpired(command, kwargs['timeout'])
        return run(command, **kwargs)
    monkeypatch.setattr('overjudge.codex_runner.subprocess.run', process)
    result = execute_stage_a(fixture, 'tank', timeout=1)
    assert result['status'] == 'BLOCKED'
    fixture.submit.assert_not_called()


def test_validation_failure_does_not_pass(fixture, monkeypatch):
    monkeypatch.setattr('overjudge.codex_runner.subprocess.run', fake_process(dict(status='PASS_WITH_LIMITATIONS', report_markdown='invalid', reviewed_frame_timestamps=[12], limitations=['sampled']), []))
    fixture.submit.side_effect = ValueError('invalid report contract')
    result = execute_stage_a(fixture, 'tank')
    assert result['status'] == 'BLOCKED'
    assert 'invalid report contract' in result['reason']


def test_execute_rejects_downstream():
    with pytest.raises(SystemExit):
        main(['run', '--stage', 'B', '--execute'])


def test_find_codex_uses_desktop_bundle(monkeypatch):
    from overjudge.codex_runner import find_codex
    monkeypatch.setattr('overjudge.codex_runner.shutil.which', lambda b: None)
    expected = '/Applications/ChatGPT.app/Contents/Resources/codex-cli/CodexCLI.app/Contents/MacOS/codex'
    monkeypatch.setattr('overjudge.codex_runner.Path.is_file', lambda p: str(p) == expected)
    monkeypatch.setattr('overjudge.codex_runner.os.access', lambda p, mode: True)
    assert find_codex() == expected
    assert find_codex('explicit-missing-binary') is None


def test_find_codex_prefers_path(monkeypatch):
    from overjudge.codex_runner import find_codex
    monkeypatch.setattr('overjudge.codex_runner.shutil.which', lambda b: '/custom/bin/codex')
    assert find_codex() == '/custom/bin/codex'
