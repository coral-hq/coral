from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import tests.e2e.coral._claude_config_probe as probe
from tests.e2e.coral._claude_sdk_kit import apply_env, install_keychain_stubs, mock_only_env

_PROXY = "http://127.0.0.1:9"
_INHERITED = {
    "PATH": "/usr/bin",
    "LANG": "en_US.UTF-8",
    "PYTEST_XDIST_WORKER": "gw0",
    "ANTHROPIC_API_KEY": "sk-real",
    "ANTHROPIC_AUTH_TOKEN": "real-token",
    "CLAUDE_CODE_OAUTH_TOKEN": "oauth-real",
    "CLAUDE_CODE_USE_BEDROCK": "1",
    "CLAUDE_CODE_USE_VERTEX": "1",
    "CLAUDE_CODE_USE_FOUNDRY": "1",
    "ANTHROPIC_CUSTOM_HEADERS": "x-key: real",
    "ANTHROPIC_MODEL": "claude-real",
    "AWS_PROFILE": "prod",
    "AWS_SECRET_ACCESS_KEY": "aws-real",
    "GOOGLE_APPLICATION_CREDENTIALS": "/real.json",
    "CLAUDE_CONFIG_DIR": "/Users/real/.claude",
    "no_proxy": "*",
    "all_proxy": "socks5://real",
    "https_proxy": "http://real-proxy",
}


def test_mock_only_env_keeps_allowlist_and_routes_every_proxy_name_to_recorder(
    tmp_path: Path,
) -> None:
    environ = dict(_INHERITED)
    home = Path("/tmp/claude-home")
    stubs = install_keychain_stubs(tmp_path / "keychain-stubs" / "bin")
    # The caller's PATH alone finds the keychain programs elsewhere, or nowhere.
    assert stubs.bypassed(environ["PATH"]) == ["security", "gh"]

    apply_env(
        mock_only_env(
            home=home,
            base_url="http://127.0.0.1:5123",
            proxy_url=_PROXY,
            inherited=environ,
            stubs=stubs,
        ),
        environ,
    )

    # By resolution only: the CLI's keychain lookups by name stop at the kit's own stand-ins.
    assert stubs.bypassed(environ["PATH"]) == []
    assert environ["PATH"].split(os.pathsep)[1:] == ["/usr/bin"]

    for proxy_name in ("HTTPS_PROXY", "HTTP_PROXY", "ALL_PROXY"):
        assert environ[proxy_name] == environ[proxy_name.lower()] == _PROXY
    assert environ["NO_PROXY"] == environ["no_proxy"] == "127.0.0.1,localhost"
    assert environ["HOME"] == environ["CLAUDE_CONFIG_DIR"] == str(home)
    assert environ["ANTHROPIC_BASE_URL"] == "http://127.0.0.1:5123"
    assert {"PATH", "LANG", "PYTEST_XDIST_WORKER"} <= environ.keys()
    leaked = [
        name
        for name in environ
        if any(part in name for part in ("TOKEN", "KEY", "USE_", "HEADERS", "MODEL"))
        or name.startswith(("AWS_", "GOOGLE_"))
    ]
    assert leaked == []


def test_the_config_probe_finds_a_model_key_in_its_environment_by_digest_alone(
    tmp_path: Path,
) -> None:
    key = "sk-ant-test-0123456789abcdef"
    environs = {
        "clean": {"PATH": "/usr/bin:/bin", probe.PROXY_TOKEN: "session"},
        "holding": {"PATH": "/usr/bin:/bin", "ANY_NAME": f"Bearer {key} trailing"},
    }
    home = tmp_path / "home"
    probe.seed_claude_home(home)
    found = {}
    for name, environ in environs.items():
        report = tmp_path / f"{name}.txt"
        argv = [sys.executable, probe.__file__, str(report), str(home), ""]
        done = subprocess.run(
            [*argv, probe.secret_spec(key)], env=environ, cwd=tmp_path, capture_output=True
        )
        assert done.returncode == 0
        lines = report.read_text().splitlines()
        found[name] = [line for line in lines if line.startswith(("proxy_token ", "model_key "))]
    spec = probe.secret_spec(key)
    assert key not in spec and spec.startswith(f"{len(key)}:")
    assert found == {
        "clean": ["proxy_token yes", "model_key no"],
        "holding": ["proxy_token no", "model_key yes"],
    }
