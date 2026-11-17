"""Tool guards each Coral bundle carries by stance.

They are the step roster, the orchestrator allowlist and the anchor's
deny-all. Runners resolve these handlers before an agent starts, so this module
imports only the policy event types and Coral's standard-library tool catalog.
Every guard decides ``tool_call`` events only, allows every other event and
never raises. It reads the call's ``target``, which no earlier policy can
rewrite. Exemptions and allowlists match exact names; only the roster's deny
side uses a prefix, so it also covers cross-session tools added later.
"""

from __future__ import annotations

from collections.abc import Mapping

from coral.tools.catalog import ENGINE_TOOL_NAMES, orchestrator_tool_names
from omnigent.policies.schema import PolicyEvent, PolicyResponse

# The form under which claude-sdk lists Omnigent's own tools.
OMNIGENT_TOOL_PREFIX = "mcp__omnigent__"
TOOL_SEARCH = "ToolSearch"
STEP_ROSTER_PREFIX = "sys_session_"
AGENT_TOOLS = ("Agent", "Task")
# Builtins outside the sys_session_ prefix that read other sessions.
SESSION_READ_TOOLS = ("search_conversations",)
# Codex-family agent spawners, e.g. ``collaborationspawn_agent``; matched casefolded.
SPAWN_AGENT_SUFFIX = "spawn_agent"

_ORCHESTRATOR_TOOLS = orchestrator_tool_names()
_ROSTER_DENY = (
    "[roster] Coral steps cannot start, message or read other sessions or agents. "
    "Put what you need in your handoff report."
)
_ORCHESTRATOR_DENY = (
    "[orchestrator] A Coral orchestrator can only call coral_choose_arrow "
    "(and ToolSearch to load it)."
)
_ANCHOR_DENY = "[anchor] The Coral run anchor does not run tools."


def is_tool_call(event: PolicyEvent) -> bool:
    """Whether *event* is a ``tool_call`` event; ``False`` for anything malformed."""
    return isinstance(event, Mapping) and event.get("type") == "tool_call"


def tool_name(event: PolicyEvent) -> str:
    """
    The called tool's name, or ``""`` when the event names none.

    :param event: A V0 policy event.
    :returns: ``target``, the dispatched tool, which an earlier policy's
        transform cannot change; ``data.name`` only when ``target`` is absent.
    """
    if not isinstance(event, Mapping):
        return ""
    name = event.get("target")
    if name is None:
        data = event.get("data")
        name = data.get("name") if isinstance(data, Mapping) else None
    return name if isinstance(name, str) else ""


def _without_omnigent_prefix(name: str) -> str:
    return name.removeprefix(OMNIGENT_TOOL_PREFIX)


def _engine_tool(name: str) -> str | None:
    """The engine tool *name* calls, bare or after one ``mcp__omnigent__``; ``None`` otherwise."""
    bare = _without_omnigent_prefix(name)
    return bare if bare in ENGINE_TOOL_NAMES else None


def is_engine_tool(name: str) -> bool:
    """
    Whether *name* is exactly one of Coral's engine tools.

    A name alone cannot tell an engine tool from a spec's own tool of the same
    name, so this holds only for a spec that passes Coral's bundle hygiene: no
    local tool takes an engine tool's name and no MCP server is named ``mcp``.

    :param name: A called tool name, e.g. ``"mcp__omnigent__coral_submit_handoff"``.
    :returns: ``True`` for an engine tool's name, bare or after one
        ``mcp__omnigent__``; ``False`` for a look-alike such as ``"coral_x"``.
    """
    return _engine_tool(name) is not None


def is_tool_search(name: str) -> bool:
    """Whether *name* is exactly claude-sdk's ``ToolSearch``, which loads deferred tools."""
    return name == TOOL_SEARCH


def _on_step_roster(name: str) -> bool:
    bare = _without_omnigent_prefix(name)
    return (
        # A call that names no tool cannot be shown to be off the roster.
        not bare
        or bare.startswith(STEP_ROSTER_PREFIX)
        or bare in AGENT_TOOLS
        or bare in SESSION_READ_TOOLS
        or bare.casefold().endswith(SPAWN_AGENT_SUFFIX)
    )


def step_roster(event: PolicyEvent) -> PolicyResponse:
    """
    Deny a step's tool calls that start, message or read other sessions or agents.

    :param event: A V0 policy event.
    :returns: DENY for a ``sys_session_*`` tool or ``search_conversations``
        (bare or ``mcp__omnigent__``), ``Agent``, ``Task``, a ``*spawn_agent``
        tool or a call that names no tool; ALLOW otherwise.
    """
    if is_tool_call(event) and _on_step_roster(tool_name(event)):
        return {"result": "DENY", "reason": _ROSTER_DENY}
    return {"result": "ALLOW"}


def orchestrator_guard(event: PolicyEvent) -> PolicyResponse:
    """
    Allow an orchestrator only its engine tool and ``ToolSearch``.

    :param event: A V0 policy event.
    :returns: ALLOW for ``coral_choose_arrow`` (bare or ``mcp__omnigent__``),
        exactly ``ToolSearch`` and every non-tool-call event; DENY for every
        other tool call.
    """
    if not is_tool_call(event):
        return {"result": "ALLOW"}
    name = tool_name(event)
    if _engine_tool(name) in _ORCHESTRATOR_TOOLS or is_tool_search(name):
        return {"result": "ALLOW"}
    return {"result": "DENY", "reason": _ORCHESTRATOR_DENY}


def deny_all_tools(event: PolicyEvent) -> PolicyResponse:
    """
    Deny every tool call of a run's anchor, which Coral never runs.

    :param event: A V0 policy event.
    :returns: DENY for a tool call, ALLOW for every other event.
    """
    if is_tool_call(event):
        return {"result": "DENY", "reason": _ANCHOR_DENY}
    return {"result": "ALLOW"}


# Internal: bundles name these handlers by stance; users cannot pick them from the listing.
POLICY_REGISTRY: list[dict[str, object]] = [
    {
        "handler": "coral.omni.policies.guards.step_roster",
        "kind": "callable",
        "name": "Coral Step Roster",
        "description": "Denies a Coral step's tool calls that start, message or read other "
        "sessions or agents.",
        "params_schema": None,
        "internal_only": True,
    },
    {
        "handler": "coral.omni.policies.guards.orchestrator_guard",
        "kind": "callable",
        "name": "Coral Orchestrator Allowlist",
        "description": "Allows a Coral orchestrator only coral_choose_arrow and ToolSearch.",
        "params_schema": None,
        "internal_only": True,
    },
    {
        "handler": "coral.omni.policies.guards.deny_all_tools",
        "kind": "callable",
        "name": "Coral Anchor Deny-All",
        "description": "Denies every tool call of a Coral run's anchor session.",
        "params_schema": None,
        "internal_only": True,
    },
]
