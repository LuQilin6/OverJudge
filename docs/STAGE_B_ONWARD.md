> Run the commands in this manual guide from `backend/` after activating the
> repository-root `.venv`. The web app uses automatic Codex review by default;
> see [the main README](../README.md) for current setup and folder structure.

# Integrated A/B/C/D workflow and handoff

This branch integrates S0/A with B/C/D from `PROJECT_PLAN.md`. The operator uses
Codex manually. The application does not select a model provider or call an API.
Software checks structure, provenance and release gates; actual observation and
independent evidence review remain necessary.

## Ownership and interfaces

| Area | Modules and artifacts |
| --- | --- |
| S0/A | `intake.py`, `video_inspection.py`, `pov_analysis.py`, `stage_a.py`, A prompt, recordings, manifest, report/review/provenance revisions |
| Shared boundary | `contracts.py`, `handoff.py`, common configuration, CLI and atomic artifact helpers |
| B/C/D | `pipeline.py`, `fusion.py`, `judge.py`, `audit.py`, `artifacts.py`, B/C/D prompts and result revisions |

Coordinate contract changes with the other stage owners. B/C/D read A's original
artifacts; reinspection creates a new upstream revision. Relative paths resolve
from the project containing `config/`; a config outside that directory uses its
containing directory. `--project-root` explicitly selects a project root.

## Shared configuration and S0

Copy `config/run.example.json` to `config/run.json`. Fill in the real run/fight IDs,
common fight interval and the five paths. The example's null end timestamp is
intentionally invalid. Defaults are:

- `output_directory`: `outputs`
- `manifest_path`: `outputs/{run_id}/manifest.json` (optional override)
- `stage_a_handoff_path`: `outputs/{run_id}/handoff.json` (optional override)
- A inspection: `codex_manual`, 2 sampled frames/second, audio inspection disabled
- B/C/D `stage_tools`: `{"method":"manual","tool":"Codex"}`

```bash
source .venv/bin/activate
python main.py validate --config config/run.json
```

S0 requires exactly `tank`, `dps1`, `dps2`, `support1`, `support2`, distinct resolved
video paths and a common interval covered by all five recordings. It saves hashes,
ffprobe metadata, hero names (or `unknown`), errors and limitations. Successful
`coverage_status` is `complete`; unusable coverage is `blocked`. Missing intervals
use `{start_timestamp, end_timestamp}`. Native handoff requires all five complete.

S0 top-level status is PASS or BLOCKED. Metadata does not establish synchronization,
frozen-frame absence or full decode integrity. Inputs must already be aligned;
no automatic offsets or timestamp transformations are performed.

## Prepare and inspect Stage A

```bash
python main.py run --stage A --pov tank --config config/run.json
```

The command prints `job_path`, prepares timestamped images, and exits 1 / BLOCKED
until actual visual inspection is completed. Its job has only the assigned POV,
the shared prompt, source metadata and a sampling manifest. A one-POV pilot can
prepare a valid input while full intake remains blocked; it cannot export a
five-report handoff until S0 passes.

Open a separate Codex context for each POV. Read its `prompt.md`, inspect the
actual frames/video, and write neutral Markdown with these nonempty headings:

1. Metadata
2. Gameplay Context
3. Timestamped Behavioral Timeline
4. Player Information State
5. Cross-POV Verification Questions
6. Neutral Behavioral Summary
7. Coverage and Limitations
8. Agent Handoff

The versioned A prompt gives the exact Metadata and Handoff bullet fields. Every
event has a real `### [start–end s]` heading, observed action, immediate outcome,
evidence, quality and inference/unknown fields. The report cites only its assigned
POV and explicitly records coverage and unavailable information. Unknowns are
allowed; unavailable visual access must be BLOCKED rather than a fictional report.

Evidence is `POV_ID@start-end`, for example `tank@12.0-13.4`, always original
aligned-video seconds. Each window is positive, inside the common fight interval
and available recording, and avoids missing coverage. B/C/D retain exact original
source windows. Numeric spelling is normalized without shifting time.

Record only frame timestamps you actually inspected. Review JSON has exactly:

```json
{
  "reviewer": "actual reviewer name",
  "model_or_tool": "actual model/tool and version",
  "reviewed_frame_timestamps": [12.0, 12.5],
  "audio_inspected": false,
  "limitations": ["Sampled frames only; audio unavailable."]
}
```

Replace example timestamps with available frames. Every event and its cited
window must overlap a reviewed frame. This minimum provenance check cannot prove
continuous coverage or that the reviewer watched it. Request denser sampling for
fast or ambiguous events. Audio inspection is currently unsupported.

```bash
python main.py submit --config config/run.json --pov tank \
  --job /absolute/job_path --report /absolute/report.md --review /absolute/review.json
```

Repeat for all five POVs. Submission stores immutable report, review and provenance
files. Reusing the same report text with a different review produces a new
revision. Structural import remains `PASS_WITH_LIMITATIONS` with human evidence
audit `PENDING`; it does not establish event accuracy or sufficient coverage.

## Export A to B

```bash
python main.py handoff --config config/run.json
python main.py validate --stage B --config config/run.json --accept-limitations
python main.py prepare --stage B --config config/run.json --accept-limitations
```

`handoff` fixes five selected report revisions from `stage_a_index.json`. It checks
the full S0 gate, original recordings, job/settings/prompt snapshots, frame hashes,
review timestamps, report structure and provenance sidecars. It saves an immutable
snapshot and the current handoff pointer. It preserves all source restrictions
and audit PENDING, and grants no independent audit PASS.

The coordinator reviews those restrictions and passes `--accept-limitations` to
B/C/D prepare and import when proceeding. B consumes original Markdown together
with review/provenance and their hashes, rather than relying on a self-reported
Markdown PASS. Updated A reports/reviews revoke downstream current pointers and
make the old handoff stale. Export a fresh handoff before preparing a new task.

## Execute B/C/D manually

Their `prepare` commands print `request_path`, containing:

- `task.md`, versioned `prompt.md` and immutable request metadata
- `context.json`: manifest, original A reports, review/provenance, dependency hashes and prior results
- `response_schema.json`: field guide or JSON Schema and envelope instructions
- `response.example.json`: format only, with explicit placeholders/example content
- `clip_index.json`: D's real extracted windows and hashes; empty for B/C
- D evidence clips and bundle hashes

Use a fresh Codex context per stage. Follow `task.md`, read the actual inputs and
save a response outside immutable task files. The envelope is:

```json
{
  "execution": {
    "tool": "actual tool and version",
    "model": "actual model/version, or unknown",
    "operator": "actual operator/reviewer name"
  },
  "result": {}
}
```

Populate `result` using the stage-specific contract; the example is not an
analysis. B reconstructs events neutrally while preserving source conflicts. C
considers all five players with evidence, player knowledge, alternatives and
uncertainty; it may return `inconclusive`. D independently opens the indexed video
windows and verifies identity, timestamps, abilities, hindsight and source
consistency. Reviewer attestations are not independently machine-verifiable.

```bash
python main.py import-result --stage B --config config/run.json \
  --request /absolute/B_request --response /absolute/B_response.json --accept-limitations
python main.py prepare --stage C --config config/run.json --accept-limitations
# Execute and import C with its own request and response, then:
python main.py prepare --stage D --config config/run.json --accept-limitations
# Actually inspect and import D, then:
python main.py status --config config/run.json
```

`run --stage B|C|D` aliases task preparation. Successful imports/handoffs and B/C/D
preparation return 0. A inspection-pending preparation, blocked S0 intake and an
imported failed D audit return 1. Malformed or blocked handoffs return 2.

Scientific uncertainty and a justified inconclusive verdict are valid outputs.
Final reports retain A coverage restrictions, B unresolved conflicts and C/D
qualifications. If C establishes no cited claim, D explicitly reviews abstention
against existing A observation intervals (`audit_scope`) without inventing C facts.

## Storage and invalidation

A preserves upstream paths under `outputs/{run_id}/`:

- `manifest.json`
- `stage_a/{pov}/{cache_key}/{job_revision}/`
- `pov_reports/{pov}/{report_review_job_hash}/`
- `stage_a_index.json`
- `handoffs/{hash}/handoff.json` plus current `handoff.json`

Changed input, prompt, sampling or missing/modified frames require a new job; old
evidence is retained. Unique atomic temp files and per-run locks protect concurrent
POV writes and submissions. An identical repeated submission is idempotent.

B/C/D requests/results/releases are under `outputs/runs/{run_id}/`.
`run_metadata.json` indexes current revisions; report names are `fusion.md`,
`verdict.md`, `qa_report.md`, `final_report.md`. All historical files remain intact.
Cache keys include manifest, A report/review/provenance/job/frame hashes, upstream
result/metadata hashes, current prompt and tool configuration. Changing C's prompt
preserves B but invalidates C/D. Imports reject altered tasks, stale dependencies
and superseded requests.

Result commits and releases hold A's selection lock through final source checks,
save and publication, then compare downstream revisions. A changed selection
revokes B/C/D pointers under the same lock. This prevents concurrent A submission
from reviving or publishing results based on superseded evidence.

For explicitly supplied legacy flat reports, `manifest_path` and
`pov_reports_directory` remain supported when no native A run exists. Native A
jobs/index require their verified handoff. Old upstream jobs lacking frame hashes
or full provenance must be re-prepared and resubmitted; migration never fabricates
missing inspection evidence or destroys their history.

## Audit and validation

D checks original hashes, probes actual video durations, extracts original-time
windows, fully decodes them and records FFmpeg/ffprobe versions. Clip local zero
corresponds to the cited window's original start. Import, cache reuse and `status`
recheck original/clip hashes. Missing or changed evidence revokes the current
release. Primary, secondary and shared adverse findings all require review.
Unreviewed required evidence, identity/timing failures, unsupported findings or
open critical/major issues yield FAIL. A failed review is saved without a current
final report. Revise its owning stage and rerun descendants.

Manual model work has no automatic API retries. Tool errors remain visible.
Historical final reports are retained for provenance; consult the current index
or `status` rather than treating an archived final as the current verdict.

```bash
python --version
python -m pytest -q
git diff --check
```

Tests cover the full synthetic A-to-D workflow, provenance, stale dependencies,
malformed references, five-player coverage, conflicts, abstention, concurrency
and release gates with actual FFmpeg extraction. They do not measure gameplay
event recall/precision, timing accuracy or tactical correctness. The plan's
human-reviewed pilot and three-fight benchmark remain product acceptance work.
