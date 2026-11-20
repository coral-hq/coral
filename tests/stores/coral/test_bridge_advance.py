"""A run on ``two_steps`` advances unattended on every DB lane, read back by a fresh process.

The run, queue, binding, stable-id and op-intent stores are SQL; the sessions are
fakes and a scripted agent answers each brief through the engine tools.
"""

from __future__ import annotations

import json

from sqlalchemy import select
from sqlalchemy.orm import Session

from coral.bridge.codec import decode_entries
from coral.db import WorkRow
from coral.db.enum_codecs import RunStatus
from tests.coral.bridge._world import (
    IMPLEMENT,
    REVIEW,
    WORKSPACE,
    Agent,
    World,
    serving,
    start,
)
from tests.stores.coral._faults import fresh_process

REPORT = "Implemented the parser change in parser.py and added its tests."


async def test_a_two_step_run_advances_unattended_to_completed(coral_db_uri: str) -> None:
    async with serving(World.sql(coral_db_uri)) as sessions:
        run = start(sessions.world)
        agent = Agent(sessions, reports={"implement": REPORT})

        await sessions.run(agent)

        implementer = sessions.session_of(run.id, IMPLEMENT)
        reviewer = sessions.session_of(run.id, REVIEW)
        steps = [request for request in sessions.facade.requests if request.role == "step"]
        assert [request.engine_slot_id for request in steps] == [IMPLEMENT, REVIEW]
        assert [str(message["session_id"]) for message in sessions.messages()] == [
            implementer,
            reviewer,
        ]
        assert REPORT in str(sessions.messages(reviewer)[0]["text"])
        assert [(call.session_id, call.reply.accepted) for call in agent.calls] == [
            (implementer, True),
            (reviewer, True),
        ]

    # A fresh process reads the finished run and folds its log to the same state.
    engine = fresh_process(coral_db_uri)
    with Session(engine) as db:
        payloads = [
            json.loads(payload)
            for payload in db.scalars(
                select(WorkRow.payload).where(
                    WorkRow.workspace_id == WORKSPACE, WorkRow.run_id == run.id
                )
            )
        ]
    # One close row per step.
    closed = [
        payload["session_id"] for payload in payloads if payload["effect_type"] == "close_slot"
    ]
    assert sorted(closed) == sorted([implementer, reviewer])
    world = World.sql(coral_db_uri)
    rows = world.engine_log(run.id)
    entries = decode_entries(rows)
    assert [entry.input.kind for entry in entries] == [
        "start_run",
        "effect_completed",
        "effect_completed",
        "handoff_received",
        "handoff_evaluated",
        "effect_completed",
        "effect_completed",
        "effect_completed",
        "handoff_received",
        "handoff_evaluated",
        "effect_completed",
    ]
    assert [
        row.actor_ref
        for row, entry in zip(rows, entries, strict=True)
        if entry.input.kind == "handoff_received"
    ] == [implementer, reviewer]
    finished = world.run(run.id)
    assert (finished.status, finished.finished_at is not None) == (
        int(RunStatus.COMPLETED),
        True,
    )
    assert world.assert_fold_matches(run.id).status == "completed"
