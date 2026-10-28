"""Non-interactive, image-attached Codex adapter for Stage A.

Only parent Python writes/imports reports. Each invocation gets a fresh temporary
working directory, one POV's images, and no repository context. This is context
isolation, not an OS read-access security boundary.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
from uuid import uuid4

from .artifacts import save_json
from .contracts import ContractError, read_json
from .stage_a import validate_job

SCHEMA = {
    'type': 'object', 'additionalProperties': False,
    'properties': {
        'status': {'type': 'string', 'enum': ['PASS_WITH_LIMITATIONS', 'BLOCKED']},
        'reason': {'type': 'string'},
        'report_markdown': {'type': 'string'},
        'reviewed_frame_timestamps': {'type': 'array', 'items': {'type': 'number'}},
        'limitations': {'type': 'array', 'items': {'type': 'string'}},
    },
    'required': ['status', 'reason', 'report_markdown', 'reviewed_frame_timestamps', 'limitations'],
}


def find_codex(binary='codex'):
    """Resolve PATH first, then known desktop bundles on macOS."""
    found = shutil.which(binary)
    if found:
        return found
    if binary != 'codex':
        return None
    for applications in (Path('/Applications'), Path.home() / 'Applications'):
        for relative in (
            'ChatGPT.app/Contents/Resources/codex-cli/CodexCLI.app/Contents/MacOS/codex',
            'Codex.app/Contents/Resources/codex',
        ):
            candidate = applications / relative
            if candidate.is_file() and os.access(candidate, os.X_OK):
                return str(candidate)
    return None


def execute_stage_a(service, pov, *, force=False, model=None, timeout=900, binary='codex'):
    """Prepare, execute, and submit. Never turns model failure into a passed report."""
    if timeout <= 0:
        raise ContractError('Codex timeout must be positive')
    prepared = service.prepare(pov, force=force)
    if not prepared.get('job_path'):
        return prepared
    job = Path(prepared['job_path'])
    data = validate_job(job, service.config, service.root, pov)
    attempt = service.output / 'codex_execution' / pov / (datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S') + '-' + uuid4().hex)
    attempt.mkdir(parents=True, exist_ok=False)
    result = dict(stage='A', pov_id=pov, status='BLOCKED', job_path=str(job), execution_path=str(attempt))
    env = os.environ.copy()
    # This adapter deliberately uses the saved ChatGPT login, never API billing.
    for key in ('OPENAI_API_KEY', 'CODEX_API_KEY'):
        env.pop(key, None)
    try:
        executable = find_codex(binary)
        if not executable:
            raise ContractError('Codex CLI not found; install it and run codex login')
        auth = subprocess.run([executable, 'login', 'status'], env=env, capture_output=True, text=True, timeout=30)
        if auth.returncode or 'logged in using chatgpt' not in (auth.stdout + auth.stderr).lower():
            raise ContractError('ChatGPT login required: run codex login and choose ChatGPT sign-in')
        version = subprocess.run([executable, '--version'], env=env, capture_output=True, text=True, check=True, timeout=30).stdout.strip()
        frames = data['inspection']['frames']
        if len(frames) > 100:
            raise ContractError('More than 100 frames: shorten the interval or lower sampling rate before automatic analysis')
        with tempfile.TemporaryDirectory(prefix='overjudge-codex-') as folder:
            workspace = Path(folder)
            schema = workspace / 'schema.json'
            save_json(schema, SCHEMA)
            response = attempt / 'response.json'
            command = [executable, 'exec', '--ignore-user-config', '--ephemeral', '--skip-git-repo-check',
                       '--sandbox', 'read-only', '--json', '--color', 'never', '-C', str(workspace),
                       '--output-schema', str(schema), '--output-last-message', str(response)]
            if model:
                command.extend(['--model', model])
            mapping = []
            for index, frame in enumerate(frames):
                image = workspace / f'frame_{index:06d}.jpg'
                shutil.copyfile(frame['path'], image)
                command.extend(['--image', str(image)])
                mapping.append({'attachment': index + 1, 'file': image.name, 'timestamp': frame['timestamp']})
            command.extend(['--', '-'])
            prompt = (job / 'prompt.md').read_text() + '\n\nAutomatic execution contract:\n' + json.dumps({
                'pov_id': pov, 'video': data['video'], 'interval': data['interval'],
                'prompt_version': data['prompt_version'], 'sampling_fps': data['inspection']['frame_sampling_fps'],
                'image_mapping': mapping, 'tool': version, 'model_requested': model or 'CLI default (exact model unknown)',
            }, indent=2) + '\nInspect the attached images directly. Do not use tools or read any other files. Return ONLY the schema-shaped JSON; put the complete required Markdown report in report_markdown. Do not write files or invoke submit. List only actually inspected image timestamps. Audio was not supplied. If images are unavailable or insufficient return BLOCKED; never invent events. Outputs produced may say structured response containing report and review attestation.\n'
            (attempt / 'prompt.txt').write_text(prompt)
            save_json(attempt / 'invocation.json', dict(model=model, codex_version=version, image_mapping=mapping, timeout_seconds=timeout, authentication='ChatGPT', sandbox='read-only'))
            with (attempt / 'events.jsonl').open('w') as events, (attempt / 'stderr.log').open('w') as errors:
                process = subprocess.run(command, input=prompt, text=True, env=env, stdout=events, stderr=errors, timeout=timeout)
            if process.returncode:
                raise ContractError(f'Codex exited with code {process.returncode}; inspect stderr.log')
            payload = read_json(response)
            if payload.get('status') != 'PASS_WITH_LIMITATIONS':
                raise ContractError('Codex blocked analysis: ' + str(payload.get('reason', 'No reason supplied')))
            report = attempt / 'report.md'
            if not isinstance(payload.get('report_markdown'), str):
                raise ContractError('Codex response missing report text')
            report.write_text(payload['report_markdown'])
            review = attempt / 'review.json'
            save_json(review, dict(reviewer='Codex CLI automated POV analyst', model_or_tool=f'{version}; requested model: {model or "CLI default (unknown)"}', reviewed_frame_timestamps=payload.get('reviewed_frame_timestamps'), audio_inspected=False, limitations=payload.get('limitations')))
            imported = service.submit(pov, job, report, review)
            result.update(status='PASS_WITH_LIMITATIONS', imported=imported, human_evidence_audit='PENDING', reason='Report imported; factual accuracy still requires independent evidence audit.')
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        result['reason'] = str(exc)
    save_json(attempt / 'status.json', result)
    save_json(service.output / f'stage_a_{pov}_status.json', result)
    return result
