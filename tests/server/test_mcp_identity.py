# CORAL(S49): runner proof and MCP policy actor tests (new file).
"""Which ``/mcp`` callers prove they are the session's runner, and whose actor they get."""

from __future__ import annotations

import pytest
from starlette.applications import Starlette
from starlette.requests import Request

from omnigent.entities import Conversation
from omnigent.runner.identity import RUNNER_TUNNEL_TOKEN_HEADER, token_bound_runner_id
from omnigent.server.mcp_identity import mcp_policy_actor, runner_proven
from omnigent.server.routes._sessions.common import _TURN_ACTOR_LABEL

_TOKEN = "binding-token"
_RUNNER_ID = token_bound_runner_id(_TOKEN)
_SERVER_TOKEN = "server-tunnel-token"


def _request(token: str | None, allowed: frozenset[str] | None) -> Request:
    """A ``/mcp`` request carrying *token*, on a server allow-listing *allowed*."""
    app = Starlette()
    app.state.runner_tunnel_tokens = allowed
    headers = (
        [] if token is None else [(RUNNER_TUNNEL_TOKEN_HEADER.lower().encode(), token.encode())]
    )
    return Request({"type": "http", "method": "POST", "path": "/", "headers": headers, "app": app})


def _conversation(runner_id: str | None, labels: dict[str, str]) -> Conversation:
    return Conversation(
        id="conv_identity",
        created_at=0,
        updated_at=0,
        root_conversation_id="conv_identity",
        agent_id="ag_identity",
        runner_id=runner_id,
        labels=labels,
    )


@pytest.mark.parametrize(
    ("token", "runner_id", "allowed", "proven"),
    [
        pytest.param(_TOKEN, _RUNNER_ID, None, True, id="bound-to-the-session-runner"),
        pytest.param(f"  {_TOKEN} ", _RUNNER_ID, None, True, id="bound-padded"),
        pytest.param("other-token", _RUNNER_ID, None, False, id="bound-to-another-runner"),
        pytest.param(None, _RUNNER_ID, None, False, id="missing"),
        pytest.param("   ", _RUNNER_ID, None, False, id="blank"),
        pytest.param(_TOKEN, None, None, False, id="session-without-a-runner"),
        pytest.param(_TOKEN, "runner_stable_id", None, False, id="session-on-a-stable-id"),
        pytest.param(
            _SERVER_TOKEN, "runner_other", frozenset({_SERVER_TOKEN}), True, id="allow-listed"
        ),
        pytest.param(
            _SERVER_TOKEN, None, frozenset({_SERVER_TOKEN}), True, id="allow-listed-no-runner"
        ),
        pytest.param(
            _SERVER_TOKEN, _RUNNER_ID, frozenset({"another"}), False, id="not-allow-listed"
        ),
        pytest.param(None, None, frozenset({""}), False, id="missing-with-blank-allow-list-entry"),
    ],
)
def test_runner_proven_matches_the_policy_actor_rule(
    token: str | None, runner_id: str | None, allowed: frozenset[str] | None, proven: bool
) -> None:
    request = _request(token, allowed)
    turn = _conversation(runner_id, {_TURN_ACTOR_LABEL: "turn@example.com"})

    assert runner_proven(request, turn) is proven
    # The recorded turn actor is used exactly when the runner is proven.
    expected = "turn@example.com" if proven else "caller@example.com"
    assert mcp_policy_actor(request, turn, "caller@example.com") == {"run_as": expected}
    # Without a recorded turn actor the caller is the actor either way.
    no_turn = _conversation(runner_id, {})
    assert mcp_policy_actor(request, no_turn, "caller@example.com") == {
        "run_as": "caller@example.com"
    }
    assert mcp_policy_actor(request, no_turn, None) is None
    assert mcp_policy_actor(request, turn, None) == (
        {"run_as": "turn@example.com"} if proven else None
    )


@pytest.mark.parametrize(
    ("token", "runner_id", "proven"),
    [
        pytest.param(_TOKEN, _RUNNER_ID, True, id="bound-to-the-session-runner"),
        pytest.param(_SERVER_TOKEN, _RUNNER_ID, False, id="allow-listed"),
        pytest.param(_SERVER_TOKEN, None, False, id="allow-listed-no-runner"),
        pytest.param(
            _SERVER_TOKEN, token_bound_runner_id(_SERVER_TOKEN), True, id="allow-listed-and-bound"
        ),
    ],
)
@pytest.mark.parametrize("label", ["coral.run_id", "Coral.Role"])
def test_a_coral_session_takes_only_its_own_runner_token(
    token: str, runner_id: str | None, proven: bool, label: str
) -> None:
    """CORAL(S49): the allow-list never proves a session with a ``coral.`` label."""
    request = _request(token, frozenset({_SERVER_TOKEN}))

    assert runner_proven(request, _conversation(runner_id, {label: "run-1"})) is proven
