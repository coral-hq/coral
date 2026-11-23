"""A roster entry is a step stance or a ``<stance>/<slug>`` profile ref."""

from __future__ import annotations

import pytest

from coral.profiles.refs import parse_roster_entry, roster_stance


@pytest.mark.parametrize(
    ("entry", "parsed"),
    [
        ("implementer", ("implementer", None)),
        ("reviewer", ("reviewer", None)),
        ("reviewer/strict-review", ("reviewer", "strict-review")),
        ("implementer/a_1", ("implementer", "a_1")),
        ("implementer/" + "a" * 64, ("implementer", "a" * 64)),
        ("implementer/" + "a" * 65, None),
        ("orchestrator", None),
        ("anchor/x", None),
        ("writer/x", None),
        ("reviewer/", None),
        ("reviewer/Strict", None),
        ("reviewer/-x", None),
        ("reviewer/a.b", None),
        ("reviewer/a/b", None),
        ("/x", None),
        ("", None),
    ],
)
def test_parse_roster_entry(entry: str, parsed: tuple[str, str | None] | None) -> None:
    assert parse_roster_entry(entry) == parsed
    assert roster_stance(entry) == (parsed[0] if parsed else None)
