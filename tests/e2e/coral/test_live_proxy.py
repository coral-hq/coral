"""The live E2E's proxy admits only its token, reaches one verified upstream, keeps the key in.

A fake HTTPS upstream records every request that reaches it. The key and every marker
are test values.
"""

from __future__ import annotations

import http.client
import json
import logging
import os
import socket
import ssl
import struct
import subprocess
import sys
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import psutil
import pytest

from tests._helpers.https_server import enable_https
from tests._helpers.polling import poll_until
from tests.e2e.coral import _live_proxy
from tests.e2e.coral._live_proxy import MAX_BODY_BYTES, LiveProxy, Secret, live_proxy

FAKE_KEY = "fake-upstream-key-3c9d0e"
KEY = Secret(FAKE_KEY)
HEADER_MARK = "header-mark-5f1c"
BODY_MARK = "body-mark-9a2e"
STREAM = (
    b'event: message_start\ndata: {"type": "message_start"}\n\n'
    b'event: message_stop\ndata: {"type": "message_stop"}\n\n'
)
MODELS = {"data": [{"id": "claude-test-model", "type": "model"}]}

_Answer = tuple[int, dict[str, str], bytes]
ROOT = Path(__file__).resolve().parents[3]
LIVE_TEST = "tests/e2e/coral/test_skeleton.py::test_live_review_loop_survives_server_sigkills"
# Loaded into a child pytest: the live run fails before it reaches any model.
_FAIL_LIVE_PLUGIN = """
import pytest

from tests.e2e.coral import _skeleton


@pytest.fixture(autouse=True)
def _fail_before_any_model_call(monkeypatch):
    def refuse():
        raise AssertionError("the live run failed on purpose")

    monkeypatch.setattr(_skeleton, "require_claude_cli", refuse)
"""


@dataclass
class _FakeUpstream:
    url: str
    tls: ssl.SSLContext
    # The fake's trust root, for a client context of the test's own.
    ca_file: str
    received: list[dict[str, Any]] = field(default_factory=list)
    redirect_to: str = ""
    release: threading.Event = field(default_factory=threading.Event)
    # When set, every request is answered with this status, headers and body.
    answer: _Answer | None = None


class _QuietServer(ThreadingHTTPServer):
    def handle_error(self, request: object, client_address: object) -> None:
        """A connection the proxy dropped is not the proxy's output, so the fake stays quiet."""


@contextmanager
def _fake_upstream(tls_dir: Path) -> Iterator[_FakeUpstream]:
    """
    An HTTPS upstream on localhost: it streams messages, lists models, or redirects.

    A body holding ``hold`` waits for ``release`` before the answer; one holding
    ``slow`` waits for it between the stream's two events.
    """
    state: list[_FakeUpstream] = []

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, format: str, *args: object) -> None:
            """Quiet, so the log test sees only what the proxy writes."""

        def do_GET(self) -> None:
            self._answer()

        def do_POST(self) -> None:
            self._answer()

        def _answer(self) -> None:
            [fake] = state
            body = self.rfile.read(int(self.headers.get("content-length") or 0))
            fake.received.append(
                {
                    "method": self.command,
                    "path": self.path,
                    "headers": [(name.lower(), value) for name, value in self.headers.items()],
                    "body": body,
                }
            )
            if b"hold" in body:
                fake.release.wait(10)
            if fake.answer is not None:
                status, headers, payload = fake.answer
                self.send_response(status)
                for name, value in headers.items():
                    self.send_header(name, value)
                self.send_header("content-length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)
            elif b"redirect" in body:
                self.send_response(307)
                self.send_header("location", fake.redirect_to)
                self.send_header("content-length", "0")
                self.end_headers()
            elif self.path.startswith("/v1/models"):
                listed = json.dumps(MODELS).encode()
                self.send_response(200)
                self.send_header("content-type", "application/json")
                self.send_header("content-length", str(len(listed)))
                self.end_headers()
                self.wfile.write(listed)
            else:
                self.send_response(200)
                self.send_header("content-type", "text/event-stream")
                self.send_header("transfer-encoding", "chunked")
                self.end_headers()
                for index, event in enumerate(STREAM.split(b"\n\n")[:-1]):
                    if index and b"slow" in body:
                        fake.release.wait(10)
                    chunk = event + b"\n\n"
                    self.wfile.write(b"%x\r\n%s\r\n" % (len(chunk), chunk))
                self.wfile.write(b"0\r\n\r\n")

    server = _QuietServer(("127.0.0.1", 0), Handler)
    trust = enable_https(server, tls_dir)
    fake = _FakeUpstream(
        url=f"https://localhost:{server.server_address[1]}",
        tls=ssl.create_default_context(cafile=trust["SSL_CERT_FILE"]),
        ca_file=trust["SSL_CERT_FILE"],
    )
    state.append(fake)
    serving = threading.Thread(target=server.serve_forever, daemon=True)
    serving.start()
    try:
        yield fake
    finally:
        fake.release.set()
        server.shutdown()
        server.server_close()
        serving.join(timeout=10)


@pytest.fixture
def upstream(tmp_path: Path) -> Iterator[_FakeUpstream]:
    with _fake_upstream(tmp_path / "tls") as fake:
        yield fake


def _call(
    proxy: LiveProxy,
    method: str,
    path: str,
    *,
    headers: dict[str, str] | None = None,
    body: bytes = b"",
) -> _Answer:
    parts = urlsplit(proxy.url)
    connection = http.client.HTTPConnection(parts.hostname, parts.port, timeout=10)
    try:
        connection.request(method, path, body=body, headers=headers or {})
        answer = connection.getresponse()
        return answer.status, {k.lower(): v for k, v in answer.getheaders()}, answer.read()
    finally:
        connection.close()


def _with_token(proxy: LiveProxy, **headers: str) -> dict[str, str]:
    return {"x-api-key": proxy.token, **headers}


def _calls_in_background(
    proxy: LiveProxy, body: bytes, count: int
) -> tuple[list[threading.Thread], list[_Answer]]:
    """Start ``count`` admitted message calls at once; their answers land in the list."""
    answers: list[_Answer] = []
    threads = [
        threading.Thread(
            target=lambda: answers.append(
                _call(proxy, "POST", "/v1/messages", headers=_with_token(proxy), body=body)
            )
        )
        for _ in range(count)
    ]
    for thread in threads:
        thread.start()
    return threads, answers


def _open_call(proxy: LiveProxy, body: bytes, *, declared: int | None = None) -> socket.socket:
    """A raw admitted message call whose body is sent, but whose answer is not read."""
    parts = urlsplit(proxy.url)
    client = socket.create_connection((parts.hostname, parts.port), timeout=10)
    head = (
        f"POST /v1/messages HTTP/1.1\r\nhost: proxy\r\nx-api-key: {proxy.token}\r\n"
        f"content-length: {len(body) if declared is None else declared}\r\n\r\n"
    )
    client.sendall(head.encode() + body)
    return client


def test_a_request_without_the_runs_token_is_refused(upstream: _FakeUpstream) -> None:
    with live_proxy(KEY, upstream=upstream.url, tls=upstream.tls) as proxy:
        missing = _call(proxy, "POST", "/v1/messages", body=b"{}")
        wrong = _call(proxy, "POST", "/v1/messages", headers={"x-api-key": "guess"}, body=b"{}")
        wrong_bearer = {"authorization": "Bearer guess"}
        guessed = _call(proxy, "POST", "/v1/messages", headers=wrong_bearer, body=b"{}")
        # A request's x-api-key is the token it presents, whatever else it carries.
        both = {"x-api-key": "guess", "authorization": f"Bearer {proxy.token}"}
        shadowed = _call(proxy, "POST", "/v1/messages", headers=both, body=b"{}")

    assert [answer[0] for answer in (missing, wrong, guessed, shadowed)] == [401] * 4
    assert upstream.received == []


def test_the_token_is_also_admitted_as_a_bearer_token(upstream: _FakeUpstream) -> None:
    with live_proxy(KEY, upstream=upstream.url, tls=upstream.tls) as proxy:
        bearer = {"authorization": f"Bearer {proxy.token}"}
        status, _, body = _call(proxy, "GET", "/v1/models", headers=bearer)

    assert (status, json.loads(body)) == (200, MODELS)
    [listed] = upstream.received
    assert dict(listed["headers"])["x-api-key"] == FAKE_KEY
    assert "authorization" not in dict(listed["headers"])


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", "/v1/messages"),
        ("POST", "/v1/models"),
        ("POST", "/v1/messages/count_tokens"),
        ("POST", "/v1/complete"),
        ("DELETE", "/v1/messages"),
        # An absolute request target may not name another upstream.
        ("POST", "http://localhost:9/v1/messages"),
    ],
)
def test_only_the_messages_and_models_routes_are_forwarded(
    upstream: _FakeUpstream, method: str, path: str
) -> None:
    with live_proxy(KEY, upstream=upstream.url, tls=upstream.tls) as proxy:
        status, _, _ = _call(proxy, method, path, headers=_with_token(proxy), body=b"{}")

    assert status == 404
    assert upstream.received == []


def test_the_upstream_gets_the_key_and_the_client_never_does(upstream: _FakeUpstream) -> None:
    request = json.dumps({"model": "claude-test-model", "stream": True}).encode()
    with live_proxy(KEY, upstream=upstream.url, tls=upstream.tls) as proxy:
        token = proxy.token
        streamed = _call(
            proxy,
            "POST",
            "/v1/messages?beta=true",
            headers=_with_token(
                proxy,
                authorization=f"Bearer {token}",
                **{"anthropic-version": "2023-06-01", "x-marker": HEADER_MARK},
            ),
            body=request,
        )
        listed = _call(proxy, "GET", "/v1/models?limit=100", headers=_with_token(proxy))

    assert streamed[:1] == (200,) and streamed[2] == STREAM
    assert streamed[1]["content-type"] == "text/event-stream"
    assert listed[0] == 200 and json.loads(listed[2]) == MODELS
    sent, models = upstream.received
    assert (sent["method"], sent["path"], sent["body"]) == (
        "POST",
        "/v1/messages?beta=true",
        request,
    )
    assert (models["method"], models["path"]) == ("GET", "/v1/models?limit=100")
    assert ("x-marker", HEADER_MARK) in sent["headers"]
    for received in (sent, models):
        names = [name for name, _ in received["headers"]]
        assert dict(received["headers"])["x-api-key"] == FAKE_KEY
        assert names.count("x-api-key") == 1 and "authorization" not in names
        assert dict(received["headers"])["host"] == urlsplit(upstream.url).netloc
        assert not any(token in value for _, value in received["headers"])
    for _, headers, body in (streamed, listed):
        assert FAKE_KEY not in json.dumps(headers) and FAKE_KEY.encode() not in body


def test_a_redirect_from_the_upstream_is_not_followed(tmp_path: Path) -> None:
    # One trust root, so the proxy could reach the redirect's target if it followed it.
    with (
        _fake_upstream(tmp_path / "tls") as upstream,
        _fake_upstream(tmp_path / "tls") as elsewhere,
    ):
        upstream.redirect_to = f"{elsewhere.url}/v1/messages"
        with live_proxy(KEY, upstream=upstream.url, tls=upstream.tls) as proxy:
            status, headers, _ = _call(
                proxy, "POST", "/v1/messages", headers=_with_token(proxy), body=b'{"redirect": 1}'
            )

    assert status == 502 and "location" not in headers
    assert len(upstream.received) == 1
    assert elsewhere.received == []


def test_nothing_of_a_request_is_logged(
    upstream: _FakeUpstream, capfd: pytest.CaptureFixture[str], caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    with live_proxy(KEY, upstream=upstream.url, tls=upstream.tls) as proxy:
        token = proxy.token
        marked = _with_token(proxy, **{"x-marker": HEADER_MARK})
        body = BODY_MARK.encode()
        answers = [
            _call(proxy, "POST", "/v1/messages", headers=marked, body=body),
            _call(proxy, "POST", "/v1/messages", headers={"x-api-key": HEADER_MARK}, body=body),
            _call(proxy, "POST", f"/v1/nowhere?{BODY_MARK}", headers=marked, body=body),
        ]
    # An upstream that is not listening.
    with live_proxy(KEY, upstream="https://localhost:9", tls=upstream.tls) as down:
        answers.append(_call(down, "POST", "/v1/messages", headers=_with_token(down), body=body))

    assert [answer[0] for answer in answers] == [200, 401, 404, 502]
    captured = capfd.readouterr()
    written = captured.out + captured.err + caplog.text
    for mark in (FAKE_KEY, token, down.token, HEADER_MARK, BODY_MARK):
        assert mark not in written
    # Not even a request line.
    assert written == ""


@pytest.mark.parametrize("host", ["0.0.0.0", "192.168.1.10", "::", "::1", "localhost"])
def test_the_proxy_never_binds_a_non_loopback_address(upstream: _FakeUpstream, host: str) -> None:
    with (
        pytest.raises(ValueError, match="loopback"),
        live_proxy(KEY, upstream=upstream.url, tls=upstream.tls, host=host),
    ):
        pass


def test_the_proxy_listens_on_loopback_only_and_closes_at_teardown(
    upstream: _FakeUpstream,
) -> None:
    with live_proxy(KEY, upstream=upstream.url, tls=upstream.tls) as proxy:
        port = urlsplit(proxy.url).port
        listening = [
            conn.laddr.ip
            for conn in psutil.Process().net_connections(kind="tcp")
            if conn.status == psutil.CONN_LISTEN and conn.laddr.port == port
        ]

    assert listening == ["127.0.0.1"]
    with pytest.raises(ConnectionRefusedError):
        socket.create_connection(("127.0.0.1", port), timeout=2).close()


def test_request_bodies_and_concurrent_upstream_calls_are_capped(upstream: _FakeUpstream) -> None:
    held: list[_Answer] = []
    with live_proxy(
        KEY, upstream=upstream.url, tls=upstream.tls, max_upstream_calls=1, call_wait_s=0.2
    ) as proxy:
        # The proxy refuses on the declared length, before any body is sent.
        parts = urlsplit(proxy.url)
        oversized = http.client.HTTPConnection(parts.hostname, parts.port, timeout=10)
        oversized.putrequest("POST", "/v1/messages")
        oversized.putheader("x-api-key", proxy.token)
        oversized.putheader("content-length", str(MAX_BODY_BYTES + 1))
        oversized.endheaders()
        too_large = oversized.getresponse().status
        oversized.close()
        first = threading.Thread(
            target=lambda: held.append(
                _call(
                    proxy, "POST", "/v1/messages", headers=_with_token(proxy), body=b'{"hold": 1}'
                )
            )
        )
        first.start()
        poll_until(lambda: len(upstream.received) == 1, timeout_s=10)
        crowded = _call(proxy, "POST", "/v1/messages", headers=_with_token(proxy), body=b"{}")
        upstream.release.set()
        first.join(timeout=10)

    assert too_large == 413
    assert crowded[0] == 503
    assert [answer[0] for answer in held] == [200]
    assert len(upstream.received) == 1


@pytest.mark.parametrize(
    "origin",
    ["http://localhost:1", "https://localhost:1/v1", "https://user@localhost:1", "localhost:1"],
)
def test_the_upstream_is_one_https_origin(origin: str) -> None:
    with pytest.raises(ValueError, match="https origin"), live_proxy(KEY, upstream=origin):
        pass


def test_the_upstream_certificate_is_verified(upstream: _FakeUpstream) -> None:
    unverified = ssl.create_default_context()
    unverified.check_hostname = False
    unverified.verify_mode = ssl.CERT_NONE
    with (
        pytest.raises(ValueError, match="verifies"),
        live_proxy(KEY, upstream=upstream.url, tls=unverified),
    ):
        pass
    # The system's trust store does not know the fake upstream's root.
    with live_proxy(KEY, upstream=upstream.url) as proxy:
        status, _, _ = _call(proxy, "POST", "/v1/messages", headers=_with_token(proxy), body=b"{}")

    assert status == 502
    assert upstream.received == []


@pytest.mark.parametrize(
    ("x_api_key", "authorization", "status"),
    [
        # The x-api-key decides whenever it is present, whatever the other header says.
        ("{token}", "Bearer guess", 200),
        ("{token}", "Basic guess", 200),
        ("", "Bearer {token}", 401),
    ],
)
def test_with_both_token_headers_the_x_api_key_decides_and_neither_is_forwarded(
    upstream: _FakeUpstream, x_api_key: str, authorization: str, status: int
) -> None:
    with live_proxy(KEY, upstream=upstream.url, tls=upstream.tls) as proxy:
        token = proxy.token
        headers = {
            "x-api-key": x_api_key.format(token=token),
            "authorization": authorization.format(token=token),
        }
        answered = _call(proxy, "GET", "/v1/models", headers=headers)

    assert answered[0] == status
    assert len(upstream.received) == (1 if status == 200 else 0)
    for received in upstream.received:
        assert [value for name, value in received["headers"] if name == "x-api-key"] == [FAKE_KEY]
        assert "authorization" not in dict(received["headers"])
        assert not any(token in value or "guess" in value for _, value in received["headers"])


def test_a_body_at_the_cap_is_forwarded_whole(upstream: _FakeUpstream) -> None:
    body = b"x" * MAX_BODY_BYTES
    with live_proxy(KEY, upstream=upstream.url, tls=upstream.tls) as proxy:
        status, _, _ = _call(proxy, "POST", "/v1/messages", headers=_with_token(proxy), body=body)

    assert status == 200
    [received] = upstream.received
    assert received["body"] == body


@pytest.mark.parametrize(
    ("framing", "status"),
    [
        (("transfer-encoding", "chunked"), 411),
        (("content-length", "-1"), 400),
        (("content-length", "ten"), 400),
    ],
)
def test_a_body_without_a_usable_length_is_refused(
    upstream: _FakeUpstream, framing: tuple[str, str], status: int
) -> None:
    with live_proxy(KEY, upstream=upstream.url, tls=upstream.tls) as proxy:
        parts = urlsplit(proxy.url)
        connection = http.client.HTTPConnection(parts.hostname, parts.port, timeout=10)
        connection.putrequest("POST", "/v1/messages")
        connection.putheader("x-api-key", proxy.token)
        connection.putheader(*framing)
        connection.endheaders()
        refused = connection.getresponse().status
        connection.close()

    assert refused == status
    assert upstream.received == []


def test_no_more_than_four_upstream_calls_are_in_flight_at_once(upstream: _FakeUpstream) -> None:
    with live_proxy(KEY, upstream=upstream.url, tls=upstream.tls, call_wait_s=0.3) as proxy:
        threads, held = _calls_in_background(proxy, b'{"hold": 1}', 4)
        poll_until(lambda: len(upstream.received) == 4, timeout_s=10)
        crowded = _call(proxy, "POST", "/v1/messages", headers=_with_token(proxy), body=b"{}")
        in_flight = len(upstream.received)
        upstream.release.set()
        for thread in threads:
            thread.join(timeout=10)
        after = _call(proxy, "POST", "/v1/messages", headers=_with_token(proxy), body=b"{}")

    assert crowded[0] == 503 and in_flight == 4
    assert [answer[0] for answer in held] == [200] * 4
    # Every slot came back once its call ended.
    assert after[0] == 200


@pytest.mark.parametrize(
    "answer",
    [
        (401, {}, b'{"type": "error", "error": {"type": "authentication_error"}}'),
        (429, {"retry-after": "7"}, b'{"type": "error", "error": {"type": "rate_limit_error"}}'),
        (500, {}, b'{"type": "error", "error": {"type": "api_error"}}'),
        (529, {}, b'{"type": "error", "error": {"type": "overloaded_error"}}'),
    ],
    ids=["401", "429", "500", "529"],
)
def test_an_upstream_error_reaches_the_client_as_sent_without_the_key_or_token(
    upstream: _FakeUpstream, capfd: pytest.CaptureFixture[str], answer: _Answer
) -> None:
    status, headers, payload = answer
    upstream.answer = (
        status,
        {
            "content-type": "application/json",
            "request-id": "req-qa",
            "set-cookie": "s=1",
            **headers,
        },
        payload,
    )
    with live_proxy(KEY, upstream=upstream.url, tls=upstream.tls) as proxy:
        token = proxy.token
        relayed = _call(proxy, "POST", "/v1/messages", headers=_with_token(proxy), body=b"{}")

    assert (relayed[0], relayed[2]) == (status, payload)
    assert relayed[1]["request-id"] == "req-qa" and "set-cookie" not in relayed[1]
    assert {name: relayed[1][name] for name in headers} == headers
    for secret in (FAKE_KEY, token):
        assert secret not in json.dumps(relayed[1]) and secret.encode() not in relayed[2]
    [received] = upstream.received
    assert dict(received["headers"])["x-api-key"] == FAKE_KEY
    assert capfd.readouterr() == ("", "")


def test_a_slow_upstream_stream_reaches_the_client_as_it_arrives(upstream: _FakeUpstream) -> None:
    with live_proxy(KEY, upstream=upstream.url, tls=upstream.tls) as proxy:
        parts = urlsplit(proxy.url)
        connection = http.client.HTTPConnection(parts.hostname, parts.port, timeout=10)
        connection.request("POST", "/v1/messages", body=b'{"slow": 1}', headers=_with_token(proxy))
        answer = connection.getresponse()
        early = b""
        # The upstream holds its second event until the client has read the first.
        while b"message_start" not in early:
            early += answer.read1(65536)
        upstream.release.set()
        rest = answer.read()
        connection.close()

    assert answer.status == 200
    assert b"message_stop" not in early
    assert early + rest == STREAM


def test_an_upstream_that_never_answers_times_out_and_frees_its_slot(
    upstream: _FakeUpstream, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(_live_proxy, "UPSTREAM_TIMEOUT_S", 0.5)
    with live_proxy(
        KEY, upstream=upstream.url, tls=upstream.tls, max_upstream_calls=1, call_wait_s=0.3
    ) as proxy:
        hung = _call(
            proxy, "POST", "/v1/messages", headers=_with_token(proxy), body=b'{"hold": 1}'
        )
        after = _call(proxy, "POST", "/v1/messages", headers=_with_token(proxy), body=b"{}")

    assert hung[0] == 502 and FAKE_KEY.encode() not in hung[2]
    assert after[0] == 200


@pytest.mark.parametrize("phase", ["waiting", "streaming"])
def test_a_client_that_disconnects_mid_call_frees_its_upstream_slot(
    upstream: _FakeUpstream, capfd: pytest.CaptureFixture[str], phase: str
) -> None:
    body = b'{"hold": 1}' if phase == "waiting" else b'{"slow": 1}'
    with live_proxy(
        KEY, upstream=upstream.url, tls=upstream.tls, max_upstream_calls=1, call_wait_s=5
    ) as proxy:
        client = _open_call(proxy, body)
        if phase == "streaming":
            client.recv(65536)
        poll_until(lambda: len(upstream.received) == 1, timeout_s=10)
        # An abortive close, so the proxy's next write to this client fails.
        client.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, struct.pack("ii", 1, 0))
        client.close()
        upstream.release.set()
        # Waits for the one slot, which a leaked call would never give back.
        after = _call(proxy, "POST", "/v1/messages", headers=_with_token(proxy), body=b"{}")

    assert after[0] == 200
    assert len(upstream.received) == 2
    assert capfd.readouterr() == ("", "")


def test_a_body_the_client_cut_short_is_not_forwarded(upstream: _FakeUpstream) -> None:
    with live_proxy(KEY, upstream=upstream.url, tls=upstream.tls) as proxy:
        client = _open_call(proxy, b'{"model": "x"}', declared=1000)
        # The body ends 986 bytes early; the proxy closes once it has handled the call.
        client.shutdown(socket.SHUT_WR)
        reply = b""
        while chunk := client.recv(65536):
            reply += chunk
        client.close()

    assert reply.startswith(b"HTTP/1.1 400"), reply[:80]
    assert upstream.received == []


def test_the_key_is_taken_only_as_a_secret_that_never_shows_itself(tmp_path: Path) -> None:
    with pytest.raises(TypeError, match="Secret"), live_proxy(FAKE_KEY):
        pass

    shown = [repr(KEY), str(KEY), f"{KEY}", repr([KEY]), repr({"key": KEY})]
    assert not any(FAKE_KEY in text for text in shown), shown
    assert KEY.reveal() == FAKE_KEY
    (tmp_path / "holds").write_bytes(b"x" + FAKE_KEY.encode())
    (tmp_path / "clean").write_bytes(b"elsewhere")
    assert KEY.found_in(tmp_path / "holds") and not KEY.found_in(tmp_path / "clean")


def test_a_connection_open_at_teardown_is_cut_and_forwards_nothing(
    upstream: _FakeUpstream,
) -> None:
    with live_proxy(KEY, upstream=upstream.url, tls=upstream.tls) as proxy:
        port = urlsplit(proxy.url).port
        # An admitted call whose body is still to come: the proxy is reading it.
        client = _open_call(proxy, b"", declared=2)

        def accepted() -> bool:
            ends = [
                conn
                for conn in psutil.Process().net_connections(kind="tcp")
                if conn.status == psutil.CONN_ESTABLISHED
                and port in (conn.laddr.port, conn.raddr.port if conn.raddr else None)
            ]
            return len(ends) == 2

        poll_until(accepted, timeout_s=10, interval_s=0.05)
    try:
        client.sendall(b"{}")
        reply = client.recv(65536)
    except OSError:
        reply = b""
    finally:
        client.close()

    assert not reply.startswith(b"HTTP/1.1 200"), reply[:80]
    assert upstream.received == []


def test_the_proxy_writes_no_tls_key_log(
    upstream: _FakeUpstream, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    key_log = tmp_path / "tls-keys.log"
    monkeypatch.setenv("SSLKEYLOGFILE", str(key_log))
    # A context made with the variable set would log every session's secrets.
    tls = ssl.create_default_context(cafile=upstream.ca_file)
    assert tls.keylog_filename == str(key_log)
    with live_proxy(KEY, upstream=upstream.url, tls=tls) as proxy:
        status, _, _ = _call(proxy, "GET", "/v1/models", headers=_with_token(proxy))

    assert status == 200
    # Only the header Python writes when the variable is read; no session secret.
    logged = [line for line in key_log.read_text().splitlines() if not line.startswith("#")]
    assert logged == [], len(logged)


def test_a_failing_live_run_shows_its_key_nowhere_in_the_report(tmp_path: Path) -> None:
    # A fake key; the child stops before any stack starts, so nothing leaves loopback.
    fake = "fake-live-key-5e1d7a0c"
    (tmp_path / "fail_live.py").write_text(_FAIL_LIVE_PLUGIN)
    env = {name: value for name, value in os.environ.items() if not name.startswith("PYTEST")}
    env.update(
        CORAL_E2E_LIVE="1",
        ANTHROPIC_API_KEY=fake,
        PYTHONPATH=os.pathsep.join([str(tmp_path), str(ROOT)]),
    )
    done = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            LIVE_TEST,
            "-p",
            "fail_live",
            "-p",
            "no:cacheprovider",
            "-p",
            "no:randomly",
            "--reruns",
            "0",
            # Everything pytest can show of a failure: locals, long tracebacks, all sections.
            "-l",
            "--tb=long",
            "-rA",
            f"--basetemp={tmp_path / 'inner'}",
        ],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=180,
        check=False,
    )
    report = done.stdout + done.stderr

    assert done.returncode == 1, report[-3000:]
    assert "the live run failed on purpose" in report and "1 failed" in report, report[-3000:]
    assert fake not in report
