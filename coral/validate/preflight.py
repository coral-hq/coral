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
CheckName = Literal["auth", "host_online", "sandbox"]
CheckStatus = Literal["ok", "warn", "fail"]
CredentialKind = Literal["api_key", "provider", "none", "invalid"]
SandboxBackend = Literal["bwrap", "seatbelt"]

CLAUDE_SDK_HARNESS = "claude-sdk"
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
    host_online: bool
    sandbox: SandboxBackend | None
    steps: tuple[StepNeeds, ...]


def sandbox_from_capabilities(capabilities: Iterable[str]) -> SandboxBackend | None:
    """Read the host's OS sandbox backend from its hello capability tokens.

    Accepts ``os_sandbox:<platform_backend>`` and the richer
    ``coral_host_sandbox:1:<platform>:<backend>:<available>`` report.
    """
    for token in capabilities:
        if token in _OS_SANDBOX_TOKENS:
            return _OS_SANDBOX_TOKENS[token]
        if token.startswith(_HOST_SANDBOX_REPORT_PREFIX):
            parts = token.removeprefix(_HOST_SANDBOX_REPORT_PREFIX).split(":")
            if len(parts) == 3 and parts[2] == "1" and parts[1] in _REPORTED_BACKENDS:
                return _REPORTED_BACKENDS[parts[1]]
    return None


def _fail(check: CheckName, message: str, target: FixTarget) -> PreflightItem:
    return PreflightItem(check=check, status="fail", message=message, fix=Fix(target=target))


def _auth_item(facts: PreflightFacts) -> PreflightItem:
    if facts.credential in ("api_key", "provider"):
        return PreflightItem(check="auth", status="ok", message="Claude has an API credential.")
    if facts.credential == "invalid":
        detail = facts.credential_detail or "the configured provider could not be resolved"
        return _fail("auth", f"The Claude API credential is not usable: {detail}", "add_api_key")
    return _fail("auth", API_KEY_REQUIRED_MESSAGE, "add_api_key")


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
        return _fail("sandbox", SANDBOX_MISSING_MESSAGE, "install_bwrap")
    return PreflightItem(
        check="sandbox", status="ok", message=f"The host has an OS sandbox ({facts.sandbox})."
    )


def run_preflight(facts: PreflightFacts) -> PreflightReport:
    """Check auth, host and sandbox in that order, one item per applicable check."""
    items: list[PreflightItem] = []
    if any(step.harness == CLAUDE_SDK_HARNESS for step in facts.steps):
        items.append(_auth_item(facts))
    items.append(_host_item(facts))
    if any(step.needs_fs_sandbox for step in facts.steps):
        items.append(_sandbox_item(facts))
    return PreflightReport(items=tuple(items))
