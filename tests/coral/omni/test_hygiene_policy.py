"""``deny_vendor_ask`` and how the Coral server plugin registers Coral's policy handlers."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest

from coral.omni.policies import guards, hygiene
from coral.omni.policies.hygiene import deny_vendor_ask
from omnigent.policies.registry import is_registered_handler, load_registry
from omnigent.process_logging import DATA_DIR_ENV_VAR
from omnigent.server.server_plugins import load_server_plugins


def _tool_call(name: str) -> dict[str, object]:
    return {"type": "tool_call", "target": name, "data": {"name": name, "arguments": {}}}


def test_denies_the_vendor_question_tool_and_allows_file_reads() -> None:
    assert deny_vendor_ask(_tool_call("AskUserQuestion"))["result"] == "DENY"
    assert deny_vendor_ask(_tool_call("sys_os_read")) == {"result": "ALLOW"}
    assert deny_vendor_ask({"type": "response", "data": "AskUserQuestion"}) == {"result": "ALLOW"}


@pytest.fixture
def restore_registry() -> Iterator[None]:
    yield
    load_registry()


@pytest.mark.usefixtures("restore_registry")
def test_plugin_registers_every_coral_policy_handler(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(DATA_DIR_ENV_VAR, str(tmp_path))
    services = cast(Any, SimpleNamespace(host_sharded=False, server_config={}, auth_provider=None))
    load_registry()
    # Generated bundles name these handlers, and materialize accepts only registered ones.
    handlers = [
        str(entry["handler"]) for entry in (*hygiene.POLICY_REGISTRY, *guards.POLICY_REGISTRY)
    ]
    assert "coral.omni.policies.hygiene.deny_vendor_ask" in handlers
    assert not any(is_registered_handler(handler) for handler in handlers)

    (registration,) = load_server_plugins(["coral.omni.server.plugin"], services)
    load_registry(extra_modules=list(registration.policy_modules))

    assert all(is_registered_handler(handler) for handler in handlers), handlers
