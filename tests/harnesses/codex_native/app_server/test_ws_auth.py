# CORAL(S113): tests for the per-spawn token on the codex-native app-server WebSocket
"""The per-spawn capability token on the codex-native app-server WebSocket."""

from __future__ import annotations

import asyncio
import logging
import os
import socket
import stat
import sys
from pathlib import Path

import pytest
from websockets.asyncio.server import ServerConnection, serve

from omnigent.harnesses.codex_native import app_server
from omnigent.harnesses.codex_native import bridge as codex_bridge
from omnigent.harnesses.codex_native.app_server import (
    CodexAppServerClient,
    CodexNativeAppServer,
    _build_native_codex_app_server_argv,
    _CodexModelDiscoveryProcess,
    _start_codex_model_discovery_process,
    _stop_codex_model_discovery_process,
    build_codex_remote_args,
    codex_supports_ws_auth,
    codex_terminal_env,
    codex_ws_token_path,
    mint_codex_ws_token,
    read_codex_ws_token,
)
from omnigent.harnesses.codex_native.launch_args import reserved_codex_transport_arg

_ENV_VAR = "OMNIGENT_CODEX_WS_TOKEN"


@pytest.fixture(autouse=True)
def _isolated_token_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "codex-native"
    monkeypatch.setattr(codex_bridge, "_BRIDGE_ROOT", root)
    monkeypatch.setattr(app_server, "_ws_auth_support_cache", {})
    return root


def _fake_codex(tmp_path: Path, *, ws_auth: bool) -> Path:
    """A codex stand-in: ``app-server --help`` lists ``--ws-auth`` or not; otherwise it idles."""
    help_text = "--listen <URL>\n" + ("--ws-auth <MODE>\n" if ws_auth else "")
    script = tmp_path / ("codex-new" if ws_auth else "codex-old")
    script.write_text(
        f"#!{sys.executable}\n"
        "import sys, time\n"
        "if '--version' in sys.argv:\n"
        "    print('codex-cli 0.100.0')\n"
        "elif '--help' in sys.argv:\n"
        f"    print({help_text!r})\n"
        "else:\n"
        "    time.sleep(60)\n"
    )
    script.chmod(0o755)
    return script


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def test_argv_carries_token_file_after_listen_and_no_token(tmp_path: Path) -> None:
    token_file = mint_codex_ws_token(4242)
    argv = _build_native_codex_app_server_argv(
        tagged_argv0="codex",
        listen_url="ws://127.0.0.1:4242",
        config_overrides=[],
        ws_token_file=token_file,
    )
    assert argv[-6:] == [
        "--listen",
        "ws://127.0.0.1:4242",
        "--ws-auth",
        "capability-token",
        "--ws-token-file",
        str(token_file),
    ]
    token = read_codex_ws_token(4242)
    assert token and token not in " ".join(argv)
    assert _build_native_codex_app_server_argv(
        tagged_argv0="codex", listen_url="ws://127.0.0.1:4242", config_overrides=[]
    )[-2:] == ["--listen", "ws://127.0.0.1:4242"]


def test_token_file_is_private_and_overwrites_a_stale_one(_isolated_token_root: Path) -> None:
    path = mint_codex_ws_token(4243)
    assert path == codex_ws_token_path(4243) == _isolated_token_root / "ws-tokens" / "4243"
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert stat.S_IMODE(path.parent.stat().st_mode) == 0o700
    first = path.read_text()
    assert len(first) >= 32 and "\n" not in first
    mint_codex_ws_token(4243)
    assert read_codex_ws_token(4243) not in {None, first}


def test_symlinked_token_dir_is_refused(_isolated_token_root: Path, tmp_path: Path) -> None:
    _isolated_token_root.mkdir(parents=True, mode=0o700)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir(mode=0o700)
    (_isolated_token_root / "ws-tokens").symlink_to(elsewhere)
    with pytest.raises(RuntimeError, match="symlink"):
        mint_codex_ws_token(4244)
    assert list(elsewhere.iterdir()) == []


def test_read_token_never_raises(_isolated_token_root: Path) -> None:
    assert read_codex_ws_token(4245) is None
    codex_ws_token_path(4245).mkdir(parents=True)  # a dir, not a file
    assert read_codex_ws_token(4245) is None


async def test_capability_probe_is_cached_per_path(tmp_path: Path) -> None:
    new = _fake_codex(tmp_path, ws_auth=True)
    calls = tmp_path / "help-calls"
    new.write_text(
        new.read_text().replace(
            "elif '--help' in sys.argv:\n",
            f"elif '--help' in sys.argv:\n    open({str(calls)!r}, 'a').write('x')\n",
        )
    )
    assert await codex_supports_ws_auth(str(new)) is True
    assert await codex_supports_ws_auth(str(new)) is True
    assert calls.read_text() == "x"


async def test_a_probe_that_cannot_run_fails_closed_and_is_not_cached(tmp_path: Path) -> None:
    codex = tmp_path / "codex-late"
    assert await codex_supports_ws_auth(str(codex)) is True  # missing: pass --ws-auth anyway
    codex.write_bytes(_fake_codex(tmp_path, ws_auth=False).read_bytes())
    codex.chmod(0o755)
    assert await codex_supports_ws_auth(str(codex)) is False  # probed again, now definite


async def test_old_codex_launches_without_auth_and_warns_once(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    old = str(_fake_codex(tmp_path, ws_auth=False))
    port = _free_port()
    codex_ws_token_path(port).parent.mkdir(parents=True, mode=0o700)
    codex_ws_token_path(port).write_text("stale")
    with caplog.at_level(logging.WARNING, logger=app_server.__name__):
        assert await app_server._codex_ws_token_file(old, f"ws://127.0.0.1:{port}") is None
        assert await app_server._codex_ws_token_file(old, f"ws://127.0.0.1:{port}") is None
    warnings = [r for r in caplog.records if "--ws-auth" in r.getMessage()]
    assert len(warnings) == 1 and "0.100.0" in warnings[0].getMessage()
    assert read_codex_ws_token(port) is None  # a stale file would make clients send a token


async def test_no_token_for_unix_or_non_loopback_listen(tmp_path: Path) -> None:
    new = str(_fake_codex(tmp_path, ws_auth=True))
    assert await app_server._codex_ws_token_file(new, "unix:///tmp/x.sock") is None
    assert await app_server._codex_ws_token_file(new, "ws://10.1.2.3:4000") is None


async def _initialize_server(seen: list[str | None]) -> tuple[object, int]:
    async def handler(ws: ServerConnection) -> None:
        seen.append(ws.request.headers.get("Authorization") if ws.request else None)
        async for raw in ws:
            if '"initialize"' in str(raw):
                await ws.send('{"id": 1, "result": {}}')

    server = await serve(handler, "127.0.0.1", 0)
    port = next(iter(server.sockets)).getsockname()[1]
    return server, port


async def test_connect_sends_bearer_only_when_a_token_file_exists(
    caplog: pytest.LogCaptureFixture,
) -> None:
    seen: list[str | None] = []
    server, port = await _initialize_server(seen)
    try:
        client = CodexAppServerClient(ws_url=f"ws://127.0.0.1:{port}")
        await client.connect()
        await client.close()
        mint_codex_ws_token(port)
        token = read_codex_ws_token(port)
        client = CodexAppServerClient(ws_url=f"ws://127.0.0.1:{port}")
        with caplog.at_level(logging.DEBUG):
            await client.connect()
        await client.close()
    finally:
        server.close()  # type: ignore[attr-defined]
        await server.wait_closed()  # type: ignore[attr-defined]
    assert seen == [None, f"Bearer {token}"]
    # websockets logs request headers at DEBUG; the client must not (the test server may).
    client_logs = [r for r in caplog.records if not r.name.startswith("websockets.server")]
    assert token and not any(token in r.getMessage() for r in client_logs)


@pytest.mark.parametrize("host", ["10.0.0.5", "localhost"])
async def test_connect_sends_no_header_to_a_non_loopback_host(
    host: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    mint_codex_ws_token(4246)
    captured: dict[str, object] = {}

    async def fake_connect(url: str, **kwargs: object) -> object:
        captured.update(kwargs)
        raise OSError("stop here")

    monkeypatch.setattr(app_server.websockets, "connect", fake_connect)
    with pytest.raises(OSError):
        await CodexAppServerClient(ws_url=f"ws://{host}:4246").connect()
    assert captured["additional_headers"] is None


@pytest.mark.parametrize(
    ("thread_id", "version"), [(None, None), ("thread_1", (0, 150, 0)), ("thread_1", None)]
)
def test_remote_args_name_the_token_env_only_with_a_token(
    thread_id: str | None, version: tuple[int, int, int] | None
) -> None:
    url = "ws://127.0.0.1:4247"
    kwargs = {"codex_args": (), "thread_id": thread_id, "codex_cli_version": version}
    assert "--remote-auth-token-env" not in build_codex_remote_args(remote_url=url, **kwargs)
    mint_codex_ws_token(4247)
    args = build_codex_remote_args(remote_url=url, **kwargs)
    remote = args.index("--remote")
    assert args[remote + 1 : remote + 4] == [url, "--remote-auth-token-env", _ENV_VAR], args
    if thread_id is not None:
        assert args[-1] == thread_id
    assert "--remote-auth-token-env" not in build_codex_remote_args(
        remote_url="unix:///tmp/codex.sock", **kwargs
    )


def test_terminal_env_carries_the_token_only_when_present(tmp_path: Path) -> None:
    server = CodexNativeAppServer(
        codex_path="codex",
        socket_path=tmp_path / "s.sock",
        codex_home=tmp_path / "home",
        env={},
        config_overrides=[],
        cwd=tmp_path,
        bridge_dir=tmp_path / "bridge",
        listen_url="ws://127.0.0.1:4248",
    )
    assert _ENV_VAR not in codex_terminal_env(server)
    mint_codex_ws_token(4248)
    assert codex_terminal_env(server)[_ENV_VAR] == read_codex_ws_token(4248)


@pytest.mark.parametrize(
    "args",
    [("--remote-auth-token-env", "X"), ("--model", "m", "--remote-auth-token-env=X")],
)
def test_caller_remote_auth_token_env_is_reserved(args: tuple[str, ...]) -> None:
    assert reserved_codex_transport_arg(args) == "--remote-auth-token-env"


async def test_close_removes_the_token_file(tmp_path: Path) -> None:
    server = CodexNativeAppServer(
        codex_path="codex",
        socket_path=tmp_path / "s.sock",
        codex_home=tmp_path / "home",
        env={},
        config_overrides=[],
        cwd=tmp_path,
        bridge_dir=tmp_path / "bridge",
        listen_url="ws://127.0.0.1:4249",
    )
    mint_codex_ws_token(4249)
    await server.close()  # a wrapper that never spawned it leaves the token alone
    assert read_codex_ws_token(4249) is not None
    server.process_registry_tag = "codex-native-test"
    await server.close()
    assert read_codex_ws_token(4249) is None


async def test_discovery_process_mints_and_removes_its_token(tmp_path: Path) -> None:
    new = str(_fake_codex(tmp_path, ws_auth=True))
    port = _free_port()
    discovery = await _start_codex_model_discovery_process(
        codex_path=new,
        listen_url=f"ws://127.0.0.1:{port}",
        env=dict(os.environ),
        cwd=tmp_path,
    )
    assert isinstance(discovery, _CodexModelDiscoveryProcess)
    try:
        assert read_codex_ws_token(port) is not None
        cmdline = await asyncio.to_thread(
            lambda: os.popen(f"ps -o args= -p {discovery.process.pid}").read()
        )
        assert f"--ws-token-file {codex_ws_token_path(port)}" in cmdline
    finally:
        await _stop_codex_model_discovery_process(discovery)
    assert read_codex_ws_token(port) is None


async def test_discovery_spawn_failure_removes_its_token(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def fail_spawn(*args: object, **kwargs: object) -> None:
        raise OSError("spawn failed")

    monkeypatch.setattr(app_server.asyncio, "create_subprocess_exec", fail_spawn)
    port = _free_port()
    with pytest.raises(OSError, match="spawn failed"):
        await _start_codex_model_discovery_process(
            codex_path=str(_fake_codex(tmp_path, ws_auth=True)),
            listen_url=f"ws://127.0.0.1:{port}",
            env=dict(os.environ),
            cwd=tmp_path,
        )
    assert not codex_ws_token_path(port).exists()


def test_route_turn_hook_finds_the_token_under_codex_clean_env(
    _isolated_token_root: Path, tmp_path: Path
) -> None:
    """Codex runs the hook with OMNIGENT_* stripped; the command must carry the data dir."""
    import subprocess

    from omnigent.inner.codex_executor import _clean_codex_env

    command = app_server._codex_route_turn_hook(tmp_path / "bridge", sys.executable)["command"]
    prefix = str(command).split(f" {sys.executable}", 1)[0]
    probe = (
        "from omnigent.harnesses.codex_native.app_server import codex_ws_token_path;"
        "print(codex_ws_token_path(1))"
    )
    out = subprocess.run(
        ["/bin/sh", "-c", f"{prefix} {sys.executable} -c '{probe}'"],
        env=_clean_codex_env(),
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    assert out == str(_isolated_token_root / "ws-tokens" / "1")
