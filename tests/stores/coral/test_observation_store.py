"""Command observation store on every DB lane: idempotent records, one session's rows in order."""

from __future__ import annotations

from coral.evidence.fakes import InMemoryObservationLog
from coral.evidence.ir import CommandObservation
from coral.stores.observations import ObservationStore, SqlAlchemyObservationStore

WORKSPACE = 7
RUN = "a" * 32
SESSION = "conv_" + "b" * 27


def _shell(op_key: str, seq: int, **fields: object) -> CommandObservation:
    values: dict[str, object] = {"exit_code": 0, "l1_after": "c" * 64, **fields}
    return CommandObservation.model_validate(
        {
            "session_id": SESSION,
            "op_key": op_key,
            "obs_seq": seq,
            "tool": "shell",
            "command": "pytest -q || true",
            **values,
        }
    )


def test_records_round_trip_in_order_and_ignore_a_repeated_key(coral_db_uri: str) -> None:
    store = SqlAlchemyObservationStore(coral_db_uri)
    assert isinstance(store, ObservationStore)
    later = _shell("op-2", 20, exit_code=None, timed_out=True, l1_after=None)
    edit = CommandObservation(
        session_id=SESSION, op_key="op-1", obs_seq=10, tool="edit", changed_path="src/ü.py"
    )
    assert store.record(WORKSPACE, RUN, later) is True
    assert store.record(WORKSPACE, RUN, edit) is True
    assert store.record(WORKSPACE, RUN, later.model_copy(update={"exit_code": 3})) is False
    assert list(store.list_for_session(WORKSPACE, SESSION)) == [edit, later]


def test_rows_are_scoped_to_their_workspace_and_session(coral_db_uri: str) -> None:
    store = SqlAlchemyObservationStore(coral_db_uri)
    store.record(WORKSPACE, RUN, _shell("op-1", 1))
    store.record(WORKSPACE + 1, RUN, _shell("op-1", 1))
    assert len(store.list_for_session(WORKSPACE, SESSION)) == 1
    assert store.list_for_session(WORKSPACE, "conv_other") == []


def test_op_keys_are_case_sensitive(coral_db_uri: str) -> None:
    store = SqlAlchemyObservationStore(coral_db_uri)
    assert store.record(WORKSPACE, RUN, _shell("Op", 1))
    assert store.record(WORKSPACE, RUN, _shell("op", 2))
    assert [obs.op_key for obs in store.list_for_session(WORKSPACE, SESSION)] == ["Op", "op"]


def test_the_fake_matches_the_store() -> None:
    fake = InMemoryObservationLog()
    assert isinstance(fake, ObservationStore)
    assert fake.record(WORKSPACE, RUN, _shell("op-2", 2))
    assert fake.record(WORKSPACE, RUN, _shell("op-1", 1))
    assert not fake.record(WORKSPACE, RUN, _shell("op-1", 3))
    assert [obs.op_key for obs in fake.list_for_session(WORKSPACE, SESSION)] == ["op-1", "op-2"]
