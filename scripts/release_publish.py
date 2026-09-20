#!/usr/bin/env python3
"""The state machine that ships a version, and that survives being run again.

The problem it solves: tag, ZIP and attestation used to be three loose ends.
The tag was created by the release API without a `target_commitish`, the ZIP
was packed from the checkout, and the attestation came from a third step. A
release could tag one commit, build another and attest a third, and it was
public long before the ZIP was in place. That is not theory: a sibling
integration has a shipped release whose tag and whose attestation name
different commits. The contents happened to match that time.

Here the candidate is one thing: **repo + full commit SHA + manifest version**.
All three ends are bound to it, and the binding can be checked afterwards:

* The ZIP is built from the git objects at that exact SHA, not from the working
  tree, so the contents *are* what the tag points at. The build is
  deterministic, so anyone can rebuild it and get the same sha256.
* The tag is created explicitly on that SHA. If it already exists it is
  dereferenced (annotated or lightweight) and compared. It is never moved.
* The attestation is verified against repo, source SHA, signer workflow and the
  sha256 of the ZIP *before* anything is published.
* The candidate has to be on the main branch. A run from anywhere else stops,
  so what reaches users cannot come from somewhere that has never been on main.
  The exception is a trial release of version 0.0.0, see require_main_branch.

The order makes the flow atomic where it matters: everything happens inside a
draft, and `draft=false` is the last call. If anything fails before that, there
is no public release to clean up. Every step is idempotent, so a retry on the
same SHA picks up where it stopped: the tag is already right, the draft is
reused, an asset that is already uploaded is read back and compared rather than
replaced.

If the ZIP is there with the wrong sha256, we stop. We then do not know what is
in it, and HACS downloads exactly that file. Overwriting automatically would
turn one unclear state into another.

Subcommands:

    plan      read the state and say what would happen (reads only)
    build     build a deterministic ZIP from a SHA, print its sha256
    publish   run the state machine (`--dry-run` makes it a pure read)
    verify    check a published release against its own tag, and fail on drift

Locally:

    just release-zip     build the ZIP and see its sha256
    just release-plan    read the state on GitHub without writing anything
    just release-verify  check a release that is already out
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
import re
import subprocess
import sys
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

# The CHANGELOG rules live next door, and the release body is built from them.
# Imported rather than run as a subprocess, so the failures come out as
# exceptions with text we can pass on.
sys.path.insert(0, str(Path(__file__).resolve().parent))

import release_notes  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent
COMPONENT = "custom_components/onesti_lock"
ASSET_NAME = "onesti_lock.zip"

# Tracked component paths that are deliberately left out of the ZIP. Nothing
# Home Assistant loads imports the BLE stack yet, and `ble/client` carries the
# credential a factory-reset lock accepts as its owner. Packing it would put a
# working admin client for such a lock on every HACS user's disk for a feature
# that does not exist. The code stays in the repo and in the tag's source tree,
# so it is still public and reviewable; it just is not installed. Remove the
# entry in the same change that first imports it, which `packed_imports_excluded`
# makes impossible to forget. A name ending in "/" is a directory.
ZIP_EXCLUDE: tuple[str, ...] = ("ble/", "bluetooth.py")

# The workflow allowed to have signed the attestation. Verification is
# worthless without this: without it we accept an attestation made by any
# workflow in the repository.
SIGNER_WORKFLOW = ".github/workflows/release.yml"

# Fixed ZIP metadata. The timestamp is the ZIP format's zero point
# (1980-01-01), and permissions come from the git mode, not from the file
# system. Without this, two builds of the same content get different sha256
# sums because they ran at different times.
ZIP_TIME = (1980, 1, 1, 0, 0, 0)
ZIP_PERMISSIONS = {"100644": 0o644, "100755": 0o755}

SHA_RE = re.compile(r"^[0-9a-f]{40}$")
VERSION_RE = re.compile(r"^\d+\.\d+\.\d+$")

# The version a trial run must carry. The way around the main-branch guard is
# tied to this number, see require_main_branch. It is also the one version
# allowed to ship with an undated CHANGELOG section, so the number is kept in
# one place.
TRIAL_VERSION = release_notes.TRIAL_VERSION

# The first version this flow ships. Below it, HACS installed from the tag's
# source tree, and the ZIPs that hang on those releases were packed by hand from
# a working tree, with the `custom_components/onesti_lock/` prefix this flow does
# not use. They are neither the tag's tree nor attested, and neither can be
# fixed after the fact: an attestation is made by the workflow run that built the
# file. So below this version a missing or mismatched asset is reported, not
# blocking, or every push to main would go red over history nobody can change.
# `verify` still refuses to call those releases verified.
FIRST_ZIP_VERSION = (1, 4, 0)

EXIT_OK = 0
EXIT_FAILURE = 1
EXIT_STOP = 2


class Failure(Exception):
    """Something is wrong with the setup or the call. Exit 1."""


class Stop(Exception):
    """The state is unclear or in conflict. Exit 2, and nothing is written."""


# --------------------------------------------------------------------------
# git
# --------------------------------------------------------------------------


class Git:
    """A thin layer over `git`. Everything is read from the object database."""

    def __init__(self, root: Path) -> None:
        self.root = root

    def _run(self, argv: list[str]) -> subprocess.CompletedProcess[bytes]:
        return subprocess.run(
            ["git", "-C", str(self.root), *argv],
            capture_output=True,
            check=False,
        )

    def text(self, *argv: str) -> str:
        result = self._run(list(argv))
        if result.returncode != 0:
            raise Failure(f"git {' '.join(argv)} failed: {result.stderr.decode(errors='replace').strip()}")
        return result.stdout.decode().strip()

    def raw(self, *argv: str) -> bytes:
        result = self._run(list(argv))
        if result.returncode != 0:
            raise Failure(f"git {' '.join(argv)} failed: {result.stderr.decode(errors='replace').strip()}")
        return result.stdout


def full_sha(git: Git, ref: str) -> str:
    """Turn a ref into a full commit SHA, and require the commit locally.

    `^{commit}` dereferences an annotated tag. If the object is missing, the
    checkout is too shallow (`fetch-depth: 0` and tags are needed), and then we
    say so instead of building something other than what we think.
    """
    sha = git.text("rev-parse", "--verify", f"{ref}^{{commit}}")
    if not SHA_RE.match(sha):
        raise Failure(f"git did not give a full SHA for {ref!r}: {sha!r}")
    return sha


def read_version(git: Git, sha: str) -> str:
    """The manifest version as it stands *at that SHA*, not in the working tree."""
    raw = git.raw("show", f"{sha}:{COMPONENT}/manifest.json")
    try:
        manifest = json.loads(raw)
    except json.JSONDecodeError as err:
        raise Failure(f"manifest.json at {sha} is not valid JSON: {err}") from err
    version = manifest.get("version")
    if not isinstance(version, str) or not VERSION_RE.match(version):
        raise Failure(f"manifest.json at {sha} has an invalid version: {version!r}")
    return version


def is_excluded(name: str) -> bool:
    """Is this component-relative path one of the ZIP_EXCLUDE paths?"""
    return any(name == entry or (entry.endswith("/") and name.startswith(entry)) for entry in ZIP_EXCLUDE)


def excluded_modules() -> set[str]:
    """The top-level module names behind ZIP_EXCLUDE: ble/ -> ble, x.py -> x."""
    return {entry.rstrip("/").removesuffix(".py").split("/")[0] for entry in ZIP_EXCLUDE}


def packed_imports_excluded(git: Git, files: list[tuple[str, str, str]]) -> list[str]:
    """Packed modules that import something the ZIP leaves out, as "file:line".

    Excluding a directory is safe only as long as nothing that ships reaches
    for it: the ZIP would install a package that raises ImportError on the
    first setup, and no test in the repo would see it, because the repo has
    the files. Only relative imports count, since that is how the component
    imports itself; `from homeassistant.components import bluetooth` is
    someone else's module with the same name.
    """
    modules = excluded_modules()
    offenders: list[str] = []
    for _mode, blob, name in files:
        if not name.endswith(".py"):
            continue
        try:
            tree = ast.parse(git.raw("cat-file", "blob", blob))
        except SyntaxError as err:
            raise Failure(f"{name} does not parse as Python: {err}") from err
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.level:
                reached = {(node.module or "").split(".")[0]} | {alias.name for alias in node.names}
                if reached & modules:
                    offenders.append(f"{name}:{node.lineno}")
    return sorted(offenders)


def component_files(git: Git, sha: str) -> list[tuple[str, str, str]]:
    """(mode, blob sha, name inside the ZIP) for every tracked component file.

    The name is the path relative to the component directory, because HACS
    unpacks the ZIP straight into `custom_components/onesti_lock/` without
    stripping a prefix. The order is sorted, which is what `git ls-tree` gives
    anyway, but we sort explicitly so determinism does not rest on git's.

    ZIP_EXCLUDE is dropped here, so what the build sees is what users get.
    """
    raw = git.text("ls-tree", "-r", "-z", sha, "--", COMPONENT)
    files: list[tuple[str, str, str]] = []
    for entry in raw.split("\0"):
        if not entry:
            continue
        meta, _, path = entry.partition("\t")
        mode, kind, blob = meta.split()
        if kind != "blob":
            raise Failure(
                f"{path} at {sha} is a {kind}, not a regular file. "
                "Symlinks and submodules do not belong in a HACS ZIP."
            )
        if mode not in ZIP_PERMISSIONS:
            raise Failure(f"{path} has git mode {mode}, which cannot be packed deterministically")
        name = path[len(COMPONENT) + 1 :]
        if is_excluded(name):
            continue
        files.append((mode, blob, name))
    if not files:
        raise Failure(f"{COMPONENT} has no tracked files at {sha}")
    return sorted(files, key=lambda row: row[2])


def build_zip(git: Git, sha: str, target: Path) -> str:
    """Build the ZIP for a SHA and return its sha256.

    Determinism is the whole point: the same SHA gives a byte-identical file
    whatever the machine, clock, umask or the order the files happened to be
    in. Then anyone can rebuild the artifact and compare it with what HACS
    downloaded.
    """
    files = component_files(git, sha)
    reaching = packed_imports_excluded(git, files)
    if reaching:
        raise Failure(
            "the ZIP leaves out " + ", ".join(ZIP_EXCLUDE) + ", but " + ", ".join(reaching) + " imports it. "
            "Drop the path from ZIP_EXCLUDE, or the import."
        )
    target.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for mode, blob, name in files:
            info = zipfile.ZipInfo(name, ZIP_TIME)
            info.compress_type = zipfile.ZIP_DEFLATED
            # 3 = Unix. The permissions live in the upper 16 bits.
            info.create_system = 3
            info.external_attr = ZIP_PERMISSIONS[mode] << 16
            archive.writestr(info, git.raw("cat-file", "blob", blob))
    return sha256_of(target)


def sha256_of(path: Path) -> str:
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


# --------------------------------------------------------------------------
# gh
# --------------------------------------------------------------------------


class Gh:
    """A thin layer over `gh`, with a dry-run switch that blocks all writing."""

    def __init__(self, repo: str, *, dry_run: bool = False) -> None:
        self.repo = repo
        self.dry_run = dry_run

    def _run(self, argv: list[str], *, stdin: bytes | None = None) -> subprocess.CompletedProcess[bytes]:
        return subprocess.run(["gh", *argv], input=stdin, capture_output=True, check=False)

    def api(
        self,
        path: str,
        *,
        method: str = "GET",
        data: dict[str, Any] | None = None,
        file: Path | None = None,
        accept: str | None = None,
        paginate: bool = False,
        allow_404: bool = False,
    ) -> Any:
        """One API call. Returns parsed JSON, or None on an allowed 404."""
        if method != "GET" and self.dry_run:
            raise Failure(f"a dry run tried to write: {method} {path}")
        argv = ["api", "--method", method]
        if paginate:
            argv.append("--paginate")
        if accept:
            argv += ["-H", f"Accept: {accept}"]
        stdin: bytes | None = None
        if data is not None:
            argv += ["--input", "-"]
            stdin = json.dumps(data).encode()
        if file is not None:
            argv += ["--input", str(file), "-H", "Content-Type: application/zip"]
        argv.append(path)

        result = self._run(argv, stdin=stdin)
        if result.returncode != 0:
            message = result.stderr.decode(errors="replace").strip()
            if allow_404 and "HTTP 404" in message:
                return None
            raise Failure(f"gh api {method} {path} failed: {message}")
        if not result.stdout.strip():
            return None
        return json.loads(result.stdout)

    def raw(self, path: str, *, accept: str) -> bytes:
        result = self._run(["api", "-H", f"Accept: {accept}", path])
        if result.returncode != 0:
            raise Failure(f"gh api {path} failed: {result.stderr.decode(errors='replace').strip()}")
        return result.stdout

    def attestation(self, argv: list[str]) -> Any:
        result = self._run(["attestation", *argv])
        if result.returncode != 0:
            raise Stop("gh attestation verify failed:\n" + result.stderr.decode(errors="replace").strip())
        return json.loads(result.stdout)


# --------------------------------------------------------------------------
# Candidate and state
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class Candidate:
    """The three ends that together make up "this release"."""

    repo: str
    sha: str
    version: str

    @property
    def tag(self) -> str:
        return f"v{self.version}"

    def __str__(self) -> str:
        return f"{self.repo}@{self.sha[:12]} as {self.tag}"


def read_candidate(git: Git, repo: str, ref: str) -> Candidate:
    sha = full_sha(git, ref)
    return Candidate(repo=repo, sha=sha, version=read_version(git, sha))


def tag_sha(gh: Gh, candidate: Candidate) -> str | None:
    """The SHA the tag points at, or None if it does not exist.

    An annotated tag points at a tag object, not at the commit, so it has to be
    dereferenced. Without that, an annotated tag on the right commit would look
    like a tag on the wrong commit, and the flow would stop for no reason.
    """
    ref = gh.api(f"repos/{candidate.repo}/git/ref/tags/{candidate.tag}", allow_404=True)
    if ref is None:
        return None
    obj = ref["object"]
    if obj["type"] == "commit":
        return str(obj["sha"])
    if obj["type"] == "tag":
        tag_object = gh.api(f"repos/{candidate.repo}/git/tags/{obj['sha']}")
        return str(tag_object["object"]["sha"])
    raise Stop(f"{candidate.tag} points at a {obj['type']} object, which is not a commit")


def find_release(gh: Gh, candidate: Candidate) -> dict[str, Any] | None:
    """The release for the tag, draft or not.

    Looking a tag up (`releases/tags/...`) does not find drafts, and a draft is
    exactly the state we have to be able to resume. So all releases are listed.
    """
    releases = gh.api(f"repos/{candidate.repo}/releases", paginate=True) or []
    hits = [rel for rel in releases if rel.get("tag_name") == candidate.tag]
    if len(hits) > 1:
        raise Stop(
            f"{len(hits)} releases carry the tag {candidate.tag}. Clean up by hand; "
            "the flow does not know which one is the right one."
        )
    return hits[0] if hits else None


# --------------------------------------------------------------------------
# The main-branch guard
# --------------------------------------------------------------------------


def require_main_branch(gh: Gh, candidate: Candidate, *, trial: bool) -> None:
    """The candidate has to be on the main branch. Otherwise nothing ships.

    `workflow_dispatch` can be run from any branch, and without this guard a
    branch that has never been on main could become a public release. The check
    goes to GitHub and not to local refs: GitHub's main branch is the truth,
    and a local `origin/main` can be anything.

    The exception exists because a trial run against a throwaway tag needs a
    real workflow run to get an attestation. It is tied to version 0.0.0, so a
    dispatch on the wrong branch can never ship a real version even if someone
    ticks the wrong box.
    """
    if trial:
        if candidate.version != TRIAL_VERSION:
            raise Stop(
                f"a trial release only covers version {TRIAL_VERSION}, but the candidate is "
                f"{candidate.version}. Real versions ship from the main branch."
            )
        print(f"! Trial release: {candidate.tag} ships without the main-branch requirement.")
        return

    main = str((gh.api(f"repos/{candidate.repo}") or {}).get("default_branch") or "main")
    answer = gh.api(f"repos/{candidate.repo}/compare/{main}...{candidate.sha}", allow_404=True)
    if answer is None:
        raise Stop(
            f"GitHub does not know {candidate.sha[:12]}. If the commit was never pushed to {main}, "
            "there is nothing to release."
        )
    # `status` describes head against base: "identical" is the tip of the main
    # branch itself, "behind" is an older commit on it. "ahead" and "diverged"
    # mean there is something here that the main branch does not have.
    status = str(answer.get("status") or "unknown")
    if status not in {"identical", "behind"}:
        raise Stop(
            f"{candidate.sha[:12]} is not on {main} (status: {status}).\n"
            "What reaches users comes from the main branch. Merge it in first, "
            f"or run a trial release with manifest version {TRIAL_VERSION}."
        )
    print(f"OK Candidate is on {main} ({status}).")


# --------------------------------------------------------------------------
# Verification
# --------------------------------------------------------------------------


def verify_attestation(gh: Gh, candidate: Candidate, zip_path: Path, digest: str) -> None:
    """Require the attestation to cover this file, built from this SHA, here.

    `gh` does the cryptographic work. The flags bind it to repo, source SHA and
    signer workflow, and we read the subject digest out of the answer on top of
    that. The last part is not redundant: the flags say who signed, not that it
    was *this* ZIP they signed.
    """
    answer = gh.attestation(
        [
            "verify",
            str(zip_path),
            "--repo",
            candidate.repo,
            "--source-digest",
            candidate.sha,
            "--signer-workflow",
            f"{candidate.repo}/{SIGNER_WORKFLOW}",
            "--deny-self-hosted-runners",
            "--format",
            "json",
        ]
    )
    if not isinstance(answer, list) or not answer:
        raise Stop("gh attestation verify returned no attestations for the ZIP")

    digests = {
        subject.get("digest", {}).get("sha256")
        for entry in answer
        for subject in entry.get("verificationResult", {}).get("statement", {}).get("subject", [])
    }
    if digest not in digests:
        raise Stop(
            f"the attestation covers {sorted(d for d in digests if d)}, not the ZIP we built "
            f"({digest}). Tag, ZIP and attestation are then not the same artifact."
        )


def download_asset(gh: Gh, candidate: Candidate, asset: dict[str, Any], target: Path) -> str:
    """Read the asset back from GitHub and return the sha256 of what is there.

    We do not trust the upload to have reported the truth. `size` in the API
    answer is GitHub's own number; a truncated or swapped file only shows if we
    download it again and compute the digest ourselves.
    """
    content = gh.raw(
        f"repos/{candidate.repo}/releases/assets/{asset['id']}",
        accept="application/octet-stream",
    )
    target.write_bytes(content)
    return sha256_of(target)


# --------------------------------------------------------------------------
# Release body
# --------------------------------------------------------------------------


def release_note(version: str, repo_root: Path) -> str:
    """The short CHANGELOG note, through scripts/release_notes.py.

    The short cut is what users actually read: HACS shows the release body in a
    narrow panel inside Home Assistant, and a section of forty bullets gets
    scrolled past. The whole section stays in CHANGELOG.md, which the note
    links to.

    The date check runs here too, and not only in CI. `publish` is re-run and
    dispatched by hand, and then nothing else stands between a section that
    still says "Unreleased" and a release page telling every user that the
    version was never finished.
    """
    changelog = (repo_root / "CHANGELOG.md").read_text(encoding="utf-8")

    try:
        release_notes.require_release_date(changelog, version)
    except release_notes.UndatedError as err:
        raise Failure(
            f"{err}.\n"
            f"Put the release date in CHANGELOG.md before {version} ships: "
            f"'## [{version}] - YYYY-MM-DD'.\n"
            f"Only version {TRIAL_VERSION}, the trial release, ships with an undated section."
        ) from err

    try:
        body = release_notes.build_short_body(
            changelog,
            version,
            repo_root=repo_root,
            # History is not marked after the fact. If an old section ships
            # again, it gets its whole text rather than stopping the flow.
            strict=release_notes.is_in_progress(changelog, version),
        )
    except (
        release_notes.DeadLinkError,
        release_notes.EmptyActionError,
        release_notes.UnmarkedError,
    ) as err:
        raise Failure(f"the release note for {version} is not ready: {err}") from err
    if body is None:
        raise Failure(
            f"CHANGELOG.md has no section '## [{version}]' with content. "
            "The release note belongs in the repo before the version ships."
        )
    return body


def commits_since_previous(git: Git, candidate: Candidate) -> str:
    tags = [t for t in git.text("tag", "--sort=-version:refname").splitlines() if t != candidate.tag]
    span = f"{tags[0]}..{candidate.sha}" if tags else candidate.sha
    log = git.text("log", span, "--pretty=format:- %s", "--no-merges")
    return log or "- First release"


def build_body(git: Git, candidate: Candidate, digest: str, repo_root: Path) -> str:
    """The release body: the CHANGELOG note, plus the proof of what is in the ZIP.

    Both the SHA and the sha256 are in the text, so the binding between tag, ZIP
    and attestation can be read by a person on the release page, not only by
    `gh`.
    """
    url = f"https://github.com/{candidate.repo}"
    return "\n".join(
        [
            release_note(candidate.version, repo_root),
            "",
            "## Verification",
            "",
            f"Built from commit [`{candidate.sha[:12]}`]({url}/commit/{candidate.sha}), "
            f"the commit the tag `{candidate.tag}` points at.",
            "",
            f"**SHA256:** `{digest}` ([how to verify]({url}/blob/{candidate.tag}/SECURITY.md))",
            "",
            "<details>",
            "<summary>All commits</summary>",
            "",
            commits_since_previous(git, candidate),
            "",
            "</details>",
        ]
    )


def _version_numbers(version: str) -> tuple[int, ...]:
    return tuple(int(part) for part in version.split("."))


def should_be_latest(gh: Gh, candidate: Candidate) -> bool:
    """Explicit make_latest: only when the version is higher than the current one.

    GitHub's default is "newest published", which turns a patch on an old
    branch into "latest" and sends HACS users backwards. Here the choice is a
    number we can read. The trial version is never latest, whatever else is out.
    """
    if candidate.version == TRIAL_VERSION:
        return False
    latest = gh.api(f"repos/{candidate.repo}/releases/latest", allow_404=True)
    if latest is None:
        return True
    current = str(latest.get("tag_name", "")).lstrip("v")
    if not VERSION_RE.match(current):
        return True
    return _version_numbers(candidate.version) > _version_numbers(current)


# --------------------------------------------------------------------------
# The state machine
# --------------------------------------------------------------------------


def ensure_tag(gh: Gh, candidate: Candidate) -> str:
    """The tag points at the candidate SHA. It is created, or it already agrees.

    It is never moved. A tag that moves makes everything said about older
    releases untrue after the fact, and that is exactly what this flow is for.
    """
    existing = tag_sha(gh, candidate)
    if existing == candidate.sha:
        return "unchanged"
    if existing is not None:
        raise Stop(
            f"{candidate.tag} already points at {existing}, while the candidate is {candidate.sha}.\n"
            "The tag is not moved automatically. Either the version shipped from another commit, "
            "or this change goes out as a new version."
        )
    if gh.dry_run:
        return "would create"
    gh.api(
        f"repos/{candidate.repo}/git/refs",
        method="POST",
        data={"ref": f"refs/tags/{candidate.tag}", "sha": candidate.sha},
    )
    return "created"


def require_draft_on_candidate(candidate: Candidate, release: dict[str, Any]) -> None:
    """A draft belongs to one commit, and is not reused on another.

    The path: the tag was pushed on commit A, publishing failed, a person
    deleted the tag but left the draft. A new run on B with the same version
    would then tag B, reuse the draft from A, and publish a body saying "built
    from commit A, the commit the tag points at". The text is the only thing
    the user sees, and it would be false.

    The check runs before the tag is created, so a stop does not leave new
    writes to clean up. A draft made by hand in the browser points at a branch
    and not a commit; it also has no body from us to lie with, so it passes.
    """
    target = str(release.get("target_commitish") or "")
    if SHA_RE.match(target) and target != candidate.sha:
        raise Stop(
            f"the draft for {candidate.tag} was made for {target[:12]}, while the candidate is "
            f"{candidate.sha[:12]}.\n"
            "It is not reused on another commit: the body would describe something other than "
            "what is in the ZIP. Delete the draft, or ship this as a new version."
        )
    if target and not SHA_RE.match(target):
        print(
            f"! The draft points at '{target}' and not a commit, so it was not made by this "
            "flow. It is reused as it stands.",
            file=sys.stderr,
        )


def ensure_draft(
    gh: Gh, candidate: Candidate, release: dict[str, Any] | None, body: str
) -> tuple[dict[str, Any] | None, str]:
    """The draft exists afterwards, and one that already exists is not rewritten.

    A draft from an earlier attempt may have been edited by hand. Overwriting
    the body would throw that edit away without anyone asking for it. That the
    draft belongs to the candidate is already settled by
    require_draft_on_candidate.
    """
    if release is not None:
        if release.get("body", "") != body:
            print(
                "! The draft has a different body than CHANGELOG gives now. It is kept as it stands.",
                file=sys.stderr,
            )
        return release, "reused"
    if gh.dry_run:
        return None, "would create"
    created = gh.api(
        f"repos/{candidate.repo}/releases",
        method="POST",
        data={
            "tag_name": candidate.tag,
            "target_commitish": candidate.sha,
            "name": candidate.tag,
            "body": body,
            "draft": True,
            # A trial run must never look like a version anyone can install.
            "prerelease": candidate.version == TRIAL_VERSION,
        },
    )
    return created, "created"


def ensure_asset(
    gh: Gh, candidate: Candidate, release: dict[str, Any], zip_path: Path, digest: str, workdir: Path
) -> str:
    """The ZIP is on the release with the right sha256 afterwards, or we stop.

    An upload that fails after GitHub has taken the file is the common halfway
    state: the network dies on the answer, the job fails, and the next run sees
    an asset it knows nothing about. So it is always read back and recomputed
    before we conclude anything.
    """
    existing = [a for a in release.get("assets", []) if a.get("name") == ASSET_NAME]
    if existing:
        loaded = download_asset(gh, candidate, existing[0], workdir / "readback.zip")
        if loaded == digest:
            return "already in place, digest agrees"
        raise Stop(
            f"{ASSET_NAME} on {candidate.tag} has sha256 {loaded}, but the build gives {digest}.\n"
            "The file is not swapped automatically: HACS installs exactly that one, and we do not "
            "know what it holds. Delete the asset deliberately, or ship a new version."
        )

    if gh.dry_run:
        return "would upload"

    url = f"https://uploads.github.com/repos/{candidate.repo}/releases/{release['id']}/assets?name={ASSET_NAME}"
    try:
        gh.api(url, method="POST", file=zip_path)
    except Failure as err:
        # It may have arrived anyway. Read back rather than guess.
        print(f"! The upload failed ({err}). Reading back to see whether it arrived.", file=sys.stderr)

    updated = gh.api(f"repos/{candidate.repo}/releases/{release['id']}")
    after = [a for a in updated.get("assets", []) if a.get("name") == ASSET_NAME]
    if not after:
        raise Failure(f"{ASSET_NAME} was not uploaded to {candidate.tag}")
    loaded = download_asset(gh, candidate, after[0], workdir / "readback.zip")
    if loaded != digest:
        raise Stop(
            f"{ASSET_NAME} was uploaded, but reads back as {loaded} and not {digest}. "
            "Do not publish this."
        )
    return "uploaded and read back"


@dataclass(frozen=True)
class Check:
    """One link in the proof that a published release hangs together."""

    name: str
    ok: bool
    message: str
    blocking: bool = False

    def __str__(self) -> str:
        return f"{'OK' if self.ok else '!'} {self.name}: {self.message}"


def _unpack(path: Path) -> dict[str, bytes]:
    """File name to content. Directory entries are skipped.

    `zip -r` adds its own entry for every directory. We do not, because they
    are not content. Without this, every older release would look as if it held
    something other than the tag.
    """
    with zipfile.ZipFile(path) as archive:
        return {
            info.filename: archive.read(info)
            for info in sorted(archive.infolist(), key=lambda i: i.filename)
            if not info.is_dir()
        }


def check_published(
    gh: Gh, git: Git, candidate: Candidate, release: dict[str, Any], workdir: Path
) -> list[Check]:
    """Prove a published version against its own tag, not against today's main.

    After a release, main keeps moving with an unchanged manifest version, so
    this flow runs again on a different SHA. That is no conflict, but it is no
    reason to skip without looking either. We rebuild the ZIP from the tag's own
    commit and compare.

    From FIRST_ZIP_VERSION on, the content check is the blocking one: if the
    files in the ZIP do not match the tree the tag points at, users install code
    that is not in the tag, and that is an alarm. The other two are reporting. A
    release that is already out does not get better from every push to main
    going red afterwards, and releases made before this flow cannot be
    byte-identical: they were packed with `zip -r` from the working tree, so
    timestamps and permissions came from the runner.

    Below FIRST_ZIP_VERSION nothing blocks. `verify` is the command that looks
    at those, and it still fails on them.
    """
    sha = tag_sha(gh, candidate)
    if sha is None:
        return [
            Check("tag", False, f"{candidate.tag} does not exist, so the release cannot be proved against a commit")
        ]
    checks = [Check("tag", True, f"{candidate.tag} points at {sha[:12]}")]
    predates_zip = _version_numbers(candidate.version) < FIRST_ZIP_VERSION

    existing = [a for a in release.get("assets", []) if a.get("name") == ASSET_NAME]
    if not existing:
        checks.append(
            Check(
                "content",
                False,
                f"{candidate.tag} shipped before this flow, so it has no {ASSET_NAME} to check. "
                "HACS installs it from the tag's source tree, and nothing can be attested after the fact."
                if predates_zip
                else f"the release is missing {ASSET_NAME}, so HACS has nothing to fetch. "
                "Repair it deliberately, or ship a new version.",
                blocking=not predates_zip,
            )
        )
        return checks

    from_tag = workdir / "from-tag.zip"
    published = workdir / "published.zip"
    expected_digest = build_zip(git, sha, from_tag)
    actual_digest = download_asset(gh, candidate, existing[0], published)

    if actual_digest == expected_digest:
        checks.append(Check("content", True, f"byte-identical to a fresh build of {sha[:12]} ({actual_digest})"))
    else:
        reference, shipped = _unpack(from_tag), _unpack(published)
        if reference == shipped:
            checks.append(
                Check(
                    "content",
                    True,
                    f"the files are the same as in {sha[:12]}, but the ZIP is not byte-identical "
                    "(packed before the flow became deterministic)",
                )
            )
        else:
            drift = sorted(set(reference) ^ set(shipped)) or [
                name for name in reference if reference[name] != shipped.get(name)
            ]
            checks.append(
                Check(
                    "content",
                    False,
                    f"the ZIP on {candidate.tag} was packed by hand before this flow and is not the "
                    f"code the tag points at. Drift: {', '.join(drift[:5])}"
                    if predates_zip
                    else f"the ZIP is not the code the tag points at. Drift: {', '.join(drift[:5])}",
                    blocking=not predates_zip,
                )
            )
            return checks

    of_the_tag = Candidate(repo=candidate.repo, sha=sha, version=candidate.version)
    try:
        verify_attestation(gh, of_the_tag, published, actual_digest)
    except Stop as err:
        checks.append(Check("attestation", False, str(err).replace("\n", " ")))
    else:
        checks.append(Check("attestation", True, f"covers the ZIP and source commit {sha[:12]}"))
    return checks


def run(
    *,
    git: Git,
    gh: Gh,
    candidate: Candidate,
    workdir: Path,
    repo_root: Path,
    zip_path: Path | None,
    plan_only: bool,
    require_attestation: bool,
    strict: bool = False,
    trial: bool = False,
) -> int:
    """The state machine itself. Publishing is the last call, always."""
    print(f"Candidate: {candidate}")
    release = find_release(gh, candidate)

    if strict and (release is None or release.get("draft", False)):
        raise Stop(
            f"{candidate.tag} is not published ({'it is a draft' if release else 'it does not exist'}), "
            "so there is nothing to check."
        )

    if release is not None and not release.get("draft", False):
        print(f"{candidate.tag} is already published. Proving it against its own tag.")
        checks = check_published(gh, git, candidate, release, workdir)
        for check in checks:
            print(f"  {check}")
        worse = [c for c in checks if not c.ok and (c.blocking or strict)]
        if worse:
            raise Stop(
                f"{candidate.tag} is published, but does not hang together:\n  "
                + "\n  ".join(c.message for c in worse)
            )
        if any(not c.ok for c in checks):
            print(f"! {candidate.tag} stays out as it is. Run `verify` for the whole picture.")
        print(f"Nothing to do for {candidate.version}.")
        write_outcome(outcome="noop", version=candidate.version, tag=candidate.tag, sha=candidate.sha)
        return EXIT_OK

    # The guard stands here and not further up on purpose: a version that is
    # already out is proved against its own tag, and that commit does not have
    # to be on the main branch today. Only the path to a *new* release is
    # blocked.
    require_main_branch(gh, candidate, trial=trial)
    if release is not None:
        require_draft_on_candidate(candidate, release)

    write_outcome(outcome="ready", version=candidate.version, tag=candidate.tag, sha=candidate.sha)

    if zip_path is None:
        zip_path = workdir / ASSET_NAME
        digest = build_zip(git, candidate.sha, zip_path)
    else:
        digest = sha256_of(zip_path)
        expected = build_zip(git, candidate.sha, workdir / "control.zip")
        if digest != expected:
            raise Stop(
                f"the ZIP that was handed over has sha256 {digest}, but a fresh build of "
                f"{candidate.sha[:12]} gives {expected}. Then the file is not built from the candidate."
            )
    print(f"ZIP: {digest}")

    if require_attestation:
        verify_attestation(gh, candidate, zip_path, digest)
        print("OK The attestation covers this ZIP, built from the candidate SHA by release.yml")
    else:
        print("- Skipping the attestation check: `plan` runs before the ZIP is attested.")

    body = build_body(git, candidate, digest, repo_root)
    latest = should_be_latest(gh, candidate)

    if plan_only:
        print(f"Tag: {ensure_tag(gh, candidate)}")
        print(f"Draft: {'reused' if release else 'created'}")
        assets = [a.get("name") for a in (release or {}).get("assets", [])]
        print(f"Asset: {'already there' if ASSET_NAME in assets else 'uploaded'}")
        print(f"make_latest: {str(latest).lower()}")
        print("Dry run: nothing was written.")
        return EXIT_OK

    print(f"Tag {candidate.tag} on {candidate.sha[:12]}: {ensure_tag(gh, candidate)}")
    release, what = ensure_draft(gh, candidate, release, body)
    print(f"Draft: {what}")
    assert release is not None
    print(f"Asset: {ensure_asset(gh, candidate, release, zip_path, digest, workdir)}")

    gh.api(
        f"repos/{candidate.repo}/releases/{release['id']}",
        method="PATCH",
        data={"draft": False, "make_latest": str(latest).lower()},
    )
    print(f"OK Published {candidate.tag} (make_latest={str(latest).lower()})")
    return EXIT_OK


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------


def write_outcome(**fields: str) -> None:
    """Put the outcome in $GITHUB_OUTPUT when we run in Actions.

    The workflow has to tell "already published" from "ready to ship" without
    reading the log text, or we end up with a grep against prose deciding
    whether a release goes out.
    """
    path = os.environ.get("GITHUB_OUTPUT")
    if not path:
        return
    with open(path, "a", encoding="utf-8") as out:
        for name, value in fields.items():
            out.write(f"{name}={value}\n")


def default_repo() -> str:
    return os.environ.get("GITHUB_REPOSITORY", "fredrik-lindseth/onesti-lock")


def make_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT, help="the git root (default: this repo)")
    sub = parser.add_subparsers(dest="command", required=True)

    build = sub.add_parser("build", help="build a deterministic ZIP from a SHA")
    build.add_argument("--sha", default="HEAD", help="the commit the ZIP is built from (default: HEAD)")
    build.add_argument("--output", type=Path, default=Path("dist") / ASSET_NAME)

    for name, help_text in (
        ("plan", "read the state, write nothing"),
        ("verify", "check a published release against its own tag"),
        ("publish", "run the flow"),
    ):
        command = sub.add_parser(name, help=help_text)
        command.add_argument("--sha", default="HEAD")
        command.add_argument("--repo", default=default_repo())
        command.add_argument("--zip", type=Path, default=None, help="a prebuilt ZIP (checked against the SHA)")
        command.add_argument("--workdir", type=Path, default=None)
        if name in {"plan", "publish"}:
            command.add_argument(
                "--trial-release",
                action="store_true",
                help=f"a trial run outside the main branch, requires manifest version {TRIAL_VERSION}",
            )
        if name == "publish":
            command.add_argument("--dry-run", action="store_true", help="like plan: reads, does not write")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = make_parser().parse_args(argv)
    repo_root = args.repo_root.resolve()
    git = Git(repo_root)

    try:
        if args.command == "build":
            digest = build_zip(git, full_sha(git, args.sha), args.output)
            print(digest)
            return EXIT_OK

        plan_only = args.command in {"plan", "verify"} or getattr(args, "dry_run", False)
        # `plan` runs before the attestation exists (locally, or before the
        # build step). `publish --dry-run` runs where it should exist, and must
        # fail if it does not.
        require_attestation = args.command != "plan"
        workdir = args.workdir or repo_root / "dist"
        workdir.mkdir(parents=True, exist_ok=True)
        return run(
            git=git,
            gh=Gh(args.repo, dry_run=plan_only),
            candidate=read_candidate(git, args.repo, args.sha),
            workdir=workdir,
            repo_root=repo_root,
            zip_path=args.zip,
            plan_only=plan_only,
            require_attestation=require_attestation,
            strict=args.command == "verify",
            trial=getattr(args, "trial_release", False),
        )
    except Stop as err:
        print(f"STOP: {err}", file=sys.stderr)
        return EXIT_STOP
    except Failure as err:
        print(f"FAILED: {err}", file=sys.stderr)
        return EXIT_FAILURE


if __name__ == "__main__":
    sys.exit(main())
