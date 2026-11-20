"""A run's spend, read from its anchor's session tree with Omnigent's usage sums."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from coral.model.ids import anchor_session_id
from coral.omni.protocols import RunSpendTotals
from omnigent.db.db_models import workspace_scope
from omnigent.runtime.policies.builder import load_session_usage_and_tree
from omnigent.stores.conversation_store import ConversationStore


def _tokens(usage: Mapping[str, Any], key: str) -> int:
    # Summed as floats across sessions.
    return int(usage.get(key) or 0)


def _unpriced_models(usage: Mapping[str, Any]) -> tuple[str, ...]:
    by_model = usage.get("by_model")
    if not isinstance(by_model, Mapping):
        return ()
    return tuple(
        sorted(
            model
            for model, bucket in by_model.items()
            if isinstance(bucket, Mapping) and bucket.get("total_cost_usd") is None
        )
    )


class OmnigentRunSpend:
    """Reads a run's spend: one tree read from its anchor, which every step session is under."""

    def __init__(self, conversation_store: ConversationStore) -> None:
        self._conversation_store = conversation_store

    def run_spend(self, *, workspace_id: int, run_id: str) -> RunSpendTotals | None:
        """The run's spend, or ``None`` when its anchor is missing; blocking.

        Archived sessions count. Callers check the run's owner first: conversation
        reads are not scoped to an account.
        """
        anchor = anchor_session_id(workspace_id, run_id)
        with workspace_scope(workspace_id):
            usage, tree = load_session_usage_and_tree(
                anchor, self._conversation_store, root_conversation_id=anchor
            )
        if not tree:
            return None
        usd = usage.get("total_cost_usd")
        live_usd = usage.get("policy_cost_usd", usd)
        return RunSpendTotals(
            usd=usd,
            live_usd=live_usd,
            input_tokens=_tokens(usage, "input_tokens"),
            output_tokens=_tokens(usage, "output_tokens"),
            total_tokens=_tokens(usage, "total_tokens"),
            cache_read_tokens=_tokens(usage, "cache_read_input_tokens"),
            cache_creation_tokens=_tokens(usage, "cache_creation_input_tokens"),
            unpriced_models=_unpriced_models(usage),
            sessions=len(tree),
        )


__all__ = ["OmnigentRunSpend"]
