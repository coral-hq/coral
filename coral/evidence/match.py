"""Whether a shell command line ran a required command so that its exit code reports it.

Matching fails closed: a line counts only when it is a chain of simple commands joined by
``&&`` whose last command is the required one, so the line exits 0 only if that command
did. Any of these refuse the whole line:

- ``#``, ``$``, a backtick, a newline or ``<<`` anywhere;
- a join other than ``&&``, grouping (``( ) { }``), a function definition, or an env
  assignment;
- a command that changes the shell itself (``cd``, ``alias``, ``trap``, ``export``,
  ``eval``, ``source``, ``env`` and the like).

One level of ``sh -c '<script>'`` (also bash, zsh, dash; flags ``-e``, ``-u``, ``-x``
only) in the last command is unwrapped, and its script follows the same rules. The
required command's argv must match exactly, or as a prefix when the item allows extra
arguments.
"""

from __future__ import annotations

import os
import re
import shlex
from dataclasses import dataclass

_SEPARATORS = frozenset({"&&", "||", ";", "|", "&", ";;", "|&", ";&", ";;&"})
_GROUPING = frozenset({"(", ")", "{", "}", "((", "))", "()"})
_SHELLS = frozenset({"sh", "bash", "zsh", "dash"})
# Builtins and commands that change how later commands of the line behave.
_SHELL_STATE = frozenset(
    {
        ".",
        "alias",
        "builtin",
        "cd",
        "command",
        "declare",
        "enable",
        "env",
        "eval",
        "exec",
        "export",
        "function",
        "hash",
        "local",
        "popd",
        "pushd",
        "readonly",
        "set",
        "shopt",
        "source",
        "trap",
        "typeset",
        "unalias",
        "unset",
    }
)
_REFUSED_TEXT = ("#", "$", "`", "\n", "\r", "<<")
_ASSIGNMENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*\+?=")
# A shell flag cluster with -c and only flags that load no startup files: -c, -ec, -xc.
_DASH_C = re.compile(r"^-[eux]*c[eux]*$")


@dataclass(frozen=True)
class Segment:
    """One simple command, and whether its exit code is the line's (the last one)."""

    argv: tuple[str, ...]
    reported: bool


def argv_of(command: str) -> tuple[str, ...]:
    """The argv of one plain simple command, or ``()`` if it is anything else."""
    chain = _chain(command)
    if chain is None or len(chain) != 1:
        return ()
    return chain[0]


def segments(command: str, *, unwrap: bool = True) -> tuple[Segment, ...]:
    """The commands of an ``&&`` chain, the last one unwrapped; ``()`` when it is refused."""
    chain = _chain(command)
    if chain is None:
        return ()
    *head, last = chain
    script = _shell_script(last) if unwrap else None
    tail: tuple[tuple[str, ...], ...] = (last,)
    if script is not None:
        inner = _chain(script)
        if inner is None:
            return ()
        tail = inner
    found = (*head, *tail)
    return tuple(
        Segment(argv=argv, reported=index == len(found) - 1) for index, argv in enumerate(found)
    )


def argv_matches(required: str, argv: tuple[str, ...], *, allow_args: bool = False) -> bool:
    """Whether one command's ``argv`` is ``required``'s, or extends it when args are allowed."""
    wanted = argv_of(required)
    if not wanted:
        return False
    return argv == wanted or (allow_args and argv[: len(wanted)] == wanted)


def matches(required: str, command: str, *, allow_args: bool = False) -> bool:
    """Whether ``command`` ends with ``required`` in an ``&&`` chain nothing else can fake."""
    found = segments(command)
    return bool(found) and argv_matches(required, found[-1].argv, allow_args=allow_args)


def _chain(command: str) -> tuple[tuple[str, ...], ...] | None:
    """The argvs of a plain ``&&`` chain, or ``None`` when the line is refused."""
    text = command.strip()
    if not text or any(part in text for part in _REFUSED_TEXT):
        return None
    lexer = shlex.shlex(text, posix=True, punctuation_chars=True)
    lexer.whitespace_split = True
    lexer.commenters = ""
    try:
        tokens = list(lexer)
    except ValueError:
        return None
    groups: list[list[str]] = [[]]
    for token in tokens:
        if token == "&&":
            groups.append([])
        elif token in _SEPARATORS or token in _GROUPING:
            return None
        else:
            groups[-1].append(token)
    chain: list[tuple[str, ...]] = []
    for group in groups:
        if not group or _ASSIGNMENT.match(group[0]) or group[0] in _SHELL_STATE:
            return None
        if any(token.endswith("()") or token in "{}" for token in group):
            return None
        chain.append(tuple(group))
    return tuple(chain)


def _shell_script(argv: tuple[str, ...]) -> str | None:
    """The script of ``sh -c '<script>'``, else ``None``."""
    if os.path.basename(argv[0]) not in _SHELLS:
        return None
    for index, arg in enumerate(argv[1:], start=1):
        if _DASH_C.match(arg):
            return argv[index + 1] if index + 1 < len(argv) else None
        if not arg.startswith("-"):
            return None
    return None


__all__ = ["Segment", "argv_matches", "argv_of", "matches", "segments"]
