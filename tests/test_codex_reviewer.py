"""Mocked model responses exercise real gates; these are not gameplay evaluations."""
import io
import json
from pathlib import Path
import shutil
import subprocess
import threading
from types import SimpleNamespace
from unittest.mock import patch
import pytest

from api import codex_reviewer as runner
from api.app import Job, ReviewSpec, prepare_job
from src import fusion, judge
from src.contracts import ContractError, read_json
from tests.downstream_support import source_report, d_response


def job_at(path):
    path.mkdir(parents=True, exist_ok=True)
    return Job(path, ReviewSpec(clips=[dict(id='pov1', name='test.mp4',label='Synthetic',duration=12.,anchor=0.,size=4)], question='Synthetic QA only'), 'codex')


def reviewer_at(path):
    with patch.object(runner.subprocess, 'run', return_value=SimpleNamespace(stdout='codex-cli test', returncode=0)):
        return runner.CodexReviewer(job_at(path))


def test_connection_requires_chatgpt_login(monkeypatch):
    monkeypatch.setattr(runner, '_AUTH_CACHE', (0., None))
    monkeypatch.setattr(runner.shutil, 'which', lambda _: '/fake/codex')
    with patch.object(runner.subprocess, 'run', return_value=SimpleNamespace(stdout='',stderr='Logged in using API key',returncode=0)):
        assert not runner.connection_status()['ready']
    monkeypatch.setattr(runner, '_AUTH_CACHE', (0., None))
    with patch.object(runner.subprocess, 'run', return_value=SimpleNamespace(stdout='',stderr='Logged in using ChatGPT',returncode=0)):
        assert runner.connection_status()['ready']
    monkeypatch.setattr(runner, '_AUTH_CACHE', (0., None))


def test_cli_is_ephemeral_read_only_and_does_not_inherit_keys(tmp_path, monkeypatch):
    reviewer=reviewer_at(tmp_path)
    monkeypatch.setenv('CODEX_CA_CERTIFICATE','/etc/ssl/cert.pem')
    monkeypatch.setenv('OPENAI_API_KEY','synthetic-do-not-send')
    monkeypatch.setenv('CODEX_INTERNAL_ORIGINATOR_OVERRIDE','synthetic-parent')
    def popen(command, **kwargs):
        assert '--ephemeral' in command and '--ignore-user-config' in command
        assert command[command.index('--sandbox')+1]=='read-only'
        assert 'OPENAI_API_KEY' not in kwargs['env']
        assert kwargs['env']['CODEX_CA_CERTIFICATE']=='/etc/ssl/cert.pem'
        assert 'CODEX_INTERNAL_ORIGINATOR_OVERRIDE' not in kwargs['env']
        assert '--dangerously-bypass-approvals-and-sandbox' not in command
        assert '--image' in command
        assert command[-2:]==['--','-']
        Path(command[command.index('--output-last-message')+1]).write_text(json.dumps({'payload':json.dumps({'ok':True})}))
        return SimpleNamespace(stdin=io.BytesIO(),poll=lambda:0,returncode=0)
    with patch.object(runner.subprocess,'Popen',side_effect=popen):
        assert reviewer.call('test','Only synthetic input',['fixture.jpg'])=={'ok':True}


def test_cancellation_and_timeout_stop_child(tmp_path):
    reviewer=reviewer_at(tmp_path)
    # A real sleeping child verifies termination without invoking Codex or spending usage.
    real_popen=subprocess.Popen
    children=[]
    def sleeping(command, **kwargs):
        process=real_popen(['/bin/sleep','30'],**kwargs);children.append(process);return process
    reviewer.timeout=.01
    with patch.object(runner.subprocess,'Popen',side_effect=sleeping):
        with pytest.raises(TimeoutError):reviewer.call('timeout','synthetic',[])
    assert children[0].poll() is not None
    reviewer.timeout=30
    timer=threading.Timer(.1,reviewer.job.cancel.set);timer.start()
    try:
        with patch.object(runner.subprocess,'Popen',side_effect=sleeping):
            with pytest.raises(InterruptedError):reviewer.call('cancel','synthetic',[])
    finally:timer.cancel()
    assert children[-1].poll() is not None


def test_bounded_repair_and_no_retry_for_usage_failures(tmp_path):
    reviewer=reviewer_at(tmp_path)
    with patch.object(reviewer,'call',side_effect=[{'bad':True},{'good':True}]) as call:
        def submit(value):
            if 'bad' in value:raise ContractError('invalid evidence')
            return value
        assert reviewer.validated('A','prompt',[],submit)=={'good':True}
        assert call.call_count==2
    with patch.object(reviewer,'call',side_effect=RuntimeError('usage limit')) as call:
        with pytest.raises(RuntimeError):reviewer.validated('A','prompt',[],lambda x:x)
        assert call.call_count==1


@pytest.mark.skipif(not shutil.which('ffmpeg'),reason='FFmpeg required')
@pytest.mark.parametrize('failed_audit',[False,True])
def test_automatic_pipeline_uses_real_gates_and_blocks_failed_audit(tmp_path,monkeypatch,failed_audit):
    job=job_at(tmp_path/'review')
    subprocess.run(['ffmpeg','-v','error','-f','lavfi','-i','color=c=blue:s=64x64:r=10:d=12','-c:v','libx264','-pix_fmt','yuv420p',str(job.path/'pov1.mp4')],check=True)
    monkeypatch.setattr(runner,'connection_status',lambda:{'ready':True})
    monkeypatch.setattr(runner,'configured_model',lambda:'synthetic-test')
    def init(self,job):
        self.job=job;self.directory=job.path/'runner';self.directory.mkdir();self.tool='synthetic test';self.model='none'
    monkeypatch.setattr(runner.CodexReviewer,'__init__',init)
    called=[]
    def call(self,name,prompt,images):
        called.append(name)
        if name.startswith('A-'):
            assert len(images)==24 and all(Path(p).is_file() for p in images)
            package=Path(read_json(job.path/'pov1-task.json')['job_path'])
            data=read_json(package/'job.json')
            return {'report_markdown':source_report('pov1').replace('synthetic-test-a-v1',data['prompt_version']).replace('0.0–6.0','0.0–12.0'), 'review':{'reviewer':'synthetic','model_or_tool':'none','reviewed_frame_timestamps':[1.0], 'audio_inspected':False,'limitations':['Synthetic software test; no gameplay analyzed.']}}
        if name.startswith('B-'):return fusion.example_response(('pov1',))
        if name.startswith('C-'):return judge.example_response(('pov1',))
        assert images and all(Path(p).is_file() for p in images)
        from src.pipeline import DownstreamPipeline
        # Locate the immutable D bundle without depending on the store layout.
        indexes=list(job.path.glob('outputs/**/clip_index.json'))
        clips=next(read_json(p)['clips'] for p in indexes if read_json(p)['clips'])
        return d_response(clips,fail=failed_audit)
    monkeypatch.setattr(runner.CodexReviewer,'call',call)
    prepare_job(job)
    assert called==['A-pov1-1','B-1','C-1','D-1']
    assert job.state==('failed' if failed_audit else 'complete'),job.message
    if failed_audit:assert job.report is None
    else:
        assert job.report['verdict']=='inconclusive'
        assert runner.AI_LIMITATION in job.report['limitations']
