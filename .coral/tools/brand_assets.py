"""Generate Coral's logo assets from the source artwork (seams S79, S88, S89, S89b).

The source is docs/coral/design/coral.png: the circular leaf mosaic on a
transparent background (UI§4.1). Every other copy of the logo in the repository
is derived from it here, so a new logo needs only a new source file and a re-run.

Usage, from the repository root:
  python .coral/tools/brand_assets.py generate   write every asset
  python .coral/tools/brand_assets.py check      exit 1 if an asset is missing or the wrong size

Layout rules (UI§4.4): app icons put the logo on the cream plate #FEF7F1 at about
72% of the plate; UI copies are the bare logo on a transparent background.
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageDraw

SOURCE = Path("docs/coral/design/coral.png")
CREAM = (0xFE, 0xF7, 0xF1)
MARK_SHARE = 0.72  # of the plate or canvas, for icons
SUPERSAMPLE = 4  # for antialiased plate corners
ANDROID_DENSITIES = {"mdpi": 1.0, "hdpi": 1.5, "xhdpi": 2.0, "xxhdpi": 3.0, "xxxhdpi": 4.0}
ANDROID_RES = "web/android/app/src/main/res"
IOS_IMAGESETS = ("CoralLogo", "CoralLogoReverse")
IOS_ASSETS = "web/ios/Omnigent/Assets.xcassets"
APP_ICON = "web/platform-assets/coral/AppIcon.icon"
LINUX_SIZES = (16, 24, 32, 48, 64, 128, 256, 512)
ICO_SIZES = (16, 24, 32, 48, 64, 128, 256)


@dataclass(frozen=True)
class Asset:
    """One generated image: its path and pixel size (square)."""

    path: str
    size: int


def load_mark() -> Image.Image:
    """The source logo cropped to its artwork and centred on a square canvas."""
    source = Image.open(SOURCE).convert("RGBA")
    # Ignore faint stray pixels when finding the artwork's edges.
    box = source.getchannel("A").point(lambda alpha: 255 if alpha > 16 else 0).getbbox()
    if box is None:
        raise SystemExit(f"{SOURCE} has no visible pixels")
    artwork = source.crop(box)
    side = max(artwork.size)
    square = Image.new("RGBA", (side, side), (0, 0, 0, 0))
    square.paste(artwork, ((side - artwork.width) // 2, (side - artwork.height) // 2))
    return square


def resized(image: Image.Image, size: int) -> Image.Image:
    """Resize with premultiplied alpha so transparent edges keep their colour."""
    return image.convert("RGBa").resize((size, size), Image.Resampling.LANCZOS).convert("RGBA")


def centred(mark: Image.Image, canvas: int, mark_size: int) -> Image.Image:
    """The mark at `mark_size` pixels in the middle of a transparent square canvas."""
    out = Image.new("RGBA", (canvas, canvas), (0, 0, 0, 0))
    offset = (canvas - mark_size) // 2
    out.alpha_composite(resized(mark, mark_size), (offset, offset))
    return out


def silhouette(
    mark: Image.Image, canvas: int, mark_size: int, colour: tuple[int, int, int]
) -> Image.Image:
    """A single-colour alpha mask of the mark, for tinted system icons."""
    alpha = centred(mark, canvas, mark_size).getchannel("A")
    out = Image.new("RGBA", (canvas, canvas), (*colour, 0))
    out.putalpha(alpha)
    return out


def plate_icon(mark: Image.Image, canvas: int = 1024, plate: int = 824) -> Image.Image:
    """The desktop app icon: the mark on a rounded cream plate with a clear margin."""
    big = canvas * SUPERSAMPLE
    margin = (canvas - plate) * SUPERSAMPLE // 2
    shape = Image.new("L", (big, big), 0)
    ImageDraw.Draw(shape).rounded_rectangle(
        (margin, margin, big - margin - 1, big - margin - 1),
        radius=round(plate * 0.225 * SUPERSAMPLE),
        fill=255,
    )
    out = Image.new("RGBA", (canvas, canvas), (*CREAM, 0))
    out.putalpha(shape.resize((canvas, canvas), Image.Resampling.LANCZOS))
    mark_size = round(plate * MARK_SHARE)
    offset = (canvas - mark_size) // 2
    out.alpha_composite(resized(mark, mark_size), (offset, offset))
    return out


def full_bleed_icon(mark: Image.Image, canvas: int) -> Image.Image:
    """An opaque cream square with the mark, for platforms that round corners themselves."""
    out = Image.new("RGBA", (canvas, canvas), (*CREAM, 255))
    out.alpha_composite(centred(mark, canvas, round(canvas * MARK_SHARE)))
    return out.convert("RGB")


def build(mark: Image.Image) -> dict[str, Image.Image]:
    """Every PNG asset, keyed by path."""
    images: dict[str, Image.Image] = {
        "web/src/brand/assets/coral-logo.png": resized(mark, 512),
        "web/platform-assets/logos/coral-logo.png": resized(mark, 512),
        "web/public/coral-favicon.png": resized(mark, 64),
        "web/public/coral-apple-touch-icon.png": full_bleed_icon(mark, 180),
        f"{APP_ICON}/Assets/Coral Logo.png": centred(mark, 1024, round(1024 * MARK_SHARE)),
    }
    desktop = plate_icon(mark)
    images["web/electron/icons/coral-icon.png"] = desktop
    for size in LINUX_SIZES:
        images[f"web/electron/icons/coral-linux/{size}x{size}.png"] = desktop.resize(
            (size, size), Image.Resampling.LANCZOS
        )
    for name in IOS_IMAGESETS:
        for scale, suffix in ((1, ""), (2, "@2x"), (3, "@3x")):
            images[f"{IOS_ASSETS}/{name}.imageset/coral-logo{suffix}.png"] = resized(
                mark, 80 * scale
            )
    for density, factor in ANDROID_DENSITIES.items():
        folder = f"{ANDROID_RES}/drawable-{density}"

        def px(dp: float, factor: float = factor) -> int:
            return round(dp * factor)

        images[f"{folder}/coral_logo.png"] = resized(mark, px(56))
        # Adaptive icon layers: a 108dp canvas whose middle 66dp is always visible.
        images[f"{folder}/coral_launcher_foreground.png"] = centred(mark, px(108), px(58))
        images[f"{folder}/coral_launcher_monochrome.png"] = silhouette(
            mark, px(108), px(58), (0, 0, 0)
        )
        # Notification icons are white alpha masks on a 24dp canvas.
        images[f"{folder}/coral_notification.png"] = silhouette(
            mark, px(24), px(22), (255, 255, 255)
        )
    return images


def expected() -> list[Asset]:
    """The size of every generated file, for `check`."""
    assets = [Asset(path, image.width) for path, image in build(load_mark()).items()]
    assets.append(Asset("web/electron/icons/coral-icon.icns", 1024))
    assets.append(Asset("web/electron/icons/coral-icon.ico", 256))
    return assets


def imageset_contents() -> str:
    images = [
        {"filename": f"coral-logo{suffix}.png", "idiom": "universal", "scale": f"{scale}x"}
        for scale, suffix in ((1, ""), (2, "@2x"), (3, "@3x"))
    ]
    return (
        json.dumps(
            {"images": images, "info": {"author": "xcode", "version": 1}}, indent=2
        ).replace('": ', '" : ')
        + "\n"
    )


def generate() -> None:
    mark = load_mark()
    for path, image in build(mark).items():
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        image.save(path, optimize=True)
    desktop = plate_icon(mark)
    desktop.save("web/electron/icons/coral-icon.icns")
    desktop.save("web/electron/icons/coral-icon.ico", sizes=[(size, size) for size in ICO_SIZES])
    for name in IOS_IMAGESETS:
        Path(f"{IOS_ASSETS}/{name}.imageset/Contents.json").write_text(imageset_contents())
    icon_json = Path(f"{APP_ICON}/icon.json")
    icon = json.loads(icon_json.read_text())
    layer = icon["groups"][0]["layers"][0]
    layer["image-name"], layer["name"] = "Coral Logo.png", "Coral Logo"
    icon_json.write_text(json.dumps(icon, indent=2).replace('": ', '" : '))


def check() -> int:
    problems = 0
    for asset in expected():
        path = Path(asset.path)
        if not path.is_file():
            print(f"missing: {asset.path}")
            problems += 1
            continue
        with Image.open(path) as image:
            if image.width != asset.size or image.height != asset.size:
                print(f"wrong size: {asset.path} is {image.size}, expected {asset.size}")
                problems += 1
    if problems:
        print("run: python .coral/tools/brand_assets.py generate", file=sys.stderr)
    return 1 if problems else 0


def main(argv: list[str]) -> int:
    if argv == ["generate"]:
        generate()
        return 0
    if argv == ["check"]:
        return check()
    print(__doc__, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
