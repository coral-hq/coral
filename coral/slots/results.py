"""Keep effect results inside the queue's result column (``coral_work.result``).

The queue stores a result as ``json.dumps(result, sort_keys=True)``, which
escapes every non-ASCII character (6 bytes each, 12 for one outside the BMP),
in a column that refuses more than 16,383 stored bytes; a refused write would
stop the drain loop. So every size here is a stored size, and every executor
result passes :func:`bound_result`: text is cut, diff paths get the bytes the
rest of the result leaves, and a result still over :data:`RESULT_BYTE_BUDGET`
is refused.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from typing import Any

RESULT_BYTE_BUDGET = 12_288
DIFF_PATHS_BYTE_BUDGET = 8_192
SUBJECT_MAX_CHARS = 256
SUBJECT_MAX_BYTES = 1_536
FREE_TEXT_MAX_CHARS = 512
FREE_TEXT_MAX_BYTES = 3_072
_CUT_MARK = "…"
# ``json.dumps`` puts ", " between list items and "[]" around them.
_ITEM_SEPARATOR_BYTES = 2
_EMPTY_LIST_BYTES = 2


class ResultTooLarge(ValueError):
    """A result is over the byte budget even after trimming; a bug in its executor."""


def stored_result_bytes(result: Mapping[str, Any]) -> int:
    """The bytes ``result`` takes in the queue's result column, before compression."""
    return len(json.dumps(result, sort_keys=True).encode())


def stored_text_bytes(text: str) -> int:
    """The bytes ``text`` takes inside a stored result, without its quotes."""
    return len(json.dumps(text)) - 2


def bound_result(result: Mapping[str, Any]) -> dict[str, Any]:
    """
    Return a copy of ``result`` that fits the queue's result column.

    ``subject`` keeps at most :data:`SUBJECT_MAX_CHARS` characters and
    :data:`SUBJECT_MAX_BYTES` stored bytes, any other top-level text
    :data:`FREE_TEXT_MAX_CHARS` and :data:`FREE_TEXT_MAX_BYTES`.
    ``diff_stat.paths`` keeps the longest prefix that fits both
    :data:`DIFF_PATHS_BYTE_BUDGET` and what the rest of the result leaves of
    :data:`RESULT_BYTE_BUDGET`, and gains ``paths_truncated``; its counts still
    describe the whole diff.

    :raises ResultTooLarge: when the bounded result is still over
        :data:`RESULT_BYTE_BUDGET` stored bytes.
    """
    bounded: dict[str, Any] = {}
    for key, value in result.items():
        if isinstance(value, str):
            if key == "subject":
                bounded[key] = _cut(value, SUBJECT_MAX_CHARS, SUBJECT_MAX_BYTES)
            else:
                bounded[key] = _cut(value, FREE_TEXT_MAX_CHARS, FREE_TEXT_MAX_BYTES)
        else:
            bounded[key] = value
    diff_stat = result.get("diff_stat")
    if isinstance(diff_stat, Mapping):
        bounded["diff_stat"] = _bounded_diff_stat(bounded, diff_stat)
    size = stored_result_bytes(bounded)
    if size > RESULT_BYTE_BUDGET:
        raise ResultTooLarge(
            f"effect result is {size} bytes after trimming; the budget is {RESULT_BYTE_BUDGET}"
        )
    return bounded


def _bounded_diff_stat(result: Mapping[str, Any], diff_stat: Mapping[str, Any]) -> dict[str, Any]:
    paths = diff_stat.get("paths")
    if not isinstance(paths, Sequence) or isinstance(paths, str):
        return dict(diff_stat)
    # Measured with no paths and the longer flag value, so the kept paths always fit.
    skeleton = {**diff_stat, "paths": [], "paths_truncated": False}
    rest = stored_result_bytes({**result, "diff_stat": skeleton}) - _EMPTY_LIST_BYTES
    kept = _paths_within(paths, min(DIFF_PATHS_BYTE_BUDGET, RESULT_BYTE_BUDGET - rest))
    return {**diff_stat, "paths": kept, "paths_truncated": len(kept) < len(paths)}


def _paths_within(paths: Sequence[Any], budget: int) -> list[Any]:
    """The longest prefix of ``paths`` whose ``json.dumps`` is at most ``budget`` bytes."""
    kept: list[Any] = []
    used = _EMPTY_LIST_BYTES
    for path in paths:
        cost = len(json.dumps(path).encode()) + (_ITEM_SEPARATOR_BYTES if kept else 0)
        if used + cost > budget:
            break
        kept.append(path)
        used += cost
    return kept


def _cut(text: str, max_chars: int, max_bytes: int) -> str:
    """``text``, or its longest prefix plus a cut mark within both limits as stored."""
    if len(text) <= max_chars and stored_text_bytes(text) <= max_bytes:
        return text
    budget = max_bytes - stored_text_bytes(_CUT_MARK)
    kept: list[str] = []
    used = 0
    for char in text[: max_chars - len(_CUT_MARK)]:
        cost = stored_text_bytes(char)
        if used + cost > budget:
            break
        kept.append(char)
        used += cost
    return "".join(kept) + _CUT_MARK
