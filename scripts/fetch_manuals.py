"""Download the sources listed in docs/manuals/README.md.

Everything under docs/manuals/ is gitignored (someone else's copyright, kept
local only), so a fresh checkout has none of it. The "Sources" table in the
README is the single source of truth for what belongs there: local filename,
URL, type and expected SHA-256 per file. This script re-derives the folder
from that table, downloads whatever is missing or has the wrong hash, and
then does what the type asks for:

    pdf             run `pdftotext -layout` when the .txt is missing
    txt, json       store as-is
    zip             unpack into a folder named after the archive
    repo-snapshot   unpack the .tar.gz into a folder named after the archive

Safe to run repeatedly: an already-correct file is left untouched.

Some sources cannot be fetched by a script at all. The FCC exhibit PDFs sit
behind a bot filter that answers 403 to anything but a browser session, so a
fresh checkout will see DEAD LINK for those rows and has to get them by hand
(the README says how). An existing local copy is never damaged by that.

    python3 scripts/fetch_manuals.py
"""
import hashlib
import re
import shutil
import subprocess
import sys
import tarfile
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MANUALS_DIR = ROOT / "docs" / "manuals"
README = MANUALS_DIR / "README.md"

ROW_RE = re.compile(r"^\|(?P<file>[^|]+)\|(?P<url>[^|]+)\|(?P<type>[^|]+)\|(?P<sha>[^|]+)\|\s*$")
SHA_RE = re.compile(r"^[0-9a-f]{64}$")
URL_RE = re.compile(r"^https?://\S+$")
TYPES = {"pdf", "txt", "json", "zip", "repo-snapshot"}


def parse_table(text):
    """Pull (url, local filename, type, sha256) rows out of the README's Sources table.

    The README has two other tables (Documents, White-label brands) with a
    different number of columns, so a plain "starts with |" match isn't
    enough. Only rows whose last cell is a bare 64-hex-char SHA-256, whose
    second cell is a URL and whose third cell is a known type count.
    """
    rows = []
    for line in text.splitlines():
        m = ROW_RE.match(line.strip())
        if not m:
            continue
        filename = m.group("file").strip().strip("`")
        url = m.group("url").strip().strip("`")
        kind = m.group("type").strip().strip("`").lower()
        sha = m.group("sha").strip().strip("`").lower()
        if not (SHA_RE.match(sha) and URL_RE.match(url) and filename and kind in TYPES):
            continue
        rows.append((url, filename, kind, sha))
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


def ensure_file(url, filename, expected_sha):
    dest = MANUALS_DIR / filename
    dest.parent.mkdir(parents=True, exist_ok=True)
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


def unpacked_dir(archive_path):
    """Folder an archive unpacks into: the filename without its suffixes."""
    name = archive_path.name
    for suffix in (".tar.gz", ".tgz", ".zip"):
        if name.endswith(suffix):
            return archive_path.with_name(name[: -len(suffix)])
    return archive_path.with_name(name + ".unpacked")


def ensure_unpacked(archive_path, kind):
    """Unpack zip or tar.gz next to the archive, once."""
    target = unpacked_dir(archive_path)
    if target.exists():
        return
    try:
        if kind == "zip":
            with zipfile.ZipFile(archive_path) as zf:
                zf.extractall(target)
        else:
            with tarfile.open(archive_path, "r:gz") as tf:
                tf.extractall(target, filter="data")
    except Exception as exc:  # noqa: BLE001 - report and keep going
        print(f"UNPACK FAIL {archive_path.name}: {exc}")
        shutil.rmtree(target, ignore_errors=True)
        return
    print(f"unpacked   {target.name}/")


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

    for url, filename, kind, expected_sha in rows:
        path = ensure_file(url, filename, expected_sha)
        if not (path and path.exists()):
            continue
        if kind == "pdf":
            ensure_text(path, pdftotext, warned)
        elif kind in ("zip", "repo-snapshot"):
            ensure_unpacked(path, kind)

    return 0


if __name__ == "__main__":
    sys.exit(main())
