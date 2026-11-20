"""The actions a run allows its owner: one rule for the run list, the detail and the stream.

A finished row is authoritative over the view. A list item uses the row alone and offers
a subset of what its detail offers.
"""

from __future__ import annotations

from collections.abc import Mapping

from pydantic import BaseModel, ConfigDict, JsonValue

from coral.engine.lifecycle import resume_clears
from coral.engine.projection import RunView
from coral.engine.types import PauseCause, RunStatus
from coral.runview.types import FINISHED_RUN_STATUSES, PauseReasonName, RunAction, RunStatusName

# Row reasons that are the engine's first cause and that ResumeRun clears without a cap.
# ``drift`` and ``failure_path`` are left out: a pause made on the row alone writes them,
# and one can sit on an engine paused for ``budget``, which needs a cap.
LIST_RESUMABLE_REASONS: frozenset[PauseReasonName] = frozenset(
    {"user", "rejected_calls", "infra", "auth", "plan_limit", "authority_revoked"}
)
_LIVE: tuple[RunAction, ...] = ("pause", "cancel")
_RESUMABLE: tuple[RunAction, ...] = ("resume", "cancel")
_CANCEL_ONLY: tuple[RunAction, ...] = ("cancel",)


class RunViewFacts(BaseModel):
    """The engine status and pause causes of a loaded run, from a ``RunView`` or its JSON."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    status: RunStatus | None = None
    causes: tuple[PauseCause, ...] = ()

    @classmethod
    def of(cls, view: RunView | Mapping[str, JsonValue]) -> RunViewFacts:
        if isinstance(view, RunView):
            return cls(status=view.status, causes=view.causes)
        return cls.model_validate(dict(view))


def allowed_actions(
    *,
    row_status: RunStatusName,
    row_pause_reason: PauseReasonName | None,
    view: RunViewFacts | None,
    loadable: bool,
) -> tuple[RunAction, ...]:
    """
    What the owner may do to the run now.

    A list item cannot see whether a run loads. A run the bridge failed to load is paused
    ``failure_path``, so both list it Cancel only; one not yet paused, or paused for another
    reason before its rows stopped decoding, is listed by that row until a write repairs it.

    :param view: The loaded engine's facts; ``None`` with ``loadable`` for a run that was
        not loaded (a list item), which is judged by its row alone.
    :param loadable: ``False`` for a run the bridge cannot load, including a stream whose
        view is ``None``: only Cancel is offered.
    """
    if row_status in FINISHED_RUN_STATUSES:
        return ()
    if not loadable:
        return _CANCEL_ONLY
    if row_status != "paused":
        return _LIVE
    if view is None:
        return _RESUMABLE if row_pause_reason in LIST_RESUMABLE_REASONS else _CANCEL_ONLY
    # A paused row over an engine that is not paused is a pause on the row alone.
    if view.status != "paused":
        return _RESUMABLE
    return _RESUMABLE if any(resume_clears(cause) for cause in view.causes) else _CANCEL_ONLY


__all__ = ["LIST_RESUMABLE_REASONS", "RunViewFacts", "allowed_actions"]
