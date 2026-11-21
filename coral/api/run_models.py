"""The runs API's request and response models, and how a run's rows become them.

Every response model is frozen and sends every field. Names are the stored codes'
names; a run's actions come from :func:`coral.runview.actions.allowed_actions`.
Request models refuse unknown fields, and their refusals never quote the value.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Annotated, Any, Final, Literal, cast

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, JsonValue

from coral.api.errors import CoralApiError
from coral.api.spend import CachedSpend
from coral.bridge.config import MAX_RUN_ACTIVATIONS
from coral.bridge.messages import gate_prompt_text, sanitize
from coral.bridge.service import LOAD_FAILED_DETAIL, RunRead
from coral.db.enum_codecs import (
    GateVisitStatus,
    LogKind,
    decode_actor_kind,
    decode_log_kind,
    decode_run_pause_reason,
    decode_run_status,
    decode_slot_role,
    decode_slot_status,
)
from coral.engine import types as engine
from coral.engine.machines.activation import find_node
from coral.engine.projection import RunView, project
from coral.engine.types import JsonPatch, PauseCause
from coral.gates.ids import MAX_GATE_NOTE_CHARS, MAX_GATE_OUTCOME_CHARS
from coral.model.ids import anchor_session_id
from coral.model.ir import CompiledGraph
from coral.runview.actions import RunViewFacts, allowed_actions
from coral.runview.patch import stored_view_patch
from coral.runview.types import (
    ActorKindName,
    EntryFrame,
    LoadError,
    PauseReasonName,
    RunAction,
    RunHeader,
    RunStatusName,
)
from coral.stores.protocols import CoralRun, GateVisitState, RunLogEntry
from coral.workspace.run_worktree import run_branch_name

RUN_ID = re.compile(r"[0-9a-f]{32}")
WORKFLOW_ID_PATTERN = r"^[0-9a-f]{32}$"
# ``<created_at>:<run id>`` of the last run a page listed.
_RUN_CURSOR = re.compile(r"([0-9]{1,19}):([0-9a-f]{32})")
MAX_RUN_CURSOR_CHARS = 64
MAX_STORED_INT = 2**63 - 1
DEFAULT_RUNS_LIMIT = 25
# Status values one list request may name; there are six statuses.
MAX_STATUS_FILTERS = 6
DEFAULT_LOG_LIMIT = 50
MAX_LOG_LIMIT = 100
# A log page sends at most this many bytes of bodies and patches; a body over the other
# cap is left out.
MAX_LOG_PAGE_BYTES = 1 << 20
MAX_LOG_BODY_BYTES = 256 << 10
# The entry kind of a row whose stored text cannot be read.
UNREADABLE_LOG_KIND = "log.unreadable"
# A visit token is an activation id and a visit number, as long as a gate row stores.
MAX_VISIT_TOKEN_CHARS = 512
START_KEY_PATTERN = r"^[A-Za-z0-9_-]{1,64}$"
ACTIVATION_ID_PATTERN = r"^[0-9a-f]{32}$"
# C0 and C1 controls and DEL; the bidirectional marks, embeddings, overrides and isolates.
_CONTROLS = re.compile("[\x00-\x1f\x7f-\x9f]")
_BIDI_CONTROLS = re.compile("[\u061c\u200e\u200f\u202a-\u202e\u2066-\u2069]")
MAX_TITLE_CHARS = 256

SlotRoleName = Literal["step_agent", "orchestrator", "verifier", "merge_resolver"]
SlotStatusName = Literal[
    "pending",
    "session_created",
    "briefed",
    "working",
    "handoff_accepted",
    "rejected",
    "refreshing",
    "restarting",
    "closed",
    "evaluating",
    "closing",
]


class _Out(BaseModel):
    # Defaulted fields are always sent, so the schema lists them as required.
    model_config = ConfigDict(
        frozen=True, extra="forbid", json_schema_serialization_defaults_required=True
    )


class _In(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


def _storable(value: str) -> str:
    # The messages name the rule, never the value, which a refusal must not echo.
    if sanitize(value) != value:
        raise ValueError("must not hold NUL or unpaired surrogate characters")
    return value


def _not_an_option(value: str) -> str:
    if value.startswith("-"):
        raise ValueError("must not start with '-'")
    return value


def _no_control_characters(value: str, *, allowed: str = "") -> str:
    if any(char not in allowed for char in _CONTROLS.findall(value)):
        raise ValueError("must not hold control characters")
    return value


def _no_controls(value: str, *, allowed: str = "") -> str:
    _no_control_characters(value, allowed=allowed)
    if _BIDI_CONTROLS.search(value):
        raise ValueError("must not hold bidirectional control characters")
    return value


def _one_line(value: str) -> str:
    return _no_controls(value)


def _lines(value: str) -> str:
    return _no_controls(value, allowed="\n\t")


def default_title(name: str, fallback: str) -> str:
    """
    A run's title from its workflow's name, holding nothing a given title may not: the
    name without control and bidirectional characters, cut to fit; ``fallback`` if empty.
    """
    cleaned = " ".join(_BIDI_CONTROLS.sub("", _CONTROLS.sub(" ", sanitize(name))).split())
    return (cleaned or fallback)[:MAX_TITLE_CHARS]


_Text = AfterValidator(_storable)
_OneLine = AfterValidator(_one_line)
HostId = Annotated[str, Field(min_length=1, max_length=64), _Text, _OneLine]
# Paths may hold any other character the host's file system allows.
RepoPath = Annotated[
    str, Field(min_length=1, max_length=2048), _Text, AfterValidator(_no_control_characters)
]
BaseRef = Annotated[
    str, Field(min_length=1, max_length=255), _Text, _OneLine, AfterValidator(_not_an_option)
]
RunTitle = Annotated[str, Field(min_length=1, max_length=MAX_TITLE_CHARS), _Text, _OneLine]
RunRequestText = Annotated[str, Field(max_length=512), _Text, AfterValidator(_lines)]
# Strict: a JSON ``true`` or ``"5"`` is not a count.
ActivationCap = Annotated[int, Field(ge=1, le=MAX_RUN_ACTIVATIONS, strict=True)]


class StartRunRequest(_In):
    """
    A start of one of the caller's workflows on their host's repository.

    ``start_key`` makes the start idempotent: the same key and request answer the run
    it started, another request with the key is a conflict. ``title`` defaults to the
    workflow's name; ``base_ref`` to the repository's checked-out head.
    """

    workflow_id: Annotated[str, Field(pattern=WORKFLOW_ID_PATTERN)]
    start_key: Annotated[str, Field(pattern=START_KEY_PATTERN)]
    host_id: HostId
    repo_path: RepoPath
    base_ref: BaseRef | None = None
    title: RunTitle | None = None
    request: RunRequestText = ""
    max_activations: ActivationCap = 100


class ResumeRequest(_In):
    """A resume; ``cap`` raises the activation cap of a run paused at it."""

    cap: ActivationCap | None = None


class EmptyRequest(_In):
    """The body of an action that takes no arguments: the empty JSON object."""


class GateAnswerRequest(_In):
    """An answer to one visit of a gate: the visit's token, the chosen outcome and a note."""

    visit_token: Annotated[str, Field(min_length=1, max_length=MAX_VISIT_TOKEN_CHARS), _Text]
    outcome: Annotated[str, Field(min_length=1, max_length=MAX_GATE_OUTCOME_CHARS), _Text]
    note: Annotated[str, Field(max_length=MAX_GATE_NOTE_CHARS), _Text] = ""


class GateAnswerOut(_Out):
    """A taken answer; ``duplicate`` when the same answer was taken before."""

    result: Literal["accepted", "duplicate"]


class RunSpendTokens(_Out):
    """Tokens a run's sessions used, summed over its whole session tree."""

    input: int
    output: int
    total: int
    cache_read: int
    cache_creation: int


class RunSpend(_Out):
    """
    What a run has spent so far, as last read: shown, never capped.

    ``usd`` is the display figure its anchor's badge shows, ``live_usd`` includes
    spend still in flight; both are ``None`` when no session was priced and a lower
    bound when ``unpriced_models`` is not empty. ``as_of`` is when it was read.
    """

    estimate: Literal[True] = True
    usd: float | None
    live_usd: float | None
    tokens: RunSpendTokens
    unpriced_models: tuple[str, ...]
    sessions: int
    as_of: int


class RunSummary(_Out):
    """A run as its owner's run list shows it; ``run_branch`` is derived from its id."""

    run_id: str
    workflow_id: str
    version_id: str
    title: str
    status: RunStatusName
    pause_reason: PauseReasonName | None
    created_at: int
    updated_at: int
    finished_at: int | None
    activation_count: int
    allowed_actions: tuple[RunAction, ...]
    spend: RunSpend | None
    run_branch: str


class RunTarget(_Out):
    """Where the run works: its host, repository and worktree branch."""

    host_id: str | None
    repo_path: str | None
    worktree_path: str | None
    run_branch: str | None
    base_ref: str | None
    base_commit: str | None


class GateOut(_Out):
    """
    A gate visit waiting for its answer. ``context`` is what its approval prompt asks;
    ``None`` when the run's engine state cannot be loaded or does not hold the visit.
    """

    visit_id: str
    node_id: str
    token: str
    visit_no: int
    elicitation_id: str | None
    opened_at: int
    outcomes: tuple[str, ...]
    context: str | None


class SlotOut(_Out):
    """
    An agent slot of one of the run's steps. ``slot_id`` and ``activation_id`` are store
    ids; ``engine_slot_id`` is the id the run view's slots carry.
    """

    slot_id: str
    node_id: str
    activation_id: str
    role: SlotRoleName
    status: SlotStatusName
    session_id: str | None
    session_generation: int
    engine_slot_id: str


class RunDetail(RunSummary):
    """
    One run in full. ``view`` is ``None`` and ``load_error`` is set for a run that
    cannot be loaded; ``target``, ``max_activations`` and ``request_preview`` are
    ``None`` when its stored rows cannot be read.
    """

    version: int
    head_seq: int
    max_activations: int | None
    request_preview: str | None
    target: RunTarget | None
    anchor_session_id: str
    orchestrator_session_id: str | None
    causes: tuple[PauseCause, ...]
    load_error: LoadError | None
    view: RunView | None
    gates: tuple[GateOut, ...]
    slots: tuple[SlotOut, ...]


# Why a run's outcome has no diff.
OutcomeUnavailable = Literal[
    # The run is not completed, failed or cancelled.
    "run_not_finished",
    # The spec names no host, repository, worktree or branch, or another run's branch.
    "no_worktree",
    # The spec recorded no base commit.
    "base_unknown",
    # An unfinished run of the workspace uses the same host.
    "host_busy",
    # No host channels, or the host is offline or no longer the owner's to use.
    "host_offline",
    # The host refused the target: a removed or displaced worktree, or another branch.
    "worktree_missing",
    # Git could not compare the commits, such as a base the repository lacks.
    "compare_failed",
    # Too many reads in flight, or the host did not answer in time.
    "busy",
    # Anything else, such as a host without the op or a malformed reply.
    "failed",
]
# Why a run's outcome has no checkout command.
CheckoutUnavailable = Literal["no_worktree", "unsafe_path", "non_posix_path"]


class OutcomeDiff(_Out):
    """
    What a run changed, from ``from_commit`` (its base) to ``to_commit`` (its head when
    read). The counts cover the whole diff; ``paths`` holds at most 100 sorted paths,
    each shown with backslashes and unsafe or invisible characters as ``\\u{XXXX}`` and
    cut at 512 characters, and ``paths_truncated`` says whether the host or the server
    cut it.
    """

    from_commit: str
    to_commit: str
    files_changed: int
    insertions: int
    deletions: int
    paths: tuple[str, ...]
    paths_truncated: bool


class OutcomeCheckout(_Out):
    """
    How to check out a run's branch: ``command`` moves the repository's main checkout to
    the branch tip (detached), ``worktree_command`` opens the run's worktree. Both are
    ``None`` with ``unavailable`` set when no safe command can be built.
    """

    command: str | None
    worktree_command: str | None
    unavailable: CheckoutUnavailable | None


class RunOutcome(_Out):
    """
    What one of the caller's runs produced and how to check it out.

    Exactly one of ``diff`` and ``diff_unavailable`` is set. ``branch`` and the host
    fields are ``None`` when the run has no worktree of its own; the two paths are also
    ``None`` when no command could be built for them. ``head_commit`` is the branch tip
    the host reported now.
    """

    run_id: str
    status: RunStatusName
    finished_at: int | None
    branch: str | None
    host_id: str | None
    repo_path: str | None
    worktree_path: str | None
    base_commit: str | None
    head_commit: str | None
    diff: OutcomeDiff | None
    diff_unavailable: OutcomeUnavailable | None
    checkout: OutcomeCheckout


class RunPage(_Out):
    """One page of runs, newest first; page again with ``next_cursor`` until it is null."""

    data: tuple[RunSummary, ...]
    next_cursor: str | None


class LogEntryOut(_Out):
    """
    One run-log row with its body: the stream's entry frame plus ``body``. ``body`` is
    ``None`` for a row that cannot be read (``kind`` ``log.unreadable``) and, with
    ``body_truncated``, for a body too large to send. ``actor_kind`` is ``None`` only on
    such a row, for a code this server does not know.
    """

    type: Literal["entry"] = "entry"
    seq: int = Field(ge=1)
    run_version: int = Field(ge=0)
    kind: str
    actor_kind: ActorKindName | None
    actor: str | None
    node_id: str | None
    scope_key: str | None
    at_us: int
    rejected: str | None
    patch: tuple[JsonPatch, ...] = ()
    body: dict[str, JsonValue] | None
    body_truncated: bool


class LogPage(_Out):
    """Log rows in ``seq`` order; ``next_after_seq`` is set when more rows follow."""

    data: tuple[LogEntryOut, ...]
    next_after_seq: int | None


def parse_run_cursor(after: str) -> tuple[int, str]:
    """
    The ``(created_at, run id)`` a page's ``next_cursor`` named.

    :raises ValueError: longer than 64 characters, or not ``<0..2^63-1>:<32 lowercase hex>``.
    """
    match = _RUN_CURSOR.fullmatch(after) if len(after) <= MAX_RUN_CURSOR_CHARS else None
    if match is None or int(match[1]) > MAX_STORED_INT:
        raise ValueError("invalid run cursor")
    return int(match[1]), match[2]


def format_run_cursor(cursor: tuple[int, str] | None) -> str | None:
    return None if cursor is None else f"{cursor[0]}:{cursor[1]}"


def invalid_run_cursor() -> CoralApiError:
    """The refusal for a list cursor no page returned."""
    return CoralApiError("validation_failed", "Invalid run cursor.", 422)


def row_status(run: CoralRun) -> RunStatusName:
    return cast(RunStatusName, decode_run_status(run.status))


def row_pause_reason(run: CoralRun) -> PauseReasonName | None:
    code = run.pause_reason
    return None if code is None else cast(PauseReasonName, decode_run_pause_reason(code))


def run_spend(cached: CachedSpend | None) -> RunSpend | None:
    if cached is None:
        return None
    totals = cached.totals
    return RunSpend(
        usd=totals.usd,
        live_usd=totals.live_usd,
        tokens=RunSpendTokens(
            input=totals.input_tokens,
            output=totals.output_tokens,
            total=totals.total_tokens,
            cache_read=totals.cache_read_tokens,
            cache_creation=totals.cache_creation_tokens,
        ),
        unpriced_models=totals.unpriced_models,
        sessions=totals.sessions,
        as_of=cached.as_of,
    )


def run_summary(
    run: CoralRun, *, actions: tuple[RunAction, ...], spend: CachedSpend | None
) -> RunSummary:
    return RunSummary(
        run_id=run.id,
        workflow_id=run.workflow_id,
        version_id=run.version_id,
        title=run.title,
        status=row_status(run),
        pause_reason=row_pause_reason(run),
        created_at=run.created_at,
        updated_at=run.updated_at,
        finished_at=run.finished_at,
        activation_count=run.activation_count,
        allowed_actions=actions,
        spend=run_spend(spend),
        run_branch=run_branch_name(run.id),
    )


def list_item_actions(run: CoralRun) -> tuple[RunAction, ...]:
    """What a list item offers: the row alone, a subset of what its detail offers."""
    return allowed_actions(
        row_status=row_status(run),
        row_pause_reason=row_pause_reason(run),
        view=None,
        loadable=True,
    )


# Shown for a run that cannot be loaded, whatever its row's pause says.
_LOAD_FAILED_CAUSE: Final = PauseCause(
    reason="failure_path", detail=LOAD_FAILED_DETAIL, subject=""
)


def _gate_context(
    row: GateVisitState, graph: CompiledGraph, state: engine.RunState, run_title: str
) -> str | None:
    """The approval prompt's text of the engine visit ``row`` stores, if the state holds it."""
    visit = next((visit for visit in state.gates if visit.token == row.token), None)
    return None if visit is None else gate_prompt_text(graph, state, visit, run_title=run_title)


def _gate_out(
    row: GateVisitState,
    graph: CompiledGraph | None,
    state: engine.RunState | None,
    run_title: str,
) -> GateOut:
    node = None if graph is None else find_node(graph, row.node_id)
    return GateOut(
        visit_id=row.id,
        node_id=row.node_id,
        token=row.token,
        visit_no=row.visit_no,
        elicitation_id=row.elicitation_id,
        opened_at=row.opened_at,
        outcomes=() if node is None or node.kind != "gate" else node.outcomes,
        context=None
        if graph is None or state is None
        else _gate_context(row, graph, state, run_title),
    )


def _read_actions(read: RunRead, view: RunView | None) -> tuple[RunAction, ...]:
    """What the run offers, judged from its row and, when it loaded, its engine."""
    return allowed_actions(
        row_status=row_status(read.run),
        row_pause_reason=row_pause_reason(read.run),
        view=None if view is None else RunViewFacts.of(view),
        loadable=read.loadable,
    )


def run_header(run: CoralRun, view: RunViewFacts | None) -> RunHeader:
    """
    The run row as the stream shows it. What it allows is judged with the stream's own
    copy of the view; ``view`` is ``None`` for a run whose view cannot be loaded.
    """
    status, reason = row_status(run), row_pause_reason(run)
    return RunHeader(
        status=status,
        pause_reason=reason,
        version=run.version,
        finished_at=run.finished_at,
        allowed_actions=allowed_actions(
            row_status=status, row_pause_reason=reason, view=view, loadable=view is not None
        ),
        load_error=None if view is not None else "engine.load_failed",
    )


def read_summary(read: RunRead) -> RunSummary:
    """The run as a write answers it, without spend: the row, with its detail's actions."""
    view = None if read.snapshot is None else project(read.snapshot.state)
    return run_summary(read.run, actions=_read_actions(read, view), spend=None)


def run_detail(read: RunRead) -> RunDetail:
    """The run as its detail shows it, without spend, from a read that never writes."""
    run, rows, snapshot = read.run, read.rows, read.snapshot
    view = None if snapshot is None else project(snapshot.state)
    actions = _read_actions(read, view)
    spec = None if rows is None else rows.spec
    graph = None if snapshot is None else snapshot.graph
    state = None if snapshot is None else snapshot.state
    gates = (
        ()
        if rows is None
        else tuple(
            _gate_out(row, graph, state, run.title)
            for row in sorted(rows.gate_visits, key=lambda row: (row.opened_at, row.id))
            if row.status == GateVisitStatus.OPEN
        )
    )
    slots = (
        ()
        if rows is None
        else tuple(
            SlotOut(
                slot_id=slot.id,
                node_id=slot.node_id,
                activation_id=slot.activation_id,
                role=cast(SlotRoleName, decode_slot_role(slot.role)),
                status=cast(SlotStatusName, decode_slot_status(slot.status)),
                session_id=slot.session_id,
                session_generation=slot.session_generation,
                engine_slot_id=slot.scope_key,
            )
            for slot in rows.agent_slots
        )
    )
    summary = run_summary(run, actions=actions, spend=None)
    return RunDetail(
        **dict(summary),
        version=run.version,
        head_seq=run.next_log_seq - 1,
        max_activations=None if spec is None else spec.max_activations,
        request_preview=None if spec is None else spec.request_preview,
        target=None
        if spec is None
        else RunTarget(
            host_id=spec.host_id,
            repo_path=spec.repo_path,
            worktree_path=spec.worktree_path,
            run_branch=spec.run_branch,
            base_ref=spec.base_ref,
            base_commit=spec.base_commit,
        ),
        anchor_session_id=anchor_session_id(run.workspace_id, run.id),
        orchestrator_session_id=run.orchestrator_session_id,
        causes=(_LOAD_FAILED_CAUSE,) if view is None else view.causes,
        load_error=None if read.loadable else "engine.load_failed",
        view=view,
        gates=gates,
        slots=slots,
    )


def _json_object(text: str) -> dict[str, JsonValue] | None:
    try:
        value = json.loads(text)
    except ValueError:
        return None
    return value if isinstance(value, dict) else None


def _engine_facts(body: dict[str, JsonValue] | None) -> tuple[str | None, str | None]:
    """An engine row's input kind and rejection code, as far as its body names them."""
    if body is None:
        return None, None
    entry_input, rejection = body.get("input"), body.get("rejection")
    kind = entry_input.get("kind") if isinstance(entry_input, dict) else None
    code = rejection.get("code") if isinstance(rejection, dict) else None
    return (
        kind if isinstance(kind, str) else None,
        code if isinstance(code, str) else None,
    )


def _decoded(code: int, decode: Callable[[int], str]) -> str | None:
    """A stored code's name, or ``None`` for a code this server does not know."""
    try:
        return decode(code)
    except ValueError:
        return None


def _row_fields(row: RunLogEntry, actor_kind: ActorKindName | None) -> dict[str, Any]:
    return {
        "seq": row.seq,
        "run_version": row.run_version,
        "actor_kind": actor_kind,
        "actor": row.actor_ref,
        "node_id": row.node_id,
        "scope_key": row.scope_key,
        "at_us": row.created_at_us,
    }


@dataclass(frozen=True)
class _Readable:
    """What a row needs to be shown: its patch and the names of its codes."""

    patch: tuple[JsonPatch, ...]
    log_kind: str
    actor_kind: ActorKindName


def _readable(row: RunLogEntry) -> _Readable | None:
    """
    The row's stored view patch and code names; ``None`` when its stored text cannot be
    read or a code is one this server does not know (a newer server wrote it).
    """
    if row.unreadable:
        return None
    log_kind = _decoded(row.kind, decode_log_kind)
    actor_kind = _decoded(row.actor_kind, decode_actor_kind)
    if log_kind is None or actor_kind is None:
        return None
    try:
        patch = stored_view_patch(row.view_patch)
    except ValueError:
        return None
    return _Readable(patch=patch, log_kind=log_kind, actor_kind=cast(ActorKindName, actor_kind))


def _entry_kind(
    row: RunLogEntry, log_kind: str, body: dict[str, JsonValue] | None
) -> tuple[str, str | None]:
    """
    ``engine.<input kind>`` for an engine entry, else ``log.<log kind>``, and a refused
    input's rejection code.
    """
    kind = f"log.{log_kind}"
    if row.kind != LogKind.ENGINE:
        return kind, None
    input_kind, code = _engine_facts(body)
    return (
        kind if input_kind is None else f"engine.{input_kind}",
        code if row.audit_only else None,
    )


def entry_frame(row: RunLogEntry) -> EntryFrame | None:
    """
    The row as the run stream sends it, without its body; ``None`` for a row that cannot
    be read (:func:`_readable`). Only an engine row's body is parsed, for its kind.
    """
    readable = _readable(row)
    if readable is None:
        return None
    body = _json_object(row.body) if row.kind == LogKind.ENGINE else None
    kind, rejected = _entry_kind(row, readable.log_kind, body)
    return EntryFrame(
        **_row_fields(row, readable.actor_kind), kind=kind, rejected=rejected, patch=readable.patch
    )


def log_entry(row: RunLogEntry) -> LogEntryOut:
    """
    The row as ``/log`` sends it: the stream's entry with its body; ``kind`` is
    ``log.unreadable`` for a row that cannot be read, whose ``actor_kind`` is ``None``
    when it is a code this server does not know.
    """
    readable = _readable(row)
    if readable is None:
        actor_kind = _decoded(row.actor_kind, decode_actor_kind)
        return LogEntryOut(
            **_row_fields(row, cast(ActorKindName | None, actor_kind)),
            kind=UNREADABLE_LOG_KIND,
            rejected=None,
            body=None,
            body_truncated=False,
        )
    engine_row = row.kind == LogKind.ENGINE
    too_large = len(row.body.encode("utf-8")) > MAX_LOG_BODY_BYTES
    # An engine row's kind is in its body, so even one too large to send is parsed.
    body = None if too_large and not engine_row else _json_object(row.body)
    kind, rejected = _entry_kind(row, readable.log_kind, body)
    return LogEntryOut(
        **_row_fields(row, readable.actor_kind),
        kind=kind,
        rejected=rejected,
        patch=readable.patch,
        body=None if too_large else body,
        body_truncated=too_large,
    )


def _sent_bytes(entry: LogEntryOut, row: RunLogEntry) -> int:
    body = 0 if entry.body is None else len(row.body.encode("utf-8"))
    patch = 0 if not entry.patch or row.view_patch is None else len(row.view_patch.encode())
    return body + patch


def log_page(rows: Sequence[RunLogEntry], *, limit: int) -> LogPage:
    """
    Up to ``limit`` of ``rows`` (read one past it) and at most :data:`MAX_LOG_PAGE_BYTES`
    of their bodies and patches; ``next_after_seq`` is the last row sent when more are
    known to follow.
    """
    entries: list[LogEntryOut] = []
    sent = 0
    more = len(rows) > limit
    for row in rows[:limit]:
        entry = log_entry(row)
        size = _sent_bytes(entry, row)
        if entries and sent + size > MAX_LOG_PAGE_BYTES:
            more = True
            break
        entries.append(entry)
        sent += size
    return LogPage(data=tuple(entries), next_after_seq=entries[-1].seq if more else None)


__all__ = [
    "ACTIVATION_ID_PATTERN",
    "DEFAULT_LOG_LIMIT",
    "DEFAULT_RUNS_LIMIT",
    "MAX_LOG_BODY_BYTES",
    "MAX_LOG_LIMIT",
    "MAX_LOG_PAGE_BYTES",
    "MAX_RUN_CURSOR_CHARS",
    "MAX_STATUS_FILTERS",
    "MAX_STORED_INT",
    "MAX_TITLE_CHARS",
    "MAX_VISIT_TOKEN_CHARS",
    "RUN_ID",
    "START_KEY_PATTERN",
    "UNREADABLE_LOG_KIND",
    "WORKFLOW_ID_PATTERN",
    "CheckoutUnavailable",
    "EmptyRequest",
    "GateAnswerOut",
    "GateAnswerRequest",
    "GateOut",
    "LogEntryOut",
    "LogPage",
    "OutcomeCheckout",
    "OutcomeDiff",
    "OutcomeUnavailable",
    "ResumeRequest",
    "RunDetail",
    "RunOutcome",
    "RunPage",
    "RunSpend",
    "RunSpendTokens",
    "RunSummary",
    "RunTarget",
    "SlotOut",
    "SlotRoleName",
    "SlotStatusName",
    "StartRunRequest",
    "default_title",
    "entry_frame",
    "format_run_cursor",
    "invalid_run_cursor",
    "list_item_actions",
    "log_entry",
    "log_page",
    "parse_run_cursor",
    "read_summary",
    "row_pause_reason",
    "row_status",
    "run_detail",
    "run_header",
    "run_spend",
    "run_summary",
]
