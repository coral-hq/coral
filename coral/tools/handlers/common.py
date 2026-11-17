"""What the engine-tool planners share: the run's stop state and argument checks."""

from __future__ import annotations

import heapq
import re
from collections.abc import Iterable, Sequence
from typing import Literal

from coral.db.enum_codecs import RunStatus, decode_run_pause_reason
from coral.tools.port import RunSnapshot

RunStop = Literal["cancelled", "finished", "paused"]

_FINISHED = frozenset({int(RunStatus.COMPLETED), int(RunStatus.FAILED)})
# Unknown argument names are never echoed raw: at most this many plain names are listed.
_UNKNOWN_LISTED = 5
_PLAIN_NAME = re.compile(r"[A-Za-z0-9_]{1,32}")


def run_stop(snapshot: RunSnapshot) -> RunStop | None:
    """Why the run takes no tool call, by its store row or its engine state; ``None`` if live.

    Drift pauses change only the store row, so both are read.
    """
    stored, engine = snapshot.run.status, snapshot.state.status
    if stored == RunStatus.CANCELLED or engine == "cancelled":
        return "cancelled"
    if stored in _FINISHED or engine in {"completed", "failed"}:
        return "finished"
    if stored == RunStatus.PAUSED or engine == "paused":
        return "paused"
    return None


def pause_reason(snapshot: RunSnapshot) -> str | None:
    """The store's pause reason (drift pauses live only there), else the engine's."""
    code = snapshot.run.pause_reason
    if snapshot.run.status == RunStatus.PAUSED and code is not None:
        try:
            return decode_run_pause_reason(code)
        except ValueError:
            return None
    causes = snapshot.state.causes
    return causes[0].reason if snapshot.state.status == "paused" and causes else None


def text_argument(value: object, max_length: int) -> str | None:
    """Non-blank text of at most ``max_length`` characters that UTF-8 can encode, else ``None``."""
    if not isinstance(value, str) or len(value) > max_length or not value.strip():
        return None
    return value if encodable(value) else None


def encodable(text: str) -> bool:
    """Whether UTF-8 can encode ``text`` (an unpaired surrogate cannot be stored or sent)."""
    try:
        text.encode("utf-8")
    except UnicodeEncodeError:
        return False
    return True


def unknown_arguments_message(unknown: Sequence[object], known: Iterable[str]) -> str:
    """How many unknown arguments came, naming at most a few plain ones; never raw text."""
    plain = [name for name in unknown if isinstance(name, str) and _PLAIN_NAME.fullmatch(name)]
    named = heapq.nsmallest(_UNKNOWN_LISTED, plain)
    listed = f" ({', '.join(named)})" if named else ""
    arguments = ", ".join(sorted(known))
    return f"{len(unknown)} unknown argument(s){listed}; the arguments are {arguments}."
