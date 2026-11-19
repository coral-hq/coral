"""A gate end to end through the real server with authentication off.

The ticket's acceptance criterion as the single local user sees it: one prompt on
the run's anchor and one workflow Inbox item; a restart that loses the prompt
keeps the item and shows the same prompt again; the anchor, even labelled closed,
takes one answer that advances the run, a repeat is a duplicate, the gate's alert
clears itself and the run's end is marked read away. Header and accounts
authentication: ``test_gate_routes_*``.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest

from coral.db.enum_codecs import RunStatus
from coral.omni.server import coral_lifespan
from omnigent.runtime import pending_elicitations
from omnigent.server import elicitation_hooks
from omnigent.util.session_lifecycle import CLOSED_LABEL_KEY, CLOSED_LABEL_VALUE
from tests._helpers.polling import poll_until_async
from tests.budgets import budget
from tests.coral.omni._gate_server import (
    CORAL_SERVER_PLUGIN,
    CoralServer,
    ack,
    coral_server,
    gate_answers,
    gate_run,
    inbox,
    pending_here,
    pending_prompts,
    prompt_shown,
    resolve_gate,
    run_status,
)


@pytest.fixture
def server(db_uri: str, tmp_path: Path) -> Iterator[CoralServer]:
    yield coral_server(db_uri, tmp_path, server_plugins=[CORAL_SERVER_PLUGIN])
    # Prompts and the verdict handler outlive a lifespan in this process's registries.
    pending_elicitations.reset_for_tests()
    elicitation_hooks.reset_for_tests()


def _item(alert: dict[str, Any]) -> dict[str, Any]:
    """The fields of a feed item that say what it is and how to act on it."""
    fields = ("kind", "priority", "run_id", "elicitation_id", "session_id", "actions", "outcomes")
    return {field: alert[field] for field in fields}


async def test_a_gate_shows_once_survives_a_restart_and_resolves_once(
    server: CoralServer,
) -> None:
    world, run, anchor, prompt = gate_run(server.db_uri)
    transport = httpx.ASGITransport(app=server.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        async with coral_lifespan(server.app, server.services):
            await poll_until_async(
                lambda: prompt_shown(server, anchor, prompt), timeout_s=budget(30)
            )
            before = await pending_prompts(client, anchor)
            feed = await inbox(client)
        # The process died before anyone answered: its prompts went with it.
        pending_elicitations.reset_for_tests()
        lost = await pending_prompts(client, anchor)

        async with coral_lifespan(server.app, server.services):
            await poll_until_async(lambda: pending_here(anchor, prompt), timeout_s=budget(30))
            after = await pending_prompts(client, anchor)
            feed_after_restart = await inbox(client)
            # Only a store can close the anchor; a closed anchor still answers its gates.
            server.services.conversation_store.set_labels(
                anchor, {CLOSED_LABEL_KEY: CLOSED_LABEL_VALUE}
            )
            first = await resolve_gate(client, anchor, prompt)
            repeat = await resolve_gate(client, anchor, prompt)
            answered = await pending_prompts(client, anchor)
            [ended] = await inbox(client)
            marked = await ack(client, ended["alert_id"])
            feed_at_end = await inbox(client)

    [shown] = before
    assert (shown["elicitation_id"], shown["params"]["coral"]["run_id"]) == (prompt, run.id)
    assert [_item(alert) for alert in feed] == [
        {
            "kind": "gate",
            "priority": "normal",
            "run_id": run.id,
            "elicitation_id": prompt,
            "session_id": anchor,
            "actions": ["answer", "open_run"],
            "outcomes": ["approve", "reject"],
        }
    ]
    # The alert is durable; the prompt is republished with the same id and params.
    assert (lost, after, feed_after_restart) == ([], before, feed)
    assert (first.status_code, first.json()) == (202, {"queued": False})
    assert (repeat.status_code, repeat.json()) == (202, {"queued": False, "duplicate": True})
    assert [(answer.label, answer.by) for answer in gate_answers(world, run.id)] == [
        ("approve", "local")
    ]
    assert (answered, run_status(world, run)) == ([], int(RunStatus.COMPLETED))
    # The gate's alert resolved with the answer; the run's end is the one item left.
    assert _item(ended) == {
        "kind": "run_completed",
        "priority": "low",
        "run_id": run.id,
        "elicitation_id": None,
        "session_id": None,
        "actions": ["open_run", "mark_read"],
        "outcomes": [],
    }
    assert (marked.status_code, feed_at_end) == (204, [])
