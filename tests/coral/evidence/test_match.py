"""Which shell lines count as running a required command."""

from __future__ import annotations

import pytest

from coral.evidence.match import argv_of, matches, segments


@pytest.mark.parametrize(
    ("command", "counted"),
    [
        ("pytest -q", True),
        ("pytest -q tests/test_api.py", True),
        ("ruff format . && pytest -q", True),
        ("cd sub && pytest -q 2>&1", True),
        ("FOO=1 BAR=2 pytest -q", True),
        ("bash -lc 'cd sub && pytest -q'", True),
        ("sh -c 'pytest -q'", True),
        ("(pytest -q)", True),
        ("pytest -q || true", False),
        ("pytest -q | tee log.txt", False),
        ("pytest -q; echo done", False),
        ("pytest -q &", False),
        ("pytest -q\nfalse", False),
        ("bash -c 'pytest -q || true'", False),
        ("bash -c 'pytest -q' || true", False),
        ("echo pytest -q", False),
        ("pytest", False),
        ("pytest -q 'unterminated", False),
    ],
)
def test_a_segment_counts_only_when_every_later_join_is_and(command: str, counted: bool) -> None:
    assert matches("pytest -q", command) is counted


def test_line_continuations_join_and_newlines_separate() -> None:
    assert matches("pytest -q", "pytest \\\n  -q")
    assert [segment.argv for segment in segments("make\npytest -q")] == [
        ("make",),
        ("pytest", "-q"),
    ]


def test_only_one_level_of_sh_c_is_unwrapped() -> None:
    nested = "bash -c \"sh -c 'pytest -q'\""
    assert not matches("pytest -q", nested)


def test_argv_of_is_empty_for_more_than_one_command() -> None:
    assert argv_of("pytest -q") == ("pytest", "-q")
    assert argv_of("a && b") == ()
    assert argv_of("") == ()
