"""Claude-native step helpers: pre-approved tool names and pane wake."""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from coral.tools.catalog import CATALOG, generated_stance, tools_for_stance


def native_preapproved_tool_names(params: object) -> tuple[str, ...]:
    """Claude ``--allowedTools`` names for a Coral native step's engine tools."""
    stance = generated_stance(params if isinstance(params, dict) else None)
    if stance is None:
        return ()
    names: list[str] = []
    for decl in tools_for_stance(CATALOG, stance):
        names.append(decl.name)
        names.append(f"mcp__omnigent__{decl.name}")
    return tuple(dict.fromkeys(names))


def framework_instruction_texts(params: object) -> tuple[str, ...]:
    """Launch-stable Coral framework text for a native step's append-system-prompt."""
    stance = generated_stance(params if isinstance(params, dict) else None)
    if stance is None:
        return ()
    return tuple(dict.fromkeys(decl.instructions for decl in tools_for_stance(CATALOG, stance)))


async def ensure_native_pane(
    session_id: str, *, relaunch: Callable[[], Awaitable[None] | None] | None
) -> None:
    """Wake a claude-native pane before the next brief; *relaunch* performs the restart."""
    del session_id
    if relaunch is None:
        return
    result = relaunch()
    if result is not None:
        await result


__all__ = [
    "ensure_native_pane",
    "framework_instruction_texts",
    "native_preapproved_tool_names",
]
