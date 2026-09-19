"""The brand images Home Assistant and HACS read from custom_components/onesti_lock/brand/.

HA 2026.3 and later serve these through the Brands Proxy API, and HACS's brands
check passes when brand/icon.png exists. The PNGs are rendered from
images/icon.svg by scripts/generate_brand_images.py. CI has no rsvg-convert,
so these tests use only the standard library: the PNG header for size and
colour type, the source hash the script writes into a tEXt chunk for freshness,
and a small decoder for the transparency and trim checks.
"""

from __future__ import annotations

import importlib.util
import re
import struct
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("generate_brand_images", REPO_ROOT / "scripts/generate_brand_images.py")
assert _spec is not None and _spec.loader is not None
gen = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(gen)

# The file names the Brands Proxy API looks for; anything else in brand/ is noise.
ALLOWED_NAMES = {
    f"{prefix}{kind}{scale}.png" for prefix in ("", "dark_") for kind in ("icon", "logo") for scale in ("", "@2x")
}

# Home Assistant's default light and dark page backgrounds.
LIGHT_BACKGROUND = "#ffffff"
DARK_BACKGROUND = "#111111"
# WCAG 1.4.11: graphical objects need 3:1 against what they sit on.
MIN_CONTRAST = 3.0


def _header(path: Path) -> tuple[int, int, int, int, int]:
    """Width, height, bit depth, colour type and interlace method from IHDR."""
    data = path.read_bytes()
    assert data.startswith(gen.PNG_SIGNATURE), f"{path.name} is not a PNG"
    assert data[12:16] == b"IHDR", f"{path.name} does not start with IHDR"
    width, height, depth, colour, _compression, _filter, interlace = struct.unpack(">IIBBBBB", data[16:29])
    return width, height, depth, colour, interlace


def _alpha_rows(path: Path) -> list[bytes]:
    """Alpha channel per row of an 8-bit RGBA, non-interlaced PNG."""
    width, height, depth, colour, interlace = _header(path)
    assert (depth, colour, interlace) == (8, 6, 0)
    stream = gen.pixel_stream(path.read_bytes())
    stride = width * 4
    rows: list[bytes] = []
    previous = bytearray(stride)
    for y in range(height):
        start = y * (stride + 1)
        kind = stream[start]
        row = bytearray(stream[start + 1 : start + 1 + stride])
        for i in range(stride):
            left = row[i - 4] if i >= 4 else 0
            up = previous[i]
            up_left = previous[i - 4] if i >= 4 else 0
            if kind == 1:
                row[i] = (row[i] + left) & 0xFF
            elif kind == 2:
                row[i] = (row[i] + up) & 0xFF
            elif kind == 3:
                row[i] = (row[i] + (left + up) // 2) & 0xFF
            elif kind == 4:
                p = left + up - up_left
                pa, pb, pc = abs(p - left), abs(p - up), abs(p - up_left)
                pred = left if pa <= pb and pa <= pc else up if pb <= pc else up_left
                row[i] = (row[i] + pred) & 0xFF
        rows.append(bytes(row[3::4]))
        previous = row
    return rows


def _luminance(hex_colour: str) -> float:
    channels = [int(hex_colour[i : i + 2], 16) / 255 for i in (1, 3, 5)]
    linear = [c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


def _contrast(a: str, b: str) -> float:
    high, low = sorted((_luminance(a), _luminance(b)), reverse=True)
    return (high + 0.05) / (low + 0.05)


def _svg_tokens() -> dict[str, str]:
    """Class name -> colour from the style block at the top of the SVG."""
    style = re.search(r"<style>(.*?)</style>", gen.SOURCE_SVG.read_text(), re.S)
    assert style, "images/icon.svg has no <style> block with its colour tokens"
    return dict(re.findall(r"\.([\w-]+)\s*\{\s*(?:fill|stroke)\s*:\s*(#[0-9A-Fa-f]{6})\s*;", style.group(1)))


def test_brand_dir_holds_only_names_the_brands_api_reads():
    names = {p.name for p in gen.BRAND_DIR.iterdir() if not p.name.startswith(".")}
    assert names <= ALLOWED_NAMES, f"unexpected files in brand/: {sorted(names - ALLOWED_NAMES)}"


@pytest.mark.parametrize(("name", "size"), gen.OUTPUTS.items())
def test_icon_is_a_square_rgba_png_of_the_required_size(name, size):
    path = gen.BRAND_DIR / name
    assert path.is_file(), f"{name} is missing; run python3 scripts/generate_brand_images.py"
    width, height, depth, colour, _interlace = _header(path)
    assert (width, height) == (size, size)
    assert (depth, colour) == (8, 6), "expected 8-bit RGBA so the background stays transparent"


@pytest.mark.parametrize("name", gen.OUTPUTS)
def test_icon_was_rendered_from_the_current_svg(name):
    chunks = gen.text_chunks((gen.BRAND_DIR / name).read_bytes())
    assert chunks.get(gen.SOURCE_HASH_KEY) == gen.source_hash().encode(), (
        f"{name} was not rendered from the current images/icon.svg; run python3 scripts/generate_brand_images.py"
    )


def test_icon_is_transparent_and_trimmed():
    rows = _alpha_rows(gen.BRAND_DIR / "icon.png")
    assert rows[0][0] == 0 and rows[-1][0] == 0, "corners must be transparent"
    assert any(rows[0]) and any(rows[-1]), "the motif must touch the top and bottom edge (trimmed)"


def test_svg_colours_come_only_from_the_token_block():
    text = gen.SOURCE_SVG.read_text()
    outside = re.sub(r"<style>.*?</style>", "", text, flags=re.S)
    assert not re.search(r"#[0-9A-Fa-f]{3,8}\b", outside), "write colours as class rules in the <style> block"
    assert not re.search(r"Gradient", text), "the icon is flat; no gradients"


@pytest.mark.parametrize("background", [LIGHT_BACKGROUND, DARK_BACKGROUND])
def test_every_colour_token_holds_contrast_on_both_backgrounds(background):
    tokens = _svg_tokens()
    assert tokens, "no colour tokens found in images/icon.svg"
    for name, colour in tokens.items():
        ratio = _contrast(colour, background)
        assert ratio >= MIN_CONTRAST, f".{name} {colour} is {ratio:.2f}:1 on {background}"
