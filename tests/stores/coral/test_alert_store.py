"""Alert store on every DB lane: writes ride the run commit, the owner's feed, and ack."""

from __future__ import annotations

import dataclasses
import random
import sqlite3
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

import pytest
from sqlalchemy import event, update
from sqlalchemy.exc import IntegrityError

import coral.stores.runs as run_store_module
from coral.alerts.types import (
    LOCAL_USER_ID,
    MAX_ALERT_OUTCOME_CHARS,
    MAX_ALERT_OUTCOMES,
    AlertPayload,
)
from coral.db import AlertRow, coral_engine
from coral.db.enum_codecs import AlertKind, AlertPriority, AlertStatus
from coral.model.ids import derived_id
from coral.omni.protocols import Viewer
from coral.stores.alerts import SqlAlchemyAlertStore
from coral.stores.fakes import FakeRunStore
from coral.stores.protocols import (
    AlertDraft,
    AlertRecord,
    AlertResolution,
    LogEntryDraft,
    RunStore,
    RunVersionConflict,
    ToolReplyDraft,
    Transition,
    TransitionTooLarge,
)
from omnigent.db import current_query_name
from tests.stores.coral._alerts import (
    ALICE,
    BOB,
    NOW,
    OTHER_WORKSPACE,
    WORKSPACE,
    alert_draft,
    alert_payload,
    commit_alert_changes,
    start_owned_run,
)
from tests.stores.coral._faults import SimulatedCrash, crash_around, fresh_process, run_racing
from tests.stores.coral.conftest import CoralSplitDb

OPEN = int(AlertStatus.OPEN)
ACKED = int(AlertStatus.ACKED)
RESOLVED = int(AlertStatus.RESOLVED)


@dataclass(frozen=True)
class _Stores:
    runs: RunStore
    read: Callable[[str], list[AlertRecord]]
    mark_acked: Callable[[str], None]


@pytest.fixture(params=["sql", "fake"])
def stores(request: pytest.FixtureRequest) -> _Stores:
    """The SQL run store or the fake; each parity test holds both to the same expectations."""
    if request.param == "fake":
        fake = FakeRunStore(default_workspace_id=WORKSPACE)

        def fake_ack(alert_id: str) -> None:
            key = (WORKSPACE, alert_id)
            fake.alerts[key] = dataclasses.replace(
                fake.alerts[key], status=ACKED, acked_at=NOW + 1, acked_by=ALICE
            )

        return _Stores(
            fake, lambda run_id: fake.list_alerts(run_id, workspace_id=WORKSPACE), fake_ack
        )
    uri = request.getfixturevalue("coral_db_uri")
    alerts = SqlAlchemyAlertStore(uri)

    def sql_ack(alert_id: str) -> None:
        outcome = alerts.ack(
            workspace_id=WORKSPACE, viewer=Viewer(ALICE), alert_id=alert_id, now=NOW + 1
        )
        assert outcome == "acked"

    return _Stores(
        run_store_module.SqlAlchemyCoralRunStore(uri),
        lambda run_id: alerts.list_for_run(workspace_id=WORKSPACE, run_id=run_id),
        sql_ack,
    )


def _sql(uri: str) -> tuple[RunStore, SqlAlchemyAlertStore]:
    return run_store_module.SqlAlchemyCoralRunStore(uri), SqlAlchemyAlertStore(uri)


def _inbox(
    alerts: SqlAlchemyAlertStore,
    viewer: Viewer,
    *,
    after: tuple[int, int, str] | None = None,
    limit: int = 100,
    workspace_id: int = WORKSPACE,
) -> tuple[list[str], tuple[int, int, str] | None]:
    page, cursor = alerts.list_inbox(
        workspace_id=workspace_id, viewer=viewer, after=after, limit=limit
    )
    return [record.id for record in page], cursor


def _newest_first(drafts: Sequence[AlertDraft]) -> list[str]:
    return [d.id for d in sorted(drafts, key=lambda d: (d.created_at, d.id), reverse=True)]


# ── Writes inside the run commit (SQL and fake) ──────────────────────────────


def test_a_repeated_raise_keeps_one_row_and_never_reopens(stores: _Stores) -> None:
    run = start_owned_run(stores.runs, "raise", generation="g1")
    pause = alert_draft(run, AlertKind.PAUSE, "2")
    later = dataclasses.replace(pause, payload=alert_payload("Changed"))

    # The same id twice in one commit: the first draft wins.
    commit_alert_changes(stores.runs, run, raises=(pause, later))
    commit_alert_changes(stores.runs, run, raises=(later,), now=NOW + 10)
    opened = AlertRecord(
        workspace_id=WORKSPACE,
        id=pause.id,
        run_id=run.id,
        owner_user_id=ALICE,
        account_generation="g1",
        kind=int(AlertKind.PAUSE),
        priority=int(AlertPriority.NORMAL),
        subject_id=pause.subject_id,
        status=OPEN,
        payload=pause.payload,
        created_at=NOW,
    )
    assert stores.read(run.id) == [opened]

    commit_alert_changes(
        stores.runs,
        run,
        resolutions=(AlertResolution(subject_id=pause.subject_id),),
        now=NOW + 20,
    )
    commit_alert_changes(stores.runs, run, raises=(pause,), now=NOW + 30)
    assert stores.read(run.id) == [
        dataclasses.replace(opened, status=RESOLVED, resolved_at=NOW + 20)
    ]


def test_a_raise_keeps_its_own_creation_time(stores: _Stores) -> None:
    run = start_owned_run(stores.runs, "created")
    stamped = alert_draft(run, AlertKind.WATCHDOG, "effect", created_at=NOW - 50)

    commit_alert_changes(stores.runs, run, raises=(stamped,), now=NOW)

    assert [(r.id, r.created_at) for r in stores.read(run.id)] == [(stamped.id, NOW - 50)]


def test_resolutions_move_only_the_runs_matching_open_or_acked_rows(stores: _Stores) -> None:
    run = start_owned_run(stores.runs, "resolve")
    other = start_owned_run(stores.runs, "other")
    shared_subject = "5" * 32
    gate = alert_draft(run, AlertKind.GATE, "visit", subject=shared_subject)
    pause = alert_draft(run, AlertKind.PAUSE, "2")
    watchdog = alert_draft(run, AlertKind.WATCHDOG, "effect")
    done = alert_draft(run, AlertKind.RUN_COMPLETED, "run_completed", priority=AlertPriority.LOW)
    other_gate = alert_draft(other, AlertKind.GATE, "visit", subject=shared_subject)
    commit_alert_changes(stores.runs, run, raises=(gate, pause, watchdog, done))
    commit_alert_changes(stores.runs, other, raises=(other_gate,))
    stores.mark_acked(watchdog.id)

    def states(run_id: str) -> dict[str, tuple[int, int | None]]:
        return {r.id: (r.status, r.resolved_at) for r in stores.read(run_id)}

    commit_alert_changes(
        stores.runs,
        run,
        resolutions=(AlertResolution(subject_id=shared_subject),),
        now=NOW + 5,
    )
    assert states(run.id) == {
        gate.id: (RESOLVED, NOW + 5),
        pause.id: (OPEN, None),
        watchdog.id: (ACKED, None),
        done.id: (OPEN, None),
    }

    blocking = (AlertKind.GATE, AlertKind.QUESTION, AlertKind.PAUSE, AlertKind.WATCHDOG)
    commit_alert_changes(
        stores.runs,
        run,
        resolutions=(AlertResolution(kinds=tuple(int(kind) for kind in blocking)),),
        now=NOW + 9,
    )
    # A resolved row keeps its first resolution time.
    assert states(run.id) == {
        gate.id: (RESOLVED, NOW + 5),
        pause.id: (RESOLVED, NOW + 9),
        watchdog.id: (RESOLVED, NOW + 9),
        done.id: (OPEN, None),
    }
    assert states(other.id) == {other_gate.id: (OPEN, None)}


def test_alerts_land_only_with_their_entry(stores: _Stores) -> None:
    run = start_owned_run(stores.runs, "atomic")
    pause = alert_draft(run, AlertKind.PAUSE, "2")

    with pytest.raises(RunVersionConflict):
        commit_alert_changes(stores.runs, run, raises=(pause,), expected_version=run.version + 1)
    with pytest.raises(TransitionTooLarge, match="65 alert raises"):
        commit_alert_changes(
            stores.runs,
            run,
            raises=tuple(alert_draft(run, AlertKind.PAUSE, str(i)) for i in range(65)),
        )
    with pytest.raises(ValueError, match="another run"):
        commit_alert_changes(
            stores.runs, run, raises=(dataclasses.replace(pause, run_id="f" * 32),)
        )
    reply = ToolReplyDraft(b"\1" * 32, "{}")
    commit_alert_changes(stores.runs, run, tool_reply=reply)
    # A repeated tool reply refuses the whole transition, alerts included.
    with pytest.raises(IntegrityError):
        commit_alert_changes(stores.runs, run, raises=(pause,), tool_reply=reply)

    assert stores.read(run.id) == []
    assert len(stores.runs.read_log(run.id, workspace_id=WORKSPACE)) == 1
    current = stores.runs.get_run(run.id, workspace_id=WORKSPACE)
    assert current is not None and current.version == run.version + 1

    commit_alert_changes(
        stores.runs,
        run,
        raises=tuple(alert_draft(run, AlertKind.PAUSE, str(i)) for i in range(64)),
    )
    assert len(stores.read(run.id)) == 64


def test_a_new_raise_on_a_resolved_subject_opens_its_own_row(stores: _Stores) -> None:
    run = start_owned_run(stores.runs, "re-raise")
    subject = derived_id("coral-alert-subject", run.id, "pause")
    first, second, third = (
        alert_draft(run, AlertKind.PAUSE, key, subject=subject) for key in "246"
    )

    def states() -> dict[str, tuple[int, int | None]]:
        return {r.id: (r.status, r.resolved_at) for r in stores.read(run.id)}

    commit_alert_changes(stores.runs, run, raises=(first,))
    commit_alert_changes(
        stores.runs, run, resolutions=(AlertResolution(subject_id=subject),), now=NOW + 1
    )
    commit_alert_changes(stores.runs, run, raises=(first, second), now=NOW + 2)
    stores.mark_acked(second.id)
    # A re-raise neither reopens a resolved row nor an acked one.
    commit_alert_changes(stores.runs, run, raises=(second,), now=NOW + 3)
    assert states() == {first.id: (RESOLVED, NOW + 1), second.id: (ACKED, None)}

    # Raises are written first, so a resolution in the same commit closes them too.
    commit_alert_changes(
        stores.runs,
        run,
        raises=(third,),
        resolutions=(AlertResolution(subject_id=subject),),
        now=NOW + 4,
    )
    assert states() == {
        first.id: (RESOLVED, NOW + 1),
        second.id: (RESOLVED, NOW + 4),
        third.id: (RESOLVED, NOW + 4),
    }


def test_racing_commits_raising_one_alert_keep_the_first_writers_row(stores: _Stores) -> None:
    run = start_owned_run(stores.runs, "race")
    pause = alert_draft(run, AlertKind.PAUSE, "2")
    drafts = [dataclasses.replace(pause, payload=alert_payload(f"writer {i}")) for i in range(4)]

    def commit(index: int) -> None:
        # Each loss means another writer committed, so four attempts always suffice.
        for _ in range(4):
            current = stores.runs.get_run(run.id, workspace_id=WORKSPACE)
            assert current is not None
            try:
                stores.runs.apply_transition(
                    run.id,
                    current.version,
                    Transition(
                        alert_raises=(drafts[index],),
                        logs=(LogEntryDraft(kind=1, actor_kind=1, body=str(index)),),
                    ),
                    workspace_id=WORKSPACE,
                    now=NOW,
                )
                return
            except RunVersionConflict:
                continue
        raise AssertionError(f"writer {index} never committed")

    outcomes = run_racing(4, commit)

    assert [outcome.error for outcome in outcomes] == [None] * 4
    first_writer = int(stores.runs.read_log(run.id, workspace_id=WORKSPACE)[0].body)
    [stored] = stores.read(run.id)
    assert (stored.id, stored.payload) == (pause.id, drafts[first_writer].payload)


def _payload_at_every_limit() -> str:
    # Random 4-byte characters at every length limit: near the largest payload stored.
    chars = random.Random(0)

    def text(length: int) -> str:
        return "".join(chr(chars.randrange(0x10000, 0x110000)) for _ in range(length))

    def limit(name: str) -> int:
        [max_length] = AlertPayload.model_fields[name].metadata
        return int(max_length.max_length)

    fields: dict[str, Any] = {
        name: text(limit(name))
        for name in AlertPayload.model_fields
        if name not in {"actions", "outcomes"}
    }
    return AlertPayload(
        **fields,
        actions=("answer", "open_run", "mark_read", "resume", "cancel"),
        outcomes=tuple(text(MAX_ALERT_OUTCOME_CHARS) for _ in range(MAX_ALERT_OUTCOMES)),
    ).model_dump_json()


def test_a_payload_at_every_length_limit_round_trips(stores: _Stores) -> None:
    run = start_owned_run(stores.runs, "large")
    largest = dataclasses.replace(
        alert_draft(run, AlertKind.GATE, "visit"), payload=_payload_at_every_limit()
    )

    commit_alert_changes(stores.runs, run, raises=(largest,))

    assert [r.payload for r in stores.read(run.id)] == [largest.payload]


def test_a_raise_and_a_kinds_resolution_in_one_commit_land_resolved(stores: _Stores) -> None:
    run = start_owned_run(stores.runs, "raise-and-end")
    gate = alert_draft(run, AlertKind.GATE, "visit")
    done = alert_draft(run, AlertKind.RUN_COMPLETED, "run_completed", priority=AlertPriority.LOW)

    commit_alert_changes(
        stores.runs,
        run,
        raises=(gate, done),
        resolutions=(AlertResolution(kinds=(int(AlertKind.GATE),)),),
        now=NOW + 3,
    )

    assert {r.id: (r.status, r.resolved_at) for r in stores.read(run.id)} == {
        gate.id: (RESOLVED, NOW + 3),
        done.id: (OPEN, None),
    }


def test_the_local_user_is_stored_as_no_owner(stores: _Stores) -> None:
    run = start_owned_run(stores.runs, "local-owner", user_id=LOCAL_USER_ID)
    pause = alert_draft(run, AlertKind.PAUSE, "2")
    assert pause.owner_user_id == LOCAL_USER_ID

    commit_alert_changes(stores.runs, run, raises=(pause,))

    assert [(r.id, r.owner_user_id) for r in stores.read(run.id)] == [(pause.id, None)]


def test_an_alert_payload_too_large_for_its_column_is_refused() -> None:
    chars = random.Random(1)
    huge = "".join(chr(chars.randrange(0x10000, 0x110000)) for _ in range(6_000))

    # Refused when the draft is built, so neither store can write it.
    with pytest.raises(ValueError, match=r"alert payload is \d+ bytes after compression"):
        AlertDraft(
            id="1" * 32, run_id="2" * 32, kind=3, priority=1, subject_id="3" * 32, payload=huge
        )


def test_a_resolution_names_a_subject_or_kinds() -> None:
    assert AlertResolution(subject_id="5" * 32).kinds == ()
    assert AlertResolution(kinds=(int(AlertKind.GATE),)).subject_id is None
    with pytest.raises(ValueError, match="exactly one"):
        AlertResolution()
    with pytest.raises(ValueError, match="exactly one"):
        AlertResolution(subject_id="5" * 32, kinds=(int(AlertKind.GATE),))


def test_a_crash_after_the_alert_writes_rolls_back_the_whole_commit(
    coral_db_uri: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    runs, _ = _sql(coral_db_uri)
    run = start_owned_run(runs, "crash")
    crash_around(monkeypatch, run_store_module, "apply_alert_changes", when="after")

    with pytest.raises(SimulatedCrash):
        commit_alert_changes(runs, run, raises=(alert_draft(run, AlertKind.PAUSE, "2"),))

    engine = fresh_process(coral_db_uri)
    reopened = run_store_module.SqlAlchemyCoralRunStore(engine)
    assert SqlAlchemyAlertStore(engine).list_for_run(workspace_id=WORKSPACE, run_id=run.id) == []
    assert reopened.read_log(run.id, workspace_id=WORKSPACE) == []
    current = reopened.get_run(run.id, workspace_id=WORKSPACE)
    assert current is not None and current.version == run.version


def test_alerts_are_written_to_the_operational_db(coral_split_db: CoralSplitDb) -> None:
    runs, alerts = _sql(coral_split_db.operational_uri)
    run = start_owned_run(runs, "split")
    pause = alert_draft(run, AlertKind.PAUSE, "2")

    commit_alert_changes(runs, run, raises=(pause,))

    assert [r.id for r in alerts.list_for_run(workspace_id=WORKSPACE, run_id=run.id)] == [pause.id]
    with sqlite3.connect(coral_split_db.operational_path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM coral_alerts").fetchone() == (1,)
    with sqlite3.connect(coral_split_db.conversation_path) as connection:
        tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master")}
    assert "coral_alerts" not in tables


# ── The owner's inbox feed ───────────────────────────────────────────────────


def test_the_inbox_lists_only_the_viewers_open_alerts_in_the_workspace(
    coral_db_uri: str,
) -> None:
    runs, alerts = _sql(coral_db_uri)
    mine = start_owned_run(runs, "mine")
    open_pause = alert_draft(mine, AlertKind.PAUSE, "2")
    acked = alert_draft(mine, AlertKind.WATCHDOG, "effect")
    resolved = alert_draft(mine, AlertKind.GATE, "visit")
    commit_alert_changes(runs, mine, raises=(open_pause, acked, resolved))
    outcome = alerts.ack(workspace_id=WORKSPACE, viewer=Viewer(ALICE), alert_id=acked.id, now=NOW)
    assert outcome == "acked"
    commit_alert_changes(
        runs, mine, resolutions=(AlertResolution(subject_id=resolved.subject_id),)
    )
    others: dict[str, AlertDraft] = {}
    for key, user_id, workspace_id in (
        ("bobs", BOB, WORKSPACE),
        ("elsewhere", ALICE, OTHER_WORKSPACE),
        ("local-none", None, WORKSPACE),
        ("local-named", LOCAL_USER_ID, WORKSPACE),
    ):
        run = start_owned_run(runs, key, user_id=user_id, workspace_id=workspace_id)
        others[key] = alert_draft(run, AlertKind.PAUSE, "2")
        commit_alert_changes(runs, run, raises=(others[key],))

    assert _inbox(alerts, Viewer(ALICE)) == ([open_pause.id], None)
    # Owners compare exactly, even where the database collation folds them.
    for lookalike in ("ALICE", "alice ", "alicé"):
        assert _inbox(alerts, Viewer(lookalike)) == ([], None)
    assert _inbox(alerts, Viewer(BOB)) == ([others["bobs"].id], None)
    assert _inbox(alerts, Viewer(ALICE), workspace_id=OTHER_WORKSPACE) == (
        [others["elsewhere"].id],
        None,
    )
    local = _newest_first((others["local-none"], others["local-named"]))
    assert _inbox(alerts, Viewer(None)) == (local, None)
    assert _inbox(alerts, Viewer(LOCAL_USER_ID)) == (local, None)


def test_the_inbox_lists_normal_before_low_newest_first_and_pages_without_gaps(
    coral_db_uri: str,
) -> None:
    runs, alerts = _sql(coral_db_uri)
    run = start_owned_run(runs, "paging")
    normal = [
        alert_draft(run, AlertKind.PAUSE, f"normal-{i}", created_at=NOW + offset)
        for i, offset in enumerate((10, 20, 20, 30))
    ]
    # The newest alert is low priority; it still comes after every normal one.
    low = [
        alert_draft(
            run,
            AlertKind.RUN_COMPLETED,
            f"low-{i}",
            priority=AlertPriority.LOW,
            created_at=NOW + offset,
        )
        for i, offset in enumerate((40, 15, 15))
    ]
    commit_alert_changes(runs, run, raises=(*normal, *low))
    expected = _newest_first(normal) + _newest_first(low)

    assert _inbox(alerts, Viewer(ALICE)) == (expected, None)
    for limit in (1, 2, 3, 4, 7):
        seen: list[str] = []
        after: tuple[int, int, str] | None = None
        while True:
            page, cursor = alerts.list_inbox(
                workspace_id=WORKSPACE, viewer=Viewer(ALICE), after=after, limit=limit
            )
            assert 0 < len(page) <= limit
            seen.extend(record.id for record in page)
            if cursor is None:
                break
            assert cursor == (page[-1].priority, page[-1].created_at, page[-1].id)
            after = cursor
        assert seen == expected, limit


def test_the_inbox_lists_a_recorded_generation_only_to_a_viewer_who_proves_it(
    coral_db_uri: str,
) -> None:
    runs, alerts = _sql(coral_db_uri)
    recorded_run = start_owned_run(runs, "old-account", generation="g1")
    plain_run = start_owned_run(runs, "no-generation")
    recorded = alert_draft(recorded_run, AlertKind.PAUSE, "2", created_at=NOW + 2)
    plain = alert_draft(plain_run, AlertKind.PAUSE, "2", created_at=NOW + 1)
    commit_alert_changes(runs, recorded_run, raises=(recorded,))
    commit_alert_changes(runs, plain_run, raises=(plain,))
    newer_account = Viewer(ALICE, "g2", check_generation=True)

    assert _inbox(alerts, Viewer(ALICE, "g1", check_generation=True)) == (
        [recorded.id, plain.id],
        None,
    )
    assert _inbox(alerts, newer_account) == ([plain.id], None)
    assert _inbox(alerts, Viewer(ALICE, "g1", check_generation=False)) == ([plain.id], None)
    # Rows are dropped after paging, so a page can be empty and still continue.
    assert _inbox(alerts, newer_account, limit=1) == (
        [],
        (int(AlertPriority.NORMAL), NOW + 2, recorded.id),
    )
    assert _inbox(
        alerts,
        newer_account,
        after=(int(AlertPriority.NORMAL), NOW + 2, recorded.id),
        limit=1,
    ) == ([plain.id], None)


def test_paging_tied_alerts_among_hidden_rows_skips_and_repeats_none(coral_db_uri: str) -> None:
    runs, alerts = _sql(coral_db_uri)
    run = start_owned_run(runs, "many")
    # Three timestamps across both priorities, so ids break most ties.
    visible = [
        alert_draft(run, AlertKind.PAUSE, f"normal-{i}", created_at=NOW + i % 3) for i in range(18)
    ] + [
        alert_draft(
            run,
            AlertKind.RUN_COMPLETED,
            f"low-{i}",
            priority=AlertPriority.LOW,
            created_at=NOW + i % 3,
        )
        for i in range(12)
    ]
    commit_alert_changes(runs, run, raises=visible)
    # Another owner's rows and rows of a generation the viewer does not prove share every time.
    for key, user_id, generation in (("bobs", BOB, None), ("old-account", ALICE, "g1")):
        noise_run = start_owned_run(runs, key, user_id=user_id, generation=generation)
        commit_alert_changes(
            runs,
            noise_run,
            raises=[
                alert_draft(noise_run, AlertKind.PAUSE, f"noise-{i}", created_at=NOW + i % 3)
                for i in range(9)
            ],
        )
    by_priority = [[d for d in visible if d.priority == int(p)] for p in AlertPriority]
    expected = [alert_id for drafts in by_priority for alert_id in _newest_first(drafts)]

    def walk(limit: int, between_pages: Callable[[list[str]], None] = lambda _: None) -> list[str]:
        seen: list[str] = []
        after: tuple[int, int, str] | None = None
        while True:
            page, after = _inbox(alerts, Viewer(ALICE), after=after, limit=limit)
            assert len(page) <= limit
            seen.extend(page)
            if after is None:
                return seen
            between_pages(seen)

    for limit in (1, 4, 30, 31):
        assert walk(limit) == expected, limit

    # Rows change between pages: a seen row is acked, an unseen one resolves, a newer one opens.
    unseen = next(d for d in visible if d.id == expected[-1])
    newer = alert_draft(run, AlertKind.PAUSE, "newer", created_at=NOW + 10)
    changed: list[bool] = []

    def change_once(seen: list[str]) -> None:
        if changed or not seen:
            return
        changed.append(True)
        outcome = alerts.ack(
            workspace_id=WORKSPACE, viewer=Viewer(ALICE), alert_id=seen[0], now=NOW
        )
        assert outcome == "acked"
        commit_alert_changes(
            runs,
            run,
            raises=(newer,),
            resolutions=(AlertResolution(subject_id=unseen.subject_id),),
        )

    assert walk(4, change_once) == expected[:-1]
    assert _inbox(alerts, Viewer(ALICE))[0] == [newer.id, *expected[1:-1]]


def test_a_tampered_cursor_only_moves_within_the_viewers_alerts(coral_db_uri: str) -> None:
    runs, alerts = _sql(coral_db_uri)
    run = start_owned_run(runs, "tamper")
    bobs_run = start_owned_run(runs, "bobs", user_id=BOB)
    normal = alert_draft(run, AlertKind.PAUSE, "normal", created_at=NOW + 1)
    low = alert_draft(
        run, AlertKind.RUN_COMPLETED, "low", priority=AlertPriority.LOW, created_at=NOW + 2
    )
    bobs = alert_draft(bobs_run, AlertKind.PAUSE, "bobs", created_at=NOW + 3)
    commit_alert_changes(runs, run, raises=(normal, low))
    commit_alert_changes(runs, bobs_run, raises=(bobs,))
    mine = [normal.id, low.id]
    normal_priority, low_priority = int(AlertPriority.NORMAL), int(AlertPriority.LOW)

    # The inbox API refuses malformed cursors; the store treats any cursor as a position.
    for after, expected in (
        ((0, NOW, "f" * 32), mine),
        ((3, 0, "0" * 32), []),
        ((normal_priority, NOW + 3, bobs.id), mine),
        ((normal_priority, 2**63 - 1, "f" * 32), mine),
        ((normal_priority, -(2**63), ""), [low.id]),
        ((low_priority, NOW + 2, low.id), []),
    ):
        assert _inbox(alerts, Viewer(ALICE), after=after) == (expected, None), after


@pytest.mark.parametrize("limit", [0, 101])
def test_the_inbox_limit_is_one_to_a_hundred(coral_db_uri: str, limit: int) -> None:
    _, alerts = _sql(coral_db_uri)

    with pytest.raises(ValueError, match="limit"):
        alerts.list_inbox(workspace_id=WORKSPACE, viewer=Viewer(ALICE), after=None, limit=limit)


def test_the_inbox_reads_each_priority_as_one_index_range(coral_db_uri: str) -> None:
    engine = coral_engine(coral_db_uri)
    runs, alerts = run_store_module.SqlAlchemyCoralRunStore(engine), SqlAlchemyAlertStore(engine)
    run = start_owned_run(runs, "plan")
    commit_alert_changes(
        runs,
        run,
        raises=(
            alert_draft(run, AlertKind.PAUSE, "normal"),
            alert_draft(run, AlertKind.RUN_COMPLETED, "low", priority=AlertPriority.LOW),
        ),
    )
    queries: list[tuple[str, Any]] = []

    def capture(*args: Any) -> None:
        statement, parameters = args[2], args[3]
        if statement.lstrip().upper().startswith("SELECT") and "coral_alerts" in statement:
            queries.append((statement, parameters))

    event.listen(engine, "before_cursor_execute", capture)
    try:
        _inbox(alerts, Viewer(ALICE), limit=10)
        _inbox(alerts, Viewer(ALICE), after=(int(AlertPriority.NORMAL), NOW + 1, "f" * 32))
    finally:
        event.remove(engine, "before_cursor_execute", capture)

    # One query per priority, each bounded.
    assert len(queries) == 4
    assert all("LIMIT" in statement for statement, _ in queries)
    if engine.dialect.name != "sqlite":
        return
    with engine.connect() as connection:
        for statement, parameters in queries:
            plan = str(
                connection.exec_driver_sql("EXPLAIN QUERY PLAN " + statement, parameters).all()
            )
            assert "ix_coral_alerts_inbox" in plan
            assert "TEMP B-TREE" not in plan


# ── Ack ──────────────────────────────────────────────────────────────────────


def test_ack_marks_an_owners_open_alert_read_once(coral_db_uri: str) -> None:
    runs, alerts = _sql(coral_db_uri)
    run = start_owned_run(runs, "ack")
    pause = alert_draft(run, AlertKind.PAUSE, "2")
    gate = alert_draft(run, AlertKind.GATE, "visit")
    question = alert_draft(run, AlertKind.QUESTION, "question")
    done = alert_draft(run, AlertKind.RUN_COMPLETED, "run_completed", priority=AlertPriority.LOW)
    commit_alert_changes(runs, run, raises=(pause, gate, question, done))

    def ack(viewer: Viewer, alert_id: str, *, workspace_id: int = WORKSPACE) -> str:
        return alerts.ack(workspace_id=workspace_id, viewer=viewer, alert_id=alert_id, now=NOW + 5)

    def record(alert_id: str) -> AlertRecord:
        rows = alerts.list_for_run(workspace_id=WORKSPACE, run_id=run.id)
        return next(row for row in rows if row.id == alert_id)

    # Another user, another workspace and an unknown id all read as absent.
    assert ack(Viewer(BOB), pause.id) == "not_found"
    assert ack(Viewer(ALICE), pause.id, workspace_id=OTHER_WORKSPACE) == "not_found"
    assert ack(Viewer(ALICE), "0" * 32) == "not_found"
    assert ack(Viewer(BOB), gate.id) == "not_found"
    for lookalike in ("ALICE", "alice ", "alicé"):
        assert ack(Viewer(lookalike), pause.id) == "not_found"
    assert record(pause.id).status == OPEN

    assert ack(Viewer(ALICE), pause.id) == "acked"
    assert (record(pause.id).status, record(pause.id).acked_at, record(pause.id).acked_by) == (
        ACKED,
        NOW + 5,
        ALICE,
    )
    assert ack(Viewer(ALICE), pause.id) == "unchanged"

    # Gates and questions clear only when they are answered.
    assert ack(Viewer(ALICE), gate.id) == "not_ackable"
    assert ack(Viewer(ALICE), question.id) == "not_ackable"
    assert record(gate.id).status == OPEN
    assert _inbox(alerts, Viewer(ALICE)) == ([*_newest_first((gate, question)), done.id], None)

    commit_alert_changes(runs, run, resolutions=(AlertResolution(subject_id=gate.subject_id),))
    assert ack(Viewer(ALICE), gate.id) == "unchanged"
    assert ack(Viewer(ALICE), done.id) == "acked"
    assert _inbox(alerts, Viewer(ALICE)) == ([question.id], None)


def test_ack_of_another_generations_alert_is_not_found_and_changes_nothing(
    coral_db_uri: str,
) -> None:
    runs, alerts = _sql(coral_db_uri)
    run = start_owned_run(runs, "ack-generation", generation="g1")
    plain_run = start_owned_run(runs, "ack-plain")
    local_run = start_owned_run(runs, "ack-local", user_id=None)
    named_local_run = start_owned_run(runs, "ack-local-named", user_id=LOCAL_USER_ID)
    pause = alert_draft(run, AlertKind.PAUSE, "2")
    plain_pause = alert_draft(plain_run, AlertKind.PAUSE, "2")
    local_pause = alert_draft(local_run, AlertKind.PAUSE, "2")
    named_local_pause = alert_draft(named_local_run, AlertKind.PAUSE, "2")
    commit_alert_changes(runs, run, raises=(pause,))
    commit_alert_changes(runs, plain_run, raises=(plain_pause,))
    commit_alert_changes(runs, local_run, raises=(local_pause,))
    commit_alert_changes(runs, named_local_run, raises=(named_local_pause,))

    def ack(viewer: Viewer, alert_id: str) -> str:
        return alerts.ack(workspace_id=WORKSPACE, viewer=viewer, alert_id=alert_id, now=NOW + 5)

    assert ack(Viewer(ALICE, "g2", check_generation=True), pause.id) == "not_found"
    assert ack(Viewer(ALICE, "g1", check_generation=False), pause.id) == "not_found"
    [unchanged] = alerts.list_for_run(workspace_id=WORKSPACE, run_id=run.id)
    assert (unchanged.status, unchanged.acked_at, unchanged.acked_by) == (OPEN, None, None)
    assert ack(Viewer(ALICE, "g1", check_generation=True), pause.id) == "acked"
    # A proven generation still acks an alert recorded without one.
    assert ack(Viewer(ALICE, "g2", check_generation=True), plain_pause.id) == "acked"

    assert ack(Viewer(ALICE), local_pause.id) == "not_found"
    assert ack(Viewer(None), local_pause.id) == "acked"
    [local_acked] = alerts.list_for_run(workspace_id=WORKSPACE, run_id=local_run.id)
    assert (local_acked.status, local_acked.acked_by) == (ACKED, LOCAL_USER_ID)
    # A run that names the local user "local" is the same user's.
    assert ack(Viewer(LOCAL_USER_ID), named_local_pause.id) == "acked"
    [named_acked] = alerts.list_for_run(workspace_id=WORKSPACE, run_id=named_local_run.id)
    assert (named_acked.owner_user_id, named_acked.acked_by) == (None, LOCAL_USER_ID)


def test_racing_acks_of_one_alert_ack_it_once(coral_db_uri: str) -> None:
    runs, alerts = _sql(coral_db_uri)
    run = start_owned_run(runs, "ack-race")
    pause = alert_draft(run, AlertKind.PAUSE, "2")
    commit_alert_changes(runs, run, raises=(pause,))

    outcomes = run_racing(
        4,
        lambda index: alerts.ack(
            workspace_id=WORKSPACE, viewer=Viewer(ALICE), alert_id=pause.id, now=NOW + index
        ),
    )

    assert [outcome.error for outcome in outcomes] == [None] * 4
    values = [outcome.value for outcome in outcomes]
    assert sorted(map(str, values)) == ["acked", "unchanged", "unchanged", "unchanged"]
    [acked] = alerts.list_for_run(workspace_id=WORKSPACE, run_id=run.id)
    assert (acked.status, acked.acked_at) == (ACKED, NOW + values.index("acked"))


def test_an_ack_that_loses_to_a_resolve_after_its_read_is_unchanged(coral_db_uri: str) -> None:
    engine = coral_engine(coral_db_uri)
    runs, alerts = run_store_module.SqlAlchemyCoralRunStore(engine), SqlAlchemyAlertStore(engine)
    run = start_owned_run(runs, "ack-loses")
    pause = alert_draft(run, AlertKind.PAUSE, "2")
    commit_alert_changes(runs, run, raises=(pause,))
    resolved: list[bool] = []

    def resolve_before_the_ack_update(connection: Any, *args: Any) -> None:
        statement = args[1]
        if resolved or not statement.lstrip().upper().startswith("UPDATE CORAL_ALERTS"):
            return
        resolved.append(True)
        connection.execute(
            update(AlertRow)
            .where(AlertRow.workspace_id == WORKSPACE, AlertRow.id == pause.id)
            .values(status=RESOLVED, resolved_at=NOW + 1)
        )

    event.listen(engine, "before_cursor_execute", resolve_before_the_ack_update)
    try:
        outcome = alerts.ack(
            workspace_id=WORKSPACE, viewer=Viewer(ALICE), alert_id=pause.id, now=NOW + 2
        )
    finally:
        event.remove(engine, "before_cursor_execute", resolve_before_the_ack_update)

    assert (outcome, resolved) == ("unchanged", [True])
    [row] = alerts.list_for_run(workspace_id=WORKSPACE, run_id=run.id)
    assert (row.status, row.resolved_at, row.acked_at, row.acked_by) == (
        RESOLVED,
        NOW + 1,
        None,
        None,
    )


def test_alert_statements_run_under_their_query_names(coral_db_uri: str) -> None:
    engine = coral_engine(coral_db_uri)
    runs, alerts = run_store_module.SqlAlchemyCoralRunStore(engine), SqlAlchemyAlertStore(engine)
    run = start_owned_run(runs, "names")
    pause = alert_draft(run, AlertKind.PAUSE, "2")
    names: list[str | None] = []

    def capture(*args: Any) -> None:
        if "coral_alerts" in args[2]:
            names.append(current_query_name())

    event.listen(engine, "before_cursor_execute", capture)
    try:
        commit_alert_changes(
            runs,
            run,
            raises=(pause,),
            resolutions=(
                AlertResolution(subject_id="5" * 32),
                AlertResolution(kinds=(int(AlertKind.GATE),)),
            ),
        )
        _inbox(alerts, Viewer(ALICE))
        alerts.ack(workspace_id=WORKSPACE, viewer=Viewer(ALICE), alert_id=pause.id, now=NOW)
        alerts.list_for_run(workspace_id=WORKSPACE, run_id=run.id)
    finally:
        event.remove(engine, "before_cursor_execute", capture)

    # The alert writes inside a run commit carry their own nested names.
    assert list(dict.fromkeys(names)) == [
        "coral.alerts.raise",
        "coral.alerts.resolve_subject",
        "coral.alerts.resolve_kinds",
        "coral.alerts.list_inbox",
        "coral.alerts.ack",
        "coral.alerts.list_for_run",
    ]
