"""``coral_assign_agents`` and ``coral_assign_task`` planners (TLS-04)."""

from __future__ import annotations

from collections.abc import Mapping

from coral.db.enum_codecs import SessionBindingProgress, SessionBindingRole, SlotRole
from coral.engine.machines.activation import find_activation
from coral.engine.machines.slot import find_slot
from coral.engine.types import AssignAgents, AssignTask
from coral.tools import replies
from coral.tools.dispatch import EngineToolCall
from coral.tools.handlers.common import (
    pause_reason,
    run_stop,
    text_argument,
    unknown_arguments_message,
)
from coral.tools.handlers.message_agent import _resolve_member
from coral.tools.port import Commit, Plan, Reply, RunSnapshot
from coral.tools.schemas import (
    ASSIGN_AGENTS_PARAMETERS,
    ASSIGN_COUNT_MAX,
    ASSIGN_REASON_MAX,
    ASSIGN_TASK_MAX,
    ASSIGN_TASK_PARAMETERS,
)

_AGENTS_FIELDS = frozenset(
    ASSIGN_AGENTS_PARAMETERS["properties"]
    if isinstance(ASSIGN_AGENTS_PARAMETERS["properties"], Mapping)
    else ()
)
_TASK_FIELDS = frozenset(
    ASSIGN_TASK_PARAMETERS["properties"]
    if isinstance(ASSIGN_TASK_PARAMETERS["properties"], Mapping)
    else ()
)


def plan_assign_agents(snapshot: RunSnapshot, *, call: EngineToolCall) -> Plan:
    """Answer one ``coral_assign_agents`` call."""
    refused = _not_orchestrator(snapshot, call)
    if refused is not None:
        return refused
    fenced = _run_fence(snapshot)
    if fenced is not None:
        return fenced
    arguments = call.arguments
    unknown = [name for name in arguments if name not in _AGENTS_FIELDS]
    if unknown:
        return Reply(
            replies.illegal_message(
                "arguments", unknown_arguments_message(unknown, _AGENTS_FIELDS)
            ),
            log="unknown arguments",
        )
    activation_id = arguments.get("activation_id")
    if not isinstance(activation_id, str) or not activation_id:
        return Reply(
            replies.illegal_message(
                "activation_id", "Give the activation waiting for assignment."
            ),
            log="no activation",
        )
    reason = text_argument(arguments.get("reason"), ASSIGN_REASON_MAX)
    if reason is None:
        return Reply(
            replies.illegal_message(
                "reason", f"Give a reason of 1 to {ASSIGN_REASON_MAX} characters."
            ),
            log="no reason",
        )
    raw = arguments.get("assignments")
    if not isinstance(raw, list) or not raw:
        return Reply(
            replies.illegal_message("assignments", "Give at least one profile assignment."),
            log="no assignments",
        )
    parsed: list[tuple[str, int]] = []
    for item in raw:
        if not isinstance(item, Mapping):
            return Reply(
                replies.illegal_message("assignments", "Each assignment needs profile and count."),
                log="bad assignment",
            )
        profile = item.get("profile")
        count = item.get("count")
        if not isinstance(profile, str) or not profile:
            return Reply(
                replies.illegal_message("assignments", "Each assignment needs a profile."),
                log="bad profile",
            )
        if (
            isinstance(count, bool)
            or not isinstance(count, int)
            or not 1 <= count <= ASSIGN_COUNT_MAX
        ):
            return Reply(
                replies.illegal_message(
                    "assignments", f"Each count must be from 1 to {ASSIGN_COUNT_MAX}."
                ),
                log="bad count",
            )
        parsed.append((profile, count))
    command = AssignAgents(
        activation_id=activation_id,
        assignments=tuple(parsed),
        reason=reason,
    )
    members = tuple(
        f"{profile}#{index + 1}" for profile, count in parsed for index in range(count)
    )
    return Commit((command,), replies.agents_assigned(members))


def plan_assign_task(snapshot: RunSnapshot, *, call: EngineToolCall) -> Plan:
    """Answer one ``coral_assign_task`` call."""
    refused = _not_orchestrator(snapshot, call)
    if refused is not None:
        return refused
    fenced = _run_fence(snapshot)
    if fenced is not None:
        return fenced
    arguments = call.arguments
    unknown = [name for name in arguments if name not in _TASK_FIELDS]
    if unknown:
        return Reply(
            replies.illegal_message("arguments", unknown_arguments_message(unknown, _TASK_FIELDS)),
            log="unknown arguments",
        )
    activation_id = arguments.get("activation_id")
    if not isinstance(activation_id, str) or not activation_id:
        return Reply(
            replies.illegal_message("activation_id", "Give the merge_conflict activation id."),
            log="no activation",
        )
    owner = find_activation(snapshot.state, activation_id)
    if owner is None or owner.sub_state != "merge_conflict":
        return Reply(
            replies.illegal_message(
                "activation_id", "Only a merge_conflict activation can be re-tasked."
            ),
            log="not in merge_conflict",
        )
    member = _resolve_member(snapshot, arguments.get("member"))
    if member is None or find_slot(snapshot.state, member) is None:
        return Reply(
            replies.illegal_message("member", "Use a member id of this activation."),
            log="unknown member",
        )
    task = text_argument(arguments.get("task"), ASSIGN_TASK_MAX)
    if task is None:
        return Reply(
            replies.illegal_message("task", f"Give a task of 1 to {ASSIGN_TASK_MAX} characters."),
            log="no task",
        )
    reason = text_argument(arguments.get("reason"), ASSIGN_REASON_MAX)
    if reason is None:
        return Reply(
            replies.illegal_message(
                "reason", f"Give a reason of 1 to {ASSIGN_REASON_MAX} characters."
            ),
            log="no reason",
        )
    command = AssignTask(
        activation_id=activation_id,
        member_slot_id=member,
        task=task,
        reason=reason,
    )
    return Commit((command,), replies.task_assigned())


def _not_orchestrator(snapshot: RunSnapshot, call: EngineToolCall) -> Reply | None:
    binding = call.binding
    if (
        binding.role is not SessionBindingRole.STEP
        or binding.slot_role is not SlotRole.ORCHESTRATOR
        or binding.progress < SessionBindingProgress.ROW_CREATED
        or binding.run_id != snapshot.run.id
        or binding.workspace_id != snapshot.run.workspace_id
    ):
        return Reply(replies.not_orchestrator(), log="not an orchestrator of this run")
    if snapshot.run.orchestrator_session_id != binding.session_id:
        return Reply(replies.not_orchestrator(), log="replaced orchestrator")
    return None


def _run_fence(snapshot: RunSnapshot) -> Reply | None:
    stop = run_stop(snapshot)
    if stop == "cancelled":
        return Reply(replies.run_cancelled(), log="assign after cancel")
    if stop == "finished":
        return Reply(replies.decision_closed(), log="run finished")
    if stop == "paused":
        return Reply(replies.choice_paused(pause_reason(snapshot)))
    return None
