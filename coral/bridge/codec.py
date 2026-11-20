"""Engine log entries as ``coral_run_log`` rows of kind ENGINE, and back.

A row's body is the entry's JSON; the store's ``seq`` orders rows, never the
entry's own ``seq``, which a refused input repeats. Refused entries are stored
audit-only and never replayed.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from datetime import timedelta

from pydantic import ValidationError

from coral.bridge.config import MAX_ACTOR_REF_CHARS, epoch_us
from coral.bridge.keys import store_activation_id
from coral.db.enum_codecs import ActorKind, LogKind
from coral.engine import types as engine
from coral.engine.machines.activation import find_activation
from coral.engine.machines.slot import find_slot
from coral.stores.protocols import LogEntryDraft, RunLogEntry

_STEP_AGENT_KINDS = frozenset({"handoff_received", "handoff_evaluated", "rejection_observed"})
_USER_KINDS = frozenset({"start_run", "resume_run", "cancel_run", "retry_step", "answer_gate"})


class EngineLogDecodeError(ValueError):
    """A stored engine row is not an engine log entry."""


def actor_kind(command: engine.Input) -> ActorKind:
    """Who an input speaks for: a step agent, the orchestrator, a person or the engine."""
    if command.kind in _STEP_AGENT_KINDS:
        return ActorKind.STEP_AGENT
    if command.kind == "choose_arrow":
        return ActorKind.ORCHESTRATOR
    if command.kind in _USER_KINDS:
        return ActorKind.USER
    if isinstance(command, engine.PauseRun) and command.reason == "user":
        return ActorKind.USER
    return ActorKind.ENGINE


def entry_draft(
    entry: engine.LogEntry,
    *,
    run_id: str,
    before: engine.RunState,
    actor: str | None,
) -> LogEntryDraft:
    """
    The run-log row for one engine entry.

    :param before: The state the entry was applied to; it names the slot's activation
        and node for an input about a slot.
    :param actor: Who asked for the commit (a user id or the calling session), if anyone.
    :raises ValueError: for an entry not stamped in UTC: a replay must read back times
        that compare equal, and a local time near a DST change may not.
    """
    if entry.now.utcoffset() != timedelta(0):
        raise ValueError("engine log entries are stamped in UTC")
    activation_id = node_id = scope_key = None
    slot_id = getattr(entry.input, "slot_id", None)
    slot = find_slot(before, slot_id) if isinstance(slot_id, str) else None
    if slot is not None:
        owner = find_activation(before, slot.activation_id)
        if owner is not None:
            activation_id = store_activation_id(run_id, owner.id)
            node_id = owner.node_id
            scope_key = slot.id
    patch = (
        json.dumps([item.model_dump(mode="json") for item in entry.patch]) if entry.patch else None
    )
    return LogEntryDraft(
        kind=int(LogKind.ENGINE),
        actor_kind=int(actor_kind(entry.input)),
        body=entry.model_dump_json(),
        audit_only=entry.rejection is not None,
        actor_ref=None if actor is None else actor[:MAX_ACTOR_REF_CHARS],
        activation_id=activation_id,
        node_id=node_id,
        scope_key=scope_key,
        idempotency_cksum=None,
        view_patch=patch,
        created_at_us=epoch_us(entry.now),
    )


def decode_entries(rows: Iterable[RunLogEntry]) -> list[engine.LogEntry]:
    """
    The replayable entries of ``rows``, in the order given.

    Audit-only rows and rows of other kinds are skipped.

    :raises EngineLogDecodeError: for a body that is not an engine entry.
    """
    entries: list[engine.LogEntry] = []
    for row in rows:
        if row.kind != int(LogKind.ENGINE) or row.audit_only:
            continue
        try:
            entries.append(engine.LogEntry.model_validate_json(row.body))
        except ValidationError:
            raise EngineLogDecodeError(
                f"engine log row seq {row.seq} of run {row.run_id} is not an engine entry"
            ) from None
    return entries


__all__ = ["EngineLogDecodeError", "actor_kind", "decode_entries", "entry_draft"]
