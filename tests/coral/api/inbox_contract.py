"""The workflow Inbox contract the web tests render, built by the backend's own producers.

One feed page (a gate alert and a pause alert of one run), the run's anchor row as the
session list shows it, and the anchor's pending prompts as its snapshot replays them: the
gate's, published by the gate executor's ``publish_live`` through S6a, and a step's
approval, published on the step and mirrored onto the anchor as Omnigent's routes do.
The anchor row and the prompts are read back through the session routes' own index
reads, or through the routes themselves (``read_anchor``). Ids, times and prompt ids are
fixed, so the output is stable.

Regenerate the checked-in file: ``uv run --no-sync python -m tests.coral.api.inbox_contract
--write`` (the web Prettier hook then formats it; the test compares parsed JSON).
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import sys
import tempfile
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

from coral.api.inbox import WorkflowInboxPage, alert_item
from coral.bridge.executors import BridgeThreads
from coral.db.enum_codecs import AlertStatus, GateVisitStatus
from coral.engine.types import PauseRun
from coral.gates.executors import publish_live
from coral.gates.ids import GATE_ELICITATION_PREFIX
from coral.model.ids import anchor_session_id, effect_session_id
from coral.omni.protocols import SessionCreateRequest
from coral.omni.server.gates import OmnigentGatePublisher
from coral.omni.server.sessions import ROLE_LABEL_KEY, RUN_ID_LABEL_KEY, _role_label
from coral.stores.fakes import FakeRunStore
from coral.stores.protocols import CoralRun
from omnigent.policies.types import ElicitationRequest
from omnigent.runtime import pending_elicitations, session_stream
from omnigent.runtime.policies.approval import build_elicitation_request_event
from omnigent.server.elicitation_hooks import (
    VerdictDecision,
    claimed_handler,
    register_elicitation_verdict_handler,
)
from omnigent.server.routes._sessions.helpers import (
    _pending_elicitation_snapshot_for_session,
    _publish_elicitation_request_to_ancestors,
)
from omnigent.stores.conversation_store import ConversationStore
from omnigent.stores.conversation_store.sqlalchemy_store import SqlAlchemyConversationStore
from tests.coral.bridge._gates import GATED, IMPLEMENT_FIRST, GateIds, complete, effects
from tests.coral.bridge._scripted_runs import accept
from tests.coral.bridge._world import WORKSPACE, World, start
from tests.stores.coral._faults import evict_cached_engine

CONTRACT_PATH = (
    Path(__file__).resolve().parents[3] / "web/src/workflows/fixtures/workflowInbox.contract.json"
)
# A step's tool approval, as Omnigent ids its prompts.
STEP_PROMPT_ID = "elicit_" + "5" * 32
REPORT = "Fixed the parser and added a regression test."

# Reads the anchor's session-list row (``id``, ``labels``, ``pending_elicitations_count``)
# and its snapshot's ``pending_elicitations``.
AnchorReader = Callable[[ConversationStore, str], tuple[dict[str, Any], list[dict[str, Any]]]]


def _hand_off(world: World, run_id: str) -> str:
    """The implement step runs, hands off and closes; returns its session id."""
    (create,) = effects(world, run_id, "create_session")
    session_id = effect_session_id(WORKSPACE, create.effect_key)
    created = {"session_id": session_id, "role": "step", "generation": 1}
    complete(world, run_id, "create_session", IMPLEMENT_FIRST, created)
    sent = {"session_id": session_id, "stable_id": "m1"}
    complete(world, run_id, "send_input", IMPLEMENT_FIRST, sent)
    world.bridge.commit_inputs(
        workspace_id=WORKSPACE,
        run_id=run_id,
        inputs=lambda _snapshot: accept(IMPLEMENT_FIRST, REPORT),
    )
    complete(world, run_id, "close_slot", IMPLEMENT_FIRST, {})
    return session_id


def _anchor_labels(run: CoralRun) -> dict[str, str]:
    """The labels Coral's session facade gives a run's anchor."""
    request = SessionCreateRequest(
        workspace_id=WORKSPACE,
        run_id=run.id,
        effect_key="",
        user_id=run.user_id,
        account_generation=run.account_generation,
        role="anchor",
        title=run.title,
    )
    return {RUN_ID_LABEL_KEY: run.id, ROLE_LABEL_KEY: _role_label(request)}


async def _refuse(_verdict: object) -> VerdictDecision:
    return VerdictDecision(accepted=False, reason="contract", message="Not answered here.")


@contextlib.contextmanager
def _gate_ids_claimed() -> Iterator[None]:
    """S6a publishes only claimed ids: claim the gate prefix unless a handler already does."""
    if claimed_handler(GATE_ELICITATION_PREFIX + "0" * 32) is not None:
        yield
        return
    unregister = register_elicitation_verdict_handler(GATE_ELICITATION_PREFIX, _refuse)
    try:
        yield
    finally:
        unregister()


def _publish_gate(world: World, run_id: str) -> None:
    """The gate executor's publish of the run's open visits on its anchor."""
    open_rows = [
        row.id
        for row in world.bridge.load(workspace_id=WORKSPACE, run_id=run_id).store.gate_visits
        if row.status == int(GateVisitStatus.OPEN)
    ]

    async def publish() -> None:
        threads = BridgeThreads(world.bridge)
        try:
            await publish_live(
                OmnigentGatePublisher(),
                threads,
                workspace_id=WORKSPACE,
                run_id=run_id,
                visit_ids=open_rows,
            )
        finally:
            threads.close()

    with _gate_ids_claimed():
        asyncio.run(publish())


def _publish_step_prompt(conversations: ConversationStore, step_session_id: str) -> None:
    """A step's shell approval: published on the step, then mirrored to its ancestors."""
    event = build_elicitation_request_event(
        STEP_PROMPT_ID,
        ElicitationRequest(
            message="Allow the shell command?",
            phase="tool_call",
            policy_names=["approve_shell_commands"],
            content_preview="git push origin HEAD",
        ),
    )
    session_stream.publish(step_session_id, event)
    _publish_elicitation_request_to_ancestors(conversations, step_session_id, event)


def read_anchor_from_index(
    conversations: ConversationStore, anchor_id: str
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """The anchor as ``GET /v1/sessions`` counts it and ``GET /v1/sessions/{id}`` replays it."""
    anchor = conversations.get_conversation(anchor_id)
    assert anchor is not None
    row = {
        "id": anchor.id,
        "labels": dict(anchor.labels or {}),
        "pending_elicitations_count": pending_elicitations.counts_for([anchor_id])[anchor_id],
    }
    return row, _pending_elicitation_snapshot_for_session(conversations, anchor)


def build_contract(
    *,
    conversations: ConversationStore | None = None,
    anchor_agent_id: str | None = None,
    read_anchor: AnchorReader = read_anchor_from_index,
) -> dict[str, Any]:
    """
    The contract: ``inbox_page``, ``anchor_row`` and ``pending_elicitations``.

    :param conversations: The sessions store the anchor and step are created in; a
        scratch SQLite store when not given.
    :param anchor_agent_id: The anchor's agent; the session list shows only sessions
        that have one.
    :param read_anchor: Reads the anchor's row and snapshot, e.g. through the routes.
    """
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as scratch:
        world = World.fake(Path(scratch), gate_ids=GateIds())
        run = start(world, GATED)
        step_session_id = _hand_off(world, run.id)
        world.clock.advance(60)
        world.bridge.commit_inputs(
            workspace_id=WORKSPACE,
            run_id=run.id,
            inputs=lambda _snapshot: (PauseRun(reason="infra", detail="turns failed"),),
        )
        scratch_uri = f"sqlite:///{Path(scratch) / 'sessions.db'}"
        store = conversations or SqlAlchemyConversationStore(scratch_uri)
        anchor_id = anchor_session_id(WORKSPACE, run.id)
        try:
            store.create_conversation(
                conversation_id=anchor_id,
                title=run.title,
                agent_id=anchor_agent_id,
                labels=_anchor_labels(run),
            )
            store.create_conversation(
                conversation_id=step_session_id,
                kind="sub_agent",
                title="Implement",
                parent_conversation_id=anchor_id,
            )
            _publish_gate(world, run.id)
            _publish_step_prompt(store, step_session_id)
            anchor_row, pending = read_anchor(store, anchor_id)
        finally:
            for session_id in (anchor_id, step_session_id):
                for event in pending_elicitations.snapshot_for(session_id):
                    pending_elicitations.resolve(session_id, event["elicitation_id"])
            if conversations is None:
                evict_cached_engine(scratch_uri)
    runs = world.runs
    assert isinstance(runs, FakeRunStore)
    open_alerts = [
        alert
        for alert in runs.list_alerts(run.id, workspace_id=WORKSPACE)
        if alert.status == int(AlertStatus.OPEN)
    ]
    # Both are normal priority, so the feed lists the newest (the pause) first.
    page = WorkflowInboxPage(
        data=[
            alert_item(alert)
            for alert in sorted(open_alerts, key=lambda alert: alert.created_at, reverse=True)
        ],
        next_cursor=None,
    )
    contract = {
        "inbox_page": page.model_dump(mode="json"),
        "anchor_row": anchor_row,
        "pending_elicitations": pending,
    }
    # As the wire carries it: tuples become lists.
    return json.loads(json.dumps(contract))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build the workflow Inbox contract fixture.")
    parser.add_argument("--write", action="store_true", help="rewrite the checked-in file")
    args = parser.parse_args(argv)
    contract = build_contract()
    if args.write:
        text = json.dumps(contract, indent=2, ensure_ascii=False) + "\n"
        CONTRACT_PATH.write_text(text, encoding="utf-8")
        return 0
    if json.loads(CONTRACT_PATH.read_text(encoding="utf-8")) != contract:
        print(f"{CONTRACT_PATH} is out of date; rerun with --write", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
