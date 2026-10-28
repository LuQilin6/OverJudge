"""Synthetic pipeline fixtures; no real gameplay judgment is asserted."""
import shutil
from pathlib import Path
import pytest
from overjudge import fusion, judge
from overjudge.contracts import ContractError, EvidenceRef, read_json, validate_manifest
from overjudge.pipeline import DownstreamPipeline
from tests.test_integrated_pipeline import integrated_project, submit_synthetic_report
from tests.downstream_support import write_json, import_response, d_response

@pytest.mark.parametrize('count', [1, 2, 3, 4, 5])
@pytest.mark.skipif(not shutil.which('ffmpeg'), reason='requires FFmpeg')
def test_supplied_perspectives_complete_pipeline(tmp_path, count):
    service = integrated_project(tmp_path)
    config = read_json(service.config_path)
    config['allow_partial_povs'] = True
    config['videos'] = config['videos'][:count]
    ids = [f'pov{i+1}' for i in range(count)]
    for video, pov in zip(config['videos'], ids):
        video['pov_id'] = pov
    write_json(service.config_path, config)
    service._reload()
    for pov in ids:
        submit_synthetic_report(service, pov)
    assert service.export_handoff()['report_count'] == count
    pipeline = DownstreamPipeline(service.config_path, tmp_path)
    prepared = pipeline.prepare('B', accept_limitations=True)
    assert set(read_json(Path(prepared['request_path'])/'response.example.json')['result']['player_knowledge_limits']) == set(ids)
    b = fusion.example_response(ids)
    import_response(pipeline, 'B', prepared['request_path'], b, accept_limitations=True)
    prepared = pipeline.prepare('C', accept_limitations=True)
    c = judge.example_response(ids)
    import_response(pipeline, 'C', prepared['request_path'], c, accept_limitations=True)
    request = Path(pipeline.prepare('D', accept_limitations=True)['request_path'])
    clips = read_json(request/'clip_index.json')['clips']
    result = import_response(pipeline, 'D', request, d_response(clips), accept_limitations=True)
    assert result['release']['published']
    assert pipeline.status()['release']['latest']['published']
    with pytest.raises(ContractError):
        EvidenceRef.parse('support2@1-2', pipeline.manifest)

@pytest.mark.skipif(not shutil.which('ffmpeg'), reason='requires FFmpeg')
def test_missing_supplied_report_still_blocks(tmp_path):
    service = integrated_project(tmp_path)
    config = read_json(service.config_path)
    config['allow_partial_povs'] = True
    config['videos'] = config['videos'][:2]
    write_json(service.config_path, config)
    service._reload()
    submit_synthetic_report(service, 'tank')
    with pytest.raises(ContractError):
        service.export_handoff()
