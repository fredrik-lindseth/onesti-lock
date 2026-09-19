"""Download the manufacturer manuals listed in docs/manuals/README.md.

docs/manuals/*.pdf and *.txt are gitignored (manufacturer copyright, kept
local only), so a fresh checkout has none of them. The "Sources" table in
the README is the single source of truth for what belongs there: local
filename, URL and expected SHA-256 per file. This script re-derives the
folder from that table, downloads whatever is missing or has the wrong
hash, and runs `pdftotext -layout` for any PDF that doesn't have a matching
.txt yet.

Safe to run repeatedly: an already-correct file is left untouched.

    python3 scripts/fetch_manuals.py
"""
import hashlib
import re
import shutil
import subprocess
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MANUALS_DIR = ROOT / "docs" / "manuals"
README = MANUALS_DIR / "README.md"

ROW_RE = re.compile(r"^\|(?P<file>[^|]+)\|(?P<url>[^|]+)\|(?P<sha>[^|]+)\|\s*$")
SHA_RE = re.compile(r"^[0-9a-f]{64}$")
URL_RE = re.compile(r"^https?://\S+$")


def parse_table(text):
    """Pull (url, local filename, sha256) triples out of the README's Sources table.

    The README has two other tables (Documents, White-label brands) with a
    different number of columns, so a plain "starts with |" match isn't
    enough. Only rows whose last cell is a bare 64-hex-char SHA-256 and whose
    middle cell is a URL count as manual rows.
    """
    rows = []
    for line in text.splitlines():
        m = ROW_RE.match(line.strip())
        if not m:
            continue
        filename = m.group("file").strip().strip("`")
        url = m.group("url").strip().strip("`")
        sha = m.group("sha").strip().strip("`").lower()
        if not (SHA_RE.match(sha) and URL_RE.match(url) and filename):
            continue
        rows.append((url, filename, sha))
    return rows


def sha256_of(path):
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def download(url, dest):
    req = urllib.request.Request(url, headers={"User-Agent": "hacs-onesti-manual-fetcher/1.0"})
    with urllib.request.urlopen(req, timeout=60) as resp, dest.open("wb") as out:
        shutil.copyfileobj(resp, out)


def ensure_pdf(url, filename, expected_sha):
    dest = MANUALS_DIR / filename
    if dest.exists() and sha256_of(dest) == expected_sha:
        print(f"ok         {filename}")
        return dest

    try:
        download(url, dest)
    except Exception as exc:  # noqa: BLE001 - report and keep going
        print(f"DEAD LINK  {filename}: could not fetch {url} ({exc})")
        return dest if dest.exists() else None

    actual = sha256_of(dest)
    if actual != expected_sha:
        print(f"HASH DIFF  {filename}: expected {expected_sha}, got {actual} (manufacturer may have updated the file)")
    else:
        print(f"fetched    {filename}")
    return dest


def pdftotext_path():
    return shutil.which("pdftotext")


def ensure_text(pdf_path, pdftotext, warned):
    txt_path = pdf_path.with_suffix(".txt")
    if txt_path.exists():
        return
    if not pdftotext:
        if not warned[0]:
            print(
                "pdftotext not found on PATH: install poppler to get .txt extracts "
                "(macOS: brew install poppler / Debian & Ubuntu: apt install poppler-utils)"
            )
            warned[0] = True
        return
    result = subprocess.run([pdftotext, "-layout", str(pdf_path), str(txt_path)], capture_output=True, text=True)
    if result.returncode != 0:
        print(f"pdftotext failed for {pdf_path.name}: {result.stderr.strip()}")
        return
    # pdftotext emits a lone form-feed (\x0c) per page even when a page has
    # no real text, so a byte count alone won't catch an image-only PDF.
    contents = txt_path.read_text(errors="replace") if txt_path.exists() else ""
    if not contents.strip("\x0c \t\r\n"):
        print(f"EMPTY TEXT {pdf_path.name}: pdftotext produced nothing, likely a scanned or image-only PDF")
    else:
        print(f"extracted  {txt_path.name}")


def main():
    if not README.exists():
        print(f"{README} not found", file=sys.stderr)
        return 1

    rows = parse_table(README.read_text())
    if not rows:
        print(f"No manual rows found in {README}", file=sys.stderr)
        return 1

    MANUALS_DIR.mkdir(parents=True, exist_ok=True)
    pdftotext = pdftotext_path()
    warned = [False]

    for url, filename, expected_sha in rows:
        pdf_path = ensure_pdf(url, filename, expected_sha)
        if pdf_path and pdf_path.exists():
            ensure_text(pdf_path, pdftotext, warned)

    return 0


if __name__ == "__main__":
    sys.exit(main())
