#!/usr/bin/env python3
"""
Process Atlas extraction agent.

    python3 atlas.py run ./my-service
    python3 atlas.py run ./my-service --config process-atlas.json --out out
    python3 atlas.py discover ./my-service
    python3 atlas.py validate out/prj_x/processes/foo/cpm.json

Run `python3 atlas.py run --help` for provider and output options.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pipeline
import validation

VERSION = "1.0.0"


def cmd_run(args) -> int:
    return pipeline.run(
        repo=Path(args.source),
        out=Path(args.out),
        config_path=Path(args.config) if args.config else None,
        provider_name=args.provider,
        model=args.model,
        allow_unevidenced=args.allow_unevidenced,
        dry_run=args.dry_run,
        quiet=args.quiet,
    )


def cmd_discover(args) -> int:
    print(f"Discovery for {Path(args.source).resolve()}")
    return pipeline.run(
        repo=Path(args.source),
        out=Path(args.out),
        config_path=Path(args.config) if args.config else None,
        provider_name="heuristic",
        dry_run=True,
        quiet=False,
    )


def cmd_validate(args) -> int:
    path = Path(args.file)
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        print(f"error: file not found: {path}")
        return 3
    except json.JSONDecodeError as exc:
        print(f"error: invalid JSON at line {exc.lineno}, column {exc.colno}: {exc.msg}")
        return 3
    try:
        report = validation.validate(document, str(path))
    except ValueError as exc:
        print(f"error: {exc}")
        return 3
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print(validation.validator().render_text(report, args.verbose))
    return {"business_process": 0, "partial_process": 1, "not_a_process": 2}[report["verdict"]]


def cmd_selftest(args) -> int:
    import selftest
    return selftest.run()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="atlas",
        description="Extract business processes from source code as Canonical Process Models.",
    )
    parser.add_argument("--version", action="version", version=f"process-atlas-agent {VERSION}")
    sub = parser.add_subparsers(dest="command")

    run = sub.add_parser("run", help="extract processes and write CPM, BPMN, docs and a report")
    run.add_argument("source", help="path to the repository to analyse")
    run.add_argument("--config", help="path to process-atlas.json (default: <source>/process-atlas.json)")
    run.add_argument("--out", default="atlas-out", help="output directory (default: ./atlas-out)")
    run.add_argument("--provider", default="auto",
                     choices=["auto", "heuristic", "anthropic", "openai"],
                     help="model provider; auto uses a key if present, else the offline baseline")
    run.add_argument("--model", default="", help="override the provider's default model")
    run.add_argument("--allow-unevidenced", action="store_true",
                     help="downgrade the evidence gate for draft extraction")
    run.add_argument("--dry-run", action="store_true", help="scan and list process boundaries only")
    run.add_argument("--quiet", action="store_true", help="only print the final summary")
    run.set_defaults(func=cmd_run)

    discover = sub.add_parser("discover", help="scan a repository and show discovered boundaries")
    discover.add_argument("source")
    discover.add_argument("--config")
    discover.add_argument("--out", default="atlas-out")
    discover.set_defaults(func=cmd_discover)

    validate_cmd = sub.add_parser("validate", help="validate an existing CPM or extraction envelope")
    validate_cmd.add_argument("file")
    validate_cmd.add_argument("--json", action="store_true", help="machine-readable report")
    validate_cmd.add_argument("--verbose", action="store_true")
    validate_cmd.set_defaults(func=cmd_validate)

    selftest_cmd = sub.add_parser("selftest", help="run the bundled extraction, evidence and projection checks")
    selftest_cmd.set_defaults(func=cmd_selftest)

    return parser


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "func", None):
        parser.print_help()
        return 3
    try:
        return args.func(args)
    except KeyboardInterrupt:
        print("\ninterrupted", file=sys.stderr)
        return 130


if __name__ == "__main__":
    sys.exit(main())
