"""Web API tests use synthetic recordings and explicitly synthetic reports."""
import json
from pathlib import Path
import shutil
import subprocess
import time
from unittest.mock import patch
import pytest
from fastapi.testclient import TestClient
from api.app import create_app, ReviewSpec, overlap, browser_report
from overjudge import judge


def spec(count=1, size=4):
    return {'clips': [{'id': f'pov{i+1}', 'name': f'player-{i}.mp4', 'label': f'Player {i}', 'duration': 12., 'anchor': 0., 'size': size} for i in range(count)], 'question': 'Whose fault was it?', 'alignmentConfirmed': count>1}

@pytest.fixture
def client(tmp_path):
    with TestClient(create_app(tmp_path, execution='manual')) as client:
        yield client


def test_count_alignment_identity_and_size_validation(client):
    for count in (0, 6):
        assert client.post('/api/reviews', json=spec(count)).status_code == 422
    invalid = spec(2); invalid['alignmentConfirmed'] = False
    assert client.post('/api/reviews', json=invalid).status_code == 422
    invalid = spec(2); invalid['clips'][1]['id'] = 'pov1'
    assert client.post('/api/reviews', json=invalid).status_code == 422
    invalid = spec(); invalid['clips'][0]['size'] = 201*1024*1024
    assert client.post('/api/reviews', json=invalid).status_code == 422
    invalid = spec(); invalid['clips'][0]['anchor'] = 2
    assert client.post('/api/reviews', json=invalid).status_code == 422


def test_upload_bounds_cancellation_and_unavailable_tools(client):
    job = client.post('/api/reviews', json=spec()).json()['id']
    assert client.put(f'/api/reviews/{job}/clips/pov1', content=b'12345').status_code == 413
    assert client.put(f'/api/reviews/{job}/clips/pov1', content=b'12').status_code == 400
    assert client.put(f'/api/reviews/{job}/clips/pov1', content=b'1234').status_code == 200
    assert client.put(f'/api/reviews/{job}/clips/pov1', content=b'1234').status_code == 409
    with patch('api.app.shutil.which', return_value=None):
        assert client.post(f'/api/reviews/{job}/start').status_code == 503
    assert client.delete(f'/api/reviews/{job}').json()['state'] == 'cancelled'
    assert client.get(f'/api/reviews/{job}').json()['report'] is None
    assert client.put(f'/api/reviews/{job}/clips/pov1', content=b'1234').status_code == 409


def test_hostile_origin_and_unknown_job(client):
    assert client.post('/api/reviews', json=spec(), headers={'Origin':'https://example.com'}).status_code == 403
    assert client.get('/api/reviews/not-found').status_code == 404


def test_offset_mapping_and_reject_missing_perspective():
    data = spec(2)
    data['clips'][0]['anchor'] = 2.
    data['clips'][1]['anchor'] = 5.
    parsed = ReviewSpec.model_validate(data)
    duration, offsets = overlap(parsed.clips)
    assert duration == 9 and offsets == {'pov1': 0, 'pov2': 3}
    verdict = judge.example_response(('pov1','pov2'))
    verdict['confirmed_facts'] = [{'claim': 'Synthetic evidence', 'evidence_refs': ['pov2@1.0-2.0']}]
    mapped = browser_report(verdict, {'limitations':[]}, parsed, duration, offsets)
    assert mapped['evidence'][0]['refs'] == [{'povId':'pov2','start':4.,'end':5.}]
    verdict['confirmed_facts'][0]['evidence_refs'] = ['pov3@1.0-2.0']
    with pytest.raises(ValueError):
        browser_report(verdict, {'limitations':[]}, parsed, duration, offsets)

@pytest.mark.skipif(not shutil.which('ffmpeg'), reason='requires FFmpeg')
def test_real_video_preparation_and_corrupt_video(client, tmp_path):
    seed=tmp_path/'synthetic.mp4'
    subprocess.run(['ffmpeg','-v','error','-f','lavfi','-i','color=c=blue:s=64x64:r=10:d=12','-c:v','libx264','-pix_fmt','yuv420p',str(seed)],check=True)
    for content, expected in [(seed.read_bytes(),'awaiting_review'), (b'corrupt','failed')]:
        job=client.post('/api/reviews',json=spec(2,len(content))).json()['id']
        for pov in ('pov1','pov2'):
            assert client.put(f'/api/reviews/{job}/clips/{pov}',content=content).status_code==200
        assert client.post(f'/api/reviews/{job}/start').status_code==200
        deadline=time.monotonic()+40
        while time.monotonic()<deadline:
            state=client.get(f'/api/reviews/{job}').json()
            if state['state'] in ('awaiting_review','failed'):break
            time.sleep(.05)
        assert state['state']==expected, state
        assert state['report'] is None
        if expected=='awaiting_review':
            assert state['prepared']==['pov1','pov2']
        client.delete(f'/api/reviews/{job}')

@pytest.mark.skipif(not shutil.which('ffmpeg'), reason='requires FFmpeg')
def test_api_publishes_only_after_real_pipeline_gates_and_maps_timestamps(client, tmp_path):
    from overjudge.stage_a import StageAService
    from overjudge.pipeline import DownstreamPipeline
    from overjudge.contracts import read_json
    from overjudge import fusion
    from tests.downstream_support import source_report, write_json, import_response, d_response
    seed=tmp_path/'gate-test.mp4'
    subprocess.run(['ffmpeg','-v','error','-f','lavfi','-i','color=c=purple:s=64x64:r=10:d=12','-c:v','libx264','-pix_fmt','yuv420p',str(seed)],check=True)
    data=spec(2,seed.stat().st_size)
    data['clips'][0]['anchor']=2.; data['clips'][1]['anchor']=5.
    job_id=client.post('/api/reviews',json=data).json()['id']
    for pov in ('pov1','pov2'):
        client.put(f'/api/reviews/{job_id}/clips/{pov}',content=seed.read_bytes())
    client.post(f'/api/reviews/{job_id}/start')
    job=client.app.state.jobs[job_id]
    job.future.result(timeout=40)
    assert job.state=='awaiting_review',job.message
    service=StageAService(job.config,job.path)
    for pov in ('pov1','pov2'):
        package=read_json(job.path/f'{pov}-task.json')['job_path']
        info=read_json(Path(package)/'job.json')
        report=job.path/'submissions'/f'{pov}.md'
        report.write_text(source_report(pov).replace('synthetic-test-a-v1',info['prompt_version']).replace('0.0–6.0',f'0.0–{job.duration}'))
        review=job.path/'submissions'/f'{pov}.json'
        write_json(review,{'reviewer':'synthetic software test','model_or_tool':'none: synthetic fixture', 'reviewed_frame_timestamps':[1.0], 'audio_inspected':False,'limitations':['Synthetic software fixture; no gameplay inspected.']})
        service.submit(pov,package,report,review)
    service.export_handoff()
    pipeline=DownstreamPipeline(job.config,job.path)
    request=pipeline.prepare('B',accept_limitations=True)
    import_response(pipeline,'B',request['request_path'],fusion.example_response(('pov1','pov2')),accept_limitations=True)
    request=pipeline.prepare('C',accept_limitations=True)
    verdict=judge.example_response(('pov1','pov2'))
    verdict['confirmed_facts']=[{'id':'synthetic','claim':'Synthetic purple frame; not gameplay.','evidence_refs':['pov2@1.0-2.0']}]
    import_response(pipeline,'C',request['request_path'],verdict,accept_limitations=True)
    assert client.get(f'/api/reviews/{job_id}').json()['report'] is None
    request=pipeline.prepare('D',accept_limitations=True)
    clips=read_json(Path(request['request_path'])/'clip_index.json')['clips']
    import_response(pipeline,'D',request['request_path'],d_response(clips),accept_limitations=True)
    completed=client.get(f'/api/reviews/{job_id}').json()
    assert completed['state']=='complete',completed
    assert completed['report']['evidence'][0]['refs'][0]=={'povId':'pov2','start':4.,'end':5.}
    pipeline.store.invalidate_from('C')
    revoked=client.get(f'/api/reviews/{job_id}').json()
    assert revoked['state']=='awaiting_review' and revoked['report'] is None

@pytest.mark.skipif(not shutil.which('ffmpeg'), reason='requires FFmpeg')
@pytest.mark.parametrize('count', [1, 2])
def test_preparation_uses_actual_aligned_coverage_not_browser_rounding(client, tmp_path, count):
    seed = tmp_path / 'fractional-duration.mp4'
    subprocess.run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i',
                    'color=c=blue:s=64x64:r=30:d=12', '-c:v', 'libx264',
                    '-pix_fmt', 'yuv420p', str(seed)], check=True)
    data = spec(count, seed.stat().st_size)
    # Browser/container duration can include a fraction beyond the video stream.
    for clip in data['clips']:
        clip['duration'] = 12.000833
    job_id = client.post('/api/reviews', json=data).json()['id']
    for clip in data['clips']:
        client.put(f"/api/reviews/{job_id}/clips/{clip['id']}", content=seed.read_bytes())
    client.post(f'/api/reviews/{job_id}/start')
    job = client.app.state.jobs[job_id]
    job.future.result(timeout=40)
    assert job.state == 'awaiting_review', job.message
    assert job.duration == 12.0
    assert json.loads(job.config.read_text())['fight_end_timestamp'] == 12.0
    manifest = json.loads((job.path / 'outputs' / job_id / 'manifest.json').read_text())
    assert all(v['duration_seconds'] >= job.duration for v in manifest['videos'])
    assert job.report is None


def test_identical_submissions_do_not_reuse_a_previous_report(client):
    data = spec()
    old_id = client.post('/api/reviews', json=data).json()['id']
    old = client.app.state.jobs[old_id]
    old.state = 'complete'
    old.report = {'summary': 'Previously completed synthetic result'}
    new = client.post('/api/reviews', json=data).json()
    assert new['id'] != old_id
    assert new['state'] == 'uploading'
    assert new['report'] is None
    assert new['prepared'] == []
    assert client.app.state.jobs[new['id']].path != old.path


def test_real_truncation_is_blocked_before_any_agent_runs(tmp_path):
    from api.app import Job, prepare_job
    job = Job(tmp_path, ReviewSpec.model_validate(spec()), 'codex')
    metadata = {'duration_seconds': 12., 'fps': 30.}
    truncated = {'duration_seconds': 10., 'fps': 30.}
    with patch('api.app.probe', side_effect=[metadata, truncated]), \
         patch('api.app.run_process'), patch('api.app.review_job') as agent:
        prepare_job(job)
    assert job.state == 'failed'
    assert 'converted recording is shorter' in job.message
    agent.assert_not_called()
    failure = json.loads((job.path / 'failure.json').read_text())
    assert failure['stage'] == 'preparing'
    assert failure['agent_inputs'] == []


def test_responsibility_estimates_reach_browser_without_sum_gate():
    parsed = ReviewSpec.model_validate(spec(2))
    verdict = judge.example_response(('pov1', 'pov2'))
    for pov, value in [('pov1', 73), ('pov2', 26)]:
        verdict['player_findings'][pov]['responsibility_percent'] = value
    result = browser_report(verdict, {'limitations': []}, parsed, 12., {'pov1': 0, 'pov2': 0})
    assert [p['responsibilityPercent'] for p in result['players']] == [73, 26]


def test_report_uses_player_names_in_prose_and_preserves_evidence_ids():
    data = spec(2)
    data['clips'][0]['label'] = 'Alice'
    data['clips'][1]['label'] = 'Zoë $1'
    parsed = ReviewSpec.model_validate(data)
    verdict = judge.example_response(('pov1', 'pov2'))
    original = 'POV 1 followed pov2; POV-2 and POV_1. pov10 stayed unknown.'
    expected = 'Alice followed Zoë $1; Zoë $1 and Alice. pov10 stayed unknown.'
    verdict['verdict']['summary'] = original
    verdict['fight_summary']['summary'] = original
    verdict['confidence']['rationale'] = original
    verdict['confirmed_facts'] = [{'claim': original, 'evidence_refs': ['pov1@1.0-2.0']}]
    verdict['verdict']['limitations'] = [original]
    report = browser_report(verdict, {'limitations': [original]}, parsed, 12., {'pov1': 0., 'pov2': 0.})
    assert report['summary'] == report['fightSummary'] == report['confidence']['rationale'] == expected
    assert report['evidence'][0]['observation'] == expected
    assert report['evidence'][0]['refs'][0]['povId'] == 'pov1'
    assert expected in report['limitations']
    assert {p['povId'] for p in report['players']} == {'pov1', 'pov2'}
    assert verdict['verdict']['summary'] == original  # Audited artifacts remain unchanged.
