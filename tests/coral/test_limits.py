"""The shared per-process limits: slots per key and in all, and warnings given once."""

from __future__ import annotations

import asyncio
import logging

import pytest

from coral.limits import Slots, WarnOnce


def test_a_key_past_its_share_or_any_key_past_the_total_gets_no_slot() -> None:
    slots = Slots[str](per_key=2, total=3)

    alice = [slots.acquire("alice"), slots.acquire("alice")]
    alice_third = slots.acquire("alice")
    bob = slots.acquire("bob")
    carol = slots.acquire("carol")

    assert all(slot is not None for slot in alice) and bob is not None
    assert (alice_third, carol) == (None, None)
    assert (slots.held, slots.held_by("alice"), slots.held_by("bob")) == (3, 2, 1)
    assert slots.full("carol") and slots.full("alice")


def test_a_key_s_slots_released_in_the_order_taken_free_its_whole_share() -> None:
    slots = Slots[str](per_key=2, total=4)
    first, second = slots.acquire("alice"), slots.acquire("alice")
    assert first is not None and second is not None

    first.release()
    second.release()
    again = [slots.acquire("alice"), slots.acquire("alice")]

    assert all(slot is not None for slot in again)
    assert (slots.held, slots.held_by("alice")) == (2, 2)


def test_a_slot_released_twice_frees_one_slot() -> None:
    slots = Slots[str](per_key=2)
    kept, released = slots.take("alice"), slots.take("alice")

    released.release()
    released.release()

    assert (released.released, kept.released) == (True, False)
    assert slots.held_by("alice") == 1


def test_a_slot_taken_past_the_caps_counts_against_them() -> None:
    slots = Slots[str](per_key=1)
    slots.take("alice")

    over = slots.take("alice")

    assert slots.held_by("alice") == 2 and slots.acquire("alice") is None
    over.release()
    assert slots.held_by("alice") == 1


def test_a_slot_used_as_a_context_is_released_however_the_block_ends() -> None:
    slots = Slots[str](per_key=1)

    with pytest.raises(RuntimeError), slots.take("alice"):
        raise RuntimeError("boom")

    assert slots.held == 0


async def test_a_slot_held_for_a_task_is_freed_when_the_task_ends_not_its_waiter() -> None:
    slots = Slots[str](per_key=1)
    finish = asyncio.Event()

    async def work() -> None:
        await finish.wait()
        raise ValueError("nobody reads this")

    task = asyncio.create_task(work())
    slots.take("alice").release_when_done(task)
    # The waiter gives up; the task runs on, holding its slot.
    waiter = asyncio.shield(task)
    waiter.cancel()
    held_after_waiter = slots.held

    finish.set()
    # The slot's callback runs before the gather's, which was added after it.
    await asyncio.gather(task, return_exceptions=True)

    assert held_after_waiter == 1
    assert (slots.held, slots.running) == (0, set())


def test_a_warning_is_given_once_then_logged_at_debug() -> None:
    warned = WarnOnce()

    levels = [warned.level() for _ in range(3)]

    assert levels == [logging.WARNING, logging.DEBUG, logging.DEBUG]
    assert not warned.first()
    assert WarnOnce().first()
