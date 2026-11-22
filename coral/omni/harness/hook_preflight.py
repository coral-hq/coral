"""CLI version and hooks-installed checks for native fail-closed launches."""

from __future__ import annotations

from dataclasses import dataclass

from omnigent.native.native_policy_hook import (
    POLICY_FAILURE_MODE_FAIL_CLOSED,
    normalize_policy_failure_mode,
)
from omnigent.onboarding.harness_install import harness_cli_version

# Floor cited by RUL-04 for Claude Code ``onFailure: block`` (DD§10.5).
# Conservative until a live probe records a tighter bound.
_CLAUDE_NATIVE_FAIL_CLOSED_FLOOR = (2, 1, 295)


@dataclass(frozen=True)
class HookPreflightResult:
    """Whether a native launch may use fail-closed policy hooks."""

    ok: bool
    reason: str | None = None


def _parse_semver(version: str | None) -> tuple[int, int, int] | None:
    if not version:
        return None
    parts: list[int] = []
    for piece in version.strip().lstrip("v").split("."):
        digits = "".join(ch for ch in piece if ch.isdigit())
        if not digits:
            break
        parts.append(int(digits))
        if len(parts) == 3:
            break
    if len(parts) < 2:
        return None
    while len(parts) < 3:
        parts.append(0)
    return parts[0], parts[1], parts[2]


def check_fail_closed_launch(
    *,
    harness_key: str,
    policy_failure_mode: object | None,
    ap_server_url: str | None,
) -> HookPreflightResult:
    """Refuse fail-closed native launches without a server URL or below the CLI floor.

    Interactive ``ask`` mode always passes. Non-claude harnesses only require a
    server URL when fail-closed (Codex floor is tracked under HRN-05).
    """
    if normalize_policy_failure_mode(policy_failure_mode) != POLICY_FAILURE_MODE_FAIL_CLOSED:
        return HookPreflightResult(ok=True)
    if not isinstance(ap_server_url, str) or not ap_server_url.strip():
        return HookPreflightResult(
            ok=False,
            reason="fail_closed native hooks require ap_server_url",
        )
    if harness_key in {"claude-native", "claude"}:
        version, _required = harness_cli_version("claude")
        parsed = _parse_semver(version)
        if parsed is None:
            return HookPreflightResult(
                ok=False,
                reason="could not read Claude Code CLI version for fail_closed floor",
            )
        if parsed < _CLAUDE_NATIVE_FAIL_CLOSED_FLOOR:
            floor = ".".join(str(part) for part in _CLAUDE_NATIVE_FAIL_CLOSED_FLOOR)
            return HookPreflightResult(
                ok=False,
                reason=f"Claude Code CLI {version} is below fail_closed floor {floor}",
            )
    return HookPreflightResult(ok=True)


__all__ = ["HookPreflightResult", "check_fail_closed_launch"]
