"""Resolve MCP policy attribution without changing credential ownership."""

from fastapi import Request

from omnigent.entities import Conversation
from omnigent.runner.identity import RUNNER_TUNNEL_TOKEN_HEADER, token_bound_runner_id
from omnigent.server.routes._sessions.common import _TURN_ACTOR_LABEL
from omnigent.server.routes._sessions.helpers import _build_actor, _is_coral_label_key


def coral_bound(conversation: Conversation) -> bool:
    """CORAL(S49): whether the session is Coral's, by a ``coral.`` label clients cannot set."""
    return any(_is_coral_label_key(key) for key in conversation.labels or {})


# CORAL(S49): the runner-proof rule, shared by the policy actor and server tools.
def runner_proven(request: Request, conversation: Conversation) -> bool:
    """Whether *request* carries a tunnel token of the session's runner or one the server allows.

    A Coral session takes only its own runner's token, never the allow-list.

    :param request: The incoming ``/mcp`` request.
    :param conversation: The session's row; its ``runner_id`` is the bound runner.
    """
    token = (request.headers.get(RUNNER_TUNNEL_TOKEN_HEADER) or "").strip()
    allowed = getattr(request.app.state, "runner_tunnel_tokens", None)
    return bool(token) and (
        token_bound_runner_id(token) == conversation.runner_id
        or (allowed is not None and token in allowed and not coral_bound(conversation))
    )


def mcp_policy_actor(
    request: Request, conversation: Conversation, caller: str | None
) -> dict[str, str] | None:
    """Use the recorded turn actor only for a server-authorized runner."""
    if runner_proven(request, conversation):  # CORAL(S49)
        return _build_actor(conversation.labels.get(_TURN_ACTOR_LABEL) or caller)
    return _build_actor(caller)
