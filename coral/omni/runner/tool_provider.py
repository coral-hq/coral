"""Coral's ``omnigent.tool_providers`` entry point: engine tools by stance, and the host token.

A host loads it to build its hello and a runner on its first tool or prompt
build, so it imports only the standard library, the tool catalog, the process
map and Omnigent's extension types: never server, database or engine modules.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING

from coral.omni.process_map import host_tokens
from coral.tools.catalog import (
    CATALOG,
    TOOL_STANCES,
    EngineToolDecl,
    generated_stance,
    tools_for_stance,
    validate_catalog,
)
from omnigent.tools.extensions import ExtensionToolSet

if TYPE_CHECKING:
    from omnigent.spec import AgentSpec


class CoralToolProvider:
    """
    Offers a generated Coral bundle the engine tools of its stance.

    Each stance's declarations are picked once; :meth:`tool_set` returns fresh
    schema copies, so a caller cannot change a later answer.

    :param catalog: The declarations to offer; production offers every engine tool.
    :raises ValueError: When a declaration cannot be offered (``validate_catalog``).
    """

    def __init__(self, catalog: Sequence[EngineToolDecl] = CATALOG) -> None:
        validate_catalog(catalog)
        self._names = frozenset(decl.name for decl in catalog)
        self._decls = {stance: tools_for_stance(catalog, stance) for stance in TOOL_STANCES}

    def tool_set(self, spec: AgentSpec) -> ExtensionToolSet | None:
        """The tools of the spec's ``params.coral.generated.stance``; else ``None``."""
        stance = generated_stance(getattr(spec, "params", None))
        decls = self._decls.get(stance, ()) if stance is not None else ()
        if not decls:
            return None
        # Schemas feed both the SDK MCP surface and the native relay (S9).
        # Other native harnesses without Coral step mode omit the set entirely.
        from omnigent.harness_aliases import canonicalize_harness, is_native_harness

        harness = getattr(getattr(spec, "executor", None), "harness_kind", None)
        if isinstance(harness, str) and is_native_harness(harness):
            params = getattr(spec, "params", None)
            if not (
                (canonicalize_harness(harness) or harness) == "claude-native"
                and isinstance(params, dict)
                and "coral" in params
            ):
                return None
        return ExtensionToolSet(
            tools=tuple(decl.schema() for decl in decls),
            framework_instructions=tuple(dict.fromkeys(decl.instructions for decl in decls)),
        )

    def server_dispatched_names(self) -> frozenset[str]:
        """Every catalog tool: the server answers them all."""
        return self._names

    def host_capabilities(self) -> tuple[str, ...]:
        """``coral_runner:2``, unless Coral's host entry points are disabled."""
        return host_tokens()


def tool_provider() -> CoralToolProvider:
    """The entry point: Coral's provider over the production catalog."""
    return CoralToolProvider()
