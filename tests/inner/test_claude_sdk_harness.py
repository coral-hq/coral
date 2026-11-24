"""
Tests for the ``harness: claude-sdk`` wrap shape.

Does NOT exercise the real Claude SDK (no API key needed). Verifies:

- The wrap module exports :func:`create_app` and the registry
  resolves ``"claude-sdk"`` to it.
- ``create_app()`` returns a FastAPI app with the harness API
  subset routes wired up.
- The wrap reads its env-var config at executor construction
  time — verified by inspecting the lazy factory's behavior
  with mocked ``ClaudeSDKExecutor``.

End-to-end claude-sdk verification (real CLI, real API) lives in
the e2e suite and requires API keys.
"""

from __future__ import annotations

import hashlib  # CORAL(S118)
import json  # CORAL(S118)
import os  # CORAL(S118)
import secrets  # CORAL(S118)
import shlex  # CORAL(S118)
import socket  # CORAL(S118)
import sys  # CORAL(S118)
from collections.abc import Callable  # CORAL(S118)
from pathlib import Path  # CORAL(S118)
from typing import Any
from unittest.mock import patch

import pytest

from omnigent.inner import claude_sdk_harness
from omnigent.runner.launch_secrets import (  # CORAL(S118)
    CLAUDE_SDK_HARNESS_LAUNCH_SECRET_ENV_VARS,
    HARNESS_LAUNCH_FD_ENV_VAR,
    LAUNCH_SECRETS_EXIT_CODE,
    launch_secrets_pipe,
)
from omnigent.runtime.harnesses import _HARNESS_MODULES
from tests._helpers.polling import poll_until_async  # CORAL(S118)


def test_harness_module_registered_in_module_registry() -> None:
    """``"claude-sdk"`` resolves to the harness module path.

    Without this entry, the runner subprocess can't find the wrap
    when AP-side tries to spawn it.
    """
    assert _HARNESS_MODULES.get("claude-sdk") == "omnigent.inner.claude_sdk_harness"
    assert _HARNESS_MODULES.get("claude") == "omnigent.inner.claude_sdk_harness"


def test_create_app_returns_fastapi_with_required_routes(
    fake_environ: dict[str, str],  # CORAL(S118): create_app() pops config from os.environ
) -> None:
    """``create_app()`` returns a FastAPI app exposing the harness API.

    Verifies the wrap successfully:
    - Imports the executor adapter + Claude SDK executor.
    - Builds the FastAPI app via ExecutorAdapter.build().
    - Mounts the standard harness routes.

    The actual ClaudeSDKExecutor is constructed lazily on the
    first turn (not at app build time), so this test passes
    without a real ``claude`` CLI on PATH.
    """
    app = claude_sdk_harness.create_app()
    paths = {route.path for route in app.routes}  # type: ignore[attr-defined]
    # Session-keyed harness API: liveness probe + single
    # discriminated-event endpoint per §The Harness API Subset.
    assert "/health" in paths
    assert "/v1/sessions/{conversation_id}/events" in paths


def test_executor_factory_reads_env_vars(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Factory passes env-var values through to ClaudeSDKExecutor.

    Locks in the v1 config-flow contract: env vars set in AP's
    process before spawning the subprocess (which inherits
    them) are how the wrap learns its config. Verifies model,
    databricks, profile, cwd, permission mode all thread
    through.
    """
    monkeypatch.setenv("HARNESS_CLAUDE_SDK_MODEL", "test-model-id")
    monkeypatch.setenv("HARNESS_CLAUDE_SDK_GATEWAY", "true")
    monkeypatch.setenv("HARNESS_CLAUDE_SDK_DATABRICKS_PROFILE", "test-profile")
    monkeypatch.setenv("HARNESS_CLAUDE_SDK_GATEWAY_HOST", "https://example.databricks.com")
    monkeypatch.setenv(
        "HARNESS_CLAUDE_SDK_GATEWAY_BASE_URL",
        "https://example.databricks.com/ai-gateway/anthropic",
    )
    monkeypatch.setenv("HARNESS_CLAUDE_SDK_GATEWAY_AUTH_COMMAND", "printf token")
    monkeypatch.setenv("HARNESS_CLAUDE_SDK_GATEWAY_AUTH_REFRESH_INTERVAL_MS", "900000")
    monkeypatch.setenv("HARNESS_CLAUDE_SDK_CWD", "/tmp/test-cwd")
    monkeypatch.setenv("HARNESS_CLAUDE_SDK_PERMISSION_MODE", "acceptEdits")
    monkeypatch.setenv("HARNESS_CLAUDE_SDK_SYSTEM_PROMPT_PRESET", "claude_code")

    captured: dict[str, Any] = {}

    def _fake_init(
        self: Any,
        *,
        cwd: str | None,
        os_env: Any,
        model: str | None,
        permission_mode: str,
        system_prompt_preset: str | None,
        gateway: bool,
        databricks_profile: str | None,
        gateway_host: str | None,
        base_url_override: str | None,
        gateway_auth_command: str | None,
        gateway_auth_refresh_interval_ms: str | None,
        **_kwargs: Any,
    ) -> None:
        captured["cwd"] = cwd
        captured["os_env"] = os_env
        captured["model"] = model
        captured["permission_mode"] = permission_mode
        captured["system_prompt_preset"] = system_prompt_preset
        captured["gateway"] = gateway
        captured["databricks_profile"] = databricks_profile
        captured["gateway_host"] = gateway_host
        captured["base_url_override"] = base_url_override
        captured["gateway_auth_command"] = gateway_auth_command
        captured["gateway_auth_refresh_interval_ms"] = gateway_auth_refresh_interval_ms

    with patch(
        "omnigent.inner.claude_sdk_harness.ClaudeSDKExecutor.__init__",
        _fake_init,
    ):
        claude_sdk_harness._build_claude_sdk_executor()

    # Each env var threaded through to the corresponding
    # constructor kwarg.
    assert captured["model"] == "test-model-id"
    assert captured["gateway"] is True
    assert captured["databricks_profile"] == "test-profile"
    assert captured["gateway_host"] == "https://example.databricks.com"
    assert captured["base_url_override"] == "https://example.databricks.com/ai-gateway/anthropic"
    assert captured["gateway_auth_command"] == "printf token"
    assert captured["gateway_auth_refresh_interval_ms"] == "900000"
    assert captured["cwd"] == "/tmp/test-cwd"
    assert captured["permission_mode"] == "acceptEdits"
    assert captured["system_prompt_preset"] == "claude_code"
    # When ``HARNESS_CLAUDE_SDK_OS_ENV`` is unset (this test
    # doesn't set it), the wrap defaults to ``caller_process +
    # sandbox=none`` so the SDK exposes its native tools to the
    # LLM. A regression that flipped this back to ``None`` would
    # silently disable Bash/Read/Edit/Write/Glob/Grep — the
    # whole point of step 5g's os_env threading. The check is
    # on the discriminating fields rather than identity so a
    # future tightening (different default sandbox, etc.) is a
    # one-line update.
    os_env_value = captured["os_env"]
    assert os_env_value is not None
    assert os_env_value.type == "caller_process"
    assert os_env_value.sandbox is not None
    assert os_env_value.sandbox.type == "none"


def test_executor_factory_cwd_falls_back_to_runner_workspace(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With no ``HARNESS_CLAUDE_SDK_CWD``, the factory falls back to the
    runner's ``OMNIGENT_RUNNER_WORKSPACE`` (the folder the user launched
    in, and what the tmux terminal uses) rather than leaving cwd unset —
    which let the SDK root the CLI at the daemon's ``$HOME``. Mirrors the
    kimi / pi / hermes harnesses.
    """
    monkeypatch.delenv("HARNESS_CLAUDE_SDK_CWD", raising=False)
    monkeypatch.setenv("OMNIGENT_RUNNER_WORKSPACE", "/home/bobby/code/agents")

    captured: dict[str, Any] = {}

    def _fake_init(self: Any, *, cwd: str | None, **_kwargs: Any) -> None:
        captured["cwd"] = cwd

    with patch(
        "omnigent.inner.claude_sdk_harness.ClaudeSDKExecutor.__init__",
        _fake_init,
    ):
        claude_sdk_harness._build_claude_sdk_executor()

    assert captured["cwd"] == "/home/bobby/code/agents"


def test_executor_factory_explicit_cwd_wins_over_workspace(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An explicit ``HARNESS_CLAUDE_SDK_CWD`` takes precedence over the
    ``OMNIGENT_RUNNER_WORKSPACE`` fallback."""
    monkeypatch.setenv("HARNESS_CLAUDE_SDK_CWD", "/tmp/explicit")
    monkeypatch.setenv("OMNIGENT_RUNNER_WORKSPACE", "/home/bobby/code/agents")

    captured: dict[str, Any] = {}

    def _fake_init(self: Any, *, cwd: str | None, **_kwargs: Any) -> None:
        captured["cwd"] = cwd

    with patch(
        "omnigent.inner.claude_sdk_harness.ClaudeSDKExecutor.__init__",
        _fake_init,
    ):
        claude_sdk_harness._build_claude_sdk_executor()

    assert captured["cwd"] == "/tmp/explicit"


def test_executor_factory_decodes_os_env_json(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``HARNESS_CLAUDE_SDK_OS_ENV`` decodes into the inner OSEnvSpec.

    Omnigent serializes ``spec.executor.config["os_env"]`` via
    :func:`dataclasses.asdict` and JSON-encodes the result; the
    wrap must reconstruct an :class:`OSEnvSpec` (with nested
    sandbox spec) so :class:`ClaudeSDKExecutor` sees the same
    config a non-AP mode invocation would. Verifies the round-
    trip on a non-default payload — type, cwd, sandbox.type, and
    a sandbox boolean field all flow through.
    """
    import json

    monkeypatch.setenv(
        "HARNESS_CLAUDE_SDK_OS_ENV",
        json.dumps(
            {
                "type": "caller_process",
                "cwd": "/tmp/projected-cwd",
                "sandbox": {
                    "type": "linux_bwrap",
                    "read_paths": ["/srv/data"],
                    "write_paths": None,
                    "write_files": None,
                    # Non-default to prove every sandbox field
                    # round-trips, not just ``type``.
                    "allow_network": False,
                },
                "fork": False,
            }
        ),
    )

    captured: dict[str, Any] = {}

    def _fake_init(
        self: Any,
        *,
        cwd: str | None,
        os_env: Any,
        model: str | None,
        permission_mode: str,
        gateway: bool,
        databricks_profile: str | None,
        **_kwargs: Any,
    ) -> None:
        captured["os_env"] = os_env

    with patch(
        "omnigent.inner.claude_sdk_harness.ClaudeSDKExecutor.__init__",
        _fake_init,
    ):
        claude_sdk_harness._build_claude_sdk_executor()

    os_env_value = captured["os_env"]
    assert os_env_value is not None
    # The ``cwd`` field carries the spec-author's choice. A
    # regression that dropped it would silently route the SDK
    # to the wrong working directory.
    assert os_env_value.cwd == "/tmp/projected-cwd"
    assert os_env_value.sandbox is not None
    assert os_env_value.sandbox.type == "linux_bwrap"
    # ``allow_network=False`` flowed through; a regression that
    # ignored sandbox-specific fields would leave it at the
    # default ``True``.
    assert os_env_value.sandbox.allow_network is False
    assert os_env_value.sandbox.read_paths == ["/srv/data"]


def test_executor_factory_falls_back_on_malformed_os_env_json(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Malformed ``HARNESS_CLAUDE_SDK_OS_ENV`` falls back to default.

    A malformed payload should NOT crash the wrap — that would
    bring the whole subprocess down on first turn. The wrap
    instead logs a warning and defaults to the parity-preserving
    ``caller_process + sandbox=none`` so the agent still starts
    and the SDK natives stay enabled. Without this fallback a
    bad serialization on AP's side (or an env var hand-tweaked
    by an operator) could silently lobotomize the agent.
    """
    monkeypatch.setenv("HARNESS_CLAUDE_SDK_OS_ENV", "{this-is-not-json")
    captured: dict[str, Any] = {}

    def _fake_init(
        self: Any,
        *,
        cwd: str | None,
        os_env: Any,
        model: str | None,
        permission_mode: str,
        gateway: bool,
        databricks_profile: str | None,
        **_kwargs: Any,
    ) -> None:
        captured["os_env"] = os_env

    with patch(
        "omnigent.inner.claude_sdk_harness.ClaudeSDKExecutor.__init__",
        _fake_init,
    ):
        claude_sdk_harness._build_claude_sdk_executor()

    # Default kicks in: caller_process + sandbox=none. If the
    # wrap raised on bad JSON instead, the test (and the live
    # agent) would never see this assertion — the harness
    # subprocess would have crashed at first turn.
    os_env_value = captured["os_env"]
    assert os_env_value is not None
    assert os_env_value.type == "caller_process"
    assert os_env_value.sandbox is not None
    assert os_env_value.sandbox.type == "none"


@pytest.mark.parametrize(
    "raw_value,expected",
    [
        ("1", True),
        ("true", True),
        ("True", True),
        ("yes", True),
        ("0", False),
        ("false", False),
        ("", False),
        ("anything else", False),
    ],
)
def test_databricks_env_var_truthy_parsing(
    raw_value: str,
    expected: bool,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``HARNESS_CLAUDE_SDK_GATEWAY`` parses truthy strings only.

    The env-var-based contract requires explicit truthy strings
    to enable Databricks routing; anything else (including the
    empty string and unrecognized values) defaults to False.
    Catches a regression where the parser becomes loose and
    mistakenly enables Databricks based on stray env vars.
    """
    monkeypatch.setenv("HARNESS_CLAUDE_SDK_GATEWAY", raw_value)
    captured: dict[str, Any] = {}

    def _fake_init(self: Any, **kwargs: Any) -> None:
        captured.update(kwargs)

    with patch(
        "omnigent.inner.claude_sdk_harness.ClaudeSDKExecutor.__init__",
        _fake_init,
    ):
        claude_sdk_harness._build_claude_sdk_executor()

    assert captured["gateway"] is expected


@pytest.mark.parametrize(
    "raw_value, expected",
    [
        ('"all"', "all"),
        ('"none"', "none"),
        ('["mlflow-onboarding"]', ["mlflow-onboarding"]),
        ('["a","b","c"]', ["a", "b", "c"]),
    ],
)
def test_skills_filter_env_var_decodes(
    raw_value: str,
    expected: str | list[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``HARNESS_CLAUDE_SDK_SKILLS_FILTER`` decodes JSON into ``str``
    or ``list[str]``.

    The env-var bridge between the Omnigent runtime and the
    claude-sdk harness subprocess is the load-bearing surface
    for ``skills:`` plumbing — without it the harness wrap
    falls back to the constructor's ``"all"`` default and
    ignores the spec entirely. Verifies all three accepted
    shapes (``"all"``, ``"none"``, list) round-trip.
    """
    monkeypatch.setenv("HARNESS_CLAUDE_SDK_SKILLS_FILTER", raw_value)
    captured: dict[str, Any] = {}

    def _fake_init(self: Any, **kwargs: Any) -> None:
        captured.update(kwargs)

    with patch(
        "omnigent.inner.claude_sdk_harness.ClaudeSDKExecutor.__init__",
        _fake_init,
    ):
        claude_sdk_harness._build_claude_sdk_executor()

    assert captured["skills_filter"] == expected


def test_skills_filter_env_var_missing_falls_back_to_all(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An unset ``HARNESS_CLAUDE_SDK_SKILLS_FILTER`` defaults to ``"all"``.

    Matches the SDK's ``skills="all"`` default so legacy
    deployments that don't yet ship the env var keep their
    existing host-skill discovery behavior.
    """
    monkeypatch.delenv("HARNESS_CLAUDE_SDK_SKILLS_FILTER", raising=False)
    captured: dict[str, Any] = {}

    def _fake_init(self: Any, **kwargs: Any) -> None:
        captured.update(kwargs)

    with patch(
        "omnigent.inner.claude_sdk_harness.ClaudeSDKExecutor.__init__",
        _fake_init,
    ):
        claude_sdk_harness._build_claude_sdk_executor()

    assert captured["skills_filter"] == "all"


def test_skills_filter_env_var_malformed_json_falls_back_to_all(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Malformed JSON in ``HARNESS_CLAUDE_SDK_SKILLS_FILTER`` defaults
    to ``"all"`` rather than crashing the harness boot.

    A bad serialization shouldn't take the whole subprocess
    down on first turn — the wrap logs and degrades to the
    SDK's default skill-discovery behavior.
    """
    monkeypatch.setenv("HARNESS_CLAUDE_SDK_SKILLS_FILTER", "{not-json")
    captured: dict[str, Any] = {}

    def _fake_init(self: Any, **kwargs: Any) -> None:
        captured.update(kwargs)

    with patch(
        "omnigent.inner.claude_sdk_harness.ClaudeSDKExecutor.__init__",
        _fake_init,
    ):
        claude_sdk_harness._build_claude_sdk_executor()

    assert captured["skills_filter"] == "all"


def test_bundle_dir_and_agent_name_env_vars_thread_through(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``HARNESS_CLAUDE_SDK_BUNDLE_DIR`` / ``_AGENT_NAME`` reach the
    inner executor.

    Together they wire the SDK ``--plugin-dir`` so any
    ``<bundle>/skills/<dir>/SKILL.md`` files in the agent's
    bundle get exposed as bundled skills, with a stable
    ``<agent>:<skill>`` plugin namespace via the
    ``.claude-plugin/plugin.json`` manifest the inner executor
    writes at construction time.
    """
    from pathlib import Path

    monkeypatch.setenv("HARNESS_CLAUDE_SDK_BUNDLE_DIR", "/tmp/fake/bundle")
    monkeypatch.setenv("HARNESS_CLAUDE_SDK_AGENT_NAME", "hello_world")
    captured: dict[str, Any] = {}

    def _fake_init(self: Any, **kwargs: Any) -> None:
        captured.update(kwargs)

    with patch(
        "omnigent.inner.claude_sdk_harness.ClaudeSDKExecutor.__init__",
        _fake_init,
    ):
        claude_sdk_harness._build_claude_sdk_executor()

    assert captured["bundle_dir"] == Path("/tmp/fake/bundle")
    assert captured["agent_name"] == "hello_world"


def test_bundle_dir_unset_passes_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Missing ``HARNESS_CLAUDE_SDK_BUNDLE_DIR`` resolves to ``None``.

    Catches a regression where the wrap silently coerces
    ``""`` to ``Path("")``: a bogus path that would break the
    SDK's ``--plugin-dir`` wiring rather than skipping it.
    """
    monkeypatch.delenv("HARNESS_CLAUDE_SDK_BUNDLE_DIR", raising=False)
    monkeypatch.delenv("HARNESS_CLAUDE_SDK_AGENT_NAME", raising=False)
    captured: dict[str, Any] = {}

    def _fake_init(self: Any, **kwargs: Any) -> None:
        captured.update(kwargs)

    with patch(
        "omnigent.inner.claude_sdk_harness.ClaudeSDKExecutor.__init__",
        _fake_init,
    ):
        claude_sdk_harness._build_claude_sdk_executor()

    assert captured["bundle_dir"] is None
    assert captured["agent_name"] is None


@pytest.mark.parametrize(
    ("env_name", "kwarg"),
    [
        ("HARNESS_CLAUDE_SDK_REQUIRE_API_CREDENTIAL", "require_api_credential"),
        ("HARNESS_CLAUDE_SDK_TOOL_CALL_POLICY_HOOK", "tool_call_policy_hook"),
        # CORAL(S113)
        ("HARNESS_CLAUDE_SDK_ISOLATE_CLAUDE_CONFIG", "isolate_claude_config"),
    ],
)
@pytest.mark.parametrize(("value", "expected"), [("1", True), ("", False), (None, False)])
def test_coral_credential_and_policy_flags_thread_through(
    monkeypatch: pytest.MonkeyPatch, env_name: str, kwarg: str, value: str | None, expected: bool
) -> None:
    """CORAL(S13, S21, S113): the Coral flags reach the executor."""
    if value is None:
        monkeypatch.delenv(env_name, raising=False)
    else:
        monkeypatch.setenv(env_name, value)
    captured: dict[str, Any] = {}

    def _fake_init(self: Any, **kwargs: Any) -> None:
        captured.update(kwargs)

    with patch("omnigent.inner.claude_sdk_harness.ClaudeSDKExecutor.__init__", _fake_init):
        claude_sdk_harness._build_claude_sdk_executor()

    assert captured[kwarg] is expected


# CORAL(S118): the harness takes its config, and for Coral its CLI's credentials, out of
# os.environ, which the SDK copies whole into every CLI it spawns.

_CONFIG_PREFIX = "HARNESS_CLAUDE_SDK_"


def _fake_key() -> str:
    return f"sk-ant-test-{secrets.token_hex(16)}"


def _digest(value: str) -> str:
    """Compare secrets by digest, so a failure prints none of them."""
    return hashlib.sha256(value.encode()).hexdigest()


def _names(environ: dict[str, str]) -> list[str]:
    """The sorted names in *environ*, without the one pytest sets for the running test."""
    return sorted(name for name in environ if name != "PYTEST_CURRENT_TEST")


def _open_as(fd: int, inode: int) -> bool:
    """Whether *fd* still names the file *inode*, not a later file that reused the number."""
    try:
        return os.fstat(fd).st_ino == inode
    except OSError:
        return False


@pytest.fixture
def fake_environ(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> dict[str, str]:
    """A fake-only ``os.environ``: nothing real is read, popped or printed."""
    environ = {"PATH": os.defpath, "HOME": str(tmp_path)}
    monkeypatch.setattr(os, "environ", environ)
    return environ


def _app_executor_factory(monkeypatch: pytest.MonkeyPatch) -> Callable[[], Any]:
    """Run ``create_app()`` and return the executor factory it hands the adapter."""
    factories: list[Callable[[], Any]] = []
    real_adapter = claude_sdk_harness.ExecutorAdapter

    def recording_adapter(*, executor_factory: Callable[[], Any], **kwargs: Any) -> Any:
        factories.append(executor_factory)
        return real_adapter(executor_factory=executor_factory, **kwargs)

    monkeypatch.setattr(claude_sdk_harness, "ExecutorAdapter", recording_adapter)
    claude_sdk_harness.create_app()
    return factories[0]


def _executor_builds(
    monkeypatch: pytest.MonkeyPatch, factory: Callable[[], Any], count: int = 1
) -> list[dict[str, Any]]:
    """The constructor kwargs of *count* executor builds from *factory*."""
    builds: list[dict[str, Any]] = []
    monkeypatch.setattr(
        claude_sdk_harness.ClaudeSDKExecutor, "__init__", lambda self, **kw: builds.append(kw)
    )
    for _ in range(count):
        factory()
    return builds


def test_create_app_takes_every_harness_config_name_out_of_os_environ(
    fake_environ: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    helper = f"printf %s {_fake_key()}"
    fake_environ.update(
        {
            "HARNESS_CLAUDE_SDK_MODEL": "claude-test-model",
            "HARNESS_CLAUDE_SDK_API_KEY_HELPER": helper,
            "HARNESS_CLAUDE_SDK_GATEWAY_AUTH_COMMAND": helper,
            "HARNESS_CLAUDE_SDK_NOT_YET_READ": "1",
            "HARNESS_CODEX_MODEL": "another-harness",
            "OMNIGENT_ANTHROPIC_API_KEY": _fake_key(),
        }
    )

    factory = _app_executor_factory(monkeypatch)

    assert sorted(name for name in fake_environ if name.startswith(_CONFIG_PREFIX)) == []
    # A non-Coral harness changes nothing else.
    assert _names(fake_environ) == [
        "HARNESS_CODEX_MODEL",
        "HOME",
        "OMNIGENT_ANTHROPIC_API_KEY",
        "PATH",
    ]
    (build,) = _executor_builds(monkeypatch, factory)
    built_helper, sent_helper = _digest(build["api_key_helper"]), _digest(helper)
    assert built_helper == sent_helper
    assert build["model"] == "claude-test-model"
    assert build["credential_env"] is None


def test_every_executor_build_reads_the_config_taken_at_create_app(
    fake_environ: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(claude_sdk_harness, "IS_POSIX", True)  # a Coral snapshot, on any OS
    helper = f"printf %s {_fake_key()}"
    sent_helper = _digest(helper)
    fake_environ.update(
        {
            "HARNESS_CLAUDE_SDK_MODEL": "claude-test-model",
            "HARNESS_CLAUDE_SDK_GATEWAY": "true",
            "HARNESS_CLAUDE_SDK_GATEWAY_HOST": "https://gateway.example",
            "HARNESS_CLAUDE_SDK_GATEWAY_BASE_URL": "https://gateway.example/anthropic",
            "HARNESS_CLAUDE_SDK_GATEWAY_AUTH_COMMAND": helper,
            "HARNESS_CLAUDE_SDK_API_KEY_HELPER": helper,
            "HARNESS_CLAUDE_SDK_REQUIRE_API_CREDENTIAL": "1",
            "HARNESS_CLAUDE_SDK_TOOL_CALL_POLICY_HOOK": "1",
            "HARNESS_CLAUDE_SDK_ISOLATE_CLAUDE_CONFIG": "1",
        }
    )
    factory = _app_executor_factory(monkeypatch)
    # Set after boot: a rebuild keeps the taken config, and other names still come from here.
    fake_environ["HARNESS_CLAUDE_SDK_MODEL"] = "set-after-create-app"
    fake_environ["HARNESS_CLAUDE_SDK_GATEWAY"] = "false"
    fake_environ["OMNIGENT_RUNNER_WORKSPACE"] = "/runner/workspace"

    first, rebuilt = _executor_builds(monkeypatch, factory, count=2)

    for build in (first, rebuilt):
        assert build["model"] == "claude-test-model"
        assert build["gateway"] is True
        assert build["base_url_override"] == "https://gateway.example/anthropic"
        built_helper = _digest(build["api_key_helper"])
        built_command = _digest(build["gateway_auth_command"])
        assert (built_helper, built_command) == (sent_helper, sent_helper)
        assert build["require_api_credential"] is True
        assert build["tool_call_policy_hook"] is True
        assert build["isolate_claude_config"] is True
        assert build["cwd"] == "/runner/workspace"
    assert {name: _digest(value) for name, value in first["credential_env"].items()} == {
        name: _digest(value) for name, value in rebuilt["credential_env"].items()
    }


def test_every_build_kwarg_comes_from_the_taken_config(
    fake_environ: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """A build after create_app gets every kwarg that a build from the untouched env gets."""
    helper = f"printf %s {_fake_key()}"
    os_env = {
        "type": "caller_process",
        "cwd": "/os-env-cwd",
        "sandbox": {"type": "linux_bwrap", "read_paths": ["/srv/data"], "allow_network": False},
        "fork": False,
    }
    config = {
        "HARNESS_CLAUDE_SDK_MODEL": "claude-test-model",
        "HARNESS_CLAUDE_SDK_GATEWAY": "true",
        "HARNESS_CLAUDE_SDK_DATABRICKS_PROFILE": "test-profile",
        "HARNESS_CLAUDE_SDK_GATEWAY_HOST": "https://gateway.example",
        "HARNESS_CLAUDE_SDK_CWD": "/config-cwd",
        "HARNESS_CLAUDE_SDK_PERMISSION_MODE": "bypassPermissions",
        "HARNESS_CLAUDE_SDK_SYSTEM_PROMPT_PRESET": "test-preset",
        "HARNESS_CLAUDE_SDK_OS_ENV": json.dumps(os_env),
        "HARNESS_CLAUDE_SDK_RETRY_POLICY": json.dumps({"max_retries": 3}),
        "HARNESS_CLAUDE_SDK_SKILLS_FILTER": json.dumps(["test-skill"]),
        "HARNESS_CLAUDE_SDK_BUNDLE_DIR": "/test-bundle",
        "HARNESS_CLAUDE_SDK_AGENT_NAME": "test-agent",
        "HARNESS_CLAUDE_SDK_GATEWAY_BASE_URL": "https://gateway.example/anthropic",
        "HARNESS_CLAUDE_SDK_GATEWAY_AUTH_COMMAND": helper,
        "HARNESS_CLAUDE_SDK_GATEWAY_AUTH_REFRESH_INTERVAL_MS": "60000",
        "HARNESS_CLAUDE_SDK_API_KEY_HELPER": helper,
        "HARNESS_CLAUDE_SDK_REQUIRE_API_CREDENTIAL": "1",
        "HARNESS_CLAUDE_SDK_TOOL_CALL_POLICY_HOOK": "1",
        "HARNESS_CLAUDE_SDK_ISOLATE_CLAUDE_CONFIG": "1",
    }

    def digests(build: dict[str, Any]) -> dict[str, str]:
        return {name: _digest(repr(value)) for name, value in build.items()}

    (unconfigured,) = _executor_builds(monkeypatch, claude_sdk_harness._build_claude_sdk_executor)
    fake_environ.update(config)
    (from_env,) = _executor_builds(monkeypatch, claude_sdk_harness._build_claude_sdk_executor)
    factory = _app_executor_factory(monkeypatch)
    (from_config,) = _executor_builds(monkeypatch, factory)

    # Every kwarg the config sets differs from an unconfigured build, so each check bites.
    configured = sorted(set(from_env) - {"credential_env"})
    assert [n for n in configured if digests(from_env)[n] == digests(unconfigured)[n]] == []
    assert {n: digests(from_config)[n] for n in configured} == {
        n: digests(from_env)[n] for n in configured
    }


def test_a_coral_harness_takes_credentials_out_of_its_cli_environment(
    fake_environ: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(claude_sdk_harness, "IS_POSIX", True)
    key = _fake_key()
    scrubbed = {
        "MY_KEY": key,  # an env-ref key: caught by its value
        "COPY_OF_THE_KEY": f"prefix-{key}-suffix",
        "ANTHROPIC_API_KEY": _fake_key(),
        "OMNIGENT_ANTHROPIC_API_KEY": _fake_key(),
        "ANTHROPIC_BASE_URL": "https://upstream.example",
        "AWS_BEARER_TOKEN_BEDROCK": _fake_key(),
        "CLAUDE_CODE_USE_BEDROCK": "1",
        "CLAUDE_CODE_SKIP_VERTEX_AUTH": "1",
        "CLAUDE_CODE_USE_GATEWAY": "1",
        "PASSED_THROUGH_TOKEN": _fake_key(),
        "ALSO_PASSED_THROUGH": "1",
    }
    kept = {
        "ANTHROPIC_MODEL": "claude-test-model",
        "OMNIGENT_ANTHROPIC_MODEL": "claude-test-model",
        "OMNIGENT_RUNNER_ENV_PASSTHROUGH": " PASSED_THROUGH_TOKEN, ALSO_PASSED_THROUGH,",
        "UNRELATED_SETTING": "kept",
    }
    fake_environ.update(
        {
            **scrubbed,
            **kept,
            "HARNESS_CLAUDE_SDK_REQUIRE_API_CREDENTIAL": "1",
            "HARNESS_CLAUDE_SDK_API_KEY_HELPER": f"printf %s {shlex.quote(key)}",
        }
    )

    factory = _app_executor_factory(monkeypatch)

    assert _names(fake_environ) == sorted({"PATH", "HOME", *kept})
    assert sorted(name for name, value in fake_environ.items() if key in value) == []
    (build,) = _executor_builds(monkeypatch, factory)
    # The credential runner gets the environment as it was before the scrub, config aside.
    snapshot = build["credential_env"]
    assert _names(snapshot) == sorted({"PATH", "HOME", *kept, *scrubbed})
    assert {name: _digest(snapshot[name]) for name in scrubbed} == {
        name: _digest(value) for name, value in scrubbed.items()
    }


@pytest.mark.parametrize(
    ("coral", "posix"), [(True, False), (False, True)], ids=["coral-windows", "non-coral"]
)
def test_only_a_coral_harness_on_posix_scrubs_its_environment(
    fake_environ: dict[str, str], monkeypatch: pytest.MonkeyPatch, coral: bool, posix: bool
) -> None:
    monkeypatch.setattr(claude_sdk_harness, "IS_POSIX", posix)
    key = _fake_key()
    forwarded = {"MY_KEY": key, "ANTHROPIC_API_KEY": _fake_key(), "CLAUDE_CODE_USE_BEDROCK": "1"}
    fake_environ.update({**forwarded, "HARNESS_CLAUDE_SDK_API_KEY_HELPER": f"printf %s {key}"})
    if coral:
        fake_environ["HARNESS_CLAUDE_SDK_REQUIRE_API_CREDENTIAL"] = "1"

    (build,) = _executor_builds(monkeypatch, _app_executor_factory(monkeypatch))

    assert _names(fake_environ) == sorted({"PATH", "HOME", *forwarded})
    assert build["credential_env"] is None


class _WriteRecordingEnviron(dict[str, str]):
    """A fake environ that records every name written into it."""

    def __init__(self, initial: dict[str, str]) -> None:
        super().__init__(initial)
        self.written: set[str] = set()

    def __setitem__(self, name: str, value: str) -> None:
        self.written.add(name)
        super().__setitem__(name, value)

    def update(self, *args: Any, **kwargs: str) -> None:  # type: ignore[override]
        values = dict(*args, **kwargs)
        self.written.update(values)
        super().update(values)


@pytest.mark.posix_only
def test_create_app_adopts_its_launch_socket_into_its_config_not_os_environ(
    fake_environ: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    helper = f"printf %s {_fake_key()}"
    command = f"printf %s {_fake_key()}"
    sent = {
        claude_sdk_harness._ENV_API_KEY_HELPER: helper,
        claude_sdk_harness._ENV_GATEWAY_AUTH_COMMAND: command,
    }
    sent_digests = {name: _digest(value) for name, value in sent.items()}
    assert set(sent) == CLAUDE_SDK_HARNESS_LAUNCH_SECRET_ENV_VARS
    fd = launch_secrets_pipe(sent)
    sent_inode = os.fstat(fd).st_ino
    environ = _WriteRecordingEnviron(
        {
            **fake_environ,
            HARNESS_LAUNCH_FD_ENV_VAR: str(fd),
            "HARNESS_CLAUDE_SDK_MODEL": "claude-test-model",
        }
    )
    monkeypatch.setattr(os, "environ", environ)

    factory = _app_executor_factory(monkeypatch)

    assert _names(environ) == ["HOME", "PATH"]
    assert sorted(environ.written) == []
    assert not _open_as(fd, sent_inode)
    (build,) = _executor_builds(monkeypatch, factory)
    built_digests = {
        name: _digest(build[name.removeprefix(_CONFIG_PREFIX).lower()]) for name in sent
    }
    assert built_digests == sent_digests
    assert build["model"] == "claude-test-model"


def _socket_carrying(payload: bytes) -> int:
    """A launch socket's child end holding *payload*, its parent end already closed."""
    parent_end, child_end = socket.socketpair()
    with parent_end:
        parent_end.sendall(payload)
    return child_end.detach()


def _pipe_carrying(payload: bytes) -> int:
    """A pipe's read end holding *payload*: readable through /proc on Linux, so refused."""
    read_fd, write_fd = os.pipe()
    os.write(write_fd, payload)
    os.close(write_fd)
    return read_fd


@pytest.mark.posix_only
@pytest.mark.parametrize("refused", ["other-config", "not-json", "a-pipe", "not-a-number"])
def test_create_app_refuses_a_launch_socket_it_cannot_trust(
    fake_environ: dict[str, str], capsys: pytest.CaptureFixture[str], refused: str
) -> None:
    value = _fake_key()
    helper = claude_sdk_harness._ENV_API_KEY_HELPER
    fd: int | None = None
    if refused == "other-config":
        fd = launch_secrets_pipe({"HARNESS_CLAUDE_SDK_MODEL": value})
    elif refused == "not-json":
        fd = _socket_carrying(f'{{"{helper}": "{value}"'.encode())
    elif refused == "a-pipe":
        fd = _pipe_carrying(json.dumps({helper: value}).encode())
    inode = os.fstat(fd).st_ino if fd is not None else None
    fake_environ[HARNESS_LAUNCH_FD_ENV_VAR] = str(fd) if fd is not None else f"3{value}"

    with pytest.raises(SystemExit) as exited:
        claude_sdk_harness.create_app()

    assert exited.value.code == LAUNCH_SECRETS_EXIT_CODE
    assert value not in capsys.readouterr().err
    assert HARNESS_LAUNCH_FD_ENV_VAR not in fake_environ
    assert helper not in fake_environ
    assert fd is None or not _open_as(fd, inode)


def test_a_coral_harness_drops_every_forwarded_credential_and_provider_switch(
    fake_environ: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    from omnigent.host.connect import HARNESS_CREDENTIAL_ENV_VARS

    monkeypatch.setattr(claude_sdk_harness, "IS_POSIX", True)
    # The host forwards each credential under its OMNIGENT_ alias too.
    aliases = {
        "OMNIGENT_ANTHROPIC_API_KEY",
        "OMNIGENT_CLAUDE_CODE_OAUTH_TOKEN",
        "OMNIGENT_GIT_TOKEN",
    }
    assert aliases <= HARNESS_CREDENTIAL_ENV_VARS
    providers = (
        "BEDROCK",
        "VERTEX",
        "FOUNDRY",
        "MANTLE",
        "ANTHROPIC_AWS",
        "ANTHROPIC_GOOGLE_CLOUD",
    )
    switches = {
        f"CLAUDE_CODE_{kind}"
        for provider in providers
        for kind in (f"USE_{provider}", f"SKIP_{provider}_AUTH")
    } | {"CLAUDE_CODE_USE_GATEWAY"}
    fake_environ.update({name: _fake_key() for name in HARNESS_CREDENTIAL_ENV_VARS})
    fake_environ.update(dict.fromkeys(switches, "1"))
    fake_environ.update(
        {
            "HARNESS_CLAUDE_SDK_REQUIRE_API_CREDENTIAL": "1",
            "HARNESS_CLAUDE_SDK_API_KEY_HELPER": f"printf %s {_fake_key()}",
        }
    )

    claude_sdk_harness.create_app()

    # Model routing is the only forwarded name a Coral CLI keeps.
    assert _names(fake_environ) == [
        "ANTHROPIC_MODEL",
        "HOME",
        "OMNIGENT_ANTHROPIC_MODEL",
        "PATH",
    ]


# A key configured with a trailing newline is used stripped, so its copies are found stripped.
@pytest.mark.parametrize("tail", ["", "\n"], ids=["as-written", "trailing-newline"])
def test_a_coral_harness_drops_renamed_copies_of_its_gateway_literal(
    fake_environ: dict[str, str], monkeypatch: pytest.MonkeyPatch, tail: str
) -> None:
    monkeypatch.setattr(claude_sdk_harness, "IS_POSIX", True)
    token = f"gateway-test-{secrets.token_hex(16)}"
    fake_environ.update(
        {
            "HARNESS_CLAUDE_SDK_REQUIRE_API_CREDENTIAL": "1",
            "HARNESS_CLAUDE_SDK_API_KEY_HELPER": "databricks auth token --host https://x.example",
            "HARNESS_CLAUDE_SDK_GATEWAY_AUTH_COMMAND": f"printf %s {shlex.quote(token + tail)}",
            "RENAMED_GATEWAY_TOKEN": token,
            "HEADER_COPY": f"Authorization: Bearer {token}",
            "UNRELATED_SETTING": "kept",
        }
    )

    claude_sdk_harness.create_app()

    assert _names(fake_environ) == ["HOME", "PATH", "UNRELATED_SETTING"]


def test_an_empty_literal_or_a_command_scrubs_no_unlisted_name(
    fake_environ: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(claude_sdk_harness, "IS_POSIX", True)
    fake_environ.update(
        {
            "HARNESS_CLAUDE_SDK_REQUIRE_API_CREDENTIAL": "1",
            # An empty literal is a substring of every value; it must name nothing to drop.
            "HARNESS_CLAUDE_SDK_API_KEY_HELPER": "printf %s ''",
            "HARNESS_CLAUDE_SDK_GATEWAY_AUTH_COMMAND": "databricks auth token --host https://x",
            "UNRELATED_SETTING": "databricks auth token --host https://x",
        }
    )

    claude_sdk_harness.create_app()

    assert _names(fake_environ) == ["HOME", "PATH", "UNRELATED_SETTING"]


@pytest.mark.parametrize("coral", [True, False], ids=["coral", "non-coral"])
def test_a_coral_harness_drops_every_name_the_host_forwarded(
    fake_environ: dict[str, str], monkeypatch: pytest.MonkeyPatch, coral: bool
) -> None:
    """A second provider's ``env:MY_PROVIDER_KEY`` is known only from the host's name list."""
    from omnigent.host.connect import RUNNER_FORWARDED_NAMES_ENV_VAR

    monkeypatch.setattr(claude_sdk_harness, "IS_POSIX", True)
    forwarded = {"MY_PROVIDER_KEY": _fake_key(), "OMNIGENT_MY_PROVIDER_KEY": _fake_key()}
    sent_digests = {name: _digest(value) for name, value in forwarded.items()}
    fake_environ.update(
        {
            **forwarded,
            RUNNER_FORWARDED_NAMES_ENV_VAR: ",".join(sorted(forwarded)),
            "HARNESS_CLAUDE_SDK_API_KEY_HELPER": f"printf %s {_fake_key()}",
            "UNRELATED_SETTING": "kept",
        }
    )
    if coral:
        fake_environ["HARNESS_CLAUDE_SDK_REQUIRE_API_CREDENTIAL"] = "1"

    (build,) = _executor_builds(monkeypatch, _app_executor_factory(monkeypatch))

    kept = {"HOME", "PATH", RUNNER_FORWARDED_NAMES_ENV_VAR, "UNRELATED_SETTING"}
    assert _names(fake_environ) == sorted(kept if coral else kept | set(forwarded))
    if coral:
        snapshot = build["credential_env"]
        snapshot_digests = {name: _digest(snapshot[name]) for name in forwarded}
        assert snapshot_digests == sent_digests


def test_a_coral_harness_keeps_process_and_network_essentials(
    fake_environ: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Listed for passthrough, named as forwarded and holding the key, these still stay."""
    from omnigent.host.connect import RUNNER_FORWARDED_NAMES_ENV_VAR

    monkeypatch.setattr(claude_sdk_harness, "IS_POSIX", True)
    key = _fake_key()
    protected = {
        "PATH": f"/opt/{key}/bin:{os.defpath}",
        "HOME": fake_environ["HOME"],
        **dict.fromkeys(("TMPDIR", "TMP", "TEMP"), f"/tmp/{key}"),
        **dict.fromkeys(("USER", "LOGNAME"), f"user-{key}"),
        "SHELL": "/bin/sh",
        **dict.fromkeys(("LANG", "LC_ALL", "LC_CTYPE"), "en_US.UTF-8"),
        "TERM": "xterm",
        **dict.fromkeys(("ANTHROPIC_MODEL", "OMNIGENT_ANTHROPIC_MODEL"), "claude-test-model"),
        "HTTPS_PROXY": "http://proxy.example:3128",
        "https_proxy": "http://proxy.example:3128",
        "NO_PROXY": "localhost,127.0.0.1",
        "no_proxy": "localhost,127.0.0.1",
        **dict.fromkeys(
            ("SSL_CERT_FILE", "REQUESTS_CA_BUNDLE", "NODE_EXTRA_CA_CERTS"), f"/etc/ssl/{key}.pem"
        ),
        "SSL_CERT_DIR": "/etc/ssl/certs",
    }
    # A proxy's userinfo is its credential: off the CLI, kept for the proxy's upstream client.
    with_userinfo = {
        "HTTP_PROXY": "http://user:proxy-test-secret@proxy.example:3128",
        "all_proxy": "user:proxy-test-secret@proxy.example:1080",
    }
    listed = ",".join(sorted({*protected, *with_userinfo}))
    fake_environ.update(
        {
            **protected,
            **with_userinfo,
            "OMNIGENT_RUNNER_ENV_PASSTHROUGH": listed,
            RUNNER_FORWARDED_NAMES_ENV_VAR: listed,
            "HARNESS_CLAUDE_SDK_REQUIRE_API_CREDENTIAL": "1",
            "HARNESS_CLAUDE_SDK_API_KEY_HELPER": f"printf %s {shlex.quote(key)}",
        }
    )

    (build,) = _executor_builds(monkeypatch, _app_executor_factory(monkeypatch))

    passthrough = {"OMNIGENT_RUNNER_ENV_PASSTHROUGH", RUNNER_FORWARDED_NAMES_ENV_VAR}
    assert _names(fake_environ) == sorted({*protected, *passthrough})
    snapshot_names = set(build["credential_env"])
    assert sorted(name for name in with_userinfo if name not in snapshot_names) == []


@pytest.mark.parametrize(
    ("key", "copy_dropped"),
    [("local", False), ("k" * 19, False), ("k" * 20, True)],
    ids=["placeholder", "19-chars", "20-chars"],
)
def test_the_value_scan_skips_a_key_too_short_to_tell_from_other_values(
    fake_environ: dict[str, str], monkeypatch: pytest.MonkeyPatch, key: str, copy_dropped: bool
) -> None:
    monkeypatch.setattr(claude_sdk_harness, "IS_POSIX", True)
    fake_environ.update(
        {
            "PATH": f"/usr/{key}/bin:{os.defpath}",
            "COPY_OF_THE_KEY": f"/srv/{key}",
            "HARNESS_CLAUDE_SDK_REQUIRE_API_CREDENTIAL": "1",
            "HARNESS_CLAUDE_SDK_API_KEY_HELPER": f"printf %s {key}",
        }
    )

    claude_sdk_harness.create_app()

    expected = {"HOME", "PATH"} if copy_dropped else {"COPY_OF_THE_KEY", "HOME", "PATH"}
    assert _names(fake_environ) == sorted(expected)


@pytest.mark.posix_only  # the stand-in CLI is a shebang script
async def test_the_sdk_version_check_and_cli_spawn_see_no_harness_config(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The real SDK transport starts the CLI as ``-v``, then for the session; neither gets config.

    Spawns inherit the process environment, not a Python mapping, so this sets fake config in
    the real ``os.environ``; the stand-in CLI records names only.
    """
    from claude_agent_sdk import ClaudeAgentOptions
    from claude_agent_sdk._internal.transport.subprocess_cli import SubprocessCLITransport

    records = tmp_path / "records"
    records.mkdir()
    fake_cli = tmp_path / "claude"
    fake_cli.write_text(
        f"#!{sys.executable}\n"
        "import json, os, sys\n"
        "version = sys.argv[1:] == ['-v']\n"
        f"path = os.path.join({str(records)!r}, 'version' if version else 'session')\n"
        "with open(path + '.part', 'w') as out:\n"
        "    json.dump(sorted(os.environ), out)\n"
        "os.replace(path + '.part', path)\n"
        "if version:\n"
        "    print('9.9.9 (Claude Code)', flush=True)\n"
    )
    fake_cli.chmod(0o700)
    # Registered with monkeypatch first, so whatever create_app pops is restored afterwards.
    for name in [n for n in os.environ if n.startswith(_CONFIG_PREFIX)]:
        monkeypatch.delenv(name)
    for name in (HARNESS_LAUNCH_FD_ENV_VAR, "CLAUDE_AGENT_SDK_SKIP_VERSION_CHECK"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("HARNESS_CLAUDE_SDK_MODEL", "claude-test-model")
    monkeypatch.setenv("HARNESS_CLAUDE_SDK_API_KEY_HELPER", f"printf %s {_fake_key()}")
    monkeypatch.setenv("HARNESS_CLAUDE_SDK_AGENT_NAME", "test-agent")

    claude_sdk_harness.create_app()
    transport = SubprocessCLITransport(
        prompt="hi", options=ClaudeAgentOptions(cli_path=str(fake_cli))
    )
    await transport.connect()
    try:
        await poll_until_async(
            lambda: (records / "version").exists() and (records / "session").exists()
        )
    finally:
        await transport.close()

    for record in ("version", "session"):
        names = json.loads((records / record).read_text())
        assert "PATH" in names
        assert [name for name in names if name.startswith(_CONFIG_PREFIX)] == []
