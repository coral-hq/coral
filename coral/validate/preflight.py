"""Run preflight: turns host and credential facts into a report that names one fix per failure."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Literal

from pydantic import BaseModel, ConfigDict, computed_field

FixTarget = Literal[
    "install_harness",
    "sign_in",
    "add_api_key",
    "connect_host",
    "update_host",
    "install_bwrap",
    "fix_workflow",
]
CheckName = Literal["auth", "host_online", "sandbox", "system_claude"]
CheckStatus = Literal["ok", "warn", "fail"]
CredentialKind = Literal["api_key", "provider", "none", "invalid"]
SandboxBackend = Literal["bwrap", "seatbelt"]
HostSandbox = Literal["bwrap", "seatbelt", "none"]

CLAUDE_SDK_HARNESS = "claude-sdk"
CLAUDE_NATIVE_HARNESS = "claude-native"
CLAUDE_HARNESSES = frozenset({CLAUDE_SDK_HARNESS, CLAUDE_NATIVE_HARNESS})
CLAUDE_SDK_CAPABILITIES: dict[str, object] = {
    "tool_call_gating": "all_tools",
    "fs_sandbox_backends": ("bwrap", "seatbelt"),
}

API_KEY_REQUIRED_MESSAGE = (
    "Workflows with an orchestrator need an Anthropic API key "
    "(Console, plan-linked Console, or cloud provider)."
)
SANDBOX_MISSING_MESSAGE = (
    "Steps that read or change files need an OS sandbox: install bwrap on Linux; "
    "macOS uses sandbox-exec. Windows hosts can't run these steps."
)
SANDBOX_UNREPORTED_MESSAGE = (
    "The host does not report its OS sandbox. Update Coral on the host to run steps "
    "that read or change files."
)
SYSTEM_CLAUDE_MISSING_MESSAGE = (
    "Sandboxed Claude steps need a system Claude CLI on the host "
    "(install Claude, or set OMNIGENT_CLAUDE_PATH). The SDK's bundled CLI cannot be wrapped."
)
SYSTEM_CLAUDE_UNREPORTED_MESSAGE = (
    "The host does not report whether a system Claude CLI is installed. "
    "Update Coral on the host to run sandboxed Claude steps."
)

_OS_SANDBOX_PREFIX = "os_sandbox:"
_OS_SANDBOX_TOKENS: dict[str, SandboxBackend] = {
    "os_sandbox:linux_bwrap": "bwrap",
    "os_sandbox:darwin_seatbelt": "seatbelt",
}
_HOST_SANDBOX_REPORT_PREFIX = "coral_host_sandbox:1:"
_REPORTED_BACKENDS: dict[str, SandboxBackend] = {"bwrap": "bwrap", "seatbelt": "seatbelt"}


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class Fix(_Frozen):
    target: FixTarget
    href: str | None = None


class PreflightItem(_Frozen):
    check: CheckName
    status: CheckStatus
    message: str
    fix: Fix | None = None


class PreflightReport(_Frozen):
    items: tuple[PreflightItem, ...]

    @computed_field
    @property
    def ok(self) -> bool:
        return all(item.status != "fail" for item in self.items)


class StepNeeds(_Frozen):
    step_ref: str
    harness: str
    needs_fs_sandbox: bool


class PreflightFacts(_Frozen):
    credential: CredentialKind
    credential_detail: str | None = None
    credential_step_ref: str | None = None
    host_online: bool
    sandbox: HostSandbox | None
    # Whether the host has a system ``claude`` CLI. ``None`` when offline or unreported.
    system_claude: bool | None = None
    steps: tuple[StepNeeds, ...]


def sandbox_from_capabilities(capabilities: Iterable[str]) -> HostSandbox | None:
    """Read the host's OS sandbox from its hello capability tokens.

    Accepts ``os_sandbox:<platform_backend>`` and the richer
    ``coral_host_sandbox:1:<platform>:<backend>:<available>`` report. A host that
    reports a sandbox Coral cannot use gives ``"none"``; one that reports none gives ``None``.
    """
    for token in capabilities:
        if token.startswith(_OS_SANDBOX_PREFIX):
            return _OS_SANDBOX_TOKENS.get(token, "none")
        if token.startswith(_HOST_SANDBOX_REPORT_PREFIX):
            parts = token.removeprefix(_HOST_SANDBOX_REPORT_PREFIX).split(":")
            if len(parts) == 3:
                available = parts[2] == "1"
                return _REPORTED_BACKENDS.get(parts[1], "none") if available else "none"
    return None


def _fail(check: CheckName, message: str, target: FixTarget) -> PreflightItem:
    return PreflightItem(check=check, status="fail", message=message, fix=Fix(target=target))


def _auth_item(facts: PreflightFacts) -> PreflightItem:
    if facts.credential in ("api_key", "provider"):
        return PreflightItem(check="auth", status="ok", message="Claude has an API credential.")
    step = f" (step {facts.credential_step_ref})" if facts.credential_step_ref else ""
    if facts.credential == "invalid":
        detail = facts.credential_detail or "the configured provider could not be resolved"
        message = f"The Claude API credential is not usable{step}: {detail}"
        return _fail("auth", message, "add_api_key")
    return _fail("auth", f"{API_KEY_REQUIRED_MESSAGE}{step}", "add_api_key")


def _host_item(facts: PreflightFacts) -> PreflightItem:
    if facts.host_online:
        return PreflightItem(check="host_online", status="ok", message="The host is connected.")
    return _fail(
        "host_online", "The host is offline. Connect it to start the run.", "connect_host"
    )


def _sandbox_item(facts: PreflightFacts) -> PreflightItem:
    if not facts.host_online:
        return _fail(
            "sandbox", "The OS sandbox is checked once the host connects.", "connect_host"
        )
    if facts.sandbox is None:
        return _fail("sandbox", SANDBOX_UNREPORTED_MESSAGE, "update_host")
    if facts.sandbox == "none":
        return _fail("sandbox", SANDBOX_MISSING_MESSAGE, "install_bwrap")
    return PreflightItem(
        check="sandbox", status="ok", message=f"The host has an OS sandbox ({facts.sandbox})."
    )


def _needs_system_claude(steps: tuple[StepNeeds, ...]) -> bool:
    """Sandboxed Claude steps wrap a system CLI; the SDK's bundled one cannot be wrapped."""
    return any(step.needs_fs_sandbox and step.harness in CLAUDE_HARNESSES for step in steps)


def _system_claude_item(facts: PreflightFacts) -> PreflightItem:
    if not facts.host_online:
        return _fail(
            "system_claude",
            "The system Claude CLI is checked once the host connects.",
            "connect_host",
        )
    if facts.system_claude is None:
        return _fail("system_claude", SYSTEM_CLAUDE_UNREPORTED_MESSAGE, "update_host")
    if not facts.system_claude:
        return _fail("system_claude", SYSTEM_CLAUDE_MISSING_MESSAGE, "install_harness")
    return PreflightItem(
        check="system_claude",
        status="ok",
        message="The host has a system Claude CLI for sandboxed steps.",
    )


def run_preflight(facts: PreflightFacts) -> PreflightReport:
    """Check auth, host, sandbox and system Claude in that order, one item per applicable check."""
    items: list[PreflightItem] = []
    if any(step.harness == CLAUDE_SDK_HARNESS for step in facts.steps):
        items.append(_auth_item(facts))
    items.append(_host_item(facts))
    if any(step.needs_fs_sandbox for step in facts.steps):
        items.append(_sandbox_item(facts))
    if _needs_system_claude(facts.steps):
        items.append(_system_claude_item(facts))
    return PreflightReport(items=tuple(items))
