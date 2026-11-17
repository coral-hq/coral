"""Effect results stay inside the queue's result column, whatever the diff."""

from __future__ import annotations

import json
from typing import Any

import pytest

from coral.slots.results import (
    DIFF_PATHS_BYTE_BUDGET,
    FREE_TEXT_MAX_CHARS,
    RESULT_BYTE_BUDGET,
    SUBJECT_MAX_BYTES,
    SUBJECT_MAX_CHARS,
    ResultTooLarge,
    bound_result,
    stored_result_bytes,
    stored_text_bytes,
)

_FULL_DIFF = [f"src/{index:03d}/" + "p" * 1016 for index in range(200)]


def _commit_result(paths: list[str], **extra: Any) -> dict[str, Any]:
    return {
        "commit": "c" * 40,
        "empty": False,
        "subject": "Review: done",
        "diff_stat": {
            "files_changed": len(paths),
            "insertions": 3 * len(paths),
            "deletions": len(paths),
            "paths": paths,
        },
        "node_id": "review",
        "item_path": None,
        **extra,
    }


def test_two_hundred_kibibyte_paths_are_trimmed_under_the_budget() -> None:
    paths = [f"src/{index:03d}/" + "p" * 1016 for index in range(200)]
    assert all(len(path) == 1024 for path in paths)
    result = _commit_result(paths)

    bounded = bound_result(result)

    stat = bounded["diff_stat"]
    assert stored_result_bytes(bounded) <= RESULT_BYTE_BUDGET
    assert stat["paths_truncated"] is True
    # A prefix of the sorted paths, as many as fit; the counts still describe the whole diff.
    kept = stat["paths"]
    assert kept == paths[: len(kept)]
    assert len(json.dumps(kept)) <= DIFF_PATHS_BYTE_BUDGET
    assert len(json.dumps(paths[: len(kept) + 1])) > DIFF_PATHS_BYTE_BUDGET
    assert (stat["files_changed"], stat["insertions"], stat["deletions"]) == (200, 600, 200)
    # The input is left as it was.
    assert result["diff_stat"]["paths"] == paths
    assert "paths_truncated" not in result["diff_stat"]


def test_paths_are_measured_as_the_queue_stores_them() -> None:
    # json.dumps escapes each non-ASCII character to six bytes in the stored row.
    paths = [f"{index}-" + "é" * 600 for index in range(20)]

    bounded = bound_result(_commit_result(paths))

    kept = bounded["diff_stat"]["paths"]
    assert len(json.dumps(kept)) <= DIFF_PATHS_BYTE_BUDGET < len(json.dumps(paths))
    assert bounded["diff_stat"]["paths_truncated"] is True
    assert stored_result_bytes(bounded) <= RESULT_BYTE_BUDGET


def test_a_small_result_is_unchanged_but_says_its_paths_are_whole() -> None:
    result = _commit_result(["README.md", "src/app.py"])

    bounded = bound_result(result)

    assert bounded == {
        **result,
        "diff_stat": {**result["diff_stat"], "paths_truncated": False},
    }
    assert bound_result({"head": "c" * 40}) == {"head": "c" * 40}


def test_subject_and_free_text_are_cut_to_their_limits_but_echoed_ids_are_kept_whole() -> None:
    # The payload parser accepts an item_path of 1,024 stored bytes; the engine
    # finds its item by the exact value, so it is never cut.
    item_path = "i" * 1_024
    bounded = bound_result(
        _commit_result(
            [], subject="s" * 1000, item_path=item_path, node_id="n" * 128, note="t" * 1000
        )
    )

    assert bounded["subject"] == "s" * (SUBJECT_MAX_CHARS - 1) + "…"
    assert bounded["note"] == "t" * (FREE_TEXT_MAX_CHARS - 1) + "…"
    assert (bounded["item_path"], bounded["node_id"]) == (item_path, "n" * 128)
    assert bounded["commit"] == "c" * 40


@pytest.mark.parametrize(
    ("subject", "item_path"),
    [
        # The widest item paths the payload parser accepts: 1,020 stored bytes.
        ("\u4e2d\u6587\u63d0\u4ea4\u4fe1\u606f" * 200, "\u8def" * 170),
        ("\U0001f680 shipped " * 200, "\U0001f4c1" * 85),
    ],
    ids=["cjk", "emoji"],
)
def test_wide_text_and_a_full_path_list_fit_as_stored(subject: str, item_path: str) -> None:
    result = _commit_result(_FULL_DIFF, subject=subject, item_path=item_path, node_id="\u8282")

    bounded = bound_result(result)

    assert stored_result_bytes(bounded) <= RESULT_BYTE_BUDGET
    # Text is cut by what the queue stores: six bytes per CJK character, twelve per emoji.
    assert stored_text_bytes(bounded["subject"]) <= SUBJECT_MAX_BYTES
    assert len(bounded["subject"]) <= SUBJECT_MAX_CHARS
    assert subject.startswith(bounded["subject"][:-1]) and bounded["subject"].endswith("…")
    assert bounded["item_path"] == item_path
    assert bounded["node_id"] == "\u8282"
    # The paths get only what the text leaves.
    kept = bounded["diff_stat"]["paths"]
    assert bounded["diff_stat"]["paths_truncated"] is True
    assert kept == _FULL_DIFF[: len(kept)]
    with_one_more = {
        **bounded,
        "diff_stat": {**bounded["diff_stat"], "paths": _FULL_DIFF[: len(kept) + 1]},
    }
    assert stored_result_bytes(with_one_more) > RESULT_BYTE_BUDGET or (
        len(json.dumps(_FULL_DIFF[: len(kept) + 1])) > DIFF_PATHS_BYTE_BUDGET
    )


def test_paths_never_take_bytes_the_rest_of_the_result_needs() -> None:
    # Large but in-limit text leaves less than the usual path budget.
    result = _commit_result(
        _FULL_DIFF,
        subject="\u4e2d" * SUBJECT_MAX_CHARS,
        message="\u8282" * FREE_TEXT_MAX_CHARS,
        note="\u8def" * FREE_TEXT_MAX_CHARS,
    )

    bounded = bound_result(result)

    assert len(json.dumps(bounded["diff_stat"]["paths"])) < DIFF_PATHS_BYTE_BUDGET - 1024
    assert stored_result_bytes(bounded) <= RESULT_BYTE_BUDGET


def test_a_result_still_over_budget_is_refused() -> None:
    result = {f"note_{index}": "x" * FREE_TEXT_MAX_CHARS for index in range(30)}

    with pytest.raises(ResultTooLarge) as caught:
        bound_result(result)

    assert str(RESULT_BYTE_BUDGET) in str(caught.value)
