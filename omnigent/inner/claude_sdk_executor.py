# CORAL(S95): user-visible "Omnigent" text changed to "Coral" by .coral/tools/rebrand.py
"""ClaudeSDKExecutor: run agents using the Claude Agent SDK.

Uses the ``claude-agent-sdk`` Python package to run Claude Code as the
underlying agent harness.  Omnigent tools are bridged into the SDK session
as MCP tools so Claude can call them alongside its built-in capabilities.

The SDK manages its own internal agent loop (tool calls, retries, context).
This executor translates the SDK message stream into Omnigent ExecutorEvents
and builds up the session History from observed tool-use blocks.

Requirements:
    pip install claude-agent-sdk          # optional dependency

Environment (direct Anthropic):
    ANTHROPIC_API_KEY – API key for Claude

Environment (Databricks-hosted Claude via native Anthropic Messages API):
    DATABRICKS_CONFIG_PROFILE – optional Databricks profile selector
    ~/.databrickscfg          – host + token profile for workspace access
    (or ~/.databrickscfg with a profile containing host + token)

    The executor builds ANTHROPIC_BASE_URL plus an invocation-local
    apiKeyHelper setting from Databricks credentials so Claude Code can
    refresh auth through ``databricks auth token`` while routing through
    the Databricks gateway.
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import pathlib
import re  # CORAL(S116)
import secrets  # CORAL(S115)
import shutil
import stat  # CORAL(S125)
import sys
import tempfile  # CORAL(S113)
import threading  # CORAL(S116)
import time
import urllib.request  # CORAL(S124)
from collections.abc import AsyncIterator, Awaitable, Callable, Iterator, Mapping, Sequence
from contextlib import ExitStack, contextmanager, suppress
from dataclasses import dataclass, field
from functools import partial
from types import ModuleType
from typing import Any, NamedTuple, Protocol, TypeAlias, cast
from urllib.parse import urlsplit  # CORAL(S124)

from omnigent._platform import (  # CORAL(S124, S125)
    IS_DARWIN,
    IS_POSIX,
    resolve_cli_binary,
    stable_user_id,
)
from omnigent.cli_invocation import cli_invocation
from omnigent.databricks_ai_gateway import (
    CLAUDE_CODE_AGENT,
    is_databricks_ai_gateway_url,
    is_ug_route,
    with_gateway_attribution_lines,
)
from omnigent.inner import _proc
from omnigent.inner.bundle_skills import ensure_bundle_plugin_manifest
from omnigent.inner.hook_scripts import subagent_router
from omnigent.llms._usage_observer import notify_from_dict as _notify_usage_from_dict
from omnigent.llms.adapters._content import parse_data_uri as _parse_replay_data_uri
from omnigent.models import model_catalog
from omnigent.models.claude_model_vocabulary import (
    ALIAS_MODEL_ENV_VARS,
    served_alias_pins,
    served_canonical_overrides,
)
from omnigent.models.model_metadata import concrete_reported_model
from omnigent.models.model_override import is_databricks_model_id
from omnigent.runtime.mcp_tool_result import decode_mcp_image_result
from omnigent.spec.types import RetryPolicy
from omnigent.telemetry.surface import harness_client_surface
from omnigent.util.json_serialization import json_dumps_transport_safe
from omnigent.util.json_types import JsonObject as _JsonObject
from omnigent.util.reasoning_effort import CLAUDE_EFFORTS, validate_effort

from ._subprocess_lifecycle import close_anyio_subprocess_transport
from .async_utils import run_sync_on_thread
from .claude_gateway_shim import (
    DATABRICKS_CLAUDE_ADAPTIVE_THINKING_PREFIXES,
    MIN_SCANNED_LITERAL_CHARS,  # CORAL(S124)
    ClaudeGatewayShim,
    UpstreamCredential,  # CORAL(S124)
    UpstreamCredentialError,  # CORAL(S124)
    check_upstream_url,  # CORAL(S124, S125)
    static_credential_literal,  # CORAL(S124)
    static_printf_value,  # CORAL(S124)
)
from .datamodel import OSEnvSandboxSpec, OSEnvSpec
from .executor import (
    Executor,
    ExecutorConfig,
    ExecutorError,
    ExecutorEvent,
    Message,
    ReasoningChunk,
    TextChunk,
    ToolCallComplete,
    ToolCallRequest,
    ToolCallStatus,
    ToolSpec,
    TurnComplete,
    classify_tool_result,
    describe_exception,
    without_tool_history,
)
from .native_attachments import framework_notices, unresolved_attachment_marker
from .sandbox import (
    PRIVATE_TMPDIR_NAME,  # CORAL(S116)
    SandboxPolicy,  # CORAL(S113)
    _is_private_dir,  # CORAL(S115)
    _remove_orphaned_launch_tmpdirs,  # CORAL(S116)
    _resolve_sandbox_type,
    claim_temp_dir,  # CORAL(S116)
    create_exec_launcher,
    get_backend,
    open_regular_file,  # CORAL(S115)
    resolve_sandbox,
    with_additional_read_roots,
    with_additional_write_files,
    with_additional_write_roots,
    with_launch_tmpdir,
    with_scratch_dir_env,  # CORAL(S113)
)

logger = logging.getLogger(__name__)

# Default auth-token refresh cadence (ms) for the vendor-neutral gateway
# transport when ``HARNESS_CLAUDE_SDK_GATEWAY_AUTH_REFRESH_INTERVAL_MS`` is
# unset. Not Databricks-specific: the same fallback applies to any gateway
# producer (Databricks Unity Gateway or a generic key/gateway provider).
_GATEWAY_AUTH_REFRESH_MS = 900_000
_CLAUDE_CODE_ENABLE_TOOL_SEARCH_ENV = "ENABLE_TOOL_SEARCH"
# Claude Code floors a thinking budget at this size and requires max_tokens above it.
_CLAUDE_CODE_MIN_THINKING_BUDGET_TOKENS = 1024

# Claude Code forwards the ANTHROPIC_CUSTOM_HEADERS value verbatim as
# request headers. The Databricks Unity Gateway only serves Claude requests
# in coding-agent mode when this header is present, so the Databricks
# gateway env (not the generic-provider gateway env) must carry it.
_ANTHROPIC_CUSTOM_HEADERS_ENV = "ANTHROPIC_CUSTOM_HEADERS"
_DATABRICKS_CODING_AGENT_HEADER = "x-databricks-use-coding-agent-mode: true"

# CORAL(S13): refusals for Coral specs that lack an API credential or an OS sandbox
CORAL_SUBSCRIPTION_AUTH_REFUSED_CODE = "coral_subscription_auth_refused"
CORAL_SUBSCRIPTION_AUTH_REFUSED_MESSAGE = (
    "Workflows with an orchestrator need an Anthropic API key "
    "(Console, plan-linked Console, or cloud provider)."
)
CORAL_SANDBOX_UNAVAILABLE_CODE = "coral_sandbox_unavailable"
CORAL_POLICY_HOOK_UNAVAILABLE_CODE = "coral_policy_hook_unavailable"
# CORAL(S124): a Coral CLI presents this session token to its executor's loopback proxy,
# which holds the real credential; the helper puts no secret on any command line
_PROXY_TOKEN_ENV = "OMNIGENT_CLAUDE_PROXY_TOKEN"
_PROXY_TOKEN_HELPER = f'printf %s "${_PROXY_TOKEN_ENV}"'
# CORAL(S124): where a Coral CLI with a key and no endpoint sent it, and the CLI's own switch
# for treating its base URL, here the proxy's loopback one, as that API
_ANTHROPIC_API_URL = "https://api.anthropic.com"
_ANTHROPIC_API_HOST = "api.anthropic.com"
_ASSUME_FIRST_PARTY_ENV = "_CLAUDE_CODE_ASSUME_FIRST_PARTY_BASE_URL"
# CORAL(S124): the pinned CLI's own cache time for a key helper, which the proxy now runs
_KEY_HELPER_TTL_ENV = "CLAUDE_CODE_API_KEY_HELPER_TTL_MS"
_CLI_KEY_HELPER_TTL_S = 300.0
# CORAL(S124): the refusal when that CLI's launch would still hold the key itself
CORAL_CREDENTIAL_EXPOSED_CODE = "coral_credential_exposed"
# CORAL(S124): the refusal when the proxy's upstream is plain http to another machine
CORAL_CREDENTIAL_UPSTREAM_REFUSED_CODE = "coral_credential_upstream_refused"
# CORAL(S124): the CLI's hop to that proxy must bypass any proxy it inherits
_NO_PROXY_ENV = ("NO_PROXY", "no_proxy")
# CORAL(S124): how long the model listing waits for a credential command, as before the proxy
_LISTING_CREDENTIAL_WAIT_S = 15.0
_LOOPBACK_NO_PROXY = ("127.0.0.1", "localhost")
# CORAL(S125): what a Coral CLI behind the credential proxy takes from the user's settings env:
# model routing, and these opt-outs when their value switches them on
_SETTINGS_ENV_MODEL_NAMES = frozenset(
    {
        "ANTHROPIC_MODEL",
        "ANTHROPIC_SMALL_FAST_MODEL",
        "CLAUDE_CODE_SUBAGENT_MODEL",
        *ALIAS_MODEL_ENV_VARS.values(),
    }
)
_SETTINGS_ENV_OPT_OUT_NAMES = frozenset(
    {
        "DISABLE_TELEMETRY",
        "DISABLE_ERROR_REPORTING",
        "DISABLE_AUTOUPDATER",
        "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC",
    }
)
# Never a value that switches one off: the host may have switched it on.
_SETTINGS_ENV_SWITCH_VALUES = frozenset({"1", "true"})
# CORAL(S125): the settings names that say where the real credential goes and through what.
# The proxy's upstream hop takes them; the CLI gets a proxy name only when its value is bare.
_SETTINGS_ENV_BASE_URL = "ANTHROPIC_BASE_URL"
_SETTINGS_ENV_CA_FILE = "NODE_EXTRA_CA_CERTS"
_SETTINGS_ENV_PROXY_NAMES = frozenset(
    spelling
    for name in ("HTTPS_PROXY", "HTTP_PROXY", "NO_PROXY", "ALL_PROXY")
    for spelling in (name, name.lower())  # the two spellings a client reads
)
# CORAL(S125): the proxy kinds the credential proxy's upstream client can use
_UPSTREAM_PROXY_SCHEMES = ("http", "https")
# CORAL(S125): the settings trust rule compares paths as macOS volumes do by default, and
# gives up on a path with more links than any real one
_PATHS_IGNORE_CASE = IS_DARWIN
_MAX_FOLLOWED_LINKS = 40
# CORAL(S125): where the user's Claude settings file is, read from the host's environment once
_SETTINGS_LOCATION_ENV = ("CLAUDE_CONFIG_DIR", "HOME")
_CORAL_SANDBOX_BINARIES = {"linux_bwrap": "bwrap", "darwin_seatbelt": "sandbox-exec"}
_SUBSCRIPTION_TOKEN_ENV = ("CLAUDE_CODE_OAUTH_TOKEN", "ANTHROPIC_AUTH_TOKEN")
# CORAL(S113): an isolated CLI's Claude config is a private dir, never the user's
_CLAUDE_CONFIG_DIR_ENV = "CLAUDE_CONFIG_DIR"
_CLAUDE_CONFIG_ENV = (_CLAUDE_CONFIG_DIR_ENV, "CLAUDE_SECURESTORAGE_CONFIG_DIR")
# CORAL(S113): a file there, so the CLI reports an oversized tool result as unsaved
# instead of naming a saved copy the model has no tool to open
_CLAUDE_CONFIG_BLOCKED_NAMES = ("projects",)
# CORAL(S115): a wrapped non-Coral CLI's private dir starts from a copy of these keys of the
# user's global config, never a Claude sign-in credential: its MCP servers, identity, legacy
# env and, per project, the trust and MCP enable/disable keys the CLI reads (2.1.325).
_CLAUDE_GLOBAL_CONFIG_NAME = ".claude.json"
_CLAUDE_SEED_KEYS = {"mcpServers": dict, "userID": str, "env": dict}
# CORAL(S115): each with the value the CLI treats as unset, which is not copied
_CLAUDE_SEED_PROJECT_DEFAULTS: dict[str, object] = {
    "hasTrustDialogAccepted": False,
    "hasClaudeMdExternalIncludesApproved": False,
    "disabledMcpServers": [],
    "enabledMcpServers": [],
    "disabledMcpjsonServers": [],
    "enabledMcpjsonServers": [],
    "enableAllProjectMcpServers": False,
}
# CORAL(S115): a larger global config is treated as malformed
_CLAUDE_SEED_SOURCE_MAX_BYTES = 16 * 1024 * 1024
# CORAL(S115): this backend confines processes, not files, so its CLI keeps the shared grants
_WINDOWS_JOB_OBJECT_BACKEND = "windows_jobobject"
# CORAL(S115): names that give a wrapped CLI a credential without a stored login
_CLAUDE_CREDENTIAL_ENV = (
    *_SUBSCRIPTION_TOKEN_ENV,
    "CLAUDE_CODE_USE_BEDROCK",
    "CLAUDE_CODE_USE_VERTEX",
    "CLAUDE_CODE_USE_FOUNDRY",
)

CLAUDE_AUTH_FAILED_CODE = "claude_sdk_auth_failed"
CLAUDE_AUTH_FAILED_TITLE = "Claude Code could not authenticate"
# Failed ResultMessages carry no structured auth signal (unlike api_retry's
# status), so Claude Code's (2.1.x) failure wording is the only input. A bare
# "Run /login" is insufficient: billing/device-enrollment errors suggest it too.
_CLAUDE_AUTH_FAILURE_MARKERS = (
    "failed to authenticate",
    "authentication failed",
    "authentication_error",
    "not authenticated",
    "not logged in",
    "not signed in",
    "login expired",
    "please login again",
    "run /login to sign in",
    "run /login to authenticate",
    "run /login and sign in",
    "oauth session expired",
    "oauth token revoked",
    "credential is expired or revoked",
    "invalid api key",
    "disabled api key authentication",
)

# Claude Code ends its failure lines with "." or a " \u00b7 Run /login" clause.
_TRAILING_PUNCTUATION = ".!: \u00b7"


def is_claude_auth_failure_text(text: str) -> bool:
    """Whether *text* is Claude Code reporting that it could not authenticate."""
    normalized = " ".join(text.replace("`", "").lower().split())
    return any(marker in normalized for marker in _CLAUDE_AUTH_FAILURE_MARKERS)


def _claude_auth_remediation(
    *,
    databricks_profile: bool,
    gateway: bool,
    private_config: bool = False,  # CORAL(S115)
    token_env: str | None = None,
) -> str:
    """
    The next step for a Claude Code authentication failure in this transport mode.

    CORAL(S115): *private_config* is a sandboxed CLI with its own config and no API key
    helper; *token_env* names the subscription token variable it was given, if any.
    """
    if databricks_profile:
        return "Check your selected ~/.databrickscfg profile."
    if gateway:
        return (
            "Check your provider's base URL and auth command (ANTHROPIC_BASE_URL / gateway auth)."
        )
    if private_config:  # CORAL(S115)
        sandboxed = "This agent's Claude CLI runs in an OS sandbox with its own Claude config"
        setup = f"`{cli_invocation()} setup`"
        if token_env is not None:
            return (
                f"{sandboxed}, so it signs in only with the {token_env} it was given. Check that "
                f"token, or run {setup} there to give the agent a Claude API key or gateway."
            )
        return (
            f"{sandboxed}, so a Claude subscription login stored on this host does not reach it. "
            f"Run {setup} there to give the agent a Claude API key or gateway, or set "
            "CLAUDE_CODE_OAUTH_TOKEN (from `claude setup-token`) in the host's environment; "
            "the host passes it to every runner it starts."
        )
    return (
        "Sign in to Claude Code on the host that runs this agent (`claude auth login`), "
        f"or run `{cli_invocation()} setup` there to give the agent a Claude API key or gateway."
    )


# ---------------------------------------------------------------------------
# TypeAliases for Omnigent JSON-shaped boundary values. The SDK exchanges
# heterogeneous dicts at the transport and tool boundaries — named aliases
# here keep the executor ``object``-free while isolating the justified
# ``explicit-any`` boundary to a single place, mirroring the peer
# ``openai_agents_sdk_executor`` / ``databricks_executor`` conventions.
# ---------------------------------------------------------------------------

# Parsed tool arguments / tool result dict — JSON-shaped bags exchanged
# with the Omnigent tool executor and the SDK's MCP bridge.
ToolArgs: TypeAlias = dict[str, Any]  # type: ignore[explicit-any]
ToolResult: TypeAlias = dict[str, Any]  # type: ignore[explicit-any]

# MCP response payload (``content`` + optional ``isError``) returned to the
# Claude SDK from each MCP tool handler.
McpResponse: TypeAlias = dict[str, Any]  # type: ignore[explicit-any]

# Tool executor callable wired in by ``omnigent.Session``.
ToolExecutor: TypeAlias = Callable[[str, ToolArgs], Awaitable[ToolResult]]

# Elicitation handler wired in by :class:`ExecutorAdapter`. Kept SDK-agnostic
# so the adapter does not import ``claude_agent_sdk`` types.
ElicitationHandler: TypeAlias = Callable[
    [str, ToolArgs],
    Awaitable[bool],
]

# Adapter bridge: shows AskUserQuestion as a form; returns input+``answers`` or a deny reason.
AskQuestionHandler: TypeAlias = Callable[
    [ToolArgs],
    Awaitable[dict[str, Any] | str],
]

# Opaque SDK artifacts whose concrete shape we don't touch directly:
# - ``SdkMcpTool``: returned by ``sdk.tool(...)`` decorator and passed back
#   to ``sdk.create_sdk_mcp_server(tools=...)`` without field access.
# - ``ClaudeAgentOptions``: the SDK's dataclass; fields set via attribute
#   assignment after construction rather than typed kwargs.
SdkMcpTool: TypeAlias = Any  # type: ignore[explicit-any]
SdkOptions: TypeAlias = Any  # type: ignore[explicit-any]


# ---------------------------------------------------------------------------
# SDK-private reach Protocols.
#
# Some SDK surfaces are dynamic and the lifecycle reaches below its public
# types. Protocols keep the handful of public and private attributes this
# executor touches explicit.
#
# The private reaches (``_query``, ``_transport``, ``_process``,
# ``_stderr_task`` / ``_stderr_task_group``, etc.) are necessary to tear
# down the CLI subprocess tree when the SDK's own ``disconnect()`` path is unsafe
# (different event loop / task) or hangs. The SDK does not expose a
# supported equivalent, so we treat the private attributes as part of
# our integration contract and document them here.
# ---------------------------------------------------------------------------


class _Process(Protocol):
    """Subset of ``anyio.abc.Process`` / ``asyncio.subprocess.Process``.

    These fields are standard on both process abstractions — the SDK's
    transport uses an anyio process but the shape matches the asyncio one
    for the attributes we touch.
    """

    pid: int | None
    returncode: int | None

    def terminate(self) -> None: ...
    def kill(self) -> None: ...
    async def wait(self) -> int: ...


class _CancelScope(Protocol):
    def cancel(self) -> None: ...


class _TaskGroup(Protocol):
    cancel_scope: _CancelScope


class _TaskHandle(Protocol):
    """Private view of the SDK's detached stderr-reader task.

    Current ``claude-agent-sdk`` (>=0.2.x) runs the stderr reader as a
    single task exposed as ``_stderr_task`` with a ``cancel()`` method;
    older revs used an anyio task group (``_stderr_task_group``). The
    executor probes both shapes during force-close, so both are typed
    optional on ``_ClaudeTransport`` below.
    """

    def cancel(self) -> None: ...


class _ClaudeQuery(Protocol):
    """Private view of ``claude_agent_sdk._internal.query.Query``.

    ``_closed`` is the SDK's "stop accepting messages" flag. ``_tg`` was a
    per-query task group in older SDK revs — absent in current revs but
    still probed so this executor handles both shapes.
    """

    _closed: bool
    _tg: _TaskGroup | None


class _Stream(Protocol):
    """Structural view of an anyio text stream. Only ``aclose`` is actually
    available on the real ``TextReceiveStream`` / ``TextSendStream``; the
    ``close`` / ``transport`` attributes probed during teardown are
    historical belt-and-suspenders cleanup and no-op on the current SDK.
    """

    async def aclose(self) -> None: ...


class _ClaudeTransport(Protocol):
    """Private view of ``SubprocessCLITransport`` internals we tear down.

    Kept minimal — only the attributes ``_force_close_client`` touches.
    """

    _process: _Process | None
    _stdout_stream: _Stream | None
    _stdin_stream: _Stream | None
    _stderr_stream: _Stream | None
    _stderr_task: _TaskHandle | None
    _stderr_task_group: _TaskGroup | None
    _ready: bool


class _ClaudeClient(Protocol):
    """Structural view of ``claude_agent_sdk.ClaudeSDKClient``.

    Covers the public methods the executor calls plus the two private
    attributes it clears during a force-close. Test doubles (see
    ``tests/test_claude_sdk_executor.py``) satisfy this Protocol
    structurally via ``SimpleNamespace`` / custom classes.
    """

    _query: _ClaudeQuery | None
    _transport: _ClaudeTransport | None

    async def connect(self) -> None: ...
    async def disconnect(self) -> None: ...
    async def query(
        self,
        prompt: str | AsyncIterator[_JsonObject],
        session_id: str = "",
    ) -> None: ...
    async def set_model(self, model: str | None) -> None: ...
    async def interrupt(self) -> None: ...
    async def get_mcp_status(self) -> Mapping[str, object]: ...
    async def reconnect_mcp_server(self, server_name: str) -> None: ...

    # receive_response yields heterogeneous SDK message objects — kept
    # as ``Any`` so the caller can ``isinstance``-narrow onto the SDK's
    # real types via ``_ClaudeSDK`` below without needing a union here.
    def receive_response(self) -> AsyncIterator[Any]: ...  # type: ignore[explicit-any]


class _StreamEventObj(Protocol):
    """Structural view of ``claude_agent_sdk.StreamEvent``."""

    event: dict[str, Any]  # type: ignore[explicit-any]  # SDK declares this as dict[str, Any]


class _AssistantMessageObj(Protocol):
    """Structural view of ``claude_agent_sdk.AssistantMessage``."""

    # Each content block is one of the SDK block classes; isinstance-narrowed
    # at the read sites below.
    content: list[Any]  # type: ignore[explicit-any]
    # The model the SDK actually used for this message, e.g.
    # ``"claude-opus-4-8"``. The only place the executor learns the concrete
    # model when the spec pins none and the gateway resolves it internally.
    model: str | None


class _UserMessageObj(Protocol):
    """Structural view of ``claude_agent_sdk.UserMessage``."""

    content: str | list[Any]  # type: ignore[explicit-any]


class _ResultMessageObj(Protocol):
    """Structural view of ``claude_agent_sdk.ResultMessage``."""

    result: str | None
    is_error: bool | None
    usage: dict[str, Any] | None  # type: ignore[explicit-any]


class _SystemMessageObj(Protocol):
    """Structural view of ``claude_agent_sdk.SystemMessage``."""

    subtype: str
    data: dict[str, Any]  # type: ignore[explicit-any]


class _TextBlockObj(Protocol):
    text: str


class _ThinkingBlockObj(Protocol):
    thinking: str


class _ToolUseBlockObj(Protocol):
    id: str
    name: str
    input: ToolArgs


class _ToolResultBlockObj(Protocol):
    tool_use_id: str
    content: str | list[dict[str, Any]] | None  # type: ignore[explicit-any]
    is_error: bool | None


class _ClaudeSDK(Protocol):
    """Structural view of the ``claude_agent_sdk`` module.

    Tests swap in a fake with matching attributes, so we mirror what the
    executor actually pulls off the module. The ``*Message`` / ``*Block``
    attributes are declared as ``type`` so they can be used both as
    ``isinstance`` second args and as Protocol-implementing factories.
    """

    # Factories / callables the executor invokes. ``Callable[..., X]``
    # expands to an implicit ``Any`` arg spec under
    # ``disallow_any_explicit`` — the SDK's construction kwargs are opaque
    # at our boundary so that's the right abstraction level here.
    ClaudeSDKClient: Callable[..., _ClaudeClient]  # type: ignore[explicit-any]
    ClaudeAgentOptions: Callable[..., Any]  # type: ignore[explicit-any]
    tool: Callable[..., Any]  # type: ignore[explicit-any]
    create_sdk_mcp_server: Callable[..., Any]  # type: ignore[explicit-any]

    # Classes used as isinstance second args. Declared as ``type`` so the
    # checker accepts them in isinstance() while the real attributes are
    # the SDK's concrete classes. Test doubles assign plain ``type``
    # objects which satisfy this shape.
    AssistantMessage: type
    UserMessage: type
    SystemMessage: type
    ResultMessage: type
    TextBlock: type
    ThinkingBlock: type
    ToolUseBlock: type
    ToolResultBlock: type


_CONNECT_TIMEOUT_SECONDS = 60.0
_QUERY_START_TIMEOUT_SECONDS = 30.0
_MCP_STATUS_TIMEOUT_SECONDS = 10.0
_MCP_RECONNECT_TIMEOUT_SECONDS = 30.0
# When the response stream is quiet for this long we emit a warning,
# but keep waiting — a long-running native tool can legitimately block
# the stream far longer than any fixed deadline.
_STREAM_IDLE_WARN_SECONDS = 600.0

# ── Multimodal content block conversion ──────────────────────


def _get_inline_data_uri_info(value: Any) -> tuple[str, int] | None:  # type: ignore[explicit-any]
    """If ``value`` contains an inline ``data:*;base64,...`` URI, return its
    ``(media_type, base64_char_count)``; otherwise ``None``.

    A resolved attachment block looks like:

    .. code-block:: text

        {"type": "input_image",
         "filename": "screenshot.png",
         "image_url": "data:image/png;base64,iVBORw0KGgoAAAANS...=="}   # ~520k chars

    (non-image files carry the same payload under ``file_data`` instead of
    ``image_url``.) Returns e.g. ``("image/png", 519324)`` — the media type and
    payload size used to build the compact
    ``[image: screenshot.png, image/png, 519324 base64 chars]`` placeholder,
    so the raw base64 never lands in the ``Conversation so far:`` prompt text.
    """
    if isinstance(value, str):
        parsed = _parse_replay_data_uri(value)
        if parsed is not None:
            return parsed.media_type, len(parsed.data)
        return None
    if isinstance(value, list):
        for item in value:
            found = _get_inline_data_uri_info(item)
            if found is not None:
                return found
        return None
    if isinstance(value, dict):
        for item in value.values():
            found = _get_inline_data_uri_info(item)
            if found is not None:
                return found
    return None


def _redact_inline_base64(value: Any) -> Any:  # type: ignore[explicit-any]
    """Deep-replace inline base64 attachment payloads with a compact
    ``[attachment: …]`` marker, recursing through dict/list values. The fallback
    path for values that reach ``json.dumps`` (nested dicts, non-block content)
    so a resolver-produced base64 payload does not survive serialization.

    Two shapes are redacted: a whole-string ``data:*;base64,...`` URI (the
    resolver form under ``image_url`` / ``file_data``), and an Anthropic content
    block ``{"type": "image"|"document", "source": {"type": "base64", ...}}``
    (what the ``Read`` tool returns for an image file, carried in a
    ``function_call_output``). Neither is redacted when it appears as a dict
    key, tuple member, or substring embedded mid-text (the runner never emits
    those)."""
    if isinstance(value, str):
        parsed = _parse_replay_data_uri(value)
        if parsed is None:
            return value
        return f"[attachment: {parsed.media_type}, {len(parsed.data)} base64 chars]"
    if isinstance(value, list):
        return [_redact_inline_base64(item) for item in value]
    if isinstance(value, dict):
        source = value.get("source")
        if (
            value.get("type") in ("image", "document")
            and isinstance(source, dict)
            and source.get("type") == "base64"
        ):
            media_type = source.get("media_type") or "application/octet-stream"
            data = source.get("data")
            payload_chars = len(data) if isinstance(data, str) else 0
            kind = "image" if value.get("type") == "image" else "attachment"
            return {
                "type": "text",
                "text": f"[{kind}: {media_type}, {payload_chars} base64 chars]",
            }
        return {key: _redact_inline_base64(item) for key, item in value.items()}
    return value


def _text_block(text: str) -> _JsonObject:
    """Build an Anthropic text content block holding *text*."""
    return {"type": "text", "text": text}


def _coalesce_text_blocks(blocks: list[_JsonObject]) -> list[_JsonObject]:
    """
    Merge runs of adjacent text blocks into one newline-joined block.

    Keeps the replayed transcript readable as prose and makes the
    text-only history render byte-identical to a plain string prompt.

    :param blocks: Anthropic content blocks in transcript order.
    :returns: The same sequence with consecutive text blocks merged.
    """
    merged: list[_JsonObject] = []
    for block in blocks:
        if block.get("type") == "text" and merged and merged[-1].get("type") == "text":
            merged[-1] = _text_block(f"{merged[-1]['text']}\n{block['text']}")
        else:
            merged.append(block)
    return merged


def _structured_history_block(block: _JsonObject) -> _JsonObject | None:
    """
    Convert a resolved history attachment to a real Anthropic block.

    :param block: A prior-turn content block carrying an inline data URI.
    :returns: The ``image``/``document`` block, or ``None`` when the block
        is not a convertible attachment shape — the caller then falls back
        to the compact text marker rather than dropping the attachment.
    """
    if block.get("type") not in ("input_image", "input_file"):
        return None
    try:
        # Covers a malformed data URI and a bad base64 payload alike
        # (``binascii.Error`` subclasses ``ValueError``).
        converted = _to_anthropic_content_blocks([block])
    except ValueError:
        return None
    return converted[0] if converted else None


def _render_prior_content_blocks(content: object) -> list[_JsonObject]:
    """Render one prior message's content for the ``Conversation so far:``
    replay as Anthropic content blocks.

    Why this exists: ``_build_prompt`` only serializes prior history when
    ``resume_session=False`` — a *fresh* SDK client that must replay existing
    multimodal history (forked/shared sessions, sub-agents with
    ``pass_history=True``, or a client restarted mid-session). By that point a
    historical image/file block's ``file_id`` has already been resolved to a
    ``data:<media>;base64,...`` URI.

    Those resolved attachments are replayed as **structured** ``image`` /
    ``document`` blocks, interleaved in order with the surrounding text, so the
    cold-started client can actually inspect the image instead of reading a
    description of it. Structured blocks are also what keeps the prompt small:
    ``json.dumps()``-ing the block flattened the whole base64 payload into
    prompt TEXT, so the model tokenized the bytes as text rather than counting
    them as an image — seven ~390KB PNGs expand to ~2.5M tokens, and one real
    shared session hit a 3.5M-token prompt against a 1M limit.

    Anything that cannot become a structured block never leaks bytes into text.
    A resolver-produced inline attachment *value* — a whole-string
    ``data:*;base64,...`` under ``image_url`` / ``file_data``, including nested
    in dict/list values — is redacted, and an unconvertible attachment falls
    back to a compact ``[image/attachment: <id>, <media_type>, <N> base64
    chars]`` marker that preserves *that an attachment was present* without its
    bytes. An attachment the resolver never inlined renders as the visible
    "could not be loaded" marker. (This does not attempt to cover non-resolver
    shapes such as a data URI used as a dict key, a tuple member, or a substring
    embedded mid-text — the runner never emits those.)
    """
    if isinstance(content, str):
        sanitized = _redact_inline_base64(content)
        return [_text_block(str(sanitized))]
    if not isinstance(content, list):
        return [_text_block(json.dumps(_redact_inline_base64(content), ensure_ascii=True))]

    rendered: list[_JsonObject] = []
    for raw_block in content:
        block = cast(_JsonObject, raw_block) if isinstance(raw_block, dict) else None
        if block is not None:
            block_type = block.get("type")
            text = block.get("text")
            if block_type in ("input_text", "output_text", "text") and isinstance(text, str):
                rendered.append(_text_block(str(_redact_inline_base64(text))))
                continue

            inline_data = _get_inline_data_uri_info(block)
            if inline_data is not None:
                structured = _structured_history_block(block)
                if structured is not None:
                    rendered.append(structured)
                    continue
                media_type, payload_chars = inline_data
                kind = "image" if block_type == "input_image" else "attachment"
                identifier = block.get("filename") or block.get("file_id") or block_type
                rendered.append(
                    _text_block(
                        f"[{kind}: {identifier}, {media_type}, {payload_chars} base64 chars]"
                    )
                )
                continue

            if block.get("file_id"):
                # No inline bytes and no resolved payload: the resolver never
                # inlined this attachment. Serializing the raw block would read
                # as if the attachment were present; say it was lost instead.
                rendered.append(_text_block(unresolved_attachment_marker(block)))
                continue

        rendered.append(
            _text_block(json.dumps(_redact_inline_base64(raw_block), ensure_ascii=True))
        )
    return rendered


def _parse_data_uri(uri: str) -> tuple[str, str]:
    """
    Parse a ``data:`` URI into ``(media_type, base64_data)``.

    :param uri: A data URI, e.g.
        ``"data:image/png;base64,iVBOR..."``.
    :returns: Tuple of ``(media_type, base64_payload)``.
    :raises ValueError: If the URI is not a valid ``data:`` URI.
    """
    if not uri.startswith("data:"):
        raise ValueError(f"Not a data URI: {uri[:40]!r}")
    header, _, payload = uri[5:].partition(",")
    media_type = header.replace(";base64", "")
    return media_type, payload


def _to_anthropic_content_blocks(
    blocks: Sequence[object],
) -> list[_JsonObject]:
    """
    Convert Responses API content blocks to Anthropic Messages
    API content block format.

    Mapping:

    - ``input_text`` / ``output_text`` → ``{"type": "text", ...}``
    - ``input_image`` (with ``image_url`` data URI) →
      ``{"type": "image", "source": {"type": "base64", ...}}``
    - ``input_file`` (with ``file_data`` data URI) →
      ``{"type": "document", "source": {"type": "base64", ...}}``

    :param blocks: Responses API content block dicts.
    :returns: Anthropic API content block dicts.
    """
    result: list[_JsonObject] = []
    for raw_block in blocks:
        if not isinstance(raw_block, dict):
            raise ValueError("Anthropic content blocks must be objects")
        block = cast(_JsonObject, raw_block)
        block_type = block.get("type")
        if block_type in ("input_text", "output_text", "text"):
            result.append({"type": "text", "text": block["text"]})
        elif block_type == "input_image":
            image_url = block.get("image_url")
            if not isinstance(image_url, str) or not image_url:
                raise ValueError(
                    "input_image block is missing the 'image_url' field. "
                    "Upload the image via the session files API and reference "
                    "it by file_id so the content resolver can inline it."
                )
            if not image_url.startswith("data:"):
                raise ValueError(
                    "input_image block has a URL instead of a data URI. "
                    "Upload the image via the session files API and reference "
                    "it by file_id instead."
                )
            media_type, data = _parse_data_uri(image_url)
            result.append(
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": media_type,
                        "data": data,
                    },
                }
            )
        elif block_type == "input_file":
            file_data = block.get("file_data")
            if not isinstance(file_data, str) or not file_data:
                raise ValueError(
                    "input_file block is missing the 'file_data' field. "
                    "Upload the file via the session files API and reference "
                    "it by file_id so the content resolver can inline it."
                )
            if not file_data.startswith("data:"):
                raise ValueError(
                    "input_file block has a URL instead of a data URI. "
                    "Upload the file via the session files API and reference "
                    "it by file_id instead."
                )
            media_type, data = _parse_data_uri(file_data)
            if media_type == "application/pdf":
                # Anthropic's base64 document source only accepts PDF.
                result.append(
                    {
                        "type": "document",
                        "source": {
                            "type": "base64",
                            "media_type": "application/pdf",
                            "data": data,
                        },
                    }
                )
            else:
                # All other text files (markdown, plain text, code, etc.)
                # must use Anthropic's "text" source type with decoded content.
                text_content = base64.b64decode(data).decode("utf-8", errors="replace")
                result.append(
                    {
                        "type": "document",
                        "source": {
                            "type": "text",
                            "media_type": "text/plain",
                            "data": text_content,
                        },
                    }
                )
    return result


async def _multimodal_message_iter(
    content_blocks: list[_JsonObject],
    *,
    session_id: str,
) -> AsyncIterator[_JsonObject]:
    """
    Yield a single structured user message dict for the Claude
    SDK's ``AsyncIterable[dict]`` query path.

    The SDK transport writes each yielded dict as a JSONL line to
    the CLI's stdin. The CLI forwards the content blocks to the
    Anthropic Messages API, which supports multimodal input.

    :param content_blocks: Anthropic API content block dicts
        (output of :func:`_to_anthropic_content_blocks`).
    :param session_id: The SDK session identifier.
    :yields: A single message dict.
    """
    yield {
        "type": "user",
        "message": {"role": "user", "content": content_blocks},
        "parent_tool_use_id": None,
        "session_id": session_id,
    }


# Diagnostic knob: when set (any truthy value), skip wrapping the CLI
# via ``create_exec_launcher``. Used to isolate whether the silent
# connect hang is sandbox-related vs. inside the binary itself.
_NO_SANDBOX_ENV = "OMNIGENT_CLAUDE_SDK_NO_SANDBOX"

# Env override for an explicit claude binary, mirroring codex's
# OMNIGENT_CODEX_PATH. Set this when claude lives on a PATH the host
# daemon doesn't inherit (e.g. an nvm-managed global bin dir).
_CLAUDE_PATH_ENV = "OMNIGENT_CLAUDE_PATH"


def _usage_from_observed_call(
    last_call_usage: dict[str, Any] | None,  # type: ignore[explicit-any]
    model: str | None,
) -> dict[str, Any] | None:  # type: ignore[explicit-any]
    """Synthesize turn usage from the last observed ``message_start`` call.

    Used when a turn ends without ``ResultMessage`` usage (early stream
    close, terminal error, executor exception): the per-call prompt size
    from the most recent ``message_start`` is the best available window
    fill, so the context-occupancy meter can still advance.

    :param last_call_usage: The last ``message_start`` event's
        ``message.usage`` dict, or ``None`` when no API call started.
    :param model: Harness-reported model for cost pricing, e.g.
        ``"claude-sonnet-4-20250514"``.
    :returns: A usage dict shaped like ``TurnComplete.usage``
        (``output_tokens`` reports 0 — unknown on an incomplete turn),
        or ``None`` when nothing was observed.
    """
    if last_call_usage is None:
        return None
    ctx_in = last_call_usage.get("input_tokens") or 0
    ctx_cc = last_call_usage.get("cache_creation_input_tokens") or 0
    ctx_cr = last_call_usage.get("cache_read_input_tokens") or 0
    # ``total_tokens`` is billing-shaped (non-cache input only, no output on
    # an incomplete turn); ``context_tokens`` is window fill, so it includes
    # the cache buckets. The two intentionally differ.
    return {
        "input_tokens": ctx_in,
        "output_tokens": 0,
        "total_tokens": ctx_in,
        "context_tokens": ctx_in + ctx_cc + ctx_cr,
        "model": model,
    }


def _sandbox_disabled_by_env() -> bool:
    """``True`` when the diagnostic bypass env var is set to a truthy
    value. Emits a WARNING on activation so CI output unambiguously
    confirms the bypass was in effect for a given run.
    """
    if os.environ.get(_NO_SANDBOX_ENV):
        logger.warning(
            "Sandbox bypass active (%s is set); skipping create_exec_launcher.",
            _NO_SANDBOX_ENV,
        )
        return True
    return False


def _claude_cli_sandbox_requested(spec: OSEnvSpec | None) -> bool:
    """
    CORAL(S113): whether *spec* asks for a CLI wrap that only a fault would skip.

    The operator's bypass, ``sandbox.type: none`` and a network-denying sandbox leave the CLI
    unwrapped by design. Keep in step with :func:`prepare_claude_cli_path`'s early returns.
    """
    if spec is None or spec.type != "caller_process" or os.environ.get(_NO_SANDBOX_ENV):
        return False
    sandbox_spec = spec.sandbox or OSEnvSandboxSpec()
    return sandbox_spec.type != "none" and sandbox_spec.allow_network


def _terminate_process_tree(process: _Process | None) -> None:
    _proc.terminate_tree(process)


def _kill_process_tree(process: _Process | None) -> None:
    _proc.kill_tree(process)


@contextmanager
def _unset_env_var(name: str) -> Iterator[None]:
    """
    Temporarily remove an env var from ``os.environ`` for the duration of
    the ``with`` block, then restore it (or leave it absent if it was not
    set before).

    Used around the claude-cli subprocess spawn to strip ``CLAUDECODE``
    when our own Python process is itself running under Claude Code — the
    child cli otherwise reports a "nested session" error. The SDK builds
    the child env as ``{**os.environ, **options.env, ...}``, so the only
    way to *remove* (not just override with ``""``) a key is to unset it
    in ``os.environ`` during the spawn.

    :param name: Env var name to remove for the block, e.g. ``"CLAUDECODE"``.
    :yields: Nothing; restores ``os.environ[name]`` on exit if it was set.
    """
    previous = os.environ.pop(name, None)
    try:
        yield
    finally:
        if previous is not None:
            os.environ[name] = previous


_CLOSE_ATTR: str = "close"
_TRANSPORT_ATTR: str = "transport"
_ACLOSE_ATTR: str = "aclose"


def _call_optional_method(obj: Any, name: str) -> None:  # type: ignore[explicit-any]
    """Call ``obj.<name>()`` if it exists and is callable, swallowing errors.

    Uses a runtime attribute name so this stays out of the
    ``getattr(..., "<literal>", ...)`` lint's crosshairs while still giving
    mypy a known shape (``Any`` at the boundary — the caller's concrete
    types don't declare the sync ``close`` hook we probe here).
    """
    method = getattr(obj, name, None)
    if callable(method):
        with suppress(Exception):
            method()


def _best_effort_close(resource: _Stream | _Process) -> None:
    """Invoke a best-effort synchronous close on an SDK-internal handle.

    The current SDK exposes ``aclose`` (async) on streams and a no-``close``
    anyio ``Process``; older revs and test doubles may still ship a sync
    ``close`` method. We probe for it via ``hasattr``-style helpers and
    swallow any failures — this runs only on the force-close teardown path
    where the alternative is leaking the handle.
    """
    _call_optional_method(resource, _CLOSE_ATTR)
    transport_obj = getattr(resource, _TRANSPORT_ATTR, None)
    if transport_obj is not None:
        _call_optional_method(transport_obj, _CLOSE_ATTR)


# Default model for the Databricks-profile gateway path (no gateway base URL
# supplied directly), used when no spec/cfg model is set. On the ucode-cached
# path the Omnigent producer resolves the model instead (see workflow.py).
_CLAUDE_API_KEY_HELPER_ENV_KEY = "OMNIGENT_CLAUDE_API_KEY_HELPER"


@dataclass
class _ClaudeClientState:
    client: _ClaudeClient
    model: str | None
    loop: asyncio.AbstractEventLoop | None = None
    task: asyncio.Task[None] | None = None
    effort: str | None = None
    # Host-reported account state of each Claude MCP server when last checked.
    mcp_auth: dict[str, str] = field(default_factory=dict)


def _claude_mcp_auth_statuses() -> dict[str, str]:
    """The host sign-in manager's account state for each Claude MCP server, by name."""
    try:
        from omnigent.host.mcp_inventory import read_auth_status_overlay

        overlay = read_auth_status_overlay(pathlib.Path.home())
    except Exception:
        logger.warning("Reading MCP auth status failed", exc_info=True)
        return {}
    return {
        name: fields["auth_status"]
        for (harness, name), fields in overlay.items()
        if harness == "claude"
    }


def _inventory_mcp_server_name(live_name: str) -> str:
    """The host inventory's name for a server; the CLI adds ``plugin:<plugin>:`` to plugin ones."""
    prefix, plugin_sep, rest = live_name.partition(":")
    if prefix == "plugin" and plugin_sep:
        _plugin, server_sep, server = rest.partition(":")
        if server_sep and server:
            return server
    return live_name


async def _reconnect_failed_mcp_servers(client: _ClaudeClient, names: set[str]) -> set[str]:
    """Reconnect the named servers the CLI reports failed; return those to check again.

    :raises TimeoutError: The CLI did not answer in time and is still busy with the request.
    """
    try:
        response = await asyncio.wait_for(
            client.get_mcp_status(), timeout=_MCP_STATUS_TIMEOUT_SECONDS
        )
    except TimeoutError:
        raise
    except Exception:
        logger.warning("Reading MCP status before reconnect failed", exc_info=True)
        return names
    retry: set[str] = set()
    # (live CLI name, host inventory name) of each server to reconnect.
    failed: list[tuple[str, str]] = []
    servers = response.get("mcpServers")
    for server in servers if isinstance(servers, list) else []:
        live_name = server.get("name") if isinstance(server, Mapping) else None
        if not isinstance(live_name, str):
            continue
        name = _inventory_mcp_server_name(live_name)
        if name not in names:
            continue
        status = server.get("status")
        if status == "pending":
            retry.add(name)
        elif status in ("failed", "needs-auth"):
            failed.append((live_name, name))

    # The CLI handles control requests one at a time, so the reconnects share one budget.
    async with asyncio.timeout(_MCP_RECONNECT_TIMEOUT_SECONDS):
        for live_name, name in failed:
            try:
                await client.reconnect_mcp_server(live_name)
            except Exception:
                logger.warning("Reconnecting MCP server %r failed", live_name, exc_info=True)
                retry.add(name)
    return retry


@dataclass(frozen=True)
class PreparedClaudeCli:
    """Result of wrapping the Claude CLI in an Omnigent sandbox.

    :param cli_path: Path the SDK should exec for the Claude CLI.  May be the
        original system CLI or a generated wrapper script that applies the
        sandbox before exec-ing the real binary.  ``None`` when no CLI is
        available (no system ``claude`` on PATH).
    :param enable_native_tools: ``True`` when the sandbox is active and it is
        safe for the SDK to enable the built-in native OS tools (Bash, Read,
        Edit, …).  ``False`` when the sandbox cannot be applied (e.g. network
        denied, unsupported platform) — the caller should then leave native
        tools disabled.
    :param config_isolated: CORAL(S113): the wrap keeps the CLI's Claude config in its
        launcher's private dir.
    """

    cli_path: str | None
    enable_native_tools: bool
    config_isolated: bool = False  # CORAL(S113)


def _ensure_sdk() -> ModuleType:
    """Import and return the claude_agent_sdk module, raising a clear error if missing."""
    try:
        import claude_agent_sdk

        return claude_agent_sdk
    except ImportError as exc:
        raise ImportError(
            "ClaudeSDKExecutor requires the 'claude-agent-sdk' package. "
            "Install it with: pip install claude-agent-sdk"
        ) from exc


# Tools of the in-process ``omnigent`` MCP server; only these come back through
# ``_stable_tool_executor``. Every other tool (Claude Code's ``Skill`` and
# ``ToolSearch``, or a user-configured MCP server) runs inside the CLI.
_OMNIGENT_MCP_PREFIX = "mcp__omnigent__"


def _tool_call_metadata(tool_block: _ToolUseBlockObj) -> dict[str, object]:
    """Metadata for a ``ToolCallRequest``: its ``call_id``, and whether the CLI runs it.

    A call the CLI runs itself is marked ``internally_executed`` so the
    executor adapter keeps its id out of the dispatch-correlation queue.
    Otherwise the id is never consumed, and every later Omnigent tool
    dispatch in the turn pairs with the previous call's id, which records
    each call twice under mismatched ids.
    """
    return {
        "call_id": tool_block.id,
        "internally_executed": not tool_block.name.startswith(_OMNIGENT_MCP_PREFIX),
    }


def _mark_mcp_error(response: McpResponse) -> McpResponse:
    """Flag an SDK MCP handler response as a tool error, in both spellings.

    ``claude_agent_sdk.create_sdk_mcp_server`` builds the wire result from the
    handler's snake_case ``is_error`` only (``CallToolResult(isError=
    result.get("is_error", False))``), so a response carrying just ``isError``
    reaches the model as a success. ``isError`` is kept for native MCP
    clients and existing readers of these dicts.
    """
    response["is_error"] = True
    response["isError"] = True
    return response


def _build_mcp_tools(
    tool_schemas: list[ToolSpec],
    tool_executor: ToolExecutor | None,
) -> list[SdkMcpTool]:
    """Build SdkMcpTool objects from Omnigent tool schemas.

    Each tool is backed by a handler that calls the Omnigent tool_executor
    callback, which routes through the Session's tool registry (and thus
    respects policies, history recording, etc.).
    """
    sdk = cast(_ClaudeSDK, _ensure_sdk())

    mcp_tools: list[SdkMcpTool] = []
    for schema in tool_schemas:
        raw_name = schema.get("name")
        raw_desc = schema.get("description")
        # ``sdk.tool()`` requires ``str`` for name/description — the SDK
        # itself does not accept ``None``. Omnigent tool schemas always
        # carry a ``name`` (see ``Tool.tool_schema``); fall back to ``""``
        # only for the description, which is legitimately optional.
        tname: str = raw_name if isinstance(raw_name, str) else ""
        tdesc: str = raw_desc if isinstance(raw_desc, str) else ""
        tparams = schema.get("parameters", {"type": "object", "properties": {}})

        def _make_handler(tool_name: str) -> Callable[[ToolArgs], Awaitable[McpResponse]]:
            async def handler(args: ToolArgs) -> McpResponse:
                if tool_executor is None:
                    return _mark_mcp_error(
                        {
                            "content": [
                                {
                                    "type": "text",
                                    "text": json_dumps_transport_safe(
                                        {"error": f"No tool executor for '{tool_name}'"}
                                    ),
                                }
                            ],
                        }
                    )
                try:
                    # ``tool_executor`` is declared as ``Awaitable[ToolResult]``
                    # so we always await. The isinstance guard below preserves
                    # the pre-refactor safety net for unexpected non-dict
                    # runtime returns without confusing the type checker.
                    raw = await tool_executor(tool_name, args)
                    result: ToolResult = raw if isinstance(raw, dict) else {"result": raw}
                    image_result = decode_mcp_image_result(result)
                    if image_result is not None:
                        response: McpResponse = image_result.to_mcp()
                        # The SDK server reads snake_case; native MCP clients use isError.
                        response["is_error"] = image_result.is_error
                        return response
                    response = {
                        "content": [{"type": "text", "text": json_dumps_transport_safe(result)}],
                    }
                    if result.get("blocked") is True or (
                        "error" in result and result.get("error")
                    ):
                        return _mark_mcp_error(response)
                    return response
                except Exception as exc:  # noqa: BLE001 — tool handler converts any error to MCP error response
                    return _mark_mcp_error(
                        {
                            "content": [
                                {
                                    "type": "text",
                                    "text": json_dumps_transport_safe({"error": str(exc)}),
                                }
                            ],
                        }
                    )

            return handler

        decorated = sdk.tool(tname, tdesc, tparams)(_make_handler(tname))
        mcp_tools.append(decorated)
    return mcp_tools


def _augment_system_prompt_for_omnigent_mcp_tools(
    system_prompt: str,
    tool_schemas: list[ToolSpec],
) -> str:
    """
    Add Claude SDK-specific MCP tool-name guidance to the system prompt.

    Omnigent schemas use bare names such as ``sys_session_send``. The
    Claude SDK exposes tools from our in-process MCP server to the model
    as ``mcp__omnigent__<bare_name>``. Bundled agent prompts and skills use
    bare names because other executors call those directly, so the SDK needs
    a bridge note to stop the model from trying a non-existent bare tool first.
    """
    tool_names = [
        name for schema in tool_schemas if isinstance((name := schema.get("name")), str) and name
    ]
    if not tool_names:
        return system_prompt

    examples = [
        name
        for name in ("sys_session_rename", "sys_session_send", "sys_session_create")
        if name in tool_names
    ]
    if examples:
        example_text = "; ".join(
            f"use `mcp__omnigent__{name}` when instructions say `{name}`" for name in examples
        )
        note = (
            "Claude SDK tool naming: Coral tools are exposed as MCP tools. "
            f"{example_text}. For any other Coral tool, use "
            "`mcp__omnigent__<tool_name>` rather than the bare name."
        )
    else:
        note = (
            "Claude SDK tool naming: Coral tools are exposed as MCP tools. "
            "When instructions mention a bare Coral tool name, invoke "
            "`mcp__omnigent__<tool_name>` rather than the bare name."
        )

    if not system_prompt:
        return note
    return f"{system_prompt.rstrip()}\n\n{note}"


def _find_system_claude() -> str | None:
    """Find a system-installed ``claude`` CLI binary.

    Resolves via the ``OMNIGENT_CLAUDE_PATH`` override, then ``PATH``, then
    common global install dirs — so an nvm/npm-installed claude off the host
    daemon's frozen ``PATH`` is still found. Prefers the system install over
    the SDK's bundled CLI because the bundled version may be older and send
    beta flags the Databricks gateway doesn't support. Returns the absolute
    path, or ``None`` if not found.
    """
    return resolve_cli_binary("claude", env_var=_CLAUDE_PATH_ENV)


# DATABRICKS-PATCH(claude-sdk-live-model-discovery)
def _resolve_databricks_claude_model(profile: str | None) -> str:
    """Resolve the launch model from what the workspace serves.

    The bundled MLflow catalog is a third-party listing whose Databricks ids use
    the legacy ``databricks-`` spelling the gateway now answers with ``501 … Use
    Unity Catalog model services (v3)``. Resolve from the live Unity Catalog
    listing as claude-native does, keeping the catalog as the last resort.

    :param profile: Databricks CLI profile backing the gateway.
    :returns: The model id to launch on.
    """
    try:
        from omnigent.models.databricks_model_discovery import discover_databricks_claude_catalog
        from omnigent.runtime.credentials.databricks import resolve_databricks_workspace

        creds = resolve_databricks_workspace(profile)
        families = discover_databricks_claude_catalog(creds.host, creds.token).families
        # The precedence claude-native itself falls back to.
        for tier in ("opus", "sonnet", "haiku", "fable"):
            servable = families.get(tier)
            if servable:
                logger.warning(
                    "claude-sdk: no model pinned for this session; resolved %r "
                    "from the %r workspace catalog (%s precedence). Pin a model "
                    "in the agent spec or dispatch to control which endpoint "
                    "is billed.",
                    servable,
                    profile or "DEFAULT",
                    " > ".join(("opus", "sonnet", "haiku", "fable")),
                )
                return servable
    except Exception:  # the bundled catalog is the last resort
        logger.warning(
            "claude-sdk: live Databricks model discovery failed for profile %r; "
            "falling back to the bundled catalog",
            profile,
            exc_info=True,
        )
    resolved = model_catalog.resolve_catalog_model("databricks", family="claude").model_id
    logger.warning(
        "claude-sdk: no model pinned for this session; resolved %r from the "
        "bundled catalog. Pin a model in the agent spec or dispatch to "
        "control which endpoint is billed.",
        resolved,
    )
    return resolved


class _GatewayModelVocabulary(NamedTuple):
    """How a gateway's served ids map onto Claude Code's model vocabulary.

    :param alias_pins: ``{env_var: served_id}`` pinning each family alias.
    :param model_overrides: ``{canonical_id: served_id}`` rewrites for the ids
        Claude Code names itself.
    """

    alias_pins: dict[str, str]
    model_overrides: dict[str, str]


_EMPTY_GATEWAY_VOCABULARY = _GatewayModelVocabulary(alias_pins={}, model_overrides={})


def _gateway_model_vocabulary(
    base_url: str, auth_command: str | None, bearer: str | None = None
) -> _GatewayModelVocabulary:
    """Read Claude Code's model vocabulary off a gateway's model listing.

    Claude Code resolves a family alias — ``opus`` / ``sonnet`` / ``haiku`` /
    ``fable`` — through ``ANTHROPIC_DEFAULT_<FAMILY>_MODEL``, and every alias
    surface speaks them: the refusal-fallback (a flagged message re-issues on
    Opus), ``/model``, ``Agent``-tool spawns. Unpinned, an alias resolves to a
    canonical vendor id (``claude-opus-4-8``). A gateway that serves Claude under
    its own ids (``databricks-claude-opus-4-8``) rejects that with
    ``model_not_found``, and a refusal-fallback then kills the whole turn. List
    what the gateway serves and pin each alias to it.

    Claude Code reaches a model two ways, and a gateway with its own ids
    breaks both. Through a family alias — ``opus`` / ``sonnet`` / ``haiku`` /
    ``fable``, resolved via ``ANTHROPIC_DEFAULT_<FAMILY>_MODEL`` and spoken by
    ``/model`` and ``Agent``-tool spawns — which resolves to a canonical vendor
    id when unpinned. And by naming a canonical id itself: the refusal-fallback
    re-issues a safeguard-flagged turn on a model from a route table internal
    to the CLI. Either way the gateway answers ``model_not_found`` and the turn
    dies. One listing answers both: pin the aliases, and hand Claude Code the
    canonical-to-served rewrites for the ids it names on its own.

    :param base_url: The gateway's ``ANTHROPIC_BASE_URL``.
    :param auth_command: The gateway ``apiKeyHelper`` command; minted into the
        bearer the listing is fetched with.
    :param bearer: CORAL(S124): the credential itself, from the executor's credential
        proxy, in place of *auth_command*.
    :returns: The pins and rewrites the listing supports. Empty — leaving
        today's behavior — when the gateway lists no Claude models or the
        listing cannot be fetched.
    """
    from omnigent.onboarding.provider_config import ANTHROPIC_FAMILY, GATEWAY_KIND

    # CORAL(S124): a static key is passed as its value, stripped as the proxy sends it, so
    # listing models starts no shell; a literal that is not one token is never sent
    if (
        bearer is None
        and auth_command is not None
        and static_printf_value(auth_command) is not None
    ):
        bearer = static_credential_literal(auth_command)
        if bearer is None:
            logger.warning(
                "claude-sdk: the gateway's static key is not one printable token; leaving "
                "ANTHROPIC_DEFAULT_*_MODEL and modelOverrides unset"
            )
            return _EMPTY_GATEWAY_VOCABULARY
    provider = model_catalog.ResolvedModelProvider(
        kind=GATEWAY_KIND,
        family=ANTHROPIC_FAMILY,
        base_url=base_url,
        api_key=bearer or None,
        auth_command=auth_command if bearer is None else None,
        detail="claude-sdk gateway transport",
    )
    try:
        listing = model_catalog.listing_for_provider(provider)
    except Exception as exc:  # noqa: BLE001 — best-effort; unpinned aliases are the safe default
        # CORAL(S124): by type only; the failure's text may quote the credential command
        logger.warning(
            "claude-sdk: could not list the gateway's models (%s); leaving "
            "ANTHROPIC_DEFAULT_*_MODEL and modelOverrides unset",
            type(exc).__name__,
        )
        return _EMPTY_GATEWAY_VOCABULARY
    served = [entry.id for entry in listing.models if entry.family == "claude"]
    return _GatewayModelVocabulary(
        alias_pins={
            ALIAS_MODEL_ENV_VARS[alias]: model_id
            for alias, model_id in served_alias_pins(served).items()
        },
        model_overrides=served_canonical_overrides(served),
    )


def _claude_settings_payload(
    api_key_helper: str | None, model_overrides: dict[str, str]
) -> str | None:
    """Serialize the invocation-local settings Claude Code launches with.

    :param api_key_helper: The gateway ``apiKeyHelper`` command, or ``None``.
    :param model_overrides: Canonical-to-served model id rewrites.
    :returns: Compact JSON for ``ClaudeAgentOptions.settings``, or ``None``
        when there is nothing to configure.
    """
    settings: dict[str, Any] = {}
    if api_key_helper:
        settings["apiKeyHelper"] = api_key_helper
    if model_overrides:
        settings["modelOverrides"] = model_overrides
    return json.dumps(settings, separators=(",", ":")) if settings else None


# CORAL(S124): shim stops that outlive a cancelled ``close()``, held so they run to the end
_SHIM_STOPS: set[asyncio.Future[None]] = set()


class _CredentialExposedError(RuntimeError):
    """CORAL(S124): a proxied CLI's launch would still hold the model key; names no value."""


class _CredentialProxyRefusedError(RuntimeError):
    """CORAL(S125): a credential proxy that may not start, or could not; names no value."""


def _keep_loopback_unproxied(env: dict[str, str]) -> None:
    """CORAL(S124): append loopback to the ``NO_PROXY`` a CLI would inherit, in both spellings.

    The CLI reaches its credential proxy over plain loopback HTTP, which an inherited
    ``HTTP_PROXY`` would otherwise intercept.

    :param env: The CLI's ``options.env``, changed in place.
    """
    inherited = [env.get(name) or os.environ.get(name) or "" for name in _NO_PROXY_ENV]
    for name, own, other in zip(_NO_PROXY_ENV, inherited, reversed(inherited), strict=True):
        hosts = [host.strip() for host in (own or other).split(",") if host.strip()]
        hosts += [host for host in _LOOPBACK_NO_PROXY if host not in hosts]
        env[name] = ",".join(hosts)


def _is_first_party_url(url: str) -> bool:
    """CORAL(S124): whether the pinned CLI would take *url* for the Anthropic API itself.

    The CLI compares the URL's host, a non-default port included, with the API's. A URL with
    userinfo, a backslash or whitespace is never first-party here: two parsers could read
    different hosts in it, and a wrong "no" only leaves the CLI on its custom-endpoint
    behaviour.

    :param url: A base URL, e.g. ``"https://api.anthropic.com"``.
    :returns: Whether a CLI behind the proxy for *url* may treat the proxy as that API.
    """
    if "@" in url or "\\" in url or any(character.isspace() for character in url):
        return False
    try:
        parts = urlsplit(url)
        port = parts.port
    except ValueError:
        return False
    default_port = {"https": 443, "http": 80}.get(parts.scheme.lower())
    return (
        default_port is not None
        and parts.hostname == _ANTHROPIC_API_HOST
        and port in (None, default_port)
    )


def _proxy_for_upstream(upstream_url: str, environ: Mapping[str, str]) -> tuple[str, str] | None:
    """CORAL(S124): the proxy *environ* names for *upstream_url*, as a client reads it there.

    The scheme's own variable wins over ``ALL_PROXY``. As in urllib, a lower-case name that
    is set, even to nothing, hides its upper-case twin, so an empty one means "no proxy".
    ``NO_PROXY`` is honoured here because an explicit proxy skips it, and a loopback
    upstream never gets a proxy.

    :param upstream_url: The proxy's upstream, e.g. ``"https://gateway.example/anthropic"``.
    :param environ: A harness environment snapshot.
    :returns: The variable read (CORAL(S125)) and its proxy URL, possibly with userinfo,
        e.g. ``("HTTPS_PROXY", "http://proxy.example:3128")``; ``None`` when none applies.
    """
    from omnigent_client._http import is_loopback_url

    def setting(name: str) -> tuple[str, str]:
        spelling = name if name in environ else name.upper()
        return spelling, environ.get(spelling, "")

    upstream = urlsplit(upstream_url)
    proxy = setting(f"{upstream.scheme}_proxy")
    proxy = proxy if proxy[1] else setting("all_proxy")
    if not proxy[1] or is_loopback_url(upstream_url):
        return None
    host = upstream.hostname or ""
    target = f"{host}:{upstream.port}" if upstream.port else host
    bypasses = {"no": setting("no_proxy")[1]}
    # Missing from typeshed stubs; present at runtime.
    bypass = urllib.request.proxy_bypass_environment  # type: ignore[missing-attribute]
    return None if bypass(target, bypasses) else proxy


def _claude_user_settings_env(
    cwd: str | None = None, environ: Mapping[str, str] | None = None
) -> dict[str, str]:
    """Read the ``env`` block of Claude Code's user ``settings.json``.

    The file is located by
    :func:`omnigent.onboarding.ambient.read_claude_user_settings`.

    :param cwd: The CLI's working directory, e.g. ``"/home/user/repo"``;
        ``None`` means this process's working directory.
    :param environ: CORAL(S125): where the file's location is read; ``os.environ`` when ``None``.
    :returns: The string-valued entries, e.g.
        ``{"ANTHROPIC_BEDROCK_BASE_URL": "https://gateway.example"}``; empty
        when the file is missing, unreadable, or has no ``env`` object.
    """
    from omnigent.onboarding.ambient import read_claude_user_settings

    settings = read_claude_user_settings(cwd, environ)  # CORAL(S125)
    env = settings.get("env") if settings is not None else None
    if not isinstance(env, dict):
        return {}
    return {
        key: value for key, value in env.items() if isinstance(key, str) and isinstance(value, str)
    }


class _SettingsEnv(NamedTuple):
    """CORAL(S125): the user's settings env as a Coral CLI behind the credential proxy gets it.

    :param cli: The names the CLI's own environment takes, e.g. ``{"ANTHROPIC_MODEL": ...}``.
    :param upstream: The endpoint, proxy and CA names the proxy's upstream hop takes.
    :param ignored: Endpoint and network names taken by neither, for a warning by name.
    """

    cli: dict[str, str]
    upstream: dict[str, str]
    ignored: tuple[str, ...]


def _is_outside(path: str, directory: str) -> bool:
    """CORAL(S125): whether resolving *path* never enters *directory*.

    Each prefix of *path* is resolved one link at a time, so a link that leads through
    *directory* counts as inside it, whatever it points at afterwards. On macOS names
    are compared without case, as its default volumes compare them.

    :param path: An absolute path, e.g. ``"/home/user/.claude/settings.json"``.
    :param directory: A directory, e.g. a step's worktree.
    :returns: ``False`` also when either cannot be resolved.
    """

    def spelled(text: str) -> str:
        return text.casefold() if _PATHS_IGNORE_CASE else text

    try:
        root = spelled(os.path.realpath(directory))
        pending = list(reversed(pathlib.PurePath(path).parts[1:]))
        current, links = os.sep, 0
        while pending:
            part = pending.pop()
            if part == os.pardir:
                current = os.path.dirname(current)
                continue
            current = os.path.join(current, part)
            if f"{spelled(current)}{os.sep}".startswith(f"{root.rstrip(os.sep)}{os.sep}"):
                return False
            try:
                if not stat.S_ISLNK(os.lstat(current).st_mode):
                    continue
            except (FileNotFoundError, NotADirectoryError):
                continue  # nothing there to follow; any other failure is not "outside"
            links += 1
            if links > _MAX_FOLLOWED_LINKS:
                return False
            target = pathlib.PurePath(os.readlink(current))
            current = os.sep if target.is_absolute() else os.path.dirname(current)
            pending.extend(reversed(target.parts[1:] if target.is_absolute() else target.parts))
    except (OSError, ValueError):
        return False
    return True


def _settings_file_steers_upstream(cwd: str | None, environ: Mapping[str, str]) -> bool:
    """CORAL(S125): whether the user's settings file may say where the real credential goes.

    Only a file a step can neither place nor write: under an absolute ``CLAUDE_CONFIG_DIR``,
    or the default one in the user's home, and outside the CLI's working directory. A
    relative value, a leading ``~`` included, is read from that directory.

    :param cwd: The CLI's working directory; ``None`` means this process's.
    :param environ: The host's ``CLAUDE_CONFIG_DIR`` and ``HOME``, e.g. from before a scrub.
    :returns: Whether its endpoint, proxy and CA names are taken.
    """
    from omnigent.onboarding.ambient import claude_user_settings_path

    configured = environ.get("CLAUDE_CONFIG_DIR")
    if configured and not os.path.isabs(configured):
        return False
    workdir = cwd or os.getcwd()
    # Joined to the cwd, as the CLI would read a default dir under a relative home.
    settings_path = os.path.join(workdir, claude_user_settings_path(cwd, environ))
    return _is_outside(settings_path, workdir)


def _is_bare_proxy_setting(name: str, value: str) -> bool:
    """CORAL(S125): whether a proxy setting holds nothing a CLI should not: no userinfo
    (an ``@``, with or without a scheme), and for a proxy URL no path beyond ``/``, query
    or fragment, where a credential can sit too.

    :param name: A proxy name, e.g. ``"HTTPS_PROXY"`` or ``"no_proxy"``.
    :param value: Its value, e.g. ``"http://proxy.example:3128"``.
    """
    if "@" in value:
        return False
    if name.upper() == "NO_PROXY":
        return True  # a host list, where a slash is a network's prefix length
    location = value.strip().split("://", 1)[-1].removesuffix("/")
    return not any(mark in location for mark in "/?#")


def _allowed_settings_env(
    block: Mapping[str, str], *, trusted: bool, cwd: str | None
) -> _SettingsEnv:
    """CORAL(S125): split the user's settings env between a Coral CLI and its credential proxy.

    The CLI takes model routing, opt-outs that are switched on and, from a trusted file, bare
    proxy names (:func:`_is_bare_proxy_setting`) and the CA file. The proxy's upstream hop
    takes the trusted file's endpoint, proxy names (upper or lower case, whatever they hold)
    and CA file. Every other name goes to neither: provider switches, credentials and headers
    among them.

    :param block: The ``env`` object of the user's ``settings.json``.
    :param trusted: Whether :func:`_settings_file_steers_upstream` holds for the file.
    :param cwd: The CLI's working directory; ``None`` means this process's.
    :returns: The split, with the endpoint and network names it ignored.
    """
    cli: dict[str, str] = {}
    upstream: dict[str, str] = {}
    ignored: list[str] = []
    workdir = cwd or os.getcwd()
    for name, value in block.items():
        if name in _SETTINGS_ENV_MODEL_NAMES:
            cli[name] = value
        elif name in _SETTINGS_ENV_OPT_OUT_NAMES:
            if value.lower() in _SETTINGS_ENV_SWITCH_VALUES:
                cli[name] = value
        elif name == _SETTINGS_ENV_BASE_URL and trusted:
            upstream[name] = value
        elif name in _SETTINGS_ENV_PROXY_NAMES and trusted:
            upstream[name] = value
            if _is_bare_proxy_setting(name, value):
                cli[name] = value
        elif (
            name == _SETTINGS_ENV_CA_FILE
            and trusted
            and os.path.isabs(value)
            and _is_outside(value, workdir)
        ):
            upstream[name] = cli[name] = value
        elif name in (_SETTINGS_ENV_BASE_URL, _SETTINGS_ENV_CA_FILE, *_SETTINGS_ENV_PROXY_NAMES):
            ignored.append(name)
    return _SettingsEnv(cli, upstream, tuple(ignored))


def _resolve_gateway_env(
    profile: str | None = None,
    *,
    host_override: str | None = None,
    base_url_override: str | None = None,
    auth_command_override: str | None = None,
    auth_refresh_interval_ms: int | None = None,
) -> dict[str, str]:
    """Build Claude Code gateway env from the gateway transport values.

    The vendor-neutral gateway transport is a base URL + a bearer-token
    command + a refresh TTL. When the gateway base URL and auth command are
    supplied directly (the generic-provider producer, or ucode), they are
    used verbatim. When only a Databricks profile is supplied (no override
    values), the Databricks-specific fallback derives both from the profile's
    workspace **host** (see
    :func:`~omnigent.inner.databricks_executor._databricks_gateway_host`).
    Only the host is needed: the bearer token is minted at request time by
    the generated auth command, so OAuth U2M profiles (``auth_type =
    databricks-cli``, no static ``token`` field) resolve too. Returns an
    empty dict if no workspace host can be resolved.

    The bearer token itself is not returned. Claude Code receives an
    invocation-local ``apiKeyHelper`` setting and refresh TTL instead, so
    the CLI can periodically re-run the auth command during long sessions
    instead of inheriting a one-hour token snapshot.

    :param profile: Optional Databricks profile name from
        ``~/.databrickscfg`` (used only on the profile-derivation fallback).
    :param host_override: Gateway workspace host origin, e.g.
        ``"https://example.databricks.com"``. When set, skips
        ``~/.databrickscfg`` host lookup and requires the gateway base URL
        and auth command values.
    :param base_url_override: When set, use this as ``ANTHROPIC_BASE_URL``
        instead of deriving it from the profile host.  Populated from
        ``HARNESS_CLAUDE_SDK_GATEWAY_BASE_URL``.
    :param auth_command_override: Shell command that prints a bearer token,
        e.g. ``"databricks auth token --host ..."`` or ``"printf %s sk-..."``.
    :param auth_refresh_interval_ms: Refresh TTL in milliseconds, e.g.
        ``900000``.
    :returns: Environment values plus an internal apiKeyHelper command
        consumed by :meth:`ClaudeSDKExecutor.run_turn`, or ``{}`` when
        no credentials are available.
    :raises OSError: If a gateway host is present but missing the
        corresponding base URL or auth command.
    """
    host = host_override.rstrip("/") if host_override else None
    generic_provider = (
        host is None and base_url_override is not None and auth_command_override is not None
    )
    if generic_provider:
        # Generic-provider gateway: explicit base_url + auth command,
        # no Databricks host or profile required (e.g. ApiKeyAuth with
        # a mock LLM server URL).
        assert base_url_override is not None and auth_command_override is not None
        base_url = base_url_override
        auth_command = auth_command_override
    elif host is None:
        # Only the workspace host is needed here: the auth command mints the
        # bearer at request time. Resolving the host (rather than a static
        # ``(host, token)`` credential pair) keeps OAuth U2M profiles working
        # — they carry a ``host`` but no ``token`` field, so a token-requiring
        # lookup would fail even though ``databricks auth token`` succeeds.
        # Same derivation the codex gateway path uses.
        try:
            from .databricks_executor import _databricks_gateway_host

            host = _databricks_gateway_host(profile)
        except ImportError:
            host = None

        if not host:
            return {}
        host = host.rstrip("/")
        base_url = (
            base_url_override if base_url_override is not None else f"{host}/ai-gateway/anthropic"
        )
        auth_command = (
            auth_command_override
            if auth_command_override is not None
            else _databricks_claude_auth_command(host, profile)
        )
    else:
        if base_url_override is None:
            raise OSError(
                "ClaudeSDKExecutor(gateway=True) with a gateway workspace host "
                "requires HARNESS_CLAUDE_SDK_GATEWAY_BASE_URL."
            )
        if auth_command_override is None:
            raise OSError(
                "ClaudeSDKExecutor(gateway=True) with a gateway workspace host "
                "requires HARNESS_CLAUDE_SDK_GATEWAY_AUTH_COMMAND."
            )
        base_url = base_url_override
        auth_command = auth_command_override

    gateway_env = {
        "ANTHROPIC_BASE_URL": base_url,
        "CLAUDE_CODE_API_KEY_HELPER_TTL_MS": str(
            auth_refresh_interval_ms or _GATEWAY_AUTH_REFRESH_MS
        ),
        _CLAUDE_API_KEY_HELPER_ENV_KEY: auth_command,
    }
    if not generic_provider:
        gateway_env[_ANTHROPIC_CUSTOM_HEADERS_ENV] = _DATABRICKS_CODING_AGENT_HEADER
    # DATABRICKS-PATCH(claude-sdk-gateway-betas)
    # Blanket-disabling betas makes Claude Code strip `interleaved-thinking`,
    # after which the Databricks gateway rejects the malformed thinking blocks
    # with `400 messages.N.content.0.type: Expected 'thinking'`. claude-native
    # already fixed this by negotiating betas with the gateway instead
    # (`claude_native.py` CLAUDE_CODE_USE_GATEWAY=1); claude-sdk — the harness
    # behind Polly and Debby — never got that change. Scope it to a real
    # Databricks Unity Gateway base URL so a generic gateway (or a mock server)
    # that cannot negotiate betas keeps the original workaround.
    if is_databricks_ai_gateway_url(base_url):
        gateway_env["CLAUDE_CODE_USE_GATEWAY"] = "1"
        gateway_env[_ANTHROPIC_CUSTOM_HEADERS_ENV] = with_gateway_attribution_lines(
            gateway_env.get(_ANTHROPIC_CUSTOM_HEADERS_ENV),
            CLAUDE_CODE_AGENT,
            via_ug=is_ug_route(base_url),
            client_surface=harness_client_surface(),
        )
    else:
        gateway_env["CLAUDE_CODE_DISABLE_EXPERIMENTAL_BETAS"] = "1"
    return gateway_env


def _databricks_claude_auth_command(host: str, profile: str | None = None) -> str:
    """Return the Databricks CLI ``apiKeyHelper`` command for Claude.

    :param host: Databricks workspace host, e.g.
        ``"https://example.databricks.com"``.
    :param profile: Optional ``~/.databrickscfg`` profile name, e.g. ``"oss"``.
        Preferred over ``--host`` when known; see
        :func:`~omnigent.inner.databricks_executor.databricks_bearer_token_command`,
        which owns the command's shape for every harness.
    :returns: Shell command that prints a bearer token.
    """
    from .databricks_executor import databricks_bearer_token_command

    return databricks_bearer_token_command(host, profile)


def _parse_optional_int(value: str | None) -> int | None:
    """Parse an optional integer env-var value.

    :param value: Raw env-var value, e.g. ``"900000"``.
    :returns: Parsed integer, or ``None`` when unset or invalid.
    """
    if value is None:
        return None
    try:
        return int(value)
    except ValueError:
        logger.warning("Ignoring invalid integer value %r", value)
        return None


def _claude_internal_write_roots(*, include_config: bool = True) -> list[pathlib.Path]:
    """Writable roots the Claude CLI needs for its own local session state.

    CORAL(S113): ``include_config=False`` leaves out, and creates nothing under, ``~/.claude``.
    """

    config_names = ("backups", "plugins", "session-env", "sessions") if include_config else ()
    roots = [
        *(pathlib.Path.home() / ".claude" / name for name in config_names),
        pathlib.Path.home() / ".npm" / "_logs",
        # CORAL(S109): no per-user temp dir: one is shared by every session; see
        # _claude_launch_tmpdir_parent for the CLI's own dir per launch.
    ]
    for root in roots:
        root.mkdir(parents=True, exist_ok=True)
    return roots


# CORAL(S109): the CLI keeps child-process temp dirs in <CLAUDE_CODE_TMPDIR>/claude-<uid>
# only up to this many bytes; past it they fall back to the shared /tmp/claude-<uid>.
_CLAUDE_CLI_TEMP_DIR_MAX_BYTES = 44


def _claude_launch_tmpdir_parent() -> pathlib.Path:
    """CORAL(S109): the runner's short private socket root, which holds each launch's CLI dir."""
    from omnigent.runtime.harnesses.paths import resolve_harness_tmp_parent

    parent = resolve_harness_tmp_parent()
    # A launch dir is "c" plus eight random characters.
    longest = parent / ("c" * 9) / f"claude-{stable_user_id()}"
    if len(os.fsencode(longest)) > _CLAUDE_CLI_TEMP_DIR_MAX_BYTES:
        logger.warning(
            "The Claude CLI's temp dir under %s exceeds %d bytes; its child processes "
            "will use /tmp, which the sandbox does not grant",
            parent,
            _CLAUDE_CLI_TEMP_DIR_MAX_BYTES,
        )
    return parent


def _claude_internal_write_files() -> list[pathlib.Path]:
    """Exact files the Claude CLI updates outside its writable roots."""

    # .credentials.json holds the Claude CLI's OAuth token on Linux.
    candidates = [
        pathlib.Path.home() / ".claude.json",
        pathlib.Path.home() / ".claude" / ".credentials.json",
    ]
    return [path for path in candidates if path.exists()]


def _resolve_sandbox_cwd(spec_cwd: str | None) -> pathlib.Path:
    """Resolve the sandbox root, rooting relative paths at the session
    working folder rather than the runner daemon's process cwd.

    A relative ``os_env.cwd`` — notably the default ``"."`` — resolved
    against ``os.getcwd()`` lands on the runner daemon's ``$HOME`` when
    no workspace is selected. That both roots the sandbox at the whole
    home dir and disagrees with the tmux terminal, which uses
    ``OMNIGENT_RUNNER_WORKSPACE``. Prefer that workspace as the base so
    the two agree; fall back to the process cwd only when it is unset.
    An absolute ``spec_cwd`` is honored verbatim.

    :param spec_cwd: The spec's ``os_env.cwd``, or ``None``.
    :returns: The resolved, absolute sandbox root.
    """
    base = os.environ.get("OMNIGENT_RUNNER_WORKSPACE") or os.getcwd()
    if spec_cwd:
        path = pathlib.Path(spec_cwd)
        if not path.is_absolute():
            path = pathlib.Path(base) / path
    else:
        path = pathlib.Path(base)
    return path.resolve(strict=False)


def prepare_claude_cli_path(
    real_cli_path: str | None,
    spec: OSEnvSpec | None,
    *,
    isolate_config: bool | None = None,  # CORAL(S113, S115)
    config_seed: pathlib.Path | None = None,  # CORAL(S115)
) -> PreparedClaudeCli:
    """Wrap the Claude CLI in the agent's configured sandbox when possible.

    Degrades instead of crashing: when the sandbox can't be resolved or
    the wrap can't be built (unsupported platform, un-grantable
    interpreter layout, profile-size overflow), the CLI is returned
    unwrapped with native tools disabled — the same confinement story
    as ``OMNIGENT_CLAUDE_SDK_NO_SANDBOX``: file/shell access still goes
    through the independently sandboxed ``sys_os_*`` helpers (which
    fail closed on their own), and only the CLI supervisor process
    runs unwrapped.

    :param real_cli_path: Absolute path to the system-installed Claude CLI
        binary, or ``None`` when no CLI is available.
    :param spec: The agent's ``os_env`` spec.  Only ``caller_process`` specs
        with a compatible sandbox are eligible for wrapping.
    :param isolate_config: CORAL(S113): grant nothing of the user's Claude config home;
        the launcher gives each CLI launch its own config dir instead. A new unwrapped-by-design
        return must also change :func:`_claude_cli_sandbox_requested`. CORAL(S115): ``None``
        isolates on every backend but Windows' job object, which confines no files, so a new
        caller and a new backend are isolated; ``False`` keeps the shared grants, which no
        production caller may pass.
    :param config_seed: CORAL(S115): a file the launcher copies into an isolated CLI's dir as
        its global config. It need not exist yet, but must by launch time.
    :returns: A :class:`PreparedClaudeCli` naming the effective CLI path and
        whether native tools should be enabled.
    """

    if real_cli_path is None or spec is None or spec.type != "caller_process":
        return PreparedClaudeCli(cli_path=real_cli_path, enable_native_tools=False)

    if _sandbox_disabled_by_env():
        return PreparedClaudeCli(cli_path=real_cli_path, enable_native_tools=False)

    sandbox_spec = spec.sandbox or OSEnvSandboxSpec()
    if sandbox_spec.type == "none":
        return PreparedClaudeCli(cli_path=real_cli_path, enable_native_tools=True)

    cwd = _resolve_sandbox_cwd(spec.cwd)
    try:
        sandbox = resolve_sandbox(spec, cwd)
    except (OSError, NotImplementedError) as exc:
        logger.warning(
            "Cannot resolve the configured sandbox for the Claude CLI wrap; "
            "running the CLI unwrapped with native tools disabled "
            "(file/shell access stays confined to the sandboxed sys_os_* "
            "tools): %s",
            exc,
        )
        return PreparedClaudeCli(cli_path=real_cli_path, enable_native_tools=False)
    if not sandbox.active:
        return PreparedClaudeCli(cli_path=real_cli_path, enable_native_tools=False)
    if not sandbox.allow_network:
        # The Claude CLI itself must reach the provider, so we cannot run the
        # whole native-tool process tree inside a network-denying sandbox.
        return PreparedClaudeCli(cli_path=real_cli_path, enable_native_tools=False)

    # CORAL(S115): only the backend that confines no files keeps the shared grants by default
    if isolate_config is None:
        isolate_config = sandbox.backend_type != _WINDOWS_JOB_OBJECT_BACKEND
    if isolate_config:
        sandbox = _with_private_claude_config(sandbox, seed=config_seed)  # CORAL(S113, S115)
    else:
        sandbox = with_additional_read_roots(sandbox, _claude_internal_write_roots())
        sandbox = with_additional_write_roots(sandbox, _claude_internal_write_roots())
        sandbox = with_additional_write_files(sandbox, _claude_internal_write_files())
    # CORAL(S109): the CLI ignores TMPDIR and seatbelt shares the host's /tmp, so each launch
    # gets its own dir; bwrap's /tmp is already a private tmpfs per launch.
    if sandbox.backend_type == "darwin_seatbelt":
        sandbox = with_launch_tmpdir(sandbox, "CLAUDE_CODE_TMPDIR", _claude_launch_tmpdir_parent())
    # Dry-run the spawn-time wrap now, while degrading is still possible.
    # The real wrap happens later inside run_launcher, where an OSError
    # (un-grantable interpreter layout, profile-size cap, cwd-scan
    # overflow) kills the launcher and surfaces as an opaque connect
    # timeout. By run time native tools are already enabled, so this is
    # the last point where "skip the wrap" is still safe.
    try:
        get_backend(sandbox.backend_type).wrap_launcher_argv(
            [sys.executable, "-c", "pass"], sandbox, cwd, target=real_cli_path
        )
    except OSError as exc:
        logger.warning(
            "The configured sandbox cannot wrap the Claude CLI at %s; "
            "running it unwrapped with native tools disabled (file/shell "
            "access stays confined to the sandboxed sys_os_* tools). "
            "Remediation hints in the underlying error: %s",
            real_cli_path,
            exc,
        )
        return PreparedClaudeCli(cli_path=real_cli_path, enable_native_tools=False)
    return PreparedClaudeCli(
        cli_path=create_exec_launcher(real_cli_path, sandbox),
        enable_native_tools=True,
        config_isolated=isolate_config,  # CORAL(S113)
    )


def _with_private_claude_config(
    sandbox: SandboxPolicy, *, seed: pathlib.Path | None = None
) -> SandboxPolicy:
    """
    CORAL(S113): only ``~/.npm/_logs``; the launcher gives each launch its own config dir.

    CORAL(S115): with *seed*, that dir starts with a copy of it as the CLI's global config.
    """
    sandbox = with_additional_write_roots(
        sandbox, _claude_internal_write_roots(include_config=False)
    )
    # Both names, so an inherited secure-storage dir cannot move the keychain item off it.
    return with_scratch_dir_env(
        sandbox,
        _CLAUDE_CONFIG_DIR_ENV,
        files=_CLAUDE_CONFIG_BLOCKED_NAMES,
        extra_envs=_CLAUDE_CONFIG_ENV[1:],
        seed=((_CLAUDE_GLOBAL_CONFIG_NAME, seed),) if seed is not None else (),  # CORAL(S115)
    )


def _claude_seed_path() -> pathlib.Path:
    """CORAL(S115): a fresh name for a seed file; nothing is made until a wrapped launch."""
    name = f"omnigent-claude-seed-{secrets.token_hex(8)}"
    # Not a dotfile, which the sandbox's dotfile mask would hide.
    return pathlib.Path(tempfile.gettempdir()) / name / "claude.json"


# CORAL(S116): the executor's own dirs, as _claude_seed_path and mkdtemp name them
_CLAUDE_SEED_DIR_NAME = re.compile(r"omnigent-claude-seed-[0-9a-f]{16}")
_UNWRAPPED_CONFIG_DIR_NAME = re.compile(r"omnigent-claude-config-[a-z0-9_]{8}")
# CORAL(S116): how long close() waits for pending evictions and its last sweep, and a connect
# or teardown for its own; a sweep still running then goes on in the background
_CLOSE_WAIT_SECONDS = 10.0
_SWEEP_WAIT_SECONDS = 2.0
# CORAL(S116): after the SDK's own close, how long the rest of the CLI's tree gets before SIGKILL
_GRACEFUL_TREE_SECONDS = 2.0
# CORAL(S116): one sweep at a time per process
_SWEEP_LOCK = threading.Lock()


def _remove_orphaned_temp_dirs() -> None:
    """
    CORAL(S116): remove the temp dirs that processes now gone left behind; never raises.

    In the temp dir: launch scratches, seatbelt profile dirs, seed and unwrapped config dirs;
    under the harness socket root, if it is this user's private dir: seatbelt launch dirs.
    """
    if not hasattr(os, "getuid"):
        return
    try:
        from omnigent.runtime.harnesses.paths import resolve_harness_tmp_parent

        from .seatbelt_sandbox import PROFILE_TEMPDIR_NAME

        names = (
            PRIVATE_TMPDIR_NAME,
            PROFILE_TEMPDIR_NAME,
            _CLAUDE_SEED_DIR_NAME,
            _UNWRAPPED_CONFIG_DIR_NAME,
        )
        pattern = re.compile("|".join(f"(?:{name.pattern})" for name in names))
        _remove_orphaned_launch_tmpdirs(pathlib.Path(tempfile.gettempdir()), pattern)
        harness_root = resolve_harness_tmp_parent()
        if _is_private_dir(harness_root):  # as S109's own sweep requires
            _remove_orphaned_launch_tmpdirs(harness_root)
    except Exception as exc:  # noqa: BLE001 — it runs in teardown, which must not fail
        logger.warning("Cannot sweep the temp dirs (%s)", type(exc).__name__)


def _sweep_once(wait: float) -> None:
    """CORAL(S116): sweep, unless another sweep of this process still runs after *wait* s."""
    if not (_SWEEP_LOCK.acquire(timeout=wait) if wait > 0 else _SWEEP_LOCK.acquire(False)):
        return
    try:
        _remove_orphaned_temp_dirs()
    finally:
        _SWEEP_LOCK.release()


async def _sweep_orphaned_temp_dirs(
    timeout: float = _SWEEP_WAIT_SECONDS, *, wait_turn: float = 0.0
) -> None:
    """
    CORAL(S116): run the sweep off the event loop; a cancelled caller still lets it finish.

    *timeout* bounds only the wait; the sweep then goes on in the background. A sweep asked
    for while another runs is skipped, unless *wait_turn* lets it wait that long for its
    turn. Never raises but for the caller's own cancellation.
    """
    sweep = asyncio.create_task(asyncio.to_thread(_sweep_once, wait_turn))
    try:
        await asyncio.wait_for(asyncio.shield(sweep), timeout)
    except TimeoutError:
        logger.warning("The temp dir sweep is still running")
    except asyncio.CancelledError:
        # Bounded too, so a stuck sweep cannot hold back a cancelled teardown.
        await asyncio.wait({sweep}, timeout=timeout)
        raise
    except Exception as exc:  # noqa: BLE001 — e.g. a loop whose executor has shut down
        logger.warning("Cannot sweep the temp dirs (%s)", type(exc).__name__)


async def _wait_for_tree(
    process: _Process | None, tree: dict[int, float], *, timeout: float
) -> None:
    """
    CORAL(S116): wait for *process*, if given, and every process of its *tree* to exit.

    :raises TimeoutError: If one still runs after *timeout* seconds in all.
    """
    async with asyncio.timeout(timeout):
        if process is not None:
            with suppress(Exception):
                await process.wait()
        while _proc.live_members(tree):
            await asyncio.sleep(0.05)


def _client_process_tree(client: _ClaudeClient) -> dict[int, float]:
    """CORAL(S116): the tree of *client*'s CLI process, while it is a live child of this one."""
    process = getattr(getattr(client, "_transport", None), "_process", None)
    return _proc.snapshot_child_tree(process) if process is not None else {}


async def _reap_tree(tree: dict[int, float], *, timeout: float) -> None:
    """CORAL(S116): give every process of *tree* *timeout* s to exit, then SIGKILL the rest."""
    try:
        await _wait_for_tree(None, tree, timeout=timeout)
    except TimeoutError:
        _proc.kill_members(tree)
        with suppress(TimeoutError):
            await _wait_for_tree(None, tree, timeout=1)


def _claude_seed_source(env: Mapping[str, str]) -> pathlib.Path | None:
    """
    CORAL(S115): the global config file the CLI would read for *env*.

    ``None`` for an empty or relative ``CLAUDE_CONFIG_DIR`` or a relative ``HOME``, which the
    CLI would resolve against its working dir, a place the sandbox may write.
    """
    config_dir, home = env.get(_CLAUDE_CONFIG_DIR_ENV), env.get("HOME")
    if (config_dir is not None and not os.path.isabs(config_dir)) or (
        home and not os.path.isabs(home)
    ):
        logger.warning(
            "Not copying the user's Claude config into the CLI sandbox: CLAUDE_CONFIG_DIR %r "
            "and HOME %r must be absolute",
            config_dir,
            home,
        )
        return None
    from omnigent.harnesses.claude_native.bridge import claude_global_config_path

    return claude_global_config_path(pathlib.Path("/"), env)


def _claude_config_seed(env: Mapping[str, str]) -> dict[str, object]:
    """
    CORAL(S115): what a sandboxed CLI keeps of the user's global config for *env*.

    The top-level ``_CLAUDE_SEED_KEYS`` (``env`` with its string values, without the config dir
    names) and, for every project, the ``_CLAUDE_SEED_PROJECT_DEFAULTS`` keys not at their
    default. A missing file gives ``{}``; an unreadable, oversized or malformed one a warning
    naming it and ``{}``.
    """
    source = _claude_seed_source(env)
    if source is None:
        return {}
    try:
        with open_regular_file(source, follow_symlinks=True) as handle:
            data = handle.read(_CLAUDE_SEED_SOURCE_MAX_BYTES + 1)
        if len(data) > _CLAUDE_SEED_SOURCE_MAX_BYTES:
            raise ValueError(f"larger than {_CLAUDE_SEED_SOURCE_MAX_BYTES} bytes")
        config = json.loads(data)
    except FileNotFoundError:
        return {}
    except RecursionError:
        logger.warning("Not copying the Claude config %s into the CLI sandbox: too deep", source)
        return {}
    except (OSError, ValueError) as exc:
        logger.warning("Not copying the Claude config %s into the CLI sandbox: %s", source, exc)
        return {}
    if not isinstance(config, dict):
        logger.warning(
            "Not copying the Claude config %s into the CLI sandbox: not an object", source
        )
        return {}
    seed: dict[str, object] = {
        key: config[key]
        for key, kind in _CLAUDE_SEED_KEYS.items()
        if isinstance(config.get(key), kind)
    }
    if "env" in seed:
        # The CLI applies this env at start; it must not move the config dir off the private one.
        seed["env"] = {
            name: value
            for name, value in config["env"].items()
            if isinstance(value, str) and name not in _CLAUDE_CONFIG_ENV
        }
    projects = config.get("projects")
    kept = {
        path: {
            key: entry[key]
            for key, default in _CLAUDE_SEED_PROJECT_DEFAULTS.items()
            if key in entry and not (type(entry[key]) is type(default) and entry[key] == default)
        }
        for path, entry in (projects.items() if isinstance(projects, dict) else [])
        if isinstance(entry, dict)
    }
    if kept := {path: entry for path, entry in kept.items() if entry}:
        seed["projects"] = kept
    return seed


def prepare_tight_cli_process_path(
    real_cli_path: str | None,
    *,
    cwd: str | None = None,
    isolate_config: bool = True,  # CORAL(S113, S115): this wrap is always bwrap
    config_seed: pathlib.Path | None = None,  # CORAL(S115)
) -> str | None:
    """Wrap the Claude CLI in a tight default sandbox without enabling tools.

    CORAL(S113): ``isolate_config`` as for :func:`prepare_claude_cli_path`. CORAL(S115): so is
    ``config_seed``.
    """

    if real_cli_path is None:
        return None

    if _sandbox_disabled_by_env():
        return real_cli_path

    # Skip silently on non-Linux: the implicit default sandbox here is
    # ``linux_bwrap`` and ``resolve_sandbox`` would raise
    # NotImplementedError / OSError on every macOS / Windows run. The
    # operator's only recourse is to either accept the no-op or
    # set ``os_env.sandbox.type='none'`` explicitly — both
    # already produce the same behavior we land on here, so
    # logging a warning every run is just noise (and breaks
    # tests that assert ``stderr_is_clean``).
    if sys.platform != "linux":
        return real_cli_path

    spec = OSEnvSpec(
        type="caller_process",
        cwd=cwd,
        sandbox=OSEnvSandboxSpec(
            type="linux_bwrap",
            write_paths=[],
            allow_network=True,
        ),
    )
    try:
        resolved_cwd = _resolve_sandbox_cwd(cwd)
        sandbox = resolve_sandbox(spec, resolved_cwd)
    except (OSError, NotImplementedError) as exc:
        logger.warning(
            "Could not apply default local CLI sandbox; continuing without it: %s",
            exc,
        )
        return real_cli_path
    else:
        if not sandbox.active:
            return real_cli_path
        if isolate_config:
            sandbox = _with_private_claude_config(sandbox, seed=config_seed)  # CORAL(S113, S115)
        else:
            sandbox = with_additional_write_roots(sandbox, _claude_internal_write_roots())
            sandbox = with_additional_write_files(sandbox, _claude_internal_write_files())
        return create_exec_launcher(real_cli_path, sandbox)


@dataclass(frozen=True)
class _ResolvedSkills:
    """
    Pair of SDK options derived from a single ``skills_filter``
    value: ``ClaudeAgentOptions.skills`` and
    ``ClaudeAgentOptions.setting_sources``.

    Both are needed because the SDK's ``_apply_skills_defaults``
    auto-defaults ``setting_sources`` to ``["user", "project"]``
    whenever ``skills`` is non-None — including when ``skills=[]``.
    That auto-default loads ``~/.claude/skills/`` and the cwd's
    ancestor ``.claude/skills/`` chain into the system prompt
    listing even when the ``Skill`` tool itself is suppressed.
    Hermetic agents need to explicitly override
    ``setting_sources=[]`` to actually hide host skills from the
    model's view of its own skill listing.

    :param skills: Value for ``ClaudeAgentOptions.skills``:
        ``"all"`` / list of names / empty list for hermetic mode.
    :param setting_sources: Value for
        ``ClaudeAgentOptions.setting_sources``: ``None`` to let
        the SDK pick its default (``["user", "project"]``), or
        an explicit list (e.g. ``[]`` for hermetic mode where we
        don't want any scope-based discovery).
    """

    skills: str | list[str]
    setting_sources: list[str] | None


def _resolve_skills_option(
    skills_filter: str | list[str],
) -> _ResolvedSkills | None:
    """
    Translate the spec's ``skills_filter`` into the pair of SDK
    options ``ClaudeAgentOptions.skills`` and
    ``ClaudeAgentOptions.setting_sources``.

    Three meaningful filter values produce three distinct SDK
    configurations:

    - ``"all"`` → ``skills="all"``, ``setting_sources=None`` (SDK
      auto-defaults to ``["user", "project"]``). All host skills
      from ``~/.claude/skills/`` and ``<cwd>/.claude/skills/``
      (walking up the cwd tree) appear in the model's listing.
    - ``"none"`` → ``skills=[]``, ``setting_sources=[]``. Both
      the ``Skill`` tool listing AND the scope-based discovery
      are suppressed: no host skills appear in the system
      prompt or as invokable. Bundled skills (loaded via
      ``--plugin-dir``) are unaffected by ``setting_sources``
      and remain visible.
    - ``list[str]`` → ``skills=[names]``, ``setting_sources=None``.
      Only the named subset is in the model's listing; the SDK's
      auto-default still loads user and project sources for
      CLAUDE.md and other settings.

    :param skills_filter: ``"all"`` / ``"none"`` / list of skill
        names from :class:`AgentSpec.skills_filter`.
    :returns: The :class:`_ResolvedSkills` pair, or ``None`` when
        *skills_filter* is malformed — the caller falls back to
        ``"all"`` semantics.
    """
    if skills_filter == "all":
        return _ResolvedSkills(skills="all", setting_sources=None)
    if skills_filter == "none":
        # Empty ``skills`` suppresses the listing AND empty
        # ``setting_sources`` skips the SDK's auto-default that
        # would otherwise load ``~/.claude/skills/`` for the
        # system prompt anyway.
        return _ResolvedSkills(skills=[], setting_sources=[])
    if isinstance(skills_filter, list):
        return _ResolvedSkills(skills=list(skills_filter), setting_sources=None)
    return None


def _loads_user_settings(skills_filter: str | list[str]) -> bool:
    """CORAL(S115): whether the CLI loads user settings, and so the user's MCP servers."""
    resolved = _resolve_skills_option(skills_filter) or _ResolvedSkills("all", None)
    return resolved.setting_sources is None


class ClaudeSDKExecutor(Executor):
    """Execute agent turns using the Claude Agent SDK.

    The SDK runs Claude Code's full agent loop internally.  Omnigent tools
    are registered as MCP tools so the model can call them.  Built-in OS tools
    (Bash, Read, Edit, …) are only enabled when the agent's ``os_env`` flag
    is set.  Even without ``os_env``, Omnigent tries to place the Claude CLI
    itself in a tight default sandbox on supported Linux hosts.

    Unlike DatabricksExecutor, the SDK manages its own tool-call loop.  This
    executor yields events reconstructed from the SDK message stream:
    - ToolCallRequest for each ToolUseBlock (for history building)
    - TextChunk for streaming text
    - TurnComplete with the final result

    Multi-turn: call ``run_turn()`` repeatedly.  The executor maintains a
    persistent ``ClaudeSDKClient`` that preserves conversation context across
    turns by keeping a live Claude SDK client per Omnigent session.

    Gateway support: pass ``gateway=True`` to route through a vendor-neutral
    gateway (base URL + bearer-token command + model). The Databricks AI
    gateway is one producer of this transport (credentials resolved from
    ~/.databrickscfg via ``databricks_profile``); generic ``key`` / ``gateway``
    providers are another (base URL + auth command supplied directly).
    """

    def __init__(
        self,
        *,
        cwd: str | None = None,
        os_env: OSEnvSpec | None = None,
        model: str | None = None,
        permission_mode: str = "auto",
        gateway: bool = False,
        databricks_profile: str | None = None,
        gateway_host: str | None = None,
        base_url_override: str | None = None,
        gateway_auth_command: str | None = None,
        gateway_auth_refresh_interval_ms: str | None = None,
        retry_policy: RetryPolicy | None = None,
        bundle_dir: pathlib.Path | None = None,
        agent_name: str | None = None,
        skills_filter: str | list[str] = "all",
        api_key_helper: str | None = None,
        system_prompt_preset: str | None = None,
        require_api_credential: bool = False,
        tool_call_policy_hook: bool = False,
        isolate_claude_config: bool = False,  # CORAL(S113)
        credential_env: Mapping[str, str] | None = None,  # CORAL(S124)
    ) -> None:
        """Create a ClaudeSDKExecutor.

        Args:
            cwd: Working directory for Claude Code.
            os_env: If set, enable built-in OS tools (Bash, Read, Edit, …)
                and align them with the provided OS environment. When the
                spec's sandbox is enabled, Omnigent wraps the Claude CLI
                in the same sandbox. If omitted, Omnigent still tries to
                sandbox the Claude CLI process itself on supported Linux
                hosts, but does not enable native OS tools.
            model: Override the model name.
            system_prompt_preset: Set to ``claude_code`` to append agent
                instructions to Claude Code's prompt. Unset preserves the custom prompt.
            permission_mode: SDK permission mode (default: auto
                so the agent runs autonomously with background safety checks).
            gateway: If True, route through a vendor-neutral gateway
                (base URL + bearer-token command + model). Enables the
                gateway path regardless of which producer fed it (the
                Databricks Unity Gateway or a generic provider).
            databricks_profile: Databricks-specific config profile from
                ~/.databrickscfg, e.g. ``"<your-profile>"``.  Only used by the
                Databricks producer path (deriving base URL / auth command
                from the profile when ucode did not supply them, and for
                ``databricks auth token`` refresh). ``None`` falls back to the
                SDK's own profile resolution (``DATABRICKS_CONFIG_PROFILE``
                then the first valid section of ``~/.databrickscfg``).
            gateway_host: Gateway workspace host origin, e.g.
                ``"https://example.databricks.com"``.  Set from
                ``HARNESS_CLAUDE_SDK_GATEWAY_HOST`` (written by the AP
                workflow layer). When set, skips profile host lookup and
                requires the gateway base URL and auth command values.
            base_url_override: Override the Anthropic base URL instead of
                constructing it from the Databricks profile host.  Set from
                ``HARNESS_CLAUDE_SDK_GATEWAY_BASE_URL`` (written by the AP
                workflow layer). Required whenever ``gateway_host`` is set.
            gateway_auth_command: Shell command that prints a bearer token,
                e.g.
                ``"databricks auth token --host https://example.databricks.com ..."``
                or ``"printf %s sk-or-..."``. Set from
                ``HARNESS_CLAUDE_SDK_GATEWAY_AUTH_COMMAND``.
            gateway_auth_refresh_interval_ms: Refresh TTL as a string,
                e.g. ``"900000"``. Set from
                ``HARNESS_CLAUDE_SDK_GATEWAY_AUTH_REFRESH_INTERVAL_MS``.
            bundle_dir: Materialized agent-bundle root, when the agent
                ships its own ``skills/`` directory. Used to expose
                bundled skills to Claude via ``--plugin-dir <bundle>``
                (the SDK's plugin convention loads SKILL.md files from
                ``<plugin>/skills/<dir>/``). ``None`` for agents
                without a bundled-skill directory — the harness skips
                the plugin-dir wiring.
            agent_name: Optional agent display name. When *bundle_dir*
                is set, used to write a one-line ``.claude-plugin/
                plugin.json`` manifest so bundled skills get clean
                ``<agent-name>:<skill-name>`` namespaced labels in
                Claude's skill listing (instead of being labeled by
                the bundle's tmp-dir basename).
            skills_filter: Host-skill filter (``"all"`` / ``"none"`` /
                ``list[str]``). Maps to the SDK's ``skills`` option:
                ``"all"`` → enable every host-discovered skill,
                ``"none"`` → empty list (no host skills exposed),
                list of names → only the named skills. Bundled
                skills loaded via ``bundle_dir`` are subject to the
                same listing filter (so ``"none"`` hides every skill
                from the model, bundled or host); agents that want
                bundled skills always visible while opting out of
                host skills should set this to a list naming their
                bundled skills explicitly. Defaults to ``"all"``.
            api_key_helper: Shell command the Claude CLI will invoke to
                retrieve a bearer token, e.g.
                ``"printf %s sk-ant-..."`` (set by the harness when
                ``executor.auth: {type: api_key, …}`` is declared).
                Injected into ``_extra_env`` as
                :data:`_CLAUDE_API_KEY_HELPER_ENV_KEY` so it reaches
                the SDK's ``settings.apiKeyHelper`` option at turn time.
            require_api_credential: Refuse turns unless *api_key_helper* or
                *gateway* is set and any *os_env* has a bwrap or seatbelt
                sandbox; strip inherited subscription tokens from the CLI.
            tool_call_policy_hook: Check every non-Omnigent tool call against
                TOOL_CALL policy from a PreToolUse hook, which the CLI runs in
                every permission mode, unlike ``can_use_tool``.
            isolate_claude_config: CORAL(S113): keep the CLI's Claude config in a
                private directory instead of the user's: per launch inside a sandbox
                wrap, else this executor's own. Refuse turns when *os_env* configures a
                sandbox that could not wrap the CLI.
            credential_env: CORAL(S124): a Coral harness's environment from before it
                dropped the credentials its CLI must not inherit, for running the
                credential command; ``None`` outside a Coral harness on POSIX.
        """
        # Fail loud: a Databricks model requires the gateway transport.
        if not gateway and model is not None and is_databricks_model_id(model):
            raise ValueError(
                f"Model {model!r} is a Databricks-hosted model but gateway "
                "routing is disabled (gateway=False). "
                "Set executor.profile in the agent spec, or configure a "
                f"Databricks provider with `{cli_invocation()} setup`, to route through "
                "the Databricks Anthropic gateway."
            )
        if system_prompt_preset not in (None, "claude_code"):
            raise ValueError("system_prompt_preset must be 'claude_code' or unset")
        self._system_prompt_preset = system_prompt_preset
        # CORAL(S13, S21)
        self._require_api_credential = require_api_credential
        self._tool_call_policy_hook = tool_call_policy_hook
        # CORAL(S113): whether the wrap gives each launch its own config dir, and the
        # executor's own dir for a CLI that runs unwrapped
        self._isolate_claude_config = isolate_claude_config
        self._claude_config_isolated = False
        # CORAL(S124): kept for running the credential command, never for the CLI's env
        self._credential_env = dict(credential_env) if credential_env is not None else None
        # CORAL(S124): set below for a Coral CLI on POSIX: the one holder of the real
        # credential, and a static key long enough to tell from ordinary values
        self._upstream_credential: UpstreamCredential | None = None
        self._credential_literal: str | None = None
        # CORAL(S124): whether the proxy of a CLI with no gateway forwards to the Anthropic API
        self._proxy_is_first_party = False
        # CORAL(S125): the settings names the proxy's upstream hop takes, fixed once it starts,
        # and the ignored ones already warned about
        self._settings_upstream_env: dict[str, str] = {}
        self._settings_env_warned: set[tuple[str, str]] = set()
        # CORAL(S125): where the user's settings file is, as the host's environment said when
        # this executor was built: a connect of any session takes the name out of os.environ
        host_env = os.environ if credential_env is None else credential_env
        self._settings_location_env = {
            name: host_env[name] for name in _SETTINGS_LOCATION_ENV if name in host_env
        }
        # CORAL(S125): one turn at a time builds, starts or drops the shim
        self._gateway_shim_lock = asyncio.Lock()
        self._unwrapped_claude_config_dir: pathlib.Path | None = None
        # CORAL(S115): the seed a wrapped non-Coral CLI's launcher copies in. Its dir is made
        # at the first launch, and again if it goes missing; after close, a launch fails.
        self._claude_config_seed_path: pathlib.Path | None = None
        self._claude_config_seed_dir_made = False
        self._claude_config_seed_removed = False
        self._claude_seed_sign_in_warned: set[str] = set()
        self._cwd = cwd
        self._os_env_spec = os_env
        self._os_env = os_env is not None
        self._model_override = model
        self._permission_mode = permission_mode
        self._gateway = gateway
        self._databricks_profile = databricks_profile
        self._gateway_host = gateway_host.rstrip("/") if gateway_host else None
        self._base_url_override = base_url_override
        self._gateway_auth_command = gateway_auth_command
        self._gateway_auth_refresh_interval_ms = _parse_optional_int(
            gateway_auth_refresh_interval_ms
        )
        self._bundle_dir = bundle_dir
        self._agent_name = agent_name
        self._skills_filter = skills_filter
        # Write the bundle's plugin manifest now (idempotent) so that
        # ``--plugin-dir <bundle>`` produces clean
        # ``<agent-name>:<skill-name>`` labels in Claude's skill
        # listing instead of the auto-derived tmpdir basename.
        if self._bundle_dir is not None and (self._bundle_dir / "skills").is_dir():
            try:
                ensure_bundle_plugin_manifest(self._bundle_dir, self._agent_name)
            except OSError as exc:
                logger.warning(
                    "could not write bundle plugin manifest at %s: %s",
                    self._bundle_dir,
                    exc,
                )
        self._tool_executor: ToolExecutor | None = None
        # Elicitation handler wired in by ExecutorAdapter. When set
        # (and permission_mode is not bypassPermissions), each tool
        # call is gated by an async approve/deny round-trip through
        # the Omnigent elicitation system rather than silently allowed.
        # ``None`` until the adapter installs it on first use.
        self._elicitation_handler: ElicitationHandler | None = None
        # AskUserQuestion bridge installed by ExecutorAdapter; None until wired.
        self._ask_question_handler: AskQuestionHandler | None = None
        # Live Claude SDK clients keyed by Omnigent session id.
        self._clients: dict[str, _ClaudeClientState] = {}
        self._pending_framework_context: dict[str, str] = {}
        # Session keys whose Claude harness process crashed and must not be reused.
        self._crashed_sessions: dict[str, str] = {}
        # Force-close tasks for clients evicted on turn cancellation, kept
        # referenced so they are not GC'd mid-close.
        self._cancel_close_tasks: set[asyncio.Task[None]] = set()

        # Prefer system-installed claude over the SDK's bundled CLI.
        # The bundled CLI may be older and send beta flags that the
        # Databricks gateway doesn't support.
        self._cli_wrapper_path: str | None = None
        self._cli_path: str | None = _find_system_claude()
        # CORAL(S115): a non-Coral CLI that loads user settings gets the user's MCP servers
        seed: pathlib.Path | None = None
        if not isolate_claude_config and _loads_user_settings(skills_filter):
            seed = _claude_seed_path()
        if self._cli_path:
            if self._os_env_spec is not None:
                prepared = prepare_claude_cli_path(
                    self._cli_path,
                    self._os_env_spec,
                    # CORAL(S113, S115): Coral always; others where the sandbox confines files
                    isolate_config=True if isolate_claude_config else None,
                    config_seed=seed,
                )
                self._os_env = prepared.enable_native_tools
                self._claude_config_isolated = prepared.config_isolated  # CORAL(S113)
                if prepared.cli_path != self._cli_path:
                    self._cli_wrapper_path = prepared.cli_path
                    self._cli_path = prepared.cli_path
            else:
                wrapped_cli = prepare_tight_cli_process_path(
                    self._cli_path,
                    cwd=self._cwd,
                    isolate_config=True,  # CORAL(S113, S115): Coral or not
                    config_seed=seed,
                )
                # CORAL(S113, S115): before _cli_path names the wrapper
                self._claude_config_isolated = wrapped_cli != self._cli_path
                if wrapped_cli != self._cli_path:
                    self._cli_wrapper_path = wrapped_cli
                    self._cli_path = wrapped_cli
            if self._os_env_spec is not None and self._cwd is None:
                self._cwd = self._os_env_spec.cwd
            logger.info("Using system claude CLI: %s", self._cli_path)
        else:
            logger.info("No system claude found; SDK will use bundled CLI")
        # CORAL(S115): an unwrapped CLI reads the user's own config, as before
        self._claude_config_seed_path = seed if self._claude_config_isolated else None
        if (
            self._claude_config_isolated
            and not isolate_claude_config
            and not (api_key_helper or gateway)
            and not any(os.environ.get(name) for name in _CLAUDE_CREDENTIAL_ENV)
        ):
            logger.warning(
                "This agent's Claude CLI runs in an OS sandbox with its own Claude config, so a "
                "Claude subscription login stored on this host does not reach it, and it has no "
                "API key helper, gateway or credential variable. If it signs in no other way, "
                "run `%s setup` to give it a Claude API key or gateway, or set "
                "CLAUDE_CODE_OAUTH_TOKEN (from `claude setup-token`) in the host's environment.",
                cli_invocation(),
            )
        # CORAL(S113): a sandbox the spec configures that did not wrap the CLI is a fault
        self._claude_wrap_failure: str | None = None
        if (
            isolate_claude_config
            and not self._claude_config_isolated
            and _claude_cli_sandbox_requested(self._os_env_spec)
        ):
            self._claude_wrap_failure = (
                "no system claude CLI is installed, and the SDK's bundled one cannot be wrapped"
                if self._cli_path is None
                else "the sandbox could not wrap it; the runner log has the cause"
            )

        # True when the gateway transport was derived from a ~/.databrickscfg
        # profile (no gateway host or base URL supplied directly). Gates the
        # Databricks-specific default model in :meth:`run_turn`; the neutral
        # generic-provider gateway path leaves this False so it never selects
        # a ``databricks-*`` model.
        self._gateway_uses_databricks_profile = bool(
            gateway and self._gateway_host is None and base_url_override is None
        )
        self._resolved_default_model: str | None = None

        # Lazily-started local proxy that restores request fields the
        # Claude CLI strips on the gateway path (thinking.display).
        # Started on the first gateway turn — __init__ has no event loop.
        self._gateway_shim: ClaudeGatewayShim | None = None

        # Claude Code's model vocabulary for this gateway — alias pins and
        # canonical-to-served rewrites — read from the gateway's model listing
        # on the first gateway turn (see
        # :meth:`_apply_gateway_model_vocabulary`). ``None`` until resolved;
        # the resolved value may be empty (discovery found nothing).
        self._gateway_vocabulary: _GatewayModelVocabulary | None = None

        # Eagerly resolve the gateway transport env so errors surface at
        # construction time.
        self._extra_env: dict[str, str] = {}
        if gateway:
            gateway_env = _resolve_gateway_env(
                databricks_profile,
                host_override=self._gateway_host,
                base_url_override=base_url_override,
                auth_command_override=self._gateway_auth_command,
                auth_refresh_interval_ms=self._gateway_auth_refresh_interval_ms,
            )
            if not gateway_env:
                raise OSError(
                    "ClaudeSDKExecutor(gateway=True) requires gateway credentials "
                    "from the gateway base URL / auth command or a valid "
                    "~/.databrickscfg profile."
                )
            self._extra_env.update(gateway_env)
        self._extra_env[_CLAUDE_CODE_ENABLE_TOOL_SEARCH_ENV] = "true"
        if entrypoint := os.environ.get("OMNIGENT_CLAUDE_CODE_ENTRYPOINT"):
            self._extra_env["CLAUDE_CODE_ENTRYPOINT"] = entrypoint

        # Pass the retry budget and response-header timeout to the Claude CLI.
        self._retry_policy = retry_policy if retry_policy is not None else RetryPolicy()
        self._extra_env.update(self._retry_policy.claude_cli.env())

        # api_key_helper: shell command the Claude CLI invokes to retrieve a
        # bearer token (``executor.auth: {type: api_key, …}`` path).  Must
        # be injected here (not read from os.environ) because
        # ``_get_or_create_client`` strips ``ANTHROPIC_API_KEY`` from
        # os.environ before connecting, and the executor reads
        # ``_CLAUDE_API_KEY_HELPER_ENV_KEY`` from ``_extra_env`` only.
        if api_key_helper:
            self._extra_env[_CLAUDE_API_KEY_HELPER_ENV_KEY] = api_key_helper
        # CORAL(S124): a Coral CLI goes through the credential proxy, with or without a gateway
        # (no Windows shell runs the token helper, so there the CLI keeps the command)
        command = self._extra_env.get(_CLAUDE_API_KEY_HELPER_ENV_KEY)
        if require_api_credential and command and IS_POSIX:
            self._upstream_credential = self._new_upstream_credential(command)
            # The stripped form the proxy sends, so a copy without a trailing newline is found.
            literal = static_credential_literal(command) or ""
            if len(literal) >= MIN_SCANNED_LITERAL_CHARS:
                self._credential_literal = literal

    def _new_upstream_credential(self, command: str) -> UpstreamCredential:
        """CORAL(S124): *command* as the proxy runs it: the CLI's helper TTL, the harness's env.

        :param command: The real credential command, e.g. ``"databricks auth token ..."``.
        :returns: The credential the proxy and the model listing share.
        """
        # The pre-scrub snapshot holds what the command may need and the CLI must not.
        environ = os.environ if self._credential_env is None else self._credential_env
        ttl_ms = _parse_optional_int(self._extra_env.get(_KEY_HELPER_TTL_ENV))
        ttl_s = ttl_ms / 1000 if ttl_ms and ttl_ms > 0 else None
        if not self._gateway:
            # Without a gateway the CLI took its cache time from the harness, else its own;
            # as for the CLI, 0 is a time: the value is never reused.
            ttl_ms = _parse_optional_int(environ.get(_KEY_HELPER_TTL_ENV))
            ttl_s = ttl_ms / 1000 if ttl_ms is not None and ttl_ms >= 0 else _CLI_KEY_HELPER_TTL_S
        return UpstreamCredential(
            command,
            ttl_s=ttl_s,
            env={name: value for name, value in environ.items() if name != _PROXY_TOKEN_ENV},
        )

    def _proxy_upstream(self, env: Mapping[str, str]) -> str | None:
        """CORAL(S124): where a proxied CLI's requests go on to, as it would have sent them.

        :param env: The CLI's ``options.env`` as built so far.
        :returns: The gateway's URL; without a gateway, the endpoint the user's settings
            name (CORAL(S125)), else the one the harness had before its scrub, else the
            Anthropic API. ``None`` for a gateway whose env names none.
            Whitespace around a configured URL is dropped, as an HTTP client would drop it.
        """
        if self._gateway:
            return (env.get("ANTHROPIC_BASE_URL") or "").strip() or None
        environ = os.environ if self._credential_env is None else self._credential_env
        # CORAL(S125): the settings block came first in the CLI's own environment too
        sources = (self._settings_upstream_env, environ)
        named = ((source.get(_SETTINGS_ENV_BASE_URL) or "").strip() for source in sources)
        return next((url for url in named if url), _ANTHROPIC_API_URL)

    def _take_settings_env(self) -> dict[str, str]:
        """CORAL(S125): read the user's settings env for a Coral CLI behind the credential proxy.

        Keeps the endpoint and network names for the proxy's upstream hop until the proxy
        starts, after which they stay as they were, and warns once per name it ignored.

        :returns: The names the CLI's environment takes; none on a gateway or when the CLI
            loads user settings itself, where nothing was merged before either.
        :raises _CredentialProxyRefusedError: Before the proxy starts, when a settings file
            a step could place or write names the endpoint.
        """
        if self._gateway or _loads_user_settings(self._skills_filter):
            return {}
        where = self._settings_location_env
        trusted = _settings_file_steers_upstream(self._cwd, where)
        block = _claude_user_settings_env(self._cwd, where)
        taken = _allowed_settings_env(block, trusted=trusted, cwd=self._cwd)
        if self._gateway_shim is None:
            # The user named an endpoint for the key; no other one gets it in its place.
            if not trusted and (block.get(_SETTINGS_ENV_BASE_URL) or "").strip():
                raise _CredentialProxyRefusedError(
                    f"{_SETTINGS_ENV_BASE_URL} is set in a Claude settings file that is not "
                    "trusted to name the model endpoint. Keep that file under an absolute "
                    "CLAUDE_CONFIG_DIR, or the default one in the user's home, outside the "
                    "step's working directory, or remove the setting from it"
                )
            self._settings_upstream_env = taken.upstream
        self._warn_ignored_settings(
            taken.ignored,
            "it is not an absolute path outside the step's working directory"
            if trusted
            else "its credential proxy takes endpoint and network settings only from a "
            "settings file under an absolute CLAUDE_CONFIG_DIR, or the default one in the "
            "user's home, outside the step's working directory",
        )
        cli = dict(taken.cli)
        for name in taken.cli.keys() & _SETTINGS_ENV_PROXY_NAMES:
            # The other spelling says the same to the CLI, as it does to the proxy's own hop.
            twin = name.lower() if name.isupper() else name.upper()
            if twin not in taken.upstream:
                cli[twin] = taken.cli[name]
        return cli

    def _warn_ignored_settings(
        self, names: Sequence[str], reason: str, source: str = "the user's Claude settings"
    ) -> None:
        """CORAL(S125): warn once per executor for each endpoint or network name not taken.

        :param names: Variable names, e.g. ``("NODE_EXTRA_CA_CERTS",)``; no value is logged.
        :param reason: Why, e.g. ``"it is not an absolute path ..."``.
        :param source: Where the name was set.
        """
        for name in sorted(names):
            if (source, name) not in self._settings_env_warned:
                self._settings_env_warned.add((source, name))
                logger.warning("Ignoring %s from %s for this step: %s", name, source, reason)

    def _settings_network_env(self) -> dict[str, str] | None:
        """CORAL(S125): the names that decide the upstream hop's proxy once settings name any.

        A settings name replaces the harness's under either spelling, as it came first in
        the CLI's own environment.

        :returns: The harness's environment from before its scrub under the settings
            block's proxy names; ``None`` when the settings name none.
        """
        proxies = {
            name: value
            for name, value in self._settings_upstream_env.items()
            if name in _SETTINGS_ENV_PROXY_NAMES
        }
        if not proxies:
            return None
        replaced = {name.upper() for name in proxies}
        inherited = os.environ if self._credential_env is None else self._credential_env
        kept = {name: value for name, value in inherited.items() if name.upper() not in replaced}
        return {**kept, **proxies}

    def _upstream_hop_proxy(self, upstream: str) -> tuple[str | None, bool]:
        """CORAL(S125): the proxy for the credential proxy's hop to *upstream*.

        The user's settings names decide when they name any, else the harness's
        environment from before its scrub.

        :param upstream: The checked upstream, e.g. ``"https://gateway.example/anthropic"``.
        :returns: The proxy URL, possibly with userinfo, or ``None``; and whether the
            client may read the environment's proxies itself, which it may not once
            settings names took part.
        :raises _CredentialProxyRefusedError: For a proxy the upstream client cannot use,
            e.g. a SOCKS one; names the variable only.
        """
        settings_env = self._settings_network_env()
        network_env = self._credential_env if settings_env is None else settings_env
        named = None if network_env is None else _proxy_for_upstream(upstream, network_env)
        if named is None:
            return None, settings_env is None
        name, proxy = named[0], named[1].strip()
        try:
            scheme = urlsplit(proxy).scheme.lower()
        except ValueError:
            scheme = ""
        if scheme not in _UPSTREAM_PROXY_SCHEMES:
            raise _CredentialProxyRefusedError(
                f"{name} names a proxy for the model endpoint that is not an http:// or "
                "https:// URL, the only kinds this step's credential proxy can use"
            )
        return proxy, settings_env is None

    def _upstream_ca_file(self) -> str | None:
        """CORAL(S125): the CA file added to the trust of a direct-key proxy's upstream hop.

        The user's settings name it, else the host's environment, as the CLI's own model
        connection took it; the host's is held to the same path rule.

        :returns: An absolute path outside the step's working directory, or ``None``.
        """
        if (ca_file := self._settings_upstream_env.get(_SETTINGS_ENV_CA_FILE)) is not None:
            return ca_file
        environ = os.environ if self._credential_env is None else self._credential_env
        ca_file = environ.get(_SETTINGS_ENV_CA_FILE)
        if not ca_file:
            return None
        if os.path.isabs(ca_file) and _is_outside(ca_file, self._cwd or os.getcwd()):
            return ca_file
        self._warn_ignored_settings(
            (_SETTINGS_ENV_CA_FILE,),
            "it is not an absolute path outside the step's working directory",
            source="the host's environment",
        )
        return None

    @staticmethod
    def _proxy_refusal(refused: _CredentialProxyRefusedError) -> ExecutorError:
        """CORAL(S125): the turn's error for a credential proxy that may not or could not start."""
        return ExecutorError(
            message=f"This step's Claude CLI was not started: {refused}.",
            code=CORAL_CREDENTIAL_UPSTREAM_REFUSED_CODE,
            retryable=False,
        )

    def _check_proxy_upstream(self, env: Mapping[str, str]) -> None:
        """CORAL(S124, S125): refuse an upstream, or a proxy to it, the key may not go to.

        :param env: The CLI's ``options.env`` as built so far.
        :raises _CredentialProxyRefusedError: With a message that names no value.
        """
        if not (upstream := self._proxy_upstream(env)):
            return
        try:
            check_upstream_url(upstream)
        except OSError as exc:  # its message names the scheme at most
            raise _CredentialProxyRefusedError(str(exc)) from None
        self._upstream_hop_proxy(upstream)

    def _credential_exposure(self, options: SdkOptions) -> str | None:
        """CORAL(S124): where a proxied CLI's launch would still hold the static key, if anywhere.

        :param options: The SDK options a new client is about to connect with.
        :returns: Variable names or "its settings or arguments", never a value; ``None``
            when the key is in neither the CLI's environment nor its settings or extra
            arguments (other options, the system prompt among them, are not searched).
        """
        literal = self._credential_literal
        if literal is None:
            return None
        spawn_env = {**os.environ, **(getattr(options, "env", None) or {})}
        names = sorted(name for name, value in spawn_env.items() if literal in value)
        if names:
            return f"environment variable(s) {', '.join(names)}"
        extra_args = getattr(options, "extra_args", None) or {}
        argv = [str(getattr(options, "settings", None) or "")]
        argv += [str(part) for flag in extra_args.items() for part in flag if part is not None]
        escaped = json.dumps(literal)[1:-1]  # as the settings JSON would spell it
        held = any(literal in text or escaped in text for text in argv)
        return "its settings or arguments" if held else None

    def __del__(self) -> None:
        wrapper_path = getattr(self, "_cli_wrapper_path", None)
        if isinstance(wrapper_path, str):
            with suppress(Exception):
                pathlib.Path(wrapper_path).unlink(missing_ok=True)
        with suppress(Exception):
            self._remove_unwrapped_claude_config_dir()  # CORAL(S113)
        with suppress(Exception):
            self._remove_claude_config_seed()  # CORAL(S115)

    def _claude_config_dir_for_unwrapped_cli(self) -> pathlib.Path:
        """CORAL(S113): this executor's own 0700 Claude config dir, for a CLI it cannot wrap."""
        if self._unwrapped_claude_config_dir is None:
            path = pathlib.Path(tempfile.mkdtemp(prefix="omnigent-claude-config-"))
            claim_temp_dir(path)  # CORAL(S116): a killed harness's dir goes at a later sweep
            for name in _CLAUDE_CONFIG_BLOCKED_NAMES:
                (path / name).touch(mode=0o600, exist_ok=False)
            self._unwrapped_claude_config_dir = path
        return self._unwrapped_claude_config_dir

    def _remove_unwrapped_claude_config_dir(self) -> None:
        """CORAL(S113): remove the dir; a later turn makes a fresh one."""
        path, self._unwrapped_claude_config_dir = self._unwrapped_claude_config_dir, None
        if path is not None:
            shutil.rmtree(path, ignore_errors=True)

    def _write_claude_config_seed(self) -> frozenset[str]:
        """
        CORAL(S115): refresh the seed from the user's config just before a wrapped CLI launches.

        :returns: The names of the MCP servers it holds; none without a seed.
        :raises RuntimeError: If the seed cannot be written, or this executor was closed.
        """
        seed = self._claude_config_seed_path
        if seed is None:
            return frozenset()
        failure = "This agent's Claude CLI could not get its private Claude config"
        if self._claude_config_seed_removed:
            raise RuntimeError(f"{failure}: the executor is closed")
        try:
            # CORAL(S115): made at the first launch, and again if a temp cleaner removed it.
            # Anything else there, or a dir no longer private, fails the exclusive mkdir.
            if not (self._claude_config_seed_dir_made and _is_private_dir(seed.parent)):
                seed.parent.mkdir(mode=0o700)
                claim_temp_dir(seed.parent)  # CORAL(S116): a killed harness's seed goes later
                self._claude_config_seed_dir_made = True
            config = _claude_config_seed(os.environ)
            content = json.dumps(config)
            descriptor, temp = tempfile.mkstemp(prefix=f"{seed.name}.", dir=seed.parent)
            try:
                with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                    handle.write(content)
                os.replace(temp, seed)
            except BaseException:
                with suppress(OSError):
                    os.unlink(temp)
                raise
        except (OSError, RecursionError) as exc:
            raise RuntimeError(f"{failure}: {exc}") from exc
        return frozenset(cast("dict[str, object]", config.get("mcpServers", {})))

    def _warn_seeded_servers_signed_in_on_host(
        self, seeded: frozenset[str], mcp_auth: Mapping[str, str]
    ) -> None:
        """CORAL(S115): a sign-in the host manages stays in its store, out of the CLI's own dir."""
        for name in sorted(seeded & mcp_auth.keys() - self._claude_seed_sign_in_warned):
            self._claude_seed_sign_in_warned.add(name)
            logger.warning(
                "MCP server %r signs in through this host, but this agent's Claude CLI runs in "
                "an OS sandbox with its own Claude config, which lacks that sign-in, so the "
                "server may not connect there",
                name,
            )

    def _remove_claude_config_seed(self) -> None:
        """CORAL(S115): remove the seed; a later launch fails rather than make its dir again."""
        if self._claude_config_seed_path is not None:
            self._claude_config_seed_removed = True
            if self._claude_config_seed_dir_made:
                shutil.rmtree(self._claude_config_seed_path.parent, ignore_errors=True)

    def _new_gateway_shim(
        self, env: Mapping[str, str], credential: UpstreamCredential | None, *, direct: bool
    ) -> ClaudeGatewayShim:
        """CORAL(S124, S125): the shim for this executor's CLIs, not yet started.

        :param env: The CLI's ``options.env``; a gateway's names its URL.
        :param credential: The real credential of a Coral CLI, else ``None`` for a plain shim.
        :param direct: Whether this is a Coral CLI on a key with no gateway.
        :raises OSError: For an upstream the credential may not go to; names no value.
        :raises _CredentialProxyRefusedError: For a proxy the upstream client cannot use.
        """
        # CORAL(S124): never None here: a gateway's env names its URL (checked by the caller)
        upstream = self._proxy_upstream(env) or env["ANTHROPIC_BASE_URL"]
        if credential is None:
            return ClaudeGatewayShim(upstream_base_url=upstream)
        # Checked again here: a turn of another session may have read the settings since.
        check_upstream_url(upstream)
        self._proxy_is_first_party = direct and _is_first_party_url(upstream)
        # CORAL(S124): the shim holds the credential; its upstream hop takes the proxy the
        # harness had before the scrub, which may carry userinfo.
        # CORAL(S125): after the proxy and CA file the user's settings name. The harness's
        # environment does not hold those, so the client then reads no proxy from it.
        upstream_proxy, env_proxies = self._upstream_hop_proxy(upstream)
        return ClaudeGatewayShim(
            upstream_base_url=upstream,
            credential=credential,
            upstream_proxy=upstream_proxy,
            upstream_ca_file=self._upstream_ca_file() if direct else None,
            upstream_env_proxies=env_proxies,
        )

    async def _route_options_through_gateway_shim(self, options: SdkOptions) -> None:
        """
        Point a new client's ``ANTHROPIC_BASE_URL`` at the local shim.

        On the gateway path the Claude CLI strips ``thinking.display``
        from its requests (experimental betas are disabled there),
        which silences opus thinking; the shim restores the field. See
        the :mod:`~omnigent.inner.claude_gateway_shim` module
        docstring for the full failure chain. No-op off the gateway
        path, except for a Coral CLI on an API key (CORAL(S124)), whose
        shim is its credential proxy in front of :meth:`_proxy_upstream`.

        :param options: SDK options about to be passed to
            ``ClaudeSDKClient``; ``options.env["ANTHROPIC_BASE_URL"]``
            is rewritten in place to the shim's loopback URL.
        :raises RuntimeError: If the gateway path produced options
            without an ``ANTHROPIC_BASE_URL`` — a config bug that
            would silently bypass the shim.
        """
        # CORAL(S124): a Coral CLI with a key and no gateway is routed too, to hold no key
        credential = self._upstream_credential
        direct = not self._gateway and credential is not None
        if not self._gateway and not direct:
            return
        env = getattr(options, "env", None)
        if not isinstance(env, dict) or not (direct or "ANTHROPIC_BASE_URL" in env):
            raise RuntimeError(
                "ClaudeSDKExecutor(gateway=True) built SDK options without "
                "env['ANTHROPIC_BASE_URL']; cannot route through the gateway shim."
            )
        # CORAL(S125): a proxy that fails to start is dropped, so the next turn builds one
        # from the settings as they are then
        async with self._gateway_shim_lock:
            shim = self._gateway_shim
            try:
                if shim is None:
                    shim = self._new_gateway_shim(env, credential, direct=direct)
                    self._gateway_shim = shim
                await shim.start()
            except OSError as exc:
                if credential is None:
                    raise
                self._gateway_shim = None
                if shim is not None:
                    await shim.aclose()
                detail = str(exc)
                if exc.errno is not None:  # the system's own text may name a path
                    detail = f"its credential proxy could not start ({type(exc).__name__})"
                raise _CredentialProxyRefusedError(detail) from None
        env["ANTHROPIC_BASE_URL"] = shim.base_url
        # CORAL(S124): the session token is all the CLI holds; its hop here stays off proxies
        if (session_token := shim.session_token) is not None:
            env[_PROXY_TOKEN_ENV] = session_token
            _keep_loopback_unproxied(env)
        # CORAL(S124): behind a proxy for the Anthropic API itself the CLI keeps the behaviour
        # it had on that API; behind any other endpoint it stays on a custom one, as before
        if self._proxy_is_first_party:
            env[_ASSUME_FIRST_PARTY_ENV] = "1"

    async def _get_or_create_client(
        self,
        sdk: _ClaudeSDK,
        *,
        session_key: str,
        options: SdkOptions,
        model: str | None,
    ) -> _ClaudeClient:
        state = self._clients.get(session_key)
        if state is None:
            seeded_servers = self._write_claude_config_seed()  # CORAL(S115)
            mcp_auth = _claude_mcp_auth_statuses()
            self._warn_seeded_servers_signed_in_on_host(seeded_servers, mcp_auth)  # CORAL(S115)
            await self._route_options_through_gateway_shim(options)
            # CORAL(S124): fail closed before every connect rather than hand the CLI the key
            if (held_in := self._credential_exposure(options)) is not None:
                raise _CredentialExposedError(
                    "This step's Claude CLI would hold the model API key, which only its "
                    f"credential proxy may hold; it is in {held_in}. The CLI was not started."
                )
            # Tee CLI stderr so the connect timeout error carries the
            # tail; ``_on_stderr`` alone only logs at DEBUG.
            connect_stderr: list[str] = []
            original_stderr = getattr(options, "stderr", None)

            def _tee_stderr(line: str) -> None:
                connect_stderr.append(line)
                if original_stderr is not None:
                    original_stderr(line)

            options.stderr = _tee_stderr
            client = sdk.ClaudeSDKClient(options)
            try:
                # CLAUDECODE must be absent (not just empty) in the child
                # env — otherwise the claude cli reports a nested-session
                # error. The SDK merges ``os.environ`` with ``options.env``,
                # so we unset in ``os.environ`` for the spawn window.
                #
                # ANTHROPIC_API_KEY is also stripped so the CLI uses its
                # subscription auth rather than a developer API key that
                # would charge separately. Safe even in Databricks mode:
                # ``options.settings`` explicitly sets apiKeyHelper and
                # ``options.env`` sets the Databricks base URL, so the
                # Claude CLI does not need an inherited Anthropic key.
                #
                # DATABRICKS-PATCH(claude-sdk-gateway-betas): on the Databricks
                # gateway we negotiate betas rather than disabling them, but
                # *omitting* CLAUDE_CODE_DISABLE_EXPERIMENTAL_BETAS from
                # ``options.env`` does not beat an INHERITED one — Databricks
                # runners export it (devtools/ai/databricks_auth/gateway_env.py
                # and the arca/isaac runners), and the merge puts os.environ
                # under options.env. Without this the child still strips
                # interleaved-thinking and the gateway still answers 400. Scoped
                # to launches that negotiate (CLAUDE_CODE_USE_GATEWAY): the
                # non-gateway branch re-adds the key through ``options.env``,
                # which wins over os.environ, and a non-gateway session keeps
                # whatever it inherited.
                sdk_env = getattr(options, "env", None)
                with ExitStack() as env_stack:
                    env_stack.enter_context(_unset_env_var("CLAUDECODE"))
                    env_stack.enter_context(_unset_env_var("ANTHROPIC_API_KEY"))
                    # CORAL(S13): no subscription token reaches a Coral spec's CLI
                    if self._require_api_credential:
                        for name in _SUBSCRIPTION_TOKEN_ENV:
                            env_stack.enter_context(_unset_env_var(name))
                    # CORAL(S113): nor a config dir the host forwards
                    if self._isolate_claude_config:
                        for name in _CLAUDE_CONFIG_ENV:
                            env_stack.enter_context(_unset_env_var(name))
                    if isinstance(sdk_env, dict) and "CLAUDE_CODE_USE_GATEWAY" in sdk_env:
                        env_stack.enter_context(
                            _unset_env_var("CLAUDE_CODE_DISABLE_EXPERIMENTAL_BETAS")
                        )
                    await asyncio.wait_for(client.connect(), timeout=_CONNECT_TIMEOUT_SECONDS)
            except TimeoutError as exc:
                await self._force_close_client(client)
                tail = "\n".join(line.rstrip() for line in connect_stderr[-40:])
                detail = tail or "(no CLI stderr captured)"
                logger.warning(
                    "Claude SDK connect timed out after %ds; CLI stderr tail:\n%s",
                    int(_CONNECT_TIMEOUT_SECONDS),
                    detail,
                )
                raise TimeoutError(
                    f"Claude SDK client connect timed out after "
                    f"{int(_CONNECT_TIMEOUT_SECONDS)}s. CLI stderr tail:\n{detail}"
                ) from exc
            except Exception as exc:
                # The CLI may exit immediately (e.g. ``unknown option``) before
                # the SDK's async stderr reader has flushed all output.  A brief
                # yield lets pending reader callbacks deliver remaining lines so
                # the error message is useful rather than just "Command failed
                # with exit code 1; Check stderr output for details".
                await asyncio.sleep(0.1)
                await self._force_close_client(client)
                tail = "\n".join(line.rstrip() for line in connect_stderr[-40:])
                detail = tail or "(no CLI stderr captured)"
                logger.error(
                    "Claude SDK connect failed: %s\nCLI stderr tail:\n%s",
                    exc,
                    detail,
                )
                raise RuntimeError(
                    f"Claude SDK connect failed: {exc}\nCLI stderr:\n{detail}"
                ) from exc
            finally:
                # Restore on both paths so post-connect stderr flows
                # directly to the original callback and ``connect_stderr``
                # can be GC'd instead of growing for the session lifetime.
                options.stderr = original_stderr
            current_task: asyncio.Task[None] | None = cast(
                "asyncio.Task[None] | None", asyncio.current_task()
            )
            state = _ClaudeClientState(
                client=client,
                model=model,
                loop=asyncio.get_running_loop(),
                task=current_task,
                effort=getattr(options, "effort", None),
                mcp_auth=mcp_auth,
            )
            self._clients[session_key] = state
            # CORAL(S116): the SDK's version check left its launch behind
            await _sweep_orphaned_temp_dirs()
            return client

        if state.model != model:
            await state.client.set_model(model)
            state.model = model
        return state.client

    async def _reconnect_signed_in_mcp_servers(self, state: _ClaudeClientState) -> bool:
        """Reconnect servers the host reports signed in since this client last checked.

        The CLI connects MCP servers only at startup, so one that failed while its
        sign-in was pending stays failed for the life of the client.

        :returns: ``False`` when the CLI is still busy with a timed-out request and
            would hold the next prompt, so the client must be replaced.
        """
        current = _claude_mcp_auth_statuses()
        signed_in = {
            name
            for name, status in current.items()
            if status == "connected" and state.mcp_auth.get(name) != "connected"
        }
        try:
            retry = (
                await _reconnect_failed_mcp_servers(state.client, signed_in)
                if signed_in
                else set()
            )
        except TimeoutError:
            logger.warning(
                "Reconnecting MCP servers timed out; restarting the Claude CLI, "
                "which connects them as it starts"
            )
            return False
        # A server left out of the snapshot is checked again next turn.
        state.mcp_auth = {name: status for name, status in current.items() if name not in retry}
        return True

    async def close_session(self, session_key: str) -> None:
        self._crashed_sessions.pop(session_key, None)
        await self._close_live_client(session_key)

    async def _close_live_client(self, session_key: str) -> None:
        state = self._clients.pop(session_key, None)
        if state is None:
            return
        try:
            current_loop = asyncio.get_running_loop()
            current_task = asyncio.current_task()
        except RuntimeError:
            current_loop = None
            current_task = None

        same_loop = state.loop is None or current_loop is state.loop
        same_task = state.task is None or current_task is state.task
        if not (same_loop and same_task):
            logger.debug(
                "Force-closing Claude SDK client for session %s (different event loop/task; "
                "expected once the connecting turn has finished, e.g. idle reap / shutdown)",
                session_key,
            )
            await self._force_close_client(state.client)
            return
        # CORAL(S116): the SDK's close ends only the launcher, which the CLI can outlive
        tree = _client_process_tree(state.client)
        try:
            await state.client.disconnect()
        except RuntimeError as exc:
            if "different task" not in str(exc):
                raise
            logger.debug(
                "Force-closing Claude SDK client for session %s (different task; "
                "expected once the connecting turn has finished, e.g. idle reap / shutdown)",
                session_key,
            )
            await self._force_close_client(state.client)
            return
        await _reap_tree(tree, timeout=_GRACEFUL_TREE_SECONDS)  # CORAL(S116): before the sweep
        # SDK's disconnect() doesn't close the asyncio transport;
        # call _force_close_client to flip transport._closed before
        # the loop tears down.
        await self._force_close_client(state.client)

    def _evict_client_on_cancel(self, session_key: str) -> None:
        state = self._clients.pop(session_key, None)
        if state is None:
            return
        # Close in the background: an await here runs under an in-flight
        # cancellation and could itself be cancelled, leaking the CLI process.
        task = asyncio.create_task(self._force_close_client(state.client))
        self._cancel_close_tasks.add(task)
        task.add_done_callback(self._cancel_close_tasks.discard)

    async def _evict_terminated_client(self, session_key: str) -> None:
        """Discard a cached client after its CLI child exits."""
        state = self._clients.get(session_key)
        if state is None:
            return
        transport = getattr(state.client, "_transport", None)
        process = getattr(transport, "_process", None)
        # A non-None returncode is exactly the reaped-corpse state the SDK's
        # write() refuses; a missing transport/process reads as alive and is skipped.
        returncode = getattr(process, "returncode", None)
        if returncode is None:
            return
        logger.warning(
            "Claude SDK CLI for session %s terminated between turns "
            "(exit code: %s); discarding the dead client so this turn "
            "rebuilds a fresh one.",
            session_key,
            returncode,
        )
        await self._close_live_client(session_key)

    async def close(self) -> None:
        try:
            session_keys = list(self._clients)
            for session_key in session_keys:
                await self.close_session(session_key)
            # CORAL(S116): clients evicted on cancel finish closing first; then the last sweep
            # CORAL(S124): and before the shim stops, so no CLI outlives the port it calls
            loop = asyncio.get_running_loop()
            evictions = [task for task in self._cancel_close_tasks if task.get_loop() is loop]
            if evictions:
                await asyncio.wait(evictions, timeout=_CLOSE_WAIT_SECONDS)
        finally:
            # CORAL(S124): a close cut short (the adapter bounds it) or one that failed still
            # stops the shim, which holds the credential; a second cancel cannot stop the stop
            stop = asyncio.ensure_future(self._stop_gateway_shim())
            _SHIM_STOPS.add(stop)
            stop.add_done_callback(_SHIM_STOPS.discard)
            try:
                await asyncio.shield(stop)
            finally:
                self._remove_unwrapped_claude_config_dir()  # CORAL(S113)
                self._remove_claude_config_seed()  # CORAL(S115)
        await _sweep_orphaned_temp_dirs(_CLOSE_WAIT_SECONDS, wait_turn=_CLOSE_WAIT_SECONDS)

    async def _stop_gateway_shim(self) -> None:
        """CORAL(S124): stop the shim, and a credential command still running without one."""
        shim, self._gateway_shim = self._gateway_shim, None
        credential = getattr(self, "_upstream_credential", None)
        if shim is not None:
            await shim.aclose()  # stops its credential too
        elif credential is not None:
            await credential.aclose()

    async def interrupt_session(self, session_key: str) -> bool:
        state = self._clients.get(session_key)
        if state is None:
            return False
        # Interrupt is best-effort and fast; a failure just falls through to
        # the close below.
        try:
            await asyncio.wait_for(state.client.interrupt(), timeout=0.5)
        except Exception as exc:  # noqa: BLE001 — interrupt is best-effort
            logger.warning(
                "Claude SDK interrupt failed for session %s: %s",
                session_key,
                exc,
            )
        # Always drop the live session after an interrupt. Its transcript
        # still holds the abandoned prompt, and resumed turns send only the
        # latest user message (see _build_prompt), so the runner's
        # "[System: interrupted]" marker would never reach the model. Closing
        # forces the next turn to rebuild full history (marker included) in a
        # fresh session — the abandoned request is then visible-but-superseded
        # rather than silently continued.
        try:
            await self.close_session(session_key)
            return True
        except Exception as exc:  # noqa: BLE001 — close failures surface via False return
            logger.warning(
                "Claude SDK session close after interrupt failed for session %s: %s",
                session_key,
                exc,
            )
            return False

    async def enqueue_session_message(
        self,
        session_key: str,  # noqa: ARG002
        content: str | Message,  # noqa: ARG002
    ) -> bool:
        # query() queues a NEW turn on the SDK's stdin; it does not inject
        # into the turn already running. Returning False lets the adapter's
        # buffer hold the message and re-deliver it as a continuation turn
        # once the active turn ends, preserving in-order delivery.
        return False

    @staticmethod
    async def _force_close_client(client: _ClaudeClient) -> None:
        # getattr defensively: runs on the success path too, so must
        # no-op against test fakes that only stub `disconnect`.
        query = getattr(client, "_query", None)
        if query is not None:
            query._closed = True
            tg = getattr(query, "_tg", None)
            if tg is not None:
                with suppress(Exception):
                    tg.cancel_scope.cancel()

        transport = getattr(client, "_transport", None)
        if transport is not None:
            # The SDK's stderr reader changed shape across revs: current
            # claude-agent-sdk (>=0.2.x) exposes a single ``_stderr_task``
            # TaskHandle with ``cancel()``; older revs an anyio
            # ``_stderr_task_group``. Probe both via getattr so a force-close
            # never raises AttributeError out of lifespan shutdown (which
            # crashed the runner on session stop).
            stderr_task = getattr(transport, "_stderr_task", None)
            if stderr_task is not None:
                with suppress(Exception):
                    stderr_task.cancel()
            else:
                stderr_tg = getattr(transport, "_stderr_task_group", None)
                if stderr_tg is not None:
                    with suppress(Exception):
                        stderr_tg.cancel_scope.cancel()

            for stream in (
                transport._stdout_stream,
                transport._stdin_stream,
                transport._stderr_stream,
            ):
                if stream is not None:
                    _best_effort_close(stream)

            process = transport._process
            if process is not None:
                if process.returncode is None:
                    # CORAL(S116): the CLI can outlive its launcher, so the whole tree is waited on
                    tree = _proc.snapshot_child_tree(process)
                    _terminate_process_tree(process)
                    try:
                        await _wait_for_tree(process, tree, timeout=5)  # CORAL(S116)
                    except TimeoutError:
                        _kill_process_tree(process)
                        _proc.kill_members(tree)  # CORAL(S116)
                        # CORAL(S116): bounded, as a pipe held outside the tree outlives the kill
                        with suppress(TimeoutError):
                            await _wait_for_tree(process, tree, timeout=1)
                    except asyncio.CancelledError:
                        _kill_process_tree(process)
                        _proc.kill_members(tree)  # CORAL(S116)
                        with suppress(TimeoutError):  # CORAL(S116): bounded, as above
                            await _wait_for_tree(process, tree, timeout=1)

                _best_effort_close(process)
                # The SDK's `transport._process` is an anyio Process;
                # `_best_effort_close` can't reach its asyncio
                # transport (no sync `close`). Close it explicitly.
                close_anyio_subprocess_transport(process)

            transport._process = None
            transport._stdout_stream = None
            transport._stdin_stream = None
            transport._stderr_stream = None
            if getattr(transport, "_stderr_task", None) is not None:
                transport._stderr_task = None
            if getattr(transport, "_stderr_task_group", None) is not None:
                transport._stderr_task_group = None
            transport._ready = False

        client._query = None
        client._transport = None
        await _sweep_orphaned_temp_dirs()  # CORAL(S116): a launch this teardown killed

    def supports_streaming(self) -> bool:
        return True

    def supports_tool_calling(self) -> bool:
        return True

    def handles_tools_internally(self) -> bool:
        return True

    def replays_tool_history(self) -> bool:
        return True

    def supports_live_message_queue(self) -> bool:
        # The SDK has no API to inject into an active turn; claiming this
        # capability caused the one-turn-behind desync described in #3472.
        return False

    def supports_tool_boundary_interrupt(self) -> bool:
        return True

    def max_context_tokens(self) -> int | None:
        return None  # SDK manages its own context

    def _session_key(self, messages: list[Message]) -> str:
        for msg in reversed(messages):
            session_id = msg.get("session_id")
            if session_id:
                return str(session_id)
            metadata = msg.get("metadata", {})
            if isinstance(metadata, dict) and metadata.get("session_id"):
                return str(metadata["session_id"])
        return "default"

    async def _apply_gateway_model_vocabulary(
        self,
        env: dict[str, str],
        auth_command: str | None,
        credential: UpstreamCredential | None = None,
    ) -> dict[str, str]:
        """
        Pin the family aliases in *env* and report Claude Code's id rewrites.

        On a gateway transport, list the gateway's models once and derive both
        halves of Claude Code's model vocabulary from that listing: the
        ``ANTHROPIC_DEFAULT_*_MODEL`` pins that resolve a family alias to a
        served id, and the canonical-to-served rewrites for the ids the CLI
        names on its own (its refusal-fallback route table). A no-op off the
        gateway, where a direct Anthropic endpoint speaks canonical ids itself.

        Pins already present are respected. The rewrites still apply to those
        launches: pinning an alias does not teach Claude Code how this gateway
        spells the canonical ids its own route table names.

        :param env: The child-process env dict, mutated in place with the pins.
        :param auth_command: The gateway ``apiKeyHelper`` command used to mint
            a bearer for the model listing.
        :param credential: CORAL(S124): the credential proxy's own holder of that command;
            the listing takes its bearer there, so the command has one runner.
        :returns: Canonical-to-served rewrites for the ``modelOverrides``
            setting. Empty off the gateway or when discovery found nothing.
        """
        base_url = env.get("ANTHROPIC_BASE_URL")
        if not self._gateway or not base_url:
            return {}
        vocabulary = self._gateway_vocabulary
        if vocabulary is None:
            try:
                # CORAL(S124): only the proxy's credential runs the command; the listing waits
                # as long as its own run of it did, and the run goes on for the proxy
                bearer = (
                    None
                    if credential is None
                    else await asyncio.wait_for(credential.get(), _LISTING_CREDENTIAL_WAIT_S)
                )
            except (UpstreamCredentialError, TimeoutError) as exc:  # CORAL(S124): best-effort
                logger.warning(
                    "claude-sdk: no credential to list the gateway's models with (%s); "
                    "leaving ANTHROPIC_DEFAULT_*_MODEL and modelOverrides unset",
                    type(exc).__name__,
                )
                vocabulary = _EMPTY_GATEWAY_VOCABULARY
            else:
                vocabulary = await run_sync_on_thread(
                    _gateway_model_vocabulary, base_url, auth_command, bearer
                )
            self._gateway_vocabulary = vocabulary
        for var, model_id in vocabulary.alias_pins.items():
            env.setdefault(var, model_id)
        return vocabulary.model_overrides

    def _install_framework_context_hook(
        self, sdk: _ClaudeSDK, options: SdkOptions, session_key: str
    ) -> None:
        """Read current-turn context even when the SDK reuses its original hooks."""
        hook_matcher = getattr(sdk, "HookMatcher", None)
        if hook_matcher is None:
            return

        async def add_context(
            _payload: object, _tool_use_id: str | None, _context: object
        ) -> _JsonObject:
            text = self._pending_framework_context.pop(session_key, "")
            if not text:
                return {}
            return {
                "hookSpecificOutput": {
                    "hookEventName": "UserPromptSubmit",
                    "additionalContext": text,
                }
            }

        hooks = dict(getattr(options, "hooks", None) or {})
        hooks.setdefault("UserPromptSubmit", []).append(hook_matcher(hooks=[add_context]))
        options.hooks = hooks

    def _install_subagent_router_hook(
        self,
        sdk: _ClaudeSDK,
        options: Any,  # type: ignore[explicit-any]  # ClaudeAgentOptions — avoid a hard sdk import
        model: str | None,
    ) -> None:
        """
        Register the in-process subagent-routing ``PreToolUse`` hook.

        The claude-agent-sdk runs hook callbacks in this process, so the
        native hook script's decision logic is imported instead of
        subprocessed. No-op unless the runner advertises a
        ``route-subagent`` endpoint, so unrouted sessions register nothing.

        :param sdk: The ``claude_agent_sdk`` module (or a test double).
        :param options: ``ClaudeAgentOptions`` to mutate.
        :param model: Model this session runs on, sent as the spawn's
            parent model.
        """
        hook_matcher_cls = getattr(sdk, "HookMatcher", None)
        if hook_matcher_cls is None:
            return
        router_dir = subagent_router.discover_router_dir()
        if subagent_router.read_router_endpoint(router_dir) is None:
            return

        async def route_spawn(
            payload: Any,  # type: ignore[explicit-any]  # HookInput TypedDict
            tool_use_id: str | None,  # noqa: ARG001 -- HookCallback signature
            context: Any,  # type: ignore[explicit-any]  # HookContext  # noqa: ARG001 -- HookCallback signature
        ) -> dict[str, Any]:  # type: ignore[explicit-any]  # HookJSONOutput
            if not isinstance(payload, dict):
                return {}
            output = await asyncio.to_thread(
                subagent_router.route_pre_tool_use,
                payload,
                harness="claude-sdk",
                router_dir=router_dir,
                parent_model=model,
            )
            return output or {}

        hooks = dict(getattr(options, "hooks", None) or {})
        entries = list(hooks.get("PreToolUse") or [])
        entries.append(
            hook_matcher_cls(
                matcher=subagent_router.AGENT_TOOL_MATCHER,
                # Strictly outside the router call's own HTTP budget: equal
                # numbers let the SDK cancel the hook at the same instant its
                # request gives up, so the fail-open branch never ran.
                timeout=subagent_router.HOOK_TIMEOUT_S,
                hooks=[route_spawn],
            )
        )
        hooks["PreToolUse"] = entries
        options.hooks = hooks

    def _ask_user_question_enabled(self, sdk: _ClaudeSDK) -> bool:
        """Whether ``AskUserQuestion`` may be exposed to the model.

        True only when BOTH the answer bridge is wired AND the SDK exposes
        ``HookMatcher`` (so the PreToolUse intercept can actually be
        installed). Exposing the tool without the intercept would hang
        headless, so :meth:`_base_tools` and
        :meth:`_install_ask_user_question_hook` gate on this single predicate
        — they can never disagree.
        """
        return (
            self._ask_question_handler is not None
            and getattr(sdk, "HookMatcher", None) is not None
        )

    def _base_tools(self, sdk: _ClaudeSDK) -> list[str]:
        """Native Claude Code tools exposed to the model.

        ``Skill`` and ``ToolSearch`` are always present so MCP tool
        definitions can be discovered on demand. ``AskUserQuestion`` is added
        only when :meth:`_ask_user_question_enabled` — the tool would hang
        headless without the PreToolUse intercept, so it's never exposed
        without the bridge that answers it. OS-environment operations route
        through Omnigent ``sys_os_*`` MCP tools, not the SDK's native
        Bash/Read/Edit/Write.
        """
        tools = ["Skill", "ToolSearch"]
        if self._ask_user_question_enabled(sdk):
            tools.append("AskUserQuestion")
        return tools

    # The SDK awaits hook callbacks with no cap, so this is the human-answer
    # ceiling; it matches the native path's 24h permission-hook timeout.
    _ASK_QUESTION_HOOK_TIMEOUT_S: float = 86400.0

    def _install_ask_user_question_hook(
        self,
        sdk: _ClaudeSDK,
        options: Any,  # type: ignore[explicit-any]  # ClaudeAgentOptions — avoid a hard sdk import
    ) -> None:
        """
        Register the in-process ``AskUserQuestion`` PreToolUse hook.

        Claude Code's ``AskUserQuestion`` tool would normally open a terminal
        picker — impossible under the headless SDK. This hook intercepts the
        call, routes the questions through the Omnigent elicitation form (the
        clickable card the web UI renders), and returns the user's selections
        via ``updatedInput`` so Claude reports them as the tool result.

        Allowing from PreToolUse skips ``can_use_tool``, so the hook runs the
        TOOL_CALL policy check itself before showing the form.

        No-op unless the adapter has wired an ``_ask_question_handler``; the
        bridge is what reaches the active turn's elicitation round-trip.

        :param sdk: The ``claude_agent_sdk`` module (or a test double).
        :param options: ``ClaudeAgentOptions`` to mutate.
        """
        if not self._ask_user_question_enabled(sdk):
            return
        # Presence is guaranteed by _ask_user_question_enabled; fetch via
        # getattr (not ``sdk.HookMatcher``) because ``HookMatcher`` isn't
        # declared on the _ClaudeSDK protocol.
        hook_matcher_cls = getattr(sdk, "HookMatcher")  # noqa: B009

        def _deny(reason: str) -> dict[str, Any]:  # type: ignore[explicit-any]  # HookJSONOutput
            # Fail closed: a path that can't produce answers denies, so Claude
            # never falls through to a headless native picker that hangs.
            return {
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "permissionDecision": "deny",
                    "permissionDecisionReason": reason,
                }
            }

        async def handle_ask_user_question(
            payload: Any,  # type: ignore[explicit-any]  # HookInput TypedDict
            tool_use_id: str | None,  # noqa: ARG001 -- HookCallback signature
            context: Any,  # type: ignore[explicit-any]  # HookContext  # noqa: ARG001 -- HookCallback signature
        ) -> dict[str, Any]:  # type: ignore[explicit-any]  # HookJSONOutput
            handler = self._ask_question_handler
            if handler is None or not isinstance(payload, dict):
                # Defensive / can't-happen (exposure is gated on the handler):
                # deny deterministically rather than fall through to consent.
                return _deny("AskUserQuestion unavailable via Coral")
            tool_input = payload.get("tool_input") or {}
            # A raised hook reaches the CLI as "no opinion" and falls back to
            # native handling; deny instead. Cancellation still propagates.
            try:
                policy_result = await self._evaluate_tool_call_policy(
                    "AskUserQuestion", tool_input
                )
                if getattr(policy_result, "behavior", None) == "deny":
                    return _deny(
                        getattr(policy_result, "message", "") or "Denied by Coral TOOL_CALL policy"
                    )
                updated_input = await handler(tool_input)
            except Exception:
                logger.exception("AskUserQuestion hook failed; denying the call")
                return _deny("AskUserQuestion failed in Coral; ask in plain text instead.")
            if isinstance(updated_input, str):
                return _deny(updated_input)
            return {
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "permissionDecision": "allow",
                    "updatedInput": updated_input,
                }
            }

        hooks = dict(getattr(options, "hooks", None) or {})
        entries = list(hooks.get("PreToolUse") or [])
        entries.append(
            hook_matcher_cls(
                matcher="AskUserQuestion",
                timeout=self._ASK_QUESTION_HOOK_TIMEOUT_S,
                hooks=[handle_ask_user_question],
            )
        )
        hooks["PreToolUse"] = entries
        options.hooks = hooks

    # CORAL(S21): a slow evaluator denies; a raw ASK waits as long as AskUserQuestion
    _TOOL_CALL_POLICY_DEADLINE_S: float = 60.0

    def _install_tool_call_policy_hook(self, sdk: _ClaudeSDK, options: SdkOptions) -> bool:
        """CORAL(S21): gate every tool call on TOOL_CALL policy from a catch-all PreToolUse hook.

        :param sdk: The ``claude_agent_sdk`` module (or a test double).
        :param options: ``ClaudeAgentOptions`` to mutate.
        :returns: Whether the hook was installed, so ``can_use_tool`` skips its policy half.
        """
        hook_matcher_cls = getattr(sdk, "HookMatcher", None)
        policy_evaluator = getattr(self, "_policy_evaluator", None)
        if not self._tool_call_policy_hook or policy_evaluator is None or hook_matcher_cls is None:
            return False
        ask_hook_installed = self._ask_user_question_enabled(sdk)

        def _decide(decision: str, reason: str | None = None) -> _JsonObject:
            output: _JsonObject = {"hookEventName": "PreToolUse", "permissionDecision": decision}
            if reason is not None:
                output["permissionDecisionReason"] = reason
            return {"hookSpecificOutput": output}

        async def gate(payload: object, _tool_use_id: str | None, _context: object) -> _JsonObject:
            unchecked = "Coral could not check this tool call against policy"
            if not isinstance(payload, dict):
                return _decide("deny", unchecked)
            tool_name = str(payload.get("tool_name") or "")
            if ask_hook_installed and tool_name == "AskUserQuestion":
                return {}
            try:
                result = await self._evaluate_tool_call_policy(
                    tool_name,
                    payload.get("tool_input") or {},
                    evaluator_deadline_s=self._TOOL_CALL_POLICY_DEADLINE_S,
                )
            except Exception:
                logger.exception("TOOL_CALL policy hook failed; denying tool=%s", tool_name)
                return _decide("deny", unchecked)
            behavior = getattr(result, "behavior", None)
            if behavior == "deny":
                return _decide("deny", getattr(result, "message", "") or "Denied by Coral policy")
            if behavior == "allow":
                return _decide("allow")
            return {}

        hooks = dict(getattr(options, "hooks", None) or {})
        hooks["PreToolUse"] = [
            *hooks.get("PreToolUse", []),
            hook_matcher_cls(
                matcher=None, timeout=self._ASK_QUESTION_HOOK_TIMEOUT_S, hooks=[gate]
            ),
        ]
        options.hooks = hooks
        return True

    async def _can_use_tool_for_permission(
        self,
        tool_name: str,
        tool_input: ToolArgs,
        perm_ctx: object,
    ) -> object:
        """
        Route a Claude SDK permission request through the Omnigent elicitation system.

        Installed as ``options.can_use_tool`` when ``permission_mode`` is
        not ``"bypassPermissions"`` and an elicitation handler has been wired
        in by :class:`omnigent.runtime.harnesses._executor_adapter.ExecutorAdapter`.
        Called by the SDK before each tool invocation.

        :param tool_name: Name of the tool Claude wants to call,
            e.g. ``"Bash"``.
        :param tool_input: Arguments dict for the tool call,
            e.g. ``{"command": "ls -la"}``.
        :param perm_ctx: :class:`claude_agent_sdk.ToolPermissionContext`
            carrying ``tool_use_id`` (the SDK-assigned id for this specific
            invocation), ``agent_id`` (non-None inside sub-agents), and
            ``suggestions`` (permission hints from the CLI). Used here for
            diagnostic logging so unexpected permission requests are traceable.
        :returns: :class:`claude_agent_sdk.PermissionResultAllow` when the
            user approves, or :class:`claude_agent_sdk.PermissionResultDeny`
            with a ``message`` when they deny.
        """
        from claude_agent_sdk import PermissionResultAllow, PermissionResultDeny

        tool_use_id: str | None = getattr(perm_ctx, "tool_use_id", None)
        logger.debug(
            "permission request: tool=%s tool_use_id=%s",
            tool_name,
            tool_use_id,
        )
        if self._elicitation_handler is None:
            # No handler installed — grant by default. This branch is
            # unreachable in normal operation (run_turn only sets
            # can_use_tool when _elicitation_handler is not None), but
            # is included for safety if the SDK ever calls the callback
            # after the handler was cleared.
            return PermissionResultAllow()
        allowed = await self._elicitation_handler(tool_name, tool_input)
        if allowed:
            return PermissionResultAllow()
        return PermissionResultDeny(message="Denied via Coral elicitation")

    async def _evaluate_tool_call_policy(
        self,
        tool_name: str,
        tool_input: ToolArgs,
        *,
        evaluator_deadline_s: float | None = None,
    ) -> object | None:
        """
        Run a pre-execution TOOL_CALL policy evaluation for one tool call.

        This is the policy half of the ``can_use_tool`` gate. It exists
        so connector-native MCP tools — ones injected by the Claude Agent
        SDK / claude.ai connector layer (e.g. ``mcp__github__*``,
        ``mcp__atlassian__*``) that are NOT part of the agent spec's
        ``mcp_servers`` and execute INSIDE the CLI subprocess — get
        evaluated against Omnigent TOOL_CALL-phase policies BEFORE they
        run. Without this gate those calls bypass policy entirely (the
        executor only OBSERVES them in the message stream, which posts no
        policy event).

        Double-evaluation guard: Omnigent's OWN tools are exposed as the
        single ``omnigent`` SDK MCP server (the model sees
        ``mcp__omnigent__*``). When the model calls one, the SDK wrapper
        routes it back through Omnigent's dispatch bridge
        (``_stable_tool_executor`` -> ``TurnContext.dispatch_tool`` ->
        ``action_required``), and the runner re-dispatches it via
        ``ProxyMcpManager``, which enforces TOOL_CALL + TOOL_RESULT
        policies server-side before forwarding to ``/mcp/execute``
        (see ``omnigent/runner/app.py`` "All tool calls go through AP:/mcp
        ... which enforces TOOL_CALL + TOOL_RESULT policies server-side").
        Spec-declared MCP tools are surfaced through that same
        ``mcp__omnigent__*`` server, so they are covered there too.
        Evaluating ``mcp__omnigent__*`` here as well would double-count
        the same call (and could double-charge a cost-budget checkpoint),
        so we SKIP that prefix and only gate the connector-native /
        out-of-band tools the dispatch path never sees.

        :param tool_name: Full SDK tool name, e.g.
            ``"mcp__github__issue_write"``.
        :param tool_input: Arguments dict for the tool call.
        :param evaluator_deadline_s: CORAL(S21): seconds the evaluator may take,
            raising ``TimeoutError`` past it; elicitation is not bounded by it.
        :returns: :class:`claude_agent_sdk.PermissionResultDeny` when a
            policy denies the call. ``POLICY_ACTION_ASK`` is normally
            collapsed to a hard ALLOW/DENY by the server-side
            ``/policies/evaluate`` route. If a raw ASK reaches this callback
            (for example from a read-only evaluation path), this hook runs the
            existing Omnigent elicitation handler before returning
            :class:`claude_agent_sdk.PermissionResultAllow` or DENY; without
            a handler it fails closed. Returns ``None`` when the call should
            be allowed to proceed (no policy evaluator wired, an
            ``mcp__omnigent__*`` tool already gated on the dispatch path, or
            an ALLOW / no-match verdict). Returning ``None`` lets the caller
            fall through to its remaining gate logic (elicitation) without
            forcing an allow.
        """
        _policy_eval = getattr(self, "_policy_evaluator", None)
        if _policy_eval is None:
            return None
        # Omnigent's own tools are already TOOL_CALL-gated server-side via
        # the dispatch bridge / ProxyMcpManager — don't evaluate them twice.
        if tool_name.startswith(_OMNIGENT_MCP_PREFIX):
            return None
        _verdict = await asyncio.wait_for(
            _policy_eval("PHASE_TOOL_CALL", {"name": tool_name, "arguments": tool_input}),
            evaluator_deadline_s,
        )
        _action = getattr(_verdict, "action", None)
        if _action in ("POLICY_ACTION_ALLOW", "POLICY_ACTION_UNSPECIFIED"):
            # ALLOW / no-match — fall through (caller decides whether to also
            # run the human-consent elicitation gate).
            return None
        if _action == "POLICY_ACTION_ASK":
            from claude_agent_sdk import PermissionResultAllow, PermissionResultDeny

            reason = _verdict.reason or "Approval required by Coral TOOL_CALL policy"
            if self._elicitation_handler is None:
                logger.warning(
                    "TOOL_CALL policy ASK had no elicitation handler; denying tool=%s reason=%s",
                    tool_name,
                    reason,
                )
                return PermissionResultDeny(message=reason)
            logger.info("TOOL_CALL policy requested approval tool=%s reason=%s", tool_name, reason)
            if await self._elicitation_handler(tool_name, tool_input):
                return PermissionResultAllow()
            return PermissionResultDeny(message=reason)
        if _action == "POLICY_ACTION_DENY":
            from claude_agent_sdk import PermissionResultDeny

            reason = _verdict.reason or "Denied by Coral TOOL_CALL policy"
            logger.info("TOOL_CALL policy denied tool=%s reason=%s", tool_name, reason)
            return PermissionResultDeny(message=reason)
        from claude_agent_sdk import PermissionResultDeny

        reason = f"Unexpected Coral TOOL_CALL policy verdict: {_action!r}"
        logger.warning("TOOL_CALL policy failed closed tool=%s reason=%s", tool_name, reason)
        return PermissionResultDeny(message=reason)

    async def _can_use_tool_gate(
        self,
        tool_name: str,
        tool_input: ToolArgs,
        perm_ctx: object,
        *,
        policy_checked: bool = False,
    ) -> object:
        """
        Unified ``options.can_use_tool`` callback for the claude-sdk path.

        Composes two independent gates, in order:

        1. **TOOL_CALL policy** (when a ``_policy_evaluator`` is wired and
           *policy_checked* is false): a hard DENY short-circuits to
           :class:`~claude_agent_sdk.PermissionResultDeny`. ALLOW /
           no-match falls through with no human interaction. CORAL(S21):
           the CLI skips ``can_use_tool`` under ``bypassPermissions`` and for
           pre-approved tools, so Coral specs rely on the PreToolUse hook.
        2. **Human-consent elicitation** (only when the permission mode is
           NOT ``bypassPermissions`` and an elicitation handler is wired):
           the pre-existing per-tool approval prompt. Under
           ``bypassPermissions`` this step is skipped entirely, so the
           model still acts autonomously for anything policy allows.

        :param tool_name: Full SDK tool name, e.g. ``"Bash"`` or
            ``"mcp__github__issue_write"``.
        :param tool_input: Arguments dict for the tool call.
        :param perm_ctx: :class:`claude_agent_sdk.ToolPermissionContext`.
        :param policy_checked: The PreToolUse policy hook already evaluated this call.
        :returns: A :class:`~claude_agent_sdk.PermissionResult`.
        """
        from claude_agent_sdk import PermissionResultAllow

        policy_result = (
            None
            if policy_checked
            else await self._evaluate_tool_call_policy(tool_name, tool_input)
        )
        if policy_result is not None:
            # Hard DENY from policy — block before execution.
            return policy_result
        # Policy allowed (or no policy gate). Under bypassPermissions we
        # never prompt; otherwise defer to the elicitation gate.
        if self._permission_mode == "bypassPermissions" or self._elicitation_handler is None:
            return PermissionResultAllow()
        return await self._can_use_tool_for_permission(tool_name, tool_input, perm_ctx)

    def _coral_refusal(self, api_key_helper: str | None) -> ExecutorError | None:
        """CORAL(S13): why a Coral spec must not start, or ``None`` to proceed."""
        if not self._require_api_credential:
            return None
        if not (api_key_helper or self._gateway):
            return ExecutorError(
                message=CORAL_SUBSCRIPTION_AUTH_REFUSED_MESSAGE,
                code=CORAL_SUBSCRIPTION_AUTH_REFUSED_CODE,
                title="Anthropic API key needed",
                retryable=False,
            )
        if self._os_env_spec is None:
            return None
        sandbox = self._os_env_spec.sandbox
        sandbox_type = _resolve_sandbox_type(sandbox.type if sandbox is not None else None)
        binary = _CORAL_SANDBOX_BINARIES.get(sandbox_type)
        if binary is not None and shutil.which(binary) is not None:
            return None
        missing = f"install {binary}" if binary else f"{sandbox_type!r} does not isolate files"
        return ExecutorError(
            message=f"Steps that read or change files need an OS sandbox: {missing}.",
            code=CORAL_SANDBOX_UNAVAILABLE_CODE,
            retryable=False,
        )

    async def run_turn(
        self,
        messages: list[Message],
        tools: list[ToolSpec],
        system_prompt: str,
        config: ExecutorConfig | None = None,
    ) -> AsyncIterator[ExecutorEvent]:
        """Run one turn via the Claude Agent SDK.

        The SDK receives the latest user message as a prompt and runs its full
        agent loop (which may include multiple internal tool calls).  We
        observe the message stream and yield ExecutorEvents for the Session
        to record in History.
        """
        sdk = cast(_ClaudeSDK, _ensure_sdk())
        from claude_agent_sdk.types import StreamEvent as _StreamEvent

        cfg = config or ExecutorConfig()
        try:
            reasoning_effort = validate_effort(
                cfg.extra.get("reasoning_effort"), "Claude Agent SDK", CLAUDE_EFFORTS
            )
        except ValueError as exc:
            yield ExecutorError(message=describe_exception(exc), retryable=False)
            return

        session_key = self._session_key(messages)
        crashed_reason = self._crashed_sessions.get(session_key)
        if crashed_reason is not None:
            yield ExecutorError(
                message=(
                    "Claude SDK session crashed and cannot continue in this Session. "
                    f"Start a new Session. Cause: {crashed_reason}"
                )
            )
            return
        await self._evict_terminated_client(session_key)
        resume_session = session_key in self._clients
        prompt = self._build_prompt(
            messages,
            resume_session=resume_session,
        )
        if not prompt:
            # Resumed sessions can have nothing new to say; signal turn
            # completion with no assistant text instead of an empty string.
            yield TurnComplete(response=None)
            return

        state = self._clients.get(session_key)
        if state is not None and prompt != "/compact":
            # Effort is a launch option, and a CLI busy with a timed-out MCP reconnect
            # holds the prompt. Rebuild with history for conversational turns, but let
            # /compact operate on the existing client's context.
            rebuild = state.effort != reasoning_effort
            if not rebuild:
                try:
                    rebuild = not await self._reconnect_signed_in_mcp_servers(state)
                except asyncio.CancelledError:
                    self._evict_client_on_cancel(session_key)
                    raise
            if rebuild:
                await self._close_live_client(session_key)
                resume_session = False
                prompt = self._build_prompt(messages, resume_session=False)

        # Build MCP tools from Omnigent tool schemas
        mcp_tools = _build_mcp_tools(tools, self._tool_executor) if tools else []

        # Create MCP server config for Omnigent tools. The SDK's
        # ``McpServerConfig`` union is opaque to us — we pass through
        # whatever ``create_sdk_mcp_server`` returns.
        mcp_servers: dict[str, Any] = {}  # type: ignore[explicit-any]
        if mcp_tools:
            mcp_servers["omnigent"] = sdk.create_sdk_mcp_server(
                name="omnigent",
                version="1.0.0",
                tools=mcp_tools,
            )
            system_prompt = _augment_system_prompt_for_omnigent_mcp_tools(
                system_prompt,
                tools,
            )

        # Build allowed_tools list.  OS-environment operations route
        # through Omnigent ``sys_os_*`` MCP tools rather than the
        # SDK's native Bash/Read/Edit/Write — MCP tools flow through
        # the scaffold's ``dispatch_tool`` path, giving the runner
        # visibility, timeouts, and error recovery.
        #
        # In ``auto`` and ``bypassPermissions`` modes, pre-approve all
        # MCP tools so the agent can act autonomously without a per-call
        # human-consent gate.  ``auto`` still runs background safety
        # checks; ``bypassPermissions`` skips all gates entirely.
        # In any other mode (``default``, ``acceptEdits``, etc.), leave
        # ``allowed_tools`` empty so every tool call goes through the
        # SDK's ``can_use_tool`` callback — which routes to the AP
        # elicitation system when an elicitation handler is wired in.
        # When ``allowed_tools`` is empty the SDK omits ``--allowedTools``
        # entirely, letting Claude's normal permission flow apply.
        allowed_tools: list[str] = []
        if self._permission_mode in ("auto", "bypassPermissions"):
            # Allow all Omnigent MCP tools (no per-call human gate needed)
            for schema in tools:
                raw_tname = schema.get("name")
                # Claude SDK's ``allowed_tools`` requires concrete strings;
                # Omnigent tool schemas always carry a name (see
                # ``Tool.tool_schema``), but defend against malformed specs
                # by skipping unnamed entries rather than producing a
                # bogus ``mcp__omnigent__`` allow-entry.
                if not isinstance(raw_tname, str) or not raw_tname:
                    continue
                allowed_tools.append(f"mcp__omnigent__{raw_tname}")

        # cfg.model > spec model > Databricks default (only on the
        # Databricks-profile gateway path) > None (lets the SDK pick its own
        # default). The neutral generic-provider gateway path never falls back
        # to a ``databricks-*`` model: the Omnigent producer always resolves a
        # concrete model (spec > provider default > catalog default) before
        # spawning, so no ``databricks-*`` default is injected there.
        model = cfg.model or self._model_override
        if model is None and self._gateway_uses_databricks_profile:
            if self._resolved_default_model is None:
                self._resolved_default_model = await run_sync_on_thread(
                    _resolve_databricks_claude_model, self._databricks_profile
                )
            model = self._resolved_default_model

        # Build env: Databricks gateway settings derived from profile-backed
        # creds. CLAUDECODE removal happens around the subprocess spawn in
        # ``_get_or_create_client`` via ``_unset_env_var`` — setting it to
        # ``""`` here would still leave an empty key in the child env.
        env = dict(self._extra_env)
        env["CLAUDE_AGENT_SDK_CLIENT_APP"] = "omnigent"
        api_key_helper = env.pop(_CLAUDE_API_KEY_HELPER_ENV_KEY, None)
        # CORAL(S13): refuse a Coral spec before any CLI process starts
        refusal = self._coral_refusal(api_key_helper)
        if refusal is not None:
            yield refusal
            return
        # CORAL(S113): a CLI its configured sandbox could not wrap never starts unwrapped
        if self._claude_wrap_failure is not None:
            yield ExecutorError(
                message=f"This step's Claude CLI cannot run in its OS sandbox: "
                f"{self._claude_wrap_failure}.",
                code=CORAL_SANDBOX_UNAVAILABLE_CODE,
                retryable=False,
            )
            return
        # CORAL(S125): an isolated CLI behind the credential proxy gets only allow-listed names
        # from the user's settings env; read here, so the endpoint it names is checked below
        cli_settings_env: dict[str, str] | None = None
        # CORAL(S124): the credential leaves this machine over https only, to a URL the proxy
        # can forward to; refuse before the model listing below, the first request to carry it
        if self._upstream_credential is not None:
            try:
                if self._isolate_claude_config:
                    cli_settings_env = self._take_settings_env()
                self._check_proxy_upstream(env)
            except _CredentialProxyRefusedError as exc:
                yield self._proxy_refusal(exc)
                return
        # Teach Claude Code this gateway's spellings so no model surface routes
        # to an id the gateway rejects: pins for the family aliases, rewrites
        # for the canonical ids the CLI names itself (the refusal-fallback).
        # No-op off the gateway transport.
        model_overrides = await self._apply_gateway_model_vocabulary(
            env, api_key_helper, self._upstream_credential
        )
        # CORAL(S124): a proxied CLI's helper prints its session token; the real command, which
        # the proxy holds, is in none of its settings, environment or arguments
        cli_helper = api_key_helper if self._upstream_credential is None else _PROXY_TOKEN_HELPER
        settings_payload = _claude_settings_payload(cli_helper, model_overrides)

        # Capture stderr from the CLI subprocess for diagnostics
        stderr_lines: list[str] = []

        def _on_stderr(line: str) -> None:
            stderr_lines.append(line)
            logger.debug("Claude CLI stderr: %s", line)

        # Build options.
        #
        # ``skills="all"`` makes the Claude Agent SDK auto-configure
        # the ``Skill`` tool in ``allowed_tools`` and default
        # ``setting_sources`` to ``["user", "project"]`` so the CLI
        # discovers user-installed skills under ``~/.claude/skills/``
        # and project-local skills under ``<cwd>/.claude/skills/``.
        # See ``claude_agent_sdk._internal.transport.subprocess_cli.
        # _apply_skills_defaults`` for the auto-derivation.
        #
        # ``tools`` is the model's BASE tool set; ``allowed_tools``
        # is just a permission filter on it. ``skills="all"`` only
        # adds ``Skill`` to ``allowed_tools`` — to actually expose
        # the tool to the model we have to put it in ``tools`` too.
        # Without this, the SDK passes ``--tools ""`` to the CLI
        # which ZEROS the base set, and the agent never sees a
        # ``Skill`` tool even with ``--allowedTools=Skill`` set
        # (the live regression that makes the agent answer "I
        # don't have a Skill tool exposed in this session").
        #
        # ``--bare`` (formerly in ``extra_args``) is intentionally
        # NOT passed: bare mode skips CLAUDE.md auto-discovery,
        # plugin sync, and auto-memory — exactly the host config
        # users expect to leak through to a ``claude-sdk`` harness
        # they explicitly opted into. ``no-session-persistence``
        # stays because omnigent owns conversation persistence
        # via its own conversation store.
        # OS-environment tools are provided via Omnigent ``sys_os_*``
        # MCP tools (declared via ``os_env`` in the spec), not the
        # SDK's native Bash/Read/Edit/Write. Keep Skill and ToolSearch in
        # the base set so MCP definitions can be discovered on demand.
        base_tools: list[str] = self._base_tools(sdk)
        # Translate the spec's host-skill filter into the SDK
        # options. Falls back to ``"all"`` semantics when the
        # field is malformed (the parser already validates, so
        # this is belt-and-suspenders).
        resolved = _resolve_skills_option(self._skills_filter) or _ResolvedSkills(
            skills="all", setting_sources=None
        )
        # Bundle skills are exposed via the SDK's plugin mechanism.
        # The bundle's ``<bundle>/skills/<dir>/SKILL.md`` files are
        # discovered as plugin skills (no ``.claude/`` prefix needed
        # under the plugin convention — see plugin discovery test in
        # tests/inner/test_claude_sdk_executor.py). The plugin's
        # ``name`` (and thus the skill-listing prefix) comes from
        # the manifest written at construction time.
        bundle_plugins: list[Any] = []  # type: ignore[explicit-any]  # SdkPluginConfig is a TypedDict — typed Any here to keep the import lazy
        if self._bundle_dir is not None and (self._bundle_dir / "skills").is_dir():
            bundle_plugins.append({"type": "local", "path": str(self._bundle_dir)})
        if cli_settings_env is not None:  # CORAL(S125): never the whole block
            env = {**cli_settings_env, **env}
        elif resolved.setting_sources == [] and not self._gateway:
            # The CLI then skips the user settings env, which may hold the only provider endpoint.
            env = {**_claude_user_settings_env(self._cwd), **env}
        # CORAL(S13): user settings can carry a subscription token
        if self._require_api_credential:
            for name in _SUBSCRIPTION_TOKEN_ENV:
                env.pop(name, None)
        # CORAL(S113): the launcher or this executor names the config dir; user settings cannot
        if self._isolate_claude_config:
            for name in _CLAUDE_CONFIG_ENV:
                env.pop(name, None)
            if not self._claude_config_isolated:
                # Set, not only unset: a concurrent connect can restore the host's values.
                dir_path = str(self._claude_config_dir_for_unwrapped_cli())
                env.update(dict.fromkeys(_CLAUDE_CONFIG_ENV, dir_path))
        max_output_tokens = cfg.extra.get("max_tokens")
        if max_output_tokens is not None:
            max_output_tokens = int(max_output_tokens)
            env["CLAUDE_CODE_MAX_OUTPUT_TOKENS"] = str(max_output_tokens)
        options_kwargs: dict[str, Any] = {  # type: ignore[explicit-any]  # ClaudeAgentOptions accepts mixed-typed kwargs (str / list / dict / callable / etc.)
            "tools": base_tools,
            "system_prompt": system_prompt or None,
            "mcp_servers": mcp_servers if mcp_servers else {},
            "allowed_tools": allowed_tools,
            "permission_mode": self._permission_mode,
            "max_turns": cfg.extra.get("max_turns"),
            "env": env,
            "settings": settings_payload,
            "stderr": _on_stderr,
            "include_partial_messages": True,
            "include_hook_events": True,
            "skills": resolved.skills,
            "plugins": bundle_plugins,
            "extra_args": {"no-session-persistence": None},
            "max_buffer_size": 10 * 1024 * 1024,
        }
        if self._system_prompt_preset == "claude_code":
            options_kwargs["system_prompt"] = {
                "type": "preset",
                "preset": "claude_code",
                "append": system_prompt,
            }
        # Only forward ``setting_sources`` when explicitly set.
        # ``None`` lets the SDK apply its default
        # (``["user", "project"]`` when ``skills`` is non-None).
        # An empty list — produced by ``"none"`` — is forwarded
        # verbatim so the SDK doesn't auto-default it back to
        # ``["user", "project"]``, which would re-load host
        # skills into the model's system prompt despite
        # ``skills=[]`` (the live regression that prompted this
        # branch).
        if resolved.setting_sources is not None:
            options_kwargs["setting_sources"] = resolved.setting_sources
        if reasoning_effort is not None:
            options_kwargs["effort"] = reasoning_effort
        if (
            max_output_tokens is not None
            and max_output_tokens <= _CLAUDE_CODE_MIN_THINKING_BUDGET_TOKENS
        ):
            options_kwargs["thinking"] = {"type": "disabled"}
        # Databricks opus/fable endpoints reject thinking.type="enabled"
        # (HTTP 400); they require "adaptive" instead (those tiers are
        # adaptive-only). Sonnet is fine, so scope to those tiers only.
        # This is Databricks-specific: it is gated on the ``databricks-
        # claude-opus-`` / ``databricks-claude-fable-`` model prefixes (and
        # their ``system.ai.`` Unity Catalog spellings), so it never fires
        # for a generic gateway model.
        if (
            self._gateway
            and isinstance(model, str)
            and model.startswith(DATABRICKS_CLAUDE_ADAPTIVE_THINKING_PREFIXES)
            and "thinking" not in options_kwargs
        ):
            # display="summarized" so Opus 4.7+ / Fable streams thinking text
            # (their default is "omitted").
            options_kwargs["thinking"] = {"type": "adaptive", "display": "summarized"}
        options = sdk.ClaudeAgentOptions(**options_kwargs)
        if self._cli_path:
            options.cli_path = self._cli_path
        if model:
            options.model = model
        if self._cwd:
            options.cwd = self._cwd
        # Install the unified can_use_tool gate whenever a policy evaluator or
        # an elicitation handler is wired. CORAL(S21): Coral specs gate policy
        # in PreToolUse instead, and refuse the turn when that hook cannot run.
        policy_hooked = self._install_tool_call_policy_hook(sdk, options)
        if self._tool_call_policy_hook and not policy_hooked:
            yield ExecutorError(
                message="Coral steps need a TOOL_CALL policy check, which is unavailable.",
                code=CORAL_POLICY_HOOK_UNAVAILABLE_CODE,
                retryable=False,
            )
            return
        if (
            getattr(self, "_policy_evaluator", None) is not None
            or self._elicitation_handler is not None
        ):
            options.can_use_tool = (
                partial(self._can_use_tool_gate, policy_checked=True)
                if policy_hooked
                else self._can_use_tool_gate
            )

        self._install_subagent_router_hook(sdk, options, model)
        self._install_framework_context_hook(sdk, options, session_key)
        self._install_ask_user_question_hook(sdk, options)

        # Log the full configuration for debugging
        logger.info(
            "ClaudeSDKExecutor: model=%s, gateway=%s, base_url=%s, tools=%d, thinking=%r, "
            "system_prompt_preset=%s",
            model or "(default)",
            self._gateway,
            env.get("ANTHROPIC_BASE_URL", "(not set)"),
            len(tools),
            options_kwargs.get("thinking"),
            self._system_prompt_preset or "custom",
        )

        # Run the query, streaming events as they arrive.
        # The SDK manages its own tool-call loop internally (via MCP).
        # We observe the message stream and yield ExecutorEvents so the
        # CLI can render text chunks and tool-call progress in real time.
        response_text = ""
        turn_usage: dict[str, Any] | None = None  # type: ignore[explicit-any]
        # The concrete model the SDK reports on its assistant messages, e.g.
        # ``"claude-opus-4-8"``. Captured from the stream because the resolved
        # config ``model`` is ``None`` when the spec pins none and the gateway
        # picks a default internally — this is then forwarded in ``turn_usage``
        # so the server can price the turn. ``None`` until an assistant message
        # carrying a model arrives.
        observed_model: str | None = None
        system_diagnostics: list[str] = []
        terminal_error: str | None = None
        terminal_auth_failure = False
        terminal_usage_limited = False
        terminal_resets_at: float | None = None
        auth_remediation = _claude_auth_remediation(
            databricks_profile=self._gateway_uses_databricks_profile,
            gateway=bool(self._gateway),
            # CORAL(S115): a sandboxed CLI's own config holds no stored login
            private_config=self._claude_config_isolated and not api_key_helper,
            token_env=next(
                (
                    name
                    for name in _SUBSCRIPTION_TOKEN_ENV
                    if env.get(name) or os.environ.get(name)
                ),
                None,
            ),
        )
        compaction_occurred: bool = False
        claude_session_id: str | None = None
        compaction_transcript_path: pathlib.Path | None = None
        compaction_transcript_offset: int | None = None

        # Track in-flight tool calls so we can emit ToolCallComplete
        # with the tool name and duration when results arrive.
        pending_tools: dict[str, tuple[str, float]] = {}  # id → (name, start_mono)

        # Track whether we've received any StreamEvent messages.
        # When True, we skip text/tool events from AssistantMessage to
        # avoid double-emitting (the SDK sends both StreamEvents AND
        # the complete AssistantMessage for the same content).
        got_stream_events = False

        # Per-API-call prompt usage from the most recent ``message_start``
        # stream event. A single user turn can drive MANY internal API
        # calls (the SDK's tool loop), and ``ResultMessage.usage`` reports
        # the CUMULATIVE total across all of them — so summing its cache
        # buckets over-counts context, because each iteration re-sends the
        # whole (growing) conversation and those prompt tokens get tallied
        # once per call. For context-window fill we want only the LAST
        # call's prompt size: that single prompt already contains the full
        # conversation that carries into the next turn. We capture each
        # ``message_start``'s ``message.usage`` here and keep the latest,
        # mirroring how the openai-agents executor uses ``raw_responses[-1]``
        # for ``context_tokens``. ``None`` until the first call starts.
        last_call_usage: dict[str, Any] | None = None  # type: ignore[explicit-any]

        def _new_compact_summary_visible() -> bool:
            if compaction_transcript_path is None or compaction_transcript_offset is None:
                logger.warning(
                    "Skipping Claude compaction checkpoint after stream failure: "
                    "PreCompact did not provide a readable transcript boundary "
                    "(session=%s).",
                    claude_session_id,
                )
                return False

            try:
                with compaction_transcript_path.open("rb") as transcript:
                    transcript.seek(compaction_transcript_offset)
                    appended = transcript.read()
            except OSError:
                logger.warning(
                    "Skipping Claude compaction checkpoint after stream failure: "
                    "could not read appended transcript records (session=%s, path=%s).",
                    claude_session_id,
                    compaction_transcript_path,
                    exc_info=True,
                )
                return False

            for raw_line in appended.splitlines():
                try:
                    entry = json.loads(raw_line)
                except (json.JSONDecodeError, UnicodeDecodeError):
                    continue
                if isinstance(entry, dict) and entry.get("isCompactSummary") is True:
                    return True

            logger.warning(
                "Skipping Claude compaction checkpoint after stream failure: "
                "no post-PreCompact summary record is visible yet (session=%s, path=%s).",
                claude_session_id,
                compaction_transcript_path,
            )
            return False

        def _build_compaction_complete_event(
            *, require_new_compact_summary: bool = False
        ) -> ExecutorEvent | None:
            from omnigent.inner.executor import CompactionComplete

            assert claude_session_id is not None
            if require_new_compact_summary and not _new_compact_summary_visible():
                return None

            compaction_tokens = 0
            if turn_usage is not None:
                compaction_tokens = turn_usage.get("context_tokens", 0) or 0

            try:
                from claude_agent_sdk import get_session_messages

                messages = get_session_messages(claude_session_id, directory=self._cwd)
                compacted_messages = [
                    {
                        "type": "message",
                        "role": message.type,
                        "content": message.message.get("content", []),
                    }
                    for message in messages
                    if isinstance(message.message, dict)
                ]
            except Exception:
                logger.warning(
                    "Failed to read Claude post-compaction session messages "
                    "(session=%s); preserving full server history instead of "
                    "persisting an empty checkpoint.",
                    claude_session_id,
                    exc_info=True,
                )
                return None

            if not compacted_messages:
                logger.warning(
                    "Claude post-compaction read returned no messages "
                    "(session=%s); preserving full server history instead of "
                    "persisting an empty checkpoint.",
                    claude_session_id,
                )
                return None

            return CompactionComplete(
                summary="[Claude Code compaction — context was automatically compacted]",
                token_count=compaction_tokens,
                model=observed_model or model,
                compacted_messages=compacted_messages,
            )

        try:
            client = await self._get_or_create_client(
                sdk,
                session_key=session_key,
                options=options,
                model=model,
            )
        except _CredentialExposedError as exc:  # CORAL(S124): refused before any CLI process
            yield ExecutorError(
                message=str(exc), code=CORAL_CREDENTIAL_EXPOSED_CODE, retryable=False
            )
            return
        except _CredentialProxyRefusedError as exc:  # CORAL(S125): its proxy did not start
            yield self._proxy_refusal(exc)
            return

        # ── LLM_REQUEST policy evaluation ────────────────────────
        # If the executor adapter installed a ``_policy_evaluator``
        # callback, call it with the request data so the Omnigent server
        # can evaluate LLM_REQUEST policies before the LLM call.
        _policy_eval = getattr(self, "_policy_evaluator", None)
        if _policy_eval is not None:
            # Extract the user prompt text for PII scanning.
            _last_user_msg = ""
            if isinstance(prompt, str):
                _last_user_msg = prompt[:500]
            elif isinstance(prompt, list):
                _parts: list[str] = []
                for block in prompt:
                    text = block.get("text")
                    if block.get("type") in ("text", "input_text") and isinstance(text, str):
                        _parts.append(text)
                _last_user_msg = " ".join(_parts)[:500]
            _req_data: _JsonObject = {
                "model": model,
                "messages_count": len(prompt) if isinstance(prompt, list) else 1,
                "tools_count": len(tools),
                "system_prompt_preview": (system_prompt[:200] if system_prompt else ""),
                "last_user_message": _last_user_msg,
            }
            _req_verdict = await _policy_eval("PHASE_LLM_REQUEST", _req_data)
            if _req_verdict.action == "POLICY_ACTION_DENY":
                _deny_reason = _req_verdict.reason or "no reason given"
                yield ExecutorError(message=f"LLM call denied by policy: {_deny_reason}")
                return

        notice_messages = messages
        if resume_session:
            notice_messages = []
            for message in reversed(without_tool_history(messages)):
                if message.get("role") != "user":
                    break
                notice_messages.insert(0, message)
        self._pending_framework_context[session_key] = "\n\n".join(
            notice
            for message in notice_messages
            if message.get("role") == "user"
            for notice in framework_notices(message.get("content"))
        )
        try:
            try:
                sdk_prompt: str | AsyncIterator[_JsonObject]
                if isinstance(prompt, list):
                    # Multimodal content blocks — send as a
                    # structured message via the SDK's dict path.
                    sdk_prompt = _multimodal_message_iter(prompt, session_id=session_key)
                else:
                    sdk_prompt = prompt
                await asyncio.wait_for(
                    client.query(sdk_prompt, session_id=session_key),
                    timeout=_QUERY_START_TIMEOUT_SECONDS,
                )
            except TimeoutError as exc:
                raise TimeoutError(
                    f"Claude SDK query start timed out after {int(_QUERY_START_TIMEOUT_SECONDS)}s"
                ) from exc
            message_stream = client.receive_response()
            try:
                while True:
                    next_task = asyncio.ensure_future(anext(message_stream))
                    idle_seconds = 0.0
                    try:
                        while True:
                            done, _ = await asyncio.wait(
                                {next_task}, timeout=_STREAM_IDLE_WARN_SECONDS
                            )
                            if next_task in done:
                                break
                            idle_seconds += _STREAM_IDLE_WARN_SECONDS
                            logger.warning(
                                "Claude SDK response stream has been idle for "
                                "%ds (session %s); still waiting.",
                                int(idle_seconds),
                                session_key,
                            )
                    except BaseException:
                        next_task.cancel()
                        with suppress(BaseException):
                            await next_task
                        raise
                    try:
                        message = next_task.result()
                    except StopAsyncIteration:
                        break
                    if isinstance(message, _StreamEvent):
                        got_stream_events = True
                        stream_evt = cast(_StreamEventObj, message)
                        evt = stream_evt.event
                        evt_type = evt.get("type")

                        if evt_type == "message_start":
                            # Each ``message_start`` opens one API call and
                            # carries that call's prompt-side usage
                            # (input + cache buckets). Keep the latest so
                            # ``context_tokens`` reflects the final call's
                            # prompt — the true context size — instead of
                            # ``ResultMessage.usage``'s cumulative sum across
                            # every tool-loop iteration.
                            msg_obj = evt.get("message")
                            if isinstance(msg_obj, dict):
                                call_usage = msg_obj.get("usage")
                                if isinstance(call_usage, dict) and call_usage:
                                    last_call_usage = call_usage
                            continue

                        if evt_type == "content_block_start":
                            block_evt = evt.get("content_block", {})
                            block_type = block_evt.get("type")
                            if block_type == "thinking":
                                # Anchor the ``thinking…`` indicator at the
                                # start of an extended-thinking block.
                                yield ReasoningChunk(
                                    delta="",
                                    event_type="reasoning_started",
                                )
                                continue
                            if block_type == "tool_use":
                                raw_tool_id = block_evt.get("id")
                                # SSE stream events from the SDK should
                                # always carry an ``id`` on tool_use
                                # blocks; skip malformed events rather
                                # than bucketing them under ``""``.
                                if not isinstance(raw_tool_id, str):
                                    continue
                                tool_name = block_evt.get("name", "unknown")
                                # Track the tool for duration / pairing.
                                # The ToolCallRequest itself is emitted
                                # later, when the ``AssistantMessage``
                                # arrives with ``tool_block.input``
                                # populated — at ``content_block_start``
                                # the args have not yet been streamed via
                                # ``input_json_delta`` and the request
                                # would carry ``args={}``, rendering
                                # downstream as ``⏵ Bash()`` with no
                                # visible command. Waiting one event
                                # loses a few ms of "tool call started"
                                # feedback in exchange for correct args.
                                pending_tools[raw_tool_id] = (tool_name, time.monotonic())

                        elif evt_type == "content_block_delta":
                            delta = evt.get("delta", {})
                            delta_type = delta.get("type")
                            if delta_type == "text_delta":
                                text = delta.get("text")
                                if isinstance(text, str) and text:
                                    response_text += text
                                    yield TextChunk(text=text)
                            elif delta_type == "thinking_delta":
                                # Mirror the OpenAI reasoning path so the
                                # ``thinking…`` panel populates live.
                                thinking_text = delta.get("thinking")
                                if isinstance(thinking_text, str) and thinking_text:
                                    yield ReasoningChunk(
                                        delta=thinking_text,
                                        event_type="reasoning_text",
                                    )

                    elif isinstance(message, sdk.AssistantMessage):
                        assistant_msg = cast(_AssistantMessageObj, message)
                        # Capture the concrete model the SDK used (the resolved
                        # config ``model`` is None when the spec pins none).
                        _am_model = concrete_reported_model(getattr(assistant_msg, "model", None))
                        if _am_model is not None:
                            observed_model = _am_model
                        if got_stream_events:
                            # StreamEvents already emitted text. Emit the
                            # ToolCallRequest here, once the full
                            # ``tool_block.input`` has assembled — see the
                            # note in the ``content_block_start`` branch
                            # above for why this is deferred.
                            for block in assistant_msg.content:
                                if isinstance(block, sdk.ToolUseBlock):
                                    tool_block = cast(_ToolUseBlockObj, block)
                                    if tool_block.id not in pending_tools:
                                        pending_tools[tool_block.id] = (
                                            tool_block.name,
                                            time.monotonic(),
                                        )
                                    yield ToolCallRequest(
                                        name=tool_block.name,
                                        args=tool_block.input,
                                        # Thread the SDK's
                                        # ``tool_use_id`` through
                                        # so downstream consumers
                                        # (notably the new harness
                                        # contract's
                                        # :class:`ExecutorAdapter`)
                                        # can pair this request
                                        # with the matching
                                        # :class:`ToolCallComplete`
                                        # by call_id.
                                        metadata=_tool_call_metadata(tool_block),
                                    )
                        else:
                            # No streaming — emit events from the full message.
                            for block in assistant_msg.content:
                                if isinstance(block, sdk.TextBlock):
                                    text_block = cast(_TextBlockObj, block)
                                    response_text += text_block.text
                                    yield TextChunk(text=text_block.text)
                                elif isinstance(block, sdk.ThinkingBlock):
                                    thinking_block = cast(_ThinkingBlockObj, block)
                                    # Non-streaming counterpart of the
                                    # ``thinking_delta`` path above.
                                    if thinking_block.thinking:
                                        yield ReasoningChunk(
                                            delta="",
                                            event_type="reasoning_started",
                                        )
                                        yield ReasoningChunk(
                                            delta=thinking_block.thinking,
                                            event_type="reasoning_text",
                                        )
                                elif isinstance(block, sdk.ToolUseBlock):
                                    tool_block = cast(_ToolUseBlockObj, block)
                                    pending_tools[tool_block.id] = (
                                        tool_block.name,
                                        time.monotonic(),
                                    )
                                    yield ToolCallRequest(
                                        name=tool_block.name,
                                        args=tool_block.input,
                                        metadata=_tool_call_metadata(tool_block),
                                    )

                    elif isinstance(message, sdk.UserMessage):
                        # Tool results come back as UserMessages containing
                        # ToolResultBlocks.  Match each back to its request.
                        user_msg = cast(_UserMessageObj, message)
                        content = user_msg.content
                        if isinstance(content, list):
                            for block in content:
                                if isinstance(block, sdk.ToolResultBlock):
                                    result_block = cast(_ToolResultBlockObj, block)
                                    tool_name, start = pending_tools.pop(
                                        result_block.tool_use_id,
                                        ("unknown", time.monotonic()),
                                    )
                                    duration_ms = (time.monotonic() - start) * 1000
                                    classification = classify_tool_result(
                                        result_block.content,
                                        fallback_to_string=bool(result_block.is_error),
                                    )
                                    status = classification.status
                                    error = classification.error
                                    if result_block.is_error and not error:
                                        status = ToolCallStatus.ERROR
                                        error = "tool error"
                                    yield ToolCallComplete(
                                        name=tool_name,
                                        status=status,
                                        result=result_block.content,
                                        error=error,
                                        duration_ms=duration_ms,
                                        # Same rationale as the
                                        # ToolCallRequest above —
                                        # the call_id is the only
                                        # thing the adapter can
                                        # use to pair this output
                                        # back to its function_call.
                                        metadata={"call_id": result_block.tool_use_id},
                                    )

                    elif isinstance(message, sdk.ResultMessage):
                        result_msg = cast(_ResultMessageObj, message)
                        claude_session_id = getattr(result_msg, "session_id", None)
                        logger.info(
                            "Claude CLI result received (is_error=%s)",
                            getattr(result_msg, "is_error", None),
                        )
                        if getattr(result_msg, "is_error", None):
                            # Harness-level failure (e.g. expired login). Surface
                            # as an executor error rather than assistant content.
                            failure_text = result_msg.result or "claude-sdk harness error"
                            logger.error(
                                "claude-sdk ResultMessage is_error=True for agent %r: %s",
                                self._agent_name,
                                failure_text,
                            )
                            terminal_auth_failure = is_claude_auth_failure_text(failure_text)
                            # Keep the next step in the message too: the REPL and
                            # SDK stream render only code/message.
                            terminal_error = (
                                f"{failure_text.rstrip(_TRAILING_PUNCTUATION)}. {auth_remediation}"
                                if terminal_auth_failure
                                else failure_text
                            )
                        elif not response_text and result_msg.result:
                            response_text = result_msg.result
                        raw_usage = getattr(result_msg, "usage", None)
                        if isinstance(raw_usage, dict) and raw_usage:
                            # ``ResultMessage.usage`` is CUMULATIVE across every
                            # API call in the turn. Keep it for billing
                            # (``input``/``output``/``total`` and the cache
                            # buckets) — that's the correct sum to price.
                            in_tok = raw_usage.get("input_tokens") or 0
                            out_tok = raw_usage.get("output_tokens") or 0
                            # ``context_tokens`` is window FILL, not a billing
                            # sum: it must be a single prompt's size, not the
                            # cumulative input across iterations (which re-sends
                            # the conversation each tool-loop step and would
                            # over-count K-fold on a K-call turn). Use the LAST
                            # ``message_start`` call's prompt — input +
                            # cache_creation + cache_read — which already holds
                            # the full conversation carried into the next turn.
                            # Mirrors openai-agents' ``raw_responses[-1]`` choice.
                            # Fall back to the cumulative sum only when no
                            # ``message_start`` was observed (e.g. non-streaming
                            # paths), preserving a non-null value over None.
                            ctx_src = last_call_usage if last_call_usage is not None else raw_usage
                            ctx_in = ctx_src.get("input_tokens") or 0
                            ctx_cc = ctx_src.get("cache_creation_input_tokens") or 0
                            ctx_cr = ctx_src.get("cache_read_input_tokens") or 0
                            turn_usage = {
                                "input_tokens": in_tok,
                                "output_tokens": out_tok,
                                "total_tokens": in_tok + out_tok,
                                "context_tokens": ctx_in + ctx_cc + ctx_cr,
                                **{
                                    k: v
                                    for k, v in raw_usage.items()
                                    if k
                                    not in (
                                        "input_tokens",
                                        "output_tokens",
                                        "context_tokens",
                                    )
                                },
                                # Harness-reported model for cost pricing: prefer the SDK's
                                # observed_model (config model is None when no model is pinned).
                                "model": observed_model or model,
                            }

                    elif isinstance(message, sdk.SystemMessage):
                        system_msg = cast(_SystemMessageObj, message)
                        subtype = system_msg.subtype
                        data = system_msg.data

                        if subtype == "api_retry":
                            error_status = data.get("error_status")
                            retry_error = data.get("error", "unknown_error")
                            attempt = data.get("attempt")
                            max_retries = data.get("max_retries")
                            retry_delay_ms = data.get("retry_delay_ms")
                            diagnostic = (
                                "Claude CLI API retry"
                                f" {attempt}/{max_retries}: {retry_error}"
                                f" (status={error_status}, retry_delay_ms={retry_delay_ms})"
                            )
                            system_diagnostics.append(diagnostic)
                            logger.warning(diagnostic)

                            if (
                                error_status in {401, 403}
                                or retry_error == "authentication_failed"
                            ):
                                terminal_error = (
                                    "Claude SDK provider authentication failed"
                                    f" ({retry_error}, status={error_status}). "
                                    f"{auth_remediation}"
                                )
                                terminal_auth_failure = True
                                break

                            if error_status == 429 or retry_error in {
                                "rate_limit_error",
                                "rate_limit_exceeded",
                            }:
                                terminal_usage_limited = True
                                raw_resets = data.get("resets_at")
                                if isinstance(raw_resets, (int, float)) and not isinstance(
                                    raw_resets, bool
                                ):
                                    terminal_resets_at = float(raw_resets)

                            if error_status == 404:
                                if self._gateway:
                                    endpoint_hint = (
                                        "Check ANTHROPIC_BASE_URL / gateway endpoint "
                                        "configuration."
                                    )
                                else:
                                    endpoint_hint = "Check ANTHROPIC_BASE_URL configuration."
                                terminal_error = (
                                    "Claude SDK provider endpoint was not found "
                                    f"({retry_error}, status={error_status}). "
                                    f"{endpoint_hint}"
                                )
                                terminal_auth_failure = False
                                break
                        elif getattr(system_msg, "hook_event_name", None) == "PreCompact":
                            compaction_occurred = True
                            hook_session_id = getattr(system_msg, "session_id", None)
                            if hook_session_id is None and isinstance(data, dict):
                                hook_session_id = data.get("session_id")
                            if hook_session_id:
                                claude_session_id = str(hook_session_id)
                            hook_transcript_path = getattr(system_msg, "transcript_path", None)
                            if hook_transcript_path is None and isinstance(data, dict):
                                hook_transcript_path = data.get("transcript_path")
                            if isinstance(hook_transcript_path, str) and hook_transcript_path:
                                compaction_transcript_path = pathlib.Path(hook_transcript_path)
                                try:
                                    compaction_transcript_offset = (
                                        compaction_transcript_path.stat().st_size
                                    )
                                except OSError:
                                    compaction_transcript_offset = None
                            logger.info("Claude SDK compaction detected (PreCompact hook)")
                            from omnigent.inner.executor import CompactionStarted

                            yield CompactionStarted()
                        else:
                            logger.info("Claude CLI system message: %s", data)
            finally:
                # ``receive_response`` returns an async generator, which
                # always has ``aclose``; guard anyway for duck-typed test
                # doubles that implement the iterator protocol without it.
                aclose = getattr(message_stream, _ACLOSE_ATTR, None)
                if aclose is not None:
                    await aclose()

        except asyncio.CancelledError:
            # CancelledError is a BaseException, so a watchdog-cancelled turn
            # skips the boundary below. Evict the wedged client (no crash
            # mark) so the next turn rebuilds a fresh one and replays history
            # instead of reusing it and re-tripping the watchdog (#2109).
            self._evict_client_on_cancel(session_key)
            raise
        except Exception as exc:  # noqa: BLE001 — top-level executor error boundary; records crash and surfaces to caller
            self._pending_framework_context.pop(session_key, None)
            self._crashed_sessions[session_key] = str(exc)
            await self._close_live_client(session_key)
            stderr_text = "\n".join(stderr_lines) if stderr_lines else "(no stderr captured)"
            diagnostics_text = (
                "\n".join(system_diagnostics)
                if system_diagnostics
                else "(no system diagnostics captured)"
            )
            logger.error(
                "ClaudeSDKExecutor error: %s\nCLI stderr:\n%s\nCLI system diagnostics:\n%s",
                exc,
                stderr_text,
                diagnostics_text,
            )
            if compaction_occurred and claude_session_id:
                compaction_event = _build_compaction_complete_event(
                    require_new_compact_summary=True
                )
                if compaction_event is not None:
                    yield compaction_event
            yield ExecutorError(
                message=(
                    f"Claude SDK error: {exc}\n"
                    f"CLI stderr:\n{stderr_text}\n"
                    f"CLI system diagnostics:\n{diagnostics_text}"
                ),
                usage=turn_usage
                if turn_usage is not None
                else _usage_from_observed_call(last_call_usage, observed_model or model),
            )
            return
        finally:
            self._pending_framework_context.pop(session_key, None)
        # A turn can end without ``ResultMessage`` usage — the CLI can close
        # the stream early, fail terminally (auth failure, rejected retries),
        # or be cut short before its final usage is reported. In all of those
        # cases ``turn_usage`` is None and the context-occupancy meter would
        # freeze at the previous successful turn's value, hiding real window
        # fill exactly when a session is in trouble. The latest prompt size
        # was already observed from ``message_start`` (``last_call_usage``),
        # so synthesize a usage dict from it — for the failure return below
        # AND the completion path — and let the terminal event carry it.
        # ``output_tokens`` is unknown on an incomplete turn, so it reports 0
        # rather than guess. The full ``ResultMessage`` path above still wins
        # whenever it runs.
        if turn_usage is None:
            turn_usage = _usage_from_observed_call(last_call_usage, observed_model or model)

        if terminal_error:
            if compaction_occurred and claude_session_id:
                compaction_event = _build_compaction_complete_event()
                if compaction_event is not None:
                    yield compaction_event
            if terminal_auth_failure:
                yield ExecutorError(
                    message=terminal_error,
                    usage=turn_usage,
                    code=CLAUDE_AUTH_FAILED_CODE,
                    title=CLAUDE_AUTH_FAILED_TITLE,
                    remediation=auth_remediation,
                )
            elif terminal_usage_limited:
                yield ExecutorError(
                    message=terminal_error,
                    usage=turn_usage,
                    code=ExecutorError.USAGE_LIMITED_CODE,
                    resets_at=terminal_resets_at,
                )
            else:
                yield ExecutorError(message=terminal_error, usage=turn_usage)
            return

        # ── LLM_RESPONSE policy evaluation ───────────────────────
        # Evaluate after the stream completes but before TurnComplete
        # so a DENY prevents the response from being persisted.
        if _policy_eval is not None:
            _resp_data: _JsonObject = {
                "model": model,
                "text_preview": (response_text[:500] if response_text else ""),
                "tool_calls_count": len(pending_tools),
            }
            if turn_usage is not None:
                _resp_data["usage"] = turn_usage
            _resp_verdict = await _policy_eval("PHASE_LLM_RESPONSE", _resp_data)
            if _resp_verdict.action == "POLICY_ACTION_DENY":
                _deny_reason = _resp_verdict.reason or "no reason given"
                if compaction_occurred and claude_session_id:
                    compaction_event = _build_compaction_complete_event()
                    if compaction_event is not None:
                        yield compaction_event
                yield ExecutorError(message=(f"LLM response denied by policy: {_deny_reason}"))
                return

        _notify_usage_from_dict(model=model, usage=turn_usage)

        if compaction_occurred and claude_session_id:
            compaction_event = _build_compaction_complete_event()
            if compaction_event is not None:
                yield compaction_event

        logger.info("ClaudeSDKExecutor: turn complete")
        yield TurnComplete(response=response_text, usage=turn_usage)

    @staticmethod
    def _build_prompt(
        messages: list[Message],
        *,
        resume_session: bool,
    ) -> str | list[_JsonObject]:
        """
        Build the prompt for the SDK.

        For continued Claude SDK sessions, send only the latest user
        message. For a fresh session that already has replayable
        history (for example a sub-agent with
        ``pass_history=True``), serialize that history into the
        first prompt so Claude sees the prior conversation context.

        When the latest user message contains multimodal content
        (images, files), returns a list of Anthropic API content
        blocks instead of a plain string so the caller can send
        them through the SDK's structured message path.

        :param messages: Conversation history as inner
            :class:`Message` dicts.
        :param resume_session: ``True`` when the SDK session
            already has prior turns cached (no need to replay
            history).
        :returns: A plain string prompt, or a list of Anthropic
            API content block dicts when multimodal blocks are
            present in the latest user message.
        """
        if resume_session:
            # The live session already holds its tool items; only a fresh one replays them.
            return ClaudeSDKExecutor._extract_trailing_user_content(without_tool_history(messages))

        user_messages = [msg for msg in messages if msg.get("role") == "user"]
        if len(messages) <= 1 or len(user_messages) <= 1:
            return ClaudeSDKExecutor._extract_latest_user_content(messages)

        # Check if the latest user message is multimodal — if so,
        # serialize prior history as a text prefix but preserve the
        # latest message's content blocks for native multimodal
        # delivery to the Anthropic API.
        latest_content = ClaudeSDKExecutor._extract_latest_user_content(messages)
        latest_index = max(i for i, msg in enumerate(messages) if msg.get("role") == "user")
        prior = messages[:latest_index] + messages[latest_index + 1 :]

        prior_blocks: list[_JsonObject] = [_text_block("Conversation so far:")]
        for msg in prior:
            role = str(msg.get("role", "user")).replace("_", " ")
            raw_content = msg.get("content")
            rendered = [] if raw_content is None else _render_prior_content_blocks(raw_content)
            if not rendered:
                rendered = [_text_block("")]
            # Label the message inline when it opens with text; an attachment
            # that leads the message gets the label on its own line instead.
            if rendered[0].get("type") == "text":
                rendered[0] = _text_block(f"{role}: {rendered[0]['text']}")
            else:
                rendered.insert(0, _text_block(f"{role}:"))
            prior_blocks.extend(rendered)
        prior_blocks.append(_text_block(""))
        prior_blocks.append(
            _text_block(
                "Respond to the latest user message, using the conversation above as context."
            )
        )
        prior_blocks = _coalesce_text_blocks(prior_blocks)

        if isinstance(latest_content, list):
            return [*prior_blocks, *latest_content]
        # Coalescing leaves an all-text history as the single opening block, so
        # more than one block means an attachment survived and the prompt has
        # to stay structured for its bytes to reach the model.
        if len(prior_blocks) > 1:
            return [*prior_blocks, _text_block(f"\nuser: {latest_content}")]
        return f"{prior_blocks[0]['text']}\n\nuser: {latest_content}"

    @staticmethod
    def _extract_latest_user_content(
        messages: list[Message],
    ) -> str | list[_JsonObject]:
        """
        Extract the latest user message content for the SDK.

        Returns a plain string for text-only messages. When the
        message carries multimodal content blocks (``input_image``,
        ``input_file``), converts them to Anthropic API content
        block format and returns the list so the caller can send
        a structured message through the SDK transport.

        :param messages: Conversation history.
        :returns: A string prompt, or a list of Anthropic content
            block dicts.
        """
        for msg in reversed(messages):
            if msg.get("role") == "user":
                content = msg.get("content")
                if content is None:
                    return ""
                if isinstance(content, str):
                    return content
                if isinstance(content, list):
                    return _to_anthropic_content_blocks(content)
                return str(content)
        return ""

    @staticmethod
    def _extract_trailing_user_content(
        messages: list[Message],
    ) -> str | list[_JsonObject]:
        """
        Extract the trailing run of consecutive user messages for the SDK.

        On a resumed SDK session the client already has all prior turns
        cached, so only the *new* user input is sent. Normally that is a
        single user message, but when the runner batches several buffered
        steered messages into one continuation turn (see
        ``_check_and_start_next_turn``), the tail of history holds more than
        one brand-new user message the SDK has never seen. Sending only the
        last (as :meth:`_extract_latest_user_content` does) silently drops
        the earlier ones. This collects every user message after the last
        non-user (assistant / tool) message and concatenates them so all
        newly-buffered input reaches the model.

        Text messages are joined with blank lines. If any message in the
        trailing run carries multimodal content blocks, the whole run is
        returned as a single list of Anthropic content blocks so the bytes
        survive.

        :param messages: Conversation history.
        :returns: A string prompt, or a list of Anthropic content
            block dicts when the trailing run is multimodal.
        """
        trailing: list[Message] = []
        for msg in reversed(messages):
            if msg.get("role") == "user":
                content = msg.get("content")
                if content == "/compact" or (
                    isinstance(content, list)
                    and len(content) == 1
                    and isinstance(content[0], dict)
                    and content[0].get("type") in {"text", "input_text"}
                    and content[0].get("text") == "/compact"
                ):
                    # The runner dispatches earlier input before a compact control.
                    # Compaction may emit no assistant text; keep it out of later prompts.
                    if not trailing:
                        return "/compact"
                    break
                trailing.append(msg)
            else:
                break
        trailing.reverse()
        if not trailing:
            return ""
        if len(trailing) == 1:
            return ClaudeSDKExecutor._extract_latest_user_content(trailing)

        # Convert each trailing user message to Anthropic content blocks.
        # If any block is non-text (image/document), keep the structured
        # list so the bytes reach the model; otherwise join the text.
        block_runs: list[list[_JsonObject]] = []
        has_non_text = False
        for msg in trailing:
            content = msg.get("content")
            if content is None:
                block_runs.append([])
            elif isinstance(content, str):
                block_runs.append([_text_block(content)])
            elif isinstance(content, list):
                converted = _to_anthropic_content_blocks(content)
                block_runs.append(converted)
                if any(b.get("type") != "text" for b in converted):
                    has_non_text = True
            else:
                block_runs.append([_text_block(str(content))])

        if has_non_text:
            merged: list[_JsonObject] = []
            for run in block_runs:
                merged.extend(run)
            return merged

        texts: list[str] = []
        for run in block_runs:
            for block in run:
                text = block.get("text")
                if block.get("type") == "text" and isinstance(text, str) and text:
                    texts.append(text)
        return "\n\n".join(texts)
