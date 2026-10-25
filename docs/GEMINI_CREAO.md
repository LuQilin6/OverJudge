# Gemini + CREAO migration

This opt-in path keeps S0 video probing and the existing Codex A/B/C/D workflow.
It uses Gemini for five independent video observations and a saved CREAO agent
for timeline reconstruction and judgment. It does not import model output as an
independent D-stage audit or bypass the existing publication gates.

## Configure

1. Keep your existing run configuration and five pre-aligned video paths.
2. In CREAO Agent Builder, use `prompts/creao_judge.md` as investigator instructions.
   Test against a completed `bundle.json`, then save the workflow as an agent with
   **one text input named `prompt`**. Obtain its agent ID and API key.
3. Set `GEMINI_API_KEY`, `CREAO_API_KEY`, and `CREAO_AGENT_ID` in the shell. The
   `.env.example` lists names only; main.py does not automatically load `.env`.
4. Choose a Gemini model available to your account that accepts video via
   `generateContent`. No new Python dependencies are required (stdlib HTTPS).

The provider contracts are checked against the official
[Gemini video documentation](https://ai.google.dev/gemini-api/docs/video-understanding)
and [CREAO hackathon API guide](https://community.creao.ai/AI_hackathon_UCLA2026/tech).
This integration targets CREAO's agent.creao.ai API, not its separate developer v2 API.

## Run

```bash
.venv/bin/python main.py analyze-fight --config config/run.json \
  --model YOUR_GEMINI_MODEL --concurrency 2 --fps 2
```

This uploads each original video with Gemini Files API and restricts analysis to
its shared configured interval via videoMetadata. The five calls are independent,
with a bounded worker pool. All returned event timestamps must use the original
video origin. Higher FPS increases sampling and cost; it does not guarantee fast
abilities are observed. Instructions restrict observations to visuals and ignore
audio; the provider can still receive audio in the uploaded original file.

The CLI prints the attempt directory to stderr before analysis. Each invocation
creates a new attempt and can incur new Gemini charges. There are no automatic
billable retries. Successful remote uploads are deleted in a finally block;
cleanup failures are retained for manual follow-up. A connection failure during
upload can leave a remote file without a known identifier.

After all five valid analyses, the CLI submits CREAO and returns a run ID without
waiting for judgment. Use the returned absolute attempt path:

```bash
.venv/bin/python main.py poll-judge --attempt /absolute/provider/attempt
```

Poll periodically in a separate process or backend job; pending/running states
return immediately after a single status request. Failed/cancelled states return
exit code 1. Invalid judgments return exit code 2 and retain the raw response.
Completed valid judgments create `verdict.json` and `report.md`.

If CREAO submission was interrupted after Gemini finished:

```bash
.venv/bin/python main.py resume-judge --attempt /absolute/provider/attempt
```

This uses the original saved request and idempotency key and does not upload
videos again. A lock prevents concurrent submissions from the same attempt.
Provider-side idempotency retention still governs retries after long delays.

## Evidence and limits

Each attempt stores S0 metadata, original video hashes, individual Gemini prompts,
upload metadata, complete generation responses (including usage metadata),
normalized `analysis.json` and readable summaries, the five-player bundle, CREAO
instructions, agent/run identifiers, and every polling response. Keep these for
sponsor demonstrations. A run ID is retained; obtain a shareable run URL through
CREAO's UI, which also allows inspection of the actual investigation.

All event IDs must be unique within their assigned player, and timestamps must
fall within the shared interval. Every verdict claim needs existing event IDs;
each of five player findings must reference that player's observations. The
bundle hash is checked on resume and polling. These checks establish structural
traceability, not whether an observation is visually true or a claim logically
follows. Empty observations are allowed but prevent a fully cited five-player
verdict; uncertainty must never be filled by fabricating events.

Outputs live under `outputs/{run_id}/providers/{attempt}/`, separate from the
manual workflow's current indexes and audited releases. They are draft reports
with independent gameplay audit PENDING. There is no web server or report UI in
this repository yet; these CLI functions can be called from a backend worker.

## Remaining live acceptance

Credentials and a saved CREAO agent are required before any live result can be
claimed. Run one known fight and one unseen fight, manually verify timestamp
origin, event accuracy, contradictions, uncertainty and verdict support, and save
Gemini usage plus CREAO's agent ID and shared run link. Compare against the Codex
baseline. Tests with mocked providers verify plumbing, not gameplay quality or
live account compatibility.

## Resume an interrupted Gemini attempt

Generation requests now use a configurable 600-second read timeout. Reuse successful
POVs and retry only missing analyses with:

```bash
.venv/bin/python main.py analyze-fight --config config/run.new_set.json \
  --model YOUR_GEMINI_MODEL --gemini-timeout 600 \
  --resume-attempt /absolute/provider/attempt
```

Inputs, shared interval and completed analysis settings must match. Failed POV
artifacts are preserved and retries use fresh subdirectories. A timed-out remote
request may still have run and incurred usage; resuming explicitly submits a new
request for each missing result. Successful local results are reused.

If the selected model repeatedly returns 503, add `--retry-model MODEL_ID` to
an `analyze-fight --resume-attempt` command. The original `--model` still identifies
the completed analyses; only missing POVs use the retry model. Keep both model flags
on subsequent resumes. Each POV request records the actual model used. This can
produce a mixed-model bundle, so retain that fact when evaluating results.
