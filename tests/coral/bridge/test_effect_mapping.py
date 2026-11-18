"""Reducer effects and bridge items as queued work rows that the real executors accept."""

from __future__ import annotations

import hashlib
import json
from datetime import timedelta

import pytest

from coral.bridge.config import epoch_seconds, epoch_us
from coral.bridge.keys import store_slot_id
from coral.bridge.mapping import (
    FED_KINDS,
    UNMAPPED_KINDS,
    MapContext,
    UnsupportedStance,
    anchor_create_draft,
    map_effect,
    orchestrator_create_draft,
    timer_draft,
)
from coral.bridge.messages import nudge_text
from coral.db.enum_codecs import WorkKind
from coral.engine.machines.slot import find_slot
from coral.engine.types import (
    CancelRun,
    ChooseArrow,
    Effect,
    EffectCompleted,
    EffectFailed,
    PauseRun,
    RetryStep,
    RunState,
    SessionFailed,
    TurnEnded,
)
from coral.model.ids import derived_id, effect_session_id
from coral.model.ir import CompiledGraph
from coral.slots.executors import _cancel_payload, _close_payload, _create_payload, _send_payload
from coral.stores.protocols import WorkItemDraft
from coral.tools.catalog import STEP_STANCES
from tests.coral.bridge._scripted_runs import (
    IMPLEMENT,
    REVIEW,
    RUN_ID,
    WORKSPACE,
    accept,
    eventful_two_steps,
    exercise,
    fixture_graph,
    replay,
    start_run,
)
from tests.coral.engine.drive import NOW, Driven, drive
from tests.coral.workflow_builders import FIXTURES

GRAPH = fixture_graph("two_steps")
TITLE = "Ship the bridge"
REQUEST = "Make runs advance on their own."
LATER = NOW + timedelta(minutes=3, microseconds=250)


def _ctx(state: RunState, *, graph: CompiledGraph = GRAPH, title: str = TITLE) -> MapContext:
    return MapContext(
        workspace_id=WORKSPACE,
        run_id=RUN_ID,
        graph=graph,
        state=state,
        request_preview=REQUEST,
        title=title,
        now=LATER,
    )


def _only(driven: Driven, kind: str) -> Effect:
    (effect,) = (item for item in driven.log[-1].effects if item.kind == kind)
    return effect


def _payload(draft: WorkItemDraft) -> dict[str, object]:
    payload = json.loads(draft.payload)
    assert isinstance(payload, dict)
    assert len(draft.payload.encode()) <= 15_000
    return payload


def _assert_effect_row(draft: WorkItemDraft, key: str) -> None:
    assert draft.kind == int(WorkKind.EFFECT)
    assert draft.run_id == RUN_ID
    assert draft.id == derived_id("coral-work", RUN_ID, "effect", key)
    assert draft.idempotency_cksum == hashlib.sha256(f"effect\0{key}".encode()).digest()
    assert key.startswith(f"{RUN_ID}:") and len(key) <= 512


def _assert_slot_row(draft: WorkItemDraft, engine_slot: str, node_id: str) -> None:
    assert draft.node_id == node_id
    assert draft.scope_key == engine_slot
    assert draft.slot_generation == 1
    assert draft.owner_key == f"slot:{store_slot_id(RUN_ID, engine_slot)}"
    assert draft.available_at == epoch_seconds(LATER)


def _started(auto_ack: bool = True) -> Driven:
    return drive(GRAPH, [start_run(GRAPH)], auto_ack=auto_ack)


@pytest.mark.parametrize(
    ("fixture", "engine_slot", "node_id", "stance", "slot_role"),
    [
        ("two_steps", IMPLEMENT, "implement", "implementer", "step_agent"),
    ],
)
def test_a_step_create_becomes_a_create_session_row_for_its_stance(
    fixture: str, engine_slot: str, node_id: str, stance: str, slot_role: str
) -> None:
    graph = fixture_graph(fixture)
    started = drive(graph, [start_run(graph)], auto_ack=False)
    effect = _only(started, "create_session")
    draft = map_effect(_ctx(started.state, graph=graph), effect)

    assert draft is not None
    _assert_effect_row(draft, effect.effect_key)
    _assert_slot_row(draft, engine_slot, node_id)
    payload = _payload(draft)
    assert payload == {
        "effect_type": "create_session",
        "effect_key": effect.effect_key,
        "engine_kind": "create_session",
        "role": "step",
        "stance": stance,
        "workflow_slug": graph.workflow_id,
        "node_id": node_id,
        "roster_index": 0,
        "engine_slot_id": engine_slot,
        "slot_role": slot_role,
        "generation": 1,
        "slot_id": store_slot_id(RUN_ID, engine_slot),
    }
    # The executor resolves the agent from the stance; the rest is its parser's.
    parsed = _create_payload({**payload, "agent_id": f"coral__{stance}"})
    assert parsed["engine_slot_id"] == engine_slot
    assert parsed["slot_role"] == slot_role
    assert parsed["generation"] == 1


@pytest.mark.parametrize("profile", ["orchestrator", "planner", "claude", ""])
def test_a_create_for_a_profile_without_a_step_stance_is_refused(profile: str) -> None:
    graph = GRAPH.model_copy(
        update={
            "nodes": tuple(
                node.model_copy(update={"roster": (profile,)}) if node.id == "implement" else node
                for node in GRAPH.nodes
            )
        }
    )
    started = drive(graph, [start_run(graph)], auto_ack=False)
    with pytest.raises(UnsupportedStance, match="implement"):
        map_effect(_ctx(started.state, graph=graph), _only(started, "create_session"))


def test_the_review_create_is_a_verifier_of_the_second_slot() -> None:
    driven = drive(GRAPH, [start_run(GRAPH), *accept(IMPLEMENT, "implemented")], auto_ack=True)
    creates = [
        effect
        for entry in driven.log
        for effect in entry.effects
        if effect.kind == "create_session" and effect.subject == REVIEW
    ]
    (effect,) = creates
    payload = _payload(_draft(driven.state, effect))
    assert (payload["stance"], payload["slot_role"]) == ("reviewer", "verifier")
    assert payload["slot_id"] == store_slot_id(RUN_ID, REVIEW)


def _draft(state: RunState, effect: Effect) -> WorkItemDraft:
    draft = map_effect(_ctx(state), effect)
    assert draft is not None
    return draft


def test_a_brief_becomes_send_input_to_the_session_its_create_derives() -> None:
    started = _started(auto_ack=False)
    create = _only(started, "create_session")
    created = drive(
        GRAPH, [EffectCompleted(effect_key=create.effect_key)], auto_ack=False, after=started
    )
    brief = _only(created, "send_input")
    draft = _draft(created.state, brief)

    _assert_effect_row(draft, brief.effect_key)
    _assert_slot_row(draft, IMPLEMENT, "implement")
    payload = _payload(draft)
    session_id = effect_session_id(WORKSPACE, create.effect_key)
    text = payload.pop("text")
    assert payload == {
        "effect_type": "send_input",
        "effect_key": brief.effect_key,
        "engine_kind": "send_input",
        "session_id": session_id,
        "kind": "brief",
        "slot_id": store_slot_id(RUN_ID, IMPLEMENT),
    }
    assert isinstance(text, str) and "implement||" in text
    assert _send_payload({**payload, "text": text}) == {
        "session_id": session_id,
        "text": text,
        "kind": "brief",
    }


def test_a_nudge_becomes_send_input_with_its_reason_and_resume_while_paused() -> None:
    working = _started()
    ended = drive(
        GRAPH,
        [TurnEnded(slot_id=IMPLEMENT, fact_key="turn:s:1:msg:a")],
        auto_ack=False,
        after=working,
    )
    nudge = _only(ended, "nudge")
    create_key = next(
        effect.effect_key for effect in ended.state.effects if effect.kind == "create_session"
    )
    draft = _draft(ended.state, nudge)

    _assert_effect_row(draft, nudge.effect_key)
    _assert_slot_row(draft, IMPLEMENT, "implement")
    payload = _payload(draft)
    assert payload["effect_type"] == "send_input"
    assert payload["engine_kind"] == "nudge"
    assert payload["kind"] == "nudge"
    assert payload["session_id"] == effect_session_id(WORKSPACE, create_key)
    assert payload["text"] == nudge_text(ended.state, IMPLEMENT, "turn_ended")
    assert _send_payload(payload)["kind"] == "nudge"

    paused = drive(GRAPH, [PauseRun(reason="user", detail="look")], after=ended)
    held = _payload(_draft(paused.state, nudge))
    assert held["text"] == nudge_text(paused.state, IMPLEMENT, "resume")


def test_a_close_becomes_close_slot_for_the_derived_session() -> None:
    working = _started()
    accepted = drive(GRAPH, accept(IMPLEMENT, "implemented"), auto_ack=False, after=working)
    close = _only(accepted, "close_slot")
    create_key = next(
        effect.effect_key for effect in accepted.state.effects if effect.kind == "create_session"
    )
    draft = _draft(accepted.state, close)

    _assert_effect_row(draft, close.effect_key)
    _assert_slot_row(draft, IMPLEMENT, "implement")
    payload = _payload(draft)
    session_id = effect_session_id(WORKSPACE, create_key)
    assert payload == {
        "effect_type": "close_slot",
        "effect_key": close.effect_key,
        "engine_kind": "close_slot",
        "session_id": session_id,
        "interrupt": True,
        "closed_label": True,
        "slot_id": store_slot_id(RUN_ID, IMPLEMENT),
    }
    parsed = _close_payload(payload)
    assert (parsed["session_id"], parsed["interrupt"], parsed["closed_label"]) == (
        session_id,
        True,
        True,
    )


@pytest.mark.parametrize("create_completed", [False, True])
def test_a_cancel_names_the_session_the_create_derives_with_or_without_its_receipt(
    create_completed: bool,
) -> None:
    started = _started(auto_ack=create_completed)
    create_key = next(
        effect.effect_key for effect in started.state.effects if effect.kind == "create_session"
    )
    assert any(item.key == create_key for item in started.state.receipts) is create_completed
    cancelled = drive(GRAPH, [CancelRun()], auto_ack=False, after=started)
    cancel = _only(cancelled, "cancel_sessions")
    draft = _draft(cancelled.state, cancel)

    _assert_effect_row(draft, cancel.effect_key)
    _assert_slot_row(draft, IMPLEMENT, "implement")
    payload = _payload(draft)
    session_id = effect_session_id(WORKSPACE, create_key)
    assert payload == {
        "effect_type": "cancel_sessions",
        "effect_key": cancel.effect_key,
        "engine_kind": "cancel_sessions",
        "session_id": session_id,
        "closed_label": True,
        "slot_id": store_slot_id(RUN_ID, IMPLEMENT),
    }
    assert _cancel_payload(payload) == {"session_id": session_id, "closed_label": True}


def test_a_cancel_of_a_slot_without_a_create_names_no_session() -> None:
    started = _started(auto_ack=False)
    cancelled = drive(GRAPH, [CancelRun()], auto_ack=False, after=started)
    cancel = _only(cancelled, "cancel_sessions")
    no_create = cancelled.state.model_copy(
        update={
            "effects": tuple(
                effect for effect in cancelled.state.effects if effect.kind != "create_session"
            )
        }
    )
    payload = _payload(_draft(no_create, cancel))
    assert "session_id" in payload and payload["session_id"] is None
    assert _cancel_payload(payload) == {"session_id": None, "closed_label": True}


@pytest.mark.parametrize(
    "kind", ["publish_gate", "withdraw_gate", "notify", "runner_lost", "retry_step", "arm_timer"]
)
def test_kinds_without_an_executor_map_to_no_work(kind: str) -> None:
    started = _started()
    effect = Effect(effect_key=f"{RUN_ID}:9:{kind}:{IMPLEMENT}", kind=kind, subject=IMPLEMENT)
    assert map_effect(_ctx(started.state), effect) is None
    assert kind in UNMAPPED_KINDS


def _runs_emitting_every_kind() -> list[tuple[CompiledGraph, Driven]]:
    """Every fixture to its end, the eventful run, a runner loss, a live cancel, a retry and
    a cancel at an open gate."""
    graphs = [fixture_graph(path.stem) for path in sorted(FIXTURES.glob("*.yaml"))]
    driven = [(graph, exercise(graph)) for graph in graphs]
    driven.append((GRAPH, eventful_two_steps(GRAPH)))
    lost = SessionFailed(
        slot_id=IMPLEMENT, failure_class="infra.runner_lost", cause="lost", fact_key="turn:s:1:x"
    )
    driven.append((GRAPH, drive(GRAPH, [lost], after=_started())))
    driven.append((GRAPH, drive(GRAPH, [CancelRun()], after=_started())))
    started = _started(auto_ack=False)
    create = _only(started, "create_session")
    failed = EffectFailed(effect_key=create.effect_key, code="session.failed", retryable=True)
    driven.append((GRAPH, drive(GRAPH, [failed, RetryStep(node_id="implement")], after=started)))
    gated = fixture_graph("review_prs")
    reviewing = drive(gated, [start_run(gated), *accept("find_prs||:0", "found")])
    reviewing = drive(
        gated, [*accept("review||a6:1:0", "ok"), *accept("review||a6:1:1", "ok")], after=reviewing
    )
    approve = ChooseArrow(
        node_id="triage", label="approved", reason="fine", iteration_path=("a6:1",)
    )
    driven.append((gated, drive(gated, [approve, CancelRun()], after=reviewing)))
    return driven


def test_every_effect_the_engine_emits_is_mapped_or_named_unmapped() -> None:
    known = FED_KINDS | {"cancel_sessions"} | set(UNMAPPED_KINDS)
    seen: set[str] = set()
    for graph, driven in _runs_emitting_every_kind():
        for step in replay(graph, driven.log):
            for effect in step.entry.effects:
                assert effect.kind in known, effect.kind
                seen.add(effect.kind)
                slot = find_slot(step.after, effect.subject)
                if effect.kind == "create_session" and (
                    slot is None or slot.profile not in STEP_STANCES
                ):
                    continue  # refused, as the stance test shows
                draft = map_effect(_ctx(step.after, graph=graph), effect)
                assert (draft is None) is (effect.kind in UNMAPPED_KINDS), effect.kind
    # The runs above reach every kind, so a stale list of kinds fails here too.
    assert seen == known


def test_the_anchor_create_is_due_at_once_and_names_the_anchor() -> None:
    draft = anchor_create_draft(_ctx(_started().state))
    key = f"{RUN_ID}:anchor:create_session"
    _assert_effect_row(draft, key)
    assert draft.available_at == 0
    assert (draft.node_id, draft.scope_key, draft.slot_generation, draft.owner_key) == (
        None,
        None,
        None,
        None,
    )
    payload = _payload(draft)
    assert payload == {
        "effect_type": "create_session",
        "effect_key": key,
        "bridge_item": "anchor",
        "role": "anchor",
    }
    assert _create_payload(payload) == {"role": "anchor"}


def test_the_orchestrator_create_is_a_step_create_titled_from_the_run() -> None:
    draft = orchestrator_create_draft(_ctx(_started().state, title="t" * 256))
    key = f"{RUN_ID}:orchestrator:1:create_session"
    _assert_effect_row(draft, key)
    assert draft.available_at == epoch_seconds(LATER)
    assert (draft.scope_key, draft.slot_generation, draft.owner_key) == (
        "orchestrator",
        1,
        "slot:orchestrator",
    )
    payload = _payload(draft)
    title = payload.pop("title")
    assert payload == {
        "effect_type": "create_session",
        "effect_key": key,
        "bridge_item": "orchestrator",
        "role": "step",
        "stance": "orchestrator",
        "engine_slot_id": "orchestrator",
        "slot_role": "orchestrator",
        "generation": 1,
    }
    assert isinstance(title, str) and len(title) <= 200
    assert title == "t" * 180 + " · orchestrator"
    parsed = _create_payload({**payload, "title": title, "agent_id": "coral__orchestrator"})
    assert (parsed["engine_slot_id"], parsed["slot_role"], parsed["title"]) == (
        "orchestrator",
        "orchestrator",
        title,
    )


def test_a_timer_row_is_due_at_its_deadline_rounded_up() -> None:
    working = _started()
    failed = drive(
        GRAPH,
        [
            SessionFailed(
                slot_id=IMPLEMENT,
                failure_class="infra.transient",
                cause="529",
                fact_key="turn:s:1:msg:a",
            )
        ],
        after=working,
        now=LATER,
    )
    timer = min(failed.state.timers, key=lambda item: item.stage)
    assert timer.due_at.microsecond == 250
    draft = timer_draft(RUN_ID, timer)
    key = f"timer:{timer.key}:{timer.generation}:{epoch_us(timer.due_at)}"

    assert draft.kind == int(WorkKind.TIMER)
    assert draft.id == derived_id("coral-work", RUN_ID, "timer", key)
    assert draft.idempotency_cksum == hashlib.sha256(f"timer\0{key}".encode()).digest()
    assert draft.available_at == epoch_seconds(timer.due_at) + 1
    assert draft.scope_key == timer.subject
    assert json.loads(draft.payload) == {
        "effect_type": "timer",
        "timer_key": timer.key,
        "due_at": timer.due_at.isoformat(),
    }
    assert timer_draft(RUN_ID, timer) == draft
