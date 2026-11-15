"""Coral command-line entry point.

This composition root applies ``~/.coral`` environment defaults before lazily
importing any ``omnigent`` modules so import-time path constants resolve under
Coral's directory.
"""

from __future__ import annotations

import sys
from collections.abc import Sequence
from pathlib import Path

import click

from coral.version import apply_coral_environment, format_version

_UPGRADE_UNAVAILABLE_MESSAGE = (
    "coral upgrade is not available yet; install upgrades from Coral's release channel."
)


@click.command(
    "upgrade",
    context_settings={"ignore_unknown_options": True, "allow_extra_args": True},
)
@click.argument("args", nargs=-1, type=click.UNPROCESSED)
def _blocked_upgrade(args: tuple[str, ...]) -> None:  # noqa: ARG001
    """Block upstream Omnigent self-upgrade under the Coral CLI."""
    click.echo(_UPGRADE_UNAVAILABLE_MESSAGE, err=True)
    raise SystemExit(2)


def _make_passthrough_command(command_name: str) -> click.Command:
    @click.command(
        command_name,
        add_help_option=False,
        context_settings={
            "ignore_unknown_options": True,
            "allow_extra_args": True,
            "allow_interspersed_args": False,
        },
    )
    @click.pass_context
    def _passthrough(ctx: click.Context) -> None:
        from coral.omni.cli_passthrough import forward_to_omnigent

        forward_to_omnigent([command_name, *ctx.args])

    return _passthrough


class _CoralGroup(click.Group):
    """Click group exposing Coral commands while lazily forwarding others."""

    def get_command(self, ctx: click.Context, cmd_name: str) -> click.Command | None:
        cmd = super().get_command(ctx, cmd_name)
        if cmd is not None:
            return cmd
        if cmd_name == "upgrade":
            return _blocked_upgrade
        return _make_passthrough_command(cmd_name)


def _version_callback(ctx: click.Context, _param: click.Parameter, value: bool) -> None:
    if not value or ctx.resilient_parsing:
        return
    from coral.omni.cli_passthrough import get_omnigent_version

    click.echo(format_version(get_omnigent_version()))
    ctx.exit(0)


@click.group(
    cls=_CoralGroup,
    invoke_without_command=True,
    no_args_is_help=True,
    context_settings={"help_option_names": ["-h", "--help"]},
)
@click.option(
    "--version",
    "-V",
    is_flag=True,
    is_eager=True,
    expose_value=False,
    callback=_version_callback,
    help="Show the Coral and Omnigent versions and exit.",
)
def cli() -> None:
    """Coral workflow orchestration CLI."""
    apply_coral_environment()


@cli.group("workflow", help="Work with workflow definitions.")
def workflow_group() -> None:
    """Workflow definition subcommands."""


def _validate_workflow_file(path: Path) -> int:
    from coral.validate.pipeline import check_text

    result = check_text(path.read_text())
    if result.load_error is not None:
        error = result.load_error
        line = f":{error.range.start_line}" if error.range else ""
        click.echo(f"{path}{line}: {error.code}: {error.message}", err=True)
        return 1
    assert result.report is not None
    for problem in result.report.problems:
        line = f":{problem.range.start_line}" if problem.range else ""
        click.echo(f"{path}{line}: {problem.severity} {problem.rule}: {problem.message}")
    click.echo("runnable" if result.report.runnable else "not runnable")
    return 0 if result.report.runnable else 1


@workflow_group.command("validate", help="Check a workflow YAML file.")
@click.argument("path", type=click.Path(path_type=Path))
def validate_workflow(path: Path) -> None:
    """Validate and summarize runnability for a workflow YAML file."""
    raise SystemExit(_validate_workflow_file(path))


def main(argv: Sequence[str] | None = None) -> int:
    """Console entry point for ``coral``."""
    apply_coral_environment()
    args = list(sys.argv[1:] if argv is None else argv)
    try:
        cli.main(args=args, prog_name="coral", standalone_mode=True)
    except SystemExit as exc:
        return int(exc.code) if isinstance(exc.code, int) else 0
    return 0
