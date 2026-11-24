"""Local HTTP shim that restores request fields the Claude CLI strips.

Claude Code CLIs from 2.1.168 (and likely earlier 2.1.16x) drop the
``thinking.display`` field from ``POST /v1/messages`` bodies whenever
experimental betas are disabled — the request builder gates ``display``
on the same internal flag as the experimental beta headers. The
Databricks Unity Gateway path must set
``CLAUDE_CODE_DISABLE_EXPERIMENTAL_BETAS=1`` (the gateway's beta
allowlist rejects several of the CLI's experimental betas with HTTP
400 "invalid beta flag"), so gateway Opus requests lose ``display``
and fall back to the Opus 4.7+ model default of ``display="omitted"``:
the thinking block opens, every delta is empty, and no thoughts ever
stream. Sonnet's default keeps thinking visible, which is why only
Opus appeared broken. The Messages API itself accepts ``display``
with no beta header at all, so re-applying it at the HTTP boundary is
safe and changes nothing else about the request.

The shim binds an ephemeral port on ``127.0.0.1``; the executor points
``ANTHROPIC_BASE_URL`` at it. Qualifying ``/v1/messages`` bodies get
``display="summarized"`` re-injected; every other request — and every
response, including SSE streams — is forwarded verbatim and unbuffered.

One shim runs per
:class:`~omnigent.inner.claude_sdk_executor.ClaudeSDKExecutor`,
started lazily with the first gateway client and stopped by the
executor's ``close()`` (or with the harness subprocess, whichever
comes first).

CORAL(S118): given an :class:`UpstreamCredential`, the shim is a narrow
credential proxy. The CLI holds only :attr:`ClaudeGatewayShim.session_token`;
the shim checks it, forwards the four model routes only, and puts the real
credential in the header form the CLI used. Errors and logs name exception
types only.
"""

from __future__ import annotations

import asyncio
import contextlib
import hmac  # CORAL(S118)
import json
import logging
import re  # CORAL(S118)
import secrets  # CORAL(S118)
import shlex  # CORAL(S118)
import ssl  # CORAL(S118)
import time  # CORAL(S118)
from collections.abc import Awaitable, Callable, Iterator, Mapping, MutableMapping
from contextvars import ContextVar  # CORAL(S118)
from pathlib import Path  # CORAL(S118)
from typing import Any, TypeAlias
from urllib.parse import urlsplit  # CORAL(S118)

import httpx
import uvicorn

from omnigent.databricks_ai_gateway import (
    CLAUDE_CODE_AGENT,
    is_databricks_ai_gateway_url,
    is_ug_route,
    with_gateway_attribution_pairs,
)
from omnigent.inner import _proc  # CORAL(S118)
from omnigent.inner._subprocess_lifecycle import close_subprocess_transport  # CORAL(S118)
from omnigent.telemetry.surface import harness_client_surface

logger = logging.getLogger(__name__)


class _NoSignalServer(uvicorn.Server):
    """
    uvicorn Server that never installs process signal handlers.

    ``uvicorn.Server.serve()`` replaces the process's SIGINT/SIGTERM
    handlers for its whole lifetime when run on the main thread. The
    harness subprocess already runs its own uvicorn server whose
    graceful shutdown is driven by SIGTERM (see
    ``omnigent/runtime/harnesses/_runner.py``); a second
    signal-capturing server would steal those handlers and break the
    harness's shutdown path. The shim is stopped explicitly via
    :meth:`ClaudeGatewayShim.aclose` (or dies with the process), so it
    needs no signal handling of its own.
    """

    @contextlib.contextmanager
    def capture_signals(self) -> Iterator[None]:
        """No-op replacement for uvicorn's signal-handler swap."""
        yield


# Databricks-hosted Claude model ids that default to
# ``thinking.display="omitted"`` — Opus 4.7+ (e.g.
# ``databricks-claude-opus-4-8``) and Fable, which shares Opus's
# adaptive-only thinking surface. Both the legacy serving-endpoint
# spelling (``databricks-claude-opus-*``) and the Unity Catalog spelling
# (``system.ai.claude-opus-*``) name the same Databricks-hosted tiers.
# Sonnet/Haiku stream visible thinking without a display field, so the
# shim leaves them untouched.
DATABRICKS_CLAUDE_ADAPTIVE_THINKING_PREFIXES: tuple[str, ...] = (
    "databricks-claude-opus-",
    "databricks-claude-fable-",
    "system.ai.claude-opus-",
    "system.ai.claude-fable-",
)

# Hop-by-hop headers (RFC 9110 §7.6.1) must not be forwarded by an
# intermediary; httpx/uvicorn manage their own connection framing.
_HOP_BY_HOP_HEADERS = frozenset(
    {
        "connection",
        "keep-alive",
        "proxy-authenticate",
        "proxy-authorization",
        "te",
        "trailer",
        "transfer-encoding",
        "upgrade",
    }
)

# Request headers never forwarded upstream: hop-by-hop framing plus
# ``host`` (belongs to the upstream) and ``content-length`` (recomputed
# by httpx after the body patch changes its size).
_REQUEST_HEADER_EXCLUDES = _HOP_BY_HOP_HEADERS | {"host", "content-length"}

# How long to wait for the in-process uvicorn server to bind before
# failing the turn. Binding a localhost ephemeral port is near-instant;
# 10s only guards against a pathologically wedged event loop.
_START_TIMEOUT_SECONDS = 10.0

# Upstream timeout: ``read=None`` because /v1/messages SSE streams can
# legitimately idle between deltas for minutes on long thinking turns;
# the CLI applies its own request-level timeout.
_UPSTREAM_TIMEOUT = httpx.Timeout(connect=30.0, read=None, write=60.0, pool=None)

# ASGI callable types — uvicorn's protocol is untyped dicts.
_Scope: TypeAlias = MutableMapping[str, Any]  # type: ignore[explicit-any]  # ASGI scope is a heterogeneous dict by spec
_Receive: TypeAlias = Callable[[], Awaitable[MutableMapping[str, Any]]]  # type: ignore[explicit-any]  # ASGI message dicts
_Send: TypeAlias = Callable[[MutableMapping[str, Any]], Awaitable[None]]  # type: ignore[explicit-any]  # ASGI message dicts

# CORAL(S118): bounds of the credential proxy. h11 caps a request head at 16 KiB and the token is
# checked before any body is read, so a client without it holds little memory. No connection
# limit: idle unauthenticated sockets would fill it and refuse the CLI.
_CREDENTIAL_PROXY_HTTP_PARSER = "h11"
_MAX_REQUEST_BODY_BYTES = 32 * 1024 * 1024
_REFRESH_MIN_INTERVAL_S = 30.0
# The helper refresh interval the CLI applied (claude_sdk_executor._GATEWAY_AUTH_REFRESH_MS).
_DEFAULT_CREDENTIAL_TTL_S = 900.0
_CREDENTIAL_FAILURE_TTL_S = 30.0
_CREDENTIAL_COMMAND_TIMEOUT_S = 600.0  # the CLI's own helper timeout
_CREDENTIAL_KILL_WAIT_S = 5.0
_CREDENTIAL_STDOUT_CAP_BYTES = 64 * 1024
_CREDENTIAL_VALUE_MAX_BYTES = 4 * 1024
_CREDENTIAL_HEADERS = frozenset({"x-api-key", "authorization"})
_FORWARDED_ROUTES = frozenset(
    {("POST", "/v1/messages"), ("POST", "/v1/messages/count_tokens"), ("GET", "/v1/models")}
)
_MODEL_ROUTE_PREFIX = "/v1/models/"  # GET /v1/models/<id>, one segment
_MODEL_ID = re.compile(rb"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}")
_UNSAFE_PATH_MARKERS = (b"@", b"\\", b"%2e", b"%2f", b"%5c", b"%40", b"%3f", b"%23")
# Headers an upstream gateway may route on; the CLI never needs them.
_REQUEST_OVERRIDE_HEADERS = frozenset(
    {
        "x-original-url",
        "x-rewrite-url",
        "x-http-method-override",
        "x-http-method",
        "x-method-override",
        "forwarded",
    }
)
_LOGGED_METHODS = frozenset({"GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"})
_UPSTREAM_CLIENT_LOGGERS = (
    "httpx",
    "httpcore.connection",
    "httpcore.http11",
    "httpcore.http2",
    "httpcore.proxy",
    "httpcore.socks",
)
_SERVING_CREDENTIAL_REQUEST: ContextVar[bool] = ContextVar(
    "claude_credential_proxy_request", default=False
)


class _QuietCredentialProxyClient(logging.Filter):
    """CORAL(S118): keep the upstream client's records below WARNING out of credential requests."""

    def filter(self, record: logging.LogRecord) -> bool:
        return record.levelno >= logging.WARNING or not _SERVING_CREDENTIAL_REQUEST.get()


_QUIET_CLIENT_FILTER = _QuietCredentialProxyClient()


def _quiet_upstream_client_logs() -> None:
    """CORAL(S118): install the filter once on every httpx and httpcore logger."""
    for name in _UPSTREAM_CLIENT_LOGGERS:
        client_logger = logging.getLogger(name)
        if _QUIET_CLIENT_FILTER not in client_logger.filters:
            client_logger.addFilter(_QUIET_CLIENT_FILTER)


def restore_thinking_display(body: bytes) -> bytes:
    """
    Re-inject ``thinking.display="summarized"`` into a Messages API body.

    No-op (returns ``body`` unchanged) unless the body is a JSON object
    whose ``model`` is a Databricks Claude Opus/Fable id, whose ``thinking``
    is a dict with a non-``"disabled"`` type, and whose ``thinking``
    lacks a ``display`` key. A present ``display`` is always respected
    so a future CLI that forwards the field again makes this a no-op.

    :param body: Raw request body bytes, e.g.
        ``b'{"model": "databricks-claude-opus-4-8", "thinking":
        {"type": "adaptive"}, ...}'``.
    :returns: The body with ``display`` injected, or the original
        bytes when the request doesn't qualify.
    """
    try:
        parsed = json.loads(body)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return body
    if not isinstance(parsed, dict):
        return body
    model = parsed.get("model")
    thinking = parsed.get("thinking")
    if (
        not isinstance(model, str)
        or not model.startswith(DATABRICKS_CLAUDE_ADAPTIVE_THINKING_PREFIXES)
        or not isinstance(thinking, dict)
        or thinking.get("type") == "disabled"
        or "display" in thinking
    ):
        return body
    thinking["display"] = "summarized"
    logger.debug("Restored thinking.display=summarized for model %s", model)
    return json.dumps(parsed).encode("utf-8")


# CORAL(S118): a shorter key also occurs in ordinary values (a placeholder "local" is in
# /usr/local/bin), so its copies are not searched for; a real provider key is far longer
MIN_SCANNED_LITERAL_CHARS = 20


def static_printf_value(command: str) -> str | None:
    """CORAL(S118): the literal a static-key credential command prints, else ``None``.

    Only the exact form written for a static key, ``"printf %s " + shlex.quote(value)``,
    is a literal; any other command, however close, has to run.

    :param command: A credential command, e.g. ``"printf %s sk-ant-..."``.
    :returns: The literal, possibly ``""``, or ``None`` for a command to run.
    """
    try:
        words = shlex.split(command)
    except ValueError:
        return None
    if len(words) != 3 or words[:2] != ["printf", "%s"]:
        return None
    return words[2] if command == f"printf %s {shlex.quote(words[2])}" else None


class UpstreamCredentialError(RuntimeError):
    """CORAL(S118): the model credential is unavailable; the message never holds a value."""


def _checked_credential(raw: str | bytes) -> str:
    """CORAL(S118): the stripped value when it is one printable ASCII token of at most 4 KiB.

    :raises UpstreamCredentialError: Otherwise, with a fixed message.
    """
    try:
        value = (raw.encode("utf-8") if isinstance(raw, str) else raw).strip()
    except UnicodeEncodeError:
        value = b""
    if (
        not value
        or len(value) > _CREDENTIAL_VALUE_MAX_BYTES
        or any(byte < 0x21 or byte > 0x7E for byte in value)
    ):
        raise UpstreamCredentialError(
            "the model credential is not one printable token of at most 4 KiB"
        )
    return value.decode("ascii")


def static_credential_literal(command: str) -> str | None:
    """CORAL(S118): the static key *command* holds, in the one form the proxy sends.

    Every search for copies of the key and every request that carries it uses this form, so
    a key configured with a trailing newline is still one key.

    :param command: A credential command, e.g. ``"printf %s sk-ant-..."``.
    :returns: The stripped key; ``None`` for a command to run, and for a literal that is
        not one printable token (the proxy refuses to send that).
    """
    literal = static_printf_value(command)
    if literal is None:
        return None
    try:
        return _checked_credential(literal)
    except UpstreamCredentialError:
        return None


async def _read_capped_stdout(process: asyncio.subprocess.Process) -> bytes:
    """CORAL(S118): the command's stdout to EOF, then its exit; refuses more than 64 KiB."""
    if process.stdout is None:
        raise UpstreamCredentialError("the model credential helper has no output")
    output = bytearray()
    while chunk := await process.stdout.read(_CREDENTIAL_STDOUT_CAP_BYTES + 1 - len(output)):
        output.extend(chunk)
        if len(output) > _CREDENTIAL_STDOUT_CAP_BYTES:
            raise UpstreamCredentialError("the model credential helper printed too much")
    await process.wait()
    return bytes(output)


async def _run_credential_command(command: str, env: Mapping[str, str]) -> bytes:
    """CORAL(S118): run *command* as the CLI ran its helper, outside the step's worktree.

    ``/bin/sh -c`` in its own session, from the user's home (a step cannot plant a relative
    helper there), stderr discarded; the whole group is killed on timeout or cancellation.

    :raises UpstreamCredentialError: When the command exits non-zero or prints too much.
    :raises TimeoutError: After ``_CREDENTIAL_COMMAND_TIMEOUT_S``.
    """
    process = await asyncio.create_subprocess_exec(
        "/bin/sh",
        "-c",
        command,
        stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
        env=dict(env),
        cwd=Path.home(),
        **_proc.spawn_kwargs(),
    )
    _proc.remember_process_group(process)
    try:
        output = await asyncio.wait_for(
            _read_capped_stdout(process), timeout=_CREDENTIAL_COMMAND_TIMEOUT_S
        )
    except BaseException as exc:
        _proc.kill_tree(process)
        if not isinstance(exc, asyncio.CancelledError):
            with contextlib.suppress(Exception):
                await asyncio.wait_for(process.wait(), timeout=_CREDENTIAL_KILL_WAIT_S)
        raise
    finally:
        close_subprocess_transport(process)
    if process.returncode != 0:
        raise UpstreamCredentialError("the model credential helper exited with an error")
    return output


class UpstreamCredential:
    """CORAL(S118): the real credential, held in the harness; the CLI only sees a session token.

    A static key (``printf %s <quoted key>``) is held as its value and needs no shell. Any other
    command runs through :func:`_run_credential_command` with the *env* snapshot the caller
    gives, one run at a time, cached for *ttl_s*; a failure is cached for 30 s. The run
    belongs to the credential, not to the request that started it: a caller that leaves
    abandons only its wait, so the run still finishes and is cached.

    :param command: The credential command the CLI's ``apiKeyHelper`` would have run.
    :param ttl_s: Seconds a command's value stays cached; ``None`` means 900 s.
    :param env: The environment the command runs with, e.g. the harness's pre-scrub snapshot.
    """

    def __init__(self, command: str, *, ttl_s: float | None, env: Mapping[str, str]) -> None:
        self._command = command
        self._literal = static_printf_value(command)
        self._env = dict(env)
        self._ttl_s = _DEFAULT_CREDENTIAL_TTL_S if ttl_s is None else ttl_s
        self._value: str | None = None
        self._expires_at = 0.0
        self._failed_at: float | None = None
        self._run: asyncio.Task[str] | None = None

    def __repr__(self) -> str:
        return f"UpstreamCredential(refreshable={self.refreshable})"

    @property
    def refreshable(self) -> bool:
        """Whether :meth:`invalidate` can yield a new value (``False`` for a static key)."""
        return self._literal is None

    async def get(self) -> str:
        """
        The credential value.

        :returns: The checked value, e.g. ``"sk-ant-..."``.
        :raises UpstreamCredentialError: When the value is malformed or the command failed,
            now or within the last 30 s; the message names exception types only.
        """
        if self._literal is not None:
            return _checked_credential(self._literal)
        if self._value is not None and time.monotonic() < self._expires_at:
            return self._value
        if (
            self._failed_at is not None
            and time.monotonic() - self._failed_at < _CREDENTIAL_FAILURE_TTL_S
        ):
            raise UpstreamCredentialError("the model credential helper failed recently")
        if self._run is None:
            self._run = asyncio.create_task(self._refresh())
            # every caller may have left; retrieve the outcome so it is never logged with a value
            self._run.add_done_callback(lambda run: run.cancelled() or run.exception())
        return await asyncio.shield(self._run)

    async def _refresh(self) -> str:
        """Run the command once, cache its value or its failure, and return the value."""
        try:
            value = _checked_credential(await _run_credential_command(self._command, self._env))
        except Exception as exc:  # noqa: BLE001 — any failure is reported by type name only
            self._failed_at = time.monotonic()
            logger.warning("Claude credential helper failed (%s)", type(exc).__name__)
            raise UpstreamCredentialError(
                f"the model credential helper failed ({type(exc).__name__})"
            ) from None
        finally:
            self._run = None
        self._value, self._failed_at = value, None
        self._expires_at = time.monotonic() + self._ttl_s
        return value

    async def aclose(self) -> None:
        """Stop a command run still in flight; its process group is killed."""
        run = self._run
        if run is None:
            return
        run.cancel()
        await asyncio.wait([run], timeout=_CREDENTIAL_KILL_WAIT_S)

    def invalidate(self) -> None:
        """Drop a cached command value so the next :meth:`get` runs the command again."""
        self._value = None


def _upstream_ssl_context(ca_file: str) -> ssl.SSLContext:
    """CORAL(S118): httpx's default trust plus *ca_file*; raises when the CA cannot load."""
    context = httpx.create_ssl_context()
    context.load_verify_locations(cafile=ca_file)
    return context


def _loggable_url(url: str) -> str:
    """CORAL(S118): scheme, host, port and path of *url*: no userinfo, query or fragment."""
    try:
        parsed = httpx.URL(url)
    except httpx.InvalidURL:
        return "<unparseable URL>"
    return f"{parsed.scheme}://{parsed.netloc.decode('ascii')}{parsed.path}"


def _is_clean_raw_path(raw_path: bytes) -> bool:
    """CORAL(S118): origin-form only: no dot or empty segment, authority or encoded separator,
    and a model id is one plain word (no ``%``, ``;`` or ``#`` an upstream could reinterpret)."""
    if not raw_path.startswith(b"/") or any(byte < 0x21 or byte > 0x7E for byte in raw_path):
        return False
    if any(marker in raw_path.lower() for marker in _UNSAFE_PATH_MARKERS):
        return False
    model_id = raw_path.removeprefix(_MODEL_ROUTE_PREFIX.encode("ascii"))
    if model_id != raw_path and not _MODEL_ID.fullmatch(model_id):
        return False
    return all(segment not in (b"", b".", b"..") for segment in raw_path[1:].split(b"/"))


def _is_forwarded_route(method: str, path: str) -> bool:
    """CORAL(S118): the model routes the CLI needs; nothing else gets the real credential."""
    if (method, path) in _FORWARDED_ROUTES:
        return True
    model_id = path.removeprefix(_MODEL_ROUTE_PREFIX)
    return method == "GET" and model_id != path and "/" not in model_id


async def _receive_capped_body(receive: _Receive, send: _Send) -> bytes | None:
    """CORAL(S118): the complete request body, or ``None`` when there is nothing to forward:
    a body over ``_MAX_REQUEST_BODY_BYTES`` (answered 413) or a CLI that left mid-upload."""
    body = bytearray()
    while True:
        message = await receive()
        if message["type"] == "http.disconnect":
            return None  # nobody is left to answer
        body.extend(message.get("body", b""))
        if len(body) > _MAX_REQUEST_BODY_BYTES:
            logger.warning("Claude credential proxy refused a body over its size cap")
            await _send_error(send, 413, "request_too_large", "request body too large")
            return None
        if not message.get("more_body", False):
            return bytes(body)


async def _until_client_leaves(receive: _Receive) -> None:
    """CORAL(S118): return once the CLI disconnects; its request body was read already."""
    while (await receive())["type"] != "http.disconnect":
        pass


def check_upstream_url(url: str) -> None:
    """CORAL(S118, S119): the one check of where the real credential may be sent.

    An https URL, or a plain http one to loopback, with a host, a numeric port if it names
    one, and no user name or password, which the client would send in the credential's
    place. A backslash, a control character, a query or a fragment is refused too: two
    parsers could read different hosts in it, or no request path could be joined to it.

    :param url: The proxy's upstream, e.g. ``"https://gateway.example/anthropic"``.
    :raises OSError: Otherwise; of *url* the message names at most an ``http`` scheme.
    """
    from omnigent_client._http import is_loopback_url

    malformed = (
        "Claude credential proxy needs an upstream URL with a host, a numeric port if it "
        "names one, and no user name, password, backslash, control character, query or fragment"
    )
    if not url.isprintable() or any(mark in url for mark in "\\?#"):
        raise OSError(malformed)
    try:
        parts = urlsplit(url)
        scheme, host, _ = parts.scheme.lower(), parts.hostname, parts.port
    except ValueError:  # a port that is no number, or an address that is none
        raise OSError(malformed) from None
    if scheme not in ("http", "https") or (scheme == "http" and not is_loopback_url(url)):
        shown = "http" if scheme == "http" else "another scheme"
        raise OSError(
            f"Claude credential proxy needs an https upstream or a loopback http one (got {shown})"
        )
    # Read from the authority as written: an empty user name before the @ is userinfo too.
    if "@" in parts.netloc or not host:
        raise OSError(malformed)


async def _send_error(send: _Send, status: int, error_type: str, message: str) -> None:
    """CORAL(S118): an Anthropic-shaped error answer with a fixed, value-free message."""
    body = json.dumps({"type": "error", "error": {"type": error_type, "message": message}})
    await send(
        {
            "type": "http.response.start",
            "status": status,
            "headers": [(b"content-type", b"application/json")],
        }
    )
    await send({"type": "http.response.body", "body": body.encode("utf-8")})


async def _relay_response(upstream: httpx.Response, send: _Send) -> None:
    """
    Stream an upstream response back to the CLI unbuffered (CORAL(S118): both modes use it).

    :param upstream: An open streaming response.
    :param send: ASGI send callable.
    """
    response_headers = [
        (k.encode("latin-1"), v.encode("latin-1"))
        for k, v in upstream.headers.items()
        if k.lower() not in _HOP_BY_HOP_HEADERS
    ]
    await send(
        {
            "type": "http.response.start",
            "status": upstream.status_code,
            "headers": response_headers,
        }
    )
    # aiter_raw() preserves the wire bytes (no transparent
    # decompression), so content-encoding/content-length
    # response headers stay truthful and SSE chunks flush
    # to the CLI as they arrive.
    async for chunk in upstream.aiter_raw():
        await send(
            {
                "type": "http.response.body",
                "body": chunk,
                "more_body": True,
            }
        )
    await send({"type": "http.response.body", "body": b""})


class ClaudeGatewayShim:
    """
    Reverse proxy between the Claude CLI and an Anthropic-compatible
    gateway that patches request bodies the CLI mis-builds.

    Start with :meth:`start`, then point ``ANTHROPIC_BASE_URL`` at
    :attr:`base_url`. All traffic is forwarded to
    ``upstream_base_url`` with headers preserved (minus hop-by-hop)
    and responses streamed back chunk-by-chunk, so SSE passes through
    unbuffered.

    :param upstream_base_url: The real gateway base URL the CLI would
        otherwise talk to, e.g.
        ``"https://example.databricks.com/ai-gateway/anthropic"``.
    :param credential: CORAL(S118): the real credential; when set, the shim accepts only
        :attr:`session_token` and forwards only the model routes. ``None`` keeps the plain shim.
    :param upstream_proxy: CORAL(S118, S119): proxy URL for the upstream hop, e.g.
        ``"http://proxy.example:3128"``; ``None`` keeps httpx's environment proxies.
    :param upstream_ca_file: CORAL(S118, S119): a PEM CA added to the default trust for the
        upstream.
    :param upstream_env_proxies: CORAL(S119): ``False`` when the caller chose *upstream_proxy*,
        or none, from settings the environment does not hold, so it is not read again.
    """

    def __init__(
        self,
        upstream_base_url: str,
        *,
        credential: UpstreamCredential | None = None,
        upstream_proxy: str | None = None,
        upstream_ca_file: str | None = None,
        upstream_env_proxies: bool = True,  # CORAL(S119)
    ) -> None:
        # CORAL(S118): credential mode and the upstream client's options
        self._credential = credential
        self._upstream_proxy = upstream_proxy
        self._upstream_ca_file = upstream_ca_file
        self._upstream_env_proxies = upstream_env_proxies  # CORAL(S119)
        # The prefix keeps it from ever having an Anthropic key's shape (``sk-...``).
        self._session_token = (
            f"session-{secrets.token_urlsafe(32)}" if credential is not None else None
        )
        self._last_refresh_at: float | None = None
        self._exchanges: set[asyncio.Task[None]] = set()  # upstream exchanges aclose() stops
        self._upstream_base_url = upstream_base_url.rstrip("/")
        # Resolved once per shim: is_ug_route reads ug's state file.
        self._attribution_via_ug: bool | None = (
            is_ug_route(self._upstream_base_url)
            if is_databricks_ai_gateway_url(self._upstream_base_url)
            else None
        )
        self._client_surface = harness_client_surface()
        self._client: httpx.AsyncClient | None = None
        self._server: uvicorn.Server | None = None
        self._serve_task: asyncio.Task[None] | None = None
        self._port: int | None = None
        # Serializes start() so two concurrent first turns can't bind
        # two servers / leak a connection pool.
        self._start_lock = asyncio.Lock()

    @property
    def base_url(self) -> str:
        """
        The local URL the CLI should use as ``ANTHROPIC_BASE_URL``.

        :returns: Loopback base URL, e.g. ``"http://127.0.0.1:49152"``.
        :raises RuntimeError: If :meth:`start` has not completed.
        """
        if self._port is None:
            raise RuntimeError("ClaudeGatewayShim.start() has not completed")
        return f"http://127.0.0.1:{self._port}"

    @property
    def session_token(self) -> str | None:
        """
        CORAL(S118): the only credential the CLI holds in credential mode.

        :returns: ``"session-"`` and 256 random URL-safe bits; ``None`` without a credential.
        """
        return self._session_token

    def _new_upstream_client(self) -> httpx.AsyncClient:
        """
        CORAL(S118): the upstream client; the plain shim keeps today's client exactly.

        :raises OSError: When the proxy or CA cannot be used; names the error type only.
        """
        options = (self._credential, self._upstream_proxy, self._upstream_ca_file)
        if all(option is None for option in options) and self._upstream_env_proxies:
            return httpx.AsyncClient(timeout=_UPSTREAM_TIMEOUT)
        from omnigent_client._http import is_loopback_url

        # With no proxy named, a loopback upstream is reached directly: the real credential
        # never goes through a forward proxy the environment names.
        # CORAL(S119): nor does any upstream whose caller already decided against a proxy
        direct = self._upstream_proxy is None and (
            not self._upstream_env_proxies or is_loopback_url(self._upstream_base_url)
        )
        try:
            # A context built here still reads SSL_CERT_FILE and SSL_CERT_DIR when direct.
            verify = (
                httpx.create_ssl_context()
                if self._upstream_ca_file is None
                else _upstream_ssl_context(self._upstream_ca_file)
            )
            return httpx.AsyncClient(
                timeout=_UPSTREAM_TIMEOUT,
                follow_redirects=False,
                proxy=self._upstream_proxy,
                trust_env=not direct,
                verify=verify,
            )
        except Exception as exc:  # noqa: BLE001 — the proxy URL may hold userinfo
            name = type(exc).__name__
            raise OSError(
                f"Claude gateway shim could not configure its upstream client ({name})"
            ) from None

    async def start(self) -> None:
        """
        Bind the local server on an ephemeral loopback port.

        Idempotent — subsequent calls return immediately once the
        server is up.

        :raises OSError: If the server fails to bind within
            ``_START_TIMEOUT_SECONDS``.
        """
        async with self._start_lock:
            if self._port is not None:
                return
            await self._start_locked()

    async def _start_locked(self) -> None:
        """
        Bind the server; caller must hold ``_start_lock``.

        :raises OSError: If the server fails to bind within
            ``_START_TIMEOUT_SECONDS``.
        """
        if self._client is not None:
            # A prior failed start left a client behind; don't leak it.
            await self._client.aclose()
            self._client = None  # CORAL(S118): a client that fails to build leaves none
        if self._credential is not None:
            check_upstream_url(self._upstream_base_url)  # CORAL(S118, S119)
        self._client = self._new_upstream_client()  # CORAL(S118)
        if self._credential is not None:
            _quiet_upstream_client_logs()  # CORAL(S118)
        config = uvicorn.Config(
            self._asgi_app,
            host="127.0.0.1",
            port=0,  # ephemeral — the bound port is read back below
            log_level="warning",
            lifespan="off",  # plain ASGI callable; no lifespan protocol
            interface="asgi3",  # bound methods defeat uvicorn's auto-detection
            # CORAL(S118): the credential proxy's parser bounds request heads
            http=_CREDENTIAL_PROXY_HTTP_PARSER if self._credential is not None else "auto",
        )
        server = _NoSignalServer(config)
        self._server = server
        self._serve_task = asyncio.create_task(server.serve(), name="claude-gateway-shim-serve")
        deadline = asyncio.get_running_loop().time() + _START_TIMEOUT_SECONDS
        # uvicorn flips ``server.started`` from its serve task; there is
        # no event/callback hook to await, so poll at 10ms.
        while not server.started:
            if self._serve_task.done():
                # Surface bind/startup errors (e.g. port exhaustion)
                # instead of timing out silently.
                self._serve_task.result()
                raise OSError("Claude gateway shim server exited before startup")
            if asyncio.get_running_loop().time() > deadline:
                raise OSError(
                    f"Claude gateway shim failed to start within {_START_TIMEOUT_SECONDS}s"
                )
            await asyncio.sleep(0.01)
        self._port = server.servers[0].sockets[0].getsockname()[1]
        logger.info(
            "Claude gateway shim listening on %s → %s",
            self.base_url,
            _loggable_url(self._upstream_base_url),  # CORAL(S118)
        )

    async def aclose(self) -> None:
        """
        Stop the local server and release the upstream connection pool.

        Safe to call multiple times or before :meth:`start`.
        """
        if self._server is not None:
            self._server.should_exit = True
        # CORAL(S118): stop credential exchanges still running; a running command loses its group
        if stopping := list(self._exchanges):
            for exchange in stopping:
                exchange.cancel()
            await asyncio.wait(stopping, timeout=_CREDENTIAL_KILL_WAIT_S)
        if self._credential is not None:
            await self._credential.aclose()
        if self._serve_task is not None:
            try:
                await asyncio.wait_for(self._serve_task, timeout=5.0)
            except (TimeoutError, asyncio.CancelledError):
                self._serve_task.cancel()
            self._serve_task = None
        if self._client is not None:
            await self._client.aclose()
            self._client = None
        self._server = None
        self._port = None

    async def _asgi_app(self, scope: _Scope, receive: _Receive, send: _Send) -> None:
        """
        Forward one request to the upstream gateway.

        :param scope: ASGI connection scope; only ``"http"`` is served.
        :param receive: ASGI receive callable for request body chunks.
        :param send: ASGI send callable for response messages.
        """
        if scope["type"] != "http":
            return
        if self._credential is not None:  # CORAL(S118)
            await self._serve_credential_request(scope, receive, send)
            return
        if self._client is None:
            # Serving begins only after start() set the client; reaching
            # here means the shim's invariants were violated upstream.
            raise RuntimeError("ClaudeGatewayShim served a request before start()")

        body = bytearray()
        while True:
            message = await receive()
            body.extend(message.get("body", b""))
            if not message.get("more_body", False):
                break

        method: str = scope["method"]
        path: str = scope["path"]
        request_body = bytes(body)
        if method == "POST" and path.endswith("/v1/messages"):
            request_body = restore_thinking_display(request_body)

        headers = self._forwarded_headers(
            scope["headers"]
        )  # CORAL(S118): shared with credential mode
        query = scope.get("query_string", b"").decode("latin-1")
        url = f"{self._upstream_base_url}{path}" + (f"?{query}" if query else "")

        try:
            async with self._client.stream(
                method, url, headers=headers, content=request_body
            ) as upstream:
                await _relay_response(upstream, send)  # CORAL(S118): shared with credential mode
        except httpx.HTTPError as exc:
            logger.exception("Claude gateway shim upstream error: %s", exc)
            error_body = json.dumps(
                {
                    "type": "error",
                    "error": {
                        "type": "api_error",
                        "message": f"gateway shim upstream error: {exc}",
                    },
                }
            ).encode("utf-8")
            await send(
                {
                    "type": "http.response.start",
                    "status": 502,
                    "headers": [(b"content-type", b"application/json")],
                }
            )
            await send({"type": "http.response.body", "body": error_body})

    def _forwarded_headers(
        self, scope_headers: list[tuple[bytes, bytes]], credential: str | None = None
    ) -> list[tuple[str, str]]:
        """
        The request headers to send upstream, with the gateway attribution.

        :param scope_headers: The CLI's raw ASGI headers.
        :param credential: CORAL(S118): the real credential; it replaces the presented
            ``x-api-key`` / ``authorization`` in the same form(s). ``None`` forwards them as sent.
        :returns: Header pairs, hop-by-hop, ``host`` and ``content-length`` dropped.
        """
        headers: list[tuple[str, str]] = []
        presented: set[str] = set()
        for raw_name, raw_value in scope_headers:
            name = raw_name.decode("latin-1")
            if credential is not None and name.lower() in _CREDENTIAL_HEADERS:  # CORAL(S118)
                presented.add(name.lower())
            elif credential is not None and (  # CORAL(S118): no routing overrides upstream
                name.lower() in _REQUEST_OVERRIDE_HEADERS
                or name.lower().startswith("x-forwarded-")
            ):
                continue
            elif name.lower() not in _REQUEST_HEADER_EXCLUDES:
                headers.append((name, raw_value.decode("latin-1")))
        if credential is not None:  # CORAL(S118): the header form(s) the CLI used
            if "x-api-key" in presented:
                headers.append(("x-api-key", credential))
            if "authorization" in presented:
                headers.append(("authorization", f"Bearer {credential}"))
        if self._attribution_via_ug is not None:
            headers = with_gateway_attribution_pairs(
                headers,
                CLAUDE_CODE_AGENT,
                via_ug=self._attribution_via_ug,
                client_surface=self._client_surface,
            )
        return headers

    async def _serve_credential_request(
        self, scope: _Scope, receive: _Receive, send: _Send
    ) -> None:
        """
        CORAL(S118): serve one credential-mode request; any failure names its type only.

        :param scope: ASGI HTTP scope.
        :param receive: ASGI receive callable.
        :param send: ASGI send callable.
        """
        response_started = False

        async def tracked_send(message: MutableMapping[str, Any]) -> None:  # type: ignore[explicit-any]  # ASGI message dict
            nonlocal response_started
            response_started = response_started or message["type"] == "http.response.start"
            await send(message)

        context_token = _SERVING_CREDENTIAL_REQUEST.set(True)
        try:
            await self._forward_with_credential(scope, receive, tracked_send)
        except Exception as exc:  # noqa: BLE001 — every failure answers by type name only
            logger.error("Claude credential proxy request failed (%s)", type(exc).__name__)
            if not response_started:
                with contextlib.suppress(Exception):
                    await _send_error(
                        send,
                        502,
                        "api_error",
                        f"credential proxy upstream error ({type(exc).__name__})",
                    )
        finally:
            _SERVING_CREDENTIAL_REQUEST.reset(context_token)

    async def _forward_with_credential(
        self, scope: _Scope, receive: _Receive, send: _Send
    ) -> None:
        """
        CORAL(S118): check the session token from the headers, then the route, path and body
        size, then forward with the real credential until the answer ends or the CLI leaves.

        :param scope: ASGI HTTP scope.
        :param receive: ASGI receive callable.
        :param send: ASGI send callable.
        """
        credential, client = self._credential, self._client
        if credential is None or client is None:
            raise RuntimeError("ClaudeGatewayShim served a request before start()")
        scope_headers: list[tuple[bytes, bytes]] = list(scope["headers"])
        if not self._presents_session_token(scope_headers):
            logger.warning("Claude credential proxy refused a request without its session token")
            await _send_error(send, 401, "authentication_error", "invalid credential proxy token")
            return
        method: str = scope["method"]
        raw_path: bytes = scope.get("raw_path") or b""
        if not _is_clean_raw_path(raw_path):
            logger.warning("Claude credential proxy refused a malformed request path")
            await _send_error(send, 400, "invalid_request_error", "malformed request path")
            return
        path = raw_path.decode("ascii")
        if not _is_forwarded_route(method, path):
            logger.warning(
                "Claude credential proxy refused %s on an unlisted route (%d segments)",
                method if method in _LOGGED_METHODS else "a request",
                path.count("/"),
            )
            await _send_error(send, 404, "not_found_error", "route not served by this proxy")
            return
        query: bytes = scope.get("query_string", b"")
        url = f"{self._upstream_base_url}{path}" + (f"?{query.decode('latin-1')}" if query else "")
        if not self._is_under_upstream(url):
            logger.warning("Claude credential proxy refused a request outside its upstream")
            await _send_error(send, 400, "invalid_request_error", "request outside the upstream")
            return
        body = await _receive_capped_body(receive, send)
        if body is None:
            return
        if method == "POST" and path == "/v1/messages":
            body = restore_thinking_display(body)
        exchange = asyncio.create_task(
            self._exchange(credential, client, (method, url, scope_headers, body), send)
        )
        # uvicorn also reports a complete answer as a disconnect, but the exchange ends in the
        # step that sends its last byte (httpx closes a fully read response), so it is not cut.
        client_left = asyncio.create_task(_until_client_leaves(receive))
        self._exchanges.add(exchange)
        try:
            await asyncio.wait((exchange, client_left), return_when=asyncio.FIRST_COMPLETED)
        finally:
            self._exchanges.discard(exchange)
            exchange.cancel()  # a CLI that left stops the upstream read and closes its response
            client_left.cancel()
            await asyncio.wait((exchange, client_left))
        if not exchange.cancelled():
            exchange.result()  # a failure goes to the value-free handler
        elif client_left.cancelled():  # neither finished: aclose() stopped the exchange
            raise ConnectionAbortedError("the credential proxy closed")

    async def _exchange(
        self,
        credential: UpstreamCredential,
        client: httpx.AsyncClient,
        request: tuple[str, str, list[tuple[bytes, bytes]], bytes],
        send: _Send,
    ) -> None:
        """
        CORAL(S118): forward with the real credential and relay the answer; one refresh on an
        upstream 401.

        :param credential: The real credential.
        :param client: The upstream client.
        :param request: Method, upstream URL, the CLI's headers and the complete body.
        :param send: ASGI send callable.
        """
        method, url, scope_headers, body = request
        for attempt in range(2):
            try:
                value = await credential.get()
            except Exception as exc:  # noqa: BLE001 — get() failures all get the fixed 401
                logger.warning(
                    "Claude credential proxy has no credential (%s)", type(exc).__name__
                )
                await _send_error(
                    send, 401, "authentication_error", "the model credential helper failed"
                )
                return
            upstream_request = client.build_request(
                method, url, headers=self._forwarded_headers(scope_headers, value), content=body
            )
            upstream = await client.send(upstream_request, stream=True)
            if upstream.status_code == 401 and attempt == 0 and self._claim_refresh():
                await upstream.aclose()
                credential.invalidate()
                continue
            try:
                await _relay_response(upstream, send)
            finally:
                await upstream.aclose()
            return

    def _presents_session_token(self, scope_headers: list[tuple[bytes, bytes]]) -> bool:
        """
        CORAL(S118): every presented ``x-api-key`` and ``authorization: Bearer`` is the session
        token, at least one is present and none is repeated; compared as bytes in constant time.
        """
        expected = (self._session_token or "").encode("ascii")
        presented: list[bytes] = []
        seen: set[bytes] = set()
        for raw_name, raw_value in scope_headers:
            name = raw_name.lower()
            if name not in (b"x-api-key", b"authorization"):
                continue
            if name in seen:
                return False
            seen.add(name)
            if name == b"authorization":
                if raw_value[:7].lower() != b"bearer ":
                    return False
                raw_value = raw_value[7:]
            presented.append(raw_value)
        matches = [hmac.compare_digest(value, expected) for value in presented]
        return bool(matches) and all(matches)

    def _is_under_upstream(self, url: str) -> bool:
        """CORAL(S118): *url* has the upstream's scheme, host and port and stays under its path."""
        try:
            joined, upstream = httpx.URL(url), httpx.URL(self._upstream_base_url)
        except httpx.InvalidURL:
            return False
        return (joined.scheme, joined.host, joined.port) == (
            upstream.scheme,
            upstream.host,
            upstream.port,
        ) and joined.path.startswith(upstream.path.rstrip("/") + "/")

    def _claim_refresh(self) -> bool:
        """CORAL(S118): allow one upstream-401 refresh per ``_REFRESH_MIN_INTERVAL_S``."""
        if self._credential is None or not self._credential.refreshable:
            return False
        now = time.monotonic()
        if (
            self._last_refresh_at is not None
            and now - self._last_refresh_at < _REFRESH_MIN_INTERVAL_S
        ):
            return False
        self._last_refresh_at = now
        return True
