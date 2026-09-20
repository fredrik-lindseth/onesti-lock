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

The README's second table, "Living sources", holds the things that keep
growing: forum threads, GitHub issues and the repositories whose code we read.
A hash cannot pin those, so each row carries the date it was last fetched and
a marker of how big it was then (post count, comment count, commit SHA). The
fetch compares the marker it finds against the one in the table, says what
moved, and writes the new date and marker back into the README. The content
stays gitignored; the row in git is the record of when we looked and at what.

    python3 scripts/fetch_manuals.py            # everything
    python3 scripts/fetch_manuals.py --living   # only the living sources
    python3 scripts/fetch_manuals.py --check    # living sources, no README write
"""
import argparse
import datetime
import hashlib
import html
import json
import re
import shutil
import subprocess
import sys
import tarfile
import urllib.error
import urllib.parse
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


def request(url):
    """A GET with our own User-Agent, and the path escaped so a Norwegian letter survives."""
    url = urllib.parse.quote(url, safe=":/?#[]@!$&'()*+,;=%~")
    return urllib.request.Request(url, headers={"User-Agent": "hacs-onesti-manual-fetcher/1.0"})


def download(url, dest):
    req = request(url)
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


# --------------------------------------------------------------------------
# Living sources: forum threads, GitHub issues, code that keeps moving
# --------------------------------------------------------------------------

LIVING_TYPES = {"discourse", "invision", "gh-issue", "gh-file", "gh-repo", "web", "appstore", "manual"}
LIVING_ROW_RE = re.compile(
    r"^\|(?P<item>[^|]+)\|(?P<source>[^|]+)\|(?P<type>[^|]+)\|"
    r"(?P<key>[^|]+)\|(?P<retrieved>[^|]+)\|(?P<marker>[^|]+)\|\s*$"
)


class LivingRow:
    """One row of the Living sources table, and the cells the fetch rewrites."""

    def __init__(self, line, item, source, kind, key, retrieved, marker):
        self.line = line
        self.item = item
        self.source = source
        self.kind = kind
        self.key = key
        self.retrieved = retrieved
        self.marker = marker

    def rewritten(self, retrieved, marker):
        """The same table line with the last two cells replaced, width kept."""
        cells = self.line.rstrip().split("|")
        cells[-3] = pad_like(cells[-3], retrieved)
        cells[-2] = pad_like(cells[-2], marker)
        return "|".join(cells)


def pad_like(old_cell, value):
    """Put `value` in a table cell, keeping the column width where it fits."""
    text = f" {value} "
    return text if len(text) > len(old_cell) else text + " " * (len(old_cell) - len(text))


def parse_living_table(text):
    """Pull the Living sources rows out of the README.

    Six columns, of which the third is a known living type. The Sources table
    has four columns and the Documents table five, so neither can match.
    """
    rows = []
    for line in text.splitlines():
        m = LIVING_ROW_RE.match(line.rstrip())
        if not m:
            continue
        kind = m.group("type").strip().strip("`").lower()
        if kind not in LIVING_TYPES:
            continue
        rows.append(
            LivingRow(
                line=line.rstrip(),
                item=m.group("item").strip().strip("`"),
                source=m.group("source").strip().strip("`").strip("<>"),
                kind=kind,
                key=m.group("key").strip().strip("`"),
                retrieved=m.group("retrieved").strip(),
                marker=m.group("marker").strip().strip("`"),
            )
        )
    return rows


def strip_html(text):
    """Discourse's `cooked` HTML down to something readable, for the .txt beside the JSON."""
    text = re.sub(r"(?s)<(script|style).*?</\1>", "", text or "")
    text = re.sub(r"<br\s*/?>|</p>|</li>", "\n", text)
    text = re.sub(r"<[^>]+>", "", text)
    return html.unescape(text).strip()


def write_thread_text(dest, header, entries):
    """A JSON thread also gets a .txt, for the same reason a PDF gets one: to be read.

    Reading a 240-post thread out of JSON is no fun, and grep over the JSON
    matches escape sequences rather than sentences.
    """
    lines = [header]
    for title, body in entries:
        lines.append(f"### {title}\n{body}")
    dest.with_suffix(".txt").write_text("\n\n".join(lines) + "\n")


def get_json(url, timeout=60):
    with urllib.request.urlopen(request(url), timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def gh(*args):
    """Run `gh` and return parsed JSON, or raise RuntimeError with its stderr."""
    result = subprocess.run(["gh", *args], capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip().splitlines()[-1] if result.stderr.strip() else "gh failed")
    return json.loads(result.stdout or "null")


def fetch_discourse(row, dest):
    """A whole Discourse topic as one JSON file: topic metadata plus every post.

    Discourse serves the first 20 posts inline and the rest through
    /t/<id>/posts.json?post_ids[]=..., 20 ids at a time, which is the only
    paging the public API offers and has not changed in years.
    """
    base = row.source.rstrip("/")
    topic = get_json(f"{base}/t/{row.key}.json?include_raw=true")
    stream = topic["post_stream"]["stream"]
    have = {p["id"]: p for p in topic["post_stream"]["posts"]}
    for start in range(0, len(stream), 20):
        missing = [i for i in stream[start : start + 20] if i not in have]
        if not missing:
            continue
        query = "&".join(f"post_ids[]={i}" for i in missing)
        chunk = get_json(f"{base}/t/{row.key}/posts.json?{query}&include_raw=true")
        for post in chunk["post_stream"]["posts"]:
            have[post["id"]] = post
    posts = [have[i] for i in stream if i in have]
    payload = {
        "fetched": today(),
        "url": f"{base}/t/{row.key}",
        "title": topic.get("title"),
        "posts_count": topic.get("posts_count"),
        "created_at": topic.get("created_at"),
        "last_posted_at": topic.get("last_posted_at"),
        "posts": posts,
    }
    write_json(dest, payload)
    write_thread_text(
        dest,
        f"# {topic.get('title')} ({topic.get('posts_count')} posts, fetched {today()})\n{payload['url']}",
        [
            (
                f"#{p['post_number']} {p.get('username')} {p.get('created_at', '')[:10]}",
                p.get("raw") or strip_html(p.get("cooked")),
            )
            for p in posts
        ],
    )
    return str(topic.get("posts_count", len(posts))), f"{len(posts)} posts stored"


GH_ISSUE_RE = re.compile(r"^(?P<repo>[\w.-]+/[\w.-]+)#(?P<number>\d+)$")


def fetch_gh_issue(row, dest):
    """One issue or pull request with its full comment thread, as one JSON file."""
    m = GH_ISSUE_RE.match(row.key)
    if not m:
        raise RuntimeError(f"key {row.key!r} is not owner/repo#number")
    repo, number = m.group("repo"), m.group("number")
    issue = gh("api", f"repos/{repo}/issues/{number}")
    comments = gh("api", "--paginate", f"repos/{repo}/issues/{number}/comments?per_page=100")
    review_comments = []
    if issue.get("pull_request"):
        review_comments = gh("api", "--paginate", f"repos/{repo}/pulls/{number}/comments?per_page=100")
    payload = {
        "fetched": today(),
        "repo": repo,
        "number": int(number),
        "issue": issue,
        "comments": comments,
        "review_comments": review_comments,
    }
    write_json(dest, payload)
    total = len(comments) + len(review_comments)
    write_thread_text(
        dest,
        f"# {repo}#{number} {issue.get('title')} ({issue.get('state')}, {total} comments, fetched {today()})\n{issue.get('html_url')}",
        [(f"{issue['user']['login']} {issue.get('created_at', '')[:10]} (opening post)", issue.get("body") or "")]
        + [
            (f"{c['user']['login']} {c.get('created_at', '')[:10]}", c.get("body") or "")
            for c in comments + review_comments
        ],
    )
    return f"{total}c", f"{issue.get('state')}, {total} comments"


GH_FILE_RE = re.compile(r"^(?P<repo>[\w.-]+/[\w.-]+):(?P<path>[^@]+)@(?P<ref>\S+)$")


def fetch_gh_file(row, dest):
    """One file from a repository at a branch, marked with the commit that last touched it."""
    m = GH_FILE_RE.match(row.key)
    if not m:
        raise RuntimeError(f"key {row.key!r} is not owner/repo:path@ref")
    repo, path, ref = m.group("repo"), m.group("path"), m.group("ref")
    commits = gh("api", f"repos/{repo}/commits?path={path}&sha={ref}&per_page=1")
    if not commits:
        raise RuntimeError(f"no commit touches {path} on {ref}")
    sha = commits[0]["sha"]
    dest.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["gh", "api", "-H", "Accept: application/vnd.github.raw", f"repos/{repo}/contents/{path}?ref={sha}"],
        stdout=dest.open("wb"),
        check=True,
    )
    date = commits[0]["commit"]["committer"]["date"][:10]
    return sha[:12], f"last touched {date}"


GH_REPO_RE = re.compile(r"^(?P<repo>[\w.-]+/[\w.-]+)@(?P<ref>\S+)$")


def fetch_gh_repo(row, dest):
    """A whole repository at the head of a branch, unpacked into `dest`."""
    m = GH_REPO_RE.match(row.key)
    if not m:
        raise RuntimeError(f"key {row.key!r} is not owner/repo@branch")
    repo, ref = m.group("repo"), m.group("ref")
    head = gh("api", f"repos/{repo}/commits/{ref}")
    sha = head["sha"]
    stamp = dest / ".snapshot-sha"
    if stamp.exists() and stamp.read_text().strip() == sha:
        return sha[:12], "unpacked already"
    tarball = dest.with_suffix(".tar.gz")
    download(f"https://codeload.github.com/{repo}/tar.gz/{sha}", tarball)
    shutil.rmtree(dest, ignore_errors=True)
    with tarfile.open(tarball, "r:gz") as tf:
        tf.extractall(dest, filter="data")
    tarball.unlink()
    # codeload wraps everything in <repo>-<sha>/; lift it so paths stay short.
    inner = [p for p in dest.iterdir() if p.is_dir()]
    if len(inner) == 1 and not any(p.is_file() for p in dest.iterdir()):
        for child in list(inner[0].iterdir()):
            shutil.move(str(child), str(dest / child.name))
        inner[0].rmdir()
    (dest / ".snapshot-sha").write_text(sha + "\n")
    date = head["commit"]["committer"]["date"][:10]
    return sha[:12], f"head of {ref}, {date}"


IPS_POST_RE = re.compile(r"contentcommentid&quot;:(?P<id>\d+)\}'\s*class='ipsComment_content")


def fetch_invision(row, dest):
    """An Invision Community topic (hjemmeautomasjon.no), page by page.

    Invision has no public JSON API, but the topic pages are served whole to
    an unauthenticated fetch, posts included, 25 to a page. Each post is
    marked with a `contentcommentid`, so counting them gives both the marker
    and the stop condition: a page that adds no new id is past the end.
    """
    base = row.source.rstrip("/")
    seen, chunks = [], []
    for page in range(1, 41):
        url = base if page == 1 else f"{base}/page/{page}/"
        try:
            with urllib.request.urlopen(request(url), timeout=60) as resp:
                text = resp.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as exc:
            if exc.code == 404 and page > 1:
                break
            raise
        ids = [m.group("id") for m in IPS_POST_RE.finditer(text)]
        fresh = [i for i in ids if i not in seen]
        if not fresh:
            break
        seen.extend(fresh)
        bounds = [m.start() for m in IPS_POST_RE.finditer(text)] + [len(text)]
        for n, start in enumerate(bounds[:-1]):
            if ids[n] in fresh:
                chunks.append((ids[n], strip_html(text[start : bounds[n + 1]])))
    if not seen:
        raise RuntimeError("no posts found; the page layout may have changed")
    write_thread_text(
        dest,
        f"# {base} ({len(seen)} posts, fetched {today()})",
        [(f"post {pid}", body) for pid, body in chunks],
    )
    return str(len(seen)), f"{len(seen)} posts over {page} page(s)"


def fetch_web(row, dest):
    """A vendor page or a plain file.

    A `.txt` row means "this is a web page": the raw HTML lands beside it and
    the row keeps the text. The marker is the hash of the text and not of the
    HTML, because these pages carry a fresh nonce on every request and would
    otherwise report a change every single time.
    """
    if dest.suffix != ".txt":
        download(row.source, dest)
        return sha256_of(dest)[:12], f"{dest.stat().st_size} bytes"
    raw = dest.with_suffix(".html")
    download(row.source, raw)
    text = strip_html(raw.read_text(encoding="utf-8", errors="replace"))
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    dest.write_text(f"# {row.source}\n# fetched {today()}\n\n{text}\n")
    return hashlib.sha256(text.encode()).hexdigest()[:12], f"{len(text)} characters of text"


def fetch_appstore(row, dest):
    """An App Store listing through Apple's public lookup API, marked with its version.

    The store page itself is a JavaScript shell; the lookup endpoint answers
    JSON with the current version, its release date and the release notes,
    which is the part worth keeping.
    """
    data = get_json(f"https://itunes.apple.com/lookup?id={row.key}&country=no")
    if not data.get("results"):
        raise RuntimeError(f"App Store knows no id {row.key} in the Norwegian store")
    app = data["results"][0]
    write_json(dest, {"fetched": today(), "app": app})
    return app.get("version", "?"), f"{app.get('trackName')} by {app.get('sellerName')}, {app.get('currentVersionReleaseDate', '')[:10]}"


FETCHERS = {
    "discourse": fetch_discourse,
    "invision": fetch_invision,
    "gh-issue": fetch_gh_issue,
    "gh-file": fetch_gh_file,
    "gh-repo": fetch_gh_repo,
    "web": fetch_web,
    "appstore": fetch_appstore,
}


def today():
    return datetime.date.today().isoformat()


def write_json(dest, payload):
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(payload, indent=1, ensure_ascii=False))


def fetch_living(write_back=True):
    """Fetch every living source, report what moved, and update the README rows."""
    text = README.read_text()
    rows = parse_living_table(text)
    if not rows:
        print("No living-source rows found in the README")
        return 0

    changes, replacements = [], {}
    for row in rows:
        if row.kind == "manual":
            print(f"manual     {row.item}: fetch by hand, last done {row.retrieved}")
            continue
        dest = MANUALS_DIR / row.item
        dest.parent.mkdir(parents=True, exist_ok=True)
        try:
            marker, note = FETCHERS[row.kind](row, dest)
        except Exception as exc:  # noqa: BLE001 - report and keep going
            print(f"FAILED     {row.item}: {exc}")
            continue
        if marker == row.marker:
            print(f"same       {row.item}: {row.marker} ({note})")
        else:
            was = f"was {row.marker} on {row.retrieved}" if row.marker != "-" else "first fetch"
            print(f"CHANGED    {row.item}: {row.marker} -> {marker} ({was}; {note})")
            changes.append((row.item, row.marker, marker))
        replacements[row.line] = row.rewritten(today(), marker)

    if write_back and replacements:
        out = [replacements.get(line.rstrip(), line) for line in text.splitlines()]
        README.write_text("\n".join(out) + "\n")
        print(f"\n{len(replacements)} rows dated {today()} in {README.relative_to(ROOT)}")
    if changes:
        print(f"{len(changes)} source(s) moved since the last fetch:")
        for item, before, after in changes:
            print(f"  {item}: {before} -> {after}")
    else:
        print("nothing moved since the last fetch")
    return 0


def fetch_pinned():
    """Fetch the hash-pinned Sources table: manuals, captures, logs."""
    rows = parse_table(README.read_text())
    if not rows:
        print(f"No manual rows found in {README}", file=sys.stderr)
        return 1

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


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--living", action="store_true", help="only the living sources")
    parser.add_argument("--pinned", action="store_true", help="only the hash-pinned sources")
    parser.add_argument("--check", action="store_true", help="living sources, without rewriting the README")
    args = parser.parse_args(argv)

    if not README.exists():
        print(f"{README} not found", file=sys.stderr)
        return 1
    MANUALS_DIR.mkdir(parents=True, exist_ok=True)

    status = 0
    if not (args.living or args.check):
        status |= fetch_pinned()
    if not args.pinned:
        if not (args.living or args.check):
            print()
        status |= fetch_living(write_back=not args.check)
    return status


if __name__ == "__main__":
    sys.exit(main())
