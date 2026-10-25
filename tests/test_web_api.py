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
from src import judge


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
    from src.stage_a import StageAService
    from src.pipeline import DownstreamPipeline
    from src.contracts import read_json
    from src import fusion
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
