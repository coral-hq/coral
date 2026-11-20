"""Turn one finished tool call into a :class:`CommandObservation` (pure).

claude-sdk steps run shell commands, writes and edits through Omnigent's ``sys_os_*``
tools. ``sys_os_shell`` returns a JSON envelope whose ``exit_code`` is ``None`` on a
timeout; the exit code comes only from it, never from printed text.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping

from coral.evidence.ir import CommandObservation, ObservedTool

_TOOLS: dict[str, ObservedTool] = {
    "sys_os_shell": "shell",
    "sys_os_write": "write",
    "sys_os_edit": "edit",
}
_MCP_PREFIX = "mcp__omnigent__"
# A longer command is kept as unknown, so a cut-off ``|| true`` can never count.
MAX_COMMAND_CHARS = 8_000
MAX_PATH_CHARS = 4_096
MAX_OP_KEY_CHARS = 128


def observed_tool(tool_name: str) -> ObservedTool | None:
    """The kind of call evidence records, or ``None`` for any other tool."""
    return _TOOLS.get(tool_name.removeprefix(_MCP_PREFIX))


def op_key_for(operation_id: str | None, fallback: str) -> str:
    """The call's idempotency key: the runner's operation id, else ``fallback``, bounded."""
    key = operation_id or fallback
    if len(key) <= MAX_OP_KEY_CHARS:
        return key
    return "sha256:" + hashlib.sha256(key.encode()).hexdigest()


def shell_exit(output: str) -> tuple[int | None, bool]:
    """``(exit_code, timed_out)`` from a ``sys_os_shell`` envelope; ``(None, False)`` if none."""
    try:
        envelope = json.loads(output)
    except ValueError:
        return None, False
    if not isinstance(envelope, dict) or "exit_code" not in envelope:
        return None, False
    code = envelope.get("exit_code")
    timed_out = envelope.get("timed_out") is True
    if isinstance(code, bool) or not isinstance(code, int):
        return None, timed_out
    return code, timed_out


def observation_from_tool(
    *,
    session_id: str,
    op_key: str,
    obs_seq: int,
    tool_name: str,
    arguments: Mapping[str, object],
    output: str,
    l1_after: str | None,
) -> CommandObservation | None:
    """The observation for one finished call, or ``None`` for a tool evidence ignores."""
    tool = observed_tool(tool_name)
    if tool is None:
        return None
    if tool != "shell":
        path = arguments.get("path")
        changed = path if isinstance(path, str) and 0 < len(path) <= MAX_PATH_CHARS else None
        return CommandObservation(
            session_id=session_id, op_key=op_key, obs_seq=obs_seq, tool=tool, changed_path=changed
        )
    command = arguments.get("command")
    kept = command if isinstance(command, str) and len(command) <= MAX_COMMAND_CHARS else None
    exit_code, timed_out = shell_exit(output)
    return CommandObservation(
        session_id=session_id,
        op_key=op_key,
        obs_seq=obs_seq,
        tool="shell",
        command=kept,
        exit_code=exit_code,
        timed_out=timed_out,
        l1_after=l1_after,
    )


__all__ = [
    "MAX_COMMAND_CHARS",
    "observation_from_tool",
    "observed_tool",
    "op_key_for",
    "shell_exit",
]
