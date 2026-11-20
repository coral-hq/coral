"""A run-stream client for tests: parses each server-sent event and applies it as a browser would.

Each chunk the stream yields is one whole event. A snapshot replaces the view, an entry
must carry the next seq and its patch is applied, a ``run`` frame replaces the header.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from typing import Any

from pydantic import JsonValue

from coral.runview.patch import apply_view_patch, stored_view_patch

DONE = "[DONE]"


@dataclass(frozen=True)
class Event:
    """One server-sent event: its ``event`` and ``id`` lines and its parsed ``data``."""

    event: str | None
    id: int | None
    data: Any

    @property
    def kind(self) -> str:
        return DONE if self.data == DONE else self.data["type"]


def parse_event(chunk: str) -> Event:
    assert chunk.endswith("\n\n"), chunk
    event = event_id = data = None
    for line in chunk[:-2].split("\n"):
        name, _, value = line.partition(": ")
        if name == "event":
            event = value
        elif name == "id":
            event_id = int(value)
        elif name == "data":
            data = value if value == DONE else json.loads(value)
        else:
            raise AssertionError(f"unexpected line {line!r}")
    return Event(event=event, id=event_id, data=data)


def parse_body(body: str) -> list[Event]:
    """Every event of a whole response body."""
    return [parse_event(f"{part}\n\n") for part in body.split("\n\n") if part]


@dataclass
class StreamClient:
    """
    What a client holds: the view, the last seq it applied and the run header.

    An entry that is not the next seq fails at once, so a gap or a repeat never passes;
    so does a ``run`` header older than the last header or than an entry already sent.
    """

    view: dict[str, JsonValue] | None = None
    last_seq: int | None = None
    header: dict[str, Any] | None = None
    events: list[Event] = field(default_factory=list)
    entries: list[int] = field(default_factory=list)
    done: bool = False
    # The newest run version among the entries taken.
    rows_version: int = 0

    def take(self, chunk: str) -> Event:
        event = parse_event(chunk)
        self.events.append(event)
        if event.kind == DONE:
            assert event.event is None and event.id is None
            self.done = True
            return event
        data = event.data
        assert event.event == data["type"]
        if event.kind == "snapshot":
            assert event.id == data["seq"]
            self.view, self.last_seq, self.header = data["view"], data["seq"], data["run"]
        elif event.kind == "entry":
            assert event.id == data["seq"]
            assert self.last_seq is not None and data["seq"] == self.last_seq + 1, (
                self.last_seq,
                data["seq"],
            )
            if self.view is not None:
                self.view = apply_view_patch(
                    self.view, stored_view_patch(json.dumps(data["patch"]))
                )
            self.last_seq = data["seq"]
            self.entries.append(data["seq"])
            self.rows_version = max(self.rows_version, data["run_version"])
        else:
            assert event.id is None, event
            if event.kind == "run":
                newest = max(
                    self.rows_version, 0 if self.header is None else self.header["version"]
                )
                assert data["version"] >= newest, (data["version"], newest)
                self.header = {key: value for key, value in data.items() if key != "type"}
        return event

    def kinds(self) -> list[str]:
        return [event.kind for event in self.events]

    def of_kind(self, kind: str) -> list[Event]:
        return [event for event in self.events if event.kind == kind]


async def pump(frames: AsyncIterator[str], client: StreamClient) -> None:
    """Feed every frame to ``client`` until the stream ends."""
    async for chunk in frames:
        client.take(chunk)


async def read_until(
    frames: AsyncIterator[str],
    client: StreamClient,
    until: Callable[[StreamClient], bool],
    *,
    timeout_s: float,
) -> None:
    """Feed frames to ``client`` until ``until`` holds; the stream must not end first."""
    async with asyncio.timeout(timeout_s):
        while not until(client):
            client.take(await anext(frames))


async def never_disconnected() -> bool:
    return False


class FakeTime:
    """
    A monotonic clock and a stream wait the test drives: a wait whose event is not set
    moves the clock by its whole timeout at once.
    """

    def __init__(self, start: float = 1_000.0) -> None:
        self.start = self.now = start

    def __call__(self) -> float:
        return self.now

    @property
    def elapsed(self) -> float:
        return self.now - self.start

    def advance(self, seconds: float) -> None:
        self.now += seconds

    async def wait(self, event: asyncio.Event, timeout: float) -> None:
        if not event.is_set():
            self.now += timeout
        await asyncio.sleep(0)
