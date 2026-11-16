"""Policies every Coral step bundle carries."""

from __future__ import annotations

from omnigent.policies.schema import PolicyEvent, PolicyResponse

VENDOR_ASK_TOOL = "AskUserQuestion"
_DENY_REASON = (
    "Coral steps run unattended, so they cannot ask questions. "
    "State your assumption in your report and continue."
)


def deny_vendor_ask(event: PolicyEvent) -> PolicyResponse:
    """
    Deny the claude CLI's ``AskUserQuestion`` tool and allow everything else.

    :param event: A V0 policy event.
    :returns: DENY for an ``AskUserQuestion`` tool call, ALLOW otherwise.
    """
    data = event.get("data")
    if event.get("type") == "tool_call" and isinstance(data, dict):
        if data.get("name") == VENDOR_ASK_TOOL:
            return {"result": "DENY", "reason": _DENY_REASON}
    return {"result": "ALLOW"}


POLICY_REGISTRY: list[dict[str, object]] = [
    {
        "handler": "coral.omni.policies.hygiene.deny_vendor_ask",
        "kind": "callable",
        "name": "Deny Vendor Questions in Coral Steps",
        "description": "Denies the claude CLI's AskUserQuestion tool so an unattended "
        "Coral step never waits on a question.",
        "params_schema": None,
    },
]
