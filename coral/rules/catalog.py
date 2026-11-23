"""The rule template catalog: typed params, a plain-words statement and a guardrail policy each.

Pure tier: policies name their builtin handlers as dotted-path strings.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Annotated, Any

from pydantic import AfterValidator, BaseModel, ConfigDict, Field

CATALOG_VERSION = 1

_ORCHESTRATION = "omnigent.policies.builtins.orchestration"
_CEL_POLICY = "omnigent.policies.builtins.cel.cel_policy"
# Omnigent's file write tools, Claude's native ones, and Pi's lowercase aliases; the
# same set the worktree_guard and read_only_os builtins gate.
_WRITE_TOOLS = (
    "Edit",
    "MultiEdit",
    "NotebookEdit",
    "Write",
    "edit",
    "sys_os_edit",
    "sys_os_write",
    "write",
)
_PATH_ARGUMENTS = ("path", "file_path", "notebook_path")
# Steps' file tools resolve a relative path against the workspace root.
RELATIVE_PATHS = (
    "Give file tools paths relative to the workspace root; "
    "absolute, '~' and '..' paths are refused."
)
_PROTECTED_PATH = re.compile(r"[A-Za-z0-9._/-]{1,200}")


@dataclass(frozen=True)
class RuleTemplate:
    """One catalog entry; ``policy`` builds the guardrail policy body a Required rule adds."""

    id: str
    version: int
    title: str
    params_model: type[BaseModel]
    statement: Callable[[BaseModel], str]
    policy: Callable[[BaseModel], dict[str, Any]]
    bypasses: tuple[str, ...]


class NoParams(BaseModel):
    """Params of a template that takes none."""

    model_config = ConfigDict(frozen=True, extra="forbid")


def _protected_path(value: str) -> str:
    if _PROTECTED_PATH.fullmatch(value) is None:
        raise ValueError("use letters, digits, '.', '_', '-' and '/' only (at most 200)")
    path = value.rstrip("/")
    if any(segment in ("", ".", "..") for segment in path.split("/")):
        raise ValueError("use a relative path with no empty, '.' or '..' segment")
    return path


class ProtectPathsParams(BaseModel):
    """Workspace-relative path prefixes no file tool may change."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    paths: list[Annotated[str, AfterValidator(_protected_path)]] = Field(
        min_length=1, max_length=10
    )


def _function_policy(path: str, arguments: Mapping[str, object]) -> dict[str, Any]:
    return {
        "type": "function",
        "on": ["tool_call"],
        "function": {"path": path, "arguments": dict(arguments)},
    }


def _protect_paths_params(params: BaseModel) -> ProtectPathsParams:
    if not isinstance(params, ProtectPathsParams):
        raise TypeError(f"protect_paths takes ProtectPathsParams, got {type(params).__name__}")
    return params


def _protect_paths_statement(params: BaseModel) -> str:
    paths = _protect_paths_params(params).paths
    return f"Never change files under {', '.join(f'{path}/' for path in paths)}."


def protect_paths_pattern(paths: list[str]) -> str:
    """
    The regex a relative file tool path under a protected prefix matches.

    A prefix matches whole segments from the start of the path; ``./`` and
    repeated ``/`` between segments are skipped and case is ignored. Absolute
    and ``..`` paths are refused separately. The caller has
    already limited each prefix to ``[A-Za-z0-9._/-]`` with no empty, ``.`` or
    ``..`` segment.
    """
    separator = r"/+(\./+)*"
    prefixes = "|".join(
        separator.join(re.escape(segment) for segment in path.split("/")) for path in paths
    )
    return rf"(?i)^(\./+)*({prefixes})(/|$)"


def _any_path_matches(pattern: str) -> str:
    """CEL: some string path argument of the call matches *pattern*."""
    return (
        f"{json.dumps(list(_PATH_ARGUMENTS))}.exists(key, key in event.data.arguments"
        f" && type(event.data.arguments[key]) == string"
        f" && event.data.arguments[key].matches({json.dumps(pattern)}))"
    )


def _protect_paths_policy(params: BaseModel) -> dict[str, Any]:
    pattern = protect_paths_pattern(_protect_paths_params(params).paths)
    # json.dumps gives a valid CEL string literal for this charset. The tool name
    # comes from event.target (set by the runtime) like Coral's guards, else data.name.
    tool = "(type(event.target) == string ? event.target : event.data.name)"
    # A leading '/' or '~', a '..' segment or any backslash is not a workspace-relative
    # POSIX path.
    not_relative = r"^[/~]|\\|(^|/)\.\.(/|$)"
    expression = (
        f'event.type == "tool_call" && {tool} in {json.dumps(list(_WRITE_TOOLS))}'
        f" && has(event.data.arguments)"
        f" ? ({_any_path_matches(not_relative)}"
        f' ? {{"result": "DENY", "reason": {json.dumps(RELATIVE_PATHS)}}}'
        f' : {_any_path_matches(pattern)} ? {{"result": "DENY"}} : null)'
        " : null"
    )
    reason = f"This profile's rule says: {_protect_paths_statement(params)}"
    return _function_policy(_CEL_POLICY, {"expression": expression, "reason": reason})


def _fixed(text: str) -> Callable[[BaseModel], str]:
    return lambda _params: text


_TEMPLATES = (
    RuleTemplate(
        id="limit_blast_radius",
        version=1,
        title="Limit blast radius",
        params_model=NoParams,
        statement=_fixed(
            "Never run outward or destructive shell commands (push, merge, rm -rf, deploy)."
        ),
        policy=lambda _params: _function_policy(
            f"{_ORCHESTRATION}.blast_radius", {"risky_action": "DENY"}
        ),
        bypasses=("Indirect shell, such as a script or alias that runs the command.",),
    ),
    RuleTemplate(
        id="stay_in_worktree",
        version=1,
        title="Stay in the worktree",
        params_model=NoParams,
        statement=_fixed("Only edit files inside the run's worktree."),
        policy=lambda _params: _function_policy(
            f"{_ORCHESTRATION}.worktree_guard",
            {"allowed_root": ".", "deny_reason": RELATIVE_PATHS},
        ),
        bypasses=("None beyond the OS sandbox, which already confines writes.",),
    ),
    RuleTemplate(
        id="protect_paths",
        version=1,
        title="Protect paths",
        params_model=ProtectPathsParams,
        statement=_protect_paths_statement,
        policy=_protect_paths_policy,
        bypasses=(
            "Shell writes: the OS sandbox still allows the whole worktree.",
            "Symlinks that point into a protected path.",
            "Case: a prefix matches ignoring case, so INFRA/x is also blocked.",
        ),
    ),
)

CATALOG: Mapping[str, RuleTemplate] = MappingProxyType(
    {template.id: template for template in _TEMPLATES}
)
