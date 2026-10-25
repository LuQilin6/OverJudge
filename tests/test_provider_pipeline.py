import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.artifacts import save_json
from src.contracts import POV_IDS, sha256_file
from src.provider_pipeline import Analysis, GeminiVideoAnalyzer, Verdict, poll_judge, start_judge


def analysis(pov='tank'):
    return dict(player_id=pov, events=[dict(event_id=pov+'_E001', start_sec=42.0,
                end_sec=45.0, observation='Visible movement', confidence='medium',
                evidence='Position changes on screen')], summary='Movement observed',
                limitations='Sparse sampling; unknown audio')


def verdict():
    claim = dict(text='Possible coordination failure', event_ids=['tank_E001'])
    return dict(fight_summary=claim, timeline=[claim], turning_point=None,
                players=[dict(text='Limited visible evidence', player_id=pov,
                              event_ids=[pov+'_E001']) for pov in POV_IDS],
                contributing_factors=[claim], final_verdict=claim, primary_player=None,
                confidence='low', limitations='Incomplete information',
                alternative_explanations=['Enemy pressure'])


def test_timestamps_identity_and_duplicate_ids():
    Analysis.model_validate(analysis()).check_interval('tank', 40, 50)
    for pov, start, end in [('dps1', 40, 50), ('tank', 43, 50), ('tank', 40, 44)]:
        with pytest.raises(ValueError):
            Analysis.model_validate(analysis()).check_interval(pov, start, end)
    data = analysis()
    data['events'] *= 2
    with pytest.raises(ValueError):
        Analysis.model_validate(data).check_interval('tank', 40, 50)


def test_verdict_rejects_fabricated_references_and_wrong_player_evidence():
    bundle = [analysis(pov) for pov in POV_IDS]
    Verdict.model_validate(verdict()).check_evidence(bundle)
    data = verdict()
    data['final_verdict'] = dict(text='Invented', event_ids=['tank_E999'])
    with pytest.raises(ValueError, match='unknown event'):
        Verdict.model_validate(data).check_evidence(bundle)
    data = verdict()
    data['players'][1]['event_ids'] = ['tank_E001']
    with pytest.raises(ValueError, match='that player'):
        Verdict.model_validate(data).check_evidence(bundle)


def test_resume_poll_and_bundle_tampering(tmp_path):
    save_json(tmp_path/'bundle.json', {'analyses': [analysis(pov) for pov in POV_IDS]})
    save_json(tmp_path/'judge_request.json', dict(agent_id='agent', prompt='investigate',
              idempotency_key='overjudge-test', bundle_sha256=sha256_file(tmp_path/'bundle.json')))
    calls = []
    judge = SimpleNamespace(start=lambda prompt, key: calls.append(key) or {'id': 'remote-run'})
    assert start_judge(tmp_path, judge)['run_id'] == 'remote-run'
    start_judge(tmp_path, judge)
    assert calls == ['overjudge-test']
    for status in ('pending', 'running', 'failed', 'cancelled'):
        judge.poll = lambda run, status=status: {'status': status}
        assert poll_judge(tmp_path, judge)['status'] == status
        assert not (tmp_path/'report.md').exists()
    judge.poll = lambda run: {'status': 'completed', 'result': {'text': json.dumps(verdict())}}
    assert poll_judge(tmp_path, judge)['audit'] == 'PENDING'
    assert (tmp_path/'report.md').exists()
    save_json(tmp_path/'bundle.json', {'analyses': []})
    with pytest.raises(ValueError, match='changed'):
        poll_judge(tmp_path, judge)


def test_gemini_upload_processing_raw_and_cleanup(tmp_path, monkeypatch):
    monkeypatch.setenv('GEMINI_API_KEY', 'test-key')
    calls = []
    uploaded = {'name': 'files/123', 'uri': 'gs://test', 'state': 'ACTIVE'}
    raw = {'candidates': [{'finishReason': 'STOP', 'content': {'parts': [{'text': json.dumps(analysis())}]}}],
           'usageMetadata': {'totalTokenCount': 123}}
    def fake(method, url, headers, body=None, **kwargs):
        calls.append((method, url, body))
        if url.endswith('/upload/v1beta/files'):
            return {}, {'X-Goog-Upload-URL': GeminiVideoAnalyzer.base+'/upload/session'}
        if url.endswith('/upload/session'):
            assert body.read() == b'video'
            return {'file': uploaded}, {}
        if ':generateContent' in url:
            metadata = body['contents'][0]['parts'][0]['videoMetadata']
            assert metadata == {'startOffset': '40s', 'endOffset': '50s', 'fps': 4.0}
            return raw, {}
        assert method == 'DELETE'
        return {}, {}
    monkeypatch.setattr('src.provider_pipeline.request', fake)
    video = tmp_path/'test.mp4'
    video.write_bytes(b'video')
    directory = tmp_path/'attempt'
    result = GeminiVideoAnalyzer('test-model', fps=4).analyze(video, 'tank', 'unknown', 40, 50, directory)
    assert result['events'][0]['start_sec'] == 42
    assert json.loads((directory/'raw.json').read_text())['usageMetadata']['totalTokenCount'] == 123
    assert calls[-1][0] == 'DELETE'
    raw['candidates'][0]['finishReason'] = 'MAX_TOKENS'
    with pytest.raises(ValueError, match='incomplete'):
        GeminiVideoAnalyzer('test-model', fps=4).analyze(video, 'tank', 'unknown', 40, 50, tmp_path/'blocked')
    assert (tmp_path/'blocked'/'raw.json').exists()
    assert (tmp_path/'blocked'/'failure.json').exists()
    assert calls[-1][0] == 'DELETE'


def test_orchestrator_five_independent_jobs_and_single_judge_submission(tmp_path, monkeypatch):
    from src.provider_pipeline import analyze_fight
    for name in ('GEMINI_API_KEY', 'CREAO_API_KEY', 'CREAO_AGENT_ID'):
        monkeypatch.setenv(name, 'test-value')
    config = SimpleNamespace(run_id='fight', fight_id='one', output_directory='outputs',
        fight_start_timestamp=40.0, fight_end_timestamp=50.0,
        videos=[SimpleNamespace(path=pov+'.mp4', pov_id=pov, hero='unknown') for pov in POV_IDS])
    monkeypatch.setattr('src.provider_pipeline.load_config', lambda *args: (config, tmp_path))
    monkeypatch.setattr('src.provider_pipeline.validate_inputs', lambda *args: {'status': 'PASS'})
    seen = []
    def analyze(self, path, pov, hero, start, end, directory):
        seen.append(pov)
        return analysis(pov)
    monkeypatch.setattr(GeminiVideoAnalyzer, 'analyze', analyze)
    def start(self, prompt, key):
        assert all(pov+'_E001' in prompt for pov in POV_IDS)
        return {'id': 'real-contract-shaped-test-run', 'status': 'pending'}
    monkeypatch.setattr('src.provider_pipeline.CreaoJudge.start', start)
    result = analyze_fight('config', None, 'test-model', concurrency=2)
    assert sorted(seen) == sorted(POV_IDS)
    assert result['status'] == 'judging'
    assert (Path(result['attempt'])/'bundle.json').exists()


def test_creao_wire_contract(monkeypatch):
    from src.provider_pipeline import CreaoJudge
    monkeypatch.setenv('CREAO_API_KEY', 'test-value')
    def send(method, url, headers, body=None):
        assert headers['Authorization'] == 'Bearer test-value'
        if method == 'POST':
            assert body == {'appId': 'saved-agent', 'inputs': {'prompt': 'investigate'},
                            'idempotencyKey': 'overjudge-123'}
            return {'id': 'run'}, {}
        assert url.endswith('/run')
        return {'status': 'pending'}, {}
    monkeypatch.setattr('src.provider_pipeline.request', send)
    judge = CreaoJudge('saved-agent')
    assert judge.start('investigate', 'overjudge-123')['id'] == 'run'
    assert judge.poll('run')['status'] == 'pending'


def test_macos_missing_python_certificates_uses_verified_system_roots(monkeypatch):
    from src.provider_pipeline import tls_context
    import ssl
    monkeypatch.setattr('src.provider_pipeline.sys.platform', 'darwin')
    monkeypatch.delenv('SSL_CERT_FILE', raising=False)
    monkeypatch.delenv('SSL_CERT_DIR', raising=False)
    monkeypatch.setattr('src.provider_pipeline.ssl.get_default_verify_paths',
                        lambda: SimpleNamespace(cafile=None))
    monkeypatch.setattr('src.provider_pipeline.Path.is_file', lambda self: True)
    calls = []
    monkeypatch.setattr('src.provider_pipeline.ssl.create_default_context',
                        lambda **kwargs: calls.append(kwargs) or 'verified-context')
    assert tls_context() == 'verified-context'
    assert calls == [{'cafile': '/etc/ssl/cert.pem'}]
    monkeypatch.setenv('SSL_CERT_FILE', '/custom/trusted.pem')
    tls_context()
    assert calls[-1] == {}


def test_resume_preserves_completed_povs_and_retries_missing_only(tmp_path, monkeypatch):
    from src.provider_pipeline import analyze_fight
    for name in ('GEMINI_API_KEY', 'CREAO_API_KEY', 'CREAO_AGENT_ID'):
        monkeypatch.setenv(name, 'test-value')
    config = SimpleNamespace(run_id='fight', fight_id='one', output_directory='outputs',
        fight_start_timestamp=40.0, fight_end_timestamp=50.0,
        videos=[SimpleNamespace(path=pov+'.mp4', pov_id=pov, hero='unknown') for pov in POV_IDS])
    monkeypatch.setattr('src.provider_pipeline.load_config', lambda *args: (config, tmp_path))
    monkeypatch.setattr('src.provider_pipeline.validate_inputs', lambda *args: {'status': 'PASS'})
    directory = tmp_path/'outputs/fight/providers/attempt'
    directory.mkdir(parents=True)
    save_json(directory/'manifest.json', {'status': 'PASS'})
    for pov in POV_IDS:
        (tmp_path/(pov+'.mp4')).write_bytes(b'original')
    for pov in ('dps1', 'support1'):
        save_json(directory/pov/'analysis.json', analysis(pov))
        save_json(directory/pov/'request.json', dict(model='test-model', fps=2.0,
                  player_id=pov, start_sec=40.0, end_sec=50.0,
                  video_sha256=sha256_file(tmp_path/(pov+'.mp4'))))
    save_json(directory/'tank/failure.json', {'status': 'BLOCKED'})
    original = (directory/'dps1/analysis.json').read_bytes()
    seen = []
    def analyze(self, path, pov, hero, start, end, destination):
        seen.append(pov)
        assert self.model == 'fallback-model'
        if pov == 'tank':
            assert destination.parent == directory/'tank'
            assert destination.name.startswith('retry-')
        return analysis(pov)
    monkeypatch.setattr(GeminiVideoAnalyzer, 'analyze', analyze)
    monkeypatch.setattr('src.provider_pipeline.CreaoJudge.start', lambda *args: {'id': 'run'})
    result = analyze_fight('config', None, 'test-model', resume_attempt=directory, retry_model='fallback-model')
    assert result['status'] == 'judging'
    assert sorted(seen) == ['dps2', 'support2', 'tank']
    assert (directory/'dps1/analysis.json').read_bytes() == original
    assert (directory/'tank/failure.json').exists()


def test_display_name_normalization_preserves_raw_and_rejects_other_pov(tmp_path):
    from src.provider_pipeline import normalize_response
    data = analysis()
    data['player_id'] = 'HUD_USERNAME'
    raw = {'candidates': [{'finishReason': 'STOP', 'content': {'parts': [{'text': json.dumps(data)}]}}]}
    assert normalize_response(raw, 'tank', 40, 50, tmp_path)['player_id'] == 'tank'
    assert json.loads((tmp_path/'normalization.json').read_text())['original_player_id'] == 'HUD_USERNAME'
    assert data['player_id'] == 'HUD_USERNAME'
    data['player_id'] = 'dps1'
    raw['candidates'][0]['content']['parts'][0]['text'] = json.dumps(data)
    with pytest.raises(ValueError, match='assigned POV'):
        normalize_response(raw, 'tank', 40, 50, tmp_path)
