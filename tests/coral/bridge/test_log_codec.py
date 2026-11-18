"""Engine log entries as run-log rows: drafts, actors, scopes, size and decoding."""

from __future__ import annotations

import dataclasses
import json
import random
from datetime import timedelta, timezone

import pytest

from coral.bridge.codec import EngineLogDecodeError, actor_kind, decode_entries, entry_draft
from coral.bridge.config import epoch_us
from coral.bridge.keys import store_activation_id
from coral.db import MAX_STORED_BYTES, encode
from coral.db.enum_codecs import ActorKind, LogKind
from coral.engine.types import (
    AnswerGate,
    CancelRun,
    ChooseArrow,
    EffectCompleted,
    EffectFailed,
    HandoffEvaluated,
    HandoffReceived,
    InfraBackoffExhausted,
    Input,
    LogEntry,
    PauseRun,
    PostCloseActivity,
    RejectionObserved,
    ResumeRun,
    RetryStep,
    RunnerLost,
    RunState,
    SessionFailed,
    StartRun,
    TimerDue,
    TurnEnded,
    UsageLimited,
    WaitingWithoutElicitation,
)
from coral.stores.protocols import LogEntryDraft, RunLogEntry
from coral.tools.schemas import HANDOFF_BODY_MAX_BYTES
from tests.coral.bridge._scripted_runs import (
    IMPLEMENT,
    RUN_ID,
    WORKSPACE,
    accept,
    exercise,
    fixture_graph,
    replay,
    start_run,
)
from tests.coral.engine.drive import NOW, drive
from tests.coral.workflow_builders import FIXTURES

ACTOR = "user-alice"


def _stored(draft: LogEntryDraft, seq: int, run_version: int = 2) -> RunLogEntry:
    """The row a store writes for ``draft``."""
    return RunLogEntry(
        workspace_id=WORKSPACE,
        run_id=RUN_ID,
        seq=seq,
        run_version=run_version,
        log_version=1,
        kind=draft.kind,
        actor_kind=draft.actor_kind,
        body=draft.body,
        created_at_us=draft.created_at_us or 0,
        audit_only=draft.audit_only,
        actor_ref=draft.actor_ref,
        activation_id=draft.activation_id,
        node_id=draft.node_id,
        scope_key=draft.scope_key,
        view_patch=draft.view_patch,
    )


@pytest.mark.parametrize("fixture", sorted(path.stem for path in FIXTURES.glob("*.yaml")))
def test_every_logged_entry_of_every_fixture_round_trips(fixture: str) -> None:
    graph = fixture_graph(fixture)
    steps = replay(graph, exercise(graph).log)
    assert any(step.entry.rejection is not None for step in steps)
    for seq, step in enumerate(steps, start=1):
        draft = entry_draft(step.entry, run_id=RUN_ID, before=step.before, actor=ACTOR)
        assert draft.kind == int(LogKind.ENGINE)
        assert draft.audit_only is (step.entry.rejection is not None)
        assert draft.actor_kind == int(actor_kind(step.entry.input))
        assert draft.actor_ref == ACTOR
        assert draft.idempotency_cksum is None
        assert draft.created_at_us == epoch_us(step.entry.now)
        assert LogEntry.model_validate_json(draft.body) == step.entry
        if step.entry.patch:
            assert draft.view_patch == json.dumps(
                [patch.model_dump(mode="json") for patch in step.entry.patch]
            )
        else:
            assert draft.view_patch is None
        decoded = decode_entries([_stored(draft, seq)])
        assert decoded == ([] if draft.audit_only else [step.entry])


@pytest.mark.parametrize(
    ("command", "expected"),
    [
        (StartRun(run_id=RUN_ID, start_key="k", version_hash="h"), ActorKind.USER),
        (PauseRun(reason="user", detail="look"), ActorKind.USER),
        (PauseRun(reason="infra", detail="anchor:session.failed"), ActorKind.ENGINE),
        (PauseRun(reason="drift", detail="anchor_bound"), ActorKind.ENGINE),
        (ResumeRun(), ActorKind.USER),
        (CancelRun(), ActorKind.USER),
        (RetryStep(node_id="implement"), ActorKind.USER),
        (AnswerGate(token="t", label="approve", by="alice"), ActorKind.USER),
        (EffectCompleted(effect_key="k"), ActorKind.ENGINE),
        (EffectFailed(effect_key="k", code="session.failed"), ActorKind.ENGINE),
        (HandoffReceived(slot_id=IMPLEMENT, body="b"), ActorKind.STEP_AGENT),
        (HandoffEvaluated(slot_id=IMPLEMENT, outcome="accepted"), ActorKind.STEP_AGENT),
        (RejectionObserved(slot_id=IMPLEMENT, code="handoff.invalid"), ActorKind.STEP_AGENT),
        (ChooseArrow(node_id="triage", label="ship", reason="r"), ActorKind.ORCHESTRATOR),
        (TimerDue(timer_key="watchdog_remind:x:1"), ActorKind.ENGINE),
        (TurnEnded(slot_id=IMPLEMENT, fact_key="turn:s:1:a"), ActorKind.ENGINE),
        (RunnerLost(slot_id=IMPLEMENT, session_id="s", generation=1), ActorKind.ENGINE),
        (UsageLimited(slot_id=IMPLEMENT, fact_key="f"), ActorKind.ENGINE),
        (WaitingWithoutElicitation(slot_id=IMPLEMENT, fact_key="f"), ActorKind.ENGINE),
        (
            SessionFailed(slot_id=IMPLEMENT, failure_class="auth", cause="401", fact_key="f"),
            ActorKind.ENGINE,
        ),
        (PostCloseActivity(slot_id=IMPLEMENT), ActorKind.ENGINE),
        (InfraBackoffExhausted(slot_id=IMPLEMENT), ActorKind.ENGINE),
    ],
)
def test_each_input_kind_is_logged_with_its_actor_kind(
    command: Input, expected: ActorKind
) -> None:
    assert actor_kind(command) is expected


def test_an_input_naming_a_slot_is_scoped_to_its_activation_node_and_slot() -> None:
    graph = fixture_graph("two_steps")
    started = drive(graph, [start_run(graph)])
    handoff = drive(graph, accept(IMPLEMENT, "done")[:1], after=started)
    entry = handoff.log[-1]
    draft = entry_draft(entry, run_id=RUN_ID, before=started.state, actor=None)
    assert draft.activation_id == store_activation_id(RUN_ID, "implement||")
    assert len(draft.activation_id) == 32
    assert (draft.node_id, draft.scope_key) == ("implement", IMPLEMENT)
    assert draft.actor_ref is None

    run_level = entry_draft(started.log[0], run_id=RUN_ID, before=RunState(), actor=ACTOR)
    assert (run_level.activation_id, run_level.node_id, run_level.scope_key) == (None, None, None)
    unknown = LogEntry(seq=9, input=TurnEnded(slot_id="ghost||:0", fact_key="turn:s:1:x"), now=NOW)
    draft = entry_draft(unknown, run_id=RUN_ID, before=started.state, actor=None)
    assert (draft.activation_id, draft.node_id, draft.scope_key) == (None, None, None)


def test_an_entry_not_stamped_in_utc_is_refused() -> None:
    berlin = timezone(timedelta(hours=1))
    entry = LogEntry(seq=1, input=ResumeRun(), now=NOW.astimezone(berlin))
    with pytest.raises(ValueError, match="UTC"):
        entry_draft(entry, run_id=RUN_ID, before=RunState(), actor=None)


def test_the_actor_reference_is_cut_to_its_column() -> None:
    entry = LogEntry(seq=1, input=ResumeRun(), now=NOW)
    draft = entry_draft(entry, run_id=RUN_ID, before=RunState(), actor="u" * 300)
    assert draft.actor_ref == "u" * 128


@pytest.mark.parametrize(
    "alphabet",
    [
        # Control characters escape six-fold inside the body and again inside the entry.
        [chr(code) for code in range(1, 0x20)] + ['"', "\\", "a"],
        # High-entropy printable text compresses least.
        [chr(code) for code in range(0x20, 0x7F)],
    ],
    ids=["escaped", "high_entropy"],
)
def test_the_largest_handoff_body_still_fits_one_log_row(alphabet: list[str]) -> None:
    rng = random.Random(149)
    # A full body fills its last bytes with artifacts; a longer report stands in for them.
    report = "".join(rng.choice(alphabet) for _ in range(16_000))
    while True:
        body = json.dumps(
            {"activation_id": "implement||", "report": report, "status": "done"},
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        )
        if len(body.encode()) <= HANDOFF_BODY_MAX_BYTES:
            break
        report = report[:-50]
    assert len(body.encode()) > HANDOFF_BODY_MAX_BYTES - 400
    entry = LogEntry(
        seq=7,
        input=HandoffReceived(slot_id=IMPLEMENT, body=body, label="x" * 200),
        now=NOW + timedelta(days=365),
    )
    draft = entry_draft(entry, run_id=RUN_ID, before=RunState(), actor=ACTOR)
    framed = encode(draft.body)
    assert framed is not None
    assert len(framed) <= MAX_STORED_BYTES


def test_decoding_skips_audit_and_other_rows_and_refuses_a_corrupt_body() -> None:
    graph = fixture_graph("two_steps")
    started = drive(graph, [start_run(graph)])
    good = entry_draft(started.log[0], run_id=RUN_ID, before=RunState(), actor=ACTOR)
    refused = LogEntry(
        seq=2,
        input=HandoffEvaluated(slot_id="ghost", outcome="accepted"),
        now=NOW,
        rejection={"code": "rejected"},
    )
    audit = entry_draft(refused, run_id=RUN_ID, before=started.state, actor=None)
    assert audit.audit_only
    other = LogEntryDraft(kind=int(LogKind.PAUSED), actor_kind=int(ActorKind.ENGINE), body="{}")
    rows = [_stored(good, 1), _stored(audit, 2), _stored(other, 3)]
    assert decode_entries(rows) == [started.log[0]]

    corrupt = dataclasses.replace(_stored(good, 4), body='{"seq": "x"')
    with pytest.raises(EngineLogDecodeError, match="seq 4"):
        decode_entries([*rows, corrupt])


def _with_field(body: str, path: tuple[str, ...], value: object) -> str:
    fields = json.loads(body)
    target = fields
    for name in path[:-1]:
        target = target[name]
    target[path[-1]] = value
    return json.dumps(fields)


def test_rows_from_a_newer_engine_or_cut_short_are_refused_without_their_text() -> None:
    graph = fixture_graph("two_steps")
    started = drive(graph, [start_run(graph)])
    handoff = drive(graph, accept(IMPLEMENT, "SECRET report text")[:1], after=started)
    good = _stored(
        entry_draft(handoff.log[-1], run_id=RUN_ID, before=started.state, actor=None), 5
    )
    assert decode_entries([good]) == [handoff.log[-1]]
    unreadable = {
        "a field of a newer entry": _with_field(good.body, ("future",), 1),
        "a field of a newer input": _with_field(good.body, ("input", "future"), 1),
        "an input kind of a newer engine": _with_field(good.body, ("input", "kind"), "future"),
        "a body cut short": good.body[: len(good.body) // 2],
        "an empty body": "",
    }
    for case, body in unreadable.items():
        with pytest.raises(EngineLogDecodeError) as raised:
            decode_entries([dataclasses.replace(good, body=body)])
        message = str(raised.value)
        assert "seq 5" in message and RUN_ID in message, case
        assert "SECRET" not in message and "future" not in message, case
        assert raised.value.__cause__ is None and raised.value.__suppress_context__, case
        # An audit-only row is never replayed, so its body is never read.
        audit = dataclasses.replace(good, body=body, audit_only=True)
        assert decode_entries([audit]) == [], case
