"""The release flow: that tag, ZIP and attestation are the same artifact, and
that a broken attempt can be run again without leaving half a release behind.

The setup is deliberately not a carousel of mocks. `gh` is replaced with
`tests/fake_gh.py`, a small GitHub stand-in that *remembers* state between
calls, so a break can leave exactly the halfway state the next run has to clean
up. `git`, on the other hand, is real, and runs against a fresh repo in
tmp_path: those are the git objects the ZIP is built from, and a stub of them
would prove that the stub is deterministic, not that the build is.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

import release_publish  # noqa: E402

REPO_NAME = "owner/onesti-lock"
VERSION = "9.9.9"
TAG = f"v{VERSION}"

CHANGELOG = f"""# Changelog

## [{VERSION}]

### Bug fixes

- One thing, with [a link](docs/something.md) <!--short-->
- A detail that only belongs in the full log
"""

COMPONENT = "custom_components/onesti_lock"


# --------------------------------------------------------------------------
# Fixtures
# --------------------------------------------------------------------------


def _git(root: Path, *argv: str) -> str:
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "Test",
        "GIT_AUTHOR_EMAIL": "test@example.invalid",
        "GIT_COMMITTER_NAME": "Test",
        "GIT_COMMITTER_EMAIL": "test@example.invalid",
        "GIT_CONFIG_GLOBAL": str(root / ".gitconfig-empty"),
        "GIT_CONFIG_SYSTEM": str(root / ".gitconfig-empty"),
    }
    result = subprocess.run(
        ["git", "-C", str(root), *argv], capture_output=True, text=True, check=True, env=env
    )
    return result.stdout.strip()


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A real little git repo with the component, CHANGELOG and the linked file."""
    root = tmp_path / "repo"
    (root / COMPONENT / "translations").mkdir(parents=True)
    (root / "docs").mkdir()
    (root / COMPONENT / "manifest.json").write_text(
        json.dumps({"domain": "onesti_lock", "version": VERSION}) + "\n"
    )
    (root / COMPONENT / "__init__.py").write_text("# the integration\n")
    (root / COMPONENT / "sensor.py").write_text("SENSOR = 1\n")
    (root / COMPONENT / "translations" / "nb.json").write_text('{"title": "Onesti Lock"}\n')
    (root / "docs" / "something.md").write_text("# Something\n")
    (root / "CHANGELOG.md").write_text(CHANGELOG)
    (root / "README.md").write_text("not part of the zip\n")
    _git(root, "init", "-q", "-b", "main")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "everything")
    return root


@pytest.fixture
def sha(repo: Path) -> str:
    return _git(repo, "rev-parse", "HEAD")


class FakeGitHub:
    """The state the fake GitHub holds, seen from the test."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def read(self) -> dict:
        return json.loads(self.path.read_text())

    def write(self, state: dict) -> None:
        self.path.write_text(json.dumps(state, indent=1))

    @property
    def releases(self) -> list[dict]:
        return self.read()["releases"]

    def release(self, tag: str = TAG) -> dict | None:
        return next((r for r in self.releases if r["tag_name"] == tag), None)

    def asset_content(self, tag: str = TAG) -> bytes:
        release = self.release(tag)
        assert release is not None
        (asset,) = release["assets"]
        return bytes.fromhex(self.read()["assets"][asset["id"]])

    def tag(self, tag: str = TAG) -> dict | None:
        return self.read()["tags"].get(tag)

    def set_tag(self, tag: str, sha: str) -> None:
        state = self.read()
        state["tags"][tag] = {"type": "commit", "sha": sha}
        self.write(state)

    def attest(self, digest: str, sha: str, workflow: str | None = None) -> None:
        state = self.read()
        state["attestations"].append(
            {
                "digest": digest,
                "sha": sha,
                "repo": REPO_NAME,
                "workflow": workflow or f"{REPO_NAME}/{release_publish.SIGNER_WORKFLOW}",
            }
        )
        self.write(state)

    def calls(self, pattern: str) -> list[str]:
        return [c for c in self.read()["calls"] if re.search(pattern, c)]


@pytest.fixture
def github(repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> FakeGitHub:
    """Put a `gh` on PATH that talks to a state file we can look into."""
    state = tmp_path / "github.json"
    state.write_text(
        json.dumps(
            {
                "repo": REPO_NAME,
                "tags": {},
                "annotated": {},
                "releases": [],
                "assets": {},
                "attestations": [],
                "next_id": 100,
                "calls": [],
            }
        )
    )
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    shim = bin_dir / "gh"
    shim.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{REPO / "tests" / "fake_gh.py"}" "$@"\n')
    shim.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setenv("GH_STATE", str(state))
    # The main-branch guard asks GitHub whether the commit is on main. The
    # stand-in works that out with real git, against this repo.
    monkeypatch.setenv("GH_REPO_ROOT", str(repo))
    monkeypatch.delenv("GH_FAILURES", raising=False)
    monkeypatch.delenv("GITHUB_OUTPUT", raising=False)
    return FakeGitHub(state)


def run(repo: Path, *argv: str) -> int:
    return release_publish.main(["--repo-root", str(repo), *argv])


def publish(repo: Path, sha: str, *extra: str) -> int:
    return run(repo, "publish", "--sha", sha, "--repo", REPO_NAME, *extra)


def build(repo: Path, sha: str, target: Path) -> str:
    return release_publish.build_zip(release_publish.Git(repo), sha, target)


@pytest.fixture
def attested(repo: Path, sha: str, github: FakeGitHub, tmp_path: Path) -> str:
    """The digest for the candidate, with a valid attestation registered."""
    digest = build(repo, sha, tmp_path / "beforehand.zip")
    github.attest(digest, sha)
    return digest


# --------------------------------------------------------------------------
# Deterministic build
# --------------------------------------------------------------------------


def test_two_independent_builds_give_a_byte_identical_zip(repo: Path, sha: str, tmp_path: Path) -> None:
    """Without this, "the same artifact" is a claim nobody can check."""
    first = tmp_path / "one" / "onesti_lock.zip"
    second = tmp_path / "two" / "onesti_lock.zip"
    assert build(repo, sha, first) == build(repo, sha, second)
    assert first.read_bytes() == second.read_bytes()


def test_the_build_takes_only_tracked_component_files(repo: Path, sha: str, tmp_path: Path) -> None:
    """Untracked junk in the working tree must not be able to reach users."""
    (repo / COMPONENT / "secret.txt").write_text("untracked\n")
    (repo / COMPONENT / "__pycache__").mkdir()
    (repo / COMPONENT / "__pycache__" / "x.pyc").write_bytes(b"\x00")

    target = tmp_path / "onesti_lock.zip"
    build(repo, sha, target)
    with zipfile.ZipFile(target) as archive:
        names = sorted(archive.namelist())
        times = {info.date_time for info in archive.infolist()}
        permissions = {info.external_attr >> 16 for info in archive.infolist()}

    assert names == ["__init__.py", "manifest.json", "sensor.py", "translations/nb.json"]
    assert "README.md" not in names, "the ZIP is packed flat from the component directory"
    assert times == {release_publish.ZIP_TIME[:6]}
    assert permissions == {0o644}


def test_the_build_follows_the_sha_and_not_the_working_tree(repo: Path, sha: str, tmp_path: Path) -> None:
    """Uncommitted changes do not belong to the candidate."""
    reference = build(repo, sha, tmp_path / "reference.zip")
    (repo / COMPONENT / "sensor.py").write_text("SENSOR = 'changed without a commit'\n")
    assert build(repo, sha, tmp_path / "afterwards.zip") == reference


# --------------------------------------------------------------------------
# A fresh publish
# --------------------------------------------------------------------------


def test_a_fresh_publish_binds_tag_zip_and_attestation(
    repo: Path, sha: str, github: FakeGitHub, attested: str
) -> None:
    assert publish(repo, sha) == release_publish.EXIT_OK

    assert github.tag() == {"type": "commit", "sha": sha}
    release = github.release()
    assert release is not None
    assert release["draft"] is False
    assert release["target_commitish"] == sha
    assert hashlib.sha256(github.asset_content()).hexdigest() == attested
    assert sha[:12] in release["body"], "the SHA belongs in the note, not only in the log"
    assert attested in release["body"]
    assert "One thing" in release["body"], "the CHANGELOG section is the body"
    assert "<!--short-->" not in release["body"], "the marker must not go out"
    assert "A detail" not in release["body"], "the body is the short note, not the whole section"


def test_without_an_attestation_nothing_is_published(repo: Path, sha: str, github: FakeGitHub) -> None:
    """No attestation, no release. And no draft or tag to clean up."""
    assert publish(repo, sha) == release_publish.EXIT_STOP
    assert github.releases == []
    assert github.tag() is None


def test_an_attestation_on_another_commit_stops(
    repo: Path, sha: str, github: FakeGitHub, tmp_path: Path
) -> None:
    """Exactly the failure the flow exists for: the ZIP is built from another commit."""
    digest = build(repo, sha, tmp_path / "z.zip")
    github.attest(digest, sha="0" * 40)
    assert publish(repo, sha) == release_publish.EXIT_STOP
    assert github.releases == []


def test_an_attestation_from_the_wrong_workflow_stops(
    repo: Path, sha: str, github: FakeGitHub, tmp_path: Path
) -> None:
    digest = build(repo, sha, tmp_path / "z.zip")
    github.attest(digest, sha, workflow=f"{REPO_NAME}/.github/workflows/something-else.yml")
    assert publish(repo, sha) == release_publish.EXIT_STOP
    assert github.releases == []


def test_a_zip_not_built_from_the_candidate_stops(
    repo: Path, sha: str, github: FakeGitHub, attested: str, tmp_path: Path
) -> None:
    """`--zip` hands over a finished file. It is checked against a fresh build."""
    foreign = tmp_path / "foreign.zip"
    with zipfile.ZipFile(foreign, "w") as archive:
        archive.writestr("__init__.py", "something else")
    assert publish(repo, sha, "--zip", str(foreign)) == release_publish.EXIT_STOP
    assert github.releases == []


# --------------------------------------------------------------------------
# Resuming
# --------------------------------------------------------------------------


def test_resume_after_a_broken_upload_does_not_swap_the_right_asset(
    repo: Path, sha: str, github: FakeGitHub, attested: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The file arrived, the answer did not. The next run sees that instead of uploading again."""
    monkeypatch.setenv("GH_FAILURES", "upload_after_store,publish")
    assert publish(repo, sha) != release_publish.EXIT_OK

    halfway = github.release()
    assert halfway is not None and halfway["draft"] is True, "no public release after a break"
    (asset,) = halfway["assets"]

    monkeypatch.delenv("GH_FAILURES")
    uploads_before = len(github.calls("uploads.github.com"))
    assert publish(repo, sha) == release_publish.EXIT_OK

    done = github.release()
    assert done is not None
    assert done["draft"] is False
    assert [a["id"] for a in done["assets"]] == [asset["id"]], "the correct asset was swapped"
    assert len(github.calls("uploads.github.com")) == uploads_before, "uploaded again for nothing"
    assert hashlib.sha256(github.asset_content()).hexdigest() == attested


def test_resume_after_a_failed_publish(
    repo: Path, sha: str, github: FakeGitHub, attested: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GH_FAILURES", "publish")
    assert publish(repo, sha) == release_publish.EXIT_FAILURE
    assert github.release()["draft"] is True

    monkeypatch.delenv("GH_FAILURES")
    assert publish(repo, sha) == release_publish.EXIT_OK
    assert github.release()["draft"] is False
    assert len(github.releases) == 1, "the resume made a second release"


def test_resume_reuses_the_draft_and_does_not_overwrite_the_body(
    repo: Path, sha: str, github: FakeGitHub, attested: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A draft may have been edited by hand. Resuming is no reason to throw that away."""
    monkeypatch.setenv("GH_FAILURES", "publish")
    publish(repo, sha)
    state = github.read()
    state["releases"][0]["body"] = "edited by hand"
    github.write(state)

    monkeypatch.delenv("GH_FAILURES")
    assert publish(repo, sha) == release_publish.EXIT_OK
    assert github.release()["body"] == "edited by hand"


def test_a_corrupt_upload_stops_before_publishing(
    repo: Path, sha: str, github: FakeGitHub, attested: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GH_FAILURES", "upload_corrupt")
    assert publish(repo, sha) == release_publish.EXIT_STOP
    assert github.release()["draft"] is True, "a corrupt ZIP was published"


def test_an_asset_with_another_digest_is_not_swapped_automatically(
    repo: Path, sha: str, github: FakeGitHub, attested: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """HACS installs exactly this file. We do not know what it is, so we stop."""
    monkeypatch.setenv("GH_FAILURES", "upload_corrupt")
    publish(repo, sha)
    previous = github.asset_content()

    monkeypatch.delenv("GH_FAILURES")
    assert publish(repo, sha) == release_publish.EXIT_STOP
    assert github.asset_content() == previous, "the unknown asset was overwritten"
    assert github.release()["draft"] is True


# --------------------------------------------------------------------------
# Tags
# --------------------------------------------------------------------------


def test_a_tag_on_another_sha_stops_and_is_not_moved(
    repo: Path, sha: str, github: FakeGitHub, attested: str
) -> None:
    github.set_tag(TAG, "1" * 40)
    assert publish(repo, sha) == release_publish.EXIT_STOP
    assert github.tag()["sha"] == "1" * 40, "the tag was moved"
    assert github.releases == []


def test_a_tag_from_the_previous_attempt_is_reused(
    repo: Path, sha: str, github: FakeGitHub, attested: str
) -> None:
    """The job failed after the tag was pushed. It is right, and it stays."""
    github.set_tag(TAG, sha)
    assert publish(repo, sha) == release_publish.EXIT_OK
    assert github.calls("POST repos/.*/git/refs") == [], "tried to create a tag that existed"


def test_an_annotated_tag_is_dereferenced(repo: Path, sha: str, github: FakeGitHub, attested: str) -> None:
    """An annotated tag points at a tag object. Without dereferencing it looks wrong."""
    state = github.read()
    state["tags"][TAG] = {"type": "tag", "sha": "abc123"}
    state["annotated"]["abc123"] = sha
    github.write(state)
    assert publish(repo, sha) == release_publish.EXIT_OK


# --------------------------------------------------------------------------
# Already published
# --------------------------------------------------------------------------


def test_a_published_version_is_a_verified_noop(
    repo: Path, sha: str, github: FakeGitHub, attested: str, capsys: pytest.CaptureFixture[str]
) -> None:
    assert publish(repo, sha) == release_publish.EXIT_OK
    capsys.readouterr()

    # Main moves on with an unchanged manifest version. New commit, same version.
    (repo / "README.md").write_text("something new\n")
    _git(repo, "commit", "-qam", "afterwards")
    new_sha = _git(repo, "rev-parse", "HEAD")

    assert publish(repo, new_sha) == release_publish.EXIT_OK
    out = capsys.readouterr().out
    assert "Nothing to do" in out
    assert "content" in out and "tag" in out
    assert len(github.releases) == 1


def test_a_published_release_without_a_zip_stops(
    repo: Path, sha: str, github: FakeGitHub, attested: str
) -> None:
    """HACS has nothing to fetch. That must not pass quietly."""
    publish(repo, sha)
    state = github.read()
    state["releases"][0]["assets"] = []
    github.write(state)
    assert publish(repo, sha) == release_publish.EXIT_STOP


def test_a_published_zip_with_the_wrong_content_stops(
    repo: Path, sha: str, github: FakeGitHub, attested: str
) -> None:
    publish(repo, sha)
    state = github.read()
    (asset,) = state["releases"][0]["assets"]
    state["assets"][asset["id"]] = _other_zip().hex()
    github.write(state)
    assert publish(repo, sha) == release_publish.EXIT_STOP


def _publish_old_release(github: FakeGitHub, sha: str, version: str, asset: bytes | None) -> None:
    """A release from before this flow: tagged, published, and maybe a stale ZIP."""
    github.set_tag(f"v{version}", sha)
    state = github.read()
    release = {
        "id": "5",
        "tag_name": f"v{version}",
        "draft": False,
        "assets": [],
        "body": "",
        "prerelease": False,
    }
    if asset is not None:
        state["assets"]["55"] = asset.hex()
        release["assets"] = [{"id": "55", "name": release_publish.ASSET_NAME}]
    state["releases"].append(release)
    github.write(state)


@pytest.mark.parametrize("asset", [None, b"stale"], ids=["no asset", "stale asset"])
def test_a_release_from_before_this_flow_is_reported_not_blocking(
    repo: Path, sha: str, github: FakeGitHub, capsys: pytest.CaptureFixture[str], asset: bytes | None
) -> None:
    """Every 1.x release before this flow carries a hand-packed ZIP, or none.

    Neither can be rebuilt or attested after the fact, so they must not turn
    every push to main red. `verify` must still refuse to call them verified.
    """
    old = _side_branch(repo, version="1.0.0")
    _publish_old_release(github, old, "1.0.0", _prefixed_zip() if asset else None)

    assert publish(repo, old) == release_publish.EXIT_OK
    assert "before this flow" in capsys.readouterr().out
    assert run(repo, "verify", "--sha", old, "--repo", REPO_NAME) == release_publish.EXIT_STOP


def test_a_stale_zip_on_a_version_this_flow_owns_still_blocks(
    repo: Path, sha: str, github: FakeGitHub
) -> None:
    """The softening is tied to the version, not to "it looks old"."""
    _publish_old_release(github, sha, VERSION, _prefixed_zip())
    assert publish(repo, sha) == release_publish.EXIT_STOP


def _prefixed_zip() -> bytes:
    """A ZIP packed the old way: `zip -r` over the component path, prefix and all."""
    import io

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(f"{COMPONENT}/", "")
        archive.writestr(f"{COMPONENT}/__init__.py", "# the integration\n")
    return buffer.getvalue()


def _other_zip() -> bytes:
    import io

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("__init__.py", "something else entirely")
    return buffer.getvalue()


def test_verify_fails_where_plan_only_warns(
    repo: Path, sha: str, github: FakeGitHub, attested: str
) -> None:
    """Older releases cannot be byte-identical. Main should not go red from them,
    but `verify` must still say so."""
    publish(repo, sha)
    state = github.read()
    state["attestations"] = []
    github.write(state)

    assert run(repo, "plan", "--sha", sha, "--repo", REPO_NAME) == release_publish.EXIT_OK
    assert run(repo, "verify", "--sha", sha, "--repo", REPO_NAME) == release_publish.EXIT_STOP


def test_verify_on_something_unreleased_stops(
    repo: Path, sha: str, github: FakeGitHub, attested: str
) -> None:
    assert run(repo, "verify", "--sha", sha, "--repo", REPO_NAME) == release_publish.EXIT_STOP


# --------------------------------------------------------------------------
# Dry run and outcome
# --------------------------------------------------------------------------


def test_a_dry_run_writes_nothing(repo: Path, sha: str, github: FakeGitHub, attested: str) -> None:
    assert publish(repo, sha, "--dry-run") == release_publish.EXIT_OK
    assert github.releases == []
    assert github.tag() is None
    assert [c for c in github.read()["calls"] if c.startswith(("POST", "PATCH", "DELETE"))] == []


def test_plan_reports_the_outcome_machine_readably(
    repo: Path,
    sha: str,
    github: FakeGitHub,
    attested: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The workflow must not have to grep prose to know whether to build."""
    out_file = tmp_path / "github_output"
    monkeypatch.setenv("GITHUB_OUTPUT", str(out_file))

    assert run(repo, "plan", "--sha", sha, "--repo", REPO_NAME) == release_publish.EXIT_OK
    assert "outcome=ready\n" in out_file.read_text()

    publish(repo, sha)
    out_file.write_text("")
    assert run(repo, "plan", "--sha", sha, "--repo", REPO_NAME) == release_publish.EXIT_OK
    assert "outcome=noop\n" in out_file.read_text()


def test_make_latest_is_set_explicitly(repo: Path, sha: str, github: FakeGitHub, attested: str) -> None:
    """GitHub's default turns an old patch into "latest". The choice is ours."""
    state = github.read()
    state["releases"].append({"id": "1", "tag_name": "v99.0.0", "draft": False, "assets": [], "body": ""})
    github.write(state)

    assert publish(repo, sha) == release_publish.EXIT_OK
    assert github.release()["make_latest"] == "false"


# --------------------------------------------------------------------------
# The main branch
# --------------------------------------------------------------------------


def _side_branch(repo: Path, name: str = "side", version: str = VERSION) -> str:
    """A commit that has never been on main. The working tree stays there."""
    _git(repo, "checkout", "-qb", name)
    (repo / COMPONENT / "sensor.py").write_text("SENSOR = 'from a branch'\n")
    if version != VERSION:
        (repo / COMPONENT / "manifest.json").write_text(
            json.dumps({"domain": "onesti_lock", "version": version}) + "\n"
        )
        (repo / "CHANGELOG.md").write_text(CHANGELOG.replace(VERSION, version))
    _git(repo, "commit", "-qam", "something on a branch")
    return _git(repo, "rev-parse", "HEAD")


def test_a_commit_outside_the_main_branch_is_not_released(
    repo: Path, sha: str, github: FakeGitHub
) -> None:
    """workflow_dispatch can run anywhere. What goes out comes from main."""
    side = _side_branch(repo)
    digest = build(repo, side, repo / "dist" / "branch.zip")
    github.attest(digest, side)

    assert publish(repo, side) == release_publish.EXIT_STOP
    assert github.releases == []
    assert github.tag() is None


def test_plan_also_stops_outside_the_main_branch(repo: Path, sha: str, github: FakeGitHub) -> None:
    """The guard must fail in the first step, not only when something is written."""
    side = _side_branch(repo)
    assert run(repo, "plan", "--sha", side, "--repo", REPO_NAME) == release_publish.EXIT_STOP


def test_an_older_commit_on_the_main_branch_is_fine(
    repo: Path, sha: str, github: FakeGitHub, attested: str
) -> None:
    """Resuming on a commit main has passed is exactly what the guard should allow."""
    (repo / "README.md").write_text("main moved on\n")
    _git(repo, "commit", "-qam", "afterwards")
    assert publish(repo, sha) == release_publish.EXIT_OK


def test_a_trial_release_only_covers_the_trial_version(repo: Path, sha: str, github: FakeGitHub) -> None:
    """The exception cannot ship a real version, whoever ticks the box."""
    side = _side_branch(repo)
    digest = build(repo, side, repo / "dist" / "branch.zip")
    github.attest(digest, side)

    assert publish(repo, side, "--trial-release") == release_publish.EXIT_STOP
    assert github.releases == []


def test_a_trial_release_with_the_trial_version_goes_through(
    repo: Path, sha: str, github: FakeGitHub
) -> None:
    """The trial run against a throwaway tag needs a real workflow run to be attested."""
    side = _side_branch(repo, version=release_publish.TRIAL_VERSION)
    digest = build(repo, side, repo / "dist" / "branch.zip")
    github.attest(digest, side)

    assert publish(repo, side, "--trial-release") == release_publish.EXIT_OK
    release = github.release(f"v{release_publish.TRIAL_VERSION}")
    assert release is not None
    assert release["prerelease"] is True, "a trial tag must not look installable"
    assert release["make_latest"] == "false", "a trial tag became latest"


# --------------------------------------------------------------------------
# A draft from another commit
# --------------------------------------------------------------------------


def test_a_draft_from_another_commit_is_not_reused(
    repo: Path, sha: str, github: FakeGitHub, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The tag was deleted by hand, the draft stayed. The body describes commit A."""
    digest_a = build(repo, sha, repo / "dist" / "a.zip")
    github.attest(digest_a, sha)
    monkeypatch.setenv("GH_FAILURES", "publish")
    publish(repo, sha)
    monkeypatch.delenv("GH_FAILURES")

    # The person deletes the tag but leaves the draft.
    state = github.read()
    del state["tags"][TAG]
    github.write(state)

    (repo / COMPONENT / "sensor.py").write_text("SENSOR = 2\n")
    _git(repo, "commit", "-qam", "same version, new commit")
    new_sha = _git(repo, "rev-parse", "HEAD")
    github.attest(build(repo, new_sha, repo / "dist" / "b.zip"), new_sha)

    assert publish(repo, new_sha) == release_publish.EXIT_STOP
    assert github.tag() is None, "the tag was created before the draft was checked"
    assert github.release()["draft"] is True
    assert sha[:12] in github.release()["body"], "the draft still belongs to the old commit"


def test_a_handwritten_draft_is_still_reused(
    repo: Path, sha: str, github: FakeGitHub, attested: str
) -> None:
    """A draft made in the browser points at a branch, not a commit. It should ship."""
    state = github.read()
    state["releases"].append(
        {
            "id": "77",
            "tag_name": TAG,
            "target_commitish": "main",
            "body": "written by hand",
            "draft": True,
            "assets": [],
        }
    )
    github.write(state)

    assert publish(repo, sha) == release_publish.EXIT_OK
    assert github.release()["draft"] is False
    assert github.release()["body"] == "written by hand"


# --------------------------------------------------------------------------
# Workflows, hacs.json and the justfile
# --------------------------------------------------------------------------

# The jobs that must be green for the candidate before anything is published.
REQUIRED_JOBS = {"test", "test-ha", "coverage", "hacs", "hassfest"}


def _workflow(name: str) -> dict:
    yaml = pytest.importorskip("yaml")
    return yaml.safe_load((REPO / ".github" / "workflows" / name).read_text(encoding="utf-8"))


def test_the_release_workflow_waits_for_the_whole_ci_graph() -> None:
    """Every test layer has to belong to the candidate's own graph."""
    ci = _workflow("ci.yml")
    release = _workflow("release.yml")

    assert set(ci["jobs"]) >= REQUIRED_JOBS
    gate = ci["jobs"]["release-gate"]
    assert set(gate["needs"]) == REQUIRED_JOBS
    assert gate["if"] == "always()"
    assert not gate.get("continue-on-error", False)
    assert all(not ci["jobs"][job].get("continue-on-error", False) for job in REQUIRED_JOBS)
    # PyYAML reads the bare key `on` as True.
    assert "workflow_call" in ci[True], "ci.yml cannot be called by release.yml"

    assert release["jobs"]["ci"]["uses"] == "./.github/workflows/ci.yml"
    assert release["jobs"]["release"]["needs"] == ["ci"]
    assert "workflow_run" not in release[True], (
        "workflow_run gives the release no control over which commit was tested"
    )
    assert release["concurrency"]["cancel-in-progress"] is False


@pytest.mark.parametrize("result", ["success", "failure", "cancelled", "skipped", "missing"])
@pytest.mark.parametrize("job", sorted(REQUIRED_JOBS))
def test_the_release_gate_stops_everything_but_success(job: str, result: str) -> None:
    """Run the gate command itself with GitHub's result format, missing job included."""
    gate = _workflow("ci.yml")["jobs"]["release-gate"]
    (step,) = gate["steps"]
    assert step["env"]["JOB_RESULTS"] == "${{ toJSON(needs) }}"
    results = {name: {"result": "success"} for name in gate["needs"]}
    if result == "missing":
        results.pop(job)
    else:
        results[job]["result"] = result
    completed = subprocess.run(
        ["bash", "-e", "-c", step["run"]],
        env={**os.environ, "JOB_RESULTS": json.dumps(results)},
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == (0 if result == "success" else 1), completed.stderr
    assert f"{job}: {result}" in completed.stdout
    assert ("::error::Release blocked:" in completed.stdout) is (result != "success")


def test_the_release_job_has_a_ref_guard() -> None:
    """workflow_dispatch can run from any branch. Publishing cannot."""
    release = _workflow("release.yml")
    guard = " ".join(release["jobs"]["release"]["if"].split())

    assert "github.ref == 'refs/heads/main'" in guard
    assert "inputs.trial_release" in guard, "the trial path must be explicit"
    assert "trial_release" in release[True]["workflow_dispatch"]["inputs"]

    workflow = (REPO / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
    assert "--trial-release" in workflow, "the input has to reach the script, which binds it to 0.0.0"


def test_the_workflow_publishes_last_and_attests_before_uploading() -> None:
    """The order in the file is half the guarantee. Change it and it is no longer atomic."""
    steps = _workflow("release.yml")["jobs"]["release"]["steps"]
    names = [s.get("name", s.get("uses", "")) for s in steps]
    text = " ".join(str(s.get("run", "")) + str(s.get("uses", "")) for s in steps)

    assert names.index("Build the deterministic ZIP") < names.index("Attest the build")
    assert names.index("Attest the build") < names.index("Verify and publish")
    assert "release_publish.py publish" in text
    assert "action-gh-release" not in text, (
        "action-gh-release publishes at once and takes no target_commitish"
    )


def test_the_release_job_can_attest_and_write_releases() -> None:
    """Without these three permissions the flow fails at the attestation step."""
    permissions = _workflow("release.yml")["jobs"]["release"]["permissions"]
    assert permissions == {"contents": "write", "id-token": "write", "attestations": "write"}


def test_the_ci_graph_checks_the_release_note_before_the_release_runs() -> None:
    """A missing CHANGELOG section must fail CI, not the publish step."""
    ci = _workflow("ci.yml")
    runs = [
        str(step.get("run", ""))
        for job in REQUIRED_JOBS
        for step in ci["jobs"][job].get("steps", [])
    ]
    assert any("release_notes.py" in run for run in runs), (
        "no job the release gate waits for checks that the version has a release note"
    )


def test_hacs_installs_the_zip_we_build_and_attest() -> None:
    """Without zip_release HACS installs the tag archive, which cannot be attested."""
    hacs = json.loads((REPO / "hacs.json").read_text(encoding="utf-8"))
    assert hacs["zip_release"] is True
    assert hacs["filename"] == release_publish.ASSET_NAME
    # HACS requires hide_default_branch together with zip_release; without it,
    # installing the default branch 404s because there is no ZIP there.
    assert hacs["hide_default_branch"] is True


def test_the_justfile_and_the_workflow_call_the_same_core() -> None:
    """One flow, not one for CI and one for hand."""
    justfile = (REPO / "justfile").read_text(encoding="utf-8")
    workflow = (REPO / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")

    in_just = set(re.findall(r"release_publish\.py (\w+)", justfile))
    in_workflow = set(re.findall(r"release_publish\.py (\w+)", workflow))
    assert {"build", "plan", "verify"} <= in_just
    assert in_workflow <= in_just | {"publish"}
    assert "release-plan" in justfile and "release-zip" in justfile
