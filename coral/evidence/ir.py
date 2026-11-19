"""K11 types: a step's evidence requirement, the observations it is judged on, the verdict."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from coral.evidence.match import argv_of

EVIDENCE_IR_VERSION = 1

EvidenceScope = Literal["per_agent"]
ObservedTool = Literal["shell", "write", "edit"]
MissingReason = Literal["never_ran", "predates_change", "failed", "exit_unknown"]


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class EvidenceIRError(ValueError):
    """A ``done_when`` block that cannot compile; ``yaml_path`` names the bad key."""

    def __init__(self, yaml_path: str, message: str) -> None:
        self.yaml_path = yaml_path
        super().__init__(f"{yaml_path}: {message}")


class RequiredCommand(_Frozen):
    """
    One command that must pass after the step's last change.

    :param run: Matched as an argv prefix of a shell segment, e.g. ``pytest -q``.
    :param may_modify: The command may change the tree (a formatter); its own
        changes do not count as the step's last change.
    """

    item_id: str
    run: str
    may_modify: bool = False


class EvidenceRequirement(_Frozen):
    ir_version: int = EVIDENCE_IR_VERSION
    scope: EvidenceScope = "per_agent"
    items: tuple[RequiredCommand, ...] = Field(min_length=1)


class CommandObservation(_Frozen):
    """
    One tool call of a step session, recorded before its result reached the agent.

    :param op_key: The call's idempotency key; a second record with it is ignored.
    :param obs_seq: Orders one session's observations (microseconds at completion).
    :param exit_code: The shell's structured exit code; ``None`` when unknown.
    :param l1_after: The worktree's L1 digest after a shell run; ``None`` when unknown.
    :param changed_path: The path a write or edit changed.
    """

    session_id: str
    op_key: str
    obs_seq: int
    tool: ObservedTool
    command: str | None = None
    exit_code: int | None = None
    timed_out: bool = False
    l1_after: str | None = None
    changed_path: str | None = None


class MissingItem(_Frozen):
    item_id: str
    run: str
    reason: MissingReason
    changed_path: str | None = None


class Pass(_Frozen):
    kind: Literal["pass"] = "pass"


class Missing(_Frozen):
    kind: Literal["missing"] = "missing"
    items: tuple[MissingItem, ...]


class InProgress(_Frozen):
    kind: Literal["in_progress"] = "in_progress"
    reason: str


EvidenceVerdict = Pass | Missing | InProgress


def compile_done_when(block: object, *, yaml_path: str) -> EvidenceRequirement:
    """
    Compile an authored ``done_when`` mapping: ``{commands: [{id?, run, may_modify?}]}``.

    :raises EvidenceIRError: For any shape problem, naming its yaml path.
    """
    if not isinstance(block, dict):
        raise EvidenceIRError(yaml_path, "done_when must be a mapping with a commands list")
    unknown = sorted(str(key) for key in block if key != "commands")
    if unknown:
        raise EvidenceIRError(f"{yaml_path}.{unknown[0]}", "unknown key; only commands is allowed")
    commands = block.get("commands")
    if not isinstance(commands, list) or not commands:
        raise EvidenceIRError(f"{yaml_path}.commands", "list at least one command")
    items: list[RequiredCommand] = []
    seen: set[str] = set()
    for index, entry in enumerate(commands):
        where = f"{yaml_path}.commands[{index}]"
        items.append(_compile_command(entry, where, default_id=f"c{index + 1}", seen=seen))
    return EvidenceRequirement(items=tuple(items))


def _compile_command(
    entry: object, where: str, *, default_id: str, seen: set[str]
) -> RequiredCommand:
    if not isinstance(entry, dict):
        raise EvidenceIRError(where, "each command is a mapping with a run key")
    unknown = sorted(str(key) for key in entry if key not in ("id", "run", "may_modify"))
    if unknown:
        raise EvidenceIRError(f"{where}.{unknown[0]}", "unknown key; use id, run and may_modify")
    run = entry.get("run")
    if not isinstance(run, str) or not run.strip():
        raise EvidenceIRError(f"{where}.run", "give the command to run")
    if not argv_of(run):
        raise EvidenceIRError(f"{where}.run", "the command must be one simple command")
    item_id = entry.get("id", default_id)
    if not isinstance(item_id, str) or not item_id:
        raise EvidenceIRError(f"{where}.id", "the id must be a non-empty string")
    if item_id in seen:
        raise EvidenceIRError(f"{where}.id", f"the id {item_id!r} is used twice")
    seen.add(item_id)
    may_modify = entry.get("may_modify", False)
    if not isinstance(may_modify, bool):
        raise EvidenceIRError(f"{where}.may_modify", "use true or false")
    return RequiredCommand(item_id=item_id, run=run.strip(), may_modify=may_modify)


__all__ = [
    "EVIDENCE_IR_VERSION",
    "CommandObservation",
    "EvidenceIRError",
    "EvidenceRequirement",
    "EvidenceVerdict",
    "InProgress",
    "Missing",
    "MissingItem",
    "MissingReason",
    "ObservedTool",
    "Pass",
    "RequiredCommand",
    "compile_done_when",
]
