"""Alert names, the stored payload, and who may see an alert or share a limit. Pure: no I/O."""

from __future__ import annotations

from typing import Annotated, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field

# Names of the stored kind codes; question, overdue and reaction have no producer yet.
AlertKindName = Literal[
    "gate",
    "question",
    "pause",
    "watchdog",
    "overdue",
    "reaction",
    "run_completed",
    "run_failed",
    "run_cancelled",
]
# What the Inbox may offer on an alert; never "Extend".
AlertAction = Literal["answer", "open_run", "mark_read", "resume", "cancel"]

# Omnigent's reserved id for the single local user; runs store it or None.
LOCAL_USER_ID = "local"
MAX_ALERT_OUTCOMES = 16
MAX_ALERT_OUTCOME_CHARS = 128
# Free text is cut to these before a payload is built.
MAX_ALERT_MESSAGE_CHARS = 280
MAX_ALERT_RUN_TITLE_CHARS = 256
MAX_ALERT_STEP_LABEL_CHARS = 128


class AlertPayload(BaseModel):
    """What the Inbox shows for an alert, stored as JSON on its row."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    title: str = Field(max_length=120)
    message: str = Field(max_length=MAX_ALERT_MESSAGE_CHARS)
    run_title: str = Field(max_length=MAX_ALERT_RUN_TITLE_CHARS)
    step_label: str | None = Field(default=None, max_length=MAX_ALERT_STEP_LABEL_CHARS)
    node_id: str | None = Field(default=None, max_length=64)
    actions: tuple[AlertAction, ...]
    deep_link: str = Field(max_length=512)
    approve_link: str | None = Field(default=None, max_length=128)
    elicitation_id: str | None = Field(default=None, max_length=64)
    session_id: str | None = Field(default=None, max_length=64)
    outcomes: tuple[Annotated[str, Field(max_length=MAX_ALERT_OUTCOME_CHARS)], ...] = Field(
        default=(), max_length=MAX_ALERT_OUTCOMES
    )
    pause_reason: str | None = Field(default=None, max_length=32)


class GenerationProof(Protocol):
    """The part of a caller that says which account generation its request proved."""

    @property
    def account_generation(self) -> str | None: ...

    @property
    def check_generation(self) -> bool: ...


def normalize_owner(user_id: str | None) -> str | None:
    """The owner stored on an alert: the single local user is ``None`` however a run names it."""
    return None if user_id is None or user_id == LOCAL_USER_ID else user_id


def generation_matches(recorded: str | None, viewer: GenerationProof) -> bool:
    """Whether the caller may see something recorded under ``recorded``.

    Fails closed: a recorded generation matches only a request that proved the same one.
    """
    return recorded is None or (viewer.check_generation and viewer.account_generation == recorded)


class OwnerProof(GenerationProof, Protocol):
    """A caller: who it is and which account generation its request proved."""

    @property
    def user_id(self) -> str | None: ...


def is_owner(
    owner_user_id: str | None, recorded_generation: str | None, viewer: OwnerProof
) -> bool:
    """Whether the caller owns what ``owner_user_id`` recorded, under its generation if any."""
    return normalize_owner(owner_user_id) == normalize_owner(viewer.user_id) and (
        generation_matches(recorded_generation, viewer)
    )


# Whose share of a per-user limit a caller takes: its normalized owner id and generation.
CallerKey = tuple[str | None, str | None]


def caller_key(viewer: OwnerProof) -> CallerKey:
    """The caller's share of a per-user limit: one per user and account generation."""
    return normalize_owner(viewer.user_id), viewer.account_generation


__all__ = [
    "LOCAL_USER_ID",
    "MAX_ALERT_MESSAGE_CHARS",
    "MAX_ALERT_OUTCOMES",
    "MAX_ALERT_OUTCOME_CHARS",
    "MAX_ALERT_RUN_TITLE_CHARS",
    "MAX_ALERT_STEP_LABEL_CHARS",
    "AlertAction",
    "AlertKindName",
    "AlertPayload",
    "CallerKey",
    "GenerationProof",
    "OwnerProof",
    "caller_key",
    "generation_matches",
    "is_owner",
    "normalize_owner",
]
