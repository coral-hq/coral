# CORAL(S50): extension tool providers loaded from entry points (new file).
"""Tools, prompt text and host tokens that installed packages add.

A package declares a provider under the :data:`ENTRY_POINT_GROUP` entry-point
group as a zero-argument factory returning an object with three methods
(:class:`ToolProvider`):

- ``tool_set(spec)``: schema-only tools and framework instructions for one
  agent spec, or ``None`` when the provider adds nothing for it;
- ``server_dispatched_names()``: names the runner forwards to the server
  instead of executing itself;
- ``host_capabilities()``: tokens the host appends to its hello.

Factories run once per process, on first use and never at import, even when
threads race. A provider that fails to load, raises or returns anything
malformed is skipped and its problem logged once per process, so it never
takes away the agent's other tools or another provider's. A tool or
server-dispatched name that two providers offer is served by neither.

This module imports only the standard library and the tool-name pattern, so the
host can build its hello without loading server or database modules.
"""

from __future__ import annotations

import functools
import importlib.metadata
import json
import logging
import threading
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol, TypeGuard, runtime_checkable

from omnigent.tools.base import TOOL_NAME_RE

if TYPE_CHECKING:
    from omnigent.spec import AgentSpec

_logger = logging.getLogger(__name__)

ENTRY_POINT_GROUP = "omnigent.tool_providers"
# The host's own OS sandbox token (``omnigent.host.frames.CAP_OS_SANDBOX_PREFIX``).
RESERVED_HOST_CAPABILITY_PREFIXES = ("os_sandbox:",)
_MAX_HOST_CAPABILITY_LENGTH = 128
_MAX_HOST_CAPABILITIES_PER_PROVIDER = 16
# Deeper schemas fail elsewhere in the runner on Python's recursion limit.
_MAX_SCHEMA_DEPTH = 64


@dataclass(frozen=True)
class ExtensionToolSet:
    """What one provider adds for one agent spec.

    :param tools: OpenAI-format tool schemas made of plain JSON values, e.g.
        ``{"type": "function", "function": {"name": "coral_x", "description":
        "...", "parameters": {"type": "object", "properties": {}}}}``. Names
        must be valid tool names without ``__``.
    :param framework_instructions: Text appended to the system prompt after
        the framework's own instructions.
    """

    tools: tuple[Mapping[str, object], ...] = ()
    framework_instructions: tuple[str, ...] = ()


@runtime_checkable
class ToolProvider(Protocol):
    """An installed source of extension tools."""

    def tool_set(self, spec: AgentSpec) -> ExtensionToolSet | None:
        """Return this provider's tools for *spec*, or ``None`` to add nothing.

        Called on every tool-manager build and every prompt build, so it must
        be cheap, must not raise and must be a pure function of *spec*: the
        runner fixes a conversation's tools once, and the prompt text must
        keep matching them.
        """
        ...

    def server_dispatched_names(self) -> frozenset[str]:
        """Return the tool names the server executes; read once per process."""
        ...

    def host_capabilities(self) -> tuple[str, ...]:
        """Return the tokens a host running this provider advertises; read once per process."""
        ...


class _LoadOnce[T]:
    """Run a zero-argument loader once per process, on first use, even when threads race."""

    def __init__(self, load: Callable[[], T]) -> None:
        self._load = load
        self._lock = threading.Lock()
        self._cached: tuple[T] | None = None
        functools.update_wrapper(self, load)
        _LOADERS.append(self)

    def __call__(self) -> T:
        cached = self._cached
        if cached is None:
            with self._lock:
                cached = self._cached
                if cached is None:
                    cached = self._cached = (self._load(),)
        return cached[0]

    @property
    def loaded(self) -> bool:
        """Whether the loader has run since the process started or the last clear."""
        return self._cached is not None

    def cache_clear(self) -> None:
        """Forget the loaded value; the next call loads again."""
        with self._lock:
            self._cached = None


_LOADERS: list[_LoadOnce[Any]] = []
# Each loaded provider with the entry point it came from; holding the provider keeps its id valid.
_PROVIDER_SOURCES: dict[int, tuple[object, str]] = {}
_logged_problems: set[str] = set()
_logged_problems_lock = threading.Lock()


def load_tool_providers(
    entry_points: Iterable[importlib.metadata.EntryPoint] | None = None,
) -> tuple[ToolProvider, ...]:
    """Load providers; one that fails to import, call or conform is skipped with a warning.

    :param entry_points: Entry points to load; ``None`` discovers the installed
        :data:`ENTRY_POINT_GROUP`, sorted by ``(name, value)``.
    :returns: The loaded providers, in entry-point order.
    """
    if entry_points is None:
        try:
            entry_points = sorted(
                importlib.metadata.entry_points(group=ENTRY_POINT_GROUP),
                key=lambda entry: (entry.name, entry.value),
            )
        except Exception:  # unreadable metadata leaves the runner without extension tools
            _logger.warning("Failed to discover tool providers", exc_info=True)
            return ()
    providers: list[ToolProvider] = []
    for entry in entry_points:
        source = _entry_source(entry)
        try:
            provider = entry.load()()
            if not isinstance(provider, ToolProvider):
                raise TypeError(
                    "a tool provider needs tool_set, server_dispatched_names and host_capabilities"
                )
        except Exception:  # a broken provider must not hide the others
            _logger.warning(
                "Failed to load tool provider from %s; skipping", source, exc_info=True
            )
            continue
        _PROVIDER_SOURCES[id(provider)] = (provider, source)
        _logger.info("Loaded tool provider %s from %s", _class_label(provider), source)
        providers.append(provider)
    return tuple(providers)


@_LoadOnce
def default_tool_providers() -> tuple[ToolProvider, ...]:
    """Return the installed providers, loaded once on first use (never at import)."""
    return load_tool_providers()


def extension_tool_sets(spec: AgentSpec) -> tuple[ExtensionToolSet, ...]:
    """Return each provider's tool set for *spec* as plain JSON, in provider order.

    A provider that raises is skipped, a set with any malformed part is
    dropped whole, and a tool that two providers offer is served by neither;
    each problem is logged once per process. Never raises.

    :param spec: The agent spec the tools are for.
    :returns: The accepted tool sets.
    """
    offered: list[tuple[str, ExtensionToolSet]] = []
    for provider in default_tool_providers():
        label = _provider_label(provider)
        try:
            tool_set = provider.tool_set(spec)
        except Exception:  # logged once; a provider bug must not cost other tools
            _log_once(
                logging.ERROR,
                "Tool provider %s raised for this agent; skipping its tools",
                label,
                exc_info=True,
            )
            continue
        if tool_set is None:
            continue
        try:
            offered.append((label, _normalised_tool_set(tool_set)))
        except Exception as error:  # any part of a provider's result may raise
            problem = str(error) if isinstance(error, _MalformedToolSet) else type(error).__name__
            _log_once(
                logging.ERROR,
                "Tool provider %s returned a malformed tool set (%s); dropping all of it",
                label,
                problem,
            )
    owners: dict[str, list[str]] = {}
    for label, tool_set in offered:
        for name in _tool_names(tool_set):
            owners.setdefault(name, []).append(label)
    served = _unconflicted(owners, "Extension tool")
    return tuple(
        ExtensionToolSet(
            tools=tuple(
                schema for schema in tool_set.tools if extension_tool_name(schema) in served
            ),
            framework_instructions=tool_set.framework_instructions,
        )
        for _label, tool_set in offered
    )


def extension_framework_instructions(spec: AgentSpec) -> tuple[str, ...]:
    """Return the non-blank framework instructions of *spec*'s accepted tool sets."""
    return tuple(
        text for tool_set in extension_tool_sets(spec) for text in tool_set.framework_instructions
    )


@_LoadOnce
def static_server_dispatched_names() -> frozenset[str]:
    """Return the providers' server-dispatched tool names, read once per process.

    A provider that raises or lists an invalid name contributes none of its
    names, and a name that two providers list is served by neither; each
    problem is logged once.
    """
    owners: dict[str, list[str]] = {}
    for provider in default_tool_providers():
        label = _provider_label(provider)
        try:
            declared = _string_items(provider.server_dispatched_names())
            problem = _server_names_problem(declared)
        except Exception:  # logged once per process
            _log_once(
                logging.ERROR,
                "Tool provider %s failed to list its server-dispatched tools; skipping them",
                label,
                exc_info=True,
            )
            continue
        if declared is None or problem is not None:
            _log_once(
                logging.ERROR,
                "Tool provider %s listed invalid server-dispatched tools (%s); skipping them",
                label,
                problem,
            )
            continue
        for name in dict.fromkeys(declared):
            owners.setdefault(name, []).append(label)
    return frozenset(_unconflicted(owners, "Server-dispatched tool"))


@_LoadOnce
def extension_host_capabilities() -> tuple[str, ...]:
    """Return the providers' host tokens in order, each once, read once per process.

    A provider contributes at most 16 tokens, each a non-empty string of at
    most 128 characters without whitespace and without a reserved prefix
    (:data:`RESERVED_HOST_CAPABILITY_PREFIXES`). A provider that raises or
    breaks a rule contributes none of its tokens, with a warning.
    """
    tokens: dict[str, None] = {}
    for provider in default_tool_providers():
        label = _provider_label(provider)
        try:
            declared = _string_items(provider.host_capabilities())
            problem = _host_capabilities_problem(declared)
        except Exception:  # logged once per process
            _log_once(
                logging.WARNING,
                "Tool provider %s failed to list its host capabilities; skipping them",
                label,
                exc_info=True,
            )
            continue
        if declared is None or problem is not None:
            _log_once(
                logging.WARNING,
                "Tool provider %s listed invalid host capabilities (%s); skipping them",
                label,
                problem,
            )
            continue
        tokens.update(dict.fromkeys(declared))
    return tuple(tokens)


def extension_tool_name(schema: object) -> str | None:
    """Return the tool name of a well-formed extension tool schema, else ``None``.

    :param schema: An OpenAI-format tool schema: a mapping with ``"type":
        "function"`` and a ``function`` dict holding a ``name`` (a valid tool
        name without ``__``), a string ``description`` and a ``parameters`` dict.
    """
    if not isinstance(schema, Mapping) or schema.get("type") != "function":
        return None
    function = schema.get("function")
    if not isinstance(function, dict):
        return None
    name = function.get("name")
    if not isinstance(function.get("description"), str):
        return None
    if not isinstance(function.get("parameters"), dict) or not _is_extension_tool_name(name):
        return None
    return name


def log_extension_problem(message: str) -> None:
    """Log *message* about an extension tool at error level, once per process."""
    _log_once(logging.ERROR, "%s", message)


def clear_tool_provider_caches() -> None:
    """Forget the loaded providers, their names and tokens, and the problems already logged.

    The next use loads the installed providers again. Meant for tests.
    """
    for loader in _LOADERS:
        loader.cache_clear()
    with _logged_problems_lock:
        _logged_problems.clear()


class _MalformedToolSet(ValueError):
    """A provider's tool set breaks the :class:`ExtensionToolSet` contract."""


def _normalised_tool_set(tool_set: object) -> ExtensionToolSet:
    """Return a plain-JSON copy of *tool_set*, raising when any part of it is malformed."""
    if not isinstance(tool_set, ExtensionToolSet):
        raise _MalformedToolSet(f"expected ExtensionToolSet, got {type(tool_set).__name__}")
    if not isinstance(tool_set.tools, tuple) or not isinstance(
        tool_set.framework_instructions, tuple
    ):
        raise _MalformedToolSet("tools and framework_instructions must be tuples")
    tools: list[dict[str, object]] = []
    names: set[str] = set()
    for index, schema in enumerate(tool_set.tools):
        try:
            # Also the copy the tool manager keeps: no provider object reaches a conversation.
            plain = json.loads(json.dumps(schema, allow_nan=False))
        except (TypeError, ValueError, RecursionError) as error:
            raise _MalformedToolSet(
                f"tool schema {index} is not plain JSON ({type(error).__name__})"
            ) from error
        if _nesting_exceeds(plain, _MAX_SCHEMA_DEPTH):
            raise _MalformedToolSet(f"tool schema {index} nests deeper than {_MAX_SCHEMA_DEPTH}")
        name = extension_tool_name(plain)
        if name is None:
            raise _MalformedToolSet(f"tool schema {index} is malformed")
        if name in names:
            raise _MalformedToolSet(f"tool {name!r} is declared twice")
        names.add(name)
        tools.append(plain)
    instructions: list[str] = []
    for text in tool_set.framework_instructions:
        if not isinstance(text, str):
            raise _MalformedToolSet("framework instructions must be strings")
        if text.strip():
            instructions.append(str(text))
    return ExtensionToolSet(tools=tuple(tools), framework_instructions=tuple(instructions))


def _nesting_exceeds(value: object, limit: int) -> bool:
    """Whether plain JSON *value* nests objects or arrays more than *limit* deep."""
    pending = [(value, 1)]
    while pending:
        item, depth = pending.pop()
        if isinstance(item, dict | list) and depth > limit:
            return True
        children = (
            item.values() if isinstance(item, dict) else item if isinstance(item, list) else ()
        )
        pending.extend((child, depth + 1) for child in children)
    return False


def _tool_names(tool_set: ExtensionToolSet) -> list[str]:
    return [name for schema in tool_set.tools if (name := extension_tool_name(schema))]


def _unconflicted(owners: Mapping[str, list[str]], kind: str) -> set[str]:
    """Return the names offered by exactly one provider, logging each conflict once."""
    served: set[str] = set()
    for name, labels in owners.items():
        if len(labels) == 1:
            served.add(name)
            continue
        _log_once(
            logging.ERROR,
            "%s %r is offered by %s; serving none of them",
            kind,
            name,
            " and ".join(labels),
        )
    return served


def _server_names_problem(declared: tuple[str, ...] | None) -> str | None:
    if declared is None:
        return "not a collection of strings"
    invalid = next((name for name in declared if not _is_extension_tool_name(name)), None)
    return None if invalid is None else f"invalid name {invalid[:80]!r}"


def _host_capabilities_problem(declared: tuple[str, ...] | None) -> str | None:
    if declared is None:
        return "not a collection of strings"
    if len(declared) > _MAX_HOST_CAPABILITIES_PER_PROVIDER:
        return f"more than {_MAX_HOST_CAPABILITIES_PER_PROVIDER} tokens"
    for token in declared:
        if not 0 < len(token) <= _MAX_HOST_CAPABILITY_LENGTH or any(map(str.isspace, token)):
            return f"invalid token {token[:40]!r}"
        if token.startswith(RESERVED_HOST_CAPABILITY_PREFIXES):
            return f"reserved token {token[:40]!r}"
    return None


def _is_extension_tool_name(name: object) -> TypeGuard[str]:
    # ``__`` is excluded because the runner's MCP refresh drops builtins whose name has it.
    return isinstance(name, str) and TOOL_NAME_RE.fullmatch(name) is not None and "__" not in name


def _string_items(value: object) -> tuple[str, ...] | None:
    """Return *value*'s items when it is a non-string collection of strings, else ``None``."""
    if isinstance(value, str | bytes) or not isinstance(value, Iterable):
        return None
    items = tuple(value)
    if not all(isinstance(item, str) for item in items):
        return None
    return tuple(str(item) for item in items)


def _log_once(level: int, message: str, *args: object, exc_info: bool = False) -> None:
    """Log a problem the first time this exact text occurs in the process."""
    text = message % args
    with _logged_problems_lock:
        if text in _logged_problems:
            return
        _logged_problems.add(text)
    _logger.log(level, message, *args, exc_info=exc_info)


def _provider_label(provider: object) -> str:
    """Name a provider by its entry point when it was loaded from one, else by its class."""
    recorded = _PROVIDER_SOURCES.get(id(provider))
    if recorded is not None and recorded[0] is provider:
        return recorded[1]
    return _class_label(provider)


def _class_label(provider: object) -> str:
    """Name a provider by its class, e.g. ``"acme.tools.AcmeToolProvider"``."""
    provider_type = type(provider)
    return f"{provider_type.__module__}.{provider_type.__qualname__}"


def _entry_source(entry: importlib.metadata.EntryPoint) -> str:
    """Name an entry point by its distribution when known, e.g. ``"coral (coral)"``."""
    distribution = getattr(entry, "dist", None)
    package = getattr(distribution, "name", None)
    return f"{package} ({entry.name})" if package else entry.name
