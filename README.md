# OverJudge

Overwatch 2 multi-POV teamfight analysis scaffold, based on [PROJECT_PLAN.md](PROJECT_PLAN.md).

## Current status

Scaffold only. Python modules, test files, and stage prompts are intentionally empty. CLI commands and analysis stages are not implemented. No model calls, video analysis, or validation have run.

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
