"""CLI for intake and explicitly human-reviewed Stage A jobs."""
import hashlib
import json
from pathlib import Path
import subprocess
import typer
from src.artifacts import digest, save_json
from src.intake import POVS, load_config, validate_inputs
from src.video_inspection import extract_frames
from src.pov_analysis import validate_report

app = typer.Typer(pretty_exceptions_enable=False)


def context(path):
    try:
        config, root = load_config(path)
        return config, root, root / config.output_directory / config.run_id
    except (OSError, ValueError) as exc:
        typer.echo(f'BLOCKED: {exc}', err=True)
        raise typer.Exit(1)


@app.command()
def validate(config: Path = typer.Option(...)):
    cfg, root, output = context(config)
    manifest = validate_inputs(cfg, root)
    save_json(output / 'manifest.json', manifest)
    typer.echo(json.dumps(manifest, indent=2))
    if manifest['status'] != 'PASS':
        raise typer.Exit(1)


@app.command()
def run(config: Path = typer.Option(...), stage: str = 'A', pov: str = 'tank'):
    cfg, root, output = context(config)
    if stage != 'A' or pov not in POVS:
        typer.echo('Only Stage A and known POV IDs are supported', err=True)
        raise typer.Exit(1)
    manifest = validate_inputs(cfg, root)
    save_json(output / 'manifest.json', manifest)
    # Pilot mode allows one valid POV while preserving the failed five-POV intake gate.
    video = next(v for v in manifest['videos'] if v['pov_id'] == pov)
    metadata = dict(stage='A', pov_id=pov, status='BLOCKED', intake_status=manifest['status'])
    try:
        if video['coverage_status'] != 'PASS':
            raise ValueError(video.get('error', 'Input blocked'))
        prompt = root / cfg.prompts['A']
        key_data = dict(video=video['sha256'], prompt=digest(prompt), settings=cfg.inspection_settings.model_dump(), interval=[cfg.fight_start_timestamp, cfg.fight_end_timestamp])
        key = hashlib.sha256(json.dumps(key_data, sort_keys=True).encode()).hexdigest()
        job = output / 'stage_a' / pov / key
        if not (job / 'job.json').exists():
            inspection = extract_frames(Path(video['path']), cfg.fight_start_timestamp, cfg.fight_end_timestamp, cfg.inspection_settings.frame_sampling_fps, job / 'frames')
            job_data = dict(pov_id=pov, video=video, cache_key=key, prompt_hash=key_data['prompt'], inspection=inspection, interval=key_data['interval'], status='AWAITING_INSPECTION', tools={name: subprocess.run([name, '-version'], capture_output=True, text=True, check=True).stdout.splitlines()[0] for name in ('ffmpeg', 'ffprobe')})
            (job / 'prompt.md').write_text(prompt.read_text())
            save_json(job / 'job.json', job_data)
        metadata.update(job=str(job), cache_key=key, reason='Frames prepared. Actual visual inspection and report submission required.')
        typer.echo(f'BLOCKED pending visual inspection: {job}')
    except (OSError, ValueError, KeyError, subprocess.SubprocessError) as exc:
        metadata['reason'] = str(exc)
        typer.echo(f'BLOCKED: {exc}', err=True)
    save_json(output / f'stage_a_{pov}_status.json', metadata)
    raise typer.Exit(1)


@app.command()
def submit(config: Path = typer.Option(...), pov: str = typer.Option(...), job: Path = typer.Option(...), report: Path = typer.Option(...), review: Path = typer.Option(...)):
    """Import a report plus explicit inspection record; structural checks only."""
    cfg, root, output = context(config)
    try:
        data = json.loads((job / 'job.json').read_text())
        if pov not in POVS or data['pov_id'] != pov:
            raise ValueError('POV mismatch')
        video = next(v for v in cfg.videos if v.pov_id == pov)
        if digest(root / video.path) != data['video']['sha256'] or digest(root / cfg.prompts['A']) != data['prompt_hash']:
            raise ValueError('Stale input or prompt; prepare a new job')
        if data['interval'] != [cfg.fight_start_timestamp, cfg.fight_end_timestamp]:
            raise ValueError('Fight interval changed')
        record = json.loads(review.read_text())
        available = {f['timestamp'] for f in data['inspection']['frames']}
        reviewed = record.get('reviewed_frame_timestamps', [])
        if not record.get('reviewer') or not record.get('model_or_tool') or not reviewed or any(t not in available for t in reviewed):
            raise ValueError('Review must identify reviewer/tool and actual reviewed frame timestamps')
        if not record.get('limitations') or record.get('audio_inspected') is not False:
            raise ValueError('Document limitations and audio_inspected=false')
        text = report.read_text()
        errors = validate_report(text, pov, *data['interval'])
        if errors:
            raise ValueError('; '.join(errors))
        revision = digest(report)
        target = output / 'pov_reports' / pov / revision
        target.mkdir(parents=True, exist_ok=True)
        (target / 'report.md').write_text(text)
        save_json(target / 'review.json', record)
        save_json(target / 'provenance.json', dict(job=str(job.resolve()), cache_key=data['cache_key'], status='PASS_WITH_LIMITATIONS', human_evidence_audit='PENDING', limitations=['Structural validation does not establish factual accuracy or sufficient coverage.']))
        typer.echo(f'Imported for evidence audit: {target}')
    except (OSError, ValueError, KeyError, StopIteration) as exc:
        typer.echo(f'BLOCKED: {exc}', err=True)
        raise typer.Exit(1)
