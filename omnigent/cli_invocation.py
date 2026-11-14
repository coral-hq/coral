"""How to spell an ``omnigent`` command back to the user.

When a deployment wraps the CLI (e.g. ``isaac omni``) it sets
``OMNIGENT_WRAPPER_COMMAND`` and refuses naked ``omnigent`` calls (see the
wrapper guard in :mod:`omnigent.cli`). Followup hints that tell the user to run
a command must then name the wrapper (``isaac omni stop``) rather than the
naked binary (``omnigent stop``), or they suggest exactly the command the guard
rejects. :func:`cli_invocation` centralizes that spelling: hints interpolate it
in place of the leading ``omnigent``/``omni`` token so every one honors the
configured wrapper.
"""

from __future__ import annotations

import os
from collections.abc import Mapping, MutableMapping  # CORAL(S96): name_invoked_command
from pathlib import PureWindowsPath  # CORAL(S96): name_invoked_command

DEFAULT_CLI_NAME = "omnigent"
WRAPPER_COMMAND_ENV = "OMNIGENT_WRAPPER_COMMAND"


def cli_invocation(*, name: str = DEFAULT_CLI_NAME, env: Mapping[str, str] | None = None) -> str:
    """Return the token that invokes the CLI: the configured wrapper, else ``name``.

    ``name`` is the naked binary the hint would otherwise use (``omnigent`` or
    its ``omni`` alias); it is kept verbatim when no wrapper is configured, so a
    hint reads ``omnigent stop`` normally and ``isaac omni stop`` when
    ``OMNIGENT_WRAPPER_COMMAND=isaac omni``.
    """
    if env is None:
        env = os.environ
    return (env.get(WRAPPER_COMMAND_ENV) or "").strip() or name


# CORAL(S96): a CLI run as `coral` names itself `coral` in hints
CORAL_CLI_NAME = "coral"


def name_invoked_command(argv0: str, env: MutableMapping[str, str]) -> None:
    """Make hints spell ``coral`` when the user ran the CLI as ``coral``.

    A configured wrapper command wins. The value goes into ``env`` so that
    daemons and runners started from this process name the same command.
    """
    invoked = PureWindowsPath(argv0).stem  # accepts either path separator on every OS
    if invoked == CORAL_CLI_NAME and not (env.get(WRAPPER_COMMAND_ENV) or "").strip():
        env[WRAPPER_COMMAND_ENV] = CORAL_CLI_NAME
