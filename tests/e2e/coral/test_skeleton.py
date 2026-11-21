"""The walking skeleton: the review-loop workflow on a real server, host, runners and CLI.

A subprocess server with the Coral plugin, a host daemon that launches each step's
runner and the real ``claude`` CLI run "Implement with review loop" on a temporary git
repository. Every model call is scripted on this test's own mock gateway. Each step's
first call is held until its brief arrives, so the test reads the activation id the
engine chose instead of predicting it.
"""

from __future__ import annotations

import json
import subprocess
import time
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from tests.e2e.conftest import configure_mock_llm, get_mock_message_requests, release_mock_gate
from tests.e2e.coral import _skeleton as sk
from tests.e2e.coral._claude_sdk_kit import tool_results

# Absolute deadline for the whole scenario, below the marker's limit.
SCENARIO_S = 200
# Everything the run may log: no pause, drift, nudge or refused call.
EXPECTED_LOG_KINDS = {
    "engine.start_run",
    "engine.effect_completed",
    "engine.handoff_received",
    "engine.handoff_evaluated",
    "engine.answer_gate",
}
GREP = {"command": "grep -q 'hello coral' greeting.txt"}
CAT = {"command": "cat greeting.txt"}
DONE = {"text": "Handed off."}


def _queue(mock: str, token: str, responses: list[dict[str, Any]]) -> None:
    """Replace the step's queue; only the step sessions' own calls may draw from it."""
    configure_mock_llm(mock, responses, match=token, required_tools=[sk.HANDOFF_TOOL])


def _held(response: dict[str, Any]) -> dict[str, Any]:
    return {**response, "block": True}


def _result_texts(mock: str, call_id: str) -> list[str]:
    """The distinct texts of the tool result the CLI sent back for one scripted call."""
    texts = []
    for raw in tool_results(get_mock_message_requests(mock), call_id=call_id):
        content = json.loads(raw).get("content")
        if isinstance(content, list):
            content = "".join(
                block.get("text", "") for block in content if isinstance(block, dict)
            )
        texts.append(str(content))
    return list(dict.fromkeys(texts))


def _item_texts(items: list[dict[str, Any]]) -> list[str]:
    """The text of each user message among a session's items."""
    return [
        block["text"]
        for item in items
        if item.get("type") == "message" and item.get("role") == "user"
        for block in item.get("content") or []
        if isinstance(block, dict) and isinstance(block.get("text"), str)
    ]


@pytest.mark.timeout(300, method="signal")
def test_the_review_loop_runs_end_to_end_on_a_real_stack(
    tmp_path: Path, isolated_mock_llm_server_url: str
) -> None:
    sk.require_claude_cli()
    mock = isolated_mock_llm_server_url
    uid = uuid.uuid4().hex[:12]
    impl_token = f"impl-{uid}"
    # Longer, so a reviewer call that also quotes the implementer's token routes here.
    review_token = f"review-{uid}-pass"
    write, early, done, denied = (f"{name}-{uid}" for name in ("write", "early", "done", "deny"))
    _queue(
        mock,
        impl_token,
        [
            _held(
                sk.tool_call(
                    sk.WRITE_TOOL,
                    {"path": "greeting.txt", "content": "hello coral\n"},
                    call_id=write,
                )
            )
        ],
    )
    _queue(
        mock,
        review_token,
        [
            _held(
                sk.tool_call(sk.WRITE_TOOL, {"path": "owned.txt", "content": "x"}, call_id=denied)
            )
        ],
    )
    host_config = {"auth": {"type": "api_key", "api_key": "mock-key", "base_url": mock}}
    deadline = time.monotonic() + SCENARIO_S

    with sk.skeleton_stack(tmp_path / "stack", mock_url=mock, host_config=host_config) as stack:
        client = stack.client
        workflow_id = sk.save_workflow(
            client, sk.review_loop_yaml(impl_token=impl_token, review_token=review_token)
        )
        run_id = sk.start_run(
            client,
            workflow_id=workflow_id,
            host_id=stack.host.host_id,
            repo=stack.repo,
            start_key=f"skeleton-{uid}",
        )["run_id"]

        def wait(probe: Callable[[], Any], what: str) -> Any:
            return sk.wait_for(probe, deadline=deadline, what=what, skeleton=stack, run_id=run_id)

        def held_activation(token: str, number: int) -> str:
            """The activation of the step's ``number``-th brief, once its first call is held."""

            def found() -> str | None:
                ledger = get_mock_message_requests(mock)
                mine = [brief for brief in sk.briefs(ledger) if token in brief]
                if len(mine) >= number and sk.mock_holds_a_call(mock):
                    return sk.activation_from_brief(mine[number - 1])
                return None

            return wait(found, f"brief {number} with {token}")

        # Implement, pass 1: a handoff before the check is refused, then accepted after it.
        implement_1 = held_activation(impl_token, 1)
        _queue(
            mock,
            impl_token,
            [
                sk.handoff_call(implement_1, call_id=early, report="Wrote greeting.txt."),
                sk.tool_call(sk.SHELL_TOOL, GREP, call_id=f"grep-{uid}"),
                sk.handoff_call(implement_1, call_id=done, report="Checked greeting.txt."),
                DONE,
                # The next pass's first call, held until its brief is read.
                _held(sk.tool_call(sk.SHELL_TOOL, GREP, call_id=f"grep2-{uid}")),
            ],
        )
        release_mock_gate(mock)

        # Review, pass 1: the write was denied; the reviewer asks for one more pass.
        review_1 = held_activation(review_token, 1)
        _queue(
            mock,
            review_token,
            [
                sk.tool_call(sk.SHELL_TOOL, CAT, call_id=f"cat-{uid}"),
                sk.handoff_call(
                    review_1,
                    call_id=f"changes-{uid}",
                    report="Asked for one more pass.",
                    label="changes_requested",
                ),
                DONE,
                _held(sk.tool_call(sk.SHELL_TOOL, CAT, call_id=f"cat2-{uid}")),
            ],
        )
        release_mock_gate(mock)

        # Implement, pass 2, then review, pass 2 approves.
        implement_2 = held_activation(impl_token, 2)
        _queue(
            mock,
            impl_token,
            [sk.handoff_call(implement_2, call_id=f"done2-{uid}", report="Checked again."), DONE],
        )
        release_mock_gate(mock)
        review_2 = held_activation(review_token, 2)
        _queue(
            mock,
            review_token,
            [
                sk.handoff_call(
                    review_2, call_id=f"approved-{uid}", report="Looks right.", label="approved"
                ),
                DONE,
            ],
        )
        release_mock_gate(mock)

        # The gate: an outcome it does not offer is refused, then approve ends the run.
        visit = wait(lambda: (sk.detail(client, run_id)["gates"] or [None])[0], "the gate visit")
        anchor = sk.detail(client, run_id)["anchor_session_id"]

        def prompt() -> dict[str, Any] | None:
            pending = client.get(f"/v1/sessions/{anchor}").json().get("pending_elicitations")
            return (pending or [None])[0]

        resolve = (
            f"/v1/sessions/{anchor}/elicitations/"
            f"{wait(prompt, 'the prompt on the anchor')['elicitation_id']}/resolve"
        )
        refused = client.post(resolve, json={"action": "accept", "content": {"decision": "maybe"}})
        waiting = sk.detail(client, run_id)
        answered = client.post(
            resolve, json={"action": "accept", "content": {"decision": "approve"}}
        )

        def finished() -> dict[str, Any] | None:
            found = sk.detail(client, run_id)
            return found if found["status"] in {"completed", "failed", "cancelled"} else None

        run = wait(finished, "the run to finish")
        sessions = sk.coral_sessions(client, run_id)
        steps = [session for session in sessions if session["labels"]["coral.role"] == "step"]
        briefed = {
            session["id"]: [
                text
                for text in _item_texts(
                    client.get(
                        f"/v1/sessions/{session['id']}/items", params={"limit": 1000}
                    ).json()["data"]
                )
                if "Coral step brief." in text
            ]
            for session in steps
        }
        log = client.get(f"{sk.RUNS}/{run_id}/log", params={"limit": 100}).json()
        outcome = client.get(f"{sk.RUNS}/{run_id}/outcome").json()
        logs = "\n".join(path.read_text(errors="replace") for path in stack.root.rglob("*.log"))
        worktree = Path(run["target"]["worktree_path"])
        reviewer_wrote = (worktree / "owned.txt").exists()
        checkout = subprocess.run(
            ["sh", "-c", outcome["checkout"]["command"]],
            capture_output=True,
            text=True,
            check=False,
            env={**sk.minimal_env(), "HOME": str(stack.root)},
        )
        greeting = (stack.repo / "greeting.txt").read_text() if checkout.returncode == 0 else None

    assert (run["status"], run["causes"]) == ("completed", []), run
    # One evidence rejection, then the same activation's handoff is accepted.
    [rejected] = _result_texts(mock, early)
    [accepted] = _result_texts(mock, done)
    assert '"accepted": false' in rejected and '"reason": "evidence.missing"' in rejected, rejected
    assert '"accepted": true' in accepted, accepted
    # The reviewer's write is denied and leaves the worktree unchanged.
    [denial] = _result_texts(mock, denied)
    assert "report-only" in denial, denial
    assert not reviewer_wrote
    # The loop ran once: two passes of each step, each its own activation.
    assert len({implement_1, implement_2, review_1, review_2}) == 4
    # An outcome the gate does not offer is refused and the run keeps waiting at it.
    assert refused.status_code == 409, refused.text
    assert refused.json()["error"]["message"].startswith("[invalid_answer]"), refused.text
    assert (waiting["status"], waiting["causes"]) == ("running", []), waiting
    assert [gate["visit_id"] for gate in waiting["gates"]] == [visit["visit_id"]]
    assert answered.status_code == 202, answered.text
    # One anchor, and one step session per slot activation, each briefed once.
    assert sorted(session["labels"]["coral.role"] for session in sessions) == [
        "run",
        *["step"] * 4,
    ]
    assert sorted(session["labels"]["coral.node_id"] for session in steps) == [
        "implement",
        "implement",
        "review",
        "review",
    ]
    assert all(len(texts) == 1 for texts in briefed.values()), briefed
    assert log["next_after_seq"] is None
    assert {entry["kind"] for entry in log["data"]} <= EXPECTED_LOG_KINDS, log["data"]
    assert "sending it a '" not in logs
    # The outcome's checkout command puts the change in the repository's checkout.
    assert outcome["branch"] == run["run_branch"]
    assert checkout.returncode == 0, checkout.stderr
    assert greeting == "hello coral\n"
