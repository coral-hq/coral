"""The policy provider's binding cache keeps found rows only, so a new binding is never hidden."""

from __future__ import annotations

from contextlib import AsyncExitStack
from typing import Any

import pytest

from coral.omni.policies.bindings_cache import CachedBindingLookup
from coral.omni.server.tool_bridge import register_engine_tools
from coral.stores.session_bindings import FreshBindingLookup, SessionBindingLookup
from coral.tools.catalog import ENGINE_TOOLS
from tests.coral.tools.fake_decision_port import WORKSPACE, FakeBindingLookup, step_binding


def test_a_found_row_is_read_once_and_a_miss_is_read_every_time() -> None:
    lookup = FakeBindingLookup()
    cache = CachedBindingLookup(lookup)
    binding = step_binding("work||:0", session_id="bound")
    lookup.add(binding)

    assert cache.find_by_session(WORKSPACE, "bound") == binding
    assert cache.find_by_session(WORKSPACE, "bound") == binding
    assert cache.find_by_session(WORKSPACE, "unbound") is None
    assert cache.find_by_session(WORKSPACE, "unbound") is None
    assert lookup.reads == [(WORKSPACE, "bound"), (WORKSPACE, "unbound"), (WORKSPACE, "unbound")]

    # A binding reserved after a miss is found on the next read.
    later = step_binding("work||:0", session_id="unbound")
    lookup.add(later)
    assert cache.find_by_session(WORKSPACE, "unbound") == later
    # The same session id in another workspace is another key.
    assert cache.find_by_session(WORKSPACE + 1, "bound") is None
    assert lookup.reads[-2:] == [(WORKSPACE, "unbound"), (WORKSPACE + 1, "bound")]


def test_a_lookup_error_is_raised_and_nothing_is_kept() -> None:
    lookup = FakeBindingLookup(error=RuntimeError("database is locked"))
    cache = CachedBindingLookup(lookup)
    lookup.add(step_binding("work||:0", session_id="bound"))

    with pytest.raises(RuntimeError, match="database is locked"):
        cache.find_by_session(WORKSPACE, "bound")
    lookup.error = None
    assert cache.find_by_session(WORKSPACE, "bound") is not None
    assert len(lookup.reads) == 2


def test_the_least_recently_read_row_is_evicted() -> None:
    lookup = FakeBindingLookup()
    for session_id in ("a", "b", "c"):
        lookup.add(step_binding("work||:0", session_id=session_id))
    cache = CachedBindingLookup(lookup, max_entries=2)

    for session_id in ("a", "b", "a", "c"):
        cache.find_by_session(WORKSPACE, session_id)
    lookup.reads.clear()
    # "b" was read least recently when "c" arrived.
    for session_id in ("a", "c", "b"):
        cache.find_by_session(WORKSPACE, session_id)
    assert lookup.reads == [(WORKSPACE, "b")]

    with pytest.raises(ValueError, match="max_entries"):
        CachedBindingLookup(lookup, max_entries=0)


async def test_the_cache_is_a_lookup_the_engine_tool_bridge_refuses() -> None:
    cache = CachedBindingLookup(FakeBindingLookup())

    assert isinstance(cache, SessionBindingLookup)
    # It keeps found rows, so it must never pass for a lookup that reads fresh.
    assert not isinstance(cache, FreshBindingLookup)
    refused: Any = cache
    async with AsyncExitStack() as stack:
        with pytest.raises(TypeError, match="reads_fresh"):
            register_engine_tools(catalog=ENGINE_TOOLS, port=None, bindings=refused, stack=stack)
