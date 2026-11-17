# CORAL(S50): extension tool providers loaded from entry points (new file).
"""Tests for ``omnigent.tools.extensions``: the tool-provider loader and its checks.

Tests never depend on the installed entry-point group (it changes only after
``uv sync``): they pass entry points to the loader, patch discovery, or serve
providers through :func:`installed_tool_providers`.
"""

from __future__ import annotations

import contextlib
import importlib.metadata
import json
import logging
import subprocess
import sys
import threading
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from textwrap import dedent
from types import MappingProxyType
from typing import Any
from unittest.mock import patch

import pytest

from omnigent.host.frames import CAP_OS_SANDBOX_PREFIX
from omnigent.spec import AgentSpec
from omnigent.tools import ToolManager, extensions
from omnigent.tools.extensions import (
    ENTRY_POINT_GROUP,
    RESERVED_HOST_CAPABILITY_PREFIXES,
    ExtensionToolSet,
    clear_tool_provider_caches,
    extension_framework_instructions,
    extension_host_capabilities,
    extension_tool_name,
    extension_tool_sets,
    load_tool_providers,
    static_server_dispatched_names,
)
from tests._helpers.live_server import isolated_process_env


def tool_schema(name: str, description: str = "Echo the text back.") -> dict[str, object]:
    """An OpenAI-format schema for a one-argument tool called *name*."""
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {
                "type": "object",
                "properties": {"text": {"type": "string"}},
                "required": ["text"],
            },
        },
    }


@dataclass
class StubToolProvider:
    """A provider with fixed answers that counts its server-name calls."""

    tools: tuple[Mapping[str, object], ...] = ()
    instructions: tuple[str, ...] = ()
    server_names: Any = frozenset()
    tokens: Any = ()
    applies: Callable[[AgentSpec], bool] = lambda _spec: True
    server_name_calls: int = 0
    token_calls: int = 0

    def tool_set(self, spec: AgentSpec) -> ExtensionToolSet | None:
        if not self.applies(spec):
            return None
        return ExtensionToolSet(tools=self.tools, framework_instructions=self.instructions)

    def server_dispatched_names(self) -> frozenset[str]:
        self.server_name_calls += 1
        return self.server_names

    def host_capabilities(self) -> tuple[str, ...]:
        self.token_calls += 1
        return self.tokens


@dataclass
class _ReturningProvider(StubToolProvider):
    """Returns *returned* from ``tool_set``, whatever it is."""

    returned: object = None

    def tool_set(self, spec: AgentSpec) -> ExtensionToolSet | None:
        return self.returned  # type: ignore[return-value]


@dataclass
class _RaisingProvider:
    """Every method raises."""

    error: Exception = field(default_factory=lambda: RuntimeError("provider bug"))

    def tool_set(self, spec: AgentSpec) -> ExtensionToolSet | None:
        raise self.error

    def server_dispatched_names(self) -> frozenset[str]:
        raise self.error

    def host_capabilities(self) -> tuple[str, ...]:
        raise self.error


@contextlib.contextmanager
def installed_tool_providers(*providers: object) -> Iterator[None]:
    """Serve *providers* as the installed ones, forgetting cached results and logs around it."""
    clear_tool_provider_caches()
    try:
        with patch.object(extensions, "default_tool_providers", lambda: providers):
            yield
    finally:
        clear_tool_provider_caches()


@pytest.fixture
def fresh_default_providers() -> Iterator[None]:
    """Forget the process-wide provider caches before and after the test."""
    clear_tool_provider_caches()
    yield
    clear_tool_provider_caches()


def _spec() -> AgentSpec:
    return AgentSpec(spec_version=1, skills_filter="none")


# ── loader ──────────────────────────────────────────────


def _first_provider() -> StubToolProvider:
    return StubToolProvider(tokens=("first:1",))


def _second_provider() -> StubToolProvider:
    return StubToolProvider(tokens=("second:1",))


def _raising_factory() -> StubToolProvider:
    raise RuntimeError("factory bug")


def _incomplete_provider() -> object:
    class _NoHostCapabilities:
        def tool_set(self, spec: AgentSpec) -> None:
            return None

        def server_dispatched_names(self) -> frozenset[str]:
            return frozenset()

    return _NoHostCapabilities()


def _entry(name: str, attribute: str) -> importlib.metadata.EntryPoint:
    return importlib.metadata.EntryPoint(
        name=name, value=f"{__name__}:{attribute}", group=ENTRY_POINT_GROUP
    )


@dataclass(frozen=True)
class _Distribution:
    name: str


@dataclass(frozen=True)
class _InstalledEntry:
    """An entry point as discovered from an installed distribution."""

    name: str
    dist: _Distribution
    factory: Callable[[], object]

    def load(self) -> Callable[[], object]:
        return self.factory


@pytest.mark.usefixtures("fresh_default_providers")
def test_loader_skips_broken_providers_and_caches(
    caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    broken: list[Any] = [
        importlib.metadata.EntryPoint(
            name="a-missing-module",
            value="tests.tools.no_such_module:provider",
            group=ENTRY_POINT_GROUP,
        ),
        _entry("b-factory-raises", "_raising_factory"),
        _entry("c-incomplete", "_incomplete_provider"),
        _InstalledEntry("acme", _Distribution("acme-tools"), _raising_factory),
    ]
    with caplog.at_level(logging.WARNING, logger=extensions.__name__):
        providers = load_tool_providers([*broken, _entry("z-good", "_first_provider")])

    assert [provider.host_capabilities() for provider in providers] == [("first:1",)]
    warned = [
        record.getMessage() for record in caplog.records if record.levelno == logging.WARNING
    ]
    assert warned == [
        "Failed to load tool provider from a-missing-module; skipping",
        "Failed to load tool provider from b-factory-raises; skipping",
        "Failed to load tool provider from c-incomplete; skipping",
        "Failed to load tool provider from acme-tools (acme); skipping",
    ]

    groups: list[str] = []

    def installed(*, group: str) -> list[importlib.metadata.EntryPoint]:
        groups.append(group)
        # Two entries share a name, so their values decide the order between them.
        return [
            _entry("a-first", "_second_provider"),
            _entry("b-second", "_second_provider"),
            _entry("a-first", "_first_provider"),
        ]

    monkeypatch.setattr(importlib.metadata, "entry_points", installed)
    assert not extensions.default_tool_providers.loaded
    first = extensions.default_tool_providers()
    second = extensions.default_tool_providers()

    assert groups == [ENTRY_POINT_GROUP]
    assert first is second
    assert [provider.host_capabilities() for provider in first] == [
        ("first:1",),
        ("second:1",),
        ("second:1",),
    ]


@pytest.mark.usefixtures("fresh_default_providers")
def test_unreadable_metadata_loads_no_provider(
    caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    def unreadable(*, group: str) -> list[importlib.metadata.EntryPoint]:
        raise OSError("metadata unreadable")

    monkeypatch.setattr(importlib.metadata, "entry_points", unreadable)
    with caplog.at_level(logging.WARNING, logger=extensions.__name__):
        assert extensions.default_tool_providers() == ()
    assert "Failed to discover tool providers" in caplog.text


def test_no_provider_adds_nothing() -> None:
    with installed_tool_providers():
        assert extension_tool_sets(_spec()) == ()
        assert extension_framework_instructions(_spec()) == ()
        assert static_server_dispatched_names() == frozenset()
        assert extension_host_capabilities() == ()


# ── tool sets ───────────────────────────────────────────


def _function_schema(name: str = "coral_test_bad", **function: object) -> dict[str, object]:
    """A tool schema whose ``function`` entry is exactly *function* plus the name."""
    return {"type": "function", "function": {"name": name, **function}}


def _bad_set(*schemas: object, instructions: tuple[object, ...] = ()) -> ExtensionToolSet:
    """A set with one good tool and text alongside the malformed parts."""
    return ExtensionToolSet(
        tools=(tool_schema("coral_test_sibling"), *schemas),  # type: ignore[arg-type]
        framework_instructions=("Bad provider text.", *instructions),  # type: ignore[arg-type]
    )


class _RaisingDict(dict[str, object]):
    """A schema dict whose every read raises."""

    def items(self) -> Any:
        raise RuntimeError("schema bug")

    def get(self, *args: object) -> Any:
        raise RuntimeError("schema bug")


def _nested(depth: int) -> dict[str, object]:
    """Parameters whose objects nest *depth* levels deep."""
    parameters: dict[str, object] = {"type": "object"}
    for _ in range(depth - 1):
        parameters = {"type": "object", "properties": {"inner": parameters}}
    return parameters


def _cyclic() -> dict[str, object]:
    parameters: dict[str, object] = {"type": "object"}
    parameters["properties"] = {"self": parameters}
    return parameters


_PARAMETERS = {"type": "object", "properties": {}}
_MALFORMED_SETS: dict[str, object] = {
    "invalid name": _bad_set(tool_schema("bad name")),
    "trailing newline": _bad_set(tool_schema("coral_test_bad\n")),
    "double underscore": _bad_set(tool_schema("coral__echo")),
    "not a function": _bad_set({**tool_schema("coral_test_bad"), "type": "custom"}),
    "function not a dict": _bad_set({"type": "function", "function": "coral_test_bad"}),
    "missing description": _bad_set(_function_schema(parameters=_PARAMETERS)),
    "parameters not a dict": _bad_set(_function_schema(description="d", parameters=["text"])),
    "name declared twice": _bad_set(tool_schema("coral_test_sibling")),
    "instruction not a string": _bad_set(instructions=(b"bytes",)),
    "tools not a tuple": ExtensionToolSet(tools=[tool_schema("coral_test_list")]),  # type: ignore[arg-type]
    "not a tool set": {"tools": (tool_schema("coral_test_dict"),)},
    "nested mapping proxy": _bad_set(
        _function_schema(description="d", parameters={"properties": MappingProxyType({})})
    ),
    "non-JSON value": _bad_set(_function_schema(description="d", parameters={"required": {"x"}})),
    "non-finite number": _bad_set(_function_schema(description="d", parameters={"max": 1e999})),
    "raising mapping": _bad_set(_RaisingDict(tool_schema("coral_test_raising"))),
    "cyclic parameters": _bad_set(_function_schema(description="d", parameters=_cyclic())),
    "nested too deep": _bad_set(_function_schema(description="d", parameters=_nested(70))),
    "beyond the recursion limit": _bad_set(
        _function_schema(description="d", parameters=_nested(30_000))
    ),
}


@pytest.mark.parametrize("malformed", list(_MALFORMED_SETS.values()), ids=list(_MALFORMED_SETS))
def test_malformed_tool_sets_are_dropped(
    caplog: pytest.LogCaptureFixture, malformed: object
) -> None:
    """A malformed set is dropped whole, its good tools and text with it; others stay.

    The tool manager, the prompt and the serialized tool list never see it.
    """
    bad = _ReturningProvider(returned=malformed)
    good = StubToolProvider(tools=(tool_schema("coral_test_echo"),), instructions=("Good text.",))

    with (
        installed_tool_providers(bad, good),
        caplog.at_level(logging.ERROR, logger=extensions.__name__),
    ):
        tool_sets = extension_tool_sets(_spec())
        instructions = extension_framework_instructions(_spec())
        manager = ToolManager(_spec())

    assert tool_sets == (
        ExtensionToolSet(tools=good.tools, framework_instructions=good.instructions),
    )
    assert instructions == ("Good text.",)
    assert "coral_test_echo" in manager.get_tool_names()
    assert "coral_test_sibling" not in manager.get_tool_names()
    json.dumps(manager.get_tool_schemas())
    # Logged once per process, not once per build.
    (error,) = [record.getMessage() for record in caplog.records]
    assert error.startswith(f"Tool provider {__name__}._ReturningProvider returned a malformed")
    assert error.endswith("; dropping all of it")


def test_raising_tool_set_is_skipped_and_logged_once(caplog: pytest.LogCaptureFixture) -> None:
    good = StubToolProvider(tools=(tool_schema("coral_test_echo"),))
    with (
        installed_tool_providers(_RaisingProvider(), good),
        caplog.at_level(logging.ERROR, logger=extensions.__name__),
    ):
        tool_sets = extension_tool_sets(_spec())
        assert extension_tool_sets(_spec()) == tool_sets
        assert extension_framework_instructions(_spec()) == ()

    assert [tool_set.tools for tool_set in tool_sets] == [good.tools]
    (record,) = caplog.records
    assert record.levelno == logging.ERROR
    assert record.exc_info is not None
    assert record.getMessage() == (
        f"Tool provider {__name__}._RaisingProvider raised for this agent; skipping its tools"
    )


def test_framework_instructions_keep_provider_order_and_skip_blank_text() -> None:
    first = StubToolProvider(instructions=("First one.", "   ", "First two."))
    silent = StubToolProvider(applies=lambda _spec: False, instructions=("Never shown.",))
    second = StubToolProvider(instructions=("Second.",))
    with installed_tool_providers(first, silent, second):
        assert extension_framework_instructions(_spec()) == ("First one.", "First two.", "Second.")


# ── server-dispatched names and host tokens ─────────────


def test_server_dispatched_names_are_validated_and_computed_once(
    caplog: pytest.LogCaptureFixture,
) -> None:
    good = StubToolProvider(server_names=frozenset({"coral_test_echo"}))
    invalid = StubToolProvider(server_names=frozenset({"coral_test_ok", "bad name"}))
    double_underscore = StubToolProvider(server_names=frozenset({"coral__echo"}))
    trailing_newline = StubToolProvider(server_names=frozenset({"coral_test_newline\n"}))
    bare_string = StubToolProvider(server_names="coral_test_string")
    with (
        installed_tool_providers(
            good, invalid, double_underscore, trailing_newline, bare_string, _RaisingProvider()
        ),
        caplog.at_level(logging.ERROR, logger=extensions.__name__),
    ):
        assert static_server_dispatched_names() == frozenset({"coral_test_echo"})
        assert static_server_dispatched_names() == frozenset({"coral_test_echo"})

    assert good.server_name_calls == 1
    errors = [record.getMessage() for record in caplog.records if record.levelno == logging.ERROR]
    assert len(errors) == 5
    assert errors[-1] == (
        f"Tool provider {__name__}._RaisingProvider failed to list its server-dispatched tools; "
        "skipping them"
    )


def test_host_capabilities_are_validated_and_deduplicated(
    caplog: pytest.LogCaptureFixture,
) -> None:
    longest = "x" * 128
    sixteen = tuple(f"many:{index}" for index in range(16))
    first = StubToolProvider(tokens=("coral_runner:1", "extra:1"))
    providers = (
        first,
        StubToolProvider(tokens=("coral_runner:1", longest)),
        _RaisingProvider(),
        StubToolProvider(tokens=sixteen),
        StubToolProvider(tokens=("has space",)),
        StubToolProvider(tokens=("trailing:1\n",)),
        StubToolProvider(tokens=("",)),
        StubToolProvider(tokens=("y" * 129,)),
        StubToolProvider(tokens=(7,)),
        _ReturningProvider(tokens="coral_runner:2"),
        StubToolProvider(tokens=("spoof:1", f"{CAP_OS_SANDBOX_PREFIX}none")),
        StubToolProvider(tokens=(*sixteen, "many:16")),
    )
    with (
        installed_tool_providers(*providers),
        caplog.at_level(logging.WARNING, logger=extensions.__name__),
    ):
        expected = ("coral_runner:1", "extra:1", longest, *sixteen)
        assert extension_host_capabilities() == expected
        assert extension_host_capabilities() == expected

    assert first.token_calls == 1  # read once per process
    warned = [
        record.getMessage() for record in caplog.records if record.levelno == logging.WARNING
    ]
    assert len(warned) == 9
    assert warned[0] == (
        f"Tool provider {__name__}._RaisingProvider failed to list its host capabilities; "
        "skipping them"
    )


def test_the_sandbox_token_prefix_is_reserved() -> None:
    """Only the host itself names its OS sandbox; a provider cannot add a second token."""
    assert RESERVED_HOST_CAPABILITY_PREFIXES == (CAP_OS_SANDBOX_PREFIX,)


# ── conflicts and concurrency ───────────────────────────


@pytest.mark.usefixtures("fresh_default_providers")
def test_a_name_two_providers_offer_is_served_by_neither(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A provider cannot take over another's tool; the log names both packages."""
    shared = tool_schema("coral_test_shared")
    acme = StubToolProvider(
        tools=(shared, tool_schema("coral_test_acme")),
        instructions=("Acme text.",),
        server_names=frozenset({"coral_test_shared", "coral_test_acme"}),
    )
    coral = StubToolProvider(
        tools=(tool_schema("coral_test_shared", "Coral's own."), tool_schema("coral_test_mine")),
        server_names=frozenset({"coral_test_shared", "coral_test_mine"}),
    )
    installed: list[Any] = [
        _InstalledEntry("acme", _Distribution("acme-tools"), lambda: acme),
        _InstalledEntry("coral", _Distribution("coral"), lambda: coral),
    ]
    loaded = load_tool_providers(installed)
    with (
        installed_tool_providers(*loaded),
        caplog.at_level(logging.ERROR, logger=extensions.__name__),
    ):
        tool_sets = extension_tool_sets(_spec())
        names = static_server_dispatched_names()
        manager_names = ToolManager(_spec()).get_tool_names()

    assert [[extension_tool_name(schema) for schema in s.tools] for s in tool_sets] == [
        ["coral_test_acme"],
        ["coral_test_mine"],
    ]
    assert tool_sets[0].framework_instructions == ("Acme text.",)
    assert names == frozenset({"coral_test_acme", "coral_test_mine"})
    assert "coral_test_shared" not in manager_names
    errors = [record.getMessage() for record in caplog.records if record.levelno >= logging.ERROR]
    assert errors == [
        "Extension tool 'coral_test_shared' is offered by acme-tools (acme) and coral (coral); "
        "serving none of them",
        "Server-dispatched tool 'coral_test_shared' is offered by acme-tools (acme) and "
        "coral (coral); serving none of them",
    ]


_FACTORY_CALLS: list[int] = []
_FACTORY_RACE = threading.Barrier(1)


def _racing_factory() -> StubToolProvider:
    """Wait for every racing thread; without the load lock they would all arrive here."""
    _FACTORY_CALLS.append(1)
    with contextlib.suppress(threading.BrokenBarrierError):
        _FACTORY_RACE.wait(timeout=0.5)
    return StubToolProvider(tokens=("raced:1",))


@pytest.mark.usefixtures("fresh_default_providers")
def test_concurrent_first_use_runs_each_factory_once(monkeypatch: pytest.MonkeyPatch) -> None:
    threads = 4
    monkeypatch.setattr(sys.modules[__name__], "_FACTORY_RACE", threading.Barrier(threads))
    monkeypatch.setattr(sys.modules[__name__], "_FACTORY_CALLS", [])
    monkeypatch.setattr(
        importlib.metadata,
        "entry_points",
        lambda *, group: [_entry("raced", "_racing_factory")],
    )
    start = threading.Barrier(threads)
    results: list[tuple[object, ...]] = []

    def first_use() -> None:
        start.wait(timeout=5)
        results.append(extensions.default_tool_providers())

    workers = [threading.Thread(target=first_use) for _ in range(threads)]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join(timeout=10)

    assert _FACTORY_CALLS == [1]
    assert len(results) == threads
    assert all(result is results[0] for result in results)


def test_importing_the_seams_loads_no_provider(tmp_path: Path) -> None:
    """Providers load on first use, never when the host, runner or prompt modules import."""
    code = dedent("""\
        import importlib.metadata

        discover = importlib.metadata.entry_points
        groups = []

        # Record instead of raising: the loader would swallow an error raised here.
        def recording(**params):
            groups.append(params.get("group"))
            return discover(**params)

        importlib.metadata.entry_points = recording

        import omnigent.host.frames
        import omnigent.runner.tool_dispatch
        import omnigent.runtime.prompt
        import omnigent.tools.manager
        from omnigent.tools import extensions

        assert "omnigent.tool_providers" not in groups, "discovered at import"
        assert not extensions.default_tool_providers.loaded
        assert not extensions.static_server_dispatched_names.loaded
        assert not extensions.extension_host_capabilities.loaded
        """)
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=Path(__file__).resolve().parents[2],
        env=isolated_process_env(tmp_path, {}, None),
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
