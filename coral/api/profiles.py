"""
Profiles and rule-template router. Unmounted: the Coral server plugin registers it.

Every route needs a signed-in caller, who lists, reads and saves their own profiles in
the request's workspace, plus the built-in stances as read-only seeded rows. A profile's
content never changes: an edit saves a new revision from the one it started from.
"""

from __future__ import annotations

import functools
from collections import Counter
from collections.abc import Awaitable, Callable, Mapping
from typing import Any, Literal

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from coral.alerts.types import normalize_owner
from coral.api.errors import CoralApiError, CoralRoute, error_responses
from coral.omni.protocols import Viewer
from coral.profiles.capabilities import CapabilityState, harness_capabilities
from coral.profiles.refs import parse_roster_entry
from coral.profiles.seeds import load_seed
from coral.profiles.spec import ProfileSpec, RuleInstance, RuleStrength
from coral.rules.catalog import CATALOG
from coral.stores.profiles import (
    ProfileExists,
    ProfileKeyTaken,
    ProfileRevision,
    ProfileTooLarge,
    SqlProfileStore,
    StaleRevision,
)
from coral.stores.workflows import WorkflowDefinitionStore
from coral.tools.catalog import STEP_STANCES

PROFILE_NOT_FOUND = "Profile not found."
# Params that make a template's statement readable before a user fills them in.
_EXAMPLE_PARAMS: Mapping[str, Mapping[str, Any]] = {
    "protect_paths": {"paths": ["infra", "secrets"]}
}

# A request's spec is validated by the route, not the request model, so a refusal can
# name ``rules[i].params.<field>``.
_SPEC_IN = "A ProfileSpec."


class _Out(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class RuleOut(_Out):
    template: str
    strength: RuleStrength
    statement: str


class UsedByOut(_Out):
    workflows: int
    running_runs: int


class CapabilitiesOut(_Out):
    steering: CapabilityState
    tool_gating: CapabilityState
    fs_read_only: CapabilityState
    usage_reporting: CapabilityState


class ProfileRowOut(_Out):
    """One profile as the desk lists it; a seeded row is a built-in stance, read-only."""

    profile_ref: str
    stance: str
    name: str
    description: str
    harness: str
    model: str | None
    # ``None`` for a seeded row, which has no revisions.
    revision_no: int | None
    source: Literal["seeded", "user"]
    rules: list[RuleOut]
    capabilities: CapabilitiesOut
    used_by: UsedByOut


class RevisionOut(_Out):
    id: str
    revision_no: int
    created_at: int
    running_runs: int


class ProfileDetailOut(ProfileRowOut):
    """A user profile with its latest spec and every revision, newest first."""

    spec: ProfileSpec
    revisions: list[RevisionOut]
    # Whether this request saved a new revision; a save of unchanged content does not.
    created: bool = False


class ProfileCreateIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ref: str = Field(description="``<stance>/<slug>``, e.g. ``reviewer/strict-review``.")
    spec: dict[str, Any] = Field(description=_SPEC_IN)


class RevisionIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    base_revision_no: int = Field(ge=1, description="The revision the edit started from.")
    spec: dict[str, Any] = Field(description=_SPEC_IN)


class RuleTemplateOut(_Out):
    id: str
    version: int
    title: str
    params_schema: dict[str, Any]
    statement_example: str
    bypasses: list[str]


def _field(loc: tuple[str | int, ...]) -> str:
    path = ""
    for part in loc:
        path += f"[{part}]" if isinstance(part, int) else f".{part}" if path else part
    return path


def parse_spec(raw: dict[str, Any]) -> ProfileSpec:
    """
    Validate a request's spec.

    :raises CoralApiError: 422 listing each problem's ``field``, such as
        ``rules[0].params.paths[0]``, and ``message``.
    """
    try:
        return ProfileSpec.model_validate(raw)
    except ValidationError as exc:
        errors: list[dict[str, str]] = []
        for error in exc.errors():
            loc = tuple(error["loc"])
            inner = (error.get("ctx") or {}).get("fields")
            if error["type"] == "rule_invalid" and inner:
                errors += [{"field": _field((*loc, *sub)), "message": msg} for sub, msg in inner]
            else:
                errors.append({"field": _field(loc), "message": error["msg"]})
        raise CoralApiError(
            "validation_failed", "The profile is invalid.", 422, details={"errors": errors}
        ) from None


def _rule_out(rule: RuleInstance) -> RuleOut:
    template = CATALOG[rule.template]
    params = template.params_model.model_validate(rule.params)
    return RuleOut(
        template=rule.template, strength=rule.strength, statement=template.statement(params)
    )


@functools.cache
def _seed(stance: str) -> tuple[str, str, str | None]:
    """A stance seed's description, harness and model."""
    config = load_seed(stance).config
    executor = config.get("executor") or {}
    assert isinstance(executor, dict)
    harness = str((executor.get("config") or {}).get("harness", "unknown"))
    model = executor.get("model")
    return str(config.get("description", "")), harness, None if model is None else str(model)


def _capabilities(harness: str) -> CapabilitiesOut:
    return CapabilitiesOut(**harness_capabilities(harness))


def _profile_store(request: Request) -> SqlProfileStore:
    store = getattr(request.app.state, "coral_profile_store", None)
    if store is None:
        raise CoralApiError("not_found", PROFILE_NOT_FOUND, 404)
    return store


def create_profiles_router(
    definitions: WorkflowDefinitionStore,
    *,
    viewer_dependency: Callable[..., Viewer] | Callable[..., Awaitable[Viewer]],
    workspace_id_dependency: Callable[..., int],
) -> APIRouter:
    """
    The profiles and rule-template routes, mounted by the caller under ``/v1/coral``.

    Profiles live in the store the lifespan publishes as ``app.state.coral_profile_store``,
    the one runs pin from; without one every route but the rule templates answers 404.

    :param definitions: The caller's workflows, read to count which use a profile.
    :param viewer_dependency: Resolves the caller, refusing with 401 or 403.
    :param workspace_id_dependency: The request's workspace.
    """
    router = APIRouter(route_class=CoralRoute)
    caller = Depends(viewer_dependency)
    workspace = Depends(workspace_id_dependency)
    store = Depends(_profile_store)

    def roster_counts(workspace_id: int, owner: str | None) -> Counter[str]:
        """How many of the caller's workflows name each roster entry."""
        counts: Counter[str] = Counter()
        for definition in definitions.list_definitions(workspace_id=workspace_id, owner=owner):
            counts.update(
                {
                    entry
                    for node in definition.compiled.nodes
                    if node.kind == "step"
                    for entry in node.roster
                }
            )
        return counts

    def row(
        revision: ProfileRevision, workflows: int, running: Mapping[str, int]
    ) -> dict[str, Any]:
        stance = revision.profile_ref.partition("/")[0]
        seed_description, harness, seed_model = _seed(stance)
        spec = revision.spec
        return {
            "profile_ref": revision.profile_ref,
            "stance": stance,
            "name": spec.name,
            "description": spec.description or seed_description,
            "harness": harness,
            "model": spec.model or seed_model,
            "revision_no": revision.revision_no,
            "source": "user",
            "rules": [_rule_out(rule) for rule in spec.rules],
            "capabilities": _capabilities(harness),
            "used_by": UsedByOut(workflows=workflows, running_runs=sum(running.values())),
        }

    def detail(
        profiles: SqlProfileStore,
        workspace_id: int,
        owner: str | None,
        profile_ref: str,
        *,
        created: bool = False,
    ) -> ProfileDetailOut:
        revisions = profiles.revisions(
            workspace_id=workspace_id, profile_ref=profile_ref, owner=owner
        )
        if not revisions:
            raise CoralApiError("not_found", PROFILE_NOT_FOUND, 404)
        # Checked visible above: used_by does not filter by owner.
        running = profiles.used_by(workspace_id=workspace_id, profile_ref=profile_ref)
        workflows = roster_counts(workspace_id, owner)[profile_ref]
        return ProfileDetailOut(
            **row(revisions[0], workflows, running),
            spec=revisions[0].spec,
            revisions=[
                RevisionOut(
                    id=revision.id,
                    revision_no=revision.revision_no,
                    created_at=revision.created_at,
                    running_runs=running.get(revision.id, 0),
                )
                for revision in revisions
            ],
            created=created,
        )

    def path_ref(stance: str, slug: str) -> str:
        ref = f"{stance}/{slug}"
        parsed = parse_roster_entry(ref)
        if parsed is None or parsed[1] is None:
            raise CoralApiError("not_found", PROFILE_NOT_FOUND, 404)
        return ref

    def save(
        profiles: SqlProfileStore,
        workspace_id: int,
        owner: str | None,
        ref: str,
        spec: ProfileSpec,
        base: int | None,
    ) -> ProfileDetailOut:
        try:
            _revision, created = profiles.save_revision(
                workspace_id=workspace_id,
                profile_ref=ref,
                owner=owner,
                spec=spec,
                base_revision_no=base,
            )
        except ProfileKeyTaken as error:
            raise CoralApiError(
                "profile_key_taken", "Another user's profile has this name.", 409
            ) from error
        except ProfileExists as error:
            raise CoralApiError("profile_exists", "This profile already exists.", 409) from error
        except StaleRevision as error:
            raise CoralApiError(
                "stale_revision", "The profile changed since you opened it. Reload it.", 412
            ) from error
        except ProfileTooLarge as error:
            raise CoralApiError(
                "validation_failed",
                "The profile is invalid.",
                422,
                details={"errors": [{"field": "spec", "message": str(error)}]},
            ) from error
        return detail(profiles, workspace_id, owner, ref, created=created)

    @router.get(
        "/profiles",
        operation_id="coral_list_profiles",
        response_model=list[ProfileRowOut],
        responses=error_responses(401, 403),
    )
    def list_profiles(
        viewer: Viewer = caller,
        workspace_id: int = workspace,
        profiles: SqlProfileStore = store,
    ) -> list[ProfileRowOut]:
        """The built-in stances, then the caller's profiles by ref."""
        owner = normalize_owner(viewer.user_id)
        counts = roster_counts(workspace_id, owner)
        rows: list[ProfileRowOut] = []
        for stance in sorted(STEP_STANCES):
            description, harness, model = _seed(stance)
            rows.append(
                ProfileRowOut(
                    profile_ref=stance,
                    stance=stance,
                    name=stance.capitalize(),
                    description=description,
                    harness=harness,
                    model=model,
                    revision_no=None,
                    source="seeded",
                    rules=[],
                    capabilities=_capabilities(harness),
                    # Runs on a bare stance pin nothing, so they are not counted.
                    used_by=UsedByOut(workflows=counts[stance], running_runs=0),
                )
            )
        for revision in profiles.list_latest(workspace_id=workspace_id, owner=owner):
            running = profiles.used_by(workspace_id=workspace_id, profile_ref=revision.profile_ref)
            rows.append(ProfileRowOut(**row(revision, counts[revision.profile_ref], running)))
        return rows

    @router.get(
        "/profiles/{stance}/{slug}",
        operation_id="coral_get_profile",
        response_model=ProfileDetailOut,
        responses=error_responses(401, 403, 404, 422),
    )
    def get_profile(
        stance: str,
        slug: str,
        viewer: Viewer = caller,
        workspace_id: int = workspace,
        profiles: SqlProfileStore = store,
    ) -> ProfileDetailOut:
        """One of the caller's profiles with its spec and revisions."""
        return detail(
            profiles, workspace_id, normalize_owner(viewer.user_id), path_ref(stance, slug)
        )

    @router.post(
        "/profiles",
        operation_id="coral_create_profile",
        response_model=ProfileDetailOut,
        status_code=201,
        responses=error_responses(401, 403, 409, 422),
    )
    def create_profile(
        body: ProfileCreateIn,
        viewer: Viewer = caller,
        workspace_id: int = workspace,
        profiles: SqlProfileStore = store,
    ) -> ProfileDetailOut:
        """Create a profile at revision 1."""
        parsed = parse_roster_entry(body.ref)
        if parsed is None or parsed[1] is None:
            raise CoralApiError(
                "validation_failed",
                "The profile is invalid.",
                422,
                details={
                    "errors": [
                        {
                            "field": "ref",
                            "message": "use <stance>/<slug> with stance implementer or "
                            "reviewer and a slug of a-z, 0-9, '_' and '-'",
                        }
                    ]
                },
            )
        spec = parse_spec(body.spec)
        return save(profiles, workspace_id, normalize_owner(viewer.user_id), body.ref, spec, None)

    @router.post(
        "/profiles/{stance}/{slug}/revisions",
        operation_id="coral_save_profile_revision",
        response_model=ProfileDetailOut,
        responses=error_responses(401, 403, 404, 409, 412, 422),
    )
    def save_profile_revision(
        stance: str,
        slug: str,
        body: RevisionIn,
        viewer: Viewer = caller,
        workspace_id: int = workspace,
        profiles: SqlProfileStore = store,
    ) -> ProfileDetailOut:
        """Save an edit as the next revision; unchanged content keeps the latest one."""
        owner = normalize_owner(viewer.user_id)
        ref = path_ref(stance, slug)
        if profiles.latest(workspace_id=workspace_id, profile_ref=ref, owner=owner) is None:
            raise CoralApiError("not_found", PROFILE_NOT_FOUND, 404)
        spec = parse_spec(body.spec)
        return save(profiles, workspace_id, owner, ref, spec, body.base_revision_no)

    @router.get(
        "/rule-templates",
        operation_id="coral_list_rule_templates",
        response_model=list[RuleTemplateOut],
        responses=error_responses(401, 403),
        dependencies=[caller],
    )
    def list_rule_templates() -> list[RuleTemplateOut]:
        """Every rule template a profile can use, with its params schema and bypasses."""
        return [
            RuleTemplateOut(
                id=template.id,
                version=template.version,
                title=template.title,
                params_schema=template.params_model.model_json_schema(),
                statement_example=template.statement(
                    template.params_model.model_validate(_EXAMPLE_PARAMS.get(template.id, {}))
                ),
                bypasses=list(template.bypasses),
            )
            for template in CATALOG.values()
        ]

    return router
