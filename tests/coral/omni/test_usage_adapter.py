"""A run's spend: one read of its anchor's session tree, through Omnigent's usage sums."""

from __future__ import annotations

from typing import Any

import pytest

from coral.model.ids import anchor_session_id
from coral.omni.protocols import RunSpendTotals
from coral.omni.server.usage import OmnigentRunSpend
from omnigent.db.db_models import workspace_scope
from omnigent.entities import Conversation
from omnigent.stores.conversation_store.sqlalchemy_store import SqlAlchemyConversationStore

WORKSPACE = 7
OTHER_WORKSPACE = 8
RUN_ID = "a" * 32
OTHER_RUN_ID = "b" * 32


@pytest.fixture
def conversations(db_uri: str) -> SqlAlchemyConversationStore:
    return SqlAlchemyConversationStore(db_uri)


def _anchor(
    conversations: SqlAlchemyConversationStore,
    *,
    run_id: str = RUN_ID,
    workspace_id: int = WORKSPACE,
    usage: dict[str, Any] | None = None,
) -> Conversation:
    """The run's anchor session, as the session facade creates it."""
    with workspace_scope(workspace_id):
        anchor = conversations.create_conversation(
            title="Run", conversation_id=anchor_session_id(workspace_id, run_id)
        )
        if usage is not None:
            conversations.set_session_usage(anchor.id, usage)
    return anchor


def _child(
    conversations: SqlAlchemyConversationStore,
    parent: Conversation,
    title: str,
    usage: dict[str, Any],
    *,
    workspace_id: int = WORKSPACE,
    archived: bool = False,
) -> Conversation:
    """A step session under ``parent``, or a harness sub-agent under a step."""
    with workspace_scope(workspace_id):
        child = conversations.create_conversation(
            kind="sub_agent", parent_conversation_id=parent.id, title=title
        )
        conversations.set_session_usage(child.id, usage)
        if archived:
            conversations.update_conversation(child.id, archived=True)
    return child


def _usage(
    input_tokens: int,
    output_tokens: int,
    *,
    cost: float | None = None,
    policy_cost: float | None = None,
    model: str = "model-a",
    cache_read: int = 0,
    cache_creation: int = 0,
) -> dict[str, Any]:
    """A session's stored usage, with a per-model bucket priced only when ``cost`` is given."""
    tokens = {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": input_tokens + output_tokens,
        "cache_read_input_tokens": cache_read,
        "cache_creation_input_tokens": cache_creation,
    }
    bucket: dict[str, Any] = dict(tokens)
    usage: dict[str, Any] = dict(tokens)
    if cost is not None:
        bucket["total_cost_usd"] = cost
        usage["total_cost_usd"] = cost
    if policy_cost is not None:
        usage["policy_cost_usd"] = policy_cost
    usage["by_model"] = {model: bucket}
    return usage


def _spend(
    conversations: SqlAlchemyConversationStore,
    *,
    run_id: str = RUN_ID,
    workspace_id: int = WORKSPACE,
) -> RunSpendTotals | None:
    return OmnigentRunSpend(conversations).run_spend(workspace_id=workspace_id, run_id=run_id)


def test_a_runs_spend_sums_its_anchor_steps_sub_agents_and_archived_steps(
    conversations: SqlAlchemyConversationStore,
) -> None:
    anchor = _anchor(conversations)
    step = _child(
        conversations, anchor, "step-1", _usage(100, 10, cost=0.5, cache_read=7, cache_creation=3)
    )
    _child(conversations, step, "sub-agent", _usage(20, 2, cost=0.25))
    _child(conversations, anchor, "step-2", _usage(5, 1, cost=0.125), archived=True)
    # Another run's tree, and this run id in another workspace, are not this run's spend.
    _child(conversations, _anchor(conversations, run_id=OTHER_RUN_ID), "other", _usage(9, 9))
    elsewhere = _anchor(conversations, workspace_id=OTHER_WORKSPACE)
    _child(conversations, elsewhere, "elsewhere", _usage(9, 9), workspace_id=OTHER_WORKSPACE)

    assert _spend(conversations) == RunSpendTotals(
        usd=0.875,
        live_usd=0.875,
        input_tokens=125,
        output_tokens=13,
        total_tokens=138,
        cache_read_tokens=7,
        cache_creation_tokens=3,
        unpriced_models=(),
        sessions=4,
    )


def test_unpriced_models_show_their_tokens_with_no_cost(
    conversations: SqlAlchemyConversationStore,
) -> None:
    anchor = _anchor(conversations)
    _child(conversations, anchor, "step-1", _usage(40, 4, model="model-z"))
    _child(conversations, anchor, "step-2", _usage(60, 6, model="model-m"))

    spend = _spend(conversations)

    assert spend is not None
    assert (spend.usd, spend.live_usd) == (None, None)
    assert (spend.input_tokens, spend.output_tokens, spend.total_tokens) == (100, 10, 110)
    assert spend.unpriced_models == ("model-m", "model-z")
    assert spend.sessions == 3


def test_mixed_pricing_counts_only_the_priced_cost_and_names_the_unpriced_model(
    conversations: SqlAlchemyConversationStore,
) -> None:
    anchor = _anchor(conversations)
    _child(conversations, anchor, "priced", _usage(10, 1, cost=0.75, model="model-a"))
    _child(conversations, anchor, "unpriced", _usage(30, 3, model="model-b"))

    spend = _spend(conversations)

    assert spend is not None
    assert (spend.usd, spend.live_usd) == (0.75, 0.75)
    assert spend.total_tokens == 44
    assert spend.unpriced_models == ("model-b",)


def test_live_spend_includes_in_flight_cost_the_display_figure_leaves_out(
    conversations: SqlAlchemyConversationStore,
) -> None:
    anchor = _anchor(conversations, usage=_usage(1, 1, cost=0.5, policy_cost=1.5))
    # A step that posts only the display cost counts toward both figures.
    _child(conversations, anchor, "step", _usage(1, 1, cost=0.25))

    spend = _spend(conversations)

    assert spend is not None
    assert (spend.usd, spend.live_usd) == (0.75, 1.75)


def test_a_run_without_an_anchor_has_unknown_spend(
    conversations: SqlAlchemyConversationStore,
) -> None:
    _anchor(conversations, run_id=OTHER_RUN_ID)

    assert _spend(conversations) is None
