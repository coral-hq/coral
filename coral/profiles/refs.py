"""Roster entries: a step stance (``reviewer``) or a profile ref (``reviewer/strict-review``)."""

from __future__ import annotations

import re

from coral.tools.catalog import STEP_STANCES

PROFILE_SLUG = re.compile(r"[a-z0-9][a-z0-9_-]{0,63}")


def parse_roster_entry(entry: str) -> tuple[str, str | None] | None:
    """
    Split a roster entry into its stance and profile slug.

    :returns: ``(stance, slug)`` for ``"reviewer/strict"``, ``(stance, None)``
        for ``"reviewer"``, or ``None`` when *entry* is neither.
    """
    stance, separator, slug = entry.partition("/")
    if stance not in STEP_STANCES:
        return None
    if not separator:
        return stance, None
    if PROFILE_SLUG.fullmatch(slug) is None:
        return None
    return stance, slug


def roster_stance(entry: str) -> str | None:
    """The base stance of a roster entry, or ``None`` when the entry is invalid."""
    parsed = parse_roster_entry(entry)
    return parsed[0] if parsed else None
