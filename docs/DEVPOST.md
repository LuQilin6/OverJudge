# Not My Fault Devpost submission draft

## Project name

Not My Fault

## Elevator pitch

Turn post-game blame into a courtroom showdown. Upload your Overwatch clips and get an AI verdict with clickable replay evidence. All rise for Judge Murphy. Yes, Sojourn’s dog.

## About the project

### Inspiration

“No way that’s my fault.” One lost Overwatch fight, five different stories. Everyone saw a different angle, and the scoreboard isn’t settling the argument.

So we gave a dog a gavel. Not My Fault lets you bring your clips to Judge Murphy—yes, Sojourn’s dog—and put the play on trial. You make your case; he checks the footage.

Mostly, we wanted a fun way to revisit those moments with friends. If it takes even a little toxicity out of the Overwatch community along the way, even better.

### What it does

Players upload one to five recordings of the same fight, enter their names, and ask a question. For multiple recordings, they mark a shared moment so the app can align the perspectives. They can also explain their plan or add context for the judge to consider alongside the footage.

Not My Fault reviews the supplied footage and produces a verdict, observations, contributing decisions, and coaching. Clickable timestamps take players back to the relevant recording so they can examine the evidence themselves. The report uses their player names and can be downloaded.

Murphy also gives an estimated blame split, with explanations and uncertainty. It’s his take on that moment. When the evidence does not establish fault, the verdict can remain inconclusive—even a dog with a gavel has to admit when he can’t tell.

### How we built it

We built the courtroom interface with React, TypeScript, Vite, and custom CSS. A Python backend using FastAPI coordinates uploads, video preparation, analysis, and report delivery. FFmpeg aligns the recordings and extracts four frames per second.

Our analysis separates four jobs: observe each perspective independently, reconstruct the fight across the available views, assess the decisions, and check the proposed findings against newly extracted evidence frames. These run through fresh OpenAI Codex CLI sessions using a ChatGPT login.

Python validates structured outputs, source hashes, and timestamp bounds. The final report is released only after the evidence check passes. The browser maps citations back to the original recordings for playback.

### Challenges we ran into

Timing was harder than it first appeared. Different recording offsets and tiny duration changes during video conversion could break alignment or produce invalid evidence windows. We added checks against the converted recordings and preserved the mapping back to each original clip.

We also had to balance visual detail against model usage. Two frames per second left large gaps for a fast game, so we increased sampling to four while keeping explicit image limits. More frames still do not guarantee that every action is visible.

Getting Murphy to give useful feedback was another challenge. We wanted specific observations and practical advice, while keeping guesses clearly labeled. We separated what the footage shows from what the judge thinks it means, and kept missing perspectives visible as limitations.

On the engineering side, we added a separate AI evidence check and tightened execution handling so an existing output file cannot be mistaken for a fresh agent response.

### Accomplishments we're proud of

We connected a custom courtroom experience to a working video-review pipeline, with player-specific results and clickable evidence. We built validation and tests around alignment, report contracts, cancellation, and publication rather than relying on a convincing-looking answer alone.

We’re also proud of giving the project a personality. From submitting evidence to pleading your case, the whole flow feels like taking your last teamfight to a tiny dog’s courtroom. And if you disagree with Murphy, the replay is one click away.

### What we learned

A useful AI review needs more than a strong prompt. What the model sees, how time is represented, and how uncertainty reaches the interface all affect the answer. Separating observation from judgment helped us make those decisions explicit.

We also learned how much a theme can help explain a product. Uploads became evidence, questions became a defense, and a multi-step analysis became the court’s review. It gave a fairly technical workflow a simple, playful shape.

### What's next for Not My Fault

We want to add denser sampling around important moments, let the reviewer request a bounded second look, and evaluate its findings against experienced players’ reviews. We also want shared review sessions where teammates can discuss the same evidence together.

The current prototype runs locally and analyzes real uploaded recordings through sampled images. Audio analysis and continuous-video understanding are not part of this build; the evidence check is performed by AI, not a human referee.

## Built with

OpenAI, Codex, Python, FastAPI, Uvicorn, FFmpeg, React, TypeScript, Vite, CSS, Pydantic, Zod, Motion, Lucide, pytest, Vitest, React Testing Library, Git

## Team Hive registration emails

yuchen_han@berkeley.edu
m15395829813@gmail.com
zhipan_xu@berkeley.edu

## Universities or schools

University of California, Berkeley (all team members)

## GoDaddy Registry domains

N/A

## Technology feedback

OpenAI Codex let us build a staged review workflow that accepts image evidence and returns structured reports. The biggest integration challenge was making model output reliable enough for the application: we needed explicit schemas, validation, timeouts, and a separate evidence check. Clearer visibility into image-related usage would help us tune the tradeoff between frame density and cost.

FFmpeg was essential for aligning recordings and extracting evidence frames. We learned to probe the converted files rather than assume their duration exactly matched the browser's metadata. FastAPI and Pydantic helped us keep the upload and report contracts explicit while iterating quickly.

## AI tools used this weekend

OpenAI

## Generative AI implementation

Yes. Not My Fault uses OpenAI models through Codex CLI to inspect sampled Overwatch replay images, reconstruct events across the supplied perspectives, assess contributing decisions, and generate coaching. A separate model session inspects images from the cited evidence windows before the app releases the report. We use generative AI to interpret visual context and explain a play in natural language, while code handles alignment, timestamp validation, and report contracts. The current integration uses a ChatGPT-authenticated CLI rather than a direct API-key integration. We also used Codex to assist development and debugging.

## Gemini Project Number

N/A — leave this optional field blank. We did not use Gemini.

## Submission links

- Published project: https://devpost.com/software/not-my-fault
- Repository: https://github.com/LuQilin6/OverJudge
- Demo video: [Add the video URL.]
- Hosted demo: [Add a public URL if deployed; the current app runs locally.]

## Before submitting

Add the demo-video link. The inspiration and learning sections are a draft in the team's voice; edit them to match your experience.
