"""A step's runner lost on a real stack: killed, its host gone, or its step retried.

The review loop runs on a subprocess server with the Coral plugin, a real host daemon,
host-launched runners and the real ``claude`` CLI, with every model call scripted on
the test's own mock gateway. Each fault is the test's own: the runner's process group
SIGKILLed, the host daemon SIGKILLed and started again on the same home and identity,
and a blocked step retried through the runs API. Each fault is taken only once the
runner's process tree, its CLI included, has been found; the test then waits until the
runner's group and every process of that tree have ended before the mock answers a call
the lost CLI made.
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import time
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx
import psutil
import pytest
import yaml

from coral.db.enum_codecs import WorkStatus
from tests.e2e.conftest import get_mock_message_requests, release_mock_gate
from tests.e2e.coral import _skeleton as sk

# Absolute deadline for a scenario, below the marker's limit.
SCENARIO_S = 200
# The host outage adds the reconnect grace and up to a minute before the first sighting.
HOLD_SCENARIO_S = 240
SHORT_LEASE_S = 10
# The shortest grace the server takes, so the offline host is held soon after its loss.
HOLD_GRACE_S = 30
GREETING = {"path": "greeting.txt", "content": "hello coral\n"}
RETRIED_GREETING = {"path": "greeting.txt", "content": "hello coral\nfrom the retry\n"}
DRAFT = {"path": "draft.txt", "content": "an unfinished draft\n"}
GREP = {"command": "grep -q 'hello coral' greeting.txt"}
CAT = {"command": "cat greeting.txt"}
DONE = {"text": "Handed off."}
# A lost runner's group and every process below it end within this.
TREE_ENDS_S = 30
BRIEF = "Coral step brief."
# The re-prompt a relaunched step gets.
RELAUNCH_NUDGE = "Your runner stopped and Coral restarted it."
# The paragraph only a retried step's new brief carries, before its salvage ref.
SALVAGE_PARAGRAPH = "Coral restarted this step from its last handoff."
SALVAGE_REFS = "refs/coral/salvage/"
HOST_OFFLINE = ("infra", "infra.host_offline")
RESTARTING = ("infra", "recovery.restarting")
BLOCKED = ("failure_path", "blocked")
# What a review loop logs with no pause, drift, nudge or refused call.
BASE_LOG_KINDS = {
    "engine.start_run",
    "engine.effect_completed",
    "engine.handoff_received",
    "engine.handoff_evaluated",
    "engine.answer_gate",
}
# A lost runner is a failed session when the server saw it go, else the liveness pass's.
LOSS_KINDS = {"engine.session_failed", "engine.runner_lost"}
HOLD_KINDS = {"engine.runner_held", "engine.runner_hold_ended"}


def _activation_calls(ledger: list[dict[str, Any]], activation_id: str) -> list[dict[str, Any]]:
    """The model calls of every session briefed for the activation."""
    return sk.calls_carrying(ledger, f"Activation id: {activation_id}\n")


def _slot(run: dict[str, Any], activation_id: str) -> dict[str, Any]:
    """The detail's slot of the activation its brief names (``<activation>:<index>``)."""
    [found] = [
        slot for slot in run["slots"] if slot["engine_slot_id"].rsplit(":", 1)[0] == activation_id
    ]
    return found


def _brief_with(mock: str, marker: str) -> Callable[[], str | None]:
    """A probe: the first brief carrying ``marker``, once that session's first call is held."""

    def probe() -> str | None:
        found = [
            brief
            for brief in sk.briefs(sk.calls_carrying(get_mock_message_requests(mock), marker))
            if marker in brief
        ]
        return found[0] if found and sk.mock_holds_a_call(mock) else None

    return probe


def _causes(run: dict[str, Any]) -> list[tuple[str, str]]:
    return [(cause["reason"], cause["detail"]) for cause in run["causes"]]


def _paused_for(client: httpx.Client, run_id: str, cause: tuple[str, str]) -> Callable[[], Any]:
    """A probe: the run's detail once it is paused for ``cause``."""

    def probe() -> dict[str, Any] | None:
        run = sk.detail(client, run_id)
        return run if run["status"] == "paused" and cause in _causes(run) else None

    return probe


def _running(client: httpx.Client, run_id: str) -> Callable[[], Any]:
    def probe() -> dict[str, Any] | None:
        run = sk.detail(client, run_id)
        return run if run["status"] == "running" else None

    return probe


def _relaunched(client: httpx.Client, session_id: str, lost: str) -> Callable[[], str | None]:
    """A probe: the session's runner id once a runner other than ``lost`` is connected."""

    def probe() -> str | None:
        found = sk.session(client, session_id)
        runner = found["runner_id"]
        return runner if found["runner_online"] and runner not in {None, lost} else None

    return probe


def _calls_held(mock: str, activation_id: str, count: int) -> Callable[[], bool | None]:
    def probe() -> bool | None:
        calls = _activation_calls(get_mock_message_requests(mock), activation_id)
        return True if len(calls) == count and sk.mock_holds_a_call(mock) else None

    return probe


def _approve_gate(client: httpx.Client, run_id: str, wait: sk.Wait) -> httpx.Response:
    """Answer the open gate through the runs API once its prompt is posted."""
    gate = wait(
        lambda: next(
            (gate for gate in sk.detail(client, run_id)["gates"] if gate["elicitation_id"]), None
        ),
        "the gate's prompt",
    )
    return client.post(
        f"{sk.RUNS}/{run_id}/gates/{gate['node_id']}:answer",
        json={"visit_token": gate["token"], "outcome": "approve"},
    )


def _review_approves(wait: sk.Wait, mock: str, review_token: str, number: int, uid: str) -> str:
    """The reviewer's ``number``-th pass approves at once; returns its activation."""
    review = sk.held_activation(wait, mock, review_token, number)
    sk.queue(
        mock,
        review_token,
        [
            sk.handoff_call(
                review, call_id=f"ok-{number}-{uid}", report="Looks right.", label="approved"
            ),
            DONE,
        ],
    )
    release_mock_gate(mock)
    return review


def _step_nodes(sessions: list[dict[str, Any]]) -> list[str]:
    """The node of each step session of the run, sorted."""
    return sorted(
        session["labels"]["coral.node_id"]
        for session in sessions
        if session["labels"]["coral.role"] == "step"
    )


def _wakes(stack: sk.Skeleton, run_id: str) -> list[sk.WorkItem]:
    return [item for item in sk.work_items(stack, run_id) if item.effect_type == "recovery.wake"]


def _runner_tree(pid: int) -> list[psutil.Process]:
    """
    The runner's process tree, once it is shown to be the step's own: the runner leads a
    group other than this test's, beside its harness, with the step's CLI below them.
    """
    tree = sk.group_tree(pid)
    assert pid != os.getpgrp() and len(sk.group_members(pid)) >= 2, sk.argvs(tree)
    assert sk.claude_clis(tree), sk.argvs(tree)
    return tree


def _tree_ended(
    stack: sk.Skeleton,
    run_id: str,
    pid: int,
    tree: list[psutil.Process],
    *,
    deadline: float,
    ends_on: frozenset[str],
) -> None:
    """Wait until the runner's group and every process of its tree taken before have ended."""
    sk.wait_for(
        lambda: sk.group_tree_ended(pid, tree) or None,
        deadline=min(deadline, time.monotonic() + TREE_ENDS_S),
        what=f"runner {pid}'s group and process tree to end",
        skeleton=stack,
        run_id=run_id,
        ends_on=ends_on,
    )


def _losses(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The run-log entries that recorded a lost runner: each emitted one ``runner_lost``."""
    return [
        entry
        for entry in entries
        if any(
            effect["kind"] == "runner_lost" for effect in (entry["body"] or {}).get("effects", [])
        )
    ]


def _git(repo: Path, *argv: str) -> str:
    done = subprocess.run(
        ["git", "-C", str(repo), *argv],
        capture_output=True,
        text=True,
        check=True,
        env={**sk.minimal_env(), "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"},
    )
    return done.stdout


def _logs(stack: sk.Skeleton) -> str:
    return "\n".join(path.read_text(errors="replace") for path in stack.root.rglob("*.log"))


@pytest.mark.timeout(300, method="signal")
def test_a_killed_step_runner_is_relaunched_in_the_same_session(
    tmp_path: Path, isolated_mock_llm_server_url: str
) -> None:
    sk.require_claude_cli()
    mock = isolated_mock_llm_server_url
    uid = uuid.uuid4().hex[:12]
    impl_token = f"impl-{uid}"
    review_token = f"review-{uid}-pass"
    handed = f"handoff-{uid}"
    sk.queue(
        mock, impl_token, [sk.held(sk.tool_call(sk.WRITE_TOOL, GREETING, call_id=f"w-{uid}"))]
    )
    sk.queue(mock, review_token, [sk.held(sk.tool_call(sk.SHELL_TOOL, CAT, call_id=f"c-{uid}"))])
    began = time.monotonic()
    deadline = began + SCENARIO_S
    seen: dict[str, float] = {}

    with sk.skeleton_stack(
        tmp_path / "stack", mock_url=mock, host_config=sk.mock_auth(mock), lease_s=SHORT_LEASE_S
    ) as stack:
        client = stack.client
        run_id = sk.start_review_loop(
            stack, impl_token=impl_token, review_token=review_token, start_key=f"kill-{uid}"
        )
        wait = sk.waiter(stack, run_id, deadline)

        # The write goes through; the next call is held while the runner is killed.
        implement = sk.held_activation(wait, mock, impl_token, 1)
        sk.queue(
            mock,
            impl_token,
            [
                sk.held(sk.tool_call(sk.SHELL_TOOL, GREP, call_id=f"lost-{uid}")),
                sk.tool_call(sk.SHELL_TOOL, GREP, call_id=f"grep-{uid}"),
                sk.handoff_call(implement, call_id=handed, report="Checked greeting.txt."),
                DONE,
            ],
        )
        release_mock_gate(mock)
        wait(_calls_held(mock, implement, 2), "the implementer's second call")
        slot_before = _slot(sk.detail(client, run_id), implement)
        implementer = slot_before["session_id"]
        lost = sk.session(client, implementer)["runner_id"]
        pid = sk.runner_pid(stack, implementer)
        tree = _runner_tree(pid)
        seen.update(in_group=len(sk.group_members(pid)), in_tree=len(tree))
        calls_at_kill = len(_activation_calls(get_mock_message_requests(mock), implement))
        kinds_at_kill = sk.log_kinds(client, run_id)

        os.killpg(pid, signal.SIGKILL)
        killed = time.monotonic()
        _tree_ended(stack, run_id, pid, tree, deadline=deadline, ends_on=sk.STOPPED)
        seen["tree_ended"] = time.monotonic() - killed
        # The lost call's answer now reaches no process of the killed runner.
        release_mock_gate(mock)
        relaunched = wait(_relaunched(client, implementer, lost), "the relaunched runner")
        seen["relaunched"] = time.monotonic() - killed

        _review_approves(wait, mock, review_token, 1, uid)
        seen["handed_off"] = time.monotonic() - killed
        answered = _approve_gate(client, run_id, wait)
        run = wait(lambda: sk.finished(client, run_id), "the run to finish")
        ledger = get_mock_message_requests(mock)
        entries = sk.log_entries(client, run_id)
        wakes = _wakes(stack, run_id)
        texts = sk.session_user_texts(client, implementer)
        binding = sk.binding_generation(stack, implementer)
        sessions = sk.coral_sessions(client, run_id)
        logs = _logs(stack)
    seen["total"] = time.monotonic() - began
    print("Runner kill, seconds after the kill:", json.dumps(seen))

    assert (run["status"], run["causes"]) == ("completed", []), run
    assert not set(kinds_at_kill) & LOSS_KINDS, kinds_at_kill
    # One loss of that runner, seen by the server as it went, one wake that relaunched
    # it, and the run never paused.
    kinds = [entry["kind"] for entry in entries]
    assert set(kinds) <= BASE_LOG_KINDS | LOSS_KINDS, kinds
    [loss] = _losses(entries)
    assert [entry for entry in entries if entry["kind"] in LOSS_KINDS] == [loss], kinds
    assert loss["kind"] == "engine.session_failed", loss
    assert loss["body"]["receipt_key"].startswith(f"runner:{implementer}:1:{lost}:"), loss
    assert [(wake.status, (wake.result or {}).get("outcome")) for wake in wakes] == [
        (int(WorkStatus.SUCCEEDED), "relaunched")
    ], wakes
    # The same session and generation, with a new runner.
    slot_after = _slot(run, implement)
    assert slot_after["session_id"] == implementer
    assert slot_before["session_generation"] == slot_after["session_generation"] == 1
    assert binding == 1
    assert relaunched != lost
    assert _step_nodes(sessions) == ["implement", "review"], sessions
    # The brief and one re-prompt are the session's only messages: no second turn began.
    assert len(texts) == 2 and BRIEF in texts[0] and RELAUNCH_NUDGE in texts[1], texts
    # Every call after the kill is the relaunched turn's.
    calls = _activation_calls(ledger, implement)
    assert calls[calls_at_kill:], "the relaunched turn made no model call"
    assert calls[calls_at_kill:] == sk.calls_carrying(ledger, RELAUNCH_NUDGE)
    # Its handoff went through the new runner and was accepted; no event-guard refusal.
    [accepted] = sk.result_texts(mock, handed)
    assert '"accepted": true' in accepted, accepted
    assert "sending it a '" not in logs
    assert answered.status_code == 200, answered.text


@pytest.mark.timeout(300, method="signal")
def test_an_offline_host_holds_the_step_and_its_return_relaunches_it(
    tmp_path: Path, isolated_mock_llm_server_url: str
) -> None:
    sk.require_claude_cli()
    mock = isolated_mock_llm_server_url
    uid = uuid.uuid4().hex[:12]
    impl_token = f"impl-{uid}"
    review_token = f"review-{uid}-pass"
    handed = f"handoff-{uid}"
    sk.queue(
        mock, impl_token, [sk.held(sk.tool_call(sk.WRITE_TOOL, GREETING, call_id=f"w-{uid}"))]
    )
    sk.queue(mock, review_token, [sk.held(sk.tool_call(sk.SHELL_TOOL, CAT, call_id=f"c-{uid}"))])
    began = time.monotonic()
    deadline = began + HOLD_SCENARIO_S
    seen: dict[str, float] = {}

    with sk.skeleton_stack(
        tmp_path / "stack",
        mock_url=mock,
        host_config=sk.mock_auth(mock),
        lease_s=SHORT_LEASE_S,
        grace_s=HOLD_GRACE_S,
    ) as stack:
        client = stack.client
        server_config = yaml.safe_load((stack.root / "server.yaml").read_text())
        run_id = sk.start_review_loop(
            stack, impl_token=impl_token, review_token=review_token, start_key=f"host-{uid}"
        )
        wait = sk.waiter(stack, run_id, deadline)
        # While the host is away the run is paused, which must not end these waits.
        outage_wait = sk.waiter(stack, run_id, deadline, ends_on=sk.FAILED)

        implement = sk.held_activation(wait, mock, impl_token, 1)
        sk.queue(
            mock,
            impl_token,
            [
                sk.held(sk.tool_call(sk.SHELL_TOOL, GREP, call_id=f"lost-{uid}")),
                sk.tool_call(sk.SHELL_TOOL, GREP, call_id=f"grep-{uid}"),
                sk.handoff_call(implement, call_id=handed, report="Checked greeting.txt."),
                DONE,
            ],
        )
        release_mock_gate(mock)
        wait(_calls_held(mock, implement, 2), "the implementer's second call")
        slot = _slot(sk.detail(client, run_id), implement)
        implementer = slot["session_id"]
        lost = sk.session(client, implementer)["runner_id"]
        pid = sk.runner_pid(stack, implementer)
        tree = _runner_tree(pid)
        seen.update(in_group=len(sk.group_members(pid)), in_tree=len(tree))
        host_id = stack.host.host_id
        calls_at_kill = len(_activation_calls(get_mock_message_requests(mock), implement))

        # The host dies outright; its runner ends its own group when it sees that.
        stack.host.proc.kill()
        stack.host.proc.wait(timeout=10)
        killed = time.monotonic()
        _tree_ended(stack, run_id, pid, tree, deadline=deadline, ends_on=sk.FAILED)
        seen["tree_ended"] = time.monotonic() - killed
        held = outage_wait(_paused_for(client, run_id, HOST_OFFLINE), "the host-offline hold")
        seen["held"] = time.monotonic() - killed
        resumed = client.post(f"{sk.RUNS}/{run_id}:resume", json={})
        retried = client.post(
            f"{sk.RUNS}/{run_id}/activations/{slot['activation_id']}:retry", json={}
        )
        kinds_while_held = sk.log_kinds(client, run_id)

        sk.respawn_host(stack)
        seen["host_back"] = time.monotonic() - killed
        relaunched = outage_wait(_relaunched(client, implementer, lost), "the relaunched runner")
        seen["relaunched"] = time.monotonic() - killed
        # Only now is the call the lost CLI waited on answered, to no one.
        release_mock_gate(mock)
        outage_wait(_running(client, run_id), "the hold to end")
        seen["hold_ended"] = time.monotonic() - killed

        _review_approves(wait, mock, review_token, 1, uid)
        seen["handed_off"] = time.monotonic() - killed
        answered = _approve_gate(client, run_id, wait)
        run = wait(lambda: sk.finished(client, run_id), "the run to finish")
        ledger = get_mock_message_requests(mock)
        entries = sk.log_entries(client, run_id)
        wakes = _wakes(stack, run_id)
        texts = sk.session_user_texts(client, implementer)
        sessions = sk.coral_sessions(client, run_id)
        hosts = client.get("/v1/hosts").json()["hosts"]
        logs = _logs(stack)
    seen["total"] = time.monotonic() - began
    print("Host outage, seconds after the host's kill:", json.dumps(seen))

    assert server_config["coral_runner_reconnect_grace_s"] == HOLD_GRACE_S, server_config
    # Held: paused for the offline host, Cancel only, neither Resume nor Retry.
    assert held["pause_reason"] == "infra", held
    assert held["causes"] == [
        {"reason": HOST_OFFLINE[0], "detail": HOST_OFFLINE[1], "subject": slot["engine_slot_id"]}
    ], held["causes"]
    assert held["allowed_actions"] == ["cancel"], held["allowed_actions"]
    assert held["retry_activation_ids"] == [], held["retry_activation_ids"]
    assert resumed.status_code == 409, resumed.text
    assert resumed.json()["error"]["details"]["reason"] == "resume_not_allowed", resumed.text
    assert retried.status_code == 409, retried.text
    assert retried.json()["error"]["details"]["reason"] == "host_offline_hold", retried.text
    assert kinds_while_held.count("engine.runner_held") == 1, kinds_while_held
    # The host came back as itself, and its return relaunched the same session.
    assert [(row["host_id"], row["status"]) for row in hosts] == [(host_id, "online")], hosts
    assert relaunched != lost
    assert _slot(run, implement)["session_id"] == implementer
    assert _slot(run, implement)["session_generation"] == 1
    assert _step_nodes(sessions) == ["implement", "review"], sessions
    # One loss for the whole outage, one wake (held, then relaunched), one hold. The
    # server holds the turn without an edge while the host is away, so the liveness pass
    # finds the loss; the server's own later report of that runner adds none.
    assert (run["status"], run["causes"]) == ("completed", []), run
    kinds = [entry["kind"] for entry in entries]
    assert set(kinds) <= BASE_LOG_KINDS | LOSS_KINDS | HOLD_KINDS, kinds
    [loss] = _losses(entries)
    assert loss["kind"] == "engine.runner_lost", loss
    assert loss["body"]["receipt_key"].startswith(f"runner:{implementer}:1:{lost}:"), loss
    assert kinds.count("engine.runner_held") == kinds.count("engine.runner_hold_ended") == 1
    assert [(wake.status, (wake.result or {}).get("outcome")) for wake in wakes] == [
        (int(WorkStatus.SUCCEEDED), "relaunched")
    ], wakes
    # The brief and one re-prompt only; after the host's kill only the relaunched turn
    # called the model.
    assert len(texts) == 2 and BRIEF in texts[0] and RELAUNCH_NUDGE in texts[1], texts
    calls = _activation_calls(ledger, implement)
    assert calls[calls_at_kill:], "the relaunched turn made no model call"
    assert calls[calls_at_kill:] == sk.calls_carrying(ledger, RELAUNCH_NUDGE)
    [accepted] = sk.result_texts(mock, handed)
    assert '"accepted": true' in accepted, accepted
    assert "sending it a '" not in logs
    assert answered.status_code == 200, answered.text


@pytest.mark.timeout(300, method="signal")
def test_retrying_a_blocked_step_fences_salvages_resets_and_briefs_a_new_session(
    tmp_path: Path, isolated_mock_llm_server_url: str
) -> None:
    sk.require_claude_cli()
    mock = isolated_mock_llm_server_url
    uid = uuid.uuid4().hex[:12]
    impl_token = f"impl-{uid}"
    review_token = f"review-{uid}-pass"
    blocked_call = f"blocked-{uid}"
    sk.queue(
        mock, impl_token, [sk.held(sk.tool_call(sk.WRITE_TOOL, GREETING, call_id=f"w-{uid}"))]
    )
    sk.queue(mock, review_token, [sk.held(sk.tool_call(sk.SHELL_TOOL, CAT, call_id=f"c-{uid}"))])
    deadline = time.monotonic() + SCENARIO_S

    with sk.skeleton_stack(
        tmp_path / "stack", mock_url=mock, host_config=sk.mock_auth(mock), lease_s=SHORT_LEASE_S
    ) as stack:
        client = stack.client
        run_id = sk.start_review_loop(
            stack, impl_token=impl_token, review_token=review_token, start_key=f"retry-{uid}"
        )
        wait = sk.waiter(stack, run_id, deadline)
        paused_wait = sk.waiter(stack, run_id, deadline, ends_on=sk.FAILED)

        # Implement, pass 1, commits greeting.txt; review, pass 1, asks for another pass.
        implement_1 = sk.held_activation(wait, mock, impl_token, 1)
        sk.queue(
            mock,
            impl_token,
            [
                sk.tool_call(sk.SHELL_TOOL, GREP, call_id=f"grep-{uid}"),
                sk.handoff_call(implement_1, call_id=f"done-{uid}", report="Wrote greeting.txt."),
                DONE,
                # The next pass's first call, held until its brief is read.
                sk.held(sk.tool_call(sk.WRITE_TOOL, DRAFT, call_id=f"draft-{uid}")),
            ],
        )
        release_mock_gate(mock)
        review_1 = sk.held_activation(wait, mock, review_token, 1)
        sk.queue(
            mock,
            review_token,
            [
                sk.handoff_call(
                    review_1, call_id=f"more-{uid}", report="One more.", label="changes_requested"
                ),
                DONE,
                sk.held(sk.tool_call(sk.SHELL_TOOL, CAT, call_id=f"c2-{uid}")),
            ],
        )
        release_mock_gate(mock)

        # Implement, pass 2, generation 1: writes a draft, then reports itself blocked.
        implement_2 = sk.held_activation(wait, mock, impl_token, 2)
        sk.queue(
            mock,
            impl_token,
            [
                sk.handoff_call(
                    implement_2,
                    call_id=blocked_call,
                    report="Started a draft.",
                    status="blocked",
                    blocked_reason="The draft needs a decision.",
                ),
                DONE,
            ],
        )
        # Generation 2's calls carry the salvage paragraph, so only they draw from here.
        sk.queue(
            mock,
            SALVAGE_PARAGRAPH,
            [
                sk.held(sk.tool_call(sk.WRITE_TOOL, RETRIED_GREETING, call_id=f"w2-{uid}")),
                sk.tool_call(sk.SHELL_TOOL, GREP, call_id=f"grep2-{uid}"),
                sk.handoff_call(implement_2, call_id=f"done2-{uid}", report="Wrote it again."),
                DONE,
            ],
        )
        release_mock_gate(mock)
        blocked = wait(_paused_for(client, run_id, BLOCKED), "the blocked pause")
        # The pause is committed before the handoff's reply, so generation 1 has one call left.
        paused_wait(lambda: sk.result_texts(mock, blocked_call) or None, "session 1's last call")
        first = _slot(blocked, implement_2)
        session_1 = first["session_id"]
        pid_1 = sk.runner_pid(stack, session_1)
        tree_1 = _runner_tree(pid_1)
        worktree = Path(blocked["target"]["worktree_path"])
        drafted = (worktree / "draft.txt").read_text()
        head_before = _git(stack.repo, "rev-parse", blocked["run_branch"]).strip()

        # Retry: the run stays paused restarting until the old session is fenced and reset.
        retry_at = len(get_mock_message_requests(mock))
        retry = client.post(
            f"{sk.RUNS}/{run_id}/activations/{blocked['retry_activation_ids'][0]}:retry", json={}
        )
        restarting = sk.detail(client, run_id)
        samples: list[tuple[bool, int]] = []

        def restart_finished() -> dict[str, Any] | None:
            # The run first, then the row: a run running again means its restart had finished.
            run = sk.detail(client, run_id)
            [restart] = [
                item
                for item in sk.work_items(stack, run_id)
                if item.effect_type == "recovery.restart"
            ]
            paused = run["status"] == "paused" and _causes(run) == [RESTARTING]
            samples.append((paused, restart.status))
            done = restart.status == int(WorkStatus.SUCCEEDED)
            assert paused or done, (run["status"], run["causes"], restart)
            return {"run": run, "restart": restart} if done and not paused else None

        restarted = paused_wait(restart_finished, "the restart to finish")
        session_1_after = sk.session(client, session_1)
        # The host ends the group before it answers the fence's stop.
        group_1_after = sk.group_members(pid_1)
        _tree_ended(stack, run_id, pid_1, tree_1, deadline=deadline, ends_on=sk.FAILED)

        # Generation 2 is briefed with the salvage ref; its first call is held.
        brief_2 = paused_wait(_brief_with(mock, SALVAGE_PARAGRAPH), "generation 2's brief")
        second = _slot(sk.detail(client, run_id), implement_2)
        session_2 = second["session_id"]
        bindings = (
            sk.binding_generation(stack, session_1),
            sk.binding_generation(stack, session_2),
        )
        salvage_refs = _git(
            stack.repo, "for-each-ref", "--format=%(refname)", SALVAGE_REFS
        ).split()
        salvaged = {
            ref: _git(stack.repo, "ls-tree", "-r", "--name-only", ref).split()
            for ref in salvage_refs
        }
        salvaged_draft = _git(stack.repo, "show", f"{salvage_refs[0]}:draft.txt")
        salvage_parent = _git(stack.repo, "rev-parse", f"{salvage_refs[0]}^").strip()
        reset_clean = not (worktree / "draft.txt").exists()
        release_mock_gate(mock)

        review_2 = _review_approves(wait, mock, review_token, 2, uid)
        answered = _approve_gate(client, run_id, wait)
        run = wait(lambda: sk.finished(client, run_id), "the run to finish")
        ledger = get_mock_message_requests(mock)
        kinds = sk.log_kinds(client, run_id)
        texts_2 = sk.session_user_texts(client, session_2)
        sessions = sk.coral_sessions(client, run_id)
        branch_files = _git(stack.repo, "ls-tree", "-r", "--name-only", run["run_branch"]).split()
        greeting = _git(stack.repo, "show", f"{run['run_branch']}:greeting.txt")

    # Blocked: Cancel only, with the blocked step as the one step to retry.
    assert blocked["pause_reason"] == "failure_path", blocked
    assert _causes(blocked) == [BLOCKED], blocked["causes"]
    assert blocked["allowed_actions"] == ["cancel"], blocked["allowed_actions"]
    assert blocked["retry_activation_ids"] == [first["activation_id"]], blocked
    assert drafted == DRAFT["content"]
    # The retry is taken, and the run stays paused restarting until the restart finished.
    assert retry.status_code == 200, retry.text
    assert retry.headers["cache-control"] == "private, no-store"
    assert (retry.json()["status"], retry.json()["pause_reason"]) == ("paused", "infra")
    assert _causes(restarting) == [RESTARTING], restarting["causes"]
    assert restarting["allowed_actions"] == ["cancel"], restarting["allowed_actions"]
    assert restarting["retry_activation_ids"] == [], restarting["retry_activation_ids"]
    assert samples[0][0], samples
    # The fence closed session 1 and ended its runner's group, then its whole tree.
    assert session_1_after["labels"].get("omnigent.closed") == "true", session_1_after["labels"]
    assert group_1_after == [], group_1_after
    # Its uncommitted draft was salvaged on top of pass 1's commit, then reset away.
    result = restarted["restart"].result or {}
    assert len(salvage_refs) == 1, salvage_refs
    assert "draft.txt" in salvaged[salvage_refs[0]], salvaged
    assert salvaged_draft == DRAFT["content"]
    assert result.get("salvage_ref") == salvage_refs[0], result
    # The expected head was pass 1's commit, not the reviewer's close in between.
    assert salvage_parent == head_before
    assert result.get("head_verified") is True, result
    assert reset_clean
    # Generation 2: a new session, bound at generation 2, briefed with the salvage ref.
    assert (first["session_generation"], second["session_generation"]) == (1, 2)
    assert session_2 not in {None, session_1}
    assert bindings == (1, 2), bindings
    assert salvage_refs[0] in brief_2 and SALVAGE_PARAGRAPH in brief_2, brief_2
    assert sum(BRIEF in text for text in texts_2) == 1, texts_2
    # No call from generation 1 after the retry: only generation 2 and the reviewer's pass 2.
    after_retry = sk.agent_requests(ledger[retry_at:])
    retried_calls = _activation_calls(after_retry, implement_2)
    reviewed_calls = _activation_calls(after_retry, review_2)
    assert retried_calls, "generation 2 made no model call"
    assert retried_calls == sk.calls_carrying(after_retry, SALVAGE_PARAGRAPH)
    assert [call for call in after_retry if call not in retried_calls + reviewed_calls] == []
    # The run completes with generation 2's work and without the draft.
    assert (run["status"], run["causes"]) == ("completed", []), run
    assert answered.status_code == 200, answered.text
    assert set(kinds) <= BASE_LOG_KINDS | {"engine.retry_step"}, kinds
    assert kinds.count("engine.retry_step") == 1, kinds
    assert "greeting.txt" in branch_files and "draft.txt" not in branch_files, branch_files
    assert greeting == RETRIED_GREETING["content"]
    assert _step_nodes(sessions) == [*["implement"] * 3, *["review"] * 2], sessions
