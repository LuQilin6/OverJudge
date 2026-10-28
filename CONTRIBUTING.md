# Contributing to Not My Fault

Start with the [README](README.md) and [development guide](docs/DEVELOPMENT.md).
The app has a React frontend, a FastAPI web adapter, and a separate Python
analysis pipeline. Keep those boundaries explicit when making changes.

## Workflow

1. Agree on the change in an issue or with the team. Identify the intended base
   branch before starting; confirm which branch contains the working app.
2. Make a focused branch from that agreed base. Keep unrelated changes separate.
3. Run the checks below and explain the outcome in a pull request. For UI changes,
   include screenshots. For pipeline changes, describe the evidence and failure behavior.
4. Ask a teammate to review before merging. Choose a merge strategy deliberately
   and preserve accurate authorship. Add co-author credit when work was actually shared.

Do not force-push shared branches or replace the default branch without team
agreement. Repository ownership and GitHub contribution attribution are separate;
use an author email associated with your own account.

## Checks

```bash
source .venv/bin/activate
python -m pytest backend/tests -q
npm --prefix frontend test
npm --prefix frontend run build
git diff --check
```

Install FFmpeg/ffprobe to exercise the video tests rather than skip them. Tests
use mocked model responses; a live review consumes the operator’s Codex allowance.
Document any live analysis separately from synthetic test results.

## Evidence and UI changes

- Preserve source identity and timestamp mappings when changing alignment or sampling.
- Keep observations, interpretations, and unknowns distinguishable.
- Retain validation and publication gates when changing the reviewer.
- Check loading, error, cancellation, and retry behavior as well as successful results.
- Use actual names in player-facing prose while preserving canonical identifiers in contracts.

## Files to leave out

Do not commit credentials, `.env`, local recordings, `.local/` review artifacts,
virtual environments, or dependency directories. Historical examples already in
`docs/examples/` are snapshots, not a destination for new runtime output. Use
small synthetic fixtures for reproducible tests.

## Reporting a problem

Include the steps to reproduce, expected and actual behavior, relevant tool
versions, and a redacted error message. State whether the failure happened during
upload, alignment, observation, reconstruction, judgment, or audit when known.
Do not attach private recordings or raw account/session data to a public issue.
