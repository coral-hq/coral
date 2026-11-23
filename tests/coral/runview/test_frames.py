"""Run-stream frames: their fields, their union and their server-sent-event form."""

from __future__ import annotations

import json
from typing import Any

import pytest
from pydantic import TypeAdapter, ValidationError

from coral.engine.projection import RunView
from coral.engine.types import JsonPatch, PauseCause
from coral.runview.types import (
    DONE_FRAME,
    PROTOCOL,
    VIEW_VERSION,
    EntryFrame,
    HeartbeatFrame,
    ResyncFrame,
    RunFrame,
    RunHeader,
    RunStreamFrame,
    SnapshotFrame,
    StreamFrame,
    format_sse,
)

HEADER = RunHeader(
    status="paused",
    pause_reason="user",
    version=4,
    finished_at=None,
    allowed_actions=("resume", "cancel"),
    load_error=None,
)
VIEW = RunView(status="paused", causes=(PauseCause(reason="user", detail="user", subject=""),))


def _snapshot(**fields: Any) -> SnapshotFrame:
    values: dict[str, Any] = {
        "seq": 7,
        "run_version": 4,
        "log_version": 1,
        "run": HEADER,
        "view": VIEW,
    }
    values.update(fields)
    return SnapshotFrame(**values)


def _entry(**fields: Any) -> EntryFrame:
    values: dict[str, Any] = {
        "seq": 8,
        "run_version": 5,
        "kind": "engine.resume_run",
        "actor_kind": "user",
        "actor": "alice",
        "node_id": None,
        "scope_key": None,
        "at_us": 1_767_268_800_000_000,
        "rejected": None,
        "patch": (
            JsonPatch(op="replace", path="/status", value="running"),
            JsonPatch(op="remove", path="/causes/0"),
        ),
    }
    values.update(fields)
    return EntryFrame(**values)


FRAMES: list[StreamFrame] = [
    _snapshot(),
    _entry(),
    RunFrame(**HEADER.model_dump()),
    ResyncFrame(reason="cursor_unknown"),
    HeartbeatFrame(),
]


def _lines(frame: StreamFrame) -> list[str]:
    event = format_sse(frame)
    assert event.endswith("\n\n")
    return event[:-2].split("\n")


@pytest.mark.parametrize(("frame", "event_id"), [(FRAMES[0], "7"), (FRAMES[1], "8")])
def test_snapshot_and_entry_events_carry_their_seq_as_the_event_id(
    frame: StreamFrame, event_id: str
) -> None:
    assert _lines(frame)[:2] == [f"event: {frame.type}", f"id: {event_id}"]


@pytest.mark.parametrize("frame", FRAMES[2:])
def test_run_resync_and_heartbeat_events_carry_no_id(frame: StreamFrame) -> None:
    lines = _lines(frame)

    assert lines[0] == f"event: {frame.type}"
    assert not any(line.startswith("id:") for line in lines)


@pytest.mark.parametrize("frame", FRAMES)
def test_every_event_has_one_compact_data_line_repeating_its_type(frame: StreamFrame) -> None:
    data_lines = [line for line in _lines(frame) if line.startswith("data: ")]

    (data,) = data_lines
    payload = data.removeprefix("data: ")
    assert payload == json.dumps(json.loads(payload), separators=(",", ":"), ensure_ascii=False)
    assert json.loads(payload) == frame.model_dump(mode="json")
    assert json.loads(payload)["type"] == frame.type
    assert len(_lines(frame)) == len(data_lines) + (
        2 if frame.type in {"snapshot", "entry"} else 1
    )


def test_line_breaks_in_frame_text_stay_inside_the_one_data_line() -> None:
    frame = _entry(actor="a\nb\rc\r\nd")

    (data,) = [line for line in _lines(frame) if line.startswith("data: ")]

    assert json.loads(data.removeprefix("data: "))["actor"] == "a\nb\rc\r\nd"
    assert "\r" not in format_sse(frame)


BREAKS = "a\nb\rc\r\nd\n\ndata: x\n"


@pytest.mark.parametrize(
    "frame",
    [
        *(_entry(**{field: BREAKS}) for field in ("kind", "node_id", "scope_key", "rejected")),
        _entry(patch=(JsonPatch(op="add", path=f"/{BREAKS}", value={BREAKS: [BREAKS]}),)),
        _snapshot(view=RunView(open_gates=(BREAKS,))),
        _snapshot(view=RunView(causes=(PauseCause(reason="user", detail=BREAKS, subject=""),))),
    ],
)
def test_line_breaks_in_any_text_field_cannot_add_lines_to_the_event(frame: StreamFrame) -> None:
    lines = format_sse(frame)[:-2].replace("\r\n", "\n").replace("\r", "\n").split("\n")

    assert [line.split(":", 1)[0] for line in lines] == ["event", "id", "data"]
    assert json.loads(lines[-1].removeprefix("data: ")) == frame.model_dump(mode="json")


def test_the_end_of_a_stream_is_the_done_event() -> None:
    assert DONE_FRAME == "data: [DONE]\n\n"


@pytest.mark.parametrize("frame", FRAMES)
def test_every_frame_reads_back_through_the_frame_union(frame: StreamFrame) -> None:
    adapter: TypeAdapter[StreamFrame] = TypeAdapter(RunStreamFrame)

    assert adapter.validate_json(frame.model_dump_json()) == frame
    assert type(adapter.validate_python(frame.model_dump())) is type(frame)


def test_a_snapshot_names_the_protocol_and_view_shape_it_was_built_for() -> None:
    frame = _snapshot()

    assert (frame.protocol, frame.view_version) == (PROTOCOL, VIEW_VERSION) == (1, 1)


def test_a_snapshot_without_a_view_says_why_and_one_with_a_view_does_not() -> None:
    unloadable = _snapshot(view=None, view_error="engine.load_failed")

    assert unloadable.view is None
    with pytest.raises(ValidationError, match="view_error"):
        _snapshot(view=None)
    with pytest.raises(ValidationError, match="view_error"):
        _snapshot(view_error="engine.load_failed")


def test_an_entry_carries_its_patch_as_stored_with_a_null_remove_value() -> None:
    data = json.loads(format_sse(_entry()).split("data: ", 1)[1])

    assert data["patch"] == [
        {"op": "replace", "path": "/status", "value": "running"},
        {"op": "remove", "path": "/causes/0", "value": None},
    ]
    assert _entry(patch=()).patch == ()


def test_a_run_frame_is_the_header_with_its_type() -> None:
    frame = RunFrame(**HEADER.model_dump())

    assert frame.model_dump() == {**HEADER.model_dump(), "type": "run"}


@pytest.mark.parametrize(
    ("build", "field"),
    [
        (lambda: _entry(seq=0), "seq"),
        (lambda: _entry(actor_kind="robot"), "actor_kind"),
        (lambda: _snapshot(seq=-1), "seq"),
        (lambda: ResyncFrame.model_validate({"reason": "cursor_lost"}), "reason"),
        (lambda: RunHeader(**{**HEADER.model_dump(), "status": "stopped"}), "status"),
        (lambda: RunHeader(**{**HEADER.model_dump(), "allowed_actions": ("restart",)}), "allowed"),
        (lambda: HeartbeatFrame.model_validate({"extra": 1}), "extra"),
    ],
)
def test_frames_refuse_values_outside_the_protocol(build: Any, field: str) -> None:
    with pytest.raises(ValidationError, match=field):
        build()


def test_frames_are_frozen() -> None:
    with pytest.raises(ValidationError):
        HeartbeatFrame().type = "run"  # type: ignore[misc]


def test_the_frame_union_schema_maps_each_type_to_its_frame() -> None:
    schema = TypeAdapter(RunStreamFrame).json_schema(mode="serialization")

    assert set(schema["discriminator"]["mapping"]) == {
        "snapshot",
        "entry",
        "run",
        "resync",
        "heartbeat",
    }
    assert {"RunView", "PauseCause", "RunHeader", "JsonPatch"} <= set(schema["$defs"])


@pytest.mark.parametrize(
    "name",
    ["SnapshotFrame", "EntryFrame", "RunFrame", "ResyncFrame", "HeartbeatFrame", "RunHeader"],
)
def test_every_frame_field_is_required_in_the_schema_since_every_one_is_sent(name: str) -> None:
    frame = TypeAdapter(RunStreamFrame).json_schema(mode="serialization")["$defs"][name]

    assert set(frame["required"]) == set(frame["properties"])
    if name != "RunHeader":
        assert "type" in frame["required"]
