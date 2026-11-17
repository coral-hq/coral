"""The narrow port engine tools decide through, and the plans their planners return.

The bridge to the run store implements :class:`RunDecisionPort`; tests use an
in-memory fake. Planners are pure functions of one :class:`RunSnapshot`.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

from coral.engine.types import Input, Rejection, RunState
from coral.model.ir import CompiledGraph
from coral.stores.protocols import CoralRun, RunContended, RunNotFound
from coral.tools.schemas import ToolReply

# Attempts the port makes before it gives up on a run other writers keep changing.
MAX_DECIDE_ATTEMPTS = 5


@dataclass(frozen=True)
class RunSnapshot:
    """The run's store row and its folded engine state, from one consistent read."""

    run: CoralRun
    graph: CompiledGraph
    state: RunState


@dataclass(frozen=True)
class Reply:
    """Answer without writing anything. ``log`` adds detail to the refusal's log line."""

    reply: ToolReply
    log: str | None = None


@dataclass(frozen=True)
class Commit:
    """
    Apply engine inputs in order and answer ``reply``.

    :param observation: The inputs only record what happened (a counted
        rejection), so ``reply`` stands even when the engine refuses them.
    """

    inputs: tuple[Input, ...]
    reply: ToolReply
    observation: bool = False


Plan = Reply | Commit
Planner = Callable[[RunSnapshot], Plan]


class EngineRefused(RuntimeError):
    """The engine refused a planned input; the call's tool maps the code to a reply."""

    def __init__(self, rejection: Rejection) -> None:
        self.rejection = rejection
        super().__init__(f"the engine refused a planned input: {rejection.code}")

    @property
    def code(self) -> str:
        return self.rejection.code


class RunDecisionPort(Protocol):
    """
    Decide one engine tool call against a run, at most once per checksum.

    ``decide`` must, on every attempt:

    1. Return the reply stored under ``cksum``, if any (a resent call, another
       replica or a restart).
    2. Load a :class:`RunSnapshot`, with the graph pinned to the run's version
       hash. A missing run raises :class:`~coral.stores.protocols.RunNotFound`.
    3. Run ``planner``. A :class:`Reply` is returned as it is; nothing is written.
    4. For a :class:`Commit`, run ``transition(graph, state, input, now)`` for
       each input in order. If any is rejected, write nothing: return
       ``reply`` for an observation, else raise :class:`EngineRefused`.
    5. Otherwise write every log entry, its effects and ``reply.to_json()``
       under ``cksum`` in one ``apply_transition``, compare-and-swap on the
       snapshot's run version, and return ``reply``.
    6. On a version conflict, start again from 1. After
       :data:`MAX_DECIDE_ATTEMPTS` attempts raise
       :class:`~coral.stores.protocols.RunContended`.

    The port does not log; the dispatcher logs refusals with the call's tool.
    Each ``decide`` must be bounded (database statement and lock timeouts),
    because a caller waits for it.

    The planners' generation fence and slot receipt hold only if the bridge
    also keeps these rules:

    a. A retried slot's new session is bound with the slot's current
       ``session_generation`` (the ``retry_step`` effect's ``generation``).
       Otherwise every handoff from it is ``slot.superseded``, uncounted, and
       the step stalls.
    b. At most one session is bound to a (run, slot, generation); the fence
       compares generations only.
    c. Every write to a run row field a planner reads (``status``,
       ``pause_reason``, ``orchestrator_session_id``) bumps the version the
       compare-and-swap checks, so a decision racing a store-only pause
       re-plans.
    d. A slot's handoff body is stored and read back byte for byte; the
       duplicate receipt compares it as a string.
    """

    def find_reply(self, workspace_id: int, run_id: str, cksum: bytes) -> ToolReply | None: ...

    def decide(
        self, workspace_id: int, run_id: str, planner: Planner, cksum: bytes
    ) -> ToolReply: ...


__all__ = [
    "MAX_DECIDE_ATTEMPTS",
    "Commit",
    "EngineRefused",
    "Plan",
    "Planner",
    "Reply",
    "RunContended",
    "RunDecisionPort",
    "RunNotFound",
    "RunSnapshot",
]
