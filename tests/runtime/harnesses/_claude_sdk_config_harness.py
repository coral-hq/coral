"""CORAL(S124): the real claude-sdk harness app, with routes that report its config safely.

Spawned through the process manager to show where a direct-exec harness keeps its key: its
executor's config (reported by digest), not its environment (reported by name). It never
builds a real executor or serves a turn.
"""

from __future__ import annotations

import hashlib
import os
from collections.abc import Callable
from typing import Any
from unittest.mock import patch

from fastapi import FastAPI

from omnigent.inner import claude_sdk_harness

_REPORTED_CONFIG = ("api_key_helper", "gateway_auth_command")


def create_app() -> FastAPI:
    """Build the claude-sdk app, keeping the executor factory it hands its adapter."""
    factories: list[Callable[[], Any]] = []
    real_adapter = claude_sdk_harness.ExecutorAdapter

    def recording_adapter(*, executor_factory: Callable[[], Any], **kwargs: Any) -> Any:
        factories.append(executor_factory)
        return real_adapter(executor_factory=executor_factory, **kwargs)

    with patch.object(claude_sdk_harness, "ExecutorAdapter", recording_adapter):
        app = claude_sdk_harness.create_app()

    @app.get("/executor-config")
    async def executor_config() -> dict[str, str | None]:
        """Digests of the key-bearing values the executor would be built with."""
        built: dict[str, Any] = {}
        with patch.object(
            claude_sdk_harness.ClaudeSDKExecutor, "__init__", lambda self, **kw: built.update(kw)
        ):
            factories[0]()
        return {
            name: hashlib.sha256(built[name].encode()).hexdigest() if built[name] else None
            for name in _REPORTED_CONFIG
        }

    @app.get("/environ-names")
    async def environ_names() -> list[str]:
        """The names in this process's ``os.environ`` after boot."""
        return sorted(os.environ)

    return app
