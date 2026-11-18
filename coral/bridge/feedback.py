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

from coral.bridge.mapping import FED_KINDS
from coral.db.enum_codecs import WorkKind, WorkStatus
from coral.engine import types as engine
from coral.queue.drainer import FinishedWork
from coral.queue.run_effects import MAX_ERROR_CODE_CHARS
from coral.stores.protocols import WorkItem

# The drainer's code for an item whose retries ran out; its result names the last code.
EXHAUSTED = "infra.transient"
# Bridge rows that are not engine effects; a failure pauses the run with this prefix.
BRIDGE_ITEMS = frozenset({"anchor", "orchestrator"})
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
    "fed_payload",
    "feedback_input",
    "finished_from_row",
]
