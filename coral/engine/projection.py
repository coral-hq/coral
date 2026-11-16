"""Project a run down to the fields observers diff, and the patch between two views."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, JsonValue

from coral.engine.types import (
    Activation,
    ActivationOutcome,
    ActivationStatus,
    JsonPatch,
    LoopCounter,
    PauseCause,
    RunState,
    RunStatus,
    Slot,
    SlotStatus,
)


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class ActivationView(_Frozen):
    id: str
    status: ActivationStatus
    outcome: ActivationOutcome | None = None


class SlotView(_Frozen):
    id: str
    status: SlotStatus
    pending_input: bool
    drift: bool


class LoopPassView(_Frozen):
    back_arrow_id: str
    item_path: tuple[str, ...] = ()
    iteration_path: tuple[str, ...] = ()
    pass_index: int


class RunView(_Frozen):
    status: RunStatus | None = None
    causes: tuple[PauseCause, ...] = ()
    activations: tuple[ActivationView, ...] = ()
    slots: tuple[SlotView, ...] = ()
    open_decisions: tuple[str, ...] = ()
    open_gates: tuple[str, ...] = ()
    loop_pass_indexes: tuple[LoopPassView, ...] = ()
    armed_timer_keys: tuple[str, ...] = ()


def project(state: RunState) -> RunView:
    """Return the observable subset of a run."""
    return RunView(
        status=state.status,
        causes=state.causes,
        activations=tuple(_activation_view(item) for item in state.activations),
        slots=tuple(_slot_view(item) for item in state.slots),
        open_decisions=tuple(
            item.activation_id for item in state.decisions if item.status != "decided"
        ),
        open_gates=tuple(item.token for item in state.gates if item.status == "open"),
        loop_pass_indexes=tuple(_loop_view(item) for item in state.loop_counters),
        armed_timer_keys=tuple(item.key for item in state.timers),
    )


def view_patch(before: RunView, after: RunView) -> tuple[JsonPatch, ...]:
    """JSON Patch operations that turn ``before`` into ``after``. Empty when equal."""
    return tuple(
        _diff(
            before.model_dump(mode="json"),
            after.model_dump(mode="json"),
            "",
        )
    )


def _activation_view(activation: Activation) -> ActivationView:
    return ActivationView(id=activation.id, status=activation.status, outcome=activation.outcome)


def _slot_view(slot: Slot) -> SlotView:
    return SlotView(
        id=slot.id,
        status=slot.status,
        pending_input=slot.pending_input,
        drift=slot.drift,
    )


def _loop_view(counter: LoopCounter) -> LoopPassView:
    return LoopPassView(
        back_arrow_id=counter.back_arrow_id,
        item_path=counter.item_path,
        iteration_path=counter.iteration_path,
        pass_index=counter.pass_index,
    )


def _diff(before: JsonValue, after: JsonValue, path: str) -> list[JsonPatch]:
    if before == after:
        return []
    if isinstance(before, dict) and isinstance(after, dict):
        ops: list[JsonPatch] = []
        for key, value in before.items():
            pointer = f"{path}/{_escape(key)}"
            if key not in after:
                ops.append(JsonPatch(op="remove", path=pointer))
            else:
                ops.extend(_diff(value, after[key], pointer))
        for key, value in after.items():
            if key not in before:
                ops.append(JsonPatch(op="add", path=f"{path}/{_escape(key)}", value=value))
        return ops
    if isinstance(before, list) and isinstance(after, list):
        ops = []
        shared = min(len(before), len(after))
        for index in range(shared):
            ops.extend(_diff(before[index], after[index], f"{path}/{index}"))
        if len(after) > len(before):
            for index in range(len(before), len(after)):
                ops.append(JsonPatch(op="add", path=f"{path}/{index}", value=after[index]))
        else:
            for index in range(len(before) - 1, len(after) - 1, -1):
                ops.append(JsonPatch(op="remove", path=f"{path}/{index}"))
        return ops
    return [JsonPatch(op="replace", path=path or "/", value=after)]


def _escape(token: str) -> str:
    return token.replace("~", "~0").replace("/", "~1")
