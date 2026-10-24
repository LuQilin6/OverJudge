# Overwatch Multi-POV Teamfight Judge — Project Plan

**Version:** 0.2 (MVP — pre-aligned inputs)  
**Status:** Proposed  
**Primary language:** English for machine-readable prompts and agent handoffs; user-facing verdict may be Chinese.  
**Owner:** Project coordinator agent  
**Core principle:** Evidence before judgment.

## 1. Product objective

Given five synchronized first-person Overwatch 2 recordings from the **same team and same fight**, reconstruct what each player did and explain the strongest evidence-supported causes of a lost teamfight. Produce a readable, timestamped verdict that can be challenged and audited. The first implementation uses **Codex-led video analysis** because initial user testing favored it; the implementation must document the actual visual inputs and tools used rather than assuming Codex natively ingests all video formats.

### In scope (MVP)
- One teamfight per run; five POV recordings; one game (Overwatch 2).
- Independent **natural-language** POV reports, with timestamps and evidence.
- Shared timeline and conflict-aware fusion.
- Evidence-grounded blame attribution with explicit uncertainty and a possible **inconclusive** verdict.
- CLI execution, cached intermediate artifacts, pre-aligned input validation, and human evaluation.

### Out of scope (MVP)
- Full-match automated fight segmentation, live gameplay coaching, training a game-specific model, precise damage reconstruction, win-probability estimates, automatic causal proof, public player rankings, and a polished frontend.

### Non-negotiable constraints
1. Stage A is descriptive, **not evaluative**.
2. Every important claim references a source POV and timestamp range on the shared video timeline.
3. Distinguish `observed`, `inferred`, `unknown`, and `conflicted`.
4. Do not infer off-screen inactivity or assume players knew what other POVs show.
5. The final judge may abstain; do not force one scapegoat or numerical blame percentages.
6. An LLM self-reported confidence label is not a calibrated probability.
7. Preserve raw reports and originals; never overwrite source evidence.

## 2. Definitions and conventions

| Term | Definition |
|---|---|
| POV | A single player's first-person recording |
| Timestamp | Seconds elapsed since the beginning of the pre-aligned videos; the same timestamp denotes the same in-game moment across all five POVs |
| Evidence reference | `POV_ID@start-end` in aligned-video seconds (e.g. `tank@12.0-13.4`) |
| Observation | Directly visible or audible in the supplied recording |
| Inference | Plausible interpretation requiring reasoning beyond direct observation |
| Candidate mistake | A potentially avoidable action or omission; not necessarily causal |
| Causal contributor | A supported factor that plausibly changed the fight's trajectory |
| Inconclusive | Available evidence cannot justify a reliable verdict |

**Input synchronization assumption:** All five input POV videos are pre-aligned and begin at the same in-game moment. A timestamp of `t` seconds refers to the same in-game time across all five videos. The pipeline assumes this alignment is correct and does not perform automatic synchronization, anchor matching, or offset correction.

**Time convention:** Use one field, `timestamp`, measured in decimal seconds elapsed since the beginning of the aligned videos. For intervals, use `start_timestamp` and `end_timestamp` with the same convention. Human-readable Markdown may additionally show `MM:SS.s`. Do not claim finer temporal precision than the video inspection supports.

## 3. Architecture and artifact flow

```text
inputs/videos/{tank,dps1,dps2,support1,support2}.mp4
             │
             ▼
S0: Intake and pre-aligned video validation
             │ config/manifest.json
             ▼
A1–A5: Independent Codex-led visual analysis (parallel)
             │ outputs/pov_reports/{pov_id}.md
             ▼
B: Cross-POV reconstruction (LLM, shared timestamps)
             │ outputs/fusion.md
             ▼
C: Evidence-grounded tactical judge (separate LLM call)
             │ outputs/verdict.md
             ▼
D: Evidence audit, evaluation, release
               outputs/qa_report.md + outputs/final_report.md
```

Stage A can use Codex to inspect frames, clips, timestamps, HUD, and audio via available local tooling. The pipeline must log its actual inspection method (frame sampling rate, clips reviewed, tools/models). If Codex cannot reliably access the needed visual information, stop with an explicit limitation rather than hallucinating an analysis.

## 4. Agent roles and ownership

| Agent | Owns | Inputs | Outputs | Must not do |
|---|---|---|---|---|
| Coordinator | Scheduling, config, dependencies, acceptance gates | User request, manifest | Run plan, status, artifact index | Fabricate evidence or bypass failed gates |
| Intake Validator | File integrity, coverage and recording metadata | 5 pre-aligned videos | `manifest.json` | Modify timing or claim to verify synchronization from metadata alone |
| POV Analyst ×5 | Independent factual video descriptions | Exactly one POV, Stage A prompt, shared timestamp convention | Five `pov_reports/*.md` | Read other POV reports or assign blame |
| Fusion Analyst | Event matching, cross-POV reconstruction | Five reports, shared timestamp convention | `fusion.md` | Resolve conflicts without evidence or assign blame |
| Judge | Tactical critique and causal hypotheses | `fusion.md`, cited excerpts from original reports | `verdict.md` | Treat hypotheses as proven or force a winner |
| Evidence Auditor | Trace citations to clips, flag contradictions | All artifacts and original videos | `qa_report.md` | Quietly edit original observations |
| Report Publisher | Format validated conclusions | Verdict, QA report | `final_report.md` | Remove uncertainty or unsupported-claim warnings |

**Isolation rule:** Each POV analyst works in a separate context with access only to its assigned video, configuration, and common prompt. Agents communicate via saved artifacts, not informal assumptions.

## 5. Stage S0 — Intake and validation of pre-aligned inputs

**Objective:** Ensure the five recordings are usable and refer to the same fight.

**Input:** Five user-supplied, pre-aligned video files that start at the same in-game moment; optional hero/role mapping; optional common fight interval expressed in aligned-video seconds.

**Tasks:**
1. Validate existence, readability, duration, resolution, fps, and audio presence using `ffprobe`.
2. Assign stable IDs: `tank`, `dps1`, `dps2`, `support1`, `support2`; record actual hero if known, otherwise `unknown`.
3. Check that all videos cover the requested fight interval, and flag truncated, missing, frozen, or unreadable segments.
4. Check durations and frame rates; report differences without assuming that equal durations or frame rates prove synchronization.
5. Preserve the original aligned start point. Do not independently trim or shift a single POV; if a common fight segment is extracted, use the identical start and end timestamps for every POV and preserve originals.
6. Create a reproducible manifest with hashes, paths, metadata, coverage checks, and any common extraction interval.

**Output:** `config/manifest.json`, optional equally trimmed working clips under `work/clips/`.

**Required fields (`manifest.json`):** `run_id`, `game`, `fight_id`, `prealigned_input_assumed` (`true`), `fight_start_timestamp`, `fight_end_timestamp`, `videos[]` containing `pov_id`, `path`, `sha256`, `duration_seconds`, `fps`, `width`, `height`, `audio_present`, `hero`, `coverage_status`, `missing_intervals` (if any). If derived clips are created, record a single common extraction interval for all five POVs.

**No `sync.json` is generated.** Alignment is an upstream input guarantee, not a pipeline output. `prealigned_input_assumed: true` records the contract; it does not imply independent verification.

**Acceptance criteria:**
- Exactly five readable POVs; no missing file; stable ID mapping.
- One common fight interval is defined and covered by all five POVs.
- Metadata checks report durations, fps, and any missing/unreadable intervals.
- No automatic synchronization, anchor search, or offset computation occurs.
- If any input is missing, unreadable, or fails to cover required fight events, mark S0 **BLOCKED** or explicitly flag limited coverage; do not silently proceed.
- If obvious evidence contradicts the pre-alignment assumption, flag the input contract as violated and request corrected files rather than shifting footage automatically.

## 6. Stage A — Independent single-POV observation

**Objective:** Convert one video into a neutral, timestamped **natural-language** behavior report. Five parallel agents each run once per POV.

**Input:** One pre-aligned POV video/clip; `pov_id`; role/hero if known; shared timestamp convention; `prompts/stage_a.md`.

**Tasks:**
1. Record inspection coverage: clip ranges reviewed, frame/clip sampling, audio/HUD inspection, inaccessible intervals.
2. Identify visible context (map, mode, hero, objective) only when supported.
3. Write a chronological narrative of movement, positioning, attacks/heals, abilities, deaths, objective changes, and teammate/enemy interactions.
4. For each meaningful event, provide a **timestamp range** in aligned-video seconds, observation, immediate visible outcome, and evidence quality.
5. Describe information available to the POV player at critical moments (HUD, visible teammates/enemies, audio, kill feed).
6. List cross-POV questions and uncertainty without tactical grading.

**Output:** `outputs/pov_reports/{pov_id}.md` using the mandatory sections below.

```markdown
# POV Report — {pov_id}
## Metadata
- Video: ...
- Hero: ... (or unknown)
- Aligned-video interval: ...
- Inspection coverage / method: ...
## Gameplay Context
...
## Timestamped Behavioral Timeline
### [12.0–13.4 s]
- Observed: ...
- Immediate outcome: ...
- Evidence: tank@12.0-13.4
- Evidence quality: high/medium/low
- Inference/unknown: ...
## Player Information State
...
## Cross-POV Verification Questions
...
## Neutral Behavioral Summary
...
## Coverage and Limitations
...
```

**Acceptance criteria:**
- All five reports exist and use the same headings.
- Every major event has an evidence reference and time interval.
- Reports describe actions without `bad play`, `throw`, `blame`, or similar judgment labels.
- Unknown heroes, outcomes, and off-screen actions are explicitly marked unknown.
- Every report states its actual video inspection coverage and gaps.
- **Evaluation target on a hand-labeled test clip:** ≥ 80% recall of clearly visible major events and ≤ 10% unsupported factual claims. These are project targets, not assumed model performance.

**Failure policy:** If the analyst cannot visually inspect the video, or coverage is too sparse to support a report, output `BLOCKED` with missing capabilities and do not generate a fictional narrative.

## 7. Stage B — Multi-POV fusion

**Objective:** Combine five neutral reports on their existing shared timeline without assigning blame.

**Input:** Five `pov_reports/*.md`, `config/manifest.json`, `prompts/stage_b.md`.

**Tasks:**
1. Use timestamps directly as supplied; all five videos share the same zero point. Never calculate offsets or transform timestamps.
2. Group observations that refer to the same underlying event; retain every source citation.
3. Produce a time-indexed five-player action matrix; distinguish `not observed` from `not participating`.
4. Reconstruct key fight phases: setup, initiation, first major exchange, turning points, outcome.
5. Separate reconstructed global knowledge from each player's contemporaneous visible/audible information.
6. Explicitly enumerate corroborated, single-source, conflicting, and unresolved observations.
7. Request targeted Stage A reinspection when a critical conflict affects later judgment; log all revisions.

**Output:** `outputs/fusion.md`.

**Required sections:** Shared Context; Input Coverage and Alignment Assumption; Unified Timeline; Five-Player Action Matrix; Team Coordination; Turning Points; Player Knowledge Limits; Conflicts and Uncertainties; Evidence Index; Neutral Summary.

**Acceptance criteria:**
- All five players represented in the action matrix at each key fight phase; unknown intervals are allowed.
- Every consequential event cites at least one `POV_ID@start-end` source.
- All event intervals and citations use the single shared `timestamp` convention.
- Conflicting evidence remains flagged, not arbitrarily reconciled.
- No player blame or tactical grades.
- Every critical uncertainty is either resolved with cited evidence or passed to Stage C as unresolved.

## 8. Stage C — Tactical judgment and blame attribution

**Objective:** Identify the most defensible contributing factors to the defeat, distinguishing individual execution, decision-making, coordination, enemy outplay, and missing evidence.

**Input:** `fusion.md`, cited original POV report excerpts, input coverage limitations from `manifest.json`, `prompts/stage_c.md`.

**Tasks:**
1. Establish the fight outcome and starting constraints (numbers, positioning, resources where observable).
2. Enumerate candidate mistakes for all five players; explicitly allow `no supported mistake`.
3. For each candidate: quote/point to evidence, describe what was knowable to that player, propose a realistic alternative, and discuss plausible consequences.
4. Trace possible causal chains; distinguish temporal correlation from causal contribution.
5. Evaluate alternative explanations: earlier disadvantage, enemy outplay, forced decisions, shared coordination breakdown.
6. Return a ranked list **only if** evidence supports meaningful distinctions. Otherwise state `inconclusive` or shared responsibility.
7. Generate specific, actionable improvements and identify clips needed to settle remaining disputes.

**Output:** `outputs/verdict.md`.

**Required sections:** Fight Summary; Confirmed Facts; Candidate Mistakes; Causal Analysis; Alternative Explanations; Player-by-Player Findings; Verdict or Inconclusive; Top 3 Evidence Clips; Actionable Lessons; Confidence and Limitations.

**Acceptance criteria:**
- Every adverse finding references at least one concrete timestamped observation.
- All five players are evaluated, including justified `no finding` outcomes.
- No player is blamed solely for dying first, low damage, or being off-screen.
- No unsupported claim that a player knew something shown only in another POV.
- Includes a plausible alternative explanation and uncertainty discussion.
- Explicit `inconclusive` path is tested.
- Numerical percentages are disabled in MVP; qualitative labels (`primary`, `secondary`, `shared`, `not established`) are permitted.

## 9. Stage D — Evidence audit, QA, and publishing

**Objective:** Verify that the verdict is traceable to footage and publish only supported findings.

**Input:** Original pre-aligned videos, `manifest.json`, five reports, fusion, verdict.

**Tasks:**
1. Extract or open the cited video windows for every primary and secondary adverse finding.
2. Check timestamp accuracy, actor identity, ability identification, and whether a claim is directly visible or inferred.
3. Check whether the verdict misuses hindsight or contradicts a source report.
4. Produce an issue log: `severity`, `claim`, `source`, `finding`, `required_fix`, `owner`.
5. If critical errors are found, return work to the owning stage and rerun dependent stages.
6. Publish a concise human-readable verdict with links or local paths to evidence clips.

**Output:** `outputs/qa_report.md`, `outputs/final_report.md`, optional `outputs/evidence_clips/*.mp4`.

**Acceptance criteria:**
- 100% of primary adverse findings have a valid, reviewable evidence interval.
- Zero known critical identity/timestamp errors remain in the released report.
- Unsupported or unverified claims are removed, qualified, or marked unresolved.
- QA report explicitly records `PASS`, `PASS_WITH_LIMITATIONS`, or `FAIL`.
- `FAIL` blocks publication as a definitive verdict.

## 10. Prompt contracts

Prompts are separate versioned files:

- `prompts/stage_a.md`: strict observer role; timestamped narrative; source references; information state; no blame.
- `prompts/stage_b.md`: neutral fusion; source-preserving cross-checks; player knowledge; unresolved conflicts; no blame.
- `prompts/stage_c.md`: tactical judge; evidence → context → alternatives → plausible causal effect; abstention.
- `prompts/stage_d.md`: independent auditor; verify claims against clips; escalate failures.

**Prompt requirements:** Explicit role, task, allowed inputs, mandatory headings, prohibited behaviors, and uncertainty/abstention rules. Include a `prompt_version` in every output metadata section. Never insert another agent's conclusions into Stage A.

## 11. Runtime interface and reproducibility

Suggested CLI:

```bash
python main.py validate --config config/run.json
python main.py run --config config/run.json
python main.py run --stage A --pov tank --config config/run.json
python main.py run --stage B --config config/run.json
python main.py run --stage C --config config/run.json
python main.py run --stage D --config config/run.json
```

**Configuration:** pre-aligned input video paths, POV IDs, optional hero names, one shared fight interval, model/tool choices per stage, prompt paths, output directory, max retries, and inspection settings. API keys come from environment variables only.

**Run metadata:** Save model/tool versions, prompt hashes, input hashes, sampling parameters, start/end times, stage status, error logs, and artifact paths in `outputs/run_metadata.json`.

**Cache key:** stage + source artifact hashes + prompt version + model/tool config. Changing Stage C prompt must not force video reanalysis; changing the common fight interval or input videos must invalidate affected downstream artifacts.

**State transitions:** `PENDING → RUNNING → PASS | BLOCKED | FAIL`; dependent stages run only when upstream inputs pass or have explicitly approved limitations. Retry transient failures at most twice with backoff; never conceal persistent failures.

## 12. Proposed repository structure

```text
overwatch-judge/
├── README.md
├── PROJECT_PLAN.md
├── requirements.txt
├── .env.example
├── config/
│   ├── run.example.json
│   ├── manifest.json
├── inputs/videos/              # gitignored, original recordings
├── work/clips/                 # gitignored, derived clips
├── prompts/
│   ├── stage_a.md
│   ├── stage_b.md
│   ├── stage_c.md
│   └── stage_d.md
├── src/
│   ├── intake.py
│   ├── video_inspection.py
│   ├── pov_analysis.py
│   ├── fusion.py
│   ├── judge.py
│   ├── audit.py
│   ├── artifacts.py
│   └── cli.py
├── tests/
│   ├── test_input_coverage.py
│   ├── test_evidence_refs.py
│   ├── test_stage_gates.py
│   └── fixtures/
└── outputs/                    # gitignored run artifacts
    ├── pov_reports/
    ├── fusion.md
    ├── verdict.md
    ├── qa_report.md
    ├── final_report.md
    ├── evidence_clips/
    └── run_metadata.json
```

## 13. Evaluation plan

Create a small manually reviewed benchmark with at least **three fights** (preferably 15 POV clips total). Include a straightforward fight, a chaotic fight with visual clutter, and a fight with disputed responsibility. For each fight, manually annotate 10–20 major events, time windows, hero/actor identities, and the evidentiary basis for any tactical critique. Human disagreement should be recorded, not suppressed.

| Metric | Definition | MVP target |
|---|---|---|
| Event recall | Correctly identified ground-truth major events / all labeled major events | ≥ 80% |
| Event precision | Supported extracted major events / all extracted major events | ≥ 90% |
| Timestamp error | Absolute deviation from manually labeled event time | Median ≤ 1.0 s |
| Unsupported factual claim rate | Unverifiable/contradicted factual claims / audited factual claims | ≤ 10% |
| Primary finding evidence coverage | Primary adverse findings with reviewable citations / all primary findings | 100% |
| False-confidence audit | Cases where model states certainty despite missing/contradictory evidence | 0 critical cases |
| Input coverage | Required fight interval readable in all five POVs | 100% or explicitly flagged/blocked |
| Judge usefulness | Human reviewers rating verdict actionable and grounded | ≥ 4/5 median (exploratory) |

**Evaluation protocol:** Score Stage A independently before reviewing Stage C. Do not use the judge's own output as ground truth. Compare one-POV vs five-POV judgments on the same fights and document whether added perspectives resolve ambiguity. Avoid claiming causal correctness solely from human preference ratings.

## 14. Milestones and completion gates

| Milestone | Deliverables | Definition of done |
|---|---|---|
| M0: Repo scaffold | Config, CLI, prompts, tests, logging | `validate` works and outputs are reproducible |
| M1: Single POV | S0 + Stage A for one clip | Neutral timestamped report; manually reviewed evidence |
| M2: Five POVs | Stage A ×5 on pre-aligned inputs | Five isolated reports using the same timestamp convention |
| M3: Fusion | Stage B report | Action matrix, citations, and unresolved conflicts present |
| M4: Judge | Stage C verdict | Evidence-grounded findings and inconclusive path work |
| M5: Audit | Stage D and evaluation results | Critical findings audited; release gate passed |

**Priority:** M0 → M1 → M2 → M3 → M4 → M5. Do not optimize UI or ranking algorithms before M1 validates that visual observations are reliable.

## 15. Risks and mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| Codex cannot inspect video reliably | Fabricated/partial Stage A | Explicit inspection manifest, frame/clip tools, fail-closed behavior |
| Fast abilities missed by sparse sampling | Wrong event timeline | Targeted high-frequency clip reinspection |
| Upstream alignment assumption is violated | False ordering and causality | Flag suspicious cross-POV timing; request corrected pre-aligned inputs, never auto-shift |
| Natural-language compression loses detail | Wrong fusion/judgment | Timestamped evidence paragraphs, original reports retained |
| Five POVs contain contradictory observations | Hallucinated consensus | Conflict ledger and reinspection requests |
| Hindsight bias | Unfair blame | Per-player information state and alternatives |
| Model overstates causal certainty | Misleading verdict | Abstention, alternative hypotheses, qualitative findings |
| Evaluation lacks reliable ground truth | Inflated performance claims | Human-labeled events, inter-reviewer disagreements |
| Large video/context cost | Slow or expensive runs | Trim fights, cache reports, inspect critical windows |

## 16. Multi-agent handoff protocol

Each agent must write a handoff block at the end of its artifact:

```markdown
## Agent Handoff
- Stage: ...
- Status: PASS / PASS_WITH_LIMITATIONS / BLOCKED / FAIL
- Inputs consumed: ...
- Outputs produced: ...
- Prompt/model/tool versions: ...
- Evidence coverage: ...
- Unresolved questions: ...
- Known limitations: ...
- Recommended next action: ...
```

**Agent behavior rules:**
- Read this plan and the stage-specific prompt before beginning work.
- Never silently change schemas, paths, or timestamp conventions.
- If an input is absent, request it or mark the stage blocked.
- Never claim to have watched frames that were not actually inspected.
- Keep factual observations separate from tactical hypotheses.
- For disputed findings, cite the exact source intervals and request reinspection.
- Only the coordinator may approve proceeding with documented limitations.
- Agents must not silently rewrite another agent's source artifact; create a revision with provenance.

## 17. Open decisions (coordinator to resolve)

1. Which exact Codex workflow and local visual inspection tools will Stage A use?
2. What is the preferred recording format, clip duration, and acceptable latency/cost?
3. What upstream process guarantees that all five videos start at the same in-game moment, and who is responsible for correcting misaligned uploads?
4. Which LLM will run Stage B and Stage C, and how will outputs be versioned?
5. Should final reports be Chinese, English, or bilingual?
6. Will voice chat be included? If yes, how will privacy and consent be handled?
7. How should users challenge a verdict and request evidence reinspection?

## 18. Immediate next tasks

1. Create the repository skeleton and place this document at `PROJECT_PLAN.md`.
2. Implement S0 file, duration, frame-rate, and fight-coverage validation, with unit tests. Do not implement offset conversion.
3. Draft the Stage A prompt from the requirements above.
4. Run Stage A on **one 20–40 second clip**, verify the model actually inspected the footage, and manually audit ten events.
5. Fix Stage A until the observations are useful before parallelizing to five POVs.

**Project success criterion:** A reviewer can trace each meaningful claim in the final teamfight verdict back to a specific video interval, understand the limitations of that evidence, and see why alternative explanations were considered.
