from __future__ import annotations

from pathlib import Path

from tests.e2e.coral._claude_sdk_kit import apply_env, mock_only_env

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


def test_mock_only_env_keeps_allowlist_and_routes_every_proxy_name_to_recorder() -> None:
    environ = dict(_INHERITED)
    home = Path("/tmp/claude-home")

    apply_env(
        mock_only_env(
            home=home, base_url="http://127.0.0.1:5123", proxy_url=_PROXY, inherited=environ
        ),
        environ,
    )

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
