"""A loop run's orchestrator is created, asked and obeyed on every DB lane.

The run, queue, binding, stable-id and op-intent stores are SQL, so the decision
port reads the orchestrator the run row names and the binding the create wrote;
the sessions are fakes. A fresh process reads the finished run back.
"""

from __future__ import annotations

from coral.bridge.codec import decode_entries
from coral.bridge.keys import ORCHESTRATOR_SLOT_ID, orchestrator_effect_key
from coral.db.enum_codecs import ActorKind, RunStatus, SessionBindingRole, SlotRole
from coral.model.ids import effect_session_id
from coral.stores.session_bindings import SqlAlchemySessionBindingStore
from tests.coral.bridge._world import WORKSPACE, Agent, Orchestrator, World, serving, start
from tests.coral.workflow_builders import fixture_text
from tests.stores.coral._faults import fresh_process

REVISE = ("revise", "The parser change has no tests; add them.")
APPROVED = ("approved", "The tests cover the change.")


async def test_a_loop_run_advances_unattended_through_its_orchestrator(coral_db_uri: str) -> None:
    async with serving(World.sql(coral_db_uri)) as sessions:
        run = start(sessions.world, fixture_text("loop"))
        orchestrator = Orchestrator(sessions, [REVISE, APPROVED])

        await sessions.run(Agent(sessions), orchestrator)

        assert [(call.arguments["label"], call.reply.accepted) for call in orchestrator.calls] == [
            ("revise", True),
            ("approved", True),
        ]

    fresh_process(coral_db_uri)
    world = World.sql(coral_db_uri)
    chooser = effect_session_id(WORKSPACE, orchestrator_effect_key(run.id))
    finished = world.run(run.id)
    assert (finished.status, finished.orchestrator_session_id) == (
        int(RunStatus.COMPLETED),
        chooser,
    )
    binding = SqlAlchemySessionBindingStore(coral_db_uri).find_by_session(WORKSPACE, chooser)
    assert binding is not None
    assert (binding.role, binding.slot_id, binding.slot_role, binding.session_generation) == (
        SessionBindingRole.STEP,
        ORCHESTRATOR_SLOT_ID,
        SlotRole.ORCHESTRATOR,
        1,
    )
    rows = world.engine_log(run.id)
    chosen = [
        (row.actor_kind, row.actor_ref, entry.input.label)
        for row, entry in zip(rows, decode_entries(rows), strict=True)
        if entry.input.kind == "choose_arrow"
    ]
    assert chosen == [
        (int(ActorKind.ORCHESTRATOR), chooser, "revise"),
        (int(ActorKind.ORCHESTRATOR), chooser, "approved"),
    ]
    assert world.assert_fold_matches(run.id).status == "completed"
