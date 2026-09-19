"""Render the integration icon from images/icon.svg into the brand/ directory.

Home Assistant 2026.3 and later read brand images from
custom_components/onesti_lock/brand/ (the Brands Proxy API), and HACS accepts
brand/icon.png in place of an entry in home-assistant/brands. The PNGs there are
generated, never edited by hand:

    python3 scripts/generate_brand_images.py          # write the PNGs
    python3 scripts/generate_brand_images.py --check  # exit 1 if they are stale

Rendering needs rsvg-convert (librsvg). Nothing else does: every PNG carries the
SHA-256 of the SVG it came from in a tEXt chunk, so tests/test_brand_images.py
can tell a stale PNG from a fresh one with the standard library alone.

The PNG is rewritten after rendering: rsvg-convert's bKGD chunk is dropped (a
viewer may paint that colour behind the transparent icon), the source hash is
added, and the image data is recompressed at zlib level 9.
"""

from __future__ import annotations

import argparse
import hashlib
import shutil
import struct
import subprocess
import sys
import zlib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SOURCE_SVG = REPO_ROOT / "images" / "icon.svg"
BRAND_DIR = REPO_ROOT / "custom_components" / "onesti_lock" / "brand"

# File name -> edge length in pixels, from the icon rules in home-assistant/brands.
OUTPUTS = {"icon.png": 256, "icon@2x.png": 512}

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
SOURCE_HASH_KEY = b"onesti-source-sha256"


def source_hash(svg: Path = SOURCE_SVG) -> str:
    return hashlib.sha256(svg.read_bytes()).hexdigest()


def read_chunks(data: bytes) -> list[tuple[bytes, bytes]]:
    """Split a PNG into (type, payload) pairs, checking the signature."""
    if not data.startswith(PNG_SIGNATURE):
        raise ValueError("not a PNG file")
    chunks = []
    pos = len(PNG_SIGNATURE)
    while pos < len(data):
        (length,) = struct.unpack(">I", data[pos : pos + 4])
        kind = data[pos + 4 : pos + 8]
        chunks.append((kind, data[pos + 8 : pos + 8 + length]))
        pos += 12 + length
    return chunks


def text_chunks(data: bytes) -> dict[bytes, bytes]:
    return dict(payload.split(b"\0", 1) for kind, payload in read_chunks(data) if kind == b"tEXt")


def pixel_stream(data: bytes) -> bytes:
    """The decompressed, still filtered, image data: equal streams mean equal pixels."""
    return zlib.decompress(b"".join(payload for kind, payload in read_chunks(data) if kind == b"IDAT"))


def _chunk(kind: bytes, payload: bytes) -> bytes:
    return struct.pack(">I", len(payload)) + kind + payload + struct.pack(">I", zlib.crc32(kind + payload))


def rewrite_png(rendered: bytes, svg_hash: str) -> bytes:
    """Keep IHDR and the pixels, add the source hash, drop everything else."""
    chunks = read_chunks(rendered)
    header = next(payload for kind, payload in chunks if kind == b"IHDR")
    pixels = zlib.decompress(b"".join(payload for kind, payload in chunks if kind == b"IDAT"))
    return (
        PNG_SIGNATURE
        + _chunk(b"IHDR", header)
        + _chunk(b"tEXt", SOURCE_HASH_KEY + b"\0" + svg_hash.encode("ascii"))
        + _chunk(b"IDAT", zlib.compress(pixels, 9))
        + _chunk(b"IEND", b"")
    )


def render(size: int, svg: Path = SOURCE_SVG) -> bytes:
    rsvg = shutil.which("rsvg-convert")
    if rsvg is None:
        sys.exit(
            "rsvg-convert was not found. It comes with librsvg: `brew install librsvg` on macOS, "
            "`apt install librsvg2-bin` on Debian and Ubuntu."
        )
    result = subprocess.run(
        [rsvg, "--width", str(size), "--height", str(size), "--format", "png", str(svg)],
        capture_output=True,
        check=True,
    )
    return rewrite_png(result.stdout, source_hash(svg))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true", help="compare with the files on disk instead of writing")
    args = parser.parse_args()

    stale = []
    for name, size in OUTPUTS.items():
        fresh = render(size)
        target = BRAND_DIR / name
        if args.check:
            # Compare pixels and metadata, not compressed bytes, which can differ between zlib builds.
            current = target.read_bytes() if target.is_file() else b""
            if not current or (read_chunks(current)[0], text_chunks(current), pixel_stream(current)) != (
                read_chunks(fresh)[0],
                text_chunks(fresh),
                pixel_stream(fresh),
            ):
                stale.append(name)
            continue
        BRAND_DIR.mkdir(parents=True, exist_ok=True)
        target.write_bytes(fresh)
        print(f"wrote {target.relative_to(REPO_ROOT)} ({size}x{size}, {len(fresh)} bytes)")

    if stale:
        print(f"stale brand images: {', '.join(stale)}; run python3 scripts/generate_brand_images.py", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
