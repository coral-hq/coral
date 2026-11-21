"""A finished work row as the one engine input it feeds back, or none.

Rows are fed after they finish (finish-then-fold): the engine receipt marks an
effect consumed, so feeding a row again is a no-op. Only the fields the engine
reads are kept from a result.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from pydantic import JsonValue

from coral.bridge.mapping import DECISION_ITEM, FED_KINDS, RECOVERY_RESTART
from coral.db.enum_codecs import WorkKind, WorkStatus
from coral.engine import types as engine
from coral.engine.machines.slot import find_slot
from coral.gates.ids import GATE_ITEM
from coral.queue.drainer import FinishedWork
from coral.queue.run_effects import MAX_ERROR_CODE_CHARS
from coral.stores.protocols import WorkItem

# The drainer's code for an item whose retries ran out; its result names the last code.
EXHAUSTED = "infra.transient"
# Rows the engine does not complete; a failure pauses the run with this prefix. A
# gate's rows carry engine effects, but their subject is a visit, not a slot.
BRIDGE_ITEMS = frozenset({"anchor", "orchestrator", DECISION_ITEM, GATE_ITEM})
# The completion fields each fed kind's engine machine reads, with their JSON types.
_FED_FIELDS: Mapping[str, Mapping[str, tuple[type, ...]]] = {
    "create_session": {"session_id": (str,), "role": (str,), "generation": (int,)},
    "send_input": {"session_id": (str,), "stable_id": (str,)},
    "nudge": {"session_id": (str,), "stable_id": (str,)},
    "close_slot": {
        "pending_input": (bool,),
        "queued_input": (bool,),
        "post_accept_edits": (bool,),
        "commit": (str, type(None)),
        "empty": (bool, type(None)),
    },
    "retry_step": {
        "salvage_ref": (str, type(None)),
        "salvage_commit": (str, type(None)),
        "head_verified": (bool,),
        "head": (str, type(None)),
    },
}
_MAX_FED_TEXT_CHARS = 128


def fed_payload(kind: str, result: Mapping[str, Any] | None) -> dict[str, JsonValue]:
    """The completion payload of a ``kind`` effect: the known fields of ``result``, bounded."""
    fields = _FED_FIELDS.get(kind, {})
    payload: dict[str, JsonValue] = {}
    given = result or {}
    for name, types in fields.items():
        value = given.get(name)
        if name not in given or not isinstance(value, types):
            continue
        # ``bool`` is an ``int``, but a count never takes a flag.
        if isinstance(value, bool) and bool not in types:
            continue
        payload[name] = value[:_MAX_FED_TEXT_CHARS] if isinstance(value, str) else value
    return payload


def feedback_input(finished: FinishedWork) -> engine.Input | None:
    """
    The engine input a finished row feeds, or ``None`` for one the engine does not track.

    Timers, signals, abandoned rows and cancels are not fed. A bridge row's failure
    pauses the run, ``infra`` when its retries ran out, else ``failure_path``.
    """
    item = finished.item
    if item.kind != int(WorkKind.EFFECT):
        return None
    if finished.status not in (int(WorkStatus.SUCCEEDED), int(WorkStatus.FAILED)):
        return None
    payload = _payload(item)
    bridge_item = payload.get("bridge_item")
    if isinstance(bridge_item, str) and bridge_item in BRIDGE_ITEMS:
        if finished.status == int(WorkStatus.SUCCEEDED):
            return None
        reason = "infra" if finished.error_code == EXHAUSTED else "failure_path"
        return engine.PauseRun(reason=reason, detail=f"{bridge_item}:{_failure_code(finished)}")
    kind = payload.get("engine_kind")
    effect_key = payload.get("effect_key")
    if kind not in FED_KINDS or not isinstance(effect_key, str):
        return None
    if finished.status == int(WorkStatus.SUCCEEDED):
        return engine.EffectCompleted(
            effect_key=effect_key, payload=fed_payload(str(kind), finished.result)
        )
    return engine.EffectFailed(
        effect_key=effect_key,
        code=_failure_code(finished),
        retryable=finished.error_code == EXHAUSTED,
    )


def abandoned_restart(item: WorkItem, state: engine.RunState) -> engine.EffectFailed | None:
    """
    An abandoned restart of the slot's current generation, as the failure that ends it.

    Nothing else would end the restarting pause, so the resync feeds it with the row's
    own code; an abandoned restart of an older generation (a newer retry owns the slot)
    and every other abandoned row feed nothing.
    """
    if item.kind != int(WorkKind.EFFECT) or item.status != int(WorkStatus.ABANDONED):
        return None
    payload = _payload(item)
    effect_key = payload.get("effect_key")
    generation = payload.get("generation")
    if (
        payload.get("effect_type") != RECOVERY_RESTART
        or payload.get("engine_kind") != "retry_step"
        or not isinstance(effect_key, str)
        or not isinstance(generation, int)
    ):
        return None
    effect = next((found for found in state.effects if found.effect_key == effect_key), None)
    slot = None if effect is None else find_slot(state, effect.subject)
    if slot is None or slot.session_generation != generation:
        return None
    code = (item.error_code or "effect.abandoned")[:MAX_ERROR_CODE_CHARS]
    return engine.EffectFailed(effect_key=effect_key, code=code, retryable=False)


def decision_of(item: WorkItem) -> str | None:
    """The decision a message to the orchestrator is about; ``None`` for any other row."""
    payload = _payload(item)
    decision_id = payload.get("decision_id")
    if payload.get("bridge_item") != DECISION_ITEM or not isinstance(decision_id, str):
        return None
    return decision_id


def gate_of(item: WorkItem) -> str | None:
    """The visit row a gate's publish or withdraw is about; ``None`` for any other row."""
    payload = _payload(item)
    visit_id = payload.get("visit_id")
    if payload.get("bridge_item") != GATE_ITEM or not isinstance(visit_id, str):
        return None
    return visit_id


def finished_from_row(item: WorkItem) -> FinishedWork:
    """A stored row's outcome as the drainer handed it to the finished hook."""
    result = _json_object(item.result)
    return FinishedWork(item=item, status=item.status, error_code=item.error_code, result=result)


def _failure_code(finished: FinishedWork) -> str:
    """The code that names a failure: the last one tried when the retries ran out."""
    code = finished.error_code
    if code == EXHAUSTED:
        last = (finished.result or {}).get("last_error_code")
        code = last if isinstance(last, str) and last else EXHAUSTED
    return (code or "effect.failed")[:MAX_ERROR_CODE_CHARS]


def _payload(item: WorkItem) -> dict[str, Any]:
    return _json_object(item.payload) or {}


def _json_object(text: str | None) -> dict[str, Any] | None:
    if not text:
        return None
    try:
        value = json.loads(text)
    except ValueError:
        return None
    return value if isinstance(value, dict) else None


__all__ = [
    "BRIDGE_ITEMS",
    "EXHAUSTED",
    "abandoned_restart",
    "decision_of",
    "fed_payload",
    "feedback_input",
    "finished_from_row",
    "gate_of",
]
