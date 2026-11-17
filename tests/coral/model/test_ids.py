"""Deterministic ids the engine derives from an effect key."""

from __future__ import annotations

from collections.abc import Callable

import pytest

from coral.model.ids import (
    anchor_session_id,
    derived_id,
    effect_message_id,
    effect_op_key,
    effect_session_id,
)
from coral.workspace.ops import validate_op_key, validate_record_id

WORKSPACE = 7
EFFECT_KEY = "a" * 32 + ":3:close_slot:slot-1"

_EFFECT_IDS: dict[str, Callable[[int, str], str]] = {
    "session": effect_session_id,
    "message": effect_message_id,
    "op-key": effect_op_key,
}


def test_effect_ids_keep_their_stored_values() -> None:
    # These ids are stored (conversation and item ids, Coral-Op trailers, salvage refs),
    # so a change to the derivation would orphan every in-flight run's records.
    assert effect_session_id(WORKSPACE, EFFECT_KEY) == "e16133a872be6d66286f9529182b8d5c"
    assert effect_message_id(WORKSPACE, EFFECT_KEY) == "eedecd55cb808b20e054fdcfe44329c7"
    assert effect_op_key(WORKSPACE, EFFECT_KEY) == "e39a726209460053624548fadd5dc8ac"
    assert effect_op_key(WORKSPACE, EFFECT_KEY, "commit") == "1eca496203beeab9194fb39676dfd121"


def test_effect_ids_are_derived_ids_of_their_own_kind() -> None:
    assert effect_session_id(WORKSPACE, EFFECT_KEY) == derived_id("coral-session", "7", EFFECT_KEY)
    assert effect_message_id(WORKSPACE, EFFECT_KEY) == derived_id("coral-message", "7", EFFECT_KEY)
    assert effect_op_key(WORKSPACE, EFFECT_KEY) == derived_id("coral-op", "7", EFFECT_KEY)
    # One effect yields a distinct id per kind, so a session id never doubles as an op key.
    derived = {derive(WORKSPACE, EFFECT_KEY) for derive in _EFFECT_IDS.values()}
    assert len(derived) == len(_EFFECT_IDS)


@pytest.mark.parametrize("kind", sorted(_EFFECT_IDS))
def test_effect_ids_are_stable_and_scoped_to_workspace_and_effect(kind: str) -> None:
    derive = _EFFECT_IDS[kind]
    value = derive(WORKSPACE, EFFECT_KEY)

    assert value == derive(WORKSPACE, EFFECT_KEY)
    assert value != derive(WORKSPACE + 1, EFFECT_KEY)
    assert value != derive(WORKSPACE, EFFECT_KEY + "x")
    # 32 lowercase hex: an Omnigent conversation id and stable id, a K13 op key and record id.
    assert len(value) == 32 and int(value, 16) >= 0 and value == value.lower()
    validate_op_key(value)
    validate_record_id(value)


def test_an_op_key_qualifier_names_another_op_of_the_same_effect() -> None:
    plain = effect_op_key(WORKSPACE, EFFECT_KEY)
    commit = effect_op_key(WORKSPACE, EFFECT_KEY, "commit")

    assert commit == derived_id("coral-op", "7", EFFECT_KEY, "commit")
    assert commit != plain
    assert commit != effect_op_key(WORKSPACE, EFFECT_KEY, "salvage")
    validate_op_key(commit)


def test_the_anchor_id_differs_from_a_step_session_of_the_same_text() -> None:
    run_id = "b" * 32
    assert anchor_session_id(WORKSPACE, run_id) != effect_session_id(WORKSPACE, run_id)
