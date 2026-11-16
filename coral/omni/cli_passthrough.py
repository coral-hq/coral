"""Lazy delegation from the Coral CLI to Omnigent's CLI."""

from __future__ import annotations

import sys
from collections.abc import Sequence

from coral.version import apply_coral_environment


def get_omnigent_version() -> str:
    """Import and return Omnigent's version string after environment setup."""
    apply_coral_environment()
    from omnigent.version import VERSION

    return VERSION


def forward_to_omnigent(argv: Sequence[str], *, prog_name: str = "coral") -> None:
    """Forward non-Coral CLI invocations to :func:`omnigent.cli.main`.

    Applies ``~/.coral`` environment defaults before importing ``omnigent.cli``
    so module-level path constants resolve under Coral's directory.
    """
    apply_coral_environment()
    from omnigent.cli import main as omnigent_main

    saved_argv = list(sys.argv)
    try:
        sys.argv = [prog_name, *argv]
        omnigent_main()
    finally:
        sys.argv = saved_argv
