"""The run-view contract the web tests replay, recorded from the backend's own run stream.

One ``gated`` run whose ``implement`` step is done when ``pytest -q`` passes, driven through
the bridge on the in-memory stores: implement hands off, the gate is rejected (loop pass
2), implement hands off again, its owner pauses and resumes the run at the open gate, the
gate is approved and the run ends.

- ``live`` is one stream opened right after the start and read to the head after each
  scripted step, so its frames come in the order a live tail sends them: ``run`` frames
  among the entries, then ``[DONE]``. ``live_marks`` holds the seq at each milestone.
- ``resumed`` reconnects after the end with ``Last-Event-ID`` at the first open gate;
  ``final_snapshot`` is a fresh connect after the end.
- The details at each open gate and at the end, the pinned graph, the outcome and the
  pause copy complete it.

Each event is kept as its ``event``, ``id`` and ``data`` lines (``None`` for a line it
lacks), and ``live`` also as the raw text. Ids, clocks, prompt ids, spend and the host's
replies are fixed, and the stream's clock moves only while it waits, which it never does
here, so the output is stable.

Regenerate the checked-in file: ``uv run --no-sync python -m tests.coral.api.run_view_contract
--write`` (the web Prettier hook then formats it; the test compares parsed JSON).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import tempfile
from collections.abc import AsyncGenerator, AsyncIterator, Callable, Sequence
from pathlib import Path
from typing import Any

import yaml
from pydantic import JsonValue

from coral.alerts.rules import PAUSE_MESSAGES, row_pause_alert
from coral.alerts.types import AlertPayload
from coral.api.outcome import OutcomeDiffs, outcome_target, run_outcome
from coral.api.run_models import GateIntegrityOut, run_detail, run_header, run_spend
from coral.api.spend import CachedSpend
from coral.api.stream import STREAM_THREADS, RunStreamHub, StreamCursor, stream_cursor
from coral.bridge.executors import BoundedThreads
from coral.engine.projection import project
from coral.gates.integrity import GateIntegrityFacts, gate_integrity
from coral.omni.protocols import RunSpendTotals, Viewer
from coral.runview.actions import RunViewFacts
from coral.workspace.run_worktree import run_branch_name
from tests._helpers.polling import poll_until_async
from tests.budgets import budget
from tests.coral.api._stream_client import (
    FakeTime,
    StreamClient,
    never_disconnected,
    pump,
    read_until,
)
from tests.coral.bridge._gates import (
    CHANGE_TOKEN,
    CHANGE_TOKEN_AGAIN,
    IMPLEMENT_AGAIN,
    IMPLEMENT_FIRST,
    GateIds,
    answer,
    brief,
    complete,
)
from tests.coral.bridge._scripted_runs import accept
from tests.coral.bridge._world import USER, WORKSPACE, World, run_id_for, run_spec, start
from tests.coral.workflow_builders import fixture_text
from tests.coral.workspace._executor_fakes import (
    ChannelRequest,
    FakeChannels,
    FakeHostChannel,
    RecordingScopeRunner,
)

CONTRACT_PATH = (
    Path(__file__).resolve().parents[3] / "web/src/workflows/fixtures/runView.contract.json"
)
MODULE = "tests.coral.api.run_view_contract"
# A path a shell must quote: a space and an apostrophe.
REPO_PATH = "/home/alice/team's repo"
BASE_REF = "main"
BASE_COMMIT = "3f2a9c41d8e7b6a5f4e3d2c1b0a9f8e7d6c5b4a3"
HEAD_COMMIT = "9d8c7b6a5f4e3d2c1b0a9f8e7d6c5b4a3f2e1d0c"
# The run's changes as the host reports them; the right-to-left override is shown escaped.
DIFF_PATHS = ("tests/test_parser.py", "src/parser.py", "docs/release\u202enotes.md")
DIFF_INSERTIONS, DIFF_DELETIONS = 42, 7
EVIDENCE_COMMAND = "pytest -q"
REPORTS = (
    "Fixed the parser; pytest -q passes.",
    "Added the regression test you asked for; pytest -q passes.",
)
REJECT_NOTE = "Please add a regression test."
# The scripted milestones, in order; ``live_marks`` holds the seq the tail holds at each.
MILESTONES = (
    "implement_running",
    "gate1_open",
    "gate1_answered",
    "pass2_running",
    "gate2_open",
    "paused",
    "resumed",
    "gate2_answered",
    "finished",
)
# Each scripted step lands this long after the one before.
STEP_S = 60
SPEND = RunSpendTotals(
    usd=0.84,
    live_usd=0.91,
    input_tokens=182_000,
    output_tokens=12_400,
    total_tokens=194_400,
    cache_read_tokens=150_000,
    cache_creation_tokens=8_000,
    unpriced_models=(),
    sessions=3,
)
ALICE = Viewer(user_id=USER)
# A hang guard for every read of a stream.
TIMEOUT_S = budget(30)

SentEvent = dict[str, str | None]


def workflow_yaml() -> str:
    """The ``gated`` workflow, whose ``implement`` step is done when ``pytest -q`` passes."""
    document = yaml.safe_load(fixture_text("gated"))
    (implement,) = (node for node in document["nodes"] if node["id"] == "implement")
    implement["done_when"] = {"commands": [{"run": EVIDENCE_COMMAND}]}
    return yaml.safe_dump(document, sort_keys=False)


def worktree_path(run_id: str) -> str:
    """The run's worktree, in the repository's sibling ``-worktrees`` directory."""
    return f"{REPO_PATH}-worktrees/{run_branch_name(run_id).replace('/', '-')}"


def sent_event(chunk: str) -> SentEvent:
    """One event's ``event``, ``id`` and ``data`` lines as sent; ``None`` for a line it lacks."""
    assert chunk.endswith("\n\n"), chunk
    fields: SentEvent = {"event": None, "id": None, "data": None}
    for line in chunk[:-2].split("\n"):
        name, separator, value = line.partition(": ")
        assert separator and name in fields and fields[name] is None, line
        fields[name] = value
    return fields


def wire_event(event: SentEvent) -> str:
    """The event as it was sent: the inverse of :func:`sent_event`."""
    lines = (
        f"{name}: {event[name]}\n" for name in ("event", "id", "data") if event[name] is not None
    )
    return "".join(lines) + "\n"


def checked_in(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_or_check(contract: Any, path: Path, *, write: bool, module: str) -> int:
    """
    Write ``contract`` to ``path``, or check that the file holds it; 1 when it does not.

    It is written on one line: Prettier then keeps each object that fits on one line.
    """
    if write:
        text = json.dumps(contract, ensure_ascii=False) + "\n"
        path.write_text(text, encoding="utf-8")
        return 0
    if checked_in(path) != contract:
        print(f"{path} is out of date; rerun python -m {module} --write", file=sys.stderr)
        return 1
    return 0


def _hand_off(world: World, run_id: str, slot: str, report: str) -> None:
    """The step hands off done, its handoff is accepted and it closes: the gate opens."""
    world.bridge.commit_inputs(
        workspace_id=WORKSPACE, run_id=run_id, inputs=lambda _snapshot: accept(slot, report)
    )
    complete(world, run_id, "close_slot", slot, {})


def _script(world: World, run_id: str) -> tuple[tuple[str, Callable[[], object]], ...]:
    """Each milestone and the step that reaches it; the approve also ends the run."""
    bridge = world.bridge
    return (
        ("implement_running", lambda: brief(world, run_id, IMPLEMENT_FIRST)),
        ("gate1_open", lambda: _hand_off(world, run_id, IMPLEMENT_FIRST, REPORTS[0])),
        (
            "gate1_answered",
            lambda: answer(world, run_id, CHANGE_TOKEN, "reject", note=REJECT_NOTE),
        ),
        ("pass2_running", lambda: brief(world, run_id, IMPLEMENT_AGAIN)),
        ("gate2_open", lambda: _hand_off(world, run_id, IMPLEMENT_AGAIN, REPORTS[1])),
        # Paused at the open gate: the pill says "Paused", not "Needs you".
        ("paused", lambda: bridge.pause_run(workspace_id=WORKSPACE, run_id=run_id, actor=USER)),
        ("resumed", lambda: bridge.resume_run(workspace_id=WORKSPACE, run_id=run_id, actor=USER)),
        ("gate2_answered", lambda: answer(world, run_id, CHANGE_TOKEN_AGAIN, "approve")),
    )


def _detail(world: World, run_id: str) -> dict[str, Any]:
    """
    The run's detail as its route answers it, with a fixed spend read now, on a server that
    reports none of the gate label's facts.
    """
    unknown = GateIntegrityOut.of(gate_integrity(GateIntegrityFacts()))
    read = world.bridge.read(workspace_id=WORKSPACE, run_id=run_id)
    detail = run_detail(read, gate_integrity=unknown)
    spend = run_spend(CachedSpend(totals=SPEND, as_of=world.clock.epoch))
    return detail.model_copy(update={"spend": spend}).model_dump(mode="json")


def header_news(header: dict[str, Any] | None) -> dict[str, Any] | None:
    """A header without its version: the stream sends a ``run`` frame when this changes."""
    if header is None:
        return None
    return {key: value for key, value in header.items() if key not in ("type", "version")}


async def _kept(frames: AsyncIterator[str], sent: list[str]) -> AsyncGenerator[str]:
    """``frames``, each also appended to ``sent``."""
    async for chunk in frames:
        sent.append(chunk)
        yield chunk


class _Tail:
    """One stream of the run, read as a client reads it; every event it sends is kept."""

    def __init__(self, hub: RunStreamHub, world: World, run_id: str, cursor: StreamCursor) -> None:
        self._hub = hub
        self._world = world
        self._run_id = run_id
        stream = hub.stream(
            ALICE, WORKSPACE, run_id, cursor=cursor, is_disconnected=never_disconnected
        )
        self._source = stream.frames()
        self.sent: list[str] = []
        self.frames = _kept(self._source, self.sent)
        self.client = StreamClient(last_seq=cursor.seq)

    async def opened(self) -> None:
        await read_until(
            self.frames, self.client, lambda client: client.view is not None, timeout_s=TIMEOUT_S
        )

    async def caught_up(self) -> int:
        """
        Read until the tail holds the head and the header the row now shows; the head seq.

        The stream's watcher must hold the committed row first. Otherwise the stream would
        wait for it, which moves its clock, and a ``run`` frame due at this head could be
        merged into the next step's.
        """
        run = self._world.run(self._run_id)
        watcher = self._hub.watcher(WORKSPACE, self._run_id)
        assert watcher is not None
        await poll_until_async(lambda: watcher.row == run, timeout_s=TIMEOUT_S)
        head = run.next_log_seq - 1
        state = self._world.bridge.load(workspace_id=WORKSPACE, run_id=self._run_id).state
        expected = header_news(
            run_header(run, RunViewFacts.of(project(state))).model_dump(mode="json")
        )
        await read_until(
            self.frames,
            self.client,
            lambda client: client.last_seq == head and header_news(client.header) == expected,
            timeout_s=TIMEOUT_S,
        )
        return head

    async def to_end(self) -> None:
        async with asyncio.timeout(TIMEOUT_S):
            await pump(self.frames, self.client)
        assert self.client.done

    async def close(self) -> None:
        await self.frames.aclose()
        await self._source.aclose()


async def _outcome(world: World, run_id: str) -> dict[str, Any]:
    """The finished run's outcome, its diff read through a host with fixed replies."""

    def head(request: ChannelRequest) -> dict[str, object]:
        branch = request.params["branch"]
        return {"head": HEAD_COMMIT, "branch": branch, "merge_in_progress": False}

    stat = {
        "files_changed": len(DIFF_PATHS),
        "insertions": DIFF_INSERTIONS,
        "deletions": DIFF_DELETIONS,
        "paths": list(DIFF_PATHS),
    }
    host = FakeHostChannel([], {"head": head, "diff_stat": stat})
    state, _version = world.runs.load_run_state(run_id, workspace_id=WORKSPACE)
    target = outcome_target(state)
    assert target is not None
    read = await OutcomeDiffs().read(
        ALICE, state=state, target=target, channels=FakeChannels(host, RecordingScopeRunner())
    )
    assert host.ops() == ["head", "diff_stat"]
    return run_outcome(world.run(run_id), target, read).model_dump(mode="json")


async def _record(world: World, run_id: str) -> dict[str, Any]:
    """Drive the script with one live tail open, then connect twice more after the end."""
    clock = FakeTime()
    threads = BoundedThreads(max_workers=STREAM_THREADS, thread_name_prefix="contract-stream")
    hub = RunStreamHub(
        bridge=world.bridge, run_store=world.runs, threads=threads, clock=clock, wait=clock.wait
    )
    unhook = world.runs.register_post_commit(hub.notify)
    details: dict[str, dict[str, Any]] = {}
    marks: dict[str, int] = {}
    try:
        live = _Tail(hub, world, run_id, StreamCursor())
        try:
            await live.opened()
            for name, step in _script(world, run_id):
                world.clock.advance(STEP_S)
                await asyncio.to_thread(step)
                marks[name] = await live.caught_up()
                if name in ("gate1_open", "gate2_open"):
                    details[name] = _detail(world, run_id)
            await live.to_end()
        finally:
            await live.close()
        marks["finished"] = world.run(run_id).next_log_seq - 1
        replays = (
            _Tail(hub, world, run_id, stream_cursor(str(marks["gate1_open"]), None)),
            _Tail(hub, world, run_id, StreamCursor()),
        )
        for tail in replays:
            try:
                await tail.to_end()
            finally:
                await tail.close()
        outcome = await _outcome(world, run_id)
    finally:
        unhook()
        await hub.close()
        threads.close()
    # The stream never waited, so no heartbeat or timing decided what it sent.
    assert clock.elapsed == 0, clock.elapsed
    resumed, final = replays
    return {
        "live": [sent_event(chunk) for chunk in live.sent],
        "live_raw": "".join(live.sent),
        "live_marks": {name: marks[name] for name in MILESTONES},
        "resume_after": marks["gate1_open"],
        "resumed": [sent_event(chunk) for chunk in resumed.sent],
        "final_snapshot": [sent_event(chunk) for chunk in final.sent],
        "detail_gate_pass1": details["gate1_open"],
        "detail_gate_pass2": details["gate2_open"],
        "final_detail": _detail(world, run_id),
        "outcome": outcome,
    }


def _pause_messages(world: World, run_id: str) -> dict[str, JsonValue]:
    """What a pause alert says for each reason, and for a reason it cannot name."""
    unknown = row_pause_alert(world.run(run_id), None)
    assert unknown is not None
    return {
        "by_reason": dict(PAUSE_MESSAGES),
        "unknown": AlertPayload.model_validate_json(unknown.payload).message,
    }


def build_contract() -> dict[str, Any]:
    """
    The contract: ``graph``, ``live``, ``live_raw``, ``live_marks``, ``resume_after``,
    ``resumed``, ``final_snapshot``, ``detail_gate_pass1``, ``detail_gate_pass2``,
    ``final_detail``, ``outcome`` and ``pause_messages``.
    """
    run_id = run_id_for()
    spec = run_spec(
        repo_path=REPO_PATH,
        worktree_path=worktree_path(run_id),
        base_ref=BASE_REF,
        base_commit=BASE_COMMIT,
    )
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as scratch:
        world = World.fake(Path(scratch), gate_ids=GateIds())
        run = start(world, workflow_yaml(), spec=spec)
        assert run.id == run_id
        recorded = asyncio.run(_record(world, run_id))
        graph = world.bridge.pinned_graph(workspace_id=WORKSPACE, version_id=run.version_id)
        contract = {
            "graph": graph.model_dump(mode="json"),
            **recorded,
            "pause_messages": _pause_messages(world, run_id),
        }
    # As the wire carries it: tuples become lists.
    return json.loads(json.dumps(contract))


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build the run-view contract fixture.")
    parser.add_argument("--write", action="store_true", help="rewrite the checked-in file")
    args = parser.parse_args(argv)
    return write_or_check(build_contract(), CONTRACT_PATH, write=args.write, module=MODULE)


if __name__ == "__main__":
    sys.exit(main())
