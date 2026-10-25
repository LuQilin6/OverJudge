"""Unified intake and manual Codex A/B/C/D command-line interface."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from .contracts import ContractError
from .pipeline import DownstreamPipeline


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="OverJudge intake and Stage A/B/C/D manual Codex workflow")
    subparsers = parser.add_subparsers(dest="command", required=True)
    for name in ("validate", "prepare", "run", "submit", "handoff", "import-result", "status"):
        sub = subparsers.add_parser(name)
        sub.add_argument("--config", default="config/run.json", type=Path)
        sub.add_argument("--project-root", type=Path, help="Base for relative paths; inferred from the config location when omitted")
        if name not in ("status", "submit", "handoff"):
            sub.add_argument("--accept-limitations", action="store_true", help="Coordinator has reviewed and accepts documented upstream limitations")
        if name in ("prepare", "run"):
            sub.add_argument("--stage", default="A", choices=("A", "B", "C", "D"))
            sub.add_argument("--pov", default="tank", choices=("tank", "dps1", "dps2", "support1", "support2"))
        if name == "validate":
            sub.add_argument("--stage", default="S0", choices=("S0", "B"), help="S0 probes all videos; B checks the verified A handoff")
        if name == "import-result":
            sub.add_argument("--stage", required=True, choices=("B", "C", "D"))
        if name in ("prepare", "run"):
            sub.add_argument("--force", action="store_true", help="Prepare a fresh task even when the current result is cached")
        if name == "import-result":
            sub.add_argument("--request", type=Path, required=True)
            sub.add_argument("--response", type=Path, required=True)
        if name == "submit":
            sub.add_argument("--pov", required=True, choices=("tank", "dps1", "dps2", "support1", "support2"))
            sub.add_argument("--job", type=Path, required=True)
            sub.add_argument("--report", type=Path, required=True)
            sub.add_argument("--review", type=Path, required=True)
        if name == "run":
            sub.add_argument("--execute", action="store_true", help="Automatically analyze Stage A images using saved ChatGPT Codex login")
            sub.add_argument("--model", help="Explicit Codex model; omitted uses CLI default")
            sub.add_argument("--codex-timeout", type=int, default=900, help="Maximum Codex execution seconds")
    provider = subparsers.add_parser("analyze-fight", help="Analyze five videos with Gemini and start asynchronous CREAO judgment")
    provider.add_argument("--config", type=Path, default=Path("config/run.json"))
    provider.add_argument("--project-root", type=Path)
    provider.add_argument("--model", required=True, help="Gemini model available to your account")
    provider.add_argument("--concurrency", type=int, default=2)
    provider.add_argument("--fps", type=float, default=2.0)
    provider.add_argument("--retry-model", help="Use a different Gemini model for missing POVs while preserving completed analyses")
    provider.add_argument("--resume-attempt", type=Path, help="Reuse completed POVs and retry only missing analyses")
    provider.add_argument("--gemini-timeout", type=int, default=600, help="Generation read timeout in seconds")
    for command in ("poll-judge", "resume-judge"):
        provider = subparsers.add_parser(command)
        provider.add_argument("--attempt", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.command == "run" and args.execute and args.stage != "A":
        parser.error("--execute currently supports Stage A only")
    try:
        if args.command in ("analyze-fight", "poll-judge", "resume-judge"):
            from .provider_pipeline import analyze_fight, poll_judge, start_judge
            if args.command == "analyze-fight":
                output = analyze_fight(args.config, args.project_root, args.model, args.concurrency, args.fps, args.resume_attempt, args.gemini_timeout, args.retry_model)
            elif args.command == "poll-judge":
                output = poll_judge(args.attempt)
            else:
                output = start_judge(args.attempt)
            print(json.dumps(output, ensure_ascii=False, indent=2))
            return 1 if output.get("status") in ("failed", "cancelled") else 0
        is_upstream = (
            args.command in ("submit", "handoff")
            or args.command == "validate" and args.stage == "S0"
            or args.command in ("prepare", "run") and args.stage == "A"
        )
        if is_upstream:
            from .stage_a import StageAService
            service = StageAService(args.config, args.project_root)
            if args.command == "validate":
                output = service.validate()
            elif args.command in ("prepare", "run"):
                if args.command == "run" and args.execute:
                    from .codex_runner import execute_stage_a
                    output = execute_stage_a(service, args.pov, force=args.force, model=args.model, timeout=args.codex_timeout)
                else:
                    output = service.prepare(args.pov, force=args.force)
            elif args.command == "submit":
                output = service.submit(args.pov, args.job, args.report, args.review)
            else:
                output = service.export_handoff()
            print(json.dumps(output, ensure_ascii=False, indent=2))
            return 1 if output.get("status") in ("FAIL", "BLOCKED") else 0
        pipeline = DownstreamPipeline(args.config, args.project_root)
        if args.command == "validate":
            output = pipeline.validate(args.accept_limitations)
        elif args.command in ("prepare", "run"):
            output = pipeline.prepare(args.stage, accept_limitations=args.accept_limitations, force=args.force)
        elif args.command == "import-result":
            output = pipeline.import_result(args.stage, args.request, args.response, accept_limitations=args.accept_limitations)
        else:
            output = pipeline.status()
        print(json.dumps(output, ensure_ascii=False, indent=2))
        return 1 if output.get("status") == "FAIL" else 0
    except (ValueError, OSError) as exc:
        print(f"OverJudge: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
