"""A finished work row feeds its outcome back to the engine once; repeats write nothing."""

from __future__ import annotations

import dataclasses
import json
import logging
from collections import Counter
from pathlib import Path
from typing import Any

import pytest

from coral.bridge.feedback import abandoned_restart, fed_payload, feedback_input, gate_of
from coral.bridge.keys import anchor_effect_key, store_slot_id
from coral.bridge.mapping import RECOVERY_RESTART
from coral.db.enum_codecs import LogKind, RunPauseReason, RunStatus, SlotStatus, WorkStatus
from coral.engine.lifecycle import retryable_activations
from coral.engine.types import EffectCompleted, EffectFailed, PauseRun
from coral.model.ids import effect_session_id
from coral.queue import FinishedWork
from coral.stores.fakes import FakeRunStore
from coral.stores.protocols import RunContended, WorkItem, WorkItemDraft
from tests.coral.bridge._world import (
    IMPLEMENT,
    WORKSPACE,
    World,
    finished,
    retried,
    row_of,
    settle,
    start,
)
from tests.coral.workflow_builders import arrow, end, step, workflow_text
from tests.coral.workflow_builders import start as start_node


@pytest.fixture
def world(tmp_path: Path) -> World:
    return World.fake(tmp_path)


def _create(world: World, run_id: str) -> WorkItem:
    return row_of(world, run_id, "create_session", engine_kind="create_session")


def _anchor(world: World, run_id: str) -> WorkItem:
    anchor = row_of(world, run_id, "create_session")
    assert json.loads(anchor.payload)["effect_key"] == anchor_effect_key(run_id)
    return anchor


def _causes(world: World, run_id: str) -> list[tuple[str, str, str]]:
    state = world.assert_fold_matches(run_id)
    return [(cause.reason, cause.detail, cause.subject) for cause in state.causes]


def test_a_create_success_records_the_slot_session_and_queues_the_brief(world: World) -> None:
    run = start(world)
    create = _create(world, run.id)
    session = effect_session_id(WORKSPACE, json.loads(create.payload)["effect_key"])
    result = {"session_id": session, "role": "step", "generation": 1, "noise": "x" * 5_000}
    world.bridge.feed(finished(settle(world, create, WorkStatus.SUCCEEDED, result=result)))

    state, _version = world.runs.load_run_state(run.id, workspace_id=WORKSPACE)
    (slot,) = state.agent_slots
    assert (slot.id, slot.status, slot.session_id) == (
        store_slot_id(run.id, IMPLEMENT),
        int(SlotStatus.SESSION_CREATED),
        session,
    )
    brief = row_of(world, run.id, "send_input")
    payload = json.loads(brief.payload)
    assert (payload["kind"], payload["session_id"]) == ("brief", session)
    engine = world.assert_fold_matches(run.id)
    (receipt,) = [
        item for item in engine.receipts if item.key == json.loads(create.payload)["effect_key"]
    ]
    # Only the fields the engine reads are kept.
    assert receipt.payload == {"session_id": session, "role": "step", "generation": 1}


def test_a_send_success_puts_the_slot_to_work(world: World) -> None:
    run = start(world)
    created = {"session_id": "s" * 32, "generation": 1}
    world.bridge.feed(
        finished(settle(world, _create(world, run.id), WorkStatus.SUCCEEDED, result=created))
    )
    brief = row_of(world, run.id, "send_input")
    world.bridge.feed(
        finished(
            settle(
                world,
                brief,
                WorkStatus.SUCCEEDED,
                result={"session_id": "s" * 32, "stable_id": "m"},
            )
        )
    )
    assert world.assert_fold_matches(run.id).slots[0].status == "working"


def test_an_exhausted_effect_pauses_infra_and_a_repeat_writes_nothing(world: World) -> None:
    run = start(world)
    exhausted = settle(
        world,
        _create(world, run.id),
        WorkStatus.FAILED,
        error_code="infra.transient",
        result={"last_error_code": "session.host_offline", "message": "host gone"},
    )
    world.bridge.feed(finished(exhausted))
    paused = world.run(run.id)
    assert (paused.status, paused.pause_reason) == (
        int(RunStatus.PAUSED),
        int(RunPauseReason.INFRA),
    )
    assert _causes(world, run.id) == [("infra", "session.host_offline", IMPLEMENT)]
    (row,) = world.queue.get_work([exhausted.id], workspace_id=WORKSPACE)
    assert row.status == int(WorkStatus.FAILED)
    world.bridge.feed(finished(exhausted))
    assert world.run(run.id).version == paused.version


def test_a_permanent_failure_pauses_failure_path_once(world: World) -> None:
    run = start(world)
    failed = settle(
        world, _create(world, run.id), WorkStatus.FAILED, error_code="session.agent_not_supported"
    )
    world.bridge.feed(finished(failed))
    paused = world.run(run.id)
    assert paused.pause_reason == int(RunPauseReason.FAILURE_PATH)
    assert _causes(world, run.id) == [("failure_path", "session.agent_not_supported", IMPLEMENT)]
    key = json.loads(failed.payload)["effect_key"]
    receipts = {item.key: item.payload for item in world.assert_fold_matches(run.id).receipts}
    assert receipts[key] == {"failed": "session.agent_not_supported"}
    world.bridge.feed(finished(failed))
    assert world.run(run.id).version == paused.version


@pytest.mark.parametrize(
    ("status", "error_code"),
    [
        (WorkStatus.SUCCEEDED, None),
        (WorkStatus.FAILED, "infra.transient"),
        (WorkStatus.FAILED, "session.agent_not_supported"),
    ],
    ids=["success", "exhausted", "permanent"],
)
def test_a_later_outcome_of_an_effect_already_fed_writes_nothing(
    world: World, status: WorkStatus, error_code: str | None
) -> None:
    run = start(world)
    create = _create(world, run.id)
    world.bridge.feed(
        finished(settle(world, create, WorkStatus.SUCCEEDED, result={"session_id": "s" * 32}))
    )
    version = world.run(run.id).version
    # The row ran again (its finish was lost) and reported something else.
    rerun = settle(world, create, status, error_code=error_code, result={"session_id": "t" * 32})
    world.bridge.feed(finished(rerun))
    assert world.run(run.id).version == version
    key = json.loads(create.payload)["effect_key"]
    receipts = {item.key: item.payload for item in world.assert_fold_matches(run.id).receipts}
    assert receipts[key]["session_id"] == "s" * 32


def test_a_feed_that_loses_the_compare_and_swap_is_rebuilt_on_the_winner_s_state(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    nodes = [start_node(), step("pair", ["reviewer", "reviewer"]), end()]
    run = start(
        world, workflow_text(nodes, [arrow("a1", "start", "pair"), arrow("a2", "pair", "end")])
    )
    first, second = (
        settle(world, item, WorkStatus.SUCCEEDED, result={"session_id": f"{index:032d}"})
        for index, item in enumerate(
            item
            for item in world.work(run.id)
            if json.loads(item.payload).get("engine_kind") == "create_session"
        )
    )
    version = world.run(run.id).version
    load = world.runs.load_run_state

    def racing_load(run_id: str, **kwargs: Any) -> Any:
        # The other feed commits between this feed's read and its write.
        loaded = load(run_id, **kwargs)
        monkeypatch.setattr(world.runs, "load_run_state", load)
        world.bridge.feed(finished(second))
        return loaded

    monkeypatch.setattr(world.runs, "load_run_state", racing_load)
    world.bridge.feed(finished(first))

    assert world.run(run.id).version == version + 2
    fed = Counter(
        json.loads(row.body)["input"]["effect_key"]
        for row in world.engine_log(run.id)
        if json.loads(row.body)["input"]["kind"] == "effect_completed"
    )
    assert fed == Counter(json.loads(item.payload)["effect_key"] for item in (first, second))
    state, _version = world.runs.load_run_state(run.id, workspace_id=WORKSPACE)
    assert {slot.session_id for slot in state.agent_slots} == {f"{index:032d}" for index in (0, 1)}
    world.assert_fold_matches(run.id)


@pytest.mark.parametrize(
    ("error_code", "result", "cause"),
    [
        (
            "infra.transient",
            {"last_error_code": "session.not_ready"},
            ("infra", "anchor:session.not_ready"),
        ),
        ("session.anchor_bound", None, ("failure_path", "anchor:session.anchor_bound")),
    ],
)
def test_an_anchor_failure_pauses_with_its_prefixed_detail_once(
    world: World, error_code: str, result: dict[str, str] | None, cause: tuple[str, str]
) -> None:
    run = start(world)
    anchor = settle(
        world, _anchor(world, run.id), WorkStatus.FAILED, error_code=error_code, result=result
    )
    world.bridge.feed(finished(anchor))
    assert _causes(world, run.id) == [(*cause, "")]
    version = world.run(run.id).version
    world.bridge.feed(finished(anchor))
    assert world.run(run.id).version == version


def test_an_anchor_success_and_rows_that_are_not_fed_write_nothing(world: World) -> None:
    run = start(world)
    version = world.run(run.id).version
    world.bridge.feed(
        finished(settle(world, _anchor(world, run.id), WorkStatus.SUCCEEDED, result={}))
    )
    abandoned = settle(
        world, _create(world, run.id), WorkStatus.ABANDONED, error_code="run.terminal"
    )
    world.bridge.feed(finished(abandoned))
    for draft in (
        WorkItemDraft.timer(
            run_id=run.id, idempotency_key="t", available_at=0, payload={"effect_type": "timer"}
        ),
        WorkItemDraft.signal(
            run_id=run.id, idempotency_key="s", payload={"effect_type": "turn_fact"}
        ),
        WorkItemDraft.signal(
            run_id=run.id, idempotency_key="r", payload={"effect_type": "run_resync"}
        ),
    ):
        world.queue.enqueue_work([draft], workspace_id=WORKSPACE, now=world.clock.epoch)
        (row,) = world.queue.get_work([draft.id], workspace_id=WORKSPACE)
        world.bridge.feed(finished(settle(world, row, WorkStatus.FAILED, error_code="x")))
    assert world.run(run.id).version == version


def test_feedback_maps_outcomes_to_engine_inputs() -> None:
    def item(payload: dict[str, object]) -> WorkItem:
        draft = WorkItemDraft.effect(run_id="r" * 32, idempotency_key="k", payload=payload)
        return WorkItem(
            workspace_id=WORKSPACE,
            id=draft.id,
            run_id=draft.run_id,
            kind=draft.kind,
            status=int(WorkStatus.SUCCEEDED),
            payload=draft.payload,
            idempotency_cksum=draft.idempotency_cksum,
            available_at=0,
            created_at_us=0,
        )

    nudge = item({"effect_type": "send_input", "engine_kind": "nudge", "effect_key": "k1"})
    done = FinishedWork(nudge, int(WorkStatus.SUCCEEDED), None, {"stable_id": "m", "x": 1})
    assert feedback_input(done) == EffectCompleted(effect_key="k1", payload={"stable_id": "m"})
    exhausted = FinishedWork(nudge, int(WorkStatus.FAILED), "infra.transient", None)
    assert feedback_input(exhausted) == EffectFailed(
        effect_key="k1", code="infra.transient", retryable=True
    )
    long_code = FinishedWork(nudge, int(WorkStatus.FAILED), "c" * 200, None)
    failed = feedback_input(long_code)
    assert isinstance(failed, EffectFailed) and len(failed.code) == 64 and not failed.retryable
    cancel = item(
        {"effect_type": "cancel_sessions", "engine_kind": "cancel_sessions", "effect_key": "k2"}
    )
    assert feedback_input(FinishedWork(cancel, int(WorkStatus.SUCCEEDED), None, None)) is None
    orchestrator = item({"effect_type": "create_session", "bridge_item": "orchestrator"})
    assert feedback_input(
        FinishedWork(orchestrator, int(WorkStatus.FAILED), "session.agent_not_supported", None)
    ) == PauseRun(reason="failure_path", detail="orchestrator:session.agent_not_supported")
    # A decision request, reminder or re-request to the orchestrator is a bridge row too.
    request = item({"effect_type": "send_input", "bridge_item": "decision", "effect_key": "k3"})
    assert feedback_input(FinishedWork(request, int(WorkStatus.SUCCEEDED), None, None)) is None
    assert feedback_input(
        FinishedWork(
            request, int(WorkStatus.FAILED), "infra.transient", {"last_error_code": "c.x"}
        )
    ) == PauseRun(reason="infra", detail="decision:c.x")
    assert fed_payload(
        "close_slot", {"pending_input": True, "diff_stat": {"files": 3}, "commit": "c"}
    ) == {
        "pending_input": True,
        "commit": "c",
    }
    # A gate's publish or withdraw is a bridge row: never a completion.
    publish = item(
        {"effect_type": "gate_publish", "bridge_item": "gate", "effect_key": "k4", "visit_id": "v"}
    )
    assert feedback_input(FinishedWork(publish, int(WorkStatus.SUCCEEDED), None, None)) is None
    assert feedback_input(
        FinishedWork(publish, int(WorkStatus.FAILED), "effect.invalid_payload", None)
    ) == PauseRun(reason="failure_path", detail="gate:effect.invalid_payload")
    assert feedback_input(
        FinishedWork(
            publish,
            int(WorkStatus.FAILED),
            "infra.transient",
            {"last_error_code": "session.anchor_missing"},
        )
    ) == PauseRun(reason="infra", detail="gate:session.anchor_missing")
    assert (gate_of(publish), gate_of(request), gate_of(nudge)) == ("v", None, None)


def test_a_contended_feed_is_logged_for_the_resync(
    world: World, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    run = start(world)
    create = settle(
        world, _create(world, run.id), WorkStatus.SUCCEEDED, result={"session_id": "s" * 32}
    )

    def contended(**_kwargs: object) -> None:
        raise RunContended("version conflict after 5 attempts")

    monkeypatch.setattr("coral.bridge.service.commit_with_retry", contended)
    with caplog.at_level(logging.WARNING, logger="coral.bridge.service"):
        world.bridge.feed(finished(create))
    assert "contended" in caplog.text


def test_a_feed_for_an_unloadable_run_pauses_it_once(world: World) -> None:
    run = start(world)
    create = settle(
        world, _create(world, run.id), WorkStatus.SUCCEEDED, result={"session_id": "s" * 32}
    )
    runs = world.runs
    assert isinstance(runs, FakeRunStore)
    logs = runs.logs[(WORKSPACE, run.id)]
    logs[0] = dataclasses.replace(logs[0], body="not json")
    world.bridge.feed(finished(create))
    world.bridge.feed(finished(create))
    paused = world.run(run.id)
    assert (paused.status, paused.pause_reason) == (
        int(RunStatus.PAUSED),
        int(RunPauseReason.FAILURE_PATH),
    )
    assert [row.kind for row in logs].count(int(LogKind.PAUSED)) == 1


@pytest.mark.parametrize("code", ["infra.transient", "session.agent_not_supported"])
def test_a_failure_fed_after_a_resume_revived_its_row_is_dropped(world: World, code: str) -> None:
    run = start(world)
    world.bridge.commit_inputs(
        workspace_id=WORKSPACE,
        run_id=run.id,
        inputs=lambda _snapshot: (PauseRun(reason="user", detail="look"),),
    )
    # The create runs out while the run is paused; the resume lands before its feed.
    failed = settle(
        world,
        _create(world, run.id),
        WorkStatus.FAILED,
        error_code=code,
        result={"last_error_code": "session.host_offline"},
    )
    world.bridge.resume_run(workspace_id=WORKSPACE, run_id=run.id, actor="user:alice")
    (revived,) = world.queue.get_work([failed.id], workspace_id=WORKSPACE)
    assert revived.status == int(WorkStatus.PENDING)
    version = world.run(run.id).version

    world.bridge.feed(finished(failed))

    assert (world.run(run.id).status, world.run(run.id).version) == (
        int(RunStatus.RUNNING),
        version,
    )
    created = settle(world, revived, WorkStatus.SUCCEEDED, result={"session_id": "s" * 32})
    world.bridge.feed(finished(created))
    state = world.assert_fold_matches(run.id)
    assert (state.status, state.slots[0].status) == ("running", "session_created")


def _restart(world: World, run_id: str) -> WorkItem:
    return row_of(world, run_id, RECOVERY_RESTART)


def test_a_finished_restart_creates_the_next_generation_and_names_what_it_salvaged(
    world: World,
) -> None:
    run_id = retried(world)
    salvaged = {
        "salvage_ref": f"refs/coral/salvage/{'e' * 32}",
        "salvage_commit": "f" * 40,
        "head_verified": True,
        "noise": "x" * 500,
    }
    world.bridge.feed(
        finished(settle(world, _restart(world, run_id), WorkStatus.SUCCEEDED, result=salvaged))
    )

    assert _causes(world, run_id) == []
    assert world.run(run_id).status == int(RunStatus.RUNNING)
    creates = [
        json.loads(item.payload)
        for item in world.work(run_id)
        if json.loads(item.payload).get("engine_kind") == "create_session"
    ]
    assert [payload["generation"] for payload in creates] == [1, 2]
    state = world.assert_fold_matches(run_id)
    (receipt,) = [
        item
        for item in state.receipts
        if item.key == json.loads(_restart(world, run_id).payload)["effect_key"]
    ]
    salvaged.pop("noise")
    assert receipt.payload == salvaged


@pytest.mark.parametrize(
    ("status", "error_code", "result", "detail"),
    [
        pytest.param(
            WorkStatus.FAILED,
            "workspace.head_moved",
            None,
            "restart:workspace.head_moved",
            id="permanent",
        ),
        pytest.param(
            WorkStatus.FAILED,
            "infra.transient",
            {"last_error_code": "dispatch.stop_unconfirmed"},
            "restart:dispatch.stop_unconfirmed",
            id="retries-ran-out",
        ),
    ],
)
def test_a_failed_restart_leaves_the_step_paused_for_a_retry_only(
    world: World,
    status: WorkStatus,
    error_code: str,
    result: dict[str, Any] | None,
    detail: str,
) -> None:
    run_id = retried(world)

    world.bridge.feed(
        finished(
            settle(world, _restart(world, run_id), status, error_code=error_code, result=result)
        )
    )

    assert _causes(world, run_id) == [("failure_path", detail, IMPLEMENT)]
    state = world.assert_fold_matches(run_id)
    assert retryable_activations(state) == ("implement||",)
    assert world.run(run_id).status == int(RunStatus.PAUSED)


def test_only_an_abandoned_restart_of_the_slots_generation_is_fed_as_its_failure(
    world: World,
) -> None:
    run_id = retried(world)
    row = _restart(world, run_id)
    state = world.bridge.load(workspace_id=WORKSPACE, run_id=run_id).state
    key = json.loads(row.payload)["effect_key"]
    abandoned = settle(world, row, WorkStatus.ABANDONED, error_code="slot.generation_mismatch")

    assert abandoned_restart(abandoned, state) == EffectFailed(
        effect_key=key, code="slot.generation_mismatch", retryable=False
    )
    # The drainer's hook never sees an abandoned row; only the resync feeds it.
    assert feedback_input(finished(abandoned)) is None
    older = dataclasses.replace(
        abandoned, payload=json.dumps({**json.loads(row.payload), "generation": 1})
    )
    assert abandoned_restart(older, state) is None
    for status in (WorkStatus.FAILED, WorkStatus.SUCCEEDED, WorkStatus.PENDING):
        assert abandoned_restart(dataclasses.replace(abandoned, status=int(status)), state) is None
    close = dataclasses.replace(
        abandoned,
        payload=json.dumps({**json.loads(row.payload), "effect_type": "close_slot"}),
    )
    assert abandoned_restart(close, state) is None


def test_wake_results_feed_only_the_fields_the_engine_reads() -> None:
    seen_at = "2026-01-01T12:00:00+00:00"
    assert fed_payload(
        "runner_lost",
        {"outcome": "relaunched", "turn_running": False, "seen_at": seen_at, "runner": "r2"},
    ) == {"outcome": "relaunched", "turn_running": False, "seen_at": seen_at}
    assert fed_payload("runner_lost", {"outcome": 1, "turn_running": "no"}) == {}


def test_restart_results_feed_only_the_fields_the_engine_reads() -> None:
    assert fed_payload(
        "retry_step",
        {
            "salvage_ref": None,
            "salvage_commit": None,
            "head_verified": False,
            "phase": "reset",
        },
    ) == {"salvage_ref": None, "salvage_commit": None, "head_verified": False}
    assert fed_payload("retry_step", {"salvage_ref": 1, "head_verified": "yes"}) == {}
