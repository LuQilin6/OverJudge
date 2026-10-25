# Replay room integration

The courtroom React UI now lives in `web/`; the existing Python pipeline stays in
`src/`. `api/app.py` is a local FastAPI bridge between them. The older standalone
UI outside this repository is a backup, not the integrated application.

## Run locally

Use Python 3.11.9 (the team baseline), Node 22+, FFmpeg, and ffprobe. This integration
was also tested with Python 3.12. Create the environment once:

```bash
python3.11 -m venv .venv
.venv/bin/python -m pip install -r requirements-web.txt
npm --prefix web ci
./dev.sh
```

Open **http://127.0.0.1:5174/**. The Python server listens on
**127.0.0.1:3004**. Both are local only. The previous UI on 3001/5173 is a separate
backup and does not show these changes. `dev.sh` puts `.venv/bin` on PATH; install
FFmpeg and ffprobe on PATH before starting it. On this development machine,
project-local FFmpeg 8 executables were downloaded with `static-ffmpeg==3.0` and
linked in `.venv/bin`; those binaries are not committed or required Python packages.

The default reviewer now uses the installed **Codex CLI with ChatGPT login**.
Install Codex CLI if needed, run `codex login`, choose ChatGPT, and verify with
`codex login status`. Copy `.env.example` to `.env` if you want overrides, then
restart `./dev.sh`. No API key is required. Reviews use your Codex allowance.
The login check confirms local credentials, not remote service availability.

The runner follows your `~/.codex/config.toml` model selection (currently
`gpt-6-astra` on this machine); `CODEX_REVIEW_MODEL` overrides it. Other user
hooks/plugins are disabled for the review sessions. Each stage uses a fresh,
ephemeral, read-only CLI invocation with shell/browser/delegation tools disabled.

Keep this service local and operated by the signed-in user. This is not a
public, multi-user backend or a way to distribute subscription access.

## User experience

- One entrance on the landing page; no mode switch.
- Add one to five different perspectives of **one fight**, each 10–90 seconds,
  MP4/WebM, at most 200 MB.
- One recording defaults to “Was that my fault?”; two to five default to “Whose
  fault was it?”. Edited questions survive additions and removals.
- Each perspective has a stable recording ID (`pov1` through `pov5`), a player
  label, and optional role/hero. Role does not determine identity.
- For multiple recordings, mark the same visible event in each and explicitly
  confirm that the clips are from the same fight. Synchronization is user-supplied,
  not automatically inferred from audio or visuals.
- Review only the shared overlap, with at least two seconds available. Given
  anchors `a_i` and durations `d_i`, the common interval is
  `min(a_i) + min(d_i - a_i)` seconds long; recording `i` starts at
  `a_i - min(a_i)` in the original file.
- Uploads go to this local computer. FFmpeg makes aligned, silent copies; the
  pipeline prepares actual frame packages and automatically starts the Codex reviewer.
  Selected frames, questions and context are sent to OpenAI through the CLI. Audio
  is not analyzed. Local source files and diagnostic artifacts expire on cleanup.
- Evidence links select the correct original browser video and add that
  perspective’s trim offset to the pipeline timestamp. No frame-window offsets
  are discarded. The report download includes the submitted metadata and report.
- Closing while uploading/preparing/waiting cancels the job, aborts browser work,
  and retains the selected browser files and answers for an explicit retry.
  Closing a completed result retains it. Removing/adding a perspective invalidates
  the old result and alignment confirmation.

## Automatic review and limitations

Stage A inspects each supplied perspective in a separate session, using the actual
2fps JPEG frames (at most 180 per recording). B reconstructs the available views;
C produces a structured verdict. D receives newly decoded frames from the exact
cited evidence windows, in another fresh session, to check the proposed verdict.
This is a **separate AI check, not a human audit**. Human-audit provenance remains
PENDING, and limitations remain visible. One perspective cannot establish
cross-perspective corroboration. Fast abilities can be missed between frames.

The existing artifact hashes, timestamp validation and publication gate remain.
Only a current passing D release can appear in the browser. An audit failure blocks
publication; the runner does not automatically weaken findings to get a pass.
There is at most one format-repair attempt per stage, no automatic retry for
connection/usage failures, and a default ten-minute timeout per invocation. One
review runs at a time. A single clip needs four model calls; five clips need eight,
plus any bounded format repairs. Usage varies with footage and reasoning.

Closing or cancelling terminates the running CLI process. Server-side failed
artifacts remain available for diagnosis until explicit cleanup/retry or expiry.
`runner/` inside a review directory contains input manifests, model outputs and
logs. Do not commit these files: they can contain user footage descriptions.

If you see `workspace routing discovery failed`, the CLI could not reach its
ChatGPT workspace. Test `codex exec "Reply only OK"` in your terminal; check your
network and `codex login`. Run `codex doctor --summary --no-color` for diagnostics.
On this Mac the actual cause was TLS `UnknownIssuer`: setting
`CODEX_CA_CERTIFICATE=/etc/ssl/cert.pem` in the project-local `.env` fixed the
secure connection using existing system trusted roots. Certificate verification
remains enabled. This is a per-project setting, not a global trust-store change.
Only use an existing trusted bundle appropriate to your machine; do not copy this
Mac-specific path to other operating systems. A local login success alone cannot establish that a
model request works. Restarting the web server cancels running jobs; retained
browser clips must be explicitly submitted again.

## Optional manual fallback

Set `REVIEW_EXECUTION=manual` in `.env` and restart to use the original teammate
handoff workflow below. This fallback is explicit, never automatic.

## Reviewer handoff

The waiting screen’s **Reviewer handoff** disclosure shows the review ID. Files
are in `.local/reviews/<review-id>/`. Start with that directory’s `REVIEW.md` and
`session.json`; `povN-task.json` points to each actual Stage A job.

From the repository root, activate the environment and set these paths to the
actual values shown in the UI (placeholders below are not executable examples):

```bash
source .venv/bin/activate
review_root="$PWD/.local/reviews/REPLACE_WITH_REVIEW_ID"
review_config="$review_root/config/run.json"
```

For each supplied POV, inspect its prepared frames and write the report and review
record using the format in `docs/STAGE_B_ONWARD.md`. Record only frames actually
inspected. Then submit using its real job path:

```bash
python main.py submit --project-root "$review_root" --config "$review_config" \
  --pov pov1 --job /absolute/path/from/pov1-task.json \
  --report /absolute/path/to/pov1-report.md --review /absolute/path/to/pov1-review.json
```

Repeat for every **supplied** POV, then:

```bash
python main.py handoff --project-root "$review_root" --config "$review_config"
python main.py prepare --stage B --project-root "$review_root" \
  --config "$review_config" --accept-limitations
```

Review limitations before using `--accept-limitations`. The task directory contains
`task.md`, `context.json`, response schema, and an import command. Execute and import
B, then C, then independently inspect and import D. Do not copy example facts or
attest to footage you did not inspect. The browser detects the published release.
The existing workflow guide explains exact response formats and failure gates.

## API contract

| Endpoint | Purpose |
| --- | --- |
| `GET /api/health` | Tool/login availability and `execution: codex` or `manual` |
| `POST /api/reviews` | Validate clip metadata, question, alignment; create a job |
| `PUT /api/reviews/{id}/clips/{povId}` | Stream one recording, with byte bounds |
| `POST /api/reviews/{id}/start` | Queue preparation and configured reviewer after all uploads |
| `GET /api/reviews/{id}` | Actual state and audited report, when available |
| `DELETE /api/reviews/{id}` | Cancel and remove job-owned local files |

States: `uploading`, `preparing`, `queued`, `observing`, `comparing`, `judging`,
`auditing`, `awaiting_review` (manual/publication), `complete`, `failed`, `cancelled`.
No percentages are invented for review work. The count of prepared perspectives
reflects finished frame packages.

Reports contain qualitative verdict/confidence, observed facts, interpreted
findings, player summaries, supported coaching, and limitations. `not_established`
findings are explicitly labeled as unestablished hypotheses. Evidence references
carry `{povId, start, end}` in original recording seconds. Backend and browser both
validate evidence availability. There are no blame percentages or mandatory guilty
player. The existing pipeline does not have a separate positive-play field; no
positive play is invented to fill one.

## Pipeline compatibility

The default CLI configuration still requires the original five role-based POVs.
New web configs explicitly set `allow_partial_povs: true`, allowing one to five
unique supplied IDs, including role-independent `pov1`–`pov5`. Existing full-team
fixtures and release gates still pass. The handoff requires exactly one reviewed
report for each configured recording; partial mode never permits an omitted report
for a recording that was supplied.

B/C response maps and schemas are generated from the manifest. D remains an
independent publication gate. Prompt additions instruct reviewers to acknowledge
missing perspectives rather than infer inactivity, and to distinguish unverified
player context from evidence.

## Retention and limitations

Sessions are local and ephemeral; browser reload/server restart does not resume the
current UI session. Originals, aligned copies, and pipeline outputs are ignored by
Git. Cancellation deletes that job’s directory once its active worker/upload exits.
Directories older than 24 hours are cleaned at server startup, and tracked expired
jobs are cleaned when creating a new review. The server retains at most four tracked
jobs and runs at most two preparation workers. This is a local prototype, not a
multi-user upload service.

FFmpeg transcodes the common overlap without audio. Sampling may miss fast actions;
manual event alignment can be wrong. Neither test fixtures nor structural audit
checks establish gameplay accuracy. Real gameplay acceptance still needs the team’s
knowledgeable reviewers and actual fights.

## Checks

```bash
source .venv/bin/activate
python -m pytest -q
npm --prefix web test
npm --prefix web run build
git diff --check
```

New tests cover one through five POVs through real FFmpeg and the A/B/C/D gates,
missing-supplied-report rejection, upload limits/cancellation, incomplete/corrupt
video, missing tools, report publication/revocation, offset mapping, question/mode
transitions, stale browser responses, retry, and perspective switching.


### Codex runner verification

- Automated checks cover the actual A/B/C/D import gates with mocked model
  responses, a failed audit blocking release, cancellation/timeout terminating a
  child process, bounded schema repair, ChatGPT-only login, and API-key exclusion.
- A live 12-second labeled synthetic title card completed all four stages and
  produced an inconclusive report with no asserted gameplay events. This verifies
  the connection and workflow, not Overwatch coaching accuracy.
- Local TLS diagnosis: the default CLI reported `UnknownIssuer`; the existing
  macOS certificate bundle restored a verified WebSocket handshake and inference.

- The supplied real 22.1-second Pharah clip completed through the browser, using
  45 sampled frames. The checked verdict was inconclusive, with three timestamped
  observations and a qualified concern about doorway exposure. Evidence seeking
  to 8.5 seconds and JSON export were verified. This single sample is not an
  accuracy benchmark. The run took about 236 seconds and used 5 model calls
  (including one bounded format repair). Expect minutes, not instant results.
- Full suite: 209 Python tests plus 132 subtests, 10 frontend tests, production
  build, and whitespace checks passed.
