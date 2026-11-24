"""Tests for the Claude gateway shim (thinking.display restoration).

The shim exists because Claude CLIs ≥ 2.1.168 strip ``thinking.display``
from ``/v1/messages`` bodies when experimental betas are disabled — the
required configuration on the Databricks gateway — which silences all
Opus thinking output (Opus 4.7+ defaults ``display`` to ``"omitted"``).
"""

from __future__ import annotations

import asyncio
import base64  # CORAL(S124)
import contextlib  # CORAL(S124)
import json
import logging  # CORAL(S124)
import re  # CORAL(S124)
import secrets  # CORAL(S124)
import shlex  # CORAL(S124)
import threading  # CORAL(S124)
from collections.abc import AsyncIterator, Awaitable, Callable, Iterator  # CORAL(S124)
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer  # CORAL(S124)
from pathlib import Path  # CORAL(S124)
from types import SimpleNamespace  # CORAL(S124)
from typing import Any

import httpx
import psutil  # type: ignore[import-untyped]  # CORAL(S124)
import pytest
import uvicorn

from omnigent.inner import claude_gateway_shim as shim_module  # CORAL(S124)
from omnigent.inner.claude_gateway_shim import (
    ClaudeGatewayShim,
    UpstreamCredential,  # CORAL(S124)
    UpstreamCredentialError,  # CORAL(S124)
    restore_thinking_display,
    static_printf_value,  # CORAL(S124)
)
from tests._helpers.https_server import enable_https  # CORAL(S124)
from tests._helpers.polling import poll_until_async  # CORAL(S124)

# CORAL(S124): every upstream a shim test reaches must be a loopback server.
_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})


@pytest.fixture(autouse=True)
def _loopback_upstreams_only(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """CORAL(S124): refuse, and fail the test on, any non-loopback upstream or proxy."""
    reached: list[str] = []
    original = httpx.AsyncHTTPTransport.handle_async_request

    async def guarded(self: httpx.AsyncHTTPTransport, request: httpx.Request) -> httpx.Response:
        proxy_url = getattr(self._pool, "_proxy_url", None)
        hosts = [request.url.host]
        if proxy_url is not None:
            hosts.append(proxy_url.host.decode("ascii"))
        outside = [host for host in hosts if host not in _LOOPBACK_HOSTS]
        if outside:
            reached.extend(outside)
            raise httpx.ConnectError("the shim tests reach loopback servers only")
        return await original(self, request)

    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", guarded)
    yield
    assert not reached, f"a shim test tried to reach non-loopback hosts: {sorted(set(reached))}"


# ── restore_thinking_display unit tests ───────────────────


def _body(model: str, thinking: dict[str, Any] | None) -> bytes:  # type: ignore[explicit-any]  # thinking mirrors the API's open dict
    """
    Build a minimal Messages API request body.

    :param model: Model id, e.g. ``"databricks-claude-opus-4-8"``.
    :param thinking: Thinking config dict, e.g. ``{"type": "adaptive"}``,
        or ``None`` to omit the key entirely.
    :returns: Encoded JSON body.
    """
    payload: dict[str, Any] = {  # type: ignore[explicit-any]  # request body is a heterogeneous JSON object
        "model": model,
        "max_tokens": 100,
        "messages": [{"role": "user", "content": "hi"}],
    }
    if thinking is not None:
        payload["thinking"] = thinking
    return json.dumps(payload).encode()


@pytest.mark.parametrize(
    "model,thinking",
    [
        # Opus + adaptive missing display — the live bug shape.
        ("databricks-claude-opus-4-8", {"type": "adaptive"}),
        # Opus + enabled missing display — any non-disabled type qualifies.
        ("databricks-claude-opus-4-7", {"type": "enabled", "budget_tokens": 1024}),
        # Fable shares Opus 4.7+'s display="omitted" default.
        ("databricks-claude-fable-5", {"type": "adaptive"}),
        # Unity Catalog spellings of the same Databricks-hosted tiers.
        ("system.ai.claude-opus-4-8", {"type": "adaptive"}),
        ("system.ai.claude-fable-5", {"type": "adaptive"}),
    ],
)
def test_restore_injects_display_for_adaptive_tiers(model: str, thinking: dict[str, Any]) -> None:  # type: ignore[explicit-any]  # parametrized API dict
    """Qualifying opus/fable bodies gain ``display="summarized"``; the rest
    of the payload is preserved byte-for-byte after re-encoding."""
    result = json.loads(restore_thinking_display(_body(model, thinking)))
    # display injected — without it the model defaults to "omitted" and
    # streams no thinking text (the user-visible bug).
    assert result["thinking"]["display"] == "summarized"
    # Original thinking fields survive alongside the injected display.
    assert result["thinking"]["type"] == thinking["type"]
    # Unrelated request fields are untouched by the rewrite.
    assert result["model"] == model
    assert result["messages"] == [{"role": "user", "content": "hi"}]


@pytest.mark.parametrize(
    "model,thinking",
    [
        # Existing display must be respected (a fixed future CLI wins).
        ("databricks-claude-opus-4-8", {"type": "adaptive", "display": "omitted"}),
        # Disabled thinking has nothing to display.
        ("databricks-claude-opus-4-8", {"type": "disabled"}),
        # Sonnet streams visible thinking by default — never touched.
        ("databricks-claude-sonnet-4-6", {"type": "adaptive"}),
        ("system.ai.claude-sonnet-4-6", {"type": "adaptive"}),
        # First-party ids (no databricks- prefix) are out of scope.
        ("claude-opus-4-8", {"type": "adaptive"}),
        ("claude-fable-5", {"type": "adaptive"}),
        # No thinking key at all — nothing to patch.
        ("databricks-claude-opus-4-8", None),
    ],
)
def test_restore_leaves_non_qualifying_bodies_unchanged(
    model: str,
    thinking: dict[str, Any] | None,  # type: ignore[explicit-any]  # parametrized API dict
) -> None:
    """Bodies outside the opus-missing-display shape pass through unchanged."""
    body = _body(model, thinking)
    assert restore_thinking_display(body) == body


@pytest.mark.parametrize(
    "body",
    [
        b"not json at all",
        b'"a json string"',
        b'["a", "json", "array"]',
        json.dumps({"model": "databricks-claude-opus-4-8", "thinking": "adaptive"}).encode(),
    ],
)
def test_restore_passes_through_unparseable_bodies(body: bytes) -> None:
    """Non-object JSON, invalid JSON, and non-dict thinking are forwarded
    verbatim rather than raising — the upstream owns request validation."""
    assert restore_thinking_display(body) == body


# CORAL(S124): only the exact form written for a static key is a literal; anything else runs.
@pytest.mark.parametrize(
    "value", ["sk-ant-test-0123abcd", "it's a key", "$HOME `id` ;|&", "line\nbreak", ""]
)
def test_static_printf_value_reads_a_quoted_literal_back(value: str) -> None:
    assert static_printf_value(f"printf %s {shlex.quote(value)}") == value


@pytest.mark.parametrize(
    "command",
    [
        'printf %s "$MY_KEY"',
        "printf '%s' sk-ant-test",
        "printf  %s sk-ant-test",
        "printf %s sk-ant-test extra",
        "printf %s 'unbalanced",
        "databricks auth token --host https://example.cloud.databricks.com",
        "",
    ],
)
def test_static_printf_value_treats_other_commands_as_commands(command: str) -> None:
    assert static_printf_value(command) is None


# ── shim integration tests (real local upstream) ──────────


@dataclass
class _CapturedRequest:
    """
    One request observed by the recording upstream.

    :param method: HTTP method, e.g. ``"POST"``.
    :param path: Request path, e.g. ``"/v1/messages"``.
    :param headers: Lower-cased header name → value.
    :param body: Raw request body bytes.
    :param raw_path: CORAL(S124): the undecoded request target path.
    :param query: CORAL(S124): the raw query string.
    """

    method: str
    path: str
    headers: dict[str, str]
    body: bytes
    raw_path: bytes = b""  # CORAL(S124)
    query: bytes = b""  # CORAL(S124)


@dataclass
class _RecordingUpstream:
    """
    Minimal real ASGI server standing in for the Anthropic gateway.

    Records every request and answers ``POST /v1/messages`` with a
    small SSE stream (mirroring the real streaming endpoint); other
    paths get a JSON body.
    """

    requests: list[_CapturedRequest] = field(default_factory=list)
    _server: uvicorn.Server | None = None
    _task: asyncio.Task[None] | None = None
    port: int | None = None
    # CORAL(S124): credentials answered 401, and the HTTP parser (h11 keeps absolute-form targets)
    rejected_credentials: set[str] = field(default_factory=set)
    http: str = "auto"

    async def _app(self, scope, receive, send) -> None:  # type: ignore[no-untyped-def]  # ASGI protocol is untyped dicts
        """
        Record the request and reply.

        :param scope: ASGI HTTP scope.
        :param receive: ASGI receive callable.
        :param send: ASGI send callable.
        """
        if scope["type"] != "http":
            return
        body = bytearray()
        while True:
            message = await receive()
            body.extend(message.get("body", b""))
            if not message.get("more_body", False):
                break
        self.requests.append(
            _CapturedRequest(
                method=scope["method"],
                path=scope["path"],
                headers={
                    k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope["headers"]
                },
                body=bytes(body),
                raw_path=scope.get("raw_path", b""),  # CORAL(S124)
                query=scope.get("query_string", b""),  # CORAL(S124)
            )
        )
        # CORAL(S124): a rejected credential gets the upstream's own 401
        seen = self.requests[-1].headers
        presented = {seen.get("x-api-key"), seen.get("authorization", "").removeprefix("Bearer ")}
        if presented & self.rejected_credentials:
            await send(
                {
                    "type": "http.response.start",
                    "status": 401,
                    "headers": [(b"content-type", b"application/json")],
                }
            )
            await send({"type": "http.response.body", "body": b'{"upstream": "rejected"}'})
            return
        if scope["method"] == "POST" and scope["path"] == "/v1/messages":
            await send(
                {
                    "type": "http.response.start",
                    "status": 200,
                    "headers": [(b"content-type", b"text/event-stream")],
                }
            )
            for event in (b"event: ping\ndata: {}\n\n", b"data: [DONE]\n\n"):
                await send({"type": "http.response.body", "body": event, "more_body": True})
            await send({"type": "http.response.body", "body": b""})
        else:
            await send(
                {
                    "type": "http.response.start",
                    "status": 200,
                    "headers": [(b"content-type", b"application/json")],
                }
            )
            await send({"type": "http.response.body", "body": b'{"upstream": "ok"}'})

    async def start(self) -> str:
        """
        Serve on an ephemeral loopback port.

        :returns: The upstream base URL, e.g. ``"http://127.0.0.1:49153"``.
        """
        config = uvicorn.Config(
            self._app,
            host="127.0.0.1",
            port=0,
            log_level="warning",
            lifespan="off",
            interface="asgi3",  # bound methods defeat uvicorn's auto-detection
            http=self.http,  # CORAL(S124)
        )
        self._server = uvicorn.Server(config)
        self._task = asyncio.create_task(self._server.serve())
        while not self._server.started:
            if self._task.done():
                self._task.result()
                raise OSError("recording upstream exited before startup")
            await asyncio.sleep(0.01)
        self.port = self._server.servers[0].sockets[0].getsockname()[1]
        return f"http://127.0.0.1:{self.port}"

    async def stop(self) -> None:
        """Shut the server down and reap its serve task."""
        if self._server is not None:
            self._server.should_exit = True
        if self._task is not None:
            await asyncio.wait_for(self._task, timeout=5.0)


@pytest.fixture
async def upstream() -> Any:  # type: ignore[explicit-any]  # async generator fixture; pytest infers the yield type
    """Run a recording upstream for the duration of one test."""
    server = _RecordingUpstream()
    await server.start()
    yield server
    await server.stop()


@pytest.mark.asyncio
async def test_shim_patches_opus_messages_body_and_streams_response(upstream) -> None:  # type: ignore[no-untyped-def]  # fixture type owned by pytest
    """An opus ``/v1/messages`` POST through the shim reaches the
    upstream with ``display`` injected, and the SSE response streams
    back byte-identical."""
    shim = ClaudeGatewayShim(upstream_base_url=f"http://127.0.0.1:{upstream.port}")
    await shim.start()
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{shim.base_url}/v1/messages",
                content=_body("databricks-claude-opus-4-8", {"type": "adaptive"}),
                headers={"authorization": "Bearer test-token"},
            )
        # SSE body round-trips through the shim unmodified — a buffering
        # or truncation bug in the relay would corrupt this.
        assert resp.status_code == 200
        assert resp.headers["content-type"] == "text/event-stream"
        assert resp.text == "event: ping\ndata: {}\n\ndata: [DONE]\n\n"

        assert len(upstream.requests) == 1
        seen = upstream.requests[0]
        # The patch is the whole point of the shim: without it the
        # upstream body has no display and opus streams no thinking.
        upstream_body = json.loads(seen.body)
        assert upstream_body["thinking"] == {
            "type": "adaptive",
            "display": "summarized",
        }
        # Auth must pass through verbatim or every request 401s.
        assert seen.headers["authorization"] == "Bearer test-token"
    finally:
        await shim.aclose()


@pytest.mark.asyncio
async def test_shim_forwards_non_opus_and_non_messages_traffic_verbatim(upstream) -> None:  # type: ignore[no-untyped-def]  # fixture type owned by pytest
    """Sonnet bodies and non-/v1/messages requests are proxied untouched."""
    shim = ClaudeGatewayShim(upstream_base_url=f"http://127.0.0.1:{upstream.port}")
    await shim.start()
    try:
        sonnet_body = _body("databricks-claude-sonnet-4-6", {"type": "adaptive"})
        async with httpx.AsyncClient() as client:
            await client.post(f"{shim.base_url}/v1/messages", content=sonnet_body)
            other = await client.get(f"{shim.base_url}/v1/models?limit=5")

        # Sonnet body forwarded byte-for-byte — an over-broad patch that
        # touched sonnet would change its (working) thinking behavior.
        assert upstream.requests[0].body == sonnet_body
        # Non-messages path + query string forwarded as-is.
        assert upstream.requests[1].method == "GET"
        assert upstream.requests[1].path == "/v1/models"
        assert other.json() == {"upstream": "ok"}
    finally:
        await shim.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("upstream_url", "surfaces"),
    [
        (
            "https://ws.cloud.databricks.com/ai-gateway/anthropic",
            "omnigent-desktop, ug, inner",
        ),
        ("https://ws.cloud.databricks.com/serving-endpoints/anthropic", "ug, inner"),
    ],
    ids=["gateway", "serving-endpoint"],
)
async def test_shim_restores_gateway_attribution_after_cli_settings(
    upstream_url: str, surfaces: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("OMNIGENT_CLIENT_SURFACE", "desktop")
    requests: list[httpx.Request] = []

    def record(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, stream=httpx.ByteStream(b"recorded"))

    shim = ClaudeGatewayShim(upstream_base_url=upstream_url)
    await shim.start()
    assert shim._client is not None
    await shim._client.aclose()
    shim._client = httpx.AsyncClient(transport=httpx.MockTransport(record))
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{shim.base_url}/v1/messages",
                json={"model": "test", "messages": []},
                headers=[
                    ("Authorization", "Bearer synthetic-key"),
                    ("anthropic-beta", "one"),
                    ("anthropic-beta", "two"),
                    ("databricks-custom-coding-agent", "stale-agent"),
                    ("databricks-custom-client-surfaces", "ug, inner"),
                ],
            )
        assert response.status_code == 200
        assert len(requests) == 1
        request = requests[0]
        assert str(request.url) == upstream_url + "/v1/messages"
        assert request.headers["Databricks-Custom-Client-Surfaces"] == surfaces
        assert request.headers["Databricks-Custom-Coding-Agent"] == (
            "claude-code" if surfaces.startswith("omnigent") else "stale-agent"
        )
        assert request.headers["Authorization"] == "Bearer synthetic-key"
        assert request.headers.get_list("anthropic-beta") == ["one", "two"]
    finally:
        await shim.aclose()


@pytest.mark.asyncio
async def test_shim_returns_502_when_upstream_unreachable() -> None:
    """Upstream connection failures surface as a 502 with an Anthropic-
    shaped error body instead of hanging or crashing the shim."""
    # Port 9 (discard) on loopback is closed — connect fails immediately.
    shim = ClaudeGatewayShim(upstream_base_url="http://127.0.0.1:9")
    await shim.start()
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{shim.base_url}/v1/messages",
                content=_body("databricks-claude-opus-4-8", {"type": "adaptive"}),
            )
        assert resp.status_code == 502
        # Anthropic error shape lets the CLI render a real API error.
        assert resp.json()["type"] == "error"
    finally:
        await shim.aclose()


@pytest.mark.asyncio
async def test_shim_does_not_install_process_signal_handlers() -> None:
    """The shim's uvicorn server must not swap the process's
    SIGINT/SIGTERM handlers — the harness subprocess's own uvicorn
    server owns those for graceful shutdown (_runner.py). A stock
    ``uvicorn.Server`` here replaces the handlers for the shim's whole
    lifetime, silently breaking harness SIGTERM shutdown."""
    import signal

    before = {sig: signal.getsignal(sig) for sig in (signal.SIGINT, signal.SIGTERM)}
    shim = ClaudeGatewayShim(upstream_base_url="http://127.0.0.1:9")
    await shim.start()
    try:
        after = {sig: signal.getsignal(sig) for sig in (signal.SIGINT, signal.SIGTERM)}
        # Identical handler objects — the shim never touched them.
        assert after == before
    finally:
        await shim.aclose()


# ── executor wiring test ──────────────────────────────────


@pytest.mark.asyncio
async def test_gateway_executor_routes_new_client_through_shim(monkeypatch) -> None:  # type: ignore[no-untyped-def]  # pytest fixture
    """On the gateway path, a new SDK client's env must point at the
    local shim, and the shim must target the original gateway URL.

    Follows this suite's established stub-SDK pattern for driving
    ``_get_or_create_client`` (the seam where ``options.env`` is
    consumed); spawning the real CLI is infeasible in unit tests.
    """
    from omnigent.inner.claude_sdk_executor import ClaudeSDKExecutor
    from omnigent.inner.databricks_executor import DatabricksCredentials

    monkeypatch.setattr(
        "omnigent.inner.databricks_executor._read_databrickscfg",
        lambda profile=None: DatabricksCredentials(
            host="https://example.databricks.com", token="dapi_test_token"
        ),
    )
    executor = ClaudeSDKExecutor(gateway=True)

    connect_env: dict[str, str] = {}

    class _StubClient:
        """Captures ``options.env`` at connect time (= CLI spawn time)."""

        def __init__(self, options) -> None:  # type: ignore[no-untyped-def]  # SDK options shape owned by stub
            self.options = options
            self._query = None
            self._transport = None

        async def connect(self) -> None:
            """Snapshot the env the CLI subprocess would receive."""
            connect_env.update(self.options.env)

        async def disconnect(self) -> None:
            """No-op disconnect for teardown."""

    class _StubSDK:
        """Minimal SDK namespace exposing ClaudeSDKClient."""

        ClaudeSDKClient = _StubClient

    from types import SimpleNamespace

    options = SimpleNamespace(
        env={"ANTHROPIC_BASE_URL": "https://example.databricks.com/ai-gateway/anthropic"},
        stderr=None,
    )
    try:
        await executor._get_or_create_client(
            _StubSDK,  # type: ignore[arg-type]  # stub stands in for the claude_agent_sdk module
            session_key="wiring-test",
            options=options,
            model="databricks-claude-opus-4-8",
        )
        # The CLI must talk to the loopback shim, not the gateway
        # directly — otherwise its stripped body reaches the gateway
        # and opus thinking stays silent.
        assert connect_env["ANTHROPIC_BASE_URL"].startswith("http://127.0.0.1:")
        assert executor._gateway_shim is not None
        assert connect_env["ANTHROPIC_BASE_URL"] == executor._gateway_shim.base_url
    finally:
        if executor._gateway_shim is not None:
            await executor._gateway_shim.aclose()


# ── credential mode: CORAL(S124) ──────────────────────────
# Fake values only. Secrets are compared by presence; failures name labels, never values.

_FAKE_KEY = f"sk-ant-test-{secrets.token_hex(8)}"
_FAKE_STALE_KEY = f"sk-ant-test-stale-{secrets.token_hex(8)}"
_HTTP_DEBUG_LOGGERS = (
    "omnigent",
    "httpx",
    "httpcore",
    "uvicorn",
    "uvicorn.error",
    "uvicorn.access",
    "uvicorn.asgi",
)


def _literal_credential(value: str = _FAKE_KEY) -> UpstreamCredential:
    """A static-key credential in the exact form the workflow writes."""
    return UpstreamCredential(f"printf %s {shlex.quote(value)}", ttl_s=None, env={})


def _counted_credential(
    tmp_path: Path,
    command: str = 'printf %s "$FAKE_UPSTREAM_KEY"',
    *,
    ttl_s: float | None = None,
    **env: str,
) -> tuple[UpstreamCredential, Path]:
    """A command credential that appends one ``x`` to a counter file per run."""
    counter = tmp_path / "credential-runs"
    snapshot = {
        "PATH": "/usr/bin:/bin",
        "RUN_COUNTER": str(counter),
        "FAKE_UPSTREAM_KEY": _FAKE_KEY,
        **env,
    }
    return UpstreamCredential(
        f'printf x >> "$RUN_COUNTER"; {command}', ttl_s=ttl_s, env=snapshot
    ), counter


def _runs(counter: Path) -> int:
    """How many times a counted credential command ran."""
    return counter.read_text().count("x") if counter.exists() else 0


@contextlib.asynccontextmanager
async def _running_shim(
    upstream_url: str, credential: UpstreamCredential | None, **options: str
) -> AsyncIterator[ClaudeGatewayShim]:
    """Start a shim for one block and always stop it."""
    shim = ClaudeGatewayShim(upstream_url, credential=credential, **options)
    await shim.start()
    try:
        yield shim
    finally:
        await shim.aclose()


async def _send(
    shim: ClaudeGatewayShim,
    headers: list[tuple[str, str]],
    *,
    method: str = "POST",
    path: str = "/v1/messages",
    body: bytes | None = None,
) -> httpx.Response:
    """One request to the shim from a client that ignores the environment."""
    content = _body("claude-test-model", None) if body is None and method == "POST" else body
    async with httpx.AsyncClient(trust_env=False) as client:
        return await client.request(
            method, f"{shim.base_url}{path}", headers=headers, content=content
        )


def _token_headers(shim: ClaudeGatewayShim) -> list[tuple[str, str]]:
    assert shim.session_token is not None
    return [("x-api-key", shim.session_token)]


async def _raw_status(
    port: int,
    target: str,
    token: str,
    *,
    send_body: bool = True,
    method: str = "POST",
    body: bytes = b'{"model": "claude-test-model", "messages": []}',
    declared_length: int | None = None,
) -> int:
    """Send a hand-written request so the target reaches the parser unnormalized.

    :param declared_length: The content-length to announce when it differs from *body*'s.
    :returns: The response status, or 0 when the server closed without one.
    """
    length = len(body) if declared_length is None else declared_length
    head = (
        f"{method} {target} HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\nx-api-key: {token}\r\n"
        f"content-type: application/json\r\ncontent-length: {length}\r\n"
        "connection: close\r\n\r\n"
    )
    reader, writer = await asyncio.open_connection("127.0.0.1", port)
    try:
        writer.write(head.encode("latin-1") + (body if send_body else b""))
        await writer.drain()
        status_line = await asyncio.wait_for(reader.readline(), timeout=10)
    finally:
        writer.close()
        with contextlib.suppress(OSError):
            await writer.wait_closed()
    parts = status_line.split()
    return int(parts[1]) if len(parts) >= 2 else 0


def _debug_every_http_logger(
    caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Capture DEBUG from the shim, the HTTP client and uvicorn, after uvicorn configured them.

    Logging setups give httpx and uvicorn their own handlers without propagation; caplog
    listens on the root logger, so propagation is restored for the test.
    """
    for name in _HTTP_DEBUG_LOGGERS:
        named = logging.getLogger(name)
        monkeypatch.setattr(named, "propagate", True)
        monkeypatch.setattr(named, "disabled", False)
        caplog.set_level(logging.DEBUG, logger=name)


def _leaked(
    values: dict[str, str], response_text: str, caplog: pytest.LogCaptureFixture
) -> list[str]:
    """The labels of *values* found in the response or any captured record (with tracebacks)."""
    formatter = logging.Formatter("%(name)s %(message)s")
    texts = [response_text, *(formatter.format(record) for record in caplog.records)]
    return sorted(label for label, value in values.items() if any(value in text for text in texts))


@pytest.fixture(params=["httptools", "h11"])
def http_parser(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> str:
    """Run the credential shim on one HTTP parser; the recording upstream keeps its own."""
    monkeypatch.setattr(shim_module, "_CREDENTIAL_PROXY_HTTP_PARSER", request.param)
    return request.param


def test_a_credential_shim_gets_a_fresh_session_token_and_a_plain_shim_none() -> None:
    first = ClaudeGatewayShim("http://127.0.0.1:9", credential=_literal_credential())
    second = ClaudeGatewayShim("http://127.0.0.1:9", credential=_literal_credential())
    assert first.session_token is not None and second.session_token is not None
    assert len(first.session_token) >= 43  # 256 bits, URL-safe base64
    assert first.session_token != second.session_token
    assert ClaudeGatewayShim("http://127.0.0.1:9").session_token is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "forms", [("x-api-key",), ("authorization",), ("x-api-key", "authorization")]
)
async def test_the_real_key_replaces_the_session_token_in_the_clis_header_forms(
    upstream: _RecordingUpstream, forms: tuple[str, ...]
) -> None:
    async with _running_shim(f"http://127.0.0.1:{upstream.port}", _literal_credential()) as shim:
        token = shim.session_token
        assert token is not None
        sent = [
            ("x-api-key", token) if form == "x-api-key" else ("authorization", f"Bearer {token}")
            for form in forms
        ]
        response = await _send(shim, sent)
    assert response.status_code == 200
    assert len(upstream.requests) == 1
    seen = upstream.requests[0].headers
    expected = {"x-api-key": _FAKE_KEY, "authorization": f"Bearer {_FAKE_KEY}"}
    assert {name: seen.get(name) for name in expected} == {
        name: expected[name] if name in forms else None for name in expected
    }
    assert not any(token in value for value in seen.values()), "session token went upstream"


_REQUEST_OVERRIDES = (
    ("X-Original-URL", "/api/2.0/clusters/list"),
    ("X-Rewrite-URL", "/api/2.0/clusters/list"),
    ("X-HTTP-Method-Override", "DELETE"),
    ("X-HTTP-Method", "DELETE"),
    ("X-Method-Override", "DELETE"),
    ("Forwarded", "for=192.0.2.1;host=evil.example;proto=https"),
    ("X-Forwarded-For", "192.0.2.1"),
    ("X-Forwarded-Host", "evil.example"),
    ("X-Forwarded-Prefix", "/api/2.0"),
    ("X-Forwarded-Proto", "https"),
)


@pytest.mark.asyncio
async def test_request_override_headers_reach_the_upstream_only_from_a_plain_shim(
    upstream: _RecordingUpstream,
) -> None:
    overrides = {name.lower() for name, _ in _REQUEST_OVERRIDES}
    async with _running_shim(f"http://127.0.0.1:{upstream.port}", _literal_credential()) as shim:
        headers = [*_token_headers(shim), *_REQUEST_OVERRIDES, ("anthropic-beta", "kept")]
        assert (await _send(shim, headers)).status_code == 200
    async with _running_shim(f"http://127.0.0.1:{upstream.port}", None) as plain:
        assert (await _send(plain, list(_REQUEST_OVERRIDES))).status_code == 200
    credential_seen, plain_seen = (request.headers for request in upstream.requests)
    assert sorted(overrides & credential_seen.keys()) == []
    assert credential_seen.get("anthropic-beta") == "kept"
    assert sorted(overrides - plain_seen.keys()) == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("upstream_url", "refused"),
    [
        ("http://gateway.example/anthropic", "http"),
        ("http://127.0.0.1.gateway.example", "http"),
        ("ftp://gateway.example", "another scheme"),
        ("http://127.0.0.1:9", None),
        ("http://localhost:9/base", None),
        ("http://[::1]:9", None),
        ("https://gateway.example/anthropic", None),
    ],
)
async def test_a_credential_shim_takes_plain_http_upstreams_on_loopback_only(
    upstream_url: str, refused: str | None
) -> None:
    shim = ClaudeGatewayShim(upstream_url, credential=_literal_credential())
    try:
        if refused is None:
            await shim.start()
        else:
            with pytest.raises(OSError) as raised:
                await shim.start()
            assert str(raised.value) == (
                "Claude credential proxy needs an https upstream or a loopback http one "
                f"(got {refused})"
            )
            assert shim._server is None and shim._client is None
    finally:
        await shim.aclose()
    async with _running_shim(upstream_url, None) as plain:  # the plain shim takes any upstream
        assert plain.base_url.startswith("http://127.0.0.1:")


# CORAL(S125): one check says where the real credential may go, for the executor's turn and
# for the shim's start; what it refuses it refuses without quoting the URL.
@pytest.mark.parametrize(
    ("url", "refused"),
    [
        ("https://gateway.example/anthropic", None),
        ("https://gateway.example:8443", None),
        ("https://[2001:db8::1]:8443/anthropic", None),
        ("http://127.0.0.1:8080/anthropic", None),
        ("http://localhost:8080", None),
        ("https://gateway.example/v1/@handle", None),  # an @ in the path is no userinfo
        ("http://gateway.example", "got http"),
        ("ftp://gateway.example", "got another scheme"),
        ("gateway.example/anthropic", "got another scheme"),
        ("https://user:<secret>@gateway.example/anthropic", "user name"),
        ("https://<secret>@gateway.example", "user name"),
        ("https://@gateway.example", "user name"),
        ("http://user:<secret>@127.0.0.1:8080", "user name"),
        ("http://<secret>.example\\@localhost", "backslash"),
        ("https://gateway.example\\anthropic", "backslash"),
        ("https:///anthropic", "a host"),
        ("https://", "a host"),
        ("https://:8443/anthropic", "a host"),
        ("https://[2001:db8::1", "a host"),
        ("https://gateway.example:notaport", "numeric port"),
        ("https://gateway.example:99999", "numeric port"),
        ("https://name:<secret>", "numeric port"),
        ("https://gateway.example/\x00anthropic", "control character"),
        ("https://gateway.example/v1?beta=<secret>", "query"),
        ("https://gateway.example/#<secret>", "fragment"),
    ],
)
def test_one_check_says_where_the_real_credential_may_go(url: str, refused: str | None) -> None:
    secret = f"pw-{secrets.token_hex(8)}"
    url = url.replace("<secret>", secret)
    if refused is None:
        shim_module.check_upstream_url(url)
        return
    with pytest.raises(OSError) as raised:
        shim_module.check_upstream_url(url)
    message = str(raised.value)
    assert refused in message
    shown = (secret, "gateway", "example", "notaport", "99999", "8443", "anthropic", "handle")
    assert not [text for text in shown if text in message]


@pytest.mark.asyncio
async def test_a_credential_shim_does_not_start_on_an_upstream_with_userinfo() -> None:
    upstream_url = "https://user:pw-fake@gateway.example/anthropic"
    shim = ClaudeGatewayShim(upstream_url, credential=_literal_credential())
    try:
        with pytest.raises(OSError, match="no user name, password") as raised:
            await shim.start()
        assert "pw-fake" not in str(raised.value)
        assert shim._server is None and shim._client is None
    finally:
        await shim.aclose()
    async with _running_shim(upstream_url, None) as plain:  # the plain shim is unchanged
        assert plain.base_url.startswith("http://127.0.0.1:")


@pytest.mark.asyncio
async def test_a_static_key_is_held_without_starting_a_shell(
    upstream: _RecordingUpstream, monkeypatch: pytest.MonkeyPatch
) -> None:
    spawned: list[str] = []

    async def no_command(command: str, env: object) -> bytes:
        spawned.append("command")
        raise AssertionError("a static key must not start a process")

    monkeypatch.setattr(shim_module, "_run_credential_command", no_command)
    credential = _literal_credential()
    assert credential.refreshable is False
    assert _FAKE_KEY not in repr(credential)
    async with _running_shim(f"http://127.0.0.1:{upstream.port}", credential) as shim:
        response = await _send(shim, _token_headers(shim))
    assert response.status_code == 200
    assert upstream.requests[0].headers["x-api-key"] == _FAKE_KEY
    assert spawned == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "case", ["none", "wrong-key", "wrong-bearer", "one-wrong-of-two", "duplicated", "basic"]
)
async def test_a_request_without_exactly_the_session_token_gets_401_and_nothing_runs(
    upstream: _RecordingUpstream, tmp_path: Path, case: str
) -> None:
    credential, counter = _counted_credential(tmp_path)
    wrong = f"sk-ant-test-presented-{secrets.token_hex(8)}"
    async with _running_shim(f"http://127.0.0.1:{upstream.port}", credential) as shim:
        token = shim.session_token
        assert token is not None
        headers = {
            "none": [],
            "wrong-key": [("x-api-key", wrong)],
            "wrong-bearer": [("authorization", f"Bearer {wrong}")],
            "one-wrong-of-two": [("x-api-key", token), ("authorization", f"Bearer {wrong}")],
            "duplicated": [("x-api-key", token), ("x-api-key", token)],
            "basic": [("authorization", f"Basic {token}")],
        }[case]
        response = await _send(shim, headers)
    assert response.status_code == 401
    assert response.json()["error"]["type"] == "authentication_error"
    assert wrong not in response.text and token not in response.text
    assert upstream.requests == [] and _runs(counter) == 0


@pytest.mark.asyncio
async def test_the_session_token_is_checked_before_the_body_is_read(
    upstream: _RecordingUpstream, tmp_path: Path
) -> None:
    credential, counter = _counted_credential(tmp_path)
    async with _running_shim(f"http://127.0.0.1:{upstream.port}", credential) as shim:
        assert shim._port is not None
        # A body is announced but never sent: only a header-first check can answer.
        status = await _raw_status(shim._port, "/v1/messages", "not-the-token", send_body=False)
    assert status == 401
    assert upstream.requests == [] and _runs(counter) == 0


@pytest.mark.asyncio
async def test_only_the_four_model_routes_are_forwarded_with_their_queries(
    upstream: _RecordingUpstream, caplog: pytest.LogCaptureFixture
) -> None:
    allowed = [
        ("POST", "/v1/messages?beta=true"),
        ("POST", "/v1/messages/count_tokens"),
        ("GET", "/v1/models?limit=5"),
        ("GET", "/v1/models/claude-test-model"),
    ]
    refused = [
        ("GET", "/v1/messages"),
        ("PUT", "/v1/messages"),
        ("POST", "/v1/models"),
        ("POST", "/v1/complete"),
        ("GET", "/api/2.0/clusters/list"),
        ("OPTIONS", "/v1/messages"),
        ("HEAD", "/v1/models"),
        ("HEAD", "/v1/models/claude-test-model"),
        ("DELETE", "/v1/models/claude-test-model"),
        ("POST", "/v1/models/claude-test-model"),
    ]
    caplog.set_level(logging.WARNING, logger="omnigent")
    async with _running_shim(f"http://127.0.0.1:{upstream.port}", _literal_credential()) as shim:
        for method, target in allowed:
            assert (await _send(shim, _token_headers(shim), method=method, path=target)).is_success
        for method, target in refused:
            response = await _send(shim, _token_headers(shim), method=method, path=target)
            assert response.status_code == 404, (method, target)
    forwarded = [
        (r.method, r.raw_path.decode() + (f"?{r.query.decode()}" if r.query else ""))
        for r in upstream.requests
    ]
    assert forwarded == allowed
    assert not any("clusters" in record.getMessage() for record in caplog.records)


_UNSAFE_TARGETS = (
    "/v1/../v1/messages",
    "/v1/messages/..",
    "/./v1/messages",
    "//v1/messages",
    "/v1//messages",
    "/v1/messages/",
    "/@evil.example/v1/messages",
    "@evil.example/v1/messages",
    "/v1/models/a@evil.example",
    "/v1\\messages",
    "/v1/%2e%2e/api/2.0/clusters/list",
    "/v1/%2E%2E/v1/messages",
    "/v1/messages%2f..%2fapi",
    "/%40evil.example/v1/messages",
    "/v1/messages%3fbeta=true",
    "/v1/messages%23fragment",
    "/v1%5cmessages",
    "/v1/models/%2e%2e",
    "http://evil.example/api/2.0/clusters/list",
    "http://evil.example/v1/../api/2.0/clusters/list",
    "https://api.anthropic.com@evil.example/v1/../api",
)
# A model id is one plain word; these reach no upstream that strips `;` or decodes twice
_REFUSED_MODEL_IDS = (
    "..;",
    ".;x",
    "%252e%252e",
    "%00",
    "a%25",
    "%3b",
    "#frag",
    "-leading-dash",
    "a" * 129,
    "claude-test-model/extra",
)
# GET /v1/models/<id> is the one allowed route with a free segment: only path hygiene refuses these
_UNSAFE_MODEL_TARGETS = (
    *(f"/v1/models/{model_id}" for model_id in _REFUSED_MODEL_IDS),
    "/v1/models/",
    "/v1/models/.",
    "/v1/models/..",
    "/v1/models/%2e",
    "/v1/models/%2E%2E",
    "/v1/models/a%2Fb",
    "/v1/models/a%5Cb",
    "/v1/models/%40evil.example",
    "/v1/models/a%3Fb",
    "/v1/models/a%23b",
    "/v1/models/a\\b",
    "/v1/models/a@b",
    "/v1/models/café",
)


@pytest.mark.asyncio
async def test_unsafe_targets_are_refused_under_both_http_parsers(
    http_parser: str, upstream: _RecordingUpstream, tmp_path: Path
) -> None:
    credential, counter = _counted_credential(tmp_path)
    async with _running_shim(f"http://127.0.0.1:{upstream.port}", credential) as shim:
        assert shim._server is not None and shim._server.config.http == http_parser
        assert shim._port is not None and shim.session_token is not None
        statuses = {
            (method, target): await _raw_status(
                shim._port, target, shim.session_token, method=method
            )
            for method, targets in (("POST", _UNSAFE_TARGETS), ("GET", _UNSAFE_MODEL_TARGETS))
            for target in targets
        }
    answered = {
        target: status for target, status in statuses.items() if status not in (0, 400, 404)
    }
    assert answered == {}
    assert upstream.requests == [] and _runs(counter) == 0


@pytest.mark.asyncio
async def test_only_a_plain_model_id_is_forwarded(upstream: _RecordingUpstream) -> None:
    plain_ids = ("claude-test-model", "vendor.claude-test:1", "a" * 128)
    async with _running_shim(f"http://127.0.0.1:{upstream.port}", _literal_credential()) as shim:
        assert shim._port is not None and shim.session_token is not None
        refused = {
            model_id: await _raw_status(
                shim._port, f"/v1/models/{model_id}", shim.session_token, method="GET", body=b""
            )
            for model_id in _REFUSED_MODEL_IDS
        }
        for model_id in plain_ids:
            path = f"/v1/models/{model_id}"
            assert (await _send(shim, _token_headers(shim), method="GET", path=path)).is_success
    assert {model_id: status for model_id, status in refused.items() if status != 400} == {}
    assert [request.raw_path.decode() for request in upstream.requests] == [
        f"/v1/models/{model_id}" for model_id in plain_ids
    ]


@pytest.mark.asyncio
async def test_an_absolute_form_target_reaches_only_the_configured_upstream(
    http_parser: str, upstream: _RecordingUpstream
) -> None:
    async with _running_shim(f"http://127.0.0.1:{upstream.port}", _literal_credential()) as shim:
        assert shim._port is not None and shim.session_token is not None
        status = await _raw_status(
            shim._port, "http://evil.example/v1/messages", shim.session_token
        )
    # httptools hands the app only the target's path, so the request goes to the configured
    # upstream as /v1/messages; h11 keeps the whole target, which the path check refuses.
    forwarded = [request.raw_path for request in upstream.requests]
    assert (status, forwarded) == (
        (200, [b"/v1/messages"]) if http_parser == "httptools" else (400, [])
    )


@pytest.mark.asyncio
async def test_a_joined_url_outside_the_upstream_base_path_is_refused(
    upstream: _RecordingUpstream,
) -> None:
    base = f"http://127.0.0.1:{upstream.port}/base"
    async with _running_shim(base, _literal_credential()) as shim:
        # CORAL(S125): no shim starts on such a base any more; the request check still holds
        shim._upstream_base_url = f"{base}?misplaced=query"
        response = await _send(shim, _token_headers(shim))
    assert response.status_code == 400
    assert upstream.requests == []


@pytest.mark.asyncio
async def test_a_body_over_the_cap_gets_413(
    upstream: _RecordingUpstream, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert shim_module._MAX_REQUEST_BODY_BYTES == 32 * 1024 * 1024
    monkeypatch.setattr(shim_module, "_MAX_REQUEST_BODY_BYTES", 1024)
    async with _running_shim(f"http://127.0.0.1:{upstream.port}", _literal_credential()) as shim:
        over = await _send(shim, _token_headers(shim), body=b"x" * 1025)
        at_cap = await _send(shim, _token_headers(shim), body=b"x" * 1024)
    assert (over.status_code, at_cap.status_code) == (413, 200)
    assert [len(request.body) for request in upstream.requests] == [1024]


async def _flood_request_head(port: int, total: int) -> tuple[int, int]:
    """Send a token-less request head that never ends.

    :returns: The header bytes written before the server stopped reading, and its status
        (0 when it closed without one).
    """
    line = b"x-pad: " + b"a" * 1015 + b"\r\n"  # 1 KiB
    sent, status_line = 0, b""
    reader, writer = await asyncio.open_connection("127.0.0.1", port)
    try:
        writer.write(f"POST /v1/messages HTTP/1.1\r\nhost: 127.0.0.1:{port}\r\n".encode())
        with contextlib.suppress(ConnectionError):
            while sent < total:
                writer.write(line)
                await writer.drain()
                sent += len(line)
        with contextlib.suppress(ConnectionError):
            status_line = await asyncio.wait_for(reader.readline(), timeout=10)
    finally:
        writer.close()
        with contextlib.suppress(OSError):
            await writer.wait_closed()
    parts = status_line.split()
    return sent, int(parts[1]) if len(parts) >= 2 else 0


@pytest.mark.asyncio
async def test_a_credential_shim_runs_h11_and_refuses_an_endless_request_head(
    upstream: _RecordingUpstream, tmp_path: Path
) -> None:
    credential, counter = _counted_credential(tmp_path)
    flood = 16 * 1024 * 1024
    async with _running_shim(f"http://127.0.0.1:{upstream.port}", credential) as shim:
        assert shim._server is not None and shim._port is not None
        assert shim._server.config.http == "h11"  # httptools buffers headers without a bound
        sent, status = await _flood_request_head(shim._port, flood)
    async with _running_shim(f"http://127.0.0.1:{upstream.port}", None) as plain:
        assert plain._server is not None and plain._server.config.http == "auto"
    assert status in (0, 400) and sent < flood
    assert upstream.requests == [] and _runs(counter) == 0


@pytest.mark.asyncio
async def test_idle_unauthenticated_connections_leave_the_cli_served(
    upstream: _RecordingUpstream,
) -> None:
    async with _running_shim(f"http://127.0.0.1:{upstream.port}", _literal_credential()) as shim:
        assert shim._server is not None and shim._port is not None
        assert shim._server.config.limit_concurrency is None
        idle = [await asyncio.open_connection("127.0.0.1", shim._port) for _ in range(80)]
        try:
            await poll_until_async(lambda: len(shim._server.server_state.connections) >= 80)
            response = await _send(shim, _token_headers(shim), method="GET", path="/v1/models")
        finally:
            for _, writer in idle:
                writer.close()
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_a_body_cut_off_by_a_disconnect_is_neither_returned_nor_answered() -> None:
    messages = iter(
        [
            {"type": "http.request", "body": b'{"model":', "more_body": True},
            {"type": "http.disconnect"},
        ]
    )
    sent: list[object] = []

    async def receive() -> dict[str, object]:
        return next(messages)

    async def send(message: object) -> None:
        sent.append(message)

    assert await shim_module._receive_capped_body(receive, send) is None
    assert sent == []


@pytest.mark.asyncio
async def test_a_request_abandoned_mid_upload_is_not_forwarded(
    http_parser: str, upstream: _RecordingUpstream, tmp_path: Path
) -> None:
    credential, counter = _counted_credential(tmp_path)
    async with _running_shim(f"http://127.0.0.1:{upstream.port}", credential) as shim:
        assert shim._server is not None and shim._port is not None
        assert shim.session_token is not None
        handlers = shim._server.server_state.tasks
        head = (
            f"POST /v1/messages HTTP/1.1\r\nhost: 127.0.0.1:{shim._port}\r\n"
            f"x-api-key: {shim.session_token}\r\ncontent-length: 1000\r\n\r\n"
        )
        _, writer = await asyncio.open_connection("127.0.0.1", shim._port)
        try:
            writer.write(head.encode() + b'{"model": "claude-test-model"')
            await writer.drain()
            await poll_until_async(lambda: len(handlers) == 1)  # the shim is reading the body
        finally:
            writer.close()  # the CLI leaves after 29 of 1000 bytes
        await poll_until_async(lambda: not handlers)  # the request's handler has returned
    assert upstream.requests == [] and _runs(counter) == 0


@pytest.mark.asyncio
@pytest.mark.posix_only
async def test_a_command_credential_runs_once_for_concurrent_requests(
    upstream: _RecordingUpstream, tmp_path: Path
) -> None:
    credential, counter = _counted_credential(
        tmp_path, 'sleep 0.3; printf %s "$FAKE_UPSTREAM_KEY"'
    )
    assert credential.refreshable is True
    async with _running_shim(f"http://127.0.0.1:{upstream.port}", credential) as shim:
        responses = await asyncio.gather(*(_send(shim, _token_headers(shim)) for _ in range(8)))
    assert [response.status_code for response in responses] == [200] * 8
    assert _runs(counter) == 1
    assert {request.headers["x-api-key"] for request in upstream.requests} == {_FAKE_KEY}


@pytest.mark.asyncio
@pytest.mark.posix_only
async def test_a_command_credential_is_cached_for_its_ttl_until_invalidated(
    tmp_path: Path,
) -> None:
    for name in ("cached", "expired"):
        (tmp_path / name).mkdir()
    cached, cached_runs = _counted_credential(tmp_path / "cached")
    assert [await cached.get(), await cached.get()] == [_FAKE_KEY, _FAKE_KEY]
    assert _runs(cached_runs) == 1
    cached.invalidate()
    assert await cached.get() == _FAKE_KEY and _runs(cached_runs) == 2
    expired, expired_runs = _counted_credential(tmp_path / "expired", ttl_s=0)
    await expired.get()
    await expired.get()
    assert _runs(expired_runs) == 2


@pytest.mark.asyncio
@pytest.mark.posix_only
async def test_an_upstream_401_refreshes_once_per_request_and_once_per_30_seconds(
    upstream: _RecordingUpstream, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert shim_module._REFRESH_MIN_INTERVAL_S == 30.0
    # The first run prints the stale key, every later run the fresh one.
    command = (
        'if [ "$(cat "$RUN_COUNTER")" = x ]; then printf %s "$STALE_KEY"; '
        'else printf %s "$FAKE_UPSTREAM_KEY"; fi'
    )
    credential, counter = _counted_credential(tmp_path, command, STALE_KEY=_FAKE_STALE_KEY)
    upstream.rejected_credentials.add(_FAKE_STALE_KEY)
    body = _body("claude-test-model", None)
    async with _running_shim(f"http://127.0.0.1:{upstream.port}", credential) as shim:
        refreshed = await _send(shim, _token_headers(shim), body=body)
        assert (refreshed.status_code, _runs(counter)) == (200, 2)
        assert [r.headers["x-api-key"] for r in upstream.requests] == [_FAKE_STALE_KEY, _FAKE_KEY]
        assert [r.body for r in upstream.requests] == [body, body]

        upstream.rejected_credentials.add(_FAKE_KEY)
        within_window = await _send(shim, _token_headers(shim))
        assert (within_window.status_code, _runs(counter)) == (401, 2)
        assert within_window.json() == {"upstream": "rejected"}

        monkeypatch.setattr(shim_module, "_REFRESH_MIN_INTERVAL_S", 0.0)
        once_per_request = await _send(shim, _token_headers(shim))
        assert (once_per_request.status_code, _runs(counter)) == (401, 3)
    assert len(upstream.requests) == 5


@pytest.mark.asyncio
async def test_a_static_key_passes_an_upstream_401_through_without_refreshing(
    upstream: _RecordingUpstream,
) -> None:
    upstream.rejected_credentials.add(_FAKE_KEY)
    async with _running_shim(f"http://127.0.0.1:{upstream.port}", _literal_credential()) as shim:
        response = await _send(shim, _token_headers(shim))
    assert response.status_code == 401 and response.json() == {"upstream": "rejected"}
    assert len(upstream.requests) == 1


@pytest.mark.asyncio
@pytest.mark.posix_only
async def test_a_failing_command_gets_a_fixed_401_and_is_not_rerun_for_30_seconds(
    upstream: _RecordingUpstream,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capfd: pytest.CaptureFixture[str],
) -> None:
    assert shim_module._CREDENTIAL_FAILURE_TTL_S == 30.0
    credential, counter = _counted_credential(
        tmp_path, 'printf %s "$FAKE_UPSTREAM_KEY"; printf %s "$FAKE_UPSTREAM_KEY" >&2; exit 3'
    )
    async with _running_shim(f"http://127.0.0.1:{upstream.port}", credential) as shim:
        first = await _send(shim, _token_headers(shim))
        cached_failure = await _send(shim, _token_headers(shim))
        monkeypatch.setattr(shim_module, "_CREDENTIAL_FAILURE_TTL_S", 0.0)
        cached_failure_expired = await _send(shim, _token_headers(shim))
    for response in (first, cached_failure, cached_failure_expired):
        assert response.status_code == 401
        assert response.json()["error"] == {
            "type": "authentication_error",
            "message": "the model credential helper failed",
        }
    assert _runs(counter) == 2
    assert upstream.requests == []
    assert _FAKE_KEY not in capfd.readouterr().err  # the command's stderr is discarded


@pytest.mark.asyncio
@pytest.mark.posix_only
async def test_the_command_runs_under_sh_in_its_own_group_from_home_with_the_snapshot_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("HARNESS_ONLY_SETTING", "harness")
    command = (
        'group=$(ps -o pgid= -p $$ | tr -d " "); '
        '[ "$group" = "$$" ] && own=own-group || own=shared-group; '
        'printf "%s|%s|%s|%s|%s" "$0" "$(pwd -P)" "$own" "$SNAPSHOT_SETTING" '
        '"${HARNESS_ONLY_SETTING:-absent}"'
    )
    credential, _ = _counted_credential(tmp_path, command, SNAPSHOT_SETTING="snapshot")
    assert (await credential.get()).split("|") == [
        "/bin/sh",
        str(home.resolve()),
        "own-group",
        "snapshot",
        "absent",
    ]


@pytest.mark.asyncio
@pytest.mark.posix_only
async def test_a_command_past_its_timeout_is_killed_with_its_process_group(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert shim_module._CREDENTIAL_COMMAND_TIMEOUT_S == 600.0
    monkeypatch.setattr(shim_module, "_CREDENTIAL_COMMAND_TIMEOUT_S", 1.0)
    pid_file = tmp_path / "background.pid"
    credential, _ = _counted_credential(
        tmp_path, 'sleep 60 & printf %s $! > "$PID_FILE"; wait', PID_FILE=str(pid_file)
    )
    with pytest.raises(UpstreamCredentialError, match=r"\(TimeoutError\)$"):
        await credential.get()
    background = int(pid_file.read_text())
    with contextlib.suppress(psutil.NoSuchProcess):
        psutil.Process(background).wait(timeout=5)
    assert not psutil.pid_exists(background) or (
        psutil.Process(background).status() == psutil.STATUS_ZOMBIE
    )


@pytest.mark.asyncio
@pytest.mark.posix_only
async def test_command_output_over_64_kib_is_refused_without_waiting_for_its_end(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert shim_module._CREDENTIAL_STDOUT_CAP_BYTES == 64 * 1024
    monkeypatch.setattr(shim_module, "_CREDENTIAL_COMMAND_TIMEOUT_S", 5.0)
    # stdout stays open after the flood, so only a cap that stops reading answers before 5 s.
    credential, _ = _counted_credential(tmp_path, "head -c 70000 /dev/zero | tr '\\0' a; sleep 60")
    with pytest.raises(UpstreamCredentialError) as raised:
        await credential.get()
    assert str(raised.value) == "the model credential helper failed (UpstreamCredentialError)"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("value", "accepted"),
    [
        (f"{_FAKE_KEY}\n", True),
        (f"  {_FAKE_KEY}\t", True),
        ("k" * 4096, True),
        ("k" * 4097, False),
        (f"{_FAKE_KEY}\nsecond-line", False),
        (f"{_FAKE_KEY} with-space", False),
        (f"{_FAKE_KEY}é", False),
        (f"{_FAKE_KEY}\x7f", False),
        ("", False),
    ],
    ids=[
        "trailing-newline",
        "padded",
        "4-kib",
        "over-4-kib",
        "newline",
        "space",
        "non-ascii",
        "delete-char",
        "empty",
    ],
)
async def test_credential_values_must_be_one_printable_ascii_token_of_at_most_4_kib(
    value: str, accepted: bool
) -> None:
    credential = _literal_credential(value)
    if accepted:
        assert await credential.get() == value.strip()
        return
    with pytest.raises(UpstreamCredentialError) as raised:
        await credential.get()
    assert str(raised.value) == "the model credential is not one printable token of at most 4 KiB"


@pytest.mark.asyncio
async def test_a_newline_bearing_key_leaves_no_value_in_the_response_or_debug_logs(
    upstream: _RecordingUpstream, caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    tail = f"tail-{secrets.token_hex(8)}"
    credential = _literal_credential(f"{_FAKE_KEY}\n{tail}")
    async with _running_shim(f"http://127.0.0.1:{upstream.port}", credential) as shim:
        _debug_every_http_logger(caplog, monkeypatch)
        assert shim.session_token is not None
        response = await _send(shim, _token_headers(shim))
        token = shim.session_token
    assert response.status_code == 401
    assert upstream.requests == []
    assert _leaked({"key": _FAKE_KEY, "tail": tail, "token": token}, response.text, caplog) == []


@pytest.mark.asyncio
async def test_a_proxy_failure_with_userinfo_leaves_no_value_in_the_502_or_debug_logs(
    upstream: _RecordingUpstream, caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    password = f"proxy-pass-{secrets.token_hex(8)}"
    basic = base64.b64encode(f"proxy-user:{password}".encode()).decode()
    # Port 9 (discard) on loopback is closed, so the proxy hop fails.
    proxy = f"http://proxy-user:{password}@127.0.0.1:9"
    async with _running_shim(
        f"http://127.0.0.1:{upstream.port}", _literal_credential(), upstream_proxy=proxy
    ) as shim:
        _debug_every_http_logger(caplog, monkeypatch)
        response = await _send(shim, _token_headers(shim))
        token = shim.session_token
    assert response.status_code == 502
    assert response.json()["error"]["type"] == "api_error"
    assert upstream.requests == []
    assert token is not None
    leaked = _leaked(
        {"key": _FAKE_KEY, "password": password, "basic": basic, "token": token},
        response.text,
        caplog,
    )
    assert leaked == []


@pytest.mark.asyncio
async def test_the_upstream_client_logs_nothing_below_warning_in_credential_mode(
    upstream: _RecordingUpstream, caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    def upstream_records() -> list[str]:
        port = str(upstream.port)
        return [
            record.name
            for record in caplog.records
            if record.name.startswith(("httpx", "httpcore")) and port in record.getMessage()
        ]

    async with _running_shim(f"http://127.0.0.1:{upstream.port}", None) as plain:
        _debug_every_http_logger(caplog, monkeypatch)
        assert (await _send(plain, [])).status_code == 200
    assert "httpx" in upstream_records()  # the plain shim's client logs its request line
    caplog.clear()
    async with _running_shim(f"http://127.0.0.1:{upstream.port}", _literal_credential()) as shim:
        _debug_every_http_logger(caplog, monkeypatch)
        assert (await _send(shim, _token_headers(shim))).status_code == 200
    assert upstream_records() == []


@pytest.mark.asyncio
async def test_the_upstream_proxy_option_carries_requests_and_its_credentials() -> None:
    proxy = _RecordingUpstream(http="h11")  # h11 keeps the absolute-form target a proxy sees
    await proxy.start()
    try:
        password = f"proxy-pass-{secrets.token_hex(8)}"
        async with _running_shim(
            "http://127.0.0.1:9/base",
            _literal_credential(),
            upstream_proxy=f"http://proxy-user:{password}@127.0.0.1:{proxy.port}",
        ) as shim:
            response = await _send(shim, _token_headers(shim), method="GET", path="/v1/models")
    finally:
        await proxy.stop()
    assert response.json() == {"upstream": "ok"}
    assert [request.raw_path for request in proxy.requests] == [
        b"http://127.0.0.1:9/base/v1/models"
    ]
    expected = base64.b64encode(f"proxy-user:{password}".encode()).decode()
    assert proxy.requests[0].headers.get("proxy-authorization") == f"Basic {expected}"
    assert proxy.requests[0].headers.get("x-api-key") == _FAKE_KEY


class _ModelsHandler(BaseHTTPRequestHandler):
    """Answers ``GET /v1/models`` over TLS for the CA-file test."""

    def do_GET(self) -> None:
        self.send_response(200)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", "2")
        self.end_headers()
        self.wfile.write(b"{}")

    def log_message(self, format: str, *args: object) -> None:
        """Keep the test output quiet."""


@pytest.mark.asyncio
async def test_the_upstream_ca_file_extends_default_trust_and_fails_closed(tmp_path: Path) -> None:
    server = ThreadingHTTPServer(("127.0.0.1", 0), _ModelsHandler)
    ca_file = enable_https(server, tmp_path / "tls")["SSL_CERT_FILE"]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    upstream_url = f"https://localhost:{server.server_address[1]}"
    try:
        async with _running_shim(
            upstream_url, _literal_credential(), upstream_ca_file=ca_file
        ) as shim:
            trusted = await _send(shim, _token_headers(shim), method="GET", path="/v1/models")
        async with _running_shim(upstream_url, _literal_credential()) as shim:
            untrusted = await _send(shim, _token_headers(shim), method="GET", path="/v1/models")
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
    assert (trusted.status_code, untrusted.status_code) == (200, 502)
    default_roots = len(httpx.create_ssl_context().get_ca_certs())
    assert len(shim_module._upstream_ssl_context(ca_file).get_ca_certs()) == default_roots + 1
    for unusable in (tmp_path / "missing.pem", tmp_path / "empty.pem"):
        if unusable.name == "empty.pem":
            unusable.write_text("")
        shim = ClaudeGatewayShim(
            upstream_url, credential=_literal_credential(), upstream_ca_file=str(unusable)
        )
        with pytest.raises(OSError, match=r"could not configure its upstream client \(\w+\)$"):
            await shim.start()
        await shim.aclose()


# CORAL(S125): a caller that chose the proxy from the user's settings, or chose none, is not
# overruled by a proxy the harness's environment names.
@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("chosen", "env_proxies", "plain", "through"),
    [
        (None, True, False, "environment.example"),
        (None, None, False, "environment.example"),  # not said: as before the option
        (None, False, False, None),
        ("http://chosen.example:3128", False, False, "chosen.example"),
        (None, False, True, None),  # a shim with no credential is told the same way
    ],
    ids=["environment-decides", "unsaid", "none-chosen", "proxy-chosen", "none-chosen-plain"],
)
async def test_an_upstream_client_told_its_proxy_takes_none_from_the_environment(
    monkeypatch: pytest.MonkeyPatch,
    chosen: str | None,
    env_proxies: bool | None,
    plain: bool,
    through: str | None,
) -> None:
    for name in ("HTTPS_PROXY", "https_proxy", "ALL_PROXY", "all_proxy", "NO_PROXY", "no_proxy"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("HTTPS_PROXY", "http://environment.example:3128")
    said = {} if env_proxies is None else {"upstream_env_proxies": env_proxies}
    shim = ClaudeGatewayShim(
        "https://gateway.example/anthropic",
        credential=None if plain else _literal_credential(),
        upstream_proxy=chosen,
        **said,
    )
    # Never contacted: only the client's route to this upstream is read.
    client = shim._new_upstream_client()
    try:
        route = client._transport_for_url(httpx.URL("https://gateway.example/anthropic"))
        proxy_url = getattr(route._pool, "_proxy_url", None)  # type: ignore[attr-defined]
        routed_through = None if proxy_url is None else proxy_url.host.decode("ascii")
    finally:
        await client.aclose()
        await shim.aclose()

    assert routed_through == through


@pytest.mark.asyncio
async def test_the_listening_log_line_drops_userinfo_and_query(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO, logger="omnigent")
    password = f"pass-{secrets.token_hex(8)}"
    query = f"query-{secrets.token_hex(8)}"
    async with _running_shim(f"http://user:{password}@127.0.0.1:9/base?token={query}", None):
        pass
    lines = [r.getMessage() for r in caplog.records if "listening on" in r.getMessage()]
    assert len(lines) == 1 and lines[0].endswith("→ http://127.0.0.1:9/base")
    assert password not in lines[0] and query not in lines[0]


_Answer = Callable[[dict[str, str], asyncio.StreamWriter], Awaitable[None]]


@contextlib.asynccontextmanager
async def _scripted_upstream(answer: _Answer) -> AsyncIterator[tuple[str, list[dict[str, str]]]]:
    """A raw loopback upstream: records each request's headers and lets *answer* write the reply.

    :returns: The base URL and the recorded request headers (lower-cased names), one per request.
    """
    seen: list[dict[str, str]] = []

    async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            head = (await reader.readuntil(b"\r\n\r\n")).decode("latin-1")
            pairs = (line.partition(":") for line in head.split("\r\n")[1:] if line)
            headers = {name.strip().lower(): value.strip() for name, _, value in pairs}
            await reader.readexactly(int(headers.get("content-length", "0")))
            seen.append(headers)
            await answer(headers, writer)
        except (asyncio.IncompleteReadError, ConnectionError):
            pass
        finally:
            writer.close()

    server = await asyncio.start_server(handle, "127.0.0.1", 0)
    try:
        yield f"http://127.0.0.1:{server.sockets[0].getsockname()[1]}", seen
    finally:
        server.close()
        await server.wait_closed()


def _sse_chunk(event: bytes) -> bytes:
    """One chunked-encoding frame holding *event*."""
    return b"%x\r\n%s\r\n" % (len(event), event)


_SSE_HEAD = (
    b"HTTP/1.1 200 OK\r\ncontent-type: text/event-stream\r\ntransfer-encoding: chunked\r\n\r\n"
)


def _assert_gone(pid: int) -> None:
    """Fail when *pid* outlives its command's group kill, killing it so nothing leaks."""
    with contextlib.suppress(psutil.NoSuchProcess, psutil.TimeoutExpired):
        psutil.Process(pid).wait(timeout=5)
    with contextlib.suppress(psutil.NoSuchProcess):
        survivor = psutil.Process(pid)
        if survivor.status() != psutil.STATUS_ZOMBIE:
            survivor.kill()
            raise AssertionError("a background child outlived its command's group kill")


@pytest.mark.asyncio
async def test_a_credential_shim_still_restores_opus_thinking_display(
    upstream: _RecordingUpstream,
) -> None:
    body = _body("databricks-claude-opus-4-8", {"type": "adaptive"})
    async with _running_shim(f"http://127.0.0.1:{upstream.port}", _literal_credential()) as shim:
        response = await _send(shim, _token_headers(shim), body=body)
    assert response.text == "event: ping\ndata: {}\n\ndata: [DONE]\n\n"
    thinking = json.loads(upstream.requests[0].body)["thinking"]
    assert thinking == {"type": "adaptive", "display": "summarized"}


@pytest.mark.asyncio
async def test_an_upstream_redirect_is_relayed_and_never_followed(
    upstream: _RecordingUpstream,
) -> None:
    async def redirect(headers: dict[str, str], writer: asyncio.StreamWriter) -> None:
        location = f"http://127.0.0.1:{upstream.port}/v1/models"
        writer.write(f"HTTP/1.1 307 Temporary Redirect\r\nlocation: {location}\r\n".encode())
        writer.write(b"content-length: 0\r\nconnection: close\r\n\r\n")
        await writer.drain()

    async with _scripted_upstream(redirect) as (url, seen):
        async with _running_shim(url, _literal_credential()) as shim:
            response = await _send(shim, _token_headers(shim), method="GET", path="/v1/models")
    assert response.status_code == 307
    assert len(seen) == 1 and upstream.requests == []  # the key never went to the new location


@pytest.mark.asyncio
async def test_an_upstream_failing_mid_stream_ends_the_cli_stream_without_values(
    caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    event = b"event: ping\n\n"

    async def break_off(headers: dict[str, str], writer: asyncio.StreamWriter) -> None:
        writer.write(_SSE_HEAD + _sse_chunk(event))  # then the connection drops mid-body
        await writer.drain()

    received = bytearray()
    async with _scripted_upstream(break_off) as (url, seen):
        async with _running_shim(url, _literal_credential()) as shim:
            _debug_every_http_logger(caplog, monkeypatch)
            token = shim.session_token
            async with httpx.AsyncClient(trust_env=False) as client:
                with pytest.raises(httpx.TransportError):
                    async with client.stream(
                        "POST",
                        f"{shim.base_url}/v1/messages",
                        headers=_token_headers(shim),
                        content=_body("claude-test-model", None),
                    ) as response:
                        async for chunk in response.aiter_raw():
                            received.extend(chunk)
    assert (response.status_code, bytes(received)) == (200, event)
    assert seen[0]["x-api-key"] == _FAKE_KEY
    failures = [
        record.getMessage()
        for record in caplog.records
        if record.name == shim_module.__name__ and record.levelno >= logging.ERROR
    ]
    assert len(failures) == 1
    assert re.fullmatch(r"Claude credential proxy request failed \(\w+\)", failures[0])
    assert token is not None
    assert _leaked({"key": _FAKE_KEY, "token": token}, "", caplog) == []


@pytest.mark.asyncio
async def test_a_cli_leaving_mid_stream_leaves_the_shim_serving_and_logs_no_value(
    caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    event = b"data: {}\n\n"

    async def stream_events(headers: dict[str, str], writer: asyncio.StreamWriter) -> None:
        writer.write(_SSE_HEAD)
        for _ in range(20):
            writer.write(_sse_chunk(event))
            await writer.drain()
            await asyncio.sleep(0.01)
        writer.write(b"0\r\n\r\n")
        await writer.drain()

    first = b""
    async with _scripted_upstream(stream_events) as (url, seen):
        async with _running_shim(url, _literal_credential()) as shim:
            _debug_every_http_logger(caplog, monkeypatch)
            token = shim.session_token
            async with httpx.AsyncClient(trust_env=False) as client:
                async with client.stream(
                    "POST",
                    f"{shim.base_url}/v1/messages",
                    headers=_token_headers(shim),
                    content=_body("claude-test-model", None),
                ) as left:
                    async for first in left.aiter_raw():
                        break  # the CLI hangs up after the first event
            after = await _send(shim, _token_headers(shim))
    assert first.startswith(event)
    assert (after.status_code, after.content, len(seen)) == (200, event * 20, 2)
    errors = [
        record.getMessage()
        for record in caplog.records
        if record.name.startswith(("omnigent", "uvicorn")) and record.levelno >= logging.ERROR
    ]
    assert errors == []
    assert token is not None
    assert _leaked({"key": _FAKE_KEY, "token": token}, after.text, caplog) == []


@pytest.mark.asyncio
async def test_upstream_error_text_holding_the_key_reaches_neither_the_cli_nor_the_logs(
    caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def echo_in_status_line(headers: dict[str, str], writer: asyncio.StreamWriter) -> None:
        writer.write(f"HTTP/1.1 2x0 {headers.get('x-api-key')}\r\n\r\n".encode())  # malformed
        await writer.drain()

    async with _scripted_upstream(echo_in_status_line) as (url, seen):
        async with _running_shim(url, _literal_credential()) as shim:
            _debug_every_http_logger(caplog, monkeypatch)
            response = await _send(shim, _token_headers(shim))
            token = shim.session_token
    assert seen[0]["x-api-key"] == _FAKE_KEY  # the upstream's reply did carry the key
    assert response.status_code == 502
    assert re.fullmatch(
        r"credential proxy upstream error \(\w+\)", response.json()["error"]["message"]
    )
    assert token is not None
    assert _leaked({"key": _FAKE_KEY, "token": token}, response.text, caplog) == []


@pytest.mark.asyncio
@pytest.mark.posix_only
async def test_requests_arriving_during_a_refresh_share_its_one_command_run(
    upstream: _RecordingUpstream, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    started, release = tmp_path / "refresh-started", tmp_path / "refresh-release"
    # The first run prints the stale key; the refresh run holds until the test releases it.
    command = (
        'if [ "$(cat "$RUN_COUNTER")" = x ]; then printf %s "$STALE_KEY"; else '
        ': > "$STARTED"; while [ ! -e "$RELEASE" ]; do sleep 0.05; done; '
        'printf %s "$FAKE_UPSTREAM_KEY"; fi'
    )
    credential, counter = _counted_credential(
        tmp_path, command, STALE_KEY=_FAKE_STALE_KEY, STARTED=str(started), RELEASE=str(release)
    )
    upstream.rejected_credentials.add(_FAKE_STALE_KEY)
    calls = 0
    real_get = credential.get

    async def counted_get() -> str:
        nonlocal calls
        calls += 1
        return await real_get()

    monkeypatch.setattr(credential, "get", counted_get)
    async with _running_shim(f"http://127.0.0.1:{upstream.port}", credential) as shim:
        requests = [asyncio.create_task(_send(shim, _token_headers(shim)))]
        try:
            await poll_until_async(lambda: started.exists() or requests[0].done())
            requests += [asyncio.create_task(_send(shim, _token_headers(shim))) for _ in range(4)]
            await poll_until_async(lambda: calls == 6)  # 2 by the refreshing request, 4 waiting
        finally:
            release.touch()
            responses = await asyncio.gather(*requests)
    assert [response.status_code for response in responses] == [200] * 5
    assert _runs(counter) == 2
    keys = [request.headers["x-api-key"] for request in upstream.requests]
    assert keys == [_FAKE_STALE_KEY] + [_FAKE_KEY] * 5


@pytest.mark.asyncio
@pytest.mark.posix_only
async def test_callers_that_leave_during_a_command_run_do_not_restart_it(tmp_path: Path) -> None:
    started, release = tmp_path / "run-started", tmp_path / "run-release"
    credential, counter = _counted_credential(
        tmp_path,
        ': > "$STARTED"; while [ ! -e "$RELEASE" ]; do sleep 0.05; done; '
        'printf %s "$FAKE_UPSTREAM_KEY"',
        STARTED=str(started),
        RELEASE=str(release),
    )
    try:
        # Each caller leaves once the command is running, as a CLI that drops its request does.
        for _ in range(5):
            caller = asyncio.create_task(credential.get())
            await poll_until_async(started.exists)
            caller.cancel()
            with pytest.raises(asyncio.CancelledError):
                await caller
        stayed = asyncio.create_task(credential.get())
    finally:
        release.touch()
    assert await asyncio.wait_for(stayed, timeout=10) == _FAKE_KEY
    assert await credential.get() == _FAKE_KEY  # served from the cache
    assert _runs(counter) == 1


@pytest.mark.asyncio
@pytest.mark.posix_only
async def test_values_and_failures_stay_cached_until_their_ttls_pass(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert shim_module._DEFAULT_CREDENTIAL_TTL_S == 900.0
    now = [1000.0]
    monkeypatch.setattr(shim_module, "time", SimpleNamespace(monotonic=lambda: now[0]))
    for name in ("value", "failure"):
        (tmp_path / name).mkdir()
    value, value_runs = _counted_credential(tmp_path / "value")
    failure, failure_runs = _counted_credential(tmp_path / "failure", "exit 3")
    observed = []
    for elapsed in (0.0, 29.9, 0.2, 869.8, 0.2):  # at 0, 29.9, 30.1, 899.9 and 900.1 s
        now[0] += elapsed
        assert await value.get() == _FAKE_KEY
        with pytest.raises(UpstreamCredentialError):
            await failure.get()
        observed.append((_runs(value_runs), _runs(failure_runs)))
    assert observed == [(1, 1), (1, 1), (1, 2), (1, 3), (2, 3)]


@pytest.mark.asyncio
@pytest.mark.posix_only
async def test_a_command_value_is_checked_and_its_env_is_the_snapshot_at_construction() -> None:
    snapshot = {"PATH": "/usr/bin:/bin", "FAKE_UPSTREAM_KEY": _FAKE_KEY}
    echoed = UpstreamCredential('echo "$FAKE_UPSTREAM_KEY"', ttl_s=None, env=snapshot)
    snapshot["FAKE_UPSTREAM_KEY"] = f"sk-ant-test-later-{secrets.token_hex(8)}"
    assert await echoed.get() == _FAKE_KEY  # newline stripped, later changes not seen
    two_lines = UpstreamCredential(
        'printf "%s\\nsecond-line" "$FAKE_UPSTREAM_KEY"', ttl_s=None, env=snapshot
    )
    with pytest.raises(UpstreamCredentialError) as raised:
        await two_lines.get()
    assert str(raised.value) == "the model credential helper failed (UpstreamCredentialError)"


@pytest.mark.asyncio
@pytest.mark.posix_only
@pytest.mark.parametrize("ending", ["closed", "flooded"])
async def test_a_closed_or_flooding_command_loses_its_hanging_child(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, ending: str
) -> None:
    monkeypatch.setattr(shim_module, "_CREDENTIAL_COMMAND_TIMEOUT_S", 30.0)
    pid_file = tmp_path / "background.pid"
    flood = "head -c 70000 /dev/zero | tr '\\0' a; " if ending == "flooded" else ""
    credential, _ = _counted_credential(
        tmp_path, f'sleep 60 & printf %s $! > "$PID_FILE"; {flood}wait', PID_FILE=str(pid_file)
    )
    getting = asyncio.create_task(credential.get())
    await poll_until_async(lambda: pid_file.exists() and pid_file.read_text() != "")
    if ending == "closed":
        # The run outlives a caller that leaves; closing the credential is what stops it.
        await credential.aclose()
        with pytest.raises(asyncio.CancelledError):
            await getting
    else:
        with pytest.raises(UpstreamCredentialError, match=r"\(UpstreamCredentialError\)$"):
            await getting
    _assert_gone(int(pid_file.read_text()))


@pytest.mark.asyncio
async def test_a_body_over_the_cap_is_refused_before_the_rest_of_it_arrives(
    upstream: _RecordingUpstream, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(shim_module, "_MAX_REQUEST_BODY_BYTES", 1024)
    credential, counter = _counted_credential(tmp_path)
    async with _running_shim(f"http://127.0.0.1:{upstream.port}", credential) as shim:
        assert shim._port is not None and shim.session_token is not None
        # 4 KiB of a declared 64 MiB body: only a shim that stops at the cap can answer.
        status = await _raw_status(
            shim._port,
            "/v1/messages",
            shim.session_token,
            body=b"x" * 4096,
            declared_length=64 * 1024 * 1024,
        )
    assert status == 413
    assert upstream.requests == [] and _runs(counter) == 0


@pytest.mark.asyncio
async def test_a_credential_shim_relays_each_sse_event_as_it_arrives() -> None:
    first, rest = b"event: ping\ndata: {}\n\n", b"data: [DONE]\n\n"
    first_relayed = asyncio.Event()

    async def hold_after_first(headers: dict[str, str], writer: asyncio.StreamWriter) -> None:
        writer.write(_SSE_HEAD + _sse_chunk(first))
        await writer.drain()
        await first_relayed.wait()  # only an unbuffered relay hands the CLI the first event now
        writer.write(_sse_chunk(rest) + b"0\r\n\r\n")
        await writer.drain()

    async with _scripted_upstream(hold_after_first) as (url, _):
        try:
            async with (
                _running_shim(url, _literal_credential()) as shim,
                httpx.AsyncClient(trust_env=False) as client,
                client.stream(
                    "POST",
                    f"{shim.base_url}/v1/messages",
                    headers=_token_headers(shim),
                    content=_body("claude-test-model", None),
                ) as response,
            ):
                chunks = response.aiter_raw()
                head = await asyncio.wait_for(anext(chunks), timeout=10)
                first_relayed.set()
                tail = b"".join([chunk async for chunk in chunks])
        finally:
            first_relayed.set()  # a buffering relay must not leave the upstream waiting
    assert response.headers["content-type"] == "text/event-stream"
    assert (head, tail) == (first, rest)


@pytest.mark.asyncio
async def test_a_cli_leaving_mid_stream_closes_the_upstream_response_early() -> None:
    total, written = 250, [0]
    upstream_done = asyncio.Event()

    async def long_stream(headers: dict[str, str], writer: asyncio.StreamWriter) -> None:
        try:
            writer.write(_SSE_HEAD)
            for _ in range(total):
                writer.write(_sse_chunk(b"data: {}\n\n"))
                await writer.drain()  # raises once the shim has closed the connection
                written[0] += 1
                await asyncio.sleep(0.02)
            writer.write(b"0\r\n\r\n")
            await writer.drain()
        finally:
            upstream_done.set()

    async with _scripted_upstream(long_stream) as (url, seen):
        async with _running_shim(url, _literal_credential()) as shim:
            async with (
                httpx.AsyncClient(trust_env=False) as client,
                client.stream(
                    "POST",
                    f"{shim.base_url}/v1/messages",
                    headers=_token_headers(shim),
                    content=_body("claude-test-model", None),
                ) as response,
            ):
                async for _ in response.aiter_raw():
                    break  # the CLI hangs up after the first event
            await poll_until_async(upstream_done.is_set)
    assert len(seen) == 1
    assert written[0] < total // 2, "the shim kept reading the upstream after the CLI left"


@pytest.mark.asyncio
@pytest.mark.posix_only
async def test_closing_the_shim_kills_a_credential_command_still_running(
    upstream: _RecordingUpstream, tmp_path: Path
) -> None:
    pid_file = tmp_path / "background.pid"
    credential, _ = _counted_credential(
        tmp_path, 'sleep 60 & printf %s $! > "$PID_FILE"; wait', PID_FILE=str(pid_file)
    )
    shim = ClaudeGatewayShim(f"http://127.0.0.1:{upstream.port}", credential=credential)
    await shim.start()
    try:
        request = asyncio.create_task(_send(shim, _token_headers(shim)))
        await poll_until_async(
            lambda: (pid_file.exists() and pid_file.read_text() != "") or request.done()
        )
        assert not request.done()
    finally:
        await shim.aclose()
    _assert_gone(int(pid_file.read_text()))
    response = await asyncio.wait_for(request, timeout=10)
    assert response.status_code == 502 and upstream.requests == []
