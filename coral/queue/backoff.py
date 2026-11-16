"""Jittered exponential backoff calculation for transient effect retries."""

from __future__ import annotations

import random
from collections.abc import Callable


def compute_effect_backoff(
    attempt: int,
    *,
    base_s: float = 1.0,
    max_s: float = 300.0,
    max_attempts: int = 8,
    rng: Callable[[], float] | None = None,
) -> int | None:
    """Compute jittered exponential backoff in seconds for the given attempt.

    Returns ``None`` when ``attempt >= max_attempts`` to signal terminal
    retry exhaustion (``infra.transient``).
    """
    if attempt >= max_attempts:
        return None
    effective_attempt = max(1, attempt)
    raw = min(max_s, base_s * (2 ** (effective_attempt - 1)))
    if rng is not None:
        u = max(0.0, min(1.0, float(rng())))
        jitter = 0.5 + u
    else:
        jitter = random.uniform(0.5, 1.5)
    delay = round(raw * jitter)
    return max(1, min(int(max_s), delay))


__all__ = ["compute_effect_backoff"]
