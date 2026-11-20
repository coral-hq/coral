"""Alert payload validation, owner normalization and the fail-closed generation rule."""

from __future__ import annotations

from typing import Any, get_args

import pytest
from pydantic import ValidationError

from coral.alerts.types import (
    LOCAL_USER_ID,
    AlertAction,
    AlertKindName,
    AlertPayload,
    generation_matches,
    is_owner,
    normalize_owner,
)
from coral.db.enum_codecs import ALERT_KIND
from coral.omni.protocols import Viewer


def _payload(**overrides: Any) -> dict[str, Any]:
    fields: dict[str, Any] = {
        "title": "Approval needed",
        "message": "Approve the merge?",
        "run_title": "Fix the parser",
        "actions": ("answer", "open_run"),
        "deep_link": "/workflows/runs/r1?node=approve&panel=gate",
    }
    fields.update(overrides)
    return fields


def test_kind_names_match_the_stored_codes() -> None:
    assert set(get_args(AlertKindName)) == set(ALERT_KIND)
    assert set(get_args(AlertAction)) == {"answer", "open_run", "mark_read", "resume", "cancel"}


def test_payload_round_trips_through_json_and_is_frozen() -> None:
    payload = AlertPayload.model_validate(
        _payload(
            step_label="Approve merge",
            node_id="approve",
            approve_link="/approve/anchor/coral_gate_" + "0" * 32,
            elicitation_id="coral_gate_" + "0" * 32,
            session_id="a" * 32,
            outcomes=("approve", "reject"),
        )
    )

    assert AlertPayload.model_validate_json(payload.model_dump_json()) == payload
    with pytest.raises(ValidationError):
        payload.title = "Changed"  # type: ignore[misc]


def test_payload_refuses_an_extra_key() -> None:
    with pytest.raises(ValidationError, match="extra"):
        AlertPayload.model_validate(_payload(note="agent text"))


@pytest.mark.parametrize(
    ("field", "limit"),
    [
        ("title", 120),
        ("message", 280),
        ("run_title", 256),
        ("step_label", 128),
        ("node_id", 64),
        ("deep_link", 512),
        ("approve_link", 128),
        ("elicitation_id", 64),
        ("session_id", 64),
        ("pause_reason", 32),
    ],
)
def test_payload_refuses_an_over_length_field(field: str, limit: int) -> None:
    assert getattr(AlertPayload.model_validate(_payload(**{field: "x" * limit})), field)
    with pytest.raises(ValidationError, match=field):
        AlertPayload.model_validate(_payload(**{field: "x" * (limit + 1)}))


def test_payload_bounds_outcomes_and_actions() -> None:
    assert len(AlertPayload.model_validate(_payload(outcomes=("o",) * 16)).outcomes) == 16
    with pytest.raises(ValidationError, match="outcomes"):
        AlertPayload.model_validate(_payload(outcomes=("o",) * 17))
    assert AlertPayload.model_validate(_payload(outcomes=("x" * 128,))).outcomes == ("x" * 128,)
    with pytest.raises(ValidationError, match="outcomes"):
        AlertPayload.model_validate(_payload(outcomes=("x" * 129,)))
    with pytest.raises(ValidationError, match="actions"):
        AlertPayload.model_validate(_payload(actions=("extend",)))


def test_normalize_owner_folds_the_local_user_into_none() -> None:
    assert LOCAL_USER_ID == "local"
    assert normalize_owner(None) is None
    assert normalize_owner(LOCAL_USER_ID) is None
    assert normalize_owner("alice") == "alice"


@pytest.mark.parametrize(
    ("recorded", "viewer", "matches"),
    [
        (None, Viewer("alice"), True),
        (None, Viewer("alice", "g1", check_generation=True), True),
        (None, Viewer(None), True),
        # A recorded generation needs a request that proves it.
        ("g1", Viewer("alice", "g1", check_generation=True), True),
        ("g1", Viewer("alice", "g2", check_generation=True), False),
        ("g1", Viewer("alice", None, check_generation=True), False),
        ("g1", Viewer("alice", "g1", check_generation=False), False),
        ("g1", Viewer("alice"), False),
        ("g1", Viewer(None), False),
    ],
)
def test_generation_matches_fails_closed(
    recorded: str | None, viewer: Viewer, matches: bool
) -> None:
    assert generation_matches(recorded, viewer) is matches


@pytest.mark.parametrize(
    ("owner", "recorded", "viewer", "owns"),
    [
        ("alice", None, Viewer("alice"), True),
        ("alice", None, Viewer("bob"), False),
        (None, None, Viewer(None), True),
        (LOCAL_USER_ID, None, Viewer(None), True),
        (None, None, Viewer(LOCAL_USER_ID), True),
        (None, None, Viewer("alice"), False),
        ("alice", None, Viewer(None), False),
        ("alice", "g1", Viewer("alice", "g1", check_generation=True), True),
        ("alice", "g1", Viewer("alice", "g2", check_generation=True), False),
        ("alice", "g1", Viewer("alice", "g1"), False),
        ("alice", "g1", Viewer("bob", "g1", check_generation=True), False),
    ],
)
def test_is_owner_folds_the_local_user_and_fails_closed_on_a_recorded_generation(
    owner: str | None, recorded: str | None, viewer: Viewer, owns: bool
) -> None:
    assert is_owner(owner, recorded, viewer) is owns
