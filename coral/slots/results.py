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

from coral.workspace.ops import paths_within

RESULT_BYTE_BUDGET = 12_288
DIFF_PATHS_BYTE_BUDGET = 8_192
SUBJECT_MAX_CHARS = 256
SUBJECT_MAX_BYTES = 1_536
FREE_TEXT_MAX_CHARS = 512
FREE_TEXT_MAX_BYTES = 3_072
# Engine ids a result echoes, bounded by the payload parser; a cut id names no item.
ECHOED_ID_KEYS = frozenset({"node_id", "item_path"})
_CUT_MARK = "…"
# ``json.dumps`` puts "[]" around a list.
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
    :data:`SUBJECT_MAX_BYTES` stored bytes, and echoed ids
    (:data:`ECHOED_ID_KEYS`) are kept whole; any other top-level text keeps
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
        if isinstance(value, str) and key not in ECHOED_ID_KEYS:
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
    kept = paths_within(paths, min(DIFF_PATHS_BYTE_BUDGET, RESULT_BYTE_BUDGET - rest))
    # The host may already have cut the list to fit its channel.
    truncated = diff_stat.get("paths_truncated") is True or len(kept) < len(paths)
    return {**diff_stat, "paths": kept, "paths_truncated": truncated}


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
