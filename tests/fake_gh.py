#!/usr/bin/env python3
"""A small GitHub stand-in, used as `gh` by tests/test_release_publish.py.

It is not a mock that returns canned answers. It keeps state (tags, releases,
assets, attestations) in a JSON file, so a test can run the flow, break it
halfway, and run it again against the state the break left behind. That is the
whole point: resuming cannot be tested against something that does not remember
the previous attempt.

Failures are injected with `GH_FAILURES`, a comma-separated list:

    upload_after_store   the file is accepted, then the answer dies (the classic)
    upload_corrupt       the file is accepted, but something else is stored
    publish              PATCH to draft=false fails
    attest               attestation verification fails

Every call is logged in `calls`, so tests can assert that a resume did *not*
upload again.

`GH_REPO_ROOT` points at the test's real git repo. The compare endpoint, which
the main-branch guard asks, answers from actual commits there rather than from
a hardcoded reply.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import NoReturn

STATE = Path(os.environ["GH_STATE"])


def read() -> dict:
    return json.loads(STATE.read_text())


def write(state: dict) -> None:
    STATE.write_text(json.dumps(state, indent=1))


def failure_active(name: str) -> bool:
    return name in os.environ.get("GH_FAILURES", "").split(",")


def answer(data) -> NoReturn:
    print(json.dumps(data))
    sys.exit(0)


def http_error(code: int, message: str) -> NoReturn:
    print(f"gh: {message} (HTTP {code})", file=sys.stderr)
    sys.exit(1)


def parse_api(argv: list[str]) -> tuple[str, str, str | None, list[str]]:
    """(method, path, --input value, accept headers)."""
    method, path, given, headers = "GET", None, None, []
    i = 0
    while i < len(argv):
        arg = argv[i]
        if arg == "--method":
            method, i = argv[i + 1], i + 2
        elif arg == "--input":
            given, i = argv[i + 1], i + 2
        elif arg in {"-H", "--header"}:
            headers.append(argv[i + 1])
            i += 2
        elif arg == "--paginate":
            i += 1
        else:
            path, i = arg, i + 1
    assert path is not None, f"found no path in {argv}"
    return method, path, given, headers


def body(given: str | None) -> dict:
    if given == "-":
        return json.loads(sys.stdin.buffer.read())
    return {}


def api(argv: list[str]) -> None:
    method, path, given, headers = parse_api(argv)
    state = read()
    state["calls"].append(f"{method} {path}")
    write(state)
    parts = path.split("?")[0].rstrip("/").split("/")

    # GET repos/R/releases/assets/<id> with octet-stream: the raw content.
    if any("octet-stream" in h for h in headers):
        content = state["assets"].get(parts[-1])
        if content is None:
            http_error(404, "Not Found")
        sys.stdout.buffer.write(bytes.fromhex(content))
        sys.exit(0)

    if path.startswith("https://uploads.github.com/"):
        release = find_release_id(state, parts[parts.index("releases") + 1])
        name = path.split("name=")[1]
        content = Path(given).read_bytes() if given else b""
        if failure_active("upload_corrupt"):
            content = b"something else entirely"
        asset_id = str(state["next_id"])
        state["next_id"] += 1
        state["assets"][asset_id] = content.hex()
        release["assets"].append({"id": asset_id, "name": name})
        write(state)
        if failure_active("upload_after_store"):
            http_error(502, "Bad Gateway")
        answer({"id": asset_id, "name": name})

    if parts[-2:] == ["git", "refs"] and method == "POST":
        data = body(given)
        tag = data["ref"].removeprefix("refs/tags/")
        if tag in state["tags"]:
            http_error(422, "Reference already exists")
        state["tags"][tag] = {"type": "commit", "sha": data["sha"]}
        write(state)
        answer({"ref": data["ref"], "object": state["tags"][tag]})

    if "git" in parts and "ref" in parts and "tags" in parts:
        tag = parts[-1]
        if tag not in state["tags"]:
            http_error(404, "Not Found")
        answer({"ref": f"refs/tags/{tag}", "object": state["tags"][tag]})

    if parts[-3:-1] == ["git", "tags"] or (len(parts) > 2 and parts[-2] == "tags" and "git" in parts):
        pointed_at = state["annotated"].get(parts[-1])
        if pointed_at is None:
            http_error(404, "Not Found")
        answer({"object": {"type": "commit", "sha": pointed_at}})

    if parts[-1] == "releases" and method == "GET":
        answer(state["releases"])

    if parts[-1] == "latest":
        published = [r for r in state["releases"] if not r["draft"]]
        if not published:
            http_error(404, "Not Found")
        answer(published[-1])

    if parts[-1] == "releases" and method == "POST":
        data = body(given)
        created = {
            "id": str(state["next_id"]),
            "tag_name": data["tag_name"],
            "target_commitish": data.get("target_commitish"),
            "name": data.get("name"),
            "body": data.get("body", ""),
            "draft": bool(data.get("draft")),
            "prerelease": bool(data.get("prerelease")),
            "assets": [],
        }
        state["next_id"] += 1
        state["releases"].append(created)
        write(state)
        answer(created)

    if len(parts) >= 2 and parts[-2] == "releases":
        release = find_release_id(state, parts[-1])
        if method == "GET":
            answer(release)
        if method == "PATCH":
            if failure_active("publish"):
                http_error(500, "Internal Server Error")
            release.update(body(given))
            write(state)
            answer(release)

    # The main-branch guard: the repo's default_branch, and the comparison.
    if len(parts) == 3 and parts[0] == "repos" and method == "GET":
        answer({"default_branch": state.get("default_branch", "main")})

    if len(parts) >= 2 and parts[-2] == "compare":
        base, _, head = parts[-1].partition("...")
        answer({"status": compare(base, head)})

    http_error(404, f"the fake gh does not know {method} {path}")


def rev(ref: str) -> str | None:
    """Full commit SHA for a ref in the real test repo, or None."""
    result = subprocess.run(
        ["git", "-C", os.environ["GH_REPO_ROOT"], "rev-parse", "--verify", f"{ref}^{{commit}}"],
        capture_output=True,
        text=True,
    )
    return result.stdout.strip() if result.returncode == 0 else None


def is_ancestor(older: str, newer: str) -> bool:
    result = subprocess.run(
        ["git", "-C", os.environ["GH_REPO_ROOT"], "merge-base", "--is-ancestor", older, newer],
        capture_output=True,
    )
    return result.returncode == 0


def compare(base: str, head: str) -> str:
    """Like GitHub's compare status, computed with real git against the test repo.

    Hardcoding the answer would turn the main-branch guard into a test of the
    hardcoding. Here actual branches and commits decide.
    """
    base_sha, head_sha = rev(base), rev(head)
    if head_sha is None:
        http_error(404, "No commit found for SHA")
    if base_sha is None:
        http_error(404, "Not Found")
    if base_sha == head_sha:
        return "identical"
    if is_ancestor(head_sha, base_sha):
        return "behind"
    if is_ancestor(base_sha, head_sha):
        return "ahead"
    return "diverged"


def find_release_id(state: dict, release_id: str) -> dict:
    for release in state["releases"]:
        if release["id"] == release_id:
            return release
    http_error(404, "Not Found")


def attestation(argv: list[str]) -> None:
    state = read()
    state["calls"].append("attestation verify")
    write(state)
    if failure_active("attest"):
        print("Error: verification failed", file=sys.stderr)
        sys.exit(1)

    path = Path(argv[1])
    flags = {argv[i]: argv[i + 1] for i in range(len(argv)) if argv[i].startswith("--") and i + 1 < len(argv)}
    digest = hashlib.sha256(path.read_bytes()).hexdigest()

    hits = [a for a in state["attestations"] if a["digest"] == digest and a["repo"] == flags.get("--repo")]
    if not hits:
        print(f"Error: no attestations found for {digest}", file=sys.stderr)
        sys.exit(1)
    source = flags.get("--source-digest")
    if source and hits[0]["sha"] != source:
        print(
            f"Error: expected SourceRepositoryDigest to be {source}, got {hits[0]['sha']}",
            file=sys.stderr,
        )
        sys.exit(1)
    signer = flags.get("--signer-workflow")
    if signer and hits[0]["workflow"] != signer:
        print(f"Error: expected signer workflow {signer}", file=sys.stderr)
        sys.exit(1)
    answer(
        [
            {
                "verificationResult": {
                    "statement": {"subject": [{"name": path.name, "digest": {"sha256": digest}}]},
                    "signature": {"certificate": {"sourceRepositoryDigest": hits[0]["sha"]}},
                }
            }
        ]
    )


if __name__ == "__main__":
    if sys.argv[1] == "api":
        api(sys.argv[2:])
    elif sys.argv[1] == "attestation":
        attestation(sys.argv[2:])
    else:
        print(f"the fake gh does not know {sys.argv[1]}", file=sys.stderr)
        sys.exit(1)
