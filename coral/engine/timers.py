"""Arm and disarm workflow timers. Due times come from ``now``; nothing sleeps."""

from __future__ import annotations

from collections.abc import Collection
from datetime import datetime, timedelta

from coral.engine.types import RunState, Timer, TimerPolicy

WATCHDOG_REMIND = "watchdog_remind"
WATCHDOG_ALERT = "watchdog_alert"
INFRA_BACKOFF = "infra_backoff"
PLAN_PROBE = "plan_probe"
WATCHDOG_KINDS = frozenset({WATCHDOG_REMIND, WATCHDOG_ALERT})


def find_timer(state: RunState, key: str) -> Timer | None:
    """The armed timer with ``key``, if it has not been disarmed."""
    for timer in state.timers:
        if timer.key == key:
            return timer
    return None


def has_live_timer(state: RunState, kind: str, subject: str, now: datetime) -> bool:
    """True when ``subject`` has a ``kind`` timer armed that is not due yet at ``now``."""
    return any(
        timer.kind == kind and timer.subject == subject and timer.due_at > now
        for timer in state.timers
    )


def drop_slot_backoff(
    state: RunState,
    slot_ids: Collection[str],
    kinds: Collection[str] = (INFRA_BACKOFF, PLAN_PROBE),
) -> RunState:
    """Drop the ``kinds`` timers (infra backoff and plan probe by default) of ``slot_ids``."""
    kept = tuple(
        timer for timer in state.timers if timer.kind not in kinds or timer.subject not in slot_ids
    )
    if kept == state.timers:
        return state
    return state.model_copy(update={"timers": kept})


def sync_watchdogs(
    before: RunState, after: RunState, now: datetime, policy: TimerPolicy
) -> RunState:
    """Arm watchdogs for decisions and gates this transition opened.

    A later pass drops the previous subject's reminder and alert, then arms the new one.
    Resolving a visit or deciding a label disarms that subject. No arm effects are emitted.
    """
    timers = list(after.timers)
    drop = _subjects_to_disarm(before, after)
    if drop:
        timers = [
            timer
            for timer in timers
            if timer.kind not in WATCHDOG_KINDS or timer.subject not in drop
        ]
    for subject, generation in _subjects_to_arm(before, after):
        timers = _replace_watchdog(timers, subject, generation, now, policy)
    updated = tuple(timers)
    if updated == after.timers:
        return after
    return after.model_copy(update={"timers": updated})


def timer_key(kind: str, subject: str, stage: int) -> str:
    """``{kind}:{subject}:{stage}``. The subject may itself contain colons."""
    return f"{kind}:{subject}:{stage}"


def probe_delay(policy: TimerPolicy, stage: int) -> timedelta:
    """Delay for a 1-based probe stage.

    Stage 1 is ``plan_probe_start``. Each later stage is ``min(previous * 2, plan_probe_cap)``.
    The arm time is not stored on the row, so the ladder is recovered from ``stage``.
    """
    delay = policy.plan_probe_start
    for _ in range(max(stage, 1) - 1):
        delay = min(delay * 2, policy.plan_probe_cap)
    return delay


def infra_backoff_rows(
    slot_id: str, generation: int, now: datetime, policy: TimerPolicy
) -> tuple[Timer, ...]:
    """Stages 1..3 for ``slot_id``. Dues are ``now + policy.infra_backoff``."""
    return tuple(
        Timer(
            key=timer_key(INFRA_BACKOFF, slot_id, stage),
            kind=INFRA_BACKOFF,
            scope=slot_id,
            subject=slot_id,
            generation=generation,
            stage=stage,
            due_at=now + delay,
        )
        for stage, delay in enumerate(policy.infra_backoff, start=1)
    )


def plan_probe_timer(
    subject: str,
    generation: int,
    now: datetime,
    policy: TimerPolicy,
    *,
    stage: int = 1,
    scope: str | None = None,
) -> Timer:
    """One plan probe. Stage 1 is due at ``now + plan_probe_start``."""
    return Timer(
        key=timer_key(PLAN_PROBE, subject, stage),
        kind=PLAN_PROBE,
        scope=subject if scope is None else scope,
        subject=subject,
        generation=generation,
        stage=stage,
        due_at=now + probe_delay(policy, stage),
    )


def arm_infra_backoff(
    state: RunState,
    slot_id: str,
    generation: int,
    now: datetime,
    policy: TimerPolicy,
) -> RunState:
    """Store stages 1..3 for ``slot_id``. Does not pause and does not emit effects."""
    return _store(state, infra_backoff_rows(slot_id, generation, now, policy))


def arm_plan_probe(
    state: RunState,
    subject: str,
    generation: int,
    now: datetime,
    policy: TimerPolicy,
    *,
    stage: int = 1,
) -> RunState:
    """Store one ``plan_probe`` row. Does not pause and does not emit effects."""
    return _store(state, (plan_probe_timer(subject, generation, now, policy, stage=stage),))


def rearm_plan_probe(
    state: RunState, timer: Timer, now: datetime, policy: TimerPolicy
) -> tuple[RunState, Timer]:
    """Disarm ``timer`` and store the next probe at ``min(previous * 2, cap)`` from ``now``.

    ``previous`` is the policy delay for ``timer.stage``, not the time remaining until
    ``due_at``. The pause is left for the caller to clear.
    """
    next_stage = timer.stage + 1
    previous = probe_delay(policy, timer.stage)
    row = plan_probe_timer(
        timer.subject,
        timer.generation,
        now,
        policy,
        stage=next_stage,
        scope=timer.scope,
    )
    # ``plan_probe_timer`` uses the same doubling. Pin the due to this formula so a
    # stage that is already at the cap does not grow.
    due_at = now + min(previous * 2, policy.plan_probe_cap)
    row = row.model_copy(update={"due_at": due_at})
    kept = tuple(item for item in state.timers if item.key != timer.key)
    return _store(state.model_copy(update={"timers": kept}), (row,)), row


def _subjects_to_disarm(before: RunState, after: RunState) -> set[str]:
    """Subjects whose reminder and alert should leave with this transition."""
    drop: set[str] = set()
    previous_gates = {visit.token: visit for visit in before.gates}
    for visit in after.gates:
        previous = previous_gates.get(visit.token)
        if previous is None or previous.status != "open" or visit.status == "open":
            continue
        if any(
            item.activation_id == visit.activation_id and item.status == "open"
            for item in after.gates
        ):
            continue
        drop.add(visit.activation_id)
    previous_decisions = {item.activation_id: item.status for item in before.decisions}
    for decision in after.decisions:
        previous = previous_decisions.get(decision.activation_id)
        if decision.status == "decided" and previous != "decided":
            drop.add(decision.activation_id)
        if decision.status != "requested" or previous == "requested":
            continue
        for timer in after.timers:
            node_id = timer.subject.split("|", 1)[0]
            if (
                timer.kind in WATCHDOG_KINDS
                and timer.subject != decision.activation_id
                and node_id == decision.node_id
            ):
                drop.add(timer.subject)
    return drop


def _subjects_to_arm(before: RunState, after: RunState) -> tuple[tuple[str, int], ...]:
    """Newly requested decisions, then newly opened gate visits."""
    armed: list[tuple[str, int]] = []
    previous_decisions = {item.activation_id: item.status for item in before.decisions}
    for decision in after.decisions:
        previous = previous_decisions.get(decision.activation_id)
        if decision.status == "requested" and previous != "requested":
            armed.append((decision.activation_id, 1))
    previous_open = {visit.token for visit in before.gates if visit.status == "open"}
    for visit in after.gates:
        if visit.status == "open" and visit.token not in previous_open:
            armed.append((visit.activation_id, visit.visit_no))
    return tuple(armed)


def _replace_watchdog(
    timers: list[Timer],
    subject: str,
    generation: int,
    now: datetime,
    policy: TimerPolicy,
) -> list[Timer]:
    """Drop this subject's watchdogs and arm reminder at ``now + T``, alert at ``now + 2T``."""
    kept = [
        timer for timer in timers if timer.subject != subject or timer.kind not in WATCHDOG_KINDS
    ]
    span = policy.watchdog
    kept.append(_watchdog(WATCHDOG_REMIND, subject, generation, 1, now + span))
    kept.append(_watchdog(WATCHDOG_ALERT, subject, generation, 2, now + (span * 2)))
    return kept


def _watchdog(kind: str, subject: str, generation: int, stage: int, due_at: datetime) -> Timer:
    return Timer(
        key=f"{kind}:{subject}",
        kind=kind,
        scope=subject,
        subject=subject,
        generation=generation,
        stage=stage,
        due_at=due_at,
    )


def _store(state: RunState, rows: tuple[Timer, ...]) -> RunState:
    return state.model_copy(update={"timers": _upsert(state.timers, rows)})


def _upsert(existing: tuple[Timer, ...], rows: tuple[Timer, ...]) -> tuple[Timer, ...]:
    by_key = {row.key: row for row in rows}
    seen: set[str] = set()
    merged: list[Timer] = []
    for timer in existing:
        replacement = by_key.get(timer.key)
        if replacement is None:
            merged.append(timer)
            continue
        merged.append(replacement)
        seen.add(timer.key)
    merged.extend(row for row in rows if row.key not in seen)
    return tuple(merged)
