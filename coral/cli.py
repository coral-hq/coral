"""Coral command line."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from coral.validate.pipeline import check_text
from coral.version import __version__


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="coral", description="Coral workflow tools.")
    parser.add_argument("--version", action="version", version=f"coral {__version__}")
    commands = parser.add_subparsers(dest="command")
    workflow = commands.add_parser("workflow", help="work with workflow definitions")
    workflow_commands = workflow.add_subparsers(dest="workflow_command")
    validate = workflow_commands.add_parser("validate", help="check a workflow YAML file")
    validate.add_argument("path", type=Path)
    return parser


def _validate_file(path: Path) -> int:
    result = check_text(path.read_text())
    if result.load_error is not None:
        error = result.load_error
        line = f":{error.range.start_line}" if error.range else ""
        print(f"{path}{line}: {error.code}: {error.message}", file=sys.stderr)
        return 1
    assert result.report is not None
    for problem in result.report.problems:
        line = f":{problem.range.start_line}" if problem.range else ""
        print(f"{path}{line}: {problem.severity} {problem.rule}: {problem.message}")
    print("runnable" if result.report.runnable else "not runnable")
    return 0 if result.report.runnable else 1


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    if args.command == "workflow" and args.workflow_command == "validate":
        return _validate_file(args.path)
    parser.print_help()
    return 0
