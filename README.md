# OverJudge

Overwatch 2 multi-POV teamfight analysis scaffold, based on [PROJECT_PLAN.md](PROJECT_PLAN.md).

## Current status

Stage A infrastructure is implemented: configuration/intake validation, timestamped frame extraction, isolated inspection jobs, and report import with structural checks. Analysis is Codex-led and manual; there is no automatic model backend. Stage B–D remain unimplemented. No real footage has been analyzed.

## Local environment

A Python 3.11 virtual environment is available at `.venv/`:

```bash
source .venv/bin/activate
python --version
```

To recreate it:

```bash
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python -m pip check
```

The shared baseline is Python **3.11.9** (`.python-version`). `requirements.txt` pins all resolved direct and transitive dependencies; install it for the same Python package versions. `requirements.in` records direct dependencies and their purposes: Pydantic for validation, Typer for CLI, python-dotenv for local environment loading, Pillow for frame images, and pytest for tests. The same environment includes runtime and test dependencies.

To update dependencies, use a clean Python 3.11.9 environment, install `requirements.in`, run `python -m pip check`, and regenerate `requirements.txt` with `python -m pip freeze`. Review and commit both files together. Wheel availability can differ across platforms; the initial environment was verified on macOS ARM64.

FFmpeg and ffprobe are external executables and are not installed by pip. On macOS, install them with `brew install ffmpeg`; on Debian/Ubuntu, use `sudo apt install ffmpeg`. Check `ffmpeg -version` and `ffprobe -version`. They were not available on PATH during initial setup; record their versions when video processing is implemented. This Python lock does not pin system tools.

Model SDKs, OpenCV, and audio/transcription packages remain deferred until the inspection workflow is selected. No provider credentials are required for this scaffold.

## Structure

- `main.py`, `src/`: empty entry point and modules for intake, inspection, POV analysis, fusion, judgment, audit, artifacts, and CLI.
- `config/run.example.json`: proposed configuration; copy to `config/run.json` and fill in the fight end time and tool choices when implementation begins. Null values mean undecided, not valid runtime settings.
- `prompts/stage_{a,b,c,d}.md`: empty prompt placeholders.
- `inputs/videos/`: five original, pre-aligned recordings (`tank`, `dps1`, `dps2`, `support1`, `support2`).
- `work/clips/`: derived clips.
- `tests/`: empty coverage, evidence-reference, and stage-gate test placeholders; `fixtures/` holds future test inputs.
- `outputs/pov_reports/`, `outputs/evidence_clips/`: future generated artifacts.

The pipeline will generate `config/manifest.json`, reports, and `outputs/run_metadata.json` once implemented. These are deliberately not populated with fabricated run data. Recordings, generated artifacts, local configuration, secrets, and `.venv/` are ignored by Git.

The original versioned plan is preserved alongside `PROJECT_PLAN.md`. This scaffold does not complete the plan's M0 acceptance gate, which requires working validation and reproducible output.

## Stage A workflow

Copy `config/run.example.json` to `config/run.json`, set the common fight interval,
and supply video paths. Paths resolve relative to the project containing `config/`.
The example deliberately leaves the fight end unset, so it cannot start an accidental run.
Install FFmpeg/ffprobe before processing footage.

```bash
.venv/bin/python main.py validate --config config/run.json
.venv/bin/python main.py run --stage A --pov tank --config config/run.json
.venv/bin/python -m pytest -q
```

`validate` requires all five inputs. For the one-POV pilot, `run` can prepare the
selected valid POV while recording that full intake is blocked. Outputs are scoped
to `outputs/{run_id}/`; the manifest is saved there to avoid collisions between runs.
Metadata checks do not detect frozen frames or prove synchronization.

The run creates `stage_a/{pov}/{cache_key}/job.json`, a prompt snapshot, and
`frames/inspection.json` with absolute video timestamps. Each frame starts with
`inspected: false`. A prepared job exits with status 1 / BLOCKED pending actual
visual inspection; it does not generate a gameplay narrative. Identical completed
preparation jobs are reused. Input, prompt, interval, or sampling changes create
new jobs. No audio analysis is currently supported.

Open only the assigned job's frames/video in a separate Codex context and follow
its prompt. Record actual reviewed frame timestamps in a JSON file, for example:

```json
{
  "reviewer": "reviewer name",
  "model_or_tool": "actual model/tool and version",
  "reviewed_frame_timestamps": [12.0, 12.5],
  "audio_inspected": false,
  "limitations": ["Only these sampled frames were inspected; audio unavailable."]
}
```

Import the resulting Markdown and review record:

```bash
.venv/bin/python main.py submit --config config/run.json --pov tank --job outputs/RUN/stage_a/tank/KEY --report /path/to/report.md --review /path/to/review.json
```

Import checks headings, event fields, timestamp bounds, POV citations, and review
provenance. Reports are retained by content hash under `pov_reports/{pov}/` with
review/provenance sidecars. Structural acceptance is PASS_WITH_LIMITATIONS with a
human evidence audit still PENDING; it does not establish factual accuracy or
sufficient coverage and does not authorize downstream stages. Audit ten manually
labeled events before expanding to five POVs. Sparse sampling may require denser
reinspection; change the configured sampling rate to create a new job.
