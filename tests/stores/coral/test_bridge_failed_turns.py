"""A failed turn's status edge pauses its run on every DB lane; resume re-prompts the step.

The run, queue, binding and stable-id stores are SQL, so the turn-fact recorder and
executor read and write them as a server does; the sessions are fakes.
"""

from __future__ import annotations

from coral.bridge.codec import decode_entries
from coral.db.enum_codecs import RunPauseReason, RunStatus
from coral.engine.types import SessionFailed
from tests.coral.bridge._world import IMPLEMENT, USER, WORKSPACE, World, serving, start
from tests.stores.coral._faults import fresh_process

RESUME = "The run is running again."


async def test_a_401_turn_pauses_auth_and_resume_re_prompts_the_step(coral_db_uri: str) -> None:
    async with serving(World.sql(coral_db_uri)) as sessions:
        world = sessions.world
        run = start(world)
        await sessions.drain()
        sessions.fail_turn(run.id, IMPLEMENT, "Invalid API key", code="claude_sdk_auth_failed")
        await sessions.drain()

        # Another process's stores read the pause.
        paused = World.sql(coral_db_uri).run(run.id)
        assert (paused.status, paused.pause_reason) == (
            int(RunStatus.PAUSED),
            int(RunPauseReason.AUTH),
        )

        world.bridge.resume_run(workspace_id=WORKSPACE, run_id=run.id, actor=USER)
        await sessions.drain()

        session_id = sessions.session_of(run.id, IMPLEMENT)
        texts = [str(send["text"]) for send in sessions.messages(session_id)]
        assert len(texts) == 2 and texts[-1].startswith(RESUME)

    fresh_process(coral_db_uri)
    reread = World.sql(coral_db_uri)
    assert reread.run(run.id).status == int(RunStatus.RUNNING)
    failures = [
        (entry.input.failure_class, entry.input.cause)
        for entry in decode_entries(reread.engine_log(run.id))
        if isinstance(entry.input, SessionFailed)
    ]
    assert failures == [("auth", "claude_sdk_auth_failed")]
