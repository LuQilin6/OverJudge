# Shared workflow

Any capable agent or human can perform the manual analysis roles below. The
program prepares and validates files; the coordinator assigns the actual work.
The optional automatic Stage A adapter uses Codex CLI specifically. Replacing
that automatic adapter requires a separate integration; changing a tool label
does not select another model. B/C/D currently use manual file exchange.

## Roles and outputs

| Stage | Work | Output |
| --- | --- | --- |
| S0 | Validate five pre-aligned recordings and a common fight interval | Manifest |
| A, one isolated observer per POV | Actually inspect assigned frames and describe events without blame | Markdown report plus review JSON |
| B | Combine five accepted reports into a neutral timeline | Fusion JSON |
| C | Evaluate evidence, alternatives and all five players; abstain when needed | Judgment JSON |
| D, independent auditor | Actually review every required evidence window | Audit JSON; final report only when the gate passes |

Use English. Keep observed facts, inferences and unknowns distinct. Spectator
overlays and other POVs do not prove what a player knew. A first death or a
teammate complaint alone does not prove responsibility.

## Run the workflow

Work from the repository checkout with Python 3.11.9, the pinned requirements,
FFmpeg and ffprobe. The current runtime requires macOS/Linux because it uses
fcntl locks. Keep the authoritative run at its original location: saved tasks
contain absolute paths and there is no general relocation importer.

Create a fresh run_id and save a separate configuration for it. Fill in the five
POV paths, alignment guarantee and common start/end times. Include the fight's
outcome when evaluating causes. Do not reuse an old run ID with changed inputs.
Commands below use OJ_CONFIG for that config and OJ_ROOT for the checkout root.

```bash
OJ_ROOT="$PWD"
OJ_CONFIG="/absolute/path/to/your/new-run-config.json"
```

1. Validate inputs and prepare each A task:

   ```bash
   python main.py validate --config "$OJ_CONFIG" --project-root "$OJ_ROOT"
   python main.py prepare --stage A --pov tank \
     --config "$OJ_CONFIG" --project-root "$OJ_ROOT"
   ```

   Repeat A preparation for dps1, dps2, support1 and support2. Preparation may
   return exit 1/BLOCKED while awaiting visual inspection. Check job_path and
   the reason before proceeding; preparation is not a completed analysis.

2. Give each observer its own job/prompt/frames. Obtain a final report and review
   file, wait for READY, then submit each pair:

   ```bash
   python main.py submit --pov tank --job /absolute/job_path \
     --report /absolute/report.md --review /absolute/review.json \
     --config "$OJ_CONFIG" --project-root "$OJ_ROOT"
   ```

   A review JSON has exactly reviewer, model_or_tool,
   reviewed_frame_timestamps, audio_inspected and limitations. Record actual
   viewed timestamps; audio_inspected must be false in the current A workflow.

3. Export the verified selection of five reports:

   ```bash
   python main.py handoff --config "$OJ_CONFIG" --project-root "$OJ_ROOT"
   ```

   A's PASS_WITH_LIMITATIONS and audit PENDING remain visible. The coordinator
   reviews these restrictions before choosing --accept-limitations.

4. Prepare, execute and import B, then C, then D in order. For each stage:

   ```bash
   python main.py prepare --stage B --accept-limitations \
     --config "$OJ_CONFIG" --project-root "$OJ_ROOT"
   # Assign the returned request_path to the selected operator.
   python main.py import-result --stage B --accept-limitations \
     --request /absolute/current_request --response /absolute/response.json \
     --config "$OJ_CONFIG" --project-root "$OJ_ROOT"
   ```

   Replace B with C or D only after its upstream imports pass. D preparation
   extracts the required clips. D must actually inspect all required references,
   including the factual basis of an inconclusive verdict.

5. Verify the current release:

   ```bash
   python main.py status --config "$OJ_CONFIG" --project-root "$OJ_ROOT"
   ```

   D FAIL blocks a final report. A passing audit may publish an inconclusive
   report. status can invalidate stale pointers; inspect archived indexes
   directly when browsing historical runs under a changed configuration.

## Replace an agent

Give the new operator the current immutable task and the same role contract.
For A, provide only that POV. For B/C, provide the prepared source documents.
For D, provide the current verdict and indexed visual evidence. The operator
must have actual vision capability for A/D or report BLOCKED.

B/C/D responses use exactly this outer envelope:

```json
{
  "execution": {
    "tool": "Actual tool used",
    "model": "Actual model/version, or unknown",
    "operator": "Actual operator"
  },
  "result": {}
}
```

Use the current task's result fields. B/D provide field guides; C provides a
JSON Schema for result. The generated outer schema file is not itself JSON
Schema. The Python importer remains the authoritative program gate.

Keep inspection_settings.method as codex_manual: it is a required legacy token,
not a vendor selection. Actual identity is recorded in the review or execution
metadata; use that saved metadata rather than a legacy report label to identify
the producer. Changing configured tools/prompts requires fresh preparation. To
deliberately rerun an accepted task with unchanged settings, use --force rather
than accidentally accepting a cached result.

## Minimal assignment template

```text
Role: {stage and assigned POV if A}
Task: {current immutable job/request directory}
Output: {separate writable submission directory}
Use English. Read the assigned prompt and input/output contract.
Use only the inputs permitted for this role; preserve uncertainty.
For A/D, actually inspect evidence and record the real viewing scope.
Write the required output files. Freeze them and send READY with final paths
and SHA-256 hashes. Do not modify them after READY.
Report BLOCKED if required inputs or capabilities are unavailable.
```

READY and isolation are coordinator procedures, not automatic backend checks.
The coordinator rehashes files and verifies the current task before importing.
The automatic Stage A adapter instead uses its own image-only child contract
and validates/submits the response itself; see README for its setup and explicit
--execute invocation. Do not pass this file-based template unchanged to that
child process or invoke automatic model execution as a routine setup check.

Use half-open evidence windows [start, end): a frame at 17.5 needs a window that
includes 17.5, not one ending there. Copy existing citations exactly downstream.
If an audit finds an error, revise the owning stage in a new file, re-import it
and prepare dependent stages again. Never patch a released artifact in place.

Private notes and media must not be bulk-added to Git. The repository includes
versioned example outputs, so an outputs/ path alone does not guarantee privacy.
See docs/STAGE_B_ONWARD.md for detailed CLI and artifact formats.
