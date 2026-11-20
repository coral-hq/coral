"""Per-process limits: slots held at once, in all and per key, and warnings given once."""

from __future__ import annotations

import asyncio
import logging
import threading
from collections.abc import Hashable
from typing import Any, Generic, TypeVar

_K = TypeVar("_K", bound=Hashable)


class Slot:
    """One slot held; :meth:`release` frees it once, however often it is called."""

    def __init__(self, owner: Slots[Any], key: Hashable) -> None:
        self._owner = owner
        self._key = key
        self._held = True

    @property
    def released(self) -> bool:
        return not self._held

    def release(self) -> None:
        if self._held:
            self._held = False
            self._owner.free(self._key)

    def release_when_done(self, task: asyncio.Future[Any]) -> None:
        """
        Hold the slot until ``task`` ends, even when nothing waits for it any more.

        The task is kept referenced until then, and its error is marked retrieved.
        """
        self._owner.running.add(task)
        task.add_done_callback(self._ended)

    def _ended(self, task: asyncio.Future[Any]) -> None:
        self._owner.running.discard(task)
        self.release()
        if not task.cancelled():
            task.exception()

    def __enter__(self) -> Slot:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.release()


class Slots(Generic[_K]):
    """
    Slots held at once: at most ``per_key`` for one key and, when given, ``total`` in all.

    Use it on one thread, such as one event loop.
    """

    def __init__(self, *, per_key: int, total: int | None = None) -> None:
        self._per_key = per_key
        self._total = total
        self._held = 0
        self._by_key: dict[_K, int] = {}
        # Tasks slots are held for, kept until they end.
        self.running: set[asyncio.Future[Any]] = set()

    @property
    def held(self) -> int:
        return self._held

    def held_by(self, key: _K) -> int:
        return self._by_key.get(key, 0)

    def full(self, key: _K) -> bool:
        """Whether ``key`` holds its share, or every slot is held."""
        return self.held_by(key) >= self._per_key or (
            self._total is not None and self._held >= self._total
        )

    def acquire(self, key: _K) -> Slot | None:
        """A slot of ``key``'s, or ``None`` when :meth:`full`."""
        return None if self.full(key) else self.take(key)

    def take(self, key: _K) -> Slot:
        """A slot of ``key``'s even past the caps; it counts against them all the same."""
        self._by_key[key] = self.held_by(key) + 1
        self._held += 1
        return Slot(self, key)

    def free(self, key: _K) -> None:
        """Free one slot of ``key``'s; :meth:`Slot.release` calls it once."""
        self._held -= 1
        remaining = self._by_key[key] - 1
        if remaining:
            self._by_key[key] = remaining
        else:
            del self._by_key[key]


class WarnOnce:
    """A warning given once per process; later ones are logged at debug. Thread-safe."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._warned = False

    def first(self) -> bool:
        """Whether this is the first time it is asked."""
        with self._lock:
            first, self._warned = not self._warned, True
        return first

    def level(self) -> int:
        """``WARNING`` the first time, ``DEBUG`` after."""
        return logging.WARNING if self.first() else logging.DEBUG


__all__ = ["Slot", "Slots", "WarnOnce"]
