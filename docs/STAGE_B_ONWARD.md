# Stage B/C/D development and upstream handoff

This branch implements the downstream part of `PROJECT_PLAN.md`. The operator
uses Codex manually; the program does not choose a model provider or call an API.
Each stage gets a saved task, returns JSON, and passes contract/provenance checks.
Stage D additionally requires actual independent video inspection. A passing
software gate cannot prove that a reviewer watched the footage or that a causal
hypothesis is correct.

## Ownership and interfaces

| Owner | Modules and artifacts |
| --- | --- |
| S0/A teammate | `intake.py`, `video_inspection.py`, `pov_analysis.py`, Stage A prompt, original recordings, S0 manifest, five neutral Markdown reports |
| B/C/D branch | `contracts.py`, `fusion.py`, `judge.py`, `audit.py`, `artifacts.py`, `pipeline.py`, CLI, B/C/D prompts and downstream tests |

`contracts.py` describes the boundary; changes to this file or the handoff format
must be coordinated. Input reports and videos are read only. A reinspection
requires a revised upstream artifact, not an edit made by B/C/D. All paths in the
configuration and manifest are relative to the repository root unless absolute;
`--project-root` selects another root for fixtures or another checkout.

## Upstream requirements

Copy `config/run.example.json` to `config/run.json`. Fill in the real run/fight IDs
and common fight interval. The configuration and manifest must agree on `run_id`,
`fight_id`, `game`, alignment assumption, and start/end timestamps. The example's
null end time deliberately does not pass validation. Defaults:

- `manifest_path`: `config/manifest.json`
- `pov_reports_directory`: `outputs/pov_reports`
- `output_directory`: `outputs`
- B/C/D `stage_tools`: `{"method":"manual","tool":"Codex"}`

The manifest follows the fields in PROJECT_PLAN §5. It must contain exactly
`tank`, `dps1`, `dps2`, `support1`, `support2`, unique recording paths, SHA-256,
positive duration/fps/dimensions, boolean audio presence, and a hero or `unknown`.
This implementation makes these previously unspecified values explicit:

- `coverage_status`: `complete` or `limited`. Blocked/unreadable input must not
  be handed off as passed. Complete means the full common interval is covered.
- `missing_intervals`: a list of `{start_timestamp, end_timestamp}` in original
  aligned-video seconds; optional when empty. A citation overlapping a gap fails.
- Optional top-level `status`: `PASS` or `PASS_WITH_LIMITATIONS` (default `PASS`).
- Inputs are already aligned: `prealigned_input_assumed` must be `true`. No
  synchronization, timestamp offsets, or automatic realignment occurs here.

Each `{pov_id}.md` must have these nonempty level-two headings:

1. Metadata
2. Gameplay Context
3. Timestamped Behavioral Timeline
4. Player Information State
5. Cross-POV Verification Questions
6. Neutral Behavioral Summary
7. Coverage and Limitations
8. Agent Handoff

Metadata must contain `- prompt_version: ...` and
`- Inspection coverage / method: ...` describing actual coverage/tools. Each
timeline event is a `###` entry with a source citation. A report cites only its
own POV, and its handoff explicitly includes `- Status: PASS` or
`- Status: PASS_WITH_LIMITATIONS`. Other handoff fields follow PROJECT_PLAN §16.
Unknowns are allowed; unavailable video inspection must be `BLOCKED`, never a
fictional observation.

Evidence is `POV_ID@start-end`, for example `tank@12.0-13.4`. Windows must have
positive duration, lie inside the common interval and available recording, and
avoid missing coverage. B/C/D retain exact original source intervals; they
cannot invent a narrower or shifted citation. Numeric spelling is normalized
(`tank@12-13.40` becomes `tank@12.0-13.4`) without changing the timestamp.

## Manual workflow

Use the project Python 3.11 environment. B/C/D have no additional Python package
requirements. D needs FFmpeg and ffprobe on PATH.

```bash
source .venv/bin/activate
python main.py validate --config config/run.json
python main.py prepare --stage B --config config/run.json
```

`prepare` prints `request_path`. That directory contains:

- `task.md` and the versioned `prompt.md`
- `context.json`: manifest, original A reports, source hashes and passed upstream results
- `response_schema.json`: response field guide or JSON Schema and envelope instructions
- `response.example.json`: **format only**, with explicit example/placeholder content
- `clip_index.json`: D's extracted windows and source/clip hashes; empty for B/C
- Request metadata, bundle hashes, and D's evidence clips

Open a fresh Codex context for each stage. Ask it to follow `task.md`, read the
inputs, and save one `response.json` outside the immutable task inputs. The
response envelope is:

```json
{
  "execution": {
    "tool": "actual tool name and version",
    "model": "actual model/version, or unknown",
    "operator": "actual operator/reviewer name"
  },
  "result": {}
}
```

Replace `result` with the stage-specific fields from its task. Do not submit the
example unchanged or describe unseen footage. B is neutral fusion; C is a
separate tactical assessment; D is a separate independent review. For D, Codex or
the reviewer must actually open the indexed clips/frames, evaluate identity,
timing, abilities, player knowledge and source consistency, then record those
checks and exact hashes. Software can verify the files and attestations' shape,
not whether the reviewer actually performed those actions.

```bash
python main.py import-result --stage B --config config/run.json \
  --request /absolute/request_path --response /absolute/response.json
python main.py prepare --stage C --config config/run.json
# Execute and import C with its own task, then:
python main.py prepare --stage D --config config/run.json
# Inspect and import D with its own task, then:
python main.py status --config config/run.json
```

`run --stage B|C|D` is an alias for preparing a manual task; it does not silently
claim model execution. Commands return 0 on successful preparation/import,
1 for an imported failed audit, and 2 for invalid/blocked inputs. A semantic QA
failure is saved with its issue log and does not publish a final report.

If S0/A/B formally handed off `PASS_WITH_LIMITATIONS`, the coordinator must review
the recorded restrictions and explicitly pass `--accept-limitations` at prepare
and import. Required scientific uncertainty and a justified `inconclusive`
verdict are not execution failures. Final reports retain A coverage statements,
B limitations/conflicts and C/D qualifications even if a downstream author
omits them. Critical unresolved B conflicts carry targeted A reinspection
requests; they must remain visible to the judge and auditor.

An entirely uncited C abstention is allowed. D then explicitly reviews that
abstention against A's existing observation intervals, labeled `audit_scope` in
its context, without turning those intervals into invented C factual claims.

## Artifacts, caching and release gates

Artifacts are under `outputs/runs/{run_id}/`, rather than overwriting the plan's
single-run example paths. `run_metadata.json` points to current records. Each
stage request/result and each release has a unique revision directory; result
reports are `fusion.md`, `verdict.md`, `qa_report.md`, and `final_report.md`.

Cache keys include the current stage, manifest and A hashes, upstream result and
metadata hashes, current prompt, and tool configuration. A changed C prompt
preserves B while invalidating C/D; changed A reports or input manifest invalidate
their descendants. A pending rerun revokes the old release pointer immediately.
Imports reject modified tasks, changed source dependencies and superseded
requests. Successful imports atomically revoke descendant pointers while keeping
all historical files. Concurrent imports/publication compare request and stage
revisions to prevent publishing a superseded result.

D verifies original SHA-256 values, probes actual video duration, extracts
original-time windows (clip local zero is the original interval's start), fully
decodes them, and records FFmpeg/ffprobe versions. On import, on D cache reuse,
and in `status`, evidence source and clip hashes are checked again. Changed or
missing evidence revokes the current release. Every primary, secondary and shared
finding requires the same review gate. Any unreviewed required evidence, failed
identity/time check, unsupported finding, or open critical/major issue yields
`FAIL`. A failed review remains inspectable but has no current final report.

If QA fails, revise the owning upstream stage and prepare/import its descendants
again. Automatic model retries are not applicable to this manual workflow;
transient local tool errors are surfaced, not hidden. Historical final reports
remain on disk for provenance and must not be mistaken for the current release;
consult the index or `status`.

## Validation and remaining product evaluation

```bash
python --version
python -m unittest discover -s tests -v
git diff --check
```

Tests cover provenance, malformed references, five-player representation,
conflicts, abstention, hindsight fields, immutable revisions, stale caches,
concurrent publication gates, and actual FFmpeg extraction with synthetic video.
They do not measure observation recall, event precision, timing accuracy on
gameplay, or tactical correctness. S0/A implementation and the plan's three-fight
human-labeled benchmark remain separate work; no benchmark result is claimed.
