"""Which shell lines count as running a required command."""

from __future__ import annotations

import pytest

from coral.evidence.match import argv_of, matches, segments


@pytest.mark.parametrize(
    ("command", "counted"),
    [
        ("pytest -q", True),
        ("  pytest -q\n", True),
        ("ruff format . && pytest -q", True),
        ("sh -c 'pytest -q'", True),
        ("bash -ec 'ruff check . && pytest -q'", True),
        ("pytest -q tests/test_api.py", False),
        ("pytest -q --co", False),
        ("pytest -q && echo done", False),
        ("cd sub && pytest -q", False),
        ("FOO=1 pytest -q", False),
        ("PYTEST_ADDOPTS=--co pytest -q", False),
        ("env X=1 pytest -q", False),
        ("bash -lc 'pytest -q'", False),
        ("(pytest -q)", False),
        ("pytest -q || true", False),
        ("pytest -q | tee log.txt", False),
        ("pytest -q; echo done", False),
        ("pytest -q &", False),
        ("make\npytest -q", False),
        ("true # && pytest -q", False),
        ('trap "exit 0" EXIT && pytest -q', False),
        ("pytest() { true; }; pytest -q", False),
        ("f() { :; } && pytest -q", False),
        ("alias pytest=true && pytest -q", False),
        ("cat <<EOF\npytest -q", False),
        ("pytest -q $EXTRA", False),
        ("pytest -q `echo --co`", False),
        ("bash -c 'pytest -q || true'", False),
        ("bash -c 'pytest -q' || true", False),
        ("echo pytest -q", False),
        ("pytest", False),
        ("pytest -q 'unterminated", False),
    ],
)
def test_only_a_plain_and_chain_ending_in_the_command_counts(command: str, counted: bool) -> None:
    assert matches("pytest -q", command) is counted


def test_extra_arguments_count_only_when_allowed() -> None:
    assert matches("pytest", "pytest -q tests/a.py", allow_args=True)
    assert not matches("pytest", "pytest -q tests/a.py")
    assert [segment.argv for segment in segments("ruff format . && pytest -q")] == [
        ("ruff", "format", "."),
        ("pytest", "-q"),
    ]


def test_only_one_level_of_sh_c_is_unwrapped() -> None:
    nested = "bash -c \"sh -c 'pytest -q'\""
    assert not matches("pytest -q", nested)


def test_argv_of_is_empty_for_more_than_one_command() -> None:
    assert argv_of("pytest -q") == ("pytest", "-q")
    assert argv_of("a && b") == ()
    assert argv_of("") == ()
