"""A forwarding proxy that lets the live E2E's CLI reach the Anthropic API without its key.

No process the test starts is given the key, but on macOS a step's shell can read it from
the environment of this process and its parents. The host, and so every CLI it starts, gets
a random per-run token as its API key and this proxy's loopback URL as its base URL; the
proxy swaps the token for the key on the way to one fixed upstream. It admits only that
token, as ``x-api-key`` (the CLI's header) or else as a bearer token (the runner's model
listing), forwards only ``POST /v1/messages`` and ``GET /v1/models``, verifies the
upstream's certificate, never follows a redirect, caps request bodies and concurrent
upstream calls, and logs nothing at all, so no header or body can reach a log. The key
travels in a :class:`Secret`, whose repr is redacted, so no traceback or report shows it.

The token does not keep out other local accounts: it reaches the CLI's command line,
which any local user can read, and the stack's own server serves unauthenticated local
requests. Run the live test only on a machine with no other users.
"""

from __future__ import annotations

import contextlib
import hmac
import http.client
import ipaddress
import json
import secrets
import socket
import ssl
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

ANTHROPIC_API = "https://api.anthropic.com"
TOKEN_HEADER = "x-api-key"
ROUTES = frozenset({("POST", "/v1/messages"), ("GET", "/v1/models")})
MAX_BODY_BYTES = 1024 * 1024
MAX_UPSTREAM_CALLS = 4
# How long a call waits for one of the upstream slots before it is refused.
CALL_WAIT_S = 120.0
# How long the proxy waits on a client that is sending its request or reading the answer.
CLIENT_TIMEOUT_S = 60.0
UPSTREAM_TIMEOUT_S = 600.0
_CHUNK_BYTES = 64 * 1024
# Credentials, hop-by-hop and framing headers are never copied between the hops.
_HOP_BY_HOP = frozenset(
    {
        "connection",
        "keep-alive",
        "proxy-authenticate",
        "proxy-authorization",
        "proxy-connection",
        "te",
        "trailer",
        "transfer-encoding",
        "upgrade",
        "content-length",
    }
)
_NOT_FORWARDED = _HOP_BY_HOP | {TOKEN_HEADER, "authorization", "cookie", "host", "accept-encoding"}
_NOT_RETURNED = _HOP_BY_HOP | {"set-cookie"}


class Secret:
    """A credential that never shows itself: its repr and str are redacted."""

    __slots__ = ("_value",)

    def __init__(self, value: str) -> None:
        self._value = value

    def __repr__(self) -> str:
        return "Secret(<redacted>)"

    __str__ = __repr__

    def reveal(self) -> str:
        """The credential itself, for the one place that sends it."""
        return self._value

    def found_in(self, path: Path) -> bool:
        """Whether the file at ``path`` holds the credential; its contents stay in here."""
        return self._value.encode() in path.read_bytes()


@dataclass(frozen=True)
class LiveProxy:
    """The running proxy: the base URL to give the host and the token it admits."""

    url: str
    token: str = field(repr=False)


@dataclass(frozen=True)
class _Upstream:
    host: str
    port: int
    tls: ssl.SSLContext
    api_key: Secret
    token: str = field(repr=False)
    max_body_bytes: int
    calls: threading.BoundedSemaphore
    call_wait_s: float
    timeout_s: float


class _ProxyServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address: tuple[str, int], upstream: _Upstream) -> None:
        super().__init__(address, _ProxyHandler)
        self.upstream = upstream
        self.closing = threading.Event()
        self._open: set[object] = set()
        self._open_lock = threading.Lock()

    def process_request(self, request: Any, client_address: Any) -> None:
        with self._open_lock:
            self._open.add(request)
        super().process_request(request, client_address)

    def shutdown_request(self, request: Any) -> None:
        with self._open_lock:
            self._open.discard(request)
        super().shutdown_request(request)

    def close_connections(self) -> None:
        """Stop forwarding and cut every connection still open, idle or mid-call."""
        self.closing.set()
        with self._open_lock:
            still_open = list(self._open)
        for connection in still_open:
            if isinstance(connection, socket.socket):
                with contextlib.suppress(OSError):
                    connection.shutdown(socket.SHUT_RDWR)

    def handle_error(self, request: object, client_address: object) -> None:
        """A failed request is dropped without a trace: its traceback could quote it."""


class _ProxyHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    timeout = CLIENT_TIMEOUT_S
    server: _ProxyServer

    def log_message(self, format: str, *args: object) -> None:
        """Nothing of a request is logged."""

    def do_GET(self) -> None:
        self._forward()

    def do_POST(self) -> None:
        self._forward()

    do_PUT = do_PATCH = do_DELETE = do_HEAD = do_OPTIONS = do_POST

    def _forward(self) -> None:
        upstream = self.server.upstream
        if self.server.closing.is_set():
            self._refuse(503, "overloaded_error", "The proxy has closed.")
            return
        if not hmac.compare_digest(self._token(), upstream.token.encode()):
            self._refuse(401, "authentication_error", "This proxy admits only its run's token.")
            return
        # Origin form only, so a request can never name another upstream.
        route = (self.command, urlsplit(self.path).path)
        if not self.path.startswith("/") or route not in ROUTES:
            self._refuse(404, "not_found_error", "This proxy forwards Messages and Models only.")
            return
        body = self._body(upstream.max_body_bytes)
        if body is None:
            return
        if not upstream.calls.acquire(timeout=upstream.call_wait_s):
            self._refuse(503, "overloaded_error", "Too many upstream calls are in flight.")
            return
        try:
            if self.server.closing.is_set():
                self._refuse(503, "overloaded_error", "The proxy has closed.")
                return
            self._relay(upstream, body)
        finally:
            upstream.calls.release()

    def _token(self) -> bytes:
        """The token the request presents: its ``x-api-key``, else its bearer token."""
        presented = self.headers.get(TOKEN_HEADER)
        if presented is None:
            scheme, _, presented = self.headers.get("authorization", "").partition(" ")
            presented = presented if scheme.lower() == "bearer" else ""
        return presented.encode("utf-8", "surrogateescape")

    def _body(self, limit: int) -> bytes | None:
        """The request body within the cap, or ``None`` once a refusal was sent."""
        if "chunked" in self.headers.get("transfer-encoding", "").lower():
            self._refuse(411, "invalid_request_error", "Send the body with a Content-Length.")
            return None
        declared = self.headers.get("content-length")
        if declared is None:
            return b""
        try:
            length = int(declared)
        except ValueError:
            length = -1
        if length < 0:
            self._refuse(400, "invalid_request_error", "The Content-Length is not valid.")
            return None
        if length > limit:
            self._refuse(413, "request_too_large", "The request body is over the proxy's cap.")
            return None
        body = self.rfile.read(length)
        if len(body) < length:
            # The client stopped before its body was whole: nothing of it is sent on.
            self._refuse(400, "invalid_request_error", "The request body ended early.")
            return None
        return body

    def _relay(self, upstream: _Upstream, body: bytes) -> None:
        connection = http.client.HTTPSConnection(
            upstream.host, upstream.port, context=upstream.tls, timeout=upstream.timeout_s
        )
        try:
            try:
                connection.putrequest(self.command, self.path, skip_accept_encoding=True)
                for name, value in self.headers.items():
                    if name.lower() not in _NOT_FORWARDED:
                        connection.putheader(name, value)
                connection.putheader(TOKEN_HEADER, upstream.api_key.reveal())
                connection.putheader("accept-encoding", "identity")
                connection.putheader("content-length", str(len(body)))
                connection.endheaders(body)
                answer = connection.getresponse()
            except (OSError, ValueError, http.client.HTTPException):
                self._refuse(502, "api_error", "The upstream could not be reached.")
                return
            if 300 <= answer.status < 400:
                self._refuse(
                    502, "api_error", "The upstream redirected; the proxy does not follow."
                )
                return
            self.send_response(answer.status, answer.reason)
            for name, value in answer.getheaders():
                if name.lower() not in _NOT_RETURNED:
                    self.send_header(name, value)
            # The body streams until the connection closes.
            self.send_header("connection", "close")
            self.end_headers()
            self.close_connection = True
            try:
                while not self.server.closing.is_set() and (chunk := answer.read1(_CHUNK_BYTES)):
                    self.wfile.write(chunk)
                    self.wfile.flush()
            except (OSError, http.client.HTTPException):
                return
        finally:
            connection.close()

    def _refuse(self, status: int, kind: str, message: str) -> None:
        payload = json.dumps({"type": "error", "error": {"type": kind, "message": message}})
        encoded = payload.encode()
        self.send_response(status)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(encoded)))
        self.send_header("connection", "close")
        self.end_headers()
        self.close_connection = True
        self.wfile.write(encoded)


def _is_ipv4_loopback(host: str) -> bool:
    try:
        return ipaddress.IPv4Address(host).is_loopback
    except ValueError:
        return False


def _https_origin(upstream: str) -> tuple[str, int]:
    parts = urlsplit(upstream)
    if parts.scheme != "https" or not parts.hostname or parts.path not in {"", "/"}:
        raise ValueError("The upstream must be an https origin with no path")
    if parts.query or parts.fragment or parts.username or parts.password:
        raise ValueError("The upstream must be an https origin with no path")
    return parts.hostname, parts.port or 443


@contextmanager
def live_proxy(
    api_key: Secret,
    *,
    upstream: str = ANTHROPIC_API,
    tls: ssl.SSLContext | None = None,
    host: str = "127.0.0.1",
    max_body_bytes: int = MAX_BODY_BYTES,
    max_upstream_calls: int = MAX_UPSTREAM_CALLS,
    call_wait_s: float = CALL_WAIT_S,
) -> Iterator[LiveProxy]:
    """
    Serve the proxy on a free loopback port until the block exits, then close it.

    At exit every connection still open is cut, so none can forward afterwards.

    :param api_key: The key the upstream receives in place of the token.
    :param upstream: The one https origin every admitted request goes to.
    :param tls: How the upstream's certificate is verified; the system's trust by
        default. A context that skips verification is refused, and the proxy turns off
        its TLS key logging (``SSLKEYLOGFILE``).
    :param host: An IPv4 loopback address to bind; any other address is refused.
    :raises TypeError: for a key that is not a :class:`Secret`.
    :raises ValueError: for a non-loopback ``host``, an upstream that is not an https
        origin, or a ``tls`` context that does not verify the upstream.
    """
    if not isinstance(api_key, Secret):
        raise TypeError("The proxy takes its key as a Secret")
    if not _is_ipv4_loopback(host):
        raise ValueError("The proxy binds an IPv4 loopback address only")
    upstream_host, upstream_port = _https_origin(upstream)
    context = tls if tls is not None else ssl.create_default_context()
    if context.verify_mode != ssl.CERT_REQUIRED or not context.check_hostname:
        raise ValueError("The proxy verifies the upstream's certificate and host name")
    # Session secrets written to a key log would let a capture read the key's header.
    context.keylog_filename = None
    upstream_config = _Upstream(
        host=upstream_host,
        port=upstream_port,
        tls=context,
        api_key=api_key,
        token=secrets.token_urlsafe(32),
        max_body_bytes=max_body_bytes,
        calls=threading.BoundedSemaphore(max_upstream_calls),
        call_wait_s=call_wait_s,
        timeout_s=UPSTREAM_TIMEOUT_S,
    )
    server = _ProxyServer((host, 0), upstream_config)
    serving = threading.Thread(
        target=server.serve_forever, kwargs={"poll_interval": 0.1}, daemon=True
    )
    serving.start()
    try:
        yield LiveProxy(
            url=f"http://{host}:{server.server_address[1]}", token=upstream_config.token
        )
    finally:
        server.shutdown()
        server.close_connections()
        server.server_close()
        serving.join(timeout=10)
