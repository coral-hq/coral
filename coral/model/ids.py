"""Slug validation and deterministic derived ids (pure tier: no omnigent imports)."""

import hashlib
import re

MAX_SLUG_LENGTH = 64
SLUG_PATTERN = re.compile(r"[a-z0-9][a-z0-9_.-]*")

# Workflow ids that collide with API path segments.
RESERVED_WORKFLOW_IDS: frozenset[str] = frozenset({"runs", "templates", "new"})


def is_valid_slug(value: str) -> bool:
    """Return whether ``value`` matches ``[a-z0-9][a-z0-9_.-]*`` and is at most 64 chars."""
    return len(value) <= MAX_SLUG_LENGTH and SLUG_PATTERN.fullmatch(value) is not None


def validate_slug(value: str) -> str:
    """
    Return ``value`` unchanged if it is a valid slug.

    :raises ValueError: when the slug is malformed or too long.
    """
    if not is_valid_slug(value):
        raise ValueError(
            f"{value!r} is not a valid id: use lowercase letters, digits, '_', '.' or '-', "
            f"start with a letter or digit, and stay within {MAX_SLUG_LENGTH} characters"
        )
    return value


def validate_workflow_id(value: str) -> str:
    """
    Validate a workflow library key: a slug that is not a reserved path segment.

    :raises ValueError: when the id is malformed or reserved.
    """
    validate_slug(value)
    if value in RESERVED_WORKFLOW_IDS:
        raise ValueError(f"{value!r} is a reserved workflow id")
    return value


def derived_id(kind: str, *parts: str) -> str:
    """
    Deterministic 32-hex id for ``kind`` over ``parts``.

    Mirrors Omnigent's ``installed_agent_id``: sha256 of ``"<kind>:"`` plus the
    NUL-joined parts, truncated to 32 hex characters.
    """
    payload = f"{kind}:".encode() + b"\0".join(part.encode() for part in parts)
    return hashlib.sha256(payload).hexdigest()[:32]
