"""The per-process fold of stored engine rows: incremental, bounded by version, golden log."""

from __future__ import annotations

import dataclasses
import json
import random
import subprocess
import sys
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import timedelta
from pathlib import Path

import pytest

from coral.bridge.codec import EngineLogDecodeError, decode_entries, entry_draft
from coral.bridge.config import FrozenConfigMissing, engine_config_for, freeze_engine_config
from coral.bridge.fold import EngineStateCache
from coral.bridge.graphs import verified_content_hash
from coral.bridge.mapping import UNMAPPED_KINDS, MapContext, map_effect, timer_draft
from coral.db.enum_codecs import ActorKind, LogKind
from coral.engine import empty_state
from coral.engine import fold as replay_log
from coral.engine.types import (
    TERMINAL_STATUSES,
    CancelRun,
    Effect,
    EngineConfig,
    LogEntry,
    RunState,
    StartRun,
)
from coral.model.ids import derived_id
from coral.model.ir import CompiledGraph
from coral.slots.executors import _cancel_payload, _close_payload, _create_payload, _send_payload
from coral.stores.fakes import FakeRunStore
from coral.stores.protocols import (
    CoralRun,
    LogEntryDraft,
    RunLogEntry,
    RunNotFound,
    RunStartSpec,
    Transition,
)
from tests.coral.bridge._scripted_runs import (
    IMPLEMENT,
    RUN_ID,
    START_KEY,
    WORKSPACE,
    accept,
    eventful_two_steps,
    fixture_graph,
    replay,
)
from tests.coral.engine.drive import NOW, drive

GOLDEN = Path(__file__).parent / "fixtures" / "engine_log_v1.json"
GRAPH = fixture_graph("two_steps")
CONFIG = EngineConfig(max_activations=100, rejected_call_limit=3)
# Entries per commit, so versions hold one, several or no engine rows.
_CHUNKS = (1, 2, 1, 3, 0, 2, 1, 4, 0, 1)


@dataclass
class CommittedRun:
    store: FakeRunStore
    # The engine state at every run version.
    states: dict[int, RunState]
    # The effects each version's commit emitted.
    effects: dict[int, tuple[Effect, ...]] = field(default_factory=dict)
    run_id: str = RUN_ID
    workspace_id: int = WORKSPACE

    @property
    def final(self) -> int:
        return max(self.states)


def _spec() -> RunStartSpec:
    return RunStartSpec(
        workflow_id="f" * 32,
        version_id="e" * 32,
        title="Ship",
        request_preview="Ship it",
        workspace_id=WORKSPACE,
        user_id="alice",
        engine_config=freeze_engine_config(max_activations=100, rejected_call_limit=3),
    )


def _committed(
    store: FakeRunStore | None = None,
    *,
    workspace_id: int = WORKSPACE,
    user: str = "alice",
    log: Sequence[LogEntry] | None = None,
) -> CommittedRun:
    """A run (the eventful one by default) committed in uneven chunks, with store-only rows."""
    store = store if store is not None else FakeRunStore(default_workspace_id=WORKSPACE)
    spec = dataclasses.replace(_spec(), workspace_id=workspace_id, user_id=user)
    run = store.start_run(spec, start_key=START_KEY, now=1)
    assert run.id == derived_id("coral-run", user, START_KEY)
    steps = [
        step
        for step in replay(GRAPH, eventful_two_steps(GRAPH).log if log is None else log, CONFIG)
        if step.entry.rejection is not None or step.after != step.before
    ]
    states = {1: empty_state()}
    effects: dict[int, tuple[Effect, ...]] = {1: ()}
    state = empty_state()
    version = 1
    position = 0
    chunk = 0
    while position < len(steps):
        size = _CHUNKS[chunk % len(_CHUNKS)]
        chunk += 1
        batch = steps[position : position + size]
        position += size
        logs = [
            entry_draft(step.entry, run_id=run.id, before=step.before, actor=user)
            for step in batch
        ]
        if not batch:
            logs = [
                LogEntryDraft(
                    kind=int(LogKind.PAUSED), actor_kind=int(ActorKind.ENGINE), body="{}"
                )
            ]
        store.apply_transition(
            run.id, version, Transition(logs=logs), workspace_id=workspace_id, now=2
        )
        version += 1
        if batch:
            state = batch[-1].after
        states[version] = state
        effects[version] = tuple(effect for step in batch for effect in step.entry.effects)
    assert state.status in TERMINAL_STATUSES
    return CommittedRun(
        store=store, states=states, effects=effects, run_id=run.id, workspace_id=workspace_id
    )


@dataclass(frozen=True)
class Read:
    after_seq: int
    max_run_version: int
    rows: int


class CountingReader:
    """The store's engine-log reads, recorded."""

    def __init__(self, store: FakeRunStore) -> None:
        self.store = store
        self.reads: list[Read] = []

    def get_run(self, run_id: str, *, workspace_id: int | None = None) -> CoralRun | None:
        return self.store.get_run(run_id, workspace_id=workspace_id)

    def read_engine_log(
        self,
        run_id: str,
        *,
        workspace_id: int,
        after_seq: int = 0,
        max_run_version: int,
        limit: int = 500,
    ) -> list[RunLogEntry]:
        rows = self.store.read_engine_log(
            run_id,
            workspace_id=workspace_id,
            after_seq=after_seq,
            max_run_version=max_run_version,
            limit=limit,
        )
        self.reads.append(Read(after_seq, max_run_version, len(rows)))
        return rows

    def take(self) -> list[Read]:
        reads, self.reads = self.reads, []
        return reads


def _fold(
    cache: EngineStateCache,
    version: int,
    *,
    graph: CompiledGraph = GRAPH,
    config: EngineConfig = CONFIG,
) -> RunState:
    return cache.fold(
        workspace_id=WORKSPACE, run_id=RUN_ID, version=version, graph=graph, config=config
    ).state


def test_importing_the_bridge_keeps_the_engines_fold_function() -> None:
    # A fresh interpreter: in this process an earlier import may already have bound it.
    script = (
        "import types, coral.bridge, coral.bridge.fold, coral.bridge.mapping\n"
        "from coral.engine import fold\n"
        "assert callable(fold) and not isinstance(fold, types.ModuleType), fold\n"
    )
    subprocess.run([sys.executable, "-c", script], check=True, timeout=60)


def test_a_fresh_fold_matches_the_engine_state_at_every_version() -> None:
    committed = _committed()
    for version, expected in committed.states.items():
        assert _fold(EngineStateCache(committed.store), version) == expected


def test_one_cache_walks_forward_reading_only_rows_it_has_not_folded() -> None:
    committed = _committed()
    reader = CountingReader(committed.store)
    cache = EngineStateCache(reader, page_size=500)
    last_seq = 0
    for version, expected in committed.states.items():
        folded = cache.fold(
            workspace_id=WORKSPACE, run_id=RUN_ID, version=version, graph=GRAPH, config=CONFIG
        )
        assert folded.state == expected
        assert folded.version == version
        reads = reader.take()
        assert reads and reads[0].after_seq == last_seq
        assert all(read.max_run_version == version for read in reads)
        assert folded.last_seq >= last_seq
        last_seq = folded.last_seq
        assert _fold(cache, version) == expected
        assert reader.take() == []


def test_an_older_version_folds_again_without_any_row_past_it() -> None:
    committed = _committed()
    reader = CountingReader(committed.store)
    cache = EngineStateCache(reader)
    assert _fold(cache, committed.final) == committed.states[committed.final]
    reader.take()
    assert _fold(cache, 4) == committed.states[4]
    reads = reader.take()
    assert reads[0].after_seq == 0
    assert all(read.max_run_version == 4 for read in reads)


def test_small_pages_fold_the_same_state() -> None:
    committed = _committed()
    reader = CountingReader(committed.store)
    cache = EngineStateCache(reader, page_size=2)
    assert _fold(cache, committed.final) == committed.states[committed.final]
    reads = reader.take()
    assert len(reads) > 3
    assert all(read.rows <= 2 for read in reads)
    assert reads[-1].rows < 2


def test_another_graph_or_config_and_an_evicted_run_fold_from_the_start() -> None:
    committed = _committed()
    reader = CountingReader(committed.store)
    cache = EngineStateCache(reader, max_runs=1)
    _fold(cache, committed.final)
    reader.take()
    other_config = CONFIG.model_copy(update={"nudge_limit": 5})
    _fold(cache, committed.final, config=other_config)
    assert reader.take()[0].after_seq == 0
    other_graph = GRAPH.model_copy(update={"content_hash": "0" * 64})
    _fold(cache, committed.final, graph=other_graph)
    assert reader.take()[0].after_seq == 0

    _fold(cache, committed.final)
    reader.take()
    other = committed.store.start_run(
        dataclasses.replace(_spec(), user_id="bob"), start_key=START_KEY, now=1
    )
    cache.fold(workspace_id=WORKSPACE, run_id=other.id, version=1, graph=GRAPH, config=CONFIG)
    _fold(cache, committed.final)
    assert reader.take()[0].after_seq == 0
    cache.forget(workspace_id=WORKSPACE, run_id=RUN_ID)
    _fold(cache, committed.final)
    assert reader.take()[0].after_seq == 0


def _cancelled(run_id: str) -> tuple[LogEntry, ...]:
    """Another history from its first entry: the run is cancelled while the review runs."""
    start = StartRun(run_id=run_id, start_key="cancelled", version_hash=GRAPH.content_hash)
    return drive(GRAPH, [start, *accept(IMPLEMENT, "done"), CancelRun()]).log


def test_interleaved_runs_fold_apart_in_any_version_order() -> None:
    first = _committed()
    # The same run id in another workspace and another run here share the store and cache.
    elsewhere = _committed(first.store, workspace_id=WORKSPACE + 1, log=_cancelled(RUN_ID))
    other_id = derived_id("coral-run", "bob", START_KEY)
    other = _committed(first.store, user="bob", log=_cancelled(other_id))
    runs = (first, elsewhere, other)
    assert all(elsewhere.states[version] != first.states[version] for version in range(2, 8))
    # In step with each other first, then in a random order.
    lockstep = [(run, v) for v in range(1, first.final + 1) for run in runs if v in run.states]
    shuffled = list(lockstep)
    random.Random(149).shuffle(shuffled)
    walk = lockstep + shuffled
    cache = EngineStateCache(first.store, max_runs=len(runs))
    for run, version in walk:
        for reader in (cache, EngineStateCache(first.store)):
            folded = reader.fold(
                workspace_id=run.workspace_id,
                run_id=run.run_id,
                version=version,
                graph=GRAPH,
                config=CONFIG,
            )
            assert folded.state == run.states[version], (run.run_id, run.workspace_id, version)


_PARSERS = {
    "create_session": lambda payload: _create_payload({**payload, "agent_id": "coral__step"}),
    "send_input": _send_payload,
    "close_slot": _close_payload,
    "cancel_sessions": _cancel_payload,
}


def _rows_for(state: RunState, effects: Sequence[Effect]) -> tuple[object, ...]:
    ctx = MapContext(
        workspace_id=WORKSPACE,
        run_id=RUN_ID,
        graph=GRAPH,
        state=state,
        request_preview="Ship it",
        title="Ship",
        now=NOW + timedelta(hours=1),
    )
    mapped = tuple(map_effect(ctx, effect) for effect in effects)
    return mapped, tuple(timer_draft(RUN_ID, timer) for timer in state.timers)


@pytest.mark.parametrize("history", ["eventful", "cancelled"])
def test_every_effect_maps_to_the_same_row_from_the_live_state_and_every_fold(
    history: str,
) -> None:
    committed = _committed(log=None if history == "eventful" else _cancelled(RUN_ID))
    walked = EngineStateCache(committed.store)
    mapped_kinds: set[str] = set()
    for version, expected in committed.states.items():
        rows = committed.store.read_engine_log(
            RUN_ID, workspace_id=WORKSPACE, max_run_version=version, limit=1_000
        )
        # Bodies as another JSON encoder would have written them.
        reencoded = [
            dataclasses.replace(row, body=json.dumps(json.loads(row.body))) for row in rows
        ]
        folds = (
            replay_log(GRAPH, decode_entries(reencoded), CONFIG),
            _fold(walked, version),
            _fold(EngineStateCache(committed.store), version),
        )
        effects = committed.effects[version]
        live = _rows_for(expected, effects)
        for state in folds:
            assert state == expected
            assert _rows_for(state, effects) == live
        for effect, draft in zip(effects, live[0], strict=True):
            if draft is None:
                assert effect.kind in UNMAPPED_KINDS
                continue
            assert draft.id == derived_id("coral-work", RUN_ID, "effect", effect.effect_key)
            payload = json.loads(draft.payload)
            assert payload["effect_key"] == effect.effect_key
            _PARSERS[payload["effect_type"]](payload)
            mapped_kinds.add(effect.kind)
    expected_kinds = {"create_session", "send_input", "close_slot"}
    expected_kinds |= {"nudge"} if history == "eventful" else {"cancel_sessions"}
    assert expected_kinds <= mapped_kinds


def test_a_version_the_run_has_not_committed_is_refused_and_not_cached() -> None:
    committed = _committed()
    store = committed.store
    run = store.get_run(RUN_ID, workspace_id=WORKSPACE)
    assert run is not None
    cache = EngineStateCache(store)
    # A version the run reaches later: folding it now would miss its rows.
    store.runs[(WORKSPACE, RUN_ID)] = dataclasses.replace(run, version=4)
    with pytest.raises(ValueError, match="not committed"):
        _fold(cache, 6)
    store.runs[(WORKSPACE, RUN_ID)] = run
    assert _fold(cache, 6) == committed.states[6]
    with pytest.raises(RunNotFound):
        cache.fold(workspace_id=WORKSPACE, run_id="0" * 32, version=1, graph=GRAPH, config=CONFIG)


def test_a_corrupt_row_fails_the_fold() -> None:
    committed = _committed()
    rows = committed.store.logs[(WORKSPACE, RUN_ID)]
    index = next(
        i for i, row in enumerate(rows) if row.kind == int(LogKind.ENGINE) and not row.audit_only
    )
    rows[index] = dataclasses.replace(rows[index], body="not json")
    with pytest.raises(EngineLogDecodeError):
        _fold(EngineStateCache(committed.store), committed.final)


def test_the_golden_log_folds_to_its_recorded_state() -> None:
    golden = json.loads(GOLDEN.read_text())
    graph = CompiledGraph.model_validate_json(golden["pinned_graph"]["compiled_json"])
    assert verified_content_hash(graph) == golden["pinned_graph"]["content_hash"]
    spec = dataclasses.replace(_spec(), engine_config=golden["engine_config"])
    config = engine_config_for(spec)
    rows = [RunLogEntry(**row) for row in golden["log"]]
    assert any(row.audit_only for row in rows)
    recorded = RunState.model_validate(golden["state"])
    assert recorded.status == "completed"

    store = FakeRunStore(default_workspace_id=golden["workspace_id"])
    run = store.start_run(_spec(), start_key=START_KEY, now=1)
    assert run.id == golden["run_id"]
    store.runs[(run.workspace_id, run.id)] = dataclasses.replace(run, version=golden["version"])
    store.logs[(run.workspace_id, run.id)] = rows
    folded = EngineStateCache(store).fold(
        workspace_id=golden["workspace_id"],
        run_id=golden["run_id"],
        version=golden["version"],
        graph=graph,
        config=config,
    )
    assert folded.state == recorded
    assert folded.last_seq == max(row.seq for row in rows)


@pytest.mark.parametrize("frozen", [None, "", '{"max_activations": "many"}'])
def test_a_run_without_a_readable_frozen_config_cannot_be_replayed(frozen: str | None) -> None:
    with pytest.raises(FrozenConfigMissing):
        engine_config_for(dataclasses.replace(_spec(), engine_config=frozen))


def test_the_frozen_config_keeps_the_run_limits_and_every_default() -> None:
    config = engine_config_for(_spec())
    assert config == EngineConfig(max_activations=100, rejected_call_limit=3)
    assert (
        engine_config_for(dataclasses.replace(_spec(), engine_config=config.model_dump_json()))
        == config
    )
