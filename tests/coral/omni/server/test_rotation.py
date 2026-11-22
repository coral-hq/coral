"""Tests for the Coral supersession follower."""

from __future__ import annotations

from coral.omni.server.rotation import SupersessionFollower


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
