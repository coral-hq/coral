"""Starting a run: the YAML is compiled and checked here, the graph pinned, StartRun committed.

The graph is never taken from the caller. A workflow is refused when the engine
could not run it safely: unresolved analysis, a profile without a step stance, a
gate with more outcomes than an answer and its alert hold or with a hidden
character in an outcome, two writers at once in
one worktree, more live slots, decisions and gates than one commit can carry, or
effect keys longer than an executor accepts, and when an arrow leaves a parallel
region while its other branches still run.

The bridge authorizes nothing, and it trusts the spec's fields as given, so the
caller (the runs API) must take them from the server, never from the request:
``user_id``, ``credential_ref`` and ``auth_mode`` from the authenticated actor;
``workflow_id`` and ``yaml_text`` from the stored definition, after checking the
actor may use it; and the run target from ``coral/workspace/run_worktree.py``.
The bridge itself sets the version, the limits it freezes and the format versions.
"""

from __future__ import annotations

import dataclasses
import re
from collections.abc import Iterator, Mapping

from coral.bridge.config import (
    ENGINE_VERSION,
    LOG_VERSION,
    MAX_LIVE_SLOTS,
    MAX_LIVE_WORK,
    MAX_REJECTED_CALL_LIMIT,
    MAX_RUN_ACTIVATIONS,
    STATE_VERSION,
    epoch_seconds,
    freeze_engine_config,
)
from coral.bridge.graphs import PinnedGraphMismatch, verified_content_hash
from coral.bridge.keys import decision_rerequest_key
from coral.bridge.mapping import FED_KINDS, UNMAPPED_KINDS
from coral.bridge.messages import sanitize, strip_format_characters
from coral.bridge.service import STORED_TEXT_ERRORS, EngineBridge, RunNotRunnable, RunRead
from coral.db.enum_codecs import (
    RUN_AUTH_MODE,
    RUN_EXECUTION_TARGET,
    RUN_TRIGGER_KIND,
    RunStatus,
)
from coral.engine.types import effect_key
from coral.gates.ids import MAX_GATE_OUTCOME_CHARS, MAX_GATE_OUTCOMES
from coral.model.ids import derived_id
from coral.model.ir import CompiledGraph, CompiledNode
from coral.queue.run_effects import MAX_EFFECT_KEY_CHARS
from coral.stores.protocols import CoralRun, RunNotFound, RunStartSpec, StartKeyConflict
from coral.stores.workflows import WorkflowTooLargeError
from coral.tools.catalog import STEP_STANCES
from coral.validate import ValidateContext
from coral.validate.pipeline import check_text
from coral.workspace.run_worktree import run_branch_name

# The one stance that writes the run worktree.
_WRITER = "implementer"
# Arrows region analysis does not follow.
_NON_STRUCTURAL = frozenset({"back", "failure"})
# Effect kinds a slot's effects use; the longest bounds the worst-case key.
_SLOT_KINDS = (*FED_KINDS, "cancel_sessions", *UNMAPPED_KINDS)
# Digits allowed for an engine seq and for an unlimited loop's pass index.
_SEQ_DIGITS = 10
_UNLIMITED_PASS_DIGITS = 6
_HEX32 = re.compile(r"[0-9a-f]{32}")
_MAX_START_KEY_CHARS = 256
# Text fields a spec stores, with their column widths.
_TEXT_LIMITS: Mapping[str, int] = {
    "title": 256,
    "request_preview": 512,
    "user_id": 128,
    "account_generation": 32,
    "request_ref": 512,
    "host_id": 64,
    "repository_id": 64,
    "repo_path": 2048,
    "worktree_path": 2048,
    "base_ref": 255,
    "base_commit": 64,
    "run_branch": 255,
    "credential_ref": 256,
}
# Coded fields a spec stores, with the codes their columns accept.
_CODE_FIELDS: Mapping[str, frozenset[int]] = {
    "trigger_kind": frozenset(RUN_TRIGGER_KIND.values()),
    "execution_target": frozenset(RUN_EXECUTION_TARGET.values()),
    "auth_mode": frozenset(RUN_AUTH_MODE.values()),
}
# Basis points of a context window.
_MAX_REFRESH_THRESHOLD_BP = 10_000


def start_engine_run(
    bridge: EngineBridge,
    *,
    spec: RunStartSpec,
    yaml_text: str,
    start_key: str,
    actor: str | None,
    allow_ownerless: bool = False,
    validate_ctx: ValidateContext | None = None,
    rejected_call_limit: int = 3,
) -> CoralRun:
    """
    Start a run of ``yaml_text`` on ``spec``'s target; a repeat with the same key and
    spec returns the same run and commits nothing.

    The spec's version, rejected-call limit and frozen engine config are set here. A
    repeat is replayed before the workflow is checked, so rules added since the run
    started do not refuse it, and it does not pause a run it cannot load (see
    :func:`replay_start`).
    A first start that a concurrent one of the same key beat is replayed the same way.

    :param actor: Who starts it, recorded on the run's first engine row; ``None`` only
        on a server without authentication.
    :param allow_ownerless: Accept a spec without ``user_id``: only on a single-user
        server, where its agents are the local user's; anywhere else its first create
        is refused ``session.invalid``.
    :raises RunNotRunnable: for the first rule the workflow or spec breaks.
    :raises StartKeyConflict: when the key started a run with other caller fields or
        another workflow, or one whose stored spec cannot be read back to compare.
    """
    existing = _existing_run(bridge, spec, start_key, allow_ownerless)
    if existing is not None:
        # A retry, perhaps after a deploy changed what the bridge derives: the run stands.
        return _replay(bridge, existing, spec, yaml_text, rejected_call_limit, validate_ctx, actor)
    graph = _checked_graph(yaml_text, validate_ctx)
    _refuse(_graph_refusals(graph))
    if spec.user_id is None and not allow_ownerless:
        raise RunNotRunnable("run.owner_required", "a run needs an owner")
    workspace_id = spec.workspace_id
    if workspace_id is None:
        raise RunNotRunnable("run.field_invalid", "the spec names no workspace")
    _refuse(_field_refusals(spec, start_key, rejected_call_limit))
    run_id = derived_id("coral-run", spec.user_id or "", start_key)
    _refuse(_target_refusals(spec, run_id))
    _refuse(_shape_refusals(graph, run_id))
    try:
        pinned = bridge.versions.pin(
            workspace_id=workspace_id,
            workflow_id=spec.workflow_id,
            graph=graph,
            yaml_text=yaml_text,
            created_by=spec.user_id,
        )
    except WorkflowTooLargeError as exc:
        raise RunNotRunnable("workflow.too_large", str(exc)) from None
    frozen = dataclasses.replace(
        spec,
        version_id=pinned.id,
        rejected_call_limit=rejected_call_limit,
        engine_config=freeze_engine_config(
            max_activations=spec.max_activations, rejected_call_limit=rejected_call_limit
        ),
        engine_version=ENGINE_VERSION,
        state_version=STATE_VERSION,
        log_version=LOG_VERSION,
    )
    try:
        run = bridge.run_store.start_run(
            frozen, start_key=start_key, now=epoch_seconds(bridge.now())
        )
    except StartKeyConflict:
        # A concurrent first start of this key stored the run first.
        raced = bridge.run_store.get_run(run_id, workspace_id=workspace_id)
        if raced is None:
            raise
        return _replay(bridge, raced, spec, yaml_text, rejected_call_limit, validate_ctx, actor)
    return _commit_start(bridge, run, actor)


def check_startable(
    yaml_text: str, *, run_id: str, validate_ctx: ValidateContext | None = None
) -> CompiledGraph:
    """
    Refuse a workflow ``start_engine_run`` would refuse, before any host or store is touched.

    The checks need only the workflow and the run id, so a caller can make them before
    it creates the run's worktree. A workflow too large to pin is refused by the start.

    :returns: The compiled graph a start would pin.
    :raises RunNotRunnable: for the first workflow rule the graph breaks.
    """
    graph = _checked_graph(yaml_text, validate_ctx)
    _refuse(_graph_refusals(graph))
    _refuse(_shape_refusals(graph, run_id))
    return graph


def replay_start(bridge: EngineBridge, read: RunRead, *, actor: str | None) -> CoralRun:
    """
    Finish a replayed start, and return the run's row.

    Only a run still starting whose engine ``read`` loaded unstarted commits its
    ``StartRun`` (a crash came between storing the run and starting it); a run that
    cannot be loaded, or one past starting, commits nothing, so it is never paused.
    That commit pauses a run whose stored data stopped decoding since ``read``.
    """
    run = read.run
    if (
        run.status != int(RunStatus.STARTING)
        or read.snapshot is None
        or read.snapshot.state.status is not None
    ):
        return run
    return _commit_start(bridge, run, actor)


def _commit_start(bridge: EngineBridge, run: CoralRun, actor: str | None) -> CoralRun:
    """Commit the run's ``StartRun`` (a no-op once its engine runs) and return the run."""
    bridge.commit_inputs(
        workspace_id=run.workspace_id,
        run_id=run.id,
        inputs=lambda snapshot: (bridge.start_input(snapshot),),
        actor=actor,
    )
    started = bridge.run_store.get_run(run.id, workspace_id=run.workspace_id)
    if started is None:
        raise RunNotFound(f"Run {run.id!r} not found in workspace {run.workspace_id}")
    return started


def _existing_run(
    bridge: EngineBridge, spec: RunStartSpec, start_key: str, allow_ownerless: bool
) -> CoralRun | None:
    """The run this key already started, when the inputs can name one."""
    if spec.workspace_id is None or (spec.user_id is None and not allow_ownerless):
        return None
    if not _clean_text(start_key, 1, _MAX_START_KEY_CHARS):
        return None
    run_id = derived_id("coral-run", spec.user_id or "", start_key)
    return bridge.run_store.get_run(run_id, workspace_id=spec.workspace_id)


def _replay(
    bridge: EngineBridge,
    run: CoralRun,
    spec: RunStartSpec,
    yaml_text: str,
    rejected_call_limit: int,
    validate_ctx: ValidateContext | None,
    actor: str | None,
) -> CoralRun:
    """The run this key started, once the retry is shown to be the same start."""
    read = bridge.read(workspace_id=run.workspace_id, run_id=run.id)
    _check_retry(bridge, read, spec, yaml_text, rejected_call_limit, validate_ctx)
    return replay_start(bridge, read, actor=actor)


def _check_retry(
    bridge: EngineBridge,
    read: RunRead,
    spec: RunStartSpec,
    yaml_text: str,
    rejected_call_limit: int,
    validate_ctx: ValidateContext | None,
) -> None:
    """
    Refuse a retry whose caller fields or workflow differ from the run's first start.

    The workflow is compared by its content hash, so an edit of comments or layout
    is the same workflow; one that no longer compiles is another.
    """
    run = read.run
    if read.rows is None:
        raise StartKeyConflict(f"run {run.id} cannot be read back to compare this start")
    stored = read.rows.spec
    if (
        _caller_owned(stored) != _caller_owned(spec)
        or stored.rejected_call_limit != rejected_call_limit
    ):
        raise StartKeyConflict(f"run {run.id} was started with other fields")
    try:
        pinned = bridge.versions.load(workspace_id=run.workspace_id, version_id=run.version_id)
    except (ValueError, *STORED_TEXT_ERRORS):
        # A row stored by reference only, or whose text does not decode.
        pinned = None
    if pinned is None:
        raise StartKeyConflict(f"run {run.id} cannot be read back to compare this start")
    if pinned.yaml_text == yaml_text:
        return
    checked = check_text(yaml_text, validate_ctx)
    if checked.graph is None or checked.graph.content_hash != pinned.content_hash:
        raise StartKeyConflict(f"run {run.id} was started with another workflow")


def _caller_owned(spec: RunStartSpec) -> RunStartSpec:
    """
    ``spec`` without the fields the bridge derives or writes later.

    The base commit is left out too: only the worktree's creation reports it, and a
    start that adopted the worktree cannot, so the stored target stands.
    """
    return dataclasses.replace(
        spec,
        version_id="",
        rejected_call_limit=0,
        engine_config=None,
        engine_version=0,
        state_version=0,
        log_version=0,
        orchestrator_session_id=None,
        base_commit=None,
    )


def _clean_text(value: str, shortest: int, longest: int) -> bool:
    """Within the length bounds, and free of NUL and lone surrogates, which no column takes."""
    return shortest <= len(value) <= longest and sanitize(value) == value


def _checked_graph(yaml_text: str, ctx: ValidateContext | None) -> CompiledGraph:
    checked = check_text(yaml_text, ctx)
    if checked.load_error is not None:
        code = (
            "workflow.too_large" if checked.load_error.code == "oversized" else "workflow.invalid"
        )
        raise RunNotRunnable(code, checked.load_error.message)
    if checked.graph is None or not checked.runnable:
        raise RunNotRunnable("workflow.invalid", "the workflow has validation errors")
    try:
        verified_content_hash(checked.graph)
    except PinnedGraphMismatch:
        raise RunNotRunnable("workflow.invalid", "the graph does not match its hash") from None
    return checked.graph


def _refuse(refusals: Iterator[RunNotRunnable]) -> None:
    first = next(refusals, None)
    if first is not None:
        raise first


def _steps(graph: CompiledGraph) -> list[CompiledNode]:
    return [node for node in graph.nodes if node.kind == "step"]


def _gates(graph: CompiledGraph) -> list[CompiledNode]:
    return [node for node in graph.nodes if node.kind == "gate"]


def _graph_refusals(graph: CompiledGraph) -> Iterator[RunNotRunnable]:
    if graph.analysis.unresolved:
        yield RunNotRunnable("graph.unresolved", graph.analysis.unresolved[0].message)
    if not any(node.kind == "start" for node in graph.nodes):
        yield RunNotRunnable("graph.no_start", "the workflow has no start node")
    for node in _steps(graph):
        unsupported = sorted(set(node.roster) - STEP_STANCES)
        if unsupported:
            yield RunNotRunnable(
                "profile.unsupported",
                f"step {node.id!r} uses {', '.join(unsupported)}; steps support "
                f"{', '.join(sorted(STEP_STANCES))}",
            )
    for node in _gates(graph):
        # A visit's alert lists every outcome, and its row stores the answer's label.
        if len(node.outcomes) > MAX_GATE_OUTCOMES:
            yield RunNotRunnable(
                "graph.gate_too_large",
                f"gate {node.id!r} has {len(node.outcomes)} outcomes; "
                f"the limit is {MAX_GATE_OUTCOMES}",
            )
        elif any(len(outcome) > MAX_GATE_OUTCOME_CHARS for outcome in node.outcomes):
            yield RunNotRunnable(
                "graph.gate_too_large",
                f"gate {node.id!r} has an outcome over {MAX_GATE_OUTCOME_CHARS} characters",
            )
        # An outcome is a button name and the answer's value, so a hidden character
        # (a bidi override, a zero-width space) is refused rather than removed.
        if any(strip_format_characters(outcome) != outcome for outcome in node.outcomes):
            yield RunNotRunnable(
                "graph.gate_label_invalid",
                f"gate {node.id!r} has an outcome with a control or invisible format character",
            )


def _field_refusals(
    spec: RunStartSpec, start_key: str, rejected_call_limit: int
) -> Iterator[RunNotRunnable]:
    def invalid(message: str) -> RunNotRunnable:
        return RunNotRunnable("run.field_invalid", message)

    if spec.orchestrator_session_id is not None:
        yield invalid("the orchestrator session is the bridge's to create")
    if not 1 <= spec.max_activations <= MAX_RUN_ACTIVATIONS:
        yield invalid(f"max_activations must be 1-{MAX_RUN_ACTIVATIONS}")
    if not 1 <= rejected_call_limit <= MAX_REJECTED_CALL_LIMIT:
        yield invalid(f"rejected_call_limit must be 1-{MAX_REJECTED_CALL_LIMIT}")
    if not _HEX32.fullmatch(spec.workflow_id):
        yield invalid("workflow_id must be the definition's 32-hex id")
    if not _clean_text(start_key, 1, _MAX_START_KEY_CHARS):
        yield invalid(f"the start key must be 1-{_MAX_START_KEY_CHARS} characters of text")
    for name, limit in _TEXT_LIMITS.items():
        value = getattr(spec, name)
        if isinstance(value, str) and not _clean_text(value, 0, limit):
            yield invalid(f"{name} must be at most {limit} characters of text")
    for name, codes in _CODE_FIELDS.items():
        if getattr(spec, name) not in codes:
            yield invalid(f"{name} is not a known code")
    if not 0 <= spec.refresh_threshold_bp <= _MAX_REFRESH_THRESHOLD_BP:
        yield invalid(f"refresh_threshold_bp must be 0-{_MAX_REFRESH_THRESHOLD_BP}")


def _target_refusals(spec: RunStartSpec, run_id: str) -> Iterator[RunNotRunnable]:
    missing = [
        name for name in ("host_id", "worktree_path", "repo_path") if not getattr(spec, name)
    ]
    if missing:
        yield RunNotRunnable("run.target_invalid", f"the run target has no {', '.join(missing)}")
    if spec.run_branch != run_branch_name(run_id):
        yield RunNotRunnable("run.target_invalid", "the run branch is not this run's branch")


def _shape_refusals(graph: CompiledGraph, run_id: str) -> Iterator[RunNotRunnable]:
    for region in graph.analysis.regions:
        inside = set(region.node_ids)
        for arrow in graph.arrows:
            # Region analysis follows forward arrows only; a back or failure arrow out of
            # a branch reopens a step while the other branches still run.
            if arrow.kind in _NON_STRUCTURAL and arrow.source in inside:
                if arrow.target not in inside:
                    yield RunNotRunnable(
                        "graph.leaves_region",
                        f"arrow {arrow.id!r} leaves the parallel steps after "
                        f"{region.split_node_id!r} while the other branches still run",
                    )
    steps = _steps(graph)
    writers = {node.id for node in steps if _WRITER in node.roster}
    for node in steps:
        if node.roster.count(_WRITER) > 1:
            yield RunNotRunnable(
                "graph.concurrent_writers", f"step {node.id!r} has two {_WRITER}s"
            )
    for region in graph.analysis.regions:
        if len(writers.intersection(region.node_ids)) > 1:
            yield RunNotRunnable(
                "graph.concurrent_writers",
                f"the steps after {region.split_node_id!r} run two {_WRITER}s at once",
            )
    live = live_slot_bound(graph)
    if live > MAX_LIVE_SLOTS:
        yield RunNotRunnable(
            "graph.too_wide",
            f"up to {live} slots can be live at once; the limit is {MAX_LIVE_SLOTS}",
        )
    work = live_work_bound(graph)
    if work > MAX_LIVE_WORK:
        yield RunNotRunnable(
            "graph.too_wide",
            f"up to {work} slots, decisions and gates can be open at once; "
            f"the limit is {MAX_LIVE_WORK}",
        )
    longest = worst_effect_key_length(graph, run_id)
    if longest > MAX_EFFECT_KEY_CHARS:
        yield RunNotRunnable(
            "graph.ids_too_long",
            f"an effect key can reach {longest} characters; the limit is {MAX_EFFECT_KEY_CHARS}",
        )


def live_slot_bound(graph: CompiledGraph) -> int:
    """The most slots live at once: a parallel region's rosters together, or one node's."""
    return _widest(graph, {node.id: len(node.roster) for node in _steps(graph)})


def live_work_bound(graph: CompiledGraph) -> int:
    """
    The most slots, open decisions and open gates at once: a parallel region's together,
    or one node's.
    """
    weights = {node.id: len(node.roster) for node in _steps(graph)}
    weights.update((node.id, 1) for node in graph.nodes if node.kind in ("decision", "gate"))
    return _widest(graph, weights)


def _widest(graph: CompiledGraph, weights: dict[str, int]) -> int:
    regions = graph.analysis.regions
    in_regions = {node_id for region in regions for node_id in region.node_ids}
    sizes = [sum(weights.get(node_id, 0) for node_id in region.node_ids) for region in regions]
    sizes.extend(size for node_id, size in weights.items() if node_id not in in_regions)
    return max(sizes, default=0)


def worst_effect_key_length(graph: CompiledGraph, run_id: str) -> int:
    """
    The longest key a step's slot effect, a decision's message to the orchestrator or a
    gate's publish or withdraw can have.

    A slot effect's key is ``{run_id}:{seq}:{kind}:{slot}`` and a slot id
    ``{activation}:{index}``; a decision's re-request key ends with its activation and
    a run version; a gate effect's subject is its visit token ``{activation}:{visit}``,
    whose visit number stays below the activation cap. An activation id is
    ``{node}|{items}|{iterations}``, with one ``{back arrow}:{pass}`` per enclosing
    loop. Item paths stay empty until the engine fans items out.
    """
    kind = max(len(name) for name in _SLOT_KINDS)
    longest = 0
    for node in _steps(graph):
        slot = f"{_worst_activation(graph, node.id)}:{max(len(node.roster) - 1, 0)}"
        longest = max(longest, len(f"{run_id}:{'9' * _SEQ_DIGITS}:{'k' * kind}:{slot}"))
    for node in graph.nodes:
        if node.kind == "decision":
            activation = _worst_activation(graph, node.id)
            key = decision_rerequest_key(run_id, activation, int("9" * _SEQ_DIGITS))
            longest = max(longest, len(key))
    for node in _gates(graph):
        token = f"{_worst_activation(graph, node.id)}:{'9' * len(str(MAX_RUN_ACTIVATIONS))}"
        key = effect_key(run_id, int("9" * _SEQ_DIGITS), "withdraw_gate", token)
        longest = max(longest, len(key))
    return longest


def _worst_activation(graph: CompiledGraph, node_id: str) -> str:
    passes = [
        f"{loop.back_arrow_id}:{'9' * _pass_digits(loop.limit)}"
        for loop in graph.analysis.loops
        if node_id in loop.body
    ]
    return f"{node_id}||{'/'.join(passes)}"


def _pass_digits(limit: int | None) -> int:
    # A loop at its limit has used one pass more than the limit.
    return _UNLIMITED_PASS_DIGITS if limit is None else len(str(limit + 1))


__all__ = [
    "RunNotRunnable",
    "check_startable",
    "live_slot_bound",
    "live_work_bound",
    "replay_start",
    "start_engine_run",
    "worst_effect_key_length",
]
