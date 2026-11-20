"""The alerts a run commit raises and resolves, and what each one tells the run's owner.

Gate alerts follow the commit's gate-visit rows; pause and run-end alerts follow the
run row's status (and a user's pause gaining another cause) before and after the
commit; watchdog alerts come only for decisions. An alert's id derives from its
workspace, run, kind and raise key, so a re-fold, a resync or a retried commit
raises nothing twice, and the store never reopens a resolved alert.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType

from coral.alerts.types import (
    MAX_ALERT_MESSAGE_CHARS,
    MAX_ALERT_RUN_TITLE_CHARS,
    MAX_ALERT_STEP_LABEL_CHARS,
    AlertAction,
    AlertKindName,
    AlertPayload,
)
from coral.bridge.messages import strip_format_characters
from coral.db.enum_codecs import (
    ALERT_KIND,
    AlertKind,
    AlertPriority,
    GateVisitStatus,
    RunPauseReason,
    RunStatus,
    decode_run_pause_reason,
)
from coral.engine import types as engine
from coral.engine.machines.activation import find_node
from coral.gates.ids import gate_node, is_binary_gate
from coral.model.ids import derived_id
from coral.model.ir import CompiledGraph, CompiledNode
from coral.stores.protocols import (
    AlertDraft,
    AlertResolution,
    CoralRun,
    GateVisitDraft,
    GateVisitState,
)

# What a pause alert says for each run-row pause reason; a user's own pause has none.
PAUSE_MESSAGES: Mapping[str, str] = MappingProxyType(
    {
        "gate": "The run is waiting at a gate.",
        "budget": "The run reached its activation cap.",
        "plan_limit": "A step reached its plan's usage limit.",
        "rejected_calls": "A step kept making calls Coral refused.",
        "infra": "A step kept failing to finish its turn.",
        "liveness": "A step is waiting for one that can no longer run.",
        "authority_revoked": "The run lost the authority it was started with.",
        "merge_conflict": "The run's changes conflict with its base branch.",
        "failure_path": "A step or one of Coral's own actions failed.",
        "engine_upgrade": "The run needs a newer Coral engine.",
        "drift": "A session the run uses was changed outside Coral.",
        "auth": "A step's harness needs you to sign in again.",
    }
)
_UNKNOWN_PAUSE = "The run paused."
_RUN_ENDS: Mapping[int, tuple[AlertKindName, str, str]] = MappingProxyType(
    {
        int(RunStatus.COMPLETED): ("run_completed", "Run completed", "The run finished."),
        int(RunStatus.FAILED): ("run_failed", "Run failed", "The run failed."),
        int(RunStatus.CANCELLED): ("run_cancelled", "Run cancelled", "The run was cancelled."),
    }
)
# A finished run leaves nothing to answer, resume or choose.
_RESOLVED_AT_RUN_END = (
    int(AlertKind.GATE),
    int(AlertKind.QUESTION),
    int(AlertKind.PAUSE),
    int(AlertKind.WATCHDOG),
)
_READ_ONLY: tuple[AlertAction, ...] = ("open_run", "mark_read")
_CUT = "…"


@dataclass(frozen=True)
class AlertChanges:
    """The alert raises and resolutions of one run commit."""

    raises: tuple[AlertDraft, ...] = ()
    resolutions: tuple[AlertResolution, ...] = ()


def alert_subject(run_id: str, *parts: str) -> str:
    """The 32-hex id of what an alert is about, which its resolutions match."""
    return derived_id("coral-alert-subject", run_id, *parts)


def alert_id(workspace_id: int, run_id: str, kind: AlertKindName, key: str) -> str:
    """The 32-hex id of the alert of ``kind`` that ``key`` raises in a run."""
    return derived_id("coral-alert", str(workspace_id), run_id, kind, key)


def run_link(run_id: str, node_id: str | None = None, *, panel: str | None = None) -> str:
    """The web path of a run, opened at a node and, given one, a panel of it."""
    path = f"/workflows/runs/{run_id}"
    if node_id is None:
        return path
    return f"{path}?node={node_id}" + (f"&panel={panel}" if panel else "")


def commit_alerts(
    run: CoralRun,
    graph: CompiledGraph,
    *,
    first: engine.RunState,
    final: engine.RunState,
    effects: Iterable[engine.Effect],
    loaded_gates: Sequence[GateVisitState],
    gate_drafts: Sequence[GateVisitDraft],
    status: int,
    pause_reason: int | None,
) -> AlertChanges:
    """
    The alerts a commit raises and resolves, raises first.

    :param run: The run row as loaded, before the commit.
    :param first: The engine state before the commit's entries.
    :param final: The engine state after them.
    :param effects: The effects of the commit's accepted entries.
    :param loaded_gates: The gate-visit rows as loaded.
    :param gate_drafts: The gate-visit rows the commit writes.
    :param status: The run row's status after the commit.
    :param pause_reason: The run row's pause reason after the commit.
    """
    raises: list[AlertDraft] = []
    resolutions: list[AlertResolution] = []
    was_open = {row.id for row in loaded_gates if row.status == int(GateVisitStatus.OPEN)}
    for draft in gate_drafts:
        if draft.status == int(GateVisitStatus.OPEN):
            if draft.id not in was_open:
                raises.append(_gate_alert(run, graph, final, draft))
        elif draft.id in was_open:
            resolutions.append(AlertResolution(subject_id=draft.id))
    paused = int(RunStatus.PAUSED)
    # A run the owner paused that gains another cause will not continue on their resume.
    user_paused = run.status == paused and run.pause_reason == int(RunPauseReason.USER)
    if status == paused and (run.status != paused or (user_paused and pause_reason is not None)):
        pause = row_pause_alert(run, pause_reason)
        raises.extend(() if pause is None else (pause,))
    elif run.status == paused and status != paused:
        resolutions.append(AlertResolution(subject_id=alert_subject(run.id, "pause")))
    raises.extend(_watchdog_alerts(run, graph, final, effects))
    resolutions.extend(_decided(run.id, first, final))
    end = _RUN_ENDS.get(status)
    if end is not None and run.status not in _RUN_ENDS:
        raises.append(_run_end_alert(run, *end))
        resolutions.append(AlertResolution(kinds=_RESOLVED_AT_RUN_END))
    return AlertChanges(raises=tuple(raises), resolutions=tuple(resolutions))


def row_pause_alert(run: CoralRun, pause_reason: int | None) -> AlertDraft | None:
    """
    The alert of the commit that shows ``run`` paused for ``pause_reason``.

    Raised when the run becomes paused, or when a user's pause gains another cause.
    One per such commit: its key is the version the commit gives the run. A user's
    own pause raises none.
    """
    if pause_reason == int(RunPauseReason.USER):
        return None
    name = None if pause_reason is None else decode_run_pause_reason(pause_reason)
    payload = AlertPayload(
        title="Run paused",
        message=PAUSE_MESSAGES.get(name or "", _UNKNOWN_PAUSE),
        run_title=_run_title(run),
        actions=_READ_ONLY,
        deep_link=run_link(run.id),
        pause_reason=name,
    )
    subject = alert_subject(run.id, "pause")
    return _draft(run, "pause", str(run.version + 1), subject, payload, AlertPriority.NORMAL)


def _watchdog_alerts(
    run: CoralRun,
    graph: CompiledGraph,
    final: engine.RunState,
    effects: Iterable[engine.Effect],
) -> list[AlertDraft]:
    """An alert for each watchdog alert stage of a decision still open after the commit."""
    still_open = {
        decision.activation_id: decision
        for decision in final.decisions
        if decision.status != "decided"
    }
    return [
        _watchdog_alert(run, graph, still_open[effect.subject], effect)
        for effect in effects
        if effect.subject in still_open and _is_watchdog_alert(effect)
    ]


def _decided(run_id: str, first: engine.RunState, final: engine.RunState) -> list[AlertResolution]:
    """Resolve the watchdog alerts of the decisions the commit decided."""
    before = {item.activation_id for item in first.decisions if item.status == "decided"}
    return [
        AlertResolution(subject_id=alert_subject(run_id, "decision", item.activation_id))
        for item in final.decisions
        if item.status == "decided" and item.activation_id not in before
    ]


def _gate_alert(
    run: CoralRun, graph: CompiledGraph, final: engine.RunState, draft: GateVisitDraft
) -> AlertDraft:
    visit = next((item for item in final.gates if item.token == draft.token), None)
    node = gate_node(graph, visit) if visit is not None else None
    binary = node is not None and is_binary_gate(node)
    step = _step_label(node, draft.node_id)
    prompt = _clean(node.prompt, MAX_ALERT_MESSAGE_CHARS) if node and node.prompt else ""
    approve_link = (
        f"/approve/{draft.elicitation_session_id}/{draft.elicitation_id}"
        if binary and draft.elicitation_session_id and draft.elicitation_id
        else None
    )
    payload = AlertPayload(
        title="Approval needed" if binary else "Decision needed",
        message=prompt or _clean(f"{step} is waiting for your answer.", MAX_ALERT_MESSAGE_CHARS),
        run_title=_run_title(run),
        step_label=step,
        node_id=draft.node_id,
        actions=("answer", "open_run"),
        deep_link=run_link(run.id, draft.node_id, panel="gate"),
        approve_link=approve_link,
        elicitation_id=draft.elicitation_id,
        session_id=draft.elicitation_session_id,
        outcomes=node.outcomes if node is not None else (),
    )
    return _draft(run, "gate", draft.id, draft.id, payload, AlertPriority.NORMAL)


def _watchdog_alert(
    run: CoralRun, graph: CompiledGraph, decision: engine.Decision, effect: engine.Effect
) -> AlertDraft:
    step = _step_label(find_node(graph, decision.node_id), decision.node_id)
    payload = AlertPayload(
        title="Decision waiting",
        message=f"The orchestrator has not chosen at {step} for an hour.",
        run_title=_run_title(run),
        step_label=step,
        node_id=decision.node_id,
        actions=_READ_ONLY,
        deep_link=run_link(run.id, decision.node_id),
    )
    subject = alert_subject(run.id, "decision", decision.activation_id)
    return _draft(run, "watchdog", effect.effect_key, subject, payload, AlertPriority.NORMAL)


def _run_end_alert(run: CoralRun, kind: AlertKindName, title: str, message: str) -> AlertDraft:
    payload = AlertPayload(
        title=title,
        message=message,
        run_title=_run_title(run),
        actions=_READ_ONLY,
        deep_link=run_link(run.id),
    )
    return _draft(run, kind, kind, alert_subject(run.id, "run"), payload, AlertPriority.LOW)


def _draft(
    run: CoralRun,
    kind: AlertKindName,
    key: str,
    subject_id: str,
    payload: AlertPayload,
    priority: AlertPriority,
) -> AlertDraft:
    return AlertDraft(
        id=alert_id(run.workspace_id, run.id, kind, key),
        run_id=run.id,
        kind=ALERT_KIND[kind],
        priority=int(priority),
        subject_id=subject_id,
        payload=payload.model_dump_json(),
        owner_user_id=run.user_id,
        account_generation=run.account_generation,
    )


def _is_watchdog_alert(effect: engine.Effect) -> bool:
    return (
        effect.kind == "notify"
        and effect.payload.get("kind") == "watchdog"
        and effect.payload.get("stage") == "alert"
    )


def _step_label(node: CompiledNode | None, node_id: str) -> str:
    name = node.name if node is not None and node.name else node_id
    return _clean(name, MAX_ALERT_STEP_LABEL_CHARS) or node_id


def _run_title(run: CoralRun) -> str:
    return _clean(run.title, MAX_ALERT_RUN_TITLE_CHARS)


def _clean(text: str, limit: int) -> str:
    """``text`` on one line, without control or format characters, cut to ``limit``."""
    spaced = " ".join(text.split())
    cleaned = " ".join(strip_format_characters(spaced).split())
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[: limit - len(_CUT)].rstrip() + _CUT


__all__ = [
    "PAUSE_MESSAGES",
    "AlertChanges",
    "alert_id",
    "alert_subject",
    "commit_alerts",
    "row_pause_alert",
    "run_link",
]
