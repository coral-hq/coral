"""Status edges become turn facts. This test does not boot a server."""

from __future__ import annotations

import subprocess
import sys

from coral.engine.facts import TurnSnapshot
from coral.engine.turn_end import evaluate
from coral.omni.server.observers import observe_status_edge
from coral.signals.nudge import decide


def _completed(**overrides: object) -> TurnSnapshot:
    payload: dict[str, object] = {
        "live_status": "idle",
        "engine_stable_id_present": True,
        "newest_substantive_item_is_assistant": True,
        "turn_outcome": "completed",
        "saw_response_completed": True,
        "background_tasks": 0,
        "pending_elicitation_count": 0,
        "engine_pending_input": False,
        "origin": "engine",
        "engine_started": True,
    }
    payload.update(overrides)
    return TurnSnapshot(**payload)


def test_unbound_edge_returns_none() -> None:
    assert observe_status_edge({}) is None
    assert observe_status_edge({"session_id": ""}) is None
    assert observe_status_edge({"session_id": None}) is None
    assert observe_status_edge({"status": "idle"}) is None


def test_idle_without_turn_outcome_is_not_completed() -> None:
    edge = {
        "session_id": "sess-1",
        "slot_id": "work||:0",
        "status": "idle",
        "origin": "engine",
        "previous_status": {"raw": True},
        "observed_at_ms": "not-a-timestamp",
    }
    fact = observe_status_edge(edge)
    assert fact is not None
    assert fact.live_status == "idle"
    assert fact.turn_outcome is None
    assert fact.slot_id == "work||:0"
    assert fact.session_id == "sess-1"
    filled = fact.model_copy(
        update={
            "engine_stable_id_present": True,
            "newest_substantive_item_is_assistant": True,
            "saw_response_completed": False,
            "background_tasks": 0,
            "pending_elicitation_count": 0,
            "engine_pending_input": False,
            "engine_started": True,
        }
    )
    assert evaluate(filled) != "completed"
    assert decide(filled, "working", fact_key="turn:sess-1") is False


def test_observer_copies_present_fields_and_keeps_no_memory() -> None:
    edge = {
        "session_id": "sess-1",
        "status": "idle",
        "turn_outcome": "failed",
        "failure_origin": "runner_disconnected",
        "origin": "nightly-archive",
        "previous_status": "working",
        "observed_at_ms": 1_700_000_000_000,
        "slot_id": "",
    }
    first = observe_status_edge(edge)
    second = observe_status_edge(edge)
    assert first == second
    assert first is not second
    assert first is not None
    assert first.live_status == "idle"
    assert first.turn_outcome == "failed"
    assert first.failure_origin == "runner_disconnected"
    assert first.origin == "archive"
    assert first.slot_id == ""
    assert observe_status_edge({"session_id": "sess-1"}).origin is None
    assert observe_status_edge({"session_id": "sess-1", "origin": "engine"}).origin == "engine"
    assert observe_status_edge({"session_id": "sess-1", "origin": "user"}).origin == "user"
    assert observe_status_edge({"session_id": "sess-1", "slot_id": 3}).slot_id == ""


def test_user_and_archive_origins_do_not_nudge() -> None:
    key = "turn:sess-1"
    assert decide(_completed(origin="user"), "working", fact_key=key) is False
    assert decide(_completed(origin="archive"), "working", fact_key=key) is False
    assert decide(_completed(), "working", fact_key=key) is True
    assert decide(_completed(), "working", fact_key=key) is True
    assert decide(_completed(), "working", fact_key=key, seen=frozenset({key})) is False
    assert decide(_completed(), "closing", fact_key=key) is False
    assert decide(_completed(), "closed", fact_key=key) is False
    assert decide(_completed(), "working", fact_key=key, taken_over=True) is False
    assert decide(_completed(turn_outcome="cancelled"), "working", fact_key=key) is False
    assert decide(_completed(engine_started=False), "working", fact_key=key) is False


def test_signal_modules_import_before_the_engine_package() -> None:
    modules = ("coral.signals.facts", "coral.signals.nudge", "coral.signals.outcomes")
    for module in modules:
        result = subprocess.run(
            [sys.executable, "-c", f"import {module}"],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, result.stdout + result.stderr


def test_signal_packages_do_not_import_omnigent() -> None:
    code = (
        "import sys\n"
        "import coral.engine\n"
        "import coral.signals\n"
        "import coral.omni.server.observers\n"
        "bad = sorted(\n"
        "    name for name in sys.modules\n"
        "    if name == 'omnigent' or name.startswith('omnigent.')\n"
        ")\n"
        "print(bad)\n"
        "sys.exit(1 if bad else 0)\n"
    )
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
