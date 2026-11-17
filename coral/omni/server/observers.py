"""Turn one status edge into a ``TurnFact``. Idle is not a completed turn."""

from __future__ import annotations

from collections.abc import Mapping

from coral.engine.facts import TurnFact


def observe_status_edge(edge: Mapping[str, object]) -> TurnFact | None:
    """Copy one edge into a fact. The same edge always returns an equal fact.

    A missing or empty ``session_id`` returns ``None``. ``previous_status`` and
    ``observed_at_ms`` are read and ignored. Nothing here is remembered. The
    fact's ``response_id`` is the response the edge's outcome reports on
    (``turn_response_id``), else the one the edge opens (``response_id``).
    """
    _ = (edge.get("previous_status"), edge.get("observed_at_ms"))
    session_id = edge.get("session_id")
    if not isinstance(session_id, str) or session_id == "":
        return None
    return TurnFact(
        slot_id=_slot_id(edge.get("slot_id")),
        session_id=session_id,
        live_status=_text(edge.get("status")),
        turn_outcome=_optional_text(edge, "turn_outcome"),
        failure_origin=_optional_text(edge, "failure_origin"),
        origin=_origin(edge),
        response_id=_response_id(edge),
    )


def _response_id(edge: Mapping[str, object]) -> str | None:
    for name in ("turn_response_id", "response_id"):
        value = edge.get(name)
        if isinstance(value, str) and value != "":
            return value
    return None


def _slot_id(value: object) -> str:
    if isinstance(value, str) and value != "":
        return value
    return ""


def _text(value: object) -> str | None:
    if isinstance(value, str):
        return value
    return None


def _optional_text(edge: Mapping[str, object], name: str) -> str | None:
    """Copy a string field only when the edge contains it. Other values stay absent."""
    if name not in edge:
        return None
    return _text(edge[name])


def _origin(edge: Mapping[str, object]) -> str | None:
    """Store ``archive`` when the origin text contains it. A missing origin stays missing."""
    if "origin" not in edge:
        return None
    value = edge["origin"]
    if not isinstance(value, str):
        return None
    if "archive" in value:
        return "archive"
    return value
