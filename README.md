# OverJudge

Overwatch 2 multi-POV teamfight analysis, based on [PROJECT_PLAN.md](PROJECT_PLAN.md).

## Current status

S0 and the **manual Codex A/B/C/D workflow** are integrated. Intake probes five
pre-aligned recordings. A prepares isolated timestamped frames and imports neutral
observation reports with review records. An explicit handoff selects five immutable
report revisions for B's fusion and C's tactical assessment. D extracts evidence
windows and requires independent review before publishing the final report.

Actual observations and audits are performed manually in Codex; the application
calls no model API. Software validates structure, provenance and release gates.
Real gameplay benchmarking remains open. See the [workflow and handoff guide](docs/STAGE_B_ONWARD.md).

## Local environment

The shared baseline is Python **3.11.9** (`.python-version`). Local environments
and recordings are not distributed through Git:

```bash
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python -m pip check
```

`requirements.txt` pins the shared runtime/test environment; `requirements.in`
records its direct dependencies. Intake uses Pydantic and the unified CLI uses
argparse. The shared environment retains the original upstream packages.
Update both dependency files together after resolving in a clean Python 3.11.9
environment and reviewing `pip freeze` output.

FFmpeg and ffprobe are external executables. Install with `brew install ffmpeg`
on macOS or `sudo apt install ffmpeg` on Debian/Ubuntu. A and D record their actual
tool versions. The Python lock does not pin these system tools. No provider
credentials are required for the manual workflow.

## Run one fight

Copy `config/run.example.json` to `config/run.json`, fill in the common interval
and paths, and preserve the original aligned recordings. The example's null end
time deliberately prevents an accidental run.

```bash
python main.py validate --config config/run.json
python main.py run --stage A --pov tank --config config/run.json
```

Repeat A for the other four POVs in separate Codex contexts. Each prepared job
contains its assigned video metadata, prompt snapshot and hashed timestamped
frames. Preparation exits 1 / BLOCKED while actual inspection is pending. After
viewing the frames, submit the Markdown report and actual review JSON:

```bash
python main.py submit --config config/run.json --pov tank \
  --job /absolute/job_path --report /absolute/report.md --review /absolute/review.json
# After all five reports are submitted:
python main.py handoff --config config/run.json
python main.py prepare --stage B --config config/run.json --accept-limitations
```

The handoff preserves `PASS_WITH_LIMITATIONS` and human evidence audit `PENDING`.
`--accept-limitations` records the coordinator's decision to proceed with the
restrictions. Execute and import B, then C, then independently review D using
its task package. The [guide](docs/STAGE_B_ONWARD.md) contains the exact response
formats, commands and publication gates.

`validate` probes S0 inputs. `validate --stage B` checks downstream handoffs.
`run` and `prepare` support A/B/C/D; A defaults to `tank` when `--pov` is omitted.

## Structure

- `main.py`, `src/cli.py`: one CLI for intake, A preparation/submission, handoff, B/C/D and status.
- `src/stage_a.py`, `src/intake.py`, `src/video_inspection.py`, `src/pov_analysis.py`: input validation and manual observation jobs.
- `src/contracts.py`, `src/handoff.py`: shared report/evidence contracts and provenance-checked five-report handoffs.
- `src/pipeline.py`, `src/fusion.py`, `src/judge.py`, `src/audit.py`: downstream orchestration, report rendering and evidence audit.
- `src/artifacts.py`: atomic writes, per-run history, dependency invalidation and release indexes.
- `prompts/stage_{a,b,c,d}.md`: versioned manual Codex instructions.
- `inputs/videos/`: five original recordings; files are not included.
- `outputs/{run_id}/`: S0 manifest, A jobs/report revisions, source index and verified handoffs.
- `outputs/runs/{run_id}/`: B/C/D task/result revisions, evidence clips, releases and `run_metadata.json`.

Recordings, outputs, secrets, local configuration, `.python-runtime/` and `.venv/`
are ignored by Git. A source revision is never silently overwritten. Updated
review records invalidate the old handoff and downstream current results.

## Validation

```bash
python -m pytest -q
python main.py --help
git diff --check
```

Tests cover contracts, provenance, five-player coverage, conflicts, abstention,
concurrent writes/publication and the full A-to-D workflow with real FFmpeg
extraction of synthetic video. Video tests skip when FFmpeg/ffprobe are absent.
Synthetic observations and reviewer attestations do not establish gameplay
accuracy. The plan's human-reviewed pilot and three-fight benchmark remain
product acceptance work; no gameplay-quality result is claimed by these tests.

## Automatic Stage A with Codex CLI

Install the Codex CLI and run `codex login`, choosing **Sign in with ChatGPT**.
Confirm `codex login status` says `Logged in using ChatGPT`. The runner requires
this login and removes `OPENAI_API_KEY` / `CODEX_API_KEY` from its child environment;
it does not fall back to API billing. Codex usage consumes your account allowance.

```bash
.venv/bin/python main.py run --stage A --pov tank --config config/run.json --execute
```

This prepares (or reuses) the assigned POV's frames, attaches them to a fresh
non-interactive `codex exec`, and automatically imports its Markdown report and
inspection attestation using the existing Stage A validators. You do not need to
open another chat or manually submit a successful response. Other POVs use the
same command with `--pov dps1`, `dps2`, `support1`, or `support2`.

`prepare` and `run` without `--execute` retain the manual workflow. Automatic
execution currently supports Stage A only. Each `--execute` invocation starts a
new analysis even when preparation is cached; avoid rerunning completed analyses
unless you want a new review. `--force` also regenerates the preparation job.

Optional flags:

- `--model MODEL`: select an available Codex model; otherwise the CLI default is
  used (user config is ignored for reproducibility).
- `--codex-timeout 900`: execution timeout in seconds (default 15 minutes).

Every attempt retains its prompt, frame-to-timestamp mapping, CLI version, JSONL
events, stderr, raw response (when produced), and status under
`outputs/{run_id}/codex_execution/{pov}/{attempt}/`. Successful imports still have
`PASS_WITH_LIMITATIONS` and independent evidence audit `PENDING`. Model attestations
and structural checks do not prove visual accuracy. No audio is supplied.

The model receives full-resolution image attachments, the one-POV prompt, and
metadata in a fresh temporary working directory. The CLI uses a read-only sandbox,
ephemeral sessions, and no user config. It is instructed not to use tools or read
other files. This prevents repository context from being supplied automatically;
it is not an OS security boundary that denies reading all other filesystem paths.
There is no session resume or cross-POV prompt sharing.

Automatic runs accept at most 100 sampled frames; shorten the configured interval
or lower the sampling rate for larger jobs, preserving the sampling limitations.
A missing login, timeout, nonzero process exit, blocked model response, or invalid
report stops import and retains a BLOCKED attempt for inspection. No automatic
retries are performed, avoiding duplicate account usage after uncertain failures.

Codex execution options follow the [official non-interactive mode documentation](https://learn.chatgpt.com/docs/non-interactive-mode).
