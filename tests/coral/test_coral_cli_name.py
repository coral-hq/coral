"""Hints name ``coral`` when the CLI runs as ``coral`` (seam S96)."""

from __future__ import annotations

import pytest

from omnigent.cli_invocation import WRAPPER_COMMAND_ENV, cli_invocation, name_invoked_command


@pytest.mark.parametrize(
    "argv0", ["coral", "/home/me/.venv/bin/coral", r"C:\venv\Scripts\coral.exe"]
)
def test_running_as_coral_makes_hints_name_coral(argv0: str) -> None:
    env: dict[str, str] = {}
    name_invoked_command(argv0, env)
    assert env == {WRAPPER_COMMAND_ENV: "coral"}
    assert f"Run `{cli_invocation(env=env)} stop`" == "Run `coral stop`"


@pytest.mark.parametrize("argv0", ["omnigent", "/usr/local/bin/omni", "pytest", "-c"])
def test_other_names_keep_the_default_hint(argv0: str) -> None:
    env: dict[str, str] = {}
    name_invoked_command(argv0, env)
    assert env == {}
    assert cli_invocation(env=env) == "omnigent"


def test_an_operator_wrapper_wins() -> None:
    env = {WRAPPER_COMMAND_ENV: "isaac omni"}
    name_invoked_command("coral", env)
    assert env == {WRAPPER_COMMAND_ENV: "isaac omni"}


def test_a_blank_wrapper_counts_as_unset() -> None:
    env = {WRAPPER_COMMAND_ENV: "  "}
    name_invoked_command("coral", env)
    assert env == {WRAPPER_COMMAND_ENV: "coral"}
