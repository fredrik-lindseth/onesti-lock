# Icon tools

Two throwaway-friendly tools kept from the round that produced
`images/icon.svg`. Neither runs in CI, and neither is the authority on whether
an icon is acceptable: `tests/test_brand_images.py` is, and
`scripts/generate_brand_images.py` is what renders the PNGs that ship.

`contrast.py` prints the WCAG 1.4.11 contrast of every colour token in an SVG
against white and against Home Assistant's dark page background, with the same
maths as the test. Useful while picking a colour, before a full test run:

```bash
python3 tools/icons/contrast.py images/icon.svg
```

`contact-sheet.sh` renders a set of candidate icons at 256, 48 and 24 px on
both backgrounds and appends them into one `kontaktark.png`, which is the only
way to judge a 24 px icon honestly. It expects a working directory holding one
`a-*`, `b-*`, `c-*` directory per candidate, each with an `icon.svg`, and
writes next to them. Needs `rsvg-convert` (librsvg) and `magick` (ImageMagick).
