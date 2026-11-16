"""Coral's packaged agent seeds, each pinned by its sha256 in ``seeds.lock``."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from importlib import resources

import yaml
from pydantic import BaseModel, ConfigDict

SEED_NAMES = ("anchor", "orchestrator", "implementer", "reviewer")


class SeedLockMismatch(RuntimeError):
    """A seed file's bytes differ from the digest ``seeds.lock`` pins for it."""


class SeedSpec(BaseModel):
    """One seed: its name, the sha256 of its YAML bytes, and the parsed mapping."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str
    sha256: str
    config: Mapping[str, object]


def seed_lock() -> dict[str, str]:
    """Return ``seeds.lock``: seed name to the sha256 hex of its YAML file."""
    return json.loads(resources.files(__name__).joinpath("seeds.lock").read_text("utf-8"))


def load_seed(name: str) -> SeedSpec:
    """
    Read the packaged seed *name* and check it against ``seeds.lock``.

    :param name: One of :data:`SEED_NAMES`, e.g. ``"reviewer"``.
    :returns: The seed with its parsed YAML mapping.
    :raises KeyError: If *name* is not a packaged seed.
    :raises SeedLockMismatch: If the file was edited without updating the lock.
    :raises pydantic.ValidationError: If the file is not a YAML mapping.
    """
    if name not in SEED_NAMES:
        raise KeyError(f"unknown Coral seed {name!r}; expected one of {SEED_NAMES}")
    raw = resources.files(__name__).joinpath(f"{name}.yaml").read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    pinned = seed_lock().get(name)
    if digest != pinned:
        raise SeedLockMismatch(
            f"seed {name!r} has sha256 {digest} but seeds.lock pins {pinned}; "
            "update seeds.lock in the same change as the seed"
        )
    config = yaml.safe_load(raw)
    return SeedSpec(name=name, sha256=digest, config=config)
