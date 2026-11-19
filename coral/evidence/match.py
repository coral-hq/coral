"""Whether a shell command line ran a required command in a way its exit code reports.

A line is split into segments on ``&&``, ``||``, ``;``, ``|``, ``&`` and newlines. One
level of ``sh -c '<script>'`` (also bash, zsh, dash) is unwrapped. A segment counts only
if every join after it is ``&&``: then the line's exit code is 0 only if the segment
passed. So ``pytest || true`` and ``pytest | tee log`` never count.
"""

from __future__ import annotations

import os
import re
import shlex
from dataclasses import dataclass

_SEPARATORS = frozenset({"&&", "||", ";", "|", "&", ";;", "|&"})
_SHELLS = frozenset({"sh", "bash", "zsh", "dash"})
_ASSIGNMENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
# A shell flag cluster that includes -c, e.g. -c, -lc, -ec.
_DASH_C = re.compile(r"^-[A-Za-z]*c[A-Za-z]*$")


@dataclass(frozen=True)
class Segment:
    """One simple command, and whether every join after it is ``&&``."""

    argv: tuple[str, ...]
    reported: bool


def argv_of(command: str) -> tuple[str, ...]:
    """The argv of a single simple command, or ``()`` if it is not exactly one."""
    found = segments(command, unwrap=False)
    return found[0].argv if len(found) == 1 else ()


def segments(command: str, *, unwrap: bool = True) -> tuple[Segment, ...]:
    """The simple commands of ``command``; ``()`` when it does not parse."""
    tokens = _tokens(command)
    if tokens is None:
        return ()
    groups: list[list[str]] = [[]]
    joins: list[str] = []
    for token in tokens:
        if token in _SEPARATORS:
            groups.append([])
            joins.append(token)
        else:
            groups[-1].append(token)
    found: list[Segment] = []
    for index, group in enumerate(groups):
        argv = _strip_assignments(tuple(token for token in group if token not in "()"))
        if not argv:
            continue
        reported = all(join == "&&" for join in joins[index:])
        script = _shell_script(argv) if unwrap else None
        if script is None:
            found.append(Segment(argv=argv, reported=reported))
            continue
        for inner in segments(script, unwrap=False):
            found.append(Segment(argv=inner.argv, reported=reported and inner.reported))
    return tuple(found)


def matches(required: str, command: str) -> bool:
    """Whether ``command`` ran ``required`` in a segment its exit code reports."""
    wanted = argv_of(required)
    if not wanted:
        return False
    return any(
        segment.reported and segment.argv[: len(wanted)] == wanted for segment in segments(command)
    )


def _tokens(command: str) -> list[str] | None:
    # A backslash-newline continues the line; any other newline ends a command.
    text = command.replace("\\\n", " ").replace("\r\n", "\n").replace("\n", " ; ")
    lexer = shlex.shlex(text, posix=True, punctuation_chars=True)
    lexer.whitespace_split = True
    lexer.commenters = ""
    try:
        return list(lexer)
    except ValueError:
        return None


def _strip_assignments(argv: tuple[str, ...]) -> tuple[str, ...]:
    index = 0
    while index < len(argv) and _ASSIGNMENT.match(argv[index]):
        index += 1
    return argv[index:]


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


__all__ = ["Segment", "argv_of", "matches", "segments"]
