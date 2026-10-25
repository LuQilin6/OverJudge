"""Command-line interface for the manual Stage B/C/D workflow."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from .contracts import ContractError
from .pipeline import DownstreamPipeline


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="OverJudge Stage B/C/D manual Codex workflow")
    subparsers = parser.add_subparsers(dest="command", required=True)
    for name in ("validate", "prepare", "run", "import-result", "status"):
        sub = subparsers.add_parser(name)
        sub.add_argument("--config", default="config/run.json", type=Path)
        sub.add_argument("--project-root", type=Path, help="Base directory for relative paths; defaults to this repository")
        if name != "status":
            sub.add_argument("--accept-limitations", action="store_true", help="Coordinator has reviewed and accepts documented upstream limitations")
        if name in ("prepare", "run", "import-result"):
            sub.add_argument("--stage", required=True, choices=("B", "C", "D"))
        if name in ("prepare", "run"):
            sub.add_argument("--force", action="store_true", help="Prepare a fresh task even when the current result is cached")
        if name == "import-result":
            sub.add_argument("--request", type=Path, required=True)
            sub.add_argument("--response", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
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
    except (ContractError, OSError) as exc:
        print(f"OverJudge: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
