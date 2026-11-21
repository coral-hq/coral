"""The checked-in run-view contract is what the run stream and the routes send for one run."""

from __future__ import annotations

import copy
import shlex
from collections.abc import Sequence
from typing import Any

import pytest

from coral.db.enum_codecs import RunPauseReason
from coral.gates.ids import GATE_ELICITATION_ID
from tests.coral.api._stream_client import DONE, StreamClient
from tests.coral.api.run_view_contract import (
    CONTRACT_PATH,
    EVIDENCE_COMMAND,
    HEAD_COMMIT,
    MILESTONES,
    REPO_PATH,
    REPORTS,
    SentEvent,
    build_contract,
    checked_in,
    wire_event,
    worktree_path,
)
from tests.coral.bridge._gates import (
    CHANGE_TOKEN,
    CHANGE_TOKEN_AGAIN,
    IMPLEMENT_AGAIN,
    IMPLEMENT_FIRST,
)

RUNNING = {
    "status": "running",
    "pause_reason": None,
    "finished_at": None,
    "allowed_actions": ["pause", "cancel"],
    "load_error": None,
}
View = dict[str, Any]
Header = dict[str, Any]


@pytest.fixture(scope="module")
def contract() -> dict[str, Any]:
    return checked_in(CONTRACT_PATH)


def _fold(events: Sequence[SentEvent], client: StreamClient | None = None) -> StreamClient:
    """``events`` taken as sent; the client fails on a gap, a repeat or a header going back."""
    folded = client if client is not None else StreamClient()
    for event in events:
        folded.take(wire_event(event))
    return folded


def _shown(events: Sequence[SentEvent]) -> dict[int, tuple[View, Header]]:
    """The view and header a client shows once it has taken every frame up to each seq."""
    client = StreamClient()
    shown: dict[int, tuple[View, Header]] = {}
    for event in events:
        seq = None if event["id"] is None else int(event["id"])
        if seq is not None and client.last_seq is not None and seq > client.last_seq:
            assert client.view is not None and client.header is not None
            shown[client.last_seq] = (client.view, client.header)
        client.take(wire_event(event))
    assert client.last_seq is not None and client.view is not None and client.header is not None
    shown[client.last_seq] = (client.view, client.header)
    return shown


def _activations(view: View) -> dict[str, tuple[str, str | None]]:
    return {item["id"]: (item["status"], item["outcome"]) for item in view["activations"]}


def _slots(view: View) -> dict[str, str]:
    return {slot["id"]: slot["status"] for slot in view["slots"]}


def _pass(view: View) -> int:
    (loop,) = view["loop_pass_indexes"]
    assert loop["back_arrow_id"] == "a4"
    return loop["pass_index"]


def _without_version(header: Header) -> Header:
    return {key: value for key, value in header.items() if key != "version"}


def test_the_checked_in_contract_equals_what_the_backend_records(
    contract: dict[str, Any],
) -> None:
    # On a mismatch: uv run --no-sync python -m tests.coral.api.run_view_contract --write
    assert contract == build_contract()


def test_the_live_tail_folds_to_the_final_view_with_every_seq_once(
    contract: dict[str, Any],
) -> None:
    live, head = contract["live"], contract["final_detail"]["head_seq"]

    client = _fold(live)
    final = _fold(contract["final_snapshot"])

    assert "".join(wire_event(event) for event in live) == contract["live_raw"]
    kinds = client.kinds()
    assert (kinds[0], kinds[-1]) == ("snapshot", DONE)
    assert kinds.count("snapshot") == kinds.count(DONE) == 1
    assert not {"resync", "heartbeat"} & set(kinds)
    snapshot_seq = client.events[0].id
    assert snapshot_seq is not None
    assert client.entries == list(range(snapshot_seq + 1, head + 1))
    versions = [event.data["version"] for event in client.of_kind("run")]
    assert versions == sorted(set(versions))
    assert final.kinds() == ["snapshot", DONE] and final.last_seq == head
    assert client.view == final.view == contract["final_detail"]["view"]
    assert client.header == final.header


def test_the_live_tail_shows_each_milestone_in_order_with_run_frames_among_the_entries(
    contract: dict[str, Any],
) -> None:
    marks = contract["live_marks"]
    shown = _shown(contract["live"])

    assert list(marks) == list(MILESTONES)
    # Each step lands its own rows; the approve's row also ends the run.
    steps = [marks[name] for name in MILESTONES[:-1]]
    assert steps == sorted(set(steps)) and marks["gate2_answered"] == marks["finished"]

    view, header = shown[marks["implement_running"]]
    assert _without_version(header) == RUNNING
    assert _activations(view)["implement||a4:1"] == ("running", None)
    assert _slots(view) == {IMPLEMENT_FIRST: "working"}
    assert (view["open_gates"], _pass(view)) == ([], 1)

    # An open gate while the run is running: the run view's "Needs you".
    view, header = shown[marks["gate1_open"]]
    assert _without_version(header) == RUNNING
    assert _activations(view)["implement||a4:1"] == ("closed", "completed")
    assert _activations(view)["approve_change||a4:1"] == ("running", None)
    assert view["open_gates"] == [CHANGE_TOKEN]

    view, header = shown[marks["gate1_answered"]]
    assert _activations(view)["approve_change||a4:1"] == ("closed", "completed")
    assert (view["open_gates"], _pass(view)) == ([], 2)

    view, header = shown[marks["pass2_running"]]
    assert _activations(view)["implement||a4:2"] == ("running", None)
    assert _slots(view)[IMPLEMENT_AGAIN] == "working"

    view, header = shown[marks["gate2_open"]]
    assert _without_version(header) == RUNNING
    assert view["open_gates"] == [CHANGE_TOKEN_AGAIN] and _pass(view) == 2

    # Paused with the gate still open: the pause, not "Needs you", is what the view shows.
    view, header = shown[marks["paused"]]
    assert _without_version(header) == {
        **RUNNING,
        "status": "paused",
        "pause_reason": "user",
        "allowed_actions": ["resume", "cancel"],
    }
    assert view["status"] == "paused" and [cause["reason"] for cause in view["causes"]] == ["user"]
    assert view["open_gates"] == [CHANGE_TOKEN_AGAIN]

    view, header = shown[marks["resumed"]]
    assert _without_version(header) == RUNNING
    assert (view["status"], view["causes"], view["open_gates"]) == (
        "running",
        [],
        [CHANGE_TOKEN_AGAIN],
    )

    view, header = shown[marks["finished"]]
    assert header["status"] == "completed" and header["allowed_actions"] == []
    assert header["finished_at"] is not None
    assert view["status"] == "completed" and view["open_gates"] == []
    assert all(status == "closed" for status, _outcome in _activations(view).values())

    # The pause's and the resume's headers arrive right after their own entries.
    order = [
        (event["event"], event["id"]) for event in contract["live"] if event["event"] != "snapshot"
    ]
    paused, resumed = str(marks["paused"]), str(marks["resumed"])
    assert order[order.index(("entry", paused)) + 1] == ("run", None)
    assert order[order.index(("entry", resumed)) + 1] == ("run", None)
    assert order[-2:] == [("run", None), (None, None)]


def test_a_replay_from_the_first_gate_opens_with_the_finished_header_then_every_later_entry(
    contract: dict[str, Any],
) -> None:
    resume_after, head = contract["resume_after"], contract["final_detail"]["head_seq"]
    held, _header = _shown(contract["live"])[resume_after]

    client = _fold(
        contract["resumed"], StreamClient(view=copy.deepcopy(held), last_seq=resume_after)
    )

    assert resume_after == contract["live_marks"]["gate1_open"]
    assert client.kinds() == ["run", *["entry"] * (head - resume_after), DONE]
    opening = client.events[0].data
    assert (opening["status"], opening["allowed_actions"]) == ("completed", [])
    assert client.entries == list(range(resume_after + 1, head + 1))
    # The same entries the live tail sent after that seq, each once.
    later = [
        event
        for event in contract["live"]
        if event["event"] == "entry" and int(event["id"] or 0) > resume_after
    ]
    assert [event for event in contract["resumed"] if event["event"] == "entry"] == later
    assert client.view == _fold(contract["final_snapshot"]).view


def test_each_detail_holds_its_open_gate_with_context_and_the_slots_by_engine_slot_id(
    contract: dict[str, Any],
) -> None:
    marks, shown = contract["live_marks"], _shown(contract["live"])
    (implement,) = (node for node in contract["graph"]["nodes"] if node["id"] == "implement")

    assert [item["run"] for item in implement["evidence"]["items"]] == [EVIDENCE_COMMAND]
    gates = (
        ("detail_gate_pass1", "gate1_open", CHANGE_TOKEN, [IMPLEMENT_FIRST]),
        (
            "detail_gate_pass2",
            "gate2_open",
            CHANGE_TOKEN_AGAIN,
            [IMPLEMENT_FIRST, IMPLEMENT_AGAIN],
        ),
    )
    for visit_no, (key, mark, token, slot_ids) in enumerate(gates, start=1):
        detail = contract[key]
        (gate,) = detail["gates"]
        assert (gate["node_id"], gate["token"], gate["visit_no"]) == (
            "approve_change",
            token,
            visit_no,
        )
        assert gate["outcomes"] == ["approve", "reject"]
        assert GATE_ELICITATION_ID.fullmatch(gate["elicitation_id"])
        assert "Approve the change?" in gate["context"]
        assert REPORTS[visit_no - 1] in gate["context"]
        assert [slot["engine_slot_id"] for slot in detail["slots"]] == slot_ids
        assert all(slot["session_id"] for slot in detail["slots"])
        # The detail read at the gate shows what the live tail shows there.
        assert (detail["status"], detail["head_seq"]) == ("running", marks[mark])
        assert detail["view"] == shown[marks[mark]][0]
        assert detail["spend"]["usd"] is not None
    final = contract["final_detail"]
    assert (final["status"], final["gates"]) == ("completed", [])
    assert [slot["status"] for slot in final["slots"]] == ["closed", "closed"]


def test_the_outcome_checks_out_the_run_branch_by_its_full_ref(contract: dict[str, Any]) -> None:
    outcome, detail = contract["outcome"], contract["final_detail"]
    branch = detail["run_branch"]

    assert outcome["branch"] == branch == detail["target"]["run_branch"]
    assert shlex.split(outcome["checkout"]["command"]) == [
        "git",
        "-C",
        REPO_PATH,
        "checkout",
        "--detach",
        f"refs/heads/{branch}",
    ]
    assert shlex.split(outcome["checkout"]["worktree_command"]) == [
        "cd",
        worktree_path(detail["run_id"]),
    ]
    assert (outcome["status"], outcome["diff_unavailable"]) == ("completed", None)
    assert outcome["head_commit"] == outcome["diff"]["to_commit"] == HEAD_COMMIT
    assert outcome["diff"]["paths"] == [
        "docs/release\\u{202E}notes.md",
        "src/parser.py",
        "tests/test_parser.py",
    ]


def test_the_pause_copy_covers_every_pause_reason_but_a_users_own(
    contract: dict[str, Any],
) -> None:
    messages = contract["pause_messages"]

    assert set(messages["by_reason"]) == {reason.name.lower() for reason in RunPauseReason} - {
        "user"
    }
    assert messages["unknown"] == "The run paused."
