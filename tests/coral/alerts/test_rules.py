"""Which alerts a commit raises and resolves, from its rows, statuses and engine states alone."""

from __future__ import annotations

import random
from collections.abc import Sequence

import pytest
from pydantic import JsonValue

from coral.alerts.rules import (
    PAUSE_MESSAGES,
    AlertChanges,
    alert_id,
    alert_subject,
    commit_alerts,
    row_pause_alert,
)
from coral.alerts.types import AlertKindName, AlertPayload
from coral.db import MAX_STORED_BYTES, encode
from coral.db.enum_codecs import (
    AlertKind,
    AlertPriority,
    GateVisitStatus,
    RunPauseReason,
    RunStatus,
)
from coral.engine import types as engine
from coral.gates.ids import gate_visit_id
from coral.model.ids import anchor_session_id
from coral.model.ir import CompiledGraph
from coral.stores.protocols import (
    AlertDraft,
    AlertResolution,
    CoralRun,
    GateVisitDraft,
    GateVisitState,
)
from tests.coral.workflow_builders import (
    arrow,
    compile_text,
    end,
    fixture_text,
    gate,
    workflow_text,
)
from tests.coral.workflow_builders import start as start_node

WORKSPACE = 7
RUN_ID = "a" * 32
ANCHOR = anchor_session_id(WORKSPACE, RUN_ID)
EID = "coral_gate_" + "1" * 32
EID_AGAIN = "coral_gate_" + "2" * 32
GATE_ONLY = compile_text(fixture_text("gate_only"))[0]
LOOP = compile_text(fixture_text("loop"))[0]
APPROVE = "approve||"
APPROVE_TOKEN = "approve||:1"
APPROVE_TOKEN_AGAIN = "approve||:2"
VISIT_ID = gate_visit_id(RUN_ID, APPROVE_TOKEN)
DECISION = "review||a4:1"
RUN_LINK = f"/workflows/runs/{RUN_ID}"
NEEDS_AN_ANSWER = (
    int(AlertKind.GATE),
    int(AlertKind.QUESTION),
    int(AlertKind.PAUSE),
    int(AlertKind.WATCHDOG),
)


def _run(
    status: RunStatus = RunStatus.RUNNING,
    *,
    pause_reason: RunPauseReason | None = None,
    title: str = "Ship the bridge",
) -> CoralRun:
    return CoralRun(
        workspace_id=WORKSPACE,
        id=RUN_ID,
        workflow_id="w" * 32,
        version_id="v" * 32,
        status=int(status),
        version=5,
        next_log_seq=9,
        activation_count=1,
        title=title,
        engine_version=1,
        state_version=1,
        log_version=1,
        created_at=100,
        updated_at=100,
        user_id="alice",
        account_generation="gen-1",
        pause_reason=None if pause_reason is None else int(pause_reason),
    )


def _visit(
    token: str = APPROVE_TOKEN, status: engine.GateStatus = "open", visit_no: int = 1
) -> engine.GateVisit:
    return engine.GateVisit(activation_id=APPROVE, token=token, visit_no=visit_no, status=status)


def _state(
    status: engine.RunStatus = "running",
    *,
    gates: Sequence[engine.GateVisit] = (),
    decisions: Sequence[engine.Decision] = (),
) -> engine.RunState:
    return engine.RunState(
        status=status, run_id=RUN_ID, gates=tuple(gates), decisions=tuple(decisions)
    )


def _draft(
    status: GateVisitStatus, token: str = APPROVE_TOKEN, eid: str = EID, visit_no: int = 1
) -> GateVisitDraft:
    return GateVisitDraft(
        id=gate_visit_id(RUN_ID, token),
        activation_id="b" * 32,
        node_id="approve",
        scope_key=APPROVE,
        visit_no=visit_no,
        token=token,
        status=int(status),
        owner_user_id="alice",
        elicitation_id=eid,
        elicitation_session_id=ANCHOR,
        opened_at=100,
        resolved_at=None if status == GateVisitStatus.OPEN else 200,
    )


def _row(status: GateVisitStatus, token: str = APPROVE_TOKEN) -> GateVisitState:
    draft = _draft(status, token)
    return GateVisitState(
        workspace_id=WORKSPACE,
        run_id=RUN_ID,
        id=draft.id,
        activation_id=draft.activation_id,
        node_id=draft.node_id,
        scope_key=draft.scope_key,
        visit_no=draft.visit_no,
        token=draft.token,
        status=draft.status,
        opened_at=draft.opened_at,
        owner_user_id=draft.owner_user_id,
        elicitation_id=draft.elicitation_id,
        elicitation_session_id=draft.elicitation_session_id,
        resolved_at=draft.resolved_at,
    )


def _alerts(
    *,
    run: CoralRun | None = None,
    graph: CompiledGraph = GATE_ONLY,
    first: engine.RunState | None = None,
    final: engine.RunState | None = None,
    effects: Sequence[engine.Effect] = (),
    loaded: Sequence[GateVisitState] = (),
    drafts: Sequence[GateVisitDraft] = (),
    status: RunStatus | None = None,
    reason: RunPauseReason | None = None,
) -> AlertChanges:
    run = run if run is not None else _run()
    first = first if first is not None else _state()
    return commit_alerts(
        run,
        graph,
        first=first,
        final=final if final is not None else first,
        effects=effects,
        loaded_gates=loaded,
        gate_drafts=drafts,
        status=run.status if status is None else int(status),
        pause_reason=(
            run.pause_reason if status is None else (None if reason is None else int(reason))
        ),
    )


def _payload(draft: AlertDraft) -> AlertPayload:
    return AlertPayload.model_validate_json(draft.payload)


def _with_gate(graph: CompiledGraph = GATE_ONLY, **fields: object) -> CompiledGraph:
    """``graph`` with its ``approve`` gate changed, past what a workflow file may say."""
    nodes = tuple(
        node.model_copy(update=fields) if node.id == "approve" else node for node in graph.nodes
    )
    return graph.model_copy(update={"nodes": nodes})


def _gate_graph(outcomes: list[str], **fields: object) -> CompiledGraph:
    text = workflow_text(
        [start_node(), gate("approve", outcomes=outcomes, **fields), end()],
        [
            arrow("a1", "start", "approve"),
            *(
                arrow(f"a{index + 2}", "approve", "end", label=label)
                for index, label in enumerate(outcomes)
            ),
        ],
    )
    return compile_text(text)[0]


def _notify(subject: str, *, kind: str = "watchdog", stage: str = "alert") -> engine.Effect:
    payload: dict[str, JsonValue] = {"kind": kind}
    if kind == "watchdog":
        payload["stage"] = stage
    return engine.Effect(
        effect_key=engine.effect_key(RUN_ID, 9, "notify", subject),
        kind="notify",
        subject=subject,
        payload=payload,
    )


def _decision(status: engine.DecisionStatus) -> engine.Decision:
    return engine.Decision(activation_id=DECISION, node_id="review", status=status)


# ── gates ────────────────────────────────────────────────────────────────────


def test_a_newly_open_gate_row_raises_one_gate_alert_naming_its_prompt() -> None:
    changes = _alerts(final=_state(gates=(_visit(),)), drafts=(_draft(GateVisitStatus.OPEN),))

    assert changes == AlertChanges(
        raises=(
            AlertDraft(
                id=alert_id(WORKSPACE, RUN_ID, "gate", VISIT_ID),
                run_id=RUN_ID,
                kind=int(AlertKind.GATE),
                priority=int(AlertPriority.NORMAL),
                subject_id=VISIT_ID,
                payload=AlertPayload(
                    title="Approval needed",
                    message="Ship it?",
                    run_title="Ship the bridge",
                    step_label="Approve",
                    node_id="approve",
                    actions=("answer", "open_run"),
                    deep_link=f"{RUN_LINK}?node=approve&panel=gate",
                    approve_link=f"/approve/{ANCHOR}/{EID}",
                    elicitation_id=EID,
                    session_id=ANCHOR,
                    outcomes=("approve", "reject"),
                ).model_dump_json(),
                owner_user_id="alice",
                account_generation="gen-1",
            ),
        )
    )


@pytest.mark.parametrize(
    ("loaded", "raised"),
    [
        pytest.param(None, True, id="no-row"),
        pytest.param(GateVisitStatus.CANCELLED, True, id="row-not-open"),
        pytest.param(GateVisitStatus.OPEN, False, id="row-already-open"),
    ],
)
def test_a_gate_alert_is_raised_only_when_its_row_becomes_open(
    loaded: GateVisitStatus | None, raised: bool
) -> None:
    changes = _alerts(
        final=_state(gates=(_visit(),)),
        loaded=() if loaded is None else (_row(loaded),),
        drafts=(_draft(GateVisitStatus.OPEN),),
    )

    assert [draft.subject_id for draft in changes.raises] == ([VISIT_ID] if raised else [])
    assert changes.resolutions == ()


@pytest.mark.parametrize("left", ["resolved", "superseded"])
def test_a_row_that_leaves_open_resolves_its_gate_alert(left: engine.GateStatus) -> None:
    status = GateVisitStatus.RESOLVED if left == "resolved" else GateVisitStatus.SUPERSEDED

    changes = _alerts(
        first=_state(gates=(_visit(),)),
        final=_state(gates=(_visit(status=left),)),
        loaded=(_row(GateVisitStatus.OPEN),),
        drafts=(_draft(status),),
    )

    assert changes == AlertChanges(resolutions=(AlertResolution(subject_id=VISIT_ID),))


def test_a_commit_that_changes_nothing_raises_and_resolves_nothing() -> None:
    state = _state(gates=(_visit(),), decisions=(_decision("escalated"),))

    assert _alerts(first=state, loaded=(_row(GateVisitStatus.OPEN),)) == AlertChanges()


def test_a_gate_with_other_outcomes_and_no_prompt_asks_for_a_decision() -> None:
    graph = _gate_graph(["ship", "hold", "drop"], name="Pick a path")

    (raised,) = _alerts(
        graph=graph, final=_state(gates=(_visit(),)), drafts=(_draft(GateVisitStatus.OPEN),)
    ).raises

    payload = _payload(raised)
    assert (payload.title, payload.message, payload.step_label) == (
        "Decision needed",
        "Pick a path is waiting for your answer.",
        "Pick a path",
    )
    assert (payload.outcomes, payload.approve_link) == (("ship", "hold", "drop"), None)


def test_an_approve_only_gate_is_an_approval_with_its_approve_link() -> None:
    (raised,) = _alerts(
        graph=_gate_graph(["approve"]),
        final=_state(gates=(_visit(),)),
        drafts=(_draft(GateVisitStatus.OPEN),),
    ).raises

    payload = _payload(raised)
    assert (payload.title, payload.message, payload.step_label) == (
        "Approval needed",
        "approve is waiting for your answer.",
        "approve",
    )
    assert payload.approve_link == f"/approve/{ANCHOR}/{EID}"


# ── pauses ───────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("before", "reason"),
    [
        (RunStatus.RUNNING, RunPauseReason.DRIFT),
        (RunStatus.STARTING, RunPauseReason.FAILURE_PATH),
    ],
)
def test_a_row_that_becomes_paused_raises_one_pause_alert_for_that_pause(
    before: RunStatus, reason: RunPauseReason
) -> None:
    run = _run(before)

    changes = _alerts(run=run, status=RunStatus.PAUSED, reason=reason)

    name = reason.name.lower()
    assert changes == AlertChanges(
        raises=(
            AlertDraft(
                id=alert_id(WORKSPACE, RUN_ID, "pause", "6"),
                run_id=RUN_ID,
                kind=int(AlertKind.PAUSE),
                priority=int(AlertPriority.NORMAL),
                subject_id=alert_subject(RUN_ID, "pause"),
                payload=AlertPayload(
                    title="Run paused",
                    message=PAUSE_MESSAGES[name],
                    run_title="Ship the bridge",
                    actions=("open_run", "mark_read"),
                    deep_link=RUN_LINK,
                    pause_reason=name,
                ).model_dump_json(),
                owner_user_id="alice",
                account_generation="gen-1",
            ),
        )
    )
    # A store-only pause raises the same alert.
    assert row_pause_alert(run, int(reason)) == changes.raises[0]


def test_a_user_pause_and_a_pause_that_stays_raise_nothing() -> None:
    assert _alerts(status=RunStatus.PAUSED, reason=RunPauseReason.USER) == AlertChanges()
    assert row_pause_alert(_run(), int(RunPauseReason.USER)) is None
    by_user = _run(RunStatus.PAUSED, pause_reason=RunPauseReason.USER)
    assert _alerts(run=by_user, status=RunStatus.PAUSED, reason=RunPauseReason.USER) == (
        AlertChanges()
    )
    # A cause that changes between non-user reasons keeps the alert already raised.
    drifted = _run(RunStatus.PAUSED, pause_reason=RunPauseReason.DRIFT)
    assert _alerts(run=drifted, status=RunStatus.PAUSED, reason=RunPauseReason.AUTH) == (
        AlertChanges()
    )


@pytest.mark.parametrize("reason", [RunPauseReason.FAILURE_PATH, RunPauseReason.DRIFT])
def test_a_user_pause_that_gains_another_cause_raises_that_pause_s_alert(
    reason: RunPauseReason,
) -> None:
    by_user = _run(RunStatus.PAUSED, pause_reason=RunPauseReason.USER)

    changes = _alerts(run=by_user, status=RunStatus.PAUSED, reason=reason)

    assert changes == AlertChanges(raises=(row_pause_alert(by_user, int(reason)),))
    (raised,) = changes.raises
    assert raised.id == alert_id(WORKSPACE, RUN_ID, "pause", "6")
    assert _payload(raised).pause_reason == reason.name.lower()


def test_a_row_that_stops_being_paused_resolves_its_pause_alerts() -> None:
    paused = _run(RunStatus.PAUSED, pause_reason=RunPauseReason.DRIFT)

    changes = _alerts(run=paused, status=RunStatus.RUNNING)

    assert changes == AlertChanges(
        resolutions=(AlertResolution(subject_id=alert_subject(RUN_ID, "pause")),)
    )


def test_every_pause_reason_but_user_has_its_own_message() -> None:
    names = {reason.name.lower() for reason in RunPauseReason}

    assert set(PAUSE_MESSAGES) == names - {"user"}
    for reason in RunPauseReason:
        draft = row_pause_alert(_run(), int(reason))
        if reason is RunPauseReason.USER:
            assert draft is None
            continue
        assert draft is not None
        payload = _payload(draft)
        assert (payload.message, payload.pause_reason) == (
            PAUSE_MESSAGES[reason.name.lower()],
            reason.name.lower(),
        )


# ── decision watchdogs ───────────────────────────────────────────────────────


def test_a_decision_s_watchdog_alert_stage_raises_a_watchdog_alert() -> None:
    notify = _notify(DECISION)

    changes = _alerts(
        graph=LOOP,
        first=_state(decisions=(_decision("reminded"),)),
        final=_state(decisions=(_decision("escalated"),)),
        effects=(notify,),
    )

    assert changes == AlertChanges(
        raises=(
            AlertDraft(
                id=alert_id(WORKSPACE, RUN_ID, "watchdog", notify.effect_key),
                run_id=RUN_ID,
                kind=int(AlertKind.WATCHDOG),
                priority=int(AlertPriority.NORMAL),
                subject_id=alert_subject(RUN_ID, "decision", DECISION),
                payload=AlertPayload(
                    title="Decision waiting",
                    message="The orchestrator has not chosen at review for an hour.",
                    run_title="Ship the bridge",
                    step_label="review",
                    node_id="review",
                    actions=("open_run", "mark_read"),
                    deep_link=f"{RUN_LINK}?node=review",
                ).model_dump_json(),
                owner_user_id="alice",
                account_generation="gen-1",
            ),
        )
    )


@pytest.mark.parametrize(
    ("notify", "decision"),
    [
        pytest.param(_notify(DECISION, stage="reminder"), "reminded", id="reminder-stage"),
        pytest.param(_notify(APPROVE), "escalated", id="gate-watchdog"),
        pytest.param(_notify(DECISION), "decided", id="decided-in-the-same-commit"),
        pytest.param(_notify(RUN_ID, kind="run_cancelled"), "escalated", id="run-cancelled"),
        pytest.param(_notify(DECISION, kind="pause"), "escalated", id="pause"),
    ],
)
def test_only_an_open_decision_s_alert_stage_raises_a_watchdog_alert(
    notify: engine.Effect, decision: engine.DecisionStatus
) -> None:
    final = _state(gates=(_visit(),), decisions=(_decision(decision),))

    changes = _alerts(graph=LOOP, first=final, final=final, effects=(notify,))

    assert changes.raises == ()


def test_a_decision_that_is_decided_resolves_its_watchdog_alert() -> None:
    changes = _alerts(
        graph=LOOP,
        first=_state(decisions=(_decision("escalated"),)),
        final=_state(decisions=(_decision("decided"),)),
    )

    assert changes == AlertChanges(
        resolutions=(AlertResolution(subject_id=alert_subject(RUN_ID, "decision", DECISION)),)
    )


# ── run ends ─────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("ended", "name", "title", "message"),
    [
        (RunStatus.COMPLETED, "run_completed", "Run completed", "The run finished."),
        (RunStatus.FAILED, "run_failed", "Run failed", "The run failed."),
        (RunStatus.CANCELLED, "run_cancelled", "Run cancelled", "The run was cancelled."),
    ],
)
def test_a_run_that_ends_raises_a_low_alert_and_resolves_what_waited_on_it(
    ended: RunStatus, name: AlertKindName, title: str, message: str
) -> None:
    changes = _alerts(status=ended)

    assert changes == AlertChanges(
        raises=(
            AlertDraft(
                id=alert_id(WORKSPACE, RUN_ID, name, name),
                run_id=RUN_ID,
                kind=int(AlertKind[name.upper()]),
                priority=int(AlertPriority.LOW),
                subject_id=alert_subject(RUN_ID, "run"),
                payload=AlertPayload(
                    title=title,
                    message=message,
                    run_title="Ship the bridge",
                    actions=("open_run", "mark_read"),
                    deep_link=RUN_LINK,
                ).model_dump_json(),
                owner_user_id="alice",
                account_generation="gen-1",
            ),
        ),
        resolutions=(AlertResolution(kinds=NEEDS_AN_ANSWER),),
    )


def test_a_paused_run_that_ends_also_resolves_its_pause_alerts() -> None:
    paused = _run(RunStatus.PAUSED, pause_reason=RunPauseReason.DRIFT)

    changes = _alerts(run=paused, status=RunStatus.CANCELLED)

    assert [draft.kind for draft in changes.raises] == [int(AlertKind.RUN_CANCELLED)]
    assert changes.resolutions == (
        AlertResolution(subject_id=alert_subject(RUN_ID, "pause")),
        AlertResolution(kinds=NEEDS_AN_ANSWER),
    )


def test_a_finished_run_raises_nothing_more() -> None:
    finished = _run(RunStatus.COMPLETED)

    assert _alerts(run=finished, status=RunStatus.COMPLETED) == AlertChanges()


# ── one commit, raises and resolutions together ──────────────────────────────


def test_a_loop_back_resolves_the_first_visit_s_alert_and_raises_the_second_s() -> None:
    again = gate_visit_id(RUN_ID, APPROVE_TOKEN_AGAIN)

    changes = _alerts(
        first=_state(gates=(_visit(),)),
        final=_state(gates=(_visit(status="superseded"), _visit(APPROVE_TOKEN_AGAIN, visit_no=2))),
        loaded=(_row(GateVisitStatus.OPEN),),
        drafts=(
            _draft(GateVisitStatus.SUPERSEDED),
            _draft(GateVisitStatus.OPEN, APPROVE_TOKEN_AGAIN, EID_AGAIN, visit_no=2),
        ),
    )

    (raised,) = changes.raises
    assert (raised.id, raised.subject_id, _payload(raised).elicitation_id) == (
        alert_id(WORKSPACE, RUN_ID, "gate", again),
        again,
        EID_AGAIN,
    )
    assert changes.resolutions == (AlertResolution(subject_id=VISIT_ID),)


def test_a_cancel_at_an_open_gate_resolves_its_alert_and_raises_run_cancelled() -> None:
    changes = _alerts(
        first=_state(gates=(_visit(),)),
        final=_state("cancelled", gates=(_visit(),)),
        effects=(_notify(RUN_ID, kind="run_cancelled"),),
        loaded=(_row(GateVisitStatus.OPEN),),
        drafts=(_draft(GateVisitStatus.CANCELLED),),
        status=RunStatus.CANCELLED,
    )

    assert [(draft.kind, draft.priority) for draft in changes.raises] == [
        (int(AlertKind.RUN_CANCELLED), int(AlertPriority.LOW))
    ]
    assert changes.resolutions == (
        AlertResolution(subject_id=VISIT_ID),
        AlertResolution(kinds=NEEDS_AN_ANSWER),
    )


def test_the_same_commit_gives_the_same_alerts() -> None:
    def changes() -> AlertChanges:
        return _alerts(
            first=_state(gates=(_visit(),)),
            final=_state("cancelled", gates=(_visit(),)),
            loaded=(_row(GateVisitStatus.OPEN),),
            drafts=(_draft(GateVisitStatus.CANCELLED),),
            status=RunStatus.CANCELLED,
        )

    assert changes() == changes()


# ── text and size ────────────────────────────────────────────────────────────


def test_free_text_loses_format_characters_and_is_cut_to_its_field() -> None:
    graph = _with_gate(
        name="Ap‮prove​\nchange",
        prompt="Ship\x00 it?\n⁦Now,\ud800 please." + " more" * 100,
    )
    run = _run(title="Fix\tthe‍ parser " + "x" * 300)

    (raised,) = _alerts(
        run=run,
        graph=graph,
        final=_state(gates=(_visit(),)),
        drafts=(_draft(GateVisitStatus.OPEN),),
    ).raises

    payload = _payload(raised)
    assert payload.step_label == "Approve change"
    assert payload.message.startswith("Ship it? Now, please. more more")
    assert payload.message.endswith("…") and len(payload.message) == 280
    assert payload.run_title.startswith("Fix the parser xxx")
    assert payload.run_title.endswith("…") and len(payload.run_title) == 256


def test_the_largest_gate_alert_fits_its_column() -> None:
    # Private-use characters are kept by the cleaning, take four UTF-8 bytes each and,
    # drawn at random, barely compress.
    chars = random.Random(134)

    def wide(length: int) -> str:
        return "".join(chr(chars.randrange(0xF0000, 0xFFFFE)) for _ in range(length))

    graph = _with_gate(
        name=wide(1_000), prompt=wide(5_000), outcomes=tuple(wide(128) for _ in range(16))
    )
    run = _run(title=wide(1_000))

    # Building the draft refuses a payload its column cannot hold.
    (raised,) = _alerts(
        run=run,
        graph=graph,
        final=_state(gates=(_visit(),)),
        drafts=(_draft(GateVisitStatus.OPEN),),
    ).raises

    payload = _payload(raised)
    assert (len(payload.message), len(payload.run_title), len(payload.step_label or "")) == (
        280,
        256,
        128,
    )
    assert len(payload.outcomes) == 16
    framed = encode(raised.payload)
    assert framed is not None
    assert len(framed) <= MAX_STORED_BYTES, f"{len(framed)} bytes stored"


# ── ids ──────────────────────────────────────────────────────────────────────


def test_alert_ids_and_subjects_derive_from_what_names_them() -> None:
    gate_alert = alert_id(WORKSPACE, RUN_ID, "gate", VISIT_ID)
    others = {
        alert_id(WORKSPACE + 1, RUN_ID, "gate", VISIT_ID),
        alert_id(WORKSPACE, "b" * 32, "gate", VISIT_ID),
        alert_id(WORKSPACE, RUN_ID, "pause", VISIT_ID),
        alert_id(WORKSPACE, RUN_ID, "gate", "6"),
    }
    subjects = {
        alert_subject(RUN_ID, "pause"),
        alert_subject(RUN_ID, "run"),
        alert_subject("b" * 32, "pause"),
        alert_subject(RUN_ID, "decision", DECISION),
    }

    assert gate_alert not in others and len(others) == 4 and len(subjects) == 4
    assert all(len(value) == 32 for value in (gate_alert, *others, *subjects))
    assert all(int(value, 16) >= 0 for value in (gate_alert, *subjects))
