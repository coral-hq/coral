"""Tests for Coral's logo asset generator, ``.coral/tools/brand_assets.py``."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / ".coral" / "tools" / "brand_assets.py"


def _load_brand_assets() -> ModuleType:
    spec = importlib.util.spec_from_file_location("coral_brand_assets", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


brand_assets = _load_brand_assets()


@pytest.fixture(autouse=True)
def _repository_root(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(ROOT)


def test_every_generated_asset_is_committed_at_its_size() -> None:
    assert brand_assets.check() == 0


def test_desktop_icon_is_the_mark_on_a_cream_plate_with_a_clear_margin() -> None:
    icon = brand_assets.plate_icon(brand_assets.load_mark(), canvas=256, plate=206)
    assert icon.getpixel((0, 0))[3] == 0  # transparent margin for the macOS squircle
    assert icon.getpixel((40, 128))[:3] == brand_assets.CREAM  # plate beside the mark
    assert icon.getpixel((128, 128))[3] == 255


def test_silhouettes_are_one_colour_masks() -> None:
    mask = brand_assets.silhouette(brand_assets.load_mark(), 96, 88, (255, 255, 255))
    for channel in "RGB":
        assert mask.getchannel(channel).getextrema() == (255, 255)
    assert mask.getpixel((0, 0))[3] == 0


def test_mark_crop_is_square_and_keeps_the_artwork() -> None:
    mark = brand_assets.load_mark()
    assert mark.width == mark.height
    assert mark.getchannel("A").getbbox() is not None
