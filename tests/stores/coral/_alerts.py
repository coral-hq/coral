"""Alert rows for store and API tests: owned runs, alert drafts and the commit that writes them.

Each builder takes its inputs from the caller and asserts nothing.
"""

from __future__ import annotations

from collections.abc import Sequence

from coral.alerts.types import AlertPayload
from coral.db.enum_codecs import AlertKind, AlertPriority
from coral.model.ids import derived_id
from coral.stores.protocols import (
    AlertDraft,
    AlertResolution,
    CoralRun,
    LogEntryDraft,
    RunStartSpec,
    RunStore,
    ToolReplyDraft,
    Transition,
)

# A non-zero workspace, so a missing workspace argument cannot pass by default.
WORKSPACE = 7
OTHER_WORKSPACE = 8
NOW = 1_700_000_000
ALICE = "alice"
BOB = "bob"


def start_owned_run(
    runs: RunStore,
    key: str,
    *,
    user_id: str | None = ALICE,
    generation: str | None = None,
    workspace_id: int = WORKSPACE,
    workflow_id: str = "wf",
    now: int = NOW,
) -> CoralRun:
    """A run of ``user_id`` recorded under ``generation``, started at ``now``."""
    spec = RunStartSpec(
        workflow_id,
        "v1",
        f"Run {key}",
        "p",
        workspace_id=workspace_id,
        user_id=user_id,
        account_generation=generation,
    )
    return runs.start_run(spec, start_key=key, now=now)


def alert_payload(title: str = "Run paused") -> str:
    """A read-only alert's stored payload."""
    return AlertPayload(
        title=title,
        message="The run paused.",
        run_title="Fix the parser",
        actions=("open_run", "mark_read"),
        deep_link="/workflows/runs/r",
    ).model_dump_json()


def alert_draft(
    run: CoralRun,
    kind: AlertKind,
    key: str,
    *,
    subject: str | None = None,
    priority: AlertPriority = AlertPriority.NORMAL,
    created_at: int = 0,
    title: str = "Run paused",
) -> AlertDraft:
    """An alert of ``run`` whose id derives from ``kind`` and ``key``, as the rules derive it."""
    return AlertDraft(
        id=derived_id("coral-alert", str(run.workspace_id), run.id, kind.name.lower(), key),
        run_id=run.id,
        kind=int(kind),
        priority=int(priority),
        subject_id=subject or derived_id("coral-alert-subject", run.id, key),
        payload=alert_payload(title),
        # As the run names its owner; the store folds the local user into None.
        owner_user_id=run.user_id,
        account_generation=run.account_generation,
        created_at=created_at,
    )


def commit_alert_changes(
    runs: RunStore,
    run: CoralRun,
    *,
    raises: Sequence[AlertDraft] = (),
    resolutions: Sequence[AlertResolution] = (),
    now: int = NOW,
    tool_reply: ToolReplyDraft | None = None,
    expected_version: int | None = None,
) -> None:
    """One run commit carrying the alert changes beside a log entry."""
    current = runs.get_run(run.id, workspace_id=run.workspace_id)
    assert current is not None
    runs.apply_transition(
        run.id,
        current.version if expected_version is None else expected_version,
        Transition(
            alert_raises=raises,
            alert_resolutions=resolutions,
            logs=(LogEntryDraft(kind=1, actor_kind=1, body="{}"),),
            tool_reply=tool_reply,
        ),
        workspace_id=run.workspace_id,
        now=now,
    )
