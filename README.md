# OverJudge

Overwatch 2 multi-POV teamfight analysis, based on [PROJECT_PLAN.md](PROJECT_PLAN.md).

## Current status

Stage B/C/D now support a **manual Codex workflow**: prepare a task package,
inspect its inputs in Codex, import a structured JSON response, and render
versioned reports. Stage D extracts real video windows with FFmpeg and requires
an explicit independent review before releasing the final report. No model API
is called by the application. See [the development and handoff guide](docs/STAGE_B_ONWARD.md).

S0 intake and Stage A video observation remain unimplemented. This branch
consumes their manifest and five independent Markdown reports. The `validate`
command checks **downstream input contracts**, not video integrity, alignment,
or observation correctness. No real gameplay evaluation has been performed.

## Local environment

A local `.venv/` is not distributed through Git. After creating one:

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

Model SDKs, OpenCV, and audio/transcription packages remain deferred until the inspection workflow is selected. No provider credentials are required for the manual workflow.

The B/C/D manual workflow uses Python's standard library and requires no new
packages. Its tests also run without installing pytest:

```bash
python -m unittest discover -s tests -v
python main.py --help
```

Video extraction integration tests require FFmpeg and ffprobe; they are skipped
when those executables are unavailable. Test recordings and reviewer statements
are explicitly synthetic and do not establish gameplay-analysis accuracy.

## Structure

- `main.py`, `src/cli.py`, `src/pipeline.py`: downstream CLI and manual task orchestration.
- `src/contracts.py`: shared manifest, evidence-reference and Stage A handoff validation.
- `src/fusion.py`, `src/judge.py`, `src/audit.py`: B/C/D result contracts and report rendering; D also extracts evidence clips and enforces the publication gate.
- `src/artifacts.py`: per-run artifact history, hashes, dependency invalidation and release indexes.
- `src/intake.py`, `src/video_inspection.py`, `src/pov_analysis.py`: S0/A placeholders owned by upstream development.
- `config/run.example.json`: copy to `config/run.json`, fill in the common interval, and supply a real S0 manifest and A reports. S0/A tool choices remain undecided.
- `prompts/stage_{b,c,d}.md`: versioned manual Codex instructions. `stage_a.md` remains a placeholder.
- `inputs/videos/`: location for five original, pre-aligned recordings (`tank`, `dps1`, `dps2`, `support1`, `support2`); recordings are not included.
- `work/clips/`: derived clips.
- `tests/`: contracts, provenance, conflict, abstention, cache, concurrency and release tests with synthetic inputs.
- `outputs/pov_reports/`: expected upstream Stage A handoffs, configurable with `pov_reports_directory`.
- `outputs/runs/{run_id}/`: immutable B/C/D requests, result revisions, evidence clips, release revisions and `run_metadata.json`.

S0 must supply `config/manifest.json`. The downstream pipeline does not fabricate
it or generate observations on behalf of Stage A. Recordings, generated artifacts,
local configuration, secrets, and `.venv/` are ignored by Git.

The original versioned plan is preserved alongside `PROJECT_PLAN.md`. This branch
does not complete upstream M0/M1 or the real-gameplay M5 evaluation gate.
