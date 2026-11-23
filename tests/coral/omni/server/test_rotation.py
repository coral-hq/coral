"""Tests for the Coral supersession follower and binding rebind."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from sqlalchemy import create_engine

from coral.bridge.bound_sessions import BoundSession, BoundSessions
from coral.db import CoralBase
from coral.db.enum_codecs import SessionBindingProgress, SessionBindingRole, SlotRole
from coral.omni.server.rotation import SupersessionFollower, follow_bound_supersession
from coral.stores.session_bindings import SessionBindingDraft, SqlAlchemySessionBindingStore

WORKSPACE = 7
RUN = "a" * 32
OLD = "d" * 32
NEW = "e" * 32


def test_follower_enqueues_only_bound_sessions() -> None:
    queued: list[tuple[str, str, str]] = []
    follower = SupersessionFollower(
        bound_session_ids=lambda: {"conv_old"},
        enqueue=lambda old, new, reason: queued.append((old, new, reason)),
    )
    follower.observe("conv_other", "conv_new", "clear")
    assert queued == []
    follower.observe("conv_old", "conv_new", "clear")
    assert queued == [("conv_old", "conv_new", "clear")]
    follower.observe("conv_old", "conv_new", "clear")  # idempotent
    assert queued == [("conv_old", "conv_new", "clear")]


def test_follow_bound_supersession_transfers_and_rekeys(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'coral.db'}")
    CoralBase.metadata.create_all(engine)
    bindings = SqlAlchemySessionBindingStore(engine)
    bindings.reserve(
        SessionBindingDraft(
            workspace_id=WORKSPACE,
            session_id=OLD,
            run_id=RUN,
            role=SessionBindingRole.STEP,
            effect_key="effect:create:a",
            slot_id="implement",
            slot_role=SlotRole.STEP_AGENT,
            session_generation=1,
            progress=SessionBindingProgress.INITIALIZED,
        )
    )
    bound = BoundSessions()
    bound.push(WORKSPACE, OLD, BoundSession.of(RUN, "implement", 1))

    results = follow_bound_supersession(old_id=OLD, new_id=NEW, bound=bound, bindings=bindings)
    assert len(results) == 1
    assert results[0].binding.session_id == NEW
    assert bound.lookup(WORKSPACE, OLD) is None
    assert bound.lookup(WORKSPACE, NEW) is not None
    assert bindings.get(WORKSPACE, NEW, run_id=RUN) is not None
    engine.dispose()


class _Labels:
    def __init__(self) -> None:
        self.labels: dict[str, dict[str, str]] = {OLD: {"coral.run_id": RUN, "team": "x"}}

    def get_conversation(self, conversation_id: str) -> object:
        return SimpleNamespace(labels=self.labels.get(conversation_id, {}))

    def set_labels(self, conversation_id: str, updates: dict[str, str]) -> None:
        self.labels.setdefault(conversation_id, {}).update(updates)


def test_a_superseding_session_carries_the_coral_labels(tmp_path: Path) -> None:
    """The server's fences know a session is Coral's by its ``coral.`` labels."""
    engine = create_engine(f"sqlite:///{tmp_path / 'coral.db'}")
    CoralBase.metadata.create_all(engine)
    bindings = SqlAlchemySessionBindingStore(engine)
    bindings.reserve(
        SessionBindingDraft(
            workspace_id=WORKSPACE,
            session_id=OLD,
            run_id=RUN,
            role=SessionBindingRole.STEP,
            effect_key="effect:create:a",
            slot_id="implement",
            slot_role=SlotRole.STEP_AGENT,
            session_generation=1,
            progress=SessionBindingProgress.INITIALIZED,
        )
    )
    bound = BoundSessions()
    bound.push(WORKSPACE, OLD, BoundSession.of(RUN, "implement", 1))
    conversations = _Labels()

    follow_bound_supersession(
        old_id=OLD, new_id=NEW, bound=bound, bindings=bindings, conversations=conversations
    )

    assert conversations.labels[NEW] == {"coral.run_id": RUN}
    engine.dispose()
