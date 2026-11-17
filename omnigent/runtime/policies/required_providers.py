# CORAL(S52): policies an installed extension requires for the sessions it claims (new file).
"""Required-policy providers: policies an extension puts ahead of every other policy.

An extension registers a provider under a name. Every policy engine build asks
each provider, in name order, whether it applies to the session and, if so,
for its policy specs; the builder puts them ahead of the session, agent, admin
and built-in approval policies, so a provider's DENY decides first and earlier
policies' label and state writes are not applied on that call. The builder
rebuilds the engine for every evaluation, so providers see current state.

A provider that fails, or answers with a spec that cannot be built, gets one
policy that denies that session's tool calls and allows everything else, so a
provider bug never blocks requests (for example an engine's message to the
session) and never affects sessions the provider does not claim (an
``applies`` that fails claims every session it is asked about). Failures log
one traceback per registration and one line each after that. With no
provider registered, policy builds are unchanged.

The registry is process-wide, keyed by provider name: the latest registration
of a name wins, as with the other server registries.
"""

from __future__ import annotations

import logging
import re
import threading
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

from omnigent.policies.function import resolve_function_policy
from omnigent.spec.types import FunctionPolicySpec, FunctionRef

if TYPE_CHECKING:
    from omnigent.entities import Conversation
    from omnigent.policies.schema import PolicyEvent, PolicyResponse
    from omnigent.spec.types import AgentSpec, PolicySpec

_logger = logging.getLogger(__name__)

_NAME_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}")
_UNAVAILABLE_POLICY_PREFIX = "__required_policy_unavailable:"
_DENY_TOOL_CALLS_PATH = f"{__name__}.deny_tool_calls"


class RequiredPolicyProvider(Protocol):
    """Policies an extension requires for the sessions it claims.

    ``spec`` is the spec the session is bound to: for a sub-agent session that
    is still the root bundle's spec, while ``conversation`` is the child's row.
    """

    def applies(self, spec: AgentSpec, conversation: Conversation | None) -> bool:
        """Whether this provider may have policies for the session.

        Called on the event loop by the policy fast path, so it must be O(1)
        with no I/O. ``conversation`` is ``None`` when the caller has no row.
        """
        ...

    def specs(self, spec: AgentSpec, conversation: Conversation) -> Sequence[PolicySpec]:
        """The session's required policy specs, in evaluation order.

        Called in a worker thread on every engine build, with the refreshed
        conversation row; it may read stores. Each spec's factory runs twice
        per build (once here to check it, once by the builder), so factories
        must be deterministic and cheap. The specs run before every other
        policy, so they see a tool call's arguments before a later policy
        rewrites them: decide on the tool and on provider-supplied state.
        Limit them to tool calls and never raise while evaluating: only
        ``specs`` itself is guarded, and a policy that raises during
        evaluation is a DENY for whatever phase it ran on, requests included.
        """
        ...


@dataclass(eq=False)
class _Registration:
    """One registration; its identity lets an unregister remove only itself."""

    name: str
    provider: RequiredPolicyProvider
    # Set under the registry lock once a failure of this registration logged its traceback.
    traceback_logged: bool = False


# Process-wide registry keyed by provider name, never by session.
# custom-lint: disable-next=workspace-scoped-cache -- keyed by provider name, not a tenant id
_registrations: dict[str, _Registration] = {}
_registrations_lock = threading.Lock()


def register_required_policy_provider(
    name: str, provider: RequiredPolicyProvider
) -> Callable[[], None]:
    """Put *provider*'s policies ahead of every other policy for the sessions it claims.

    Registering a name again replaces its provider and logs a warning when the
    provider changes.

    :param name: 1-64 letters, digits, ``_``, ``.`` or ``-``, starting with a
        letter or digit, e.g. ``"coral"``. Providers run in name order.
    :param provider: The provider; it must be thread-safe.
    :returns: An idempotent unregister function that removes this registration
        only while it is still the one registered under *name*.
    :raises ValueError: If *name* is not a valid provider name.
    :raises TypeError: If *provider* lacks a callable ``applies`` or ``specs``.
    """
    if not isinstance(name, str) or _NAME_RE.fullmatch(name) is None:
        raise ValueError(f"invalid required policy provider name {name!r}")
    if not (
        callable(getattr(provider, "applies", None)) and callable(getattr(provider, "specs", None))
    ):
        raise TypeError(f"required policy provider {name!r} needs callable applies and specs")
    registration = _Registration(name, provider)
    with _registrations_lock:
        replaced = _registrations.get(name)
        _registrations[name] = registration
    if replaced is not None and replaced.provider is not provider:
        _logger.warning("required policy provider %r replaced an earlier registration", name)

    def unregister() -> None:
        with _registrations_lock:
            if _registrations.get(name) is registration:
                del _registrations[name]

    return unregister


def required_policies_apply(spec: AgentSpec, conversation: Conversation | None) -> bool:
    """Whether any registered provider applies to the session (a failing check counts as yes).

    :param spec: The session's agent spec.
    :param conversation: The session's row, or ``None`` when the caller has none.
    """
    return any(
        _provider_applies(registration, spec, conversation) for registration in _registered()
    )


def required_policy_specs(spec: AgentSpec, conversation: Conversation | None) -> list[PolicySpec]:
    """Every applying provider's specs, providers in name order; ``[]`` without a row.

    A provider whose ``specs`` raises, or returns anything but buildable
    :class:`FunctionPolicySpec` values, is logged and contributes one policy
    that denies this session's tool calls instead.

    :param spec: The session's agent spec.
    :param conversation: The refreshed session row, or ``None`` when it does
        not exist.
    """
    if conversation is None:
        return []
    required: list[PolicySpec] = []
    for registration in _registered():
        if not _provider_applies(registration, spec, conversation):
            continue
        try:
            provided = list(registration.provider.specs(spec, conversation))
            for item in provided:
                if not isinstance(item, FunctionPolicySpec):
                    raise TypeError(f"not a FunctionPolicySpec: {type(item).__name__}")
                resolve_function_policy(item)
        except Exception:  # a provider bug denies tool calls; it never fails the build
            _log_failure(
                registration, "failed; denying this session's tool calls", conversation.id
            )
            provided = [_unavailable_spec(registration.name)]
        required.extend(provided)
    return required


def deny_tool_calls(reason: str) -> Callable[[PolicyEvent], PolicyResponse]:
    """Policy factory: DENY every tool call with *reason*; ALLOW every other event.

    :param reason: The deny reason the agent sees.
    """

    def evaluate(event: PolicyEvent) -> PolicyResponse:
        if event.get("type") == "tool_call":
            return {"result": "DENY", "reason": reason}
        return {"result": "ALLOW"}

    return evaluate


def _registered() -> list[_Registration]:
    with _registrations_lock:
        return sorted(_registrations.values(), key=lambda registration: registration.name)


def _provider_applies(
    registration: _Registration, spec: AgentSpec, conversation: Conversation | None
) -> bool:
    try:
        # bool() inside the guard: an answer whose truth test raises is a failure too.
        return bool(registration.provider.applies(spec, conversation))
    except Exception:  # evaluate rather than skip a provider that cannot decide
        session_id = conversation.id if conversation is not None else None
        _log_failure(registration, "failed to decide whether it applies; it applies", session_id)
        return True


def _log_failure(registration: _Registration, what: str, session_id: str | None) -> None:
    """Log a provider failure: its traceback once per registration, one line after that."""
    with _registrations_lock:
        first = not registration.traceback_logged
        registration.traceback_logged = True
    _logger.error(
        "required policy provider %r %s",
        registration.name,
        what,
        exc_info=first,
        extra={"session_id": session_id},
    )


def _unavailable_spec(name: str) -> FunctionPolicySpec:
    reason = (
        f"[required_policy.unavailable] Required policy provider {name!r} failed, "
        "so tool calls are denied for this session. Stop now and end your turn."
    )
    return FunctionPolicySpec(
        name=f"{_UNAVAILABLE_POLICY_PREFIX}{name}",
        on=None,
        function=FunctionRef(path=_DENY_TOOL_CALLS_PATH, arguments={"reason": reason}),
    )
