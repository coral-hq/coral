"""Run-stream frames, the run header and the names they use. Pure: no I/O.

A stream sends one ``snapshot`` (its id the head seq), one ``entry`` per run-log row
(its id the row's seq) and id-less ``run``, ``resync`` and ``heartbeat`` frames, so a
client's ``Last-Event-ID`` is always the last seq it holds.
"""

from __future__ import annotations

from typing import Annotated, Final, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from coral.engine.projection import RunView
from coral.engine.types import JsonPatch

# Bumped when the frames change, or when ``RunView`` changes shape.
PROTOCOL: Final = 1
VIEW_VERSION: Final = 1

RunAction = Literal["pause", "resume", "retry", "cancel"]
# Names of the stored run-row codes; the engine's own names are a subset.
RunStatusName = Literal["starting", "running", "paused", "completed", "failed", "cancelled"]
PauseReasonName = Literal[
    "gate",
    "budget",
    "plan_limit",
    "rejected_calls",
    "infra",
    "liveness",
    "user",
    "authority_revoked",
    "merge_conflict",
    "failure_path",
    "engine_upgrade",
    "drift",
    "auth",
]
ActorKindName = Literal["engine", "orchestrator", "step_agent", "user", "simulator"]
# A run the bridge cannot load: its stored rows or pinned graph do not decode.
LoadError = Literal["engine.load_failed"]
ResyncReason = Literal["cursor_unknown", "cursor_invalid", "replay_too_long", "row_unreadable"]

FINISHED_RUN_STATUSES: frozenset[RunStatusName] = frozenset({"completed", "failed", "cancelled"})
DONE_FRAME: Final = "data: [DONE]\n\n"


class _Frozen(BaseModel):
    # Defaulted fields are always sent, so the schema lists them as required.
    model_config = ConfigDict(
        frozen=True, extra="forbid", json_schema_serialization_defaults_required=True
    )


class RunHeader(_Frozen):
    """The run row as clients see it; a finished row wins over what the view says."""

    status: RunStatusName
    pause_reason: PauseReasonName | None
    version: int = Field(ge=0)
    finished_at: int | None
    allowed_actions: tuple[RunAction, ...]
    load_error: LoadError | None


class SnapshotFrame(_Frozen):
    """The whole view at head ``seq``; ``view`` is ``None`` only for a run that cannot load."""

    type: Literal["snapshot"] = "snapshot"
    protocol: Literal[1] = PROTOCOL
    view_version: Literal[1] = VIEW_VERSION
    seq: int = Field(ge=0)
    run_version: int = Field(ge=0)
    log_version: int = Field(ge=0)
    run: RunHeader
    view: RunView | None
    view_error: LoadError | None = None

    @model_validator(mode="after")
    def _view_or_its_error(self) -> SnapshotFrame:
        if (self.view is None) == (self.view_error is None):
            raise ValueError("a snapshot has a view or a view_error, never both or neither")
        return self


class EntryFrame(_Frozen):
    """One run-log row without its body; ``patch`` is the stored view patch, or empty."""

    type: Literal["entry"] = "entry"
    seq: int = Field(ge=1)
    run_version: int = Field(ge=0)
    kind: str
    actor_kind: ActorKindName
    actor: str | None
    node_id: str | None
    scope_key: str | None
    at_us: int
    rejected: str | None
    patch: tuple[JsonPatch, ...] = ()


class RunFrame(RunHeader):
    """The run header again, sent when the row changes without a view patch."""

    type: Literal["run"] = "run"


class ResyncFrame(_Frozen):
    """The cursor cannot be replayed; a fresh ``snapshot`` follows."""

    type: Literal["resync"] = "resync"
    reason: ResyncReason


class HeartbeatFrame(_Frozen):
    type: Literal["heartbeat"] = "heartbeat"


StreamFrame = SnapshotFrame | EntryFrame | RunFrame | ResyncFrame | HeartbeatFrame
RunStreamFrame = Annotated[StreamFrame, Field(discriminator="type")]


def format_sse(frame: StreamFrame) -> str:
    """The frame as one server-sent event: ``event``, an ``id`` when it has a seq, ``data``.

    The data is one compact JSON line: JSON escapes line breaks inside strings.
    """
    event_id = frame.seq if isinstance(frame, SnapshotFrame | EntryFrame) else None
    id_line = "" if event_id is None else f"id: {event_id}\n"
    return f"event: {frame.type}\n{id_line}data: {frame.model_dump_json()}\n\n"


__all__ = [
    "DONE_FRAME",
    "FINISHED_RUN_STATUSES",
    "PROTOCOL",
    "VIEW_VERSION",
    "ActorKindName",
    "EntryFrame",
    "HeartbeatFrame",
    "LoadError",
    "PauseReasonName",
    "ResyncFrame",
    "ResyncReason",
    "RunAction",
    "RunFrame",
    "RunHeader",
    "RunStatusName",
    "RunStreamFrame",
    "SnapshotFrame",
    "StreamFrame",
    "format_sse",
]
