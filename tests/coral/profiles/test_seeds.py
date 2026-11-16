"""The packaged seeds are pinned by ``seeds.lock``."""

from __future__ import annotations

import hashlib
import shutil
from importlib import resources
from pathlib import Path

import pytest

from coral.profiles import seeds
from coral.profiles.seeds import SEED_NAMES, SeedLockMismatch, load_seed, seed_lock


def test_lock_pins_every_shipped_seed() -> None:
    shipped = {
        entry.name.removesuffix(".yaml"): hashlib.sha256(entry.read_bytes()).hexdigest()
        for entry in resources.files(seeds).iterdir()
        if entry.name.endswith(".yaml")
    }

    assert shipped == seed_lock()
    assert set(shipped) == set(SEED_NAMES)
    for name in SEED_NAMES:
        assert load_seed(name).sha256 == shipped[name]


def test_an_edited_seed_without_a_lock_update_is_refused(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    for name in (*(f"{n}.yaml" for n in SEED_NAMES), "seeds.lock"):
        shutil.copy(resources.files(seeds).joinpath(name), tmp_path / name)
    reviewer = tmp_path / "reviewer.yaml"
    reviewer.write_text(reviewer.read_text().replace("write_paths: []", "write_paths: [.]"))
    monkeypatch.setattr(seeds.resources, "files", lambda _package: tmp_path)

    with pytest.raises(SeedLockMismatch, match="reviewer"):
        load_seed("reviewer")
    assert load_seed("implementer").name == "implementer"


def test_an_unknown_seed_is_refused() -> None:
    with pytest.raises(KeyError, match="nope"):
        load_seed("nope")
