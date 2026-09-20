"""Measure WCAG 1.4.11 contrast for the colour tokens in an icon SVG.

Same maths as tests/test_brand_images.py: every token must reach 3:1 against
white and against Home Assistant's dark page background.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

LIGHT = "#ffffff"
DARK = "#111111"
MIN = 3.0


def luminance(hex_colour: str) -> float:
    channels = [int(hex_colour[i : i + 2], 16) / 255 for i in (1, 3, 5)]
    linear = [c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


def contrast(a: str, b: str) -> float:
    high, low = sorted((luminance(a), luminance(b)), reverse=True)
    return (high + 0.05) / (low + 0.05)


def tokens(svg: Path) -> dict[str, str]:
    style = re.search(r"<style>(.*?)</style>", svg.read_text(), re.S)
    assert style, f"{svg} has no <style> block"
    return dict(re.findall(r"\.([\w-]+)\s*\{\s*(?:fill|stroke)\s*:\s*(#[0-9A-Fa-f]{6})\s*;", style.group(1)))


def main() -> int:
    bad = 0
    for arg in sys.argv[1:]:
        path = Path(arg)
        print(path.name)
        for name, colour in tokens(path).items():
            light, dark = contrast(colour, LIGHT), contrast(colour, DARK)
            mark = " " if min(light, dark) >= MIN else "FAIL"
            bad += mark == "FAIL"
            print(f"  .{name:<10} {colour}  white {light:5.2f}:1   dark {dark:5.2f}:1  {mark}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
