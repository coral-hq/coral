"""The one declaration of Coral's engine tools: names, schemas, stances and prompt text.

Standard library only: hosts and runners import it through Coral's tool
provider. The production :data:`CATALOG` is empty, so no agent is offered a
tool until the engine can answer it; :data:`ENGINE_TOOLS` declares them all.
"""

from __future__ import annotations

import copy
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from coral.tools.schemas import CHOOSE_ARROW_PARAMETERS, SUBMIT_HANDOFF_PARAMETERS

TOOL_NAME_PREFIX = "coral_"
ORCHESTRATOR_STANCE = "orchestrator"
STEP_STANCES = frozenset({"implementer", "reviewer"})
# The anchor gets no engine tool.
TOOL_STANCES = STEP_STANCES | {ORCHESTRATOR_STANCE}
# OpenAI's tool-name limit, stricter than Omnigent's.
_TOOL_NAME = re.compile(r"[A-Za-z0-9_-]{1,64}")


@dataclass(frozen=True)
class EngineToolDecl:
    """
    One engine tool as an agent sees it.

    :param name: The tool name, e.g. ``"coral_submit_handoff"``.
    :param parameters: Its JSON Schema, plain JSON values.
    :param stances: The bundle stances offered the tool, e.g. ``{"implementer"}``.
    :param instructions: Prompt text appended for an agent offered the tool.
    """

    name: str
    description: str
    parameters: Mapping[str, object]
    stances: frozenset[str]
    instructions: str

    def schema(self) -> dict[str, object]:
        """The OpenAI-format tool schema, a fresh copy the caller may change."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": copy.deepcopy(dict(self.parameters)),
            },
        }


SUBMIT_HANDOFF = EngineToolDecl(
    name="coral_submit_handoff",
    description=(
        "Hand your result to Coral: done with a report of what you did, or blocked with "
        "what stops you. Call it once, when your work is done or you cannot continue."
    ),
    parameters=SUBMIT_HANDOFF_PARAMETERS,
    stances=STEP_STANCES,
    instructions=(
        "Coral step: when your work is done, or you cannot continue, call "
        "coral_submit_handoff with the activation id from your brief (it may be listed as "
        "mcp__omnigent__coral_submit_handoff; load it with ToolSearch if it is not listed). "
        "After Coral accepts the handoff, stop: Coral closes this session."
    ),
)

CHOOSE_ARROW = EngineToolDecl(
    name="coral_choose_arrow",
    description=(
        "Answer a Coral decision request: choose one of the labels it lists and give a "
        "short reason."
    ),
    parameters=CHOOSE_ARROW_PARAMETERS,
    stances=frozenset({ORCHESTRATOR_STANCE}),
    instructions=(
        "Coral orchestrator: answer each decision request by calling coral_choose_arrow "
        "with the decision id, one of the listed labels and a short reason. You cannot "
        "edit files, run commands or start agents."
    ),
)

ENGINE_TOOLS: tuple[EngineToolDecl, ...] = (SUBMIT_HANDOFF, CHOOSE_ARROW)
# What runners advertise: nothing until the engine can answer the tools.
CATALOG: tuple[EngineToolDecl, ...] = ()


def tools_for_stance(catalog: Sequence[EngineToolDecl], stance: str) -> tuple[EngineToolDecl, ...]:
    """The declarations of *catalog* offered to a bundle of *stance*, in catalog order."""
    return tuple(decl for decl in catalog if stance in decl.stances)


def orchestrator_tool_names() -> frozenset[str]:
    """The engine tools an orchestrator may call, whatever production advertises."""
    return frozenset(decl.name for decl in tools_for_stance(ENGINE_TOOLS, ORCHESTRATOR_STANCE))


def validate_catalog(catalog: Sequence[EngineToolDecl]) -> None:
    """
    Check that every declaration can be offered as an extension tool.

    :raises ValueError: For a name without the ``coral_`` prefix, with ``__``,
        longer than 64 characters or outside ``[A-Za-z0-9_-]``, declared twice,
        or a stance other than implementer, reviewer or orchestrator.
    """
    seen: set[str] = set()
    for decl in catalog:
        name = decl.name
        if not name.startswith(TOOL_NAME_PREFIX):
            raise ValueError(f"engine tool {name!r} must start with {TOOL_NAME_PREFIX}")
        if "__" in name:
            raise ValueError(f"engine tool {name!r} must not contain __")
        if _TOOL_NAME.fullmatch(name) is None:
            raise ValueError(f"engine tool {name!r} is not a valid tool name")
        if name in seen:
            raise ValueError(f"engine tool {name!r} is declared twice")
        seen.add(name)
        unknown = sorted(decl.stances - TOOL_STANCES)
        if unknown:
            raise ValueError(
                f"engine tool {name!r} names stance {unknown[0]!r}; "
                f"only {', '.join(sorted(TOOL_STANCES))} get engine tools"
            )


def generated_stance(params: object) -> str | None:
    """
    The stance a generated Coral bundle records in ``params.coral.generated.stance``.

    :param params: An agent spec's ``params``, read defensively.
    :returns: The stance string, e.g. ``"implementer"``; ``None`` when any level
        is missing or not the expected type.
    """
    coral = params.get("coral") if isinstance(params, Mapping) else None
    generated = coral.get("generated") if isinstance(coral, Mapping) else None
    stance = generated.get("stance") if isinstance(generated, Mapping) else None
    return stance if isinstance(stance, str) else None
