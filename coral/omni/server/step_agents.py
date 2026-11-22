"""A step's stance as the run owner's Coral bundle agent (``StepAgentResolver``).

The bridge maps a step's create with its stance and step reference, never an
agent id. The ``create_session`` executor asks this resolver, inside the run's
scopes, for the agent: the generated bundle of that stance and step (the
orchestrator's seed bundle for the orchestrator), stored as the owner's agent.
The bundle is deterministic, so a repeat finds the same row; a bounded cache
skips rebuilding it while its row and blob are still stored. A create retried
after its session was written keeps that session's agent, so an upgrade that
changes a bundle cannot strand it.
"""

from __future__ import annotations

import asyncio
import functools
import hashlib
import sys
import threading
from collections import OrderedDict
from collections.abc import Sequence
from pathlib import Path

import yaml
from pydantic import ValidationError

import coral
import omnigent
from coral.omni.protocols import CoralSessionError
from coral.omni.server.access import omnigent_owner, ownerless_runs_allowed
from coral.omni.server.bundles import MaterializedAgent, StepBundleRejected, materialize
from coral.profiles.bundle_spec import (
    ENGINE_PREFIX,
    ProfileOverlay,
    Stance,
    StepRef,
    build_seed_bundle_yaml,
    build_step_bundle_yaml,
    step_agent_name,
)
from coral.profiles.refs import parse_roster_entry
from coral.stores.profiles import SqlProfileStore
from coral.tools.catalog import ORCHESTRATOR_STANCE, STEP_STANCES
from omnigent.db.db_models import workspace_scope
from omnigent.stores.agent_store import AgentStore
from omnigent.stores.artifact_store import ArtifactStore
from omnigent.stores.conversation_store import ConversationStore

# Materialized agents kept per (workspace, owner, bundle digest).
STEP_AGENT_CACHE_ENTRIES = 256


def _not_supported(stance: str, reason: str) -> CoralSessionError:
    return CoralSessionError(
        "session.agent_not_supported", f"no {stance[:64]!r} step agent: {reason}"
    )


def _bundle(
    stance: str,
    workflow_slug: str | None,
    node_id: str | None,
    roster_index: int | None,
    profile: ProfileOverlay | None = None,
) -> tuple[bytes, Stance, str]:
    """The bundle's ``config.yaml``, stance and agent name; a step's comes from its reference."""
    if stance == ORCHESTRATOR_STANCE:
        orchestrator = Stance.ORCHESTRATOR
        name = f"{ENGINE_PREFIX}{orchestrator.value}"
        return build_seed_bundle_yaml(orchestrator), orchestrator, name
    if stance not in STEP_STANCES:
        raise _not_supported(stance, "the stance has no step bundle")
    try:
        ref = StepRef.model_validate(
            {"workflow_id": workflow_slug, "node_id": node_id, "roster_index": roster_index}
        )
    except ValidationError as exc:
        # Which fields failed, never their values.
        fields = sorted({".".join(map(str, error["loc"])) for error in exc.errors()})
        raise _not_supported(
            stance, f"the step reference is invalid ({', '.join(fields)})"
        ) from None
    step_stance = Stance(stance)
    config_yaml = build_step_bundle_yaml(
        ref, step_stance, model=None, provider=None, profile=profile
    )
    return _with_read_paths(config_yaml, _checkout_read_paths()), step_stance, step_agent_name(ref)


def checkout_read_paths(packages: Sequence[Path], prefix: Path) -> tuple[str, ...]:
    """
    The package directories a step's OS sandbox must read: those outside ``prefix``.

    An editable checkout imports ``omnigent`` and ``coral`` from the repository, which
    the sandbox otherwise hides from its own helpers. Only the package directories are
    granted, never the repository root, which may hold ``.env`` files.
    """
    root = prefix.resolve()
    outside = {package.resolve() for package in packages}
    return tuple(sorted(str(path) for path in outside if not path.is_relative_to(root)))


@functools.cache
def _checkout_read_paths() -> tuple[str, ...]:
    packages = (Path(omnigent.__file__).parent, Path(coral.__file__).parent)
    return checkout_read_paths(packages, Path(sys.prefix))


def _with_read_paths(config_yaml: bytes, read_paths: tuple[str, ...]) -> bytes:
    """The bundle with ``read_paths`` granted to its OS sandbox; unchanged without any."""
    if not read_paths:
        return config_yaml
    config = yaml.safe_load(config_yaml)
    sandbox = config["os_env"]["sandbox"]
    sandbox["read_paths"] = sorted({*sandbox.get("read_paths", ()), *read_paths})
    return yaml.safe_dump(config, sort_keys=True, allow_unicode=True).encode("utf-8")


class OmnigentStepAgents:
    """
    Materializes a step's stance as the run owner's agent, in a thread, cached per bundle.

    :param conversation_store: Reads a retried create's session, whose agent it keeps.
    """

    def __init__(
        self,
        agent_store: AgentStore,
        artifact_store: ArtifactStore,
        *,
        conversation_store: ConversationStore | None = None,
        profiles: SqlProfileStore | None = None,
        max_entries: int = STEP_AGENT_CACHE_ENTRIES,
    ) -> None:
        self._agents = agent_store
        self._profiles = profiles
        self._artifacts = artifact_store
        self._conversations = conversation_store
        self._max_entries = max_entries
        self._cache: OrderedDict[tuple[int, str | None, str], MaterializedAgent] = OrderedDict()
        self._lock = threading.Lock()

    async def resolve(
        self,
        *,
        workspace_id: int,
        owner: str | None,
        stance: str,
        workflow_slug: str | None,
        node_id: str | None,
        roster_index: int | None,
        session_id: str | None = None,
        run_id: str | None = None,
        profile: str | None = None,
    ) -> str:
        """
        The agent id of the stance's bundle, stored as ``owner``'s agent in ``workspace_id``.

        :param session_id: The session the create makes. When an earlier try wrote it
            and it runs the owner's agent of this bundle's name, that agent is kept.
        :param run_id: The step's run, whose pin names ``profile``'s revision.
        :param profile: A profile ref (``reviewer/strict``): the bundle carries the
            revision ``run_id`` pinned at its start, never the latest one.
        :raises CoralSessionError: Permanent ``session.invalid`` for an ownerless run
            outside a single-user server; permanent ``session.agent_not_supported`` when the
            stance or step cannot name a bundle, a profile has no pinned revision, or the
            bundle breaks a step rule.
        """
        if owner is None and not ownerless_runs_allowed():
            raise CoralSessionError(
                "session.invalid", "the run has no owner, and this server requires one"
            )
        return await asyncio.to_thread(
            self._resolve,
            workspace_id,
            omnigent_owner(owner),
            stance,
            (workflow_slug, node_id, roster_index),
            session_id,
            (run_id, profile),
        )

    def _resolve(
        self,
        workspace_id: int,
        owner: str | None,
        stance: str,
        step: tuple[str | None, str | None, int | None],
        session_id: str | None,
        pinned: tuple[str | None, str | None],
    ) -> str:
        overlay = self._pinned_overlay(workspace_id, stance, *pinned)
        config_yaml, bundle_stance, name = _bundle(stance, *step, overlay)
        # Agent rows belong to a workspace: use the run's, whatever the caller's scope.
        with workspace_scope(workspace_id):
            if session_id is not None:
                kept = self._session_agent(session_id, owner, name)
                if kept is not None:
                    return kept
            key = (workspace_id, owner, hashlib.sha256(config_yaml).hexdigest())
            with self._lock:
                cached = self._cache.get(key)
            if cached is not None:
                if self._still_stored(cached, owner):
                    with self._lock:
                        if key in self._cache:
                            self._cache.move_to_end(key)
                    return cached.agent_id
                # Deleted or changed since: the bundle is materialized again.
                with self._lock:
                    self._cache.pop(key, None)
            try:
                agent = materialize(
                    self._agents,
                    self._artifacts,
                    owner=owner,
                    config_yaml=config_yaml,
                    stance=bundle_stance,
                )
            except StepBundleRejected as exc:
                raise _not_supported(stance, str(exc)) from exc
        with self._lock:
            self._cache[key] = agent
            while len(self._cache) > self._max_entries:
                self._cache.popitem(last=False)
        return agent.agent_id

    def _pinned_overlay(
        self, workspace_id: int, stance: str, run_id: str | None, profile: str | None
    ) -> ProfileOverlay | None:
        """The revision of ``profile`` that ``run_id`` pinned; ``None`` for a bare stance."""
        if profile is None:
            return None
        parsed = parse_roster_entry(profile)
        if parsed is None or parsed[1] is None:
            return None
        missing = CoralSessionError(
            "session.agent_not_supported",
            f"Profile missing: {profile} has no revision pinned for this run",
        )
        if self._profiles is None or run_id is None or parsed[0] != stance:
            raise missing
        revision_id = self._profiles.run_pin(
            workspace_id=workspace_id, run_id=run_id, profile_ref=profile
        )
        revision = (
            None
            if revision_id is None
            else self._profiles.get_revision(workspace_id=workspace_id, revision_id=revision_id)
        )
        if revision is None:
            raise missing
        return ProfileOverlay(
            revision.profile_ref, revision.id, revision.revision_no, revision.spec
        )

    def _session_agent(self, session_id: str, owner: str | None, name: str) -> str | None:
        """The agent an earlier try's session runs, when it is the owner's agent of ``name``."""
        if self._conversations is None:
            return None
        conv = self._conversations.get_conversation(session_id)
        if conv is None or not conv.agent_id:
            return None
        agent = self._agents.get(conv.agent_id)
        if agent is None or agent.kind != "user" or agent.created_by != owner:
            return None
        return agent.id if agent.name == name else None

    def _still_stored(self, cached: MaterializedAgent, owner: str | None) -> bool:
        """Whether the cached agent's row and blob are still as materialized (one read each)."""
        agent = self._agents.get(cached.agent_id)
        if (
            agent is None
            or agent.kind != "user"
            or agent.created_by != owner
            or agent.bundle_location != cached.bundle_location
        ):
            return False
        try:
            return self._artifacts.exists(cached.bundle_location)
        except Exception:  # noqa: BLE001 -- an unconfirmed blob is materialized again
            return False


__all__ = ["STEP_AGENT_CACHE_ENTRIES", "OmnigentStepAgents"]
