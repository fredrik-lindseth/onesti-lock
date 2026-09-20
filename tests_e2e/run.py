"""Run the release ZIP inside a real Home Assistant container.

The host side is standard library only. Everything that talks to Home
Assistant runs inside the container, where aiohttp is already installed
(driver.py).

The flow is the one a HACS user goes through: build the ZIP from a committed
SHA the way scripts/release_publish.py does, unpack it flat into
custom_components/onesti_lock, start Home Assistant on it, and look at what
came up. See README.md for what that does and does not prove.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import tomllib
import uuid
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
ARTIFACTS = HERE / "artifacts"
PROJECT_PREFIX = "onesti-e2e-"
MARKER = "onesti-lock-e2e-v1"
PLUGIN = "pytest-homeassistant-custom-component"
IMAGE_REPOSITORY = "ghcr.io/home-assistant/home-assistant"
# The seeded lock. No ZHA device has it, which is the point: the entry has to
# load without one, the way a user's entry does while the stick is missing.
E2E_IEEE = "00:0d:6f:00:0e:2e:00:01"
E2E_MODEL = "NimlyPRO"


class Failure(RuntimeError):
    """Something the run cannot continue past."""


def command(args: list[str], *, timeout: int = 300, env: dict | None = None) -> str:
    result = subprocess.run(
        args, cwd=REPO, env=env, capture_output=True, text=True, timeout=timeout
    )
    if result.returncode:
        raise Failure(f"{args[0]} failed ({result.returncode}): {result.stderr[-4000:]}")
    return result.stdout


def redact(text: str, secrets: tuple[str, ...] = ()) -> str:
    """Strip the lab's own credentials out of evidence before it is kept.

    The user is a throwaway one in a throwaway container, but a CI artifact is
    public, and a token that looks like a real one invites someone to try it.
    """
    for value in secrets:
        if value:
            text = text.replace(value, "<redacted>")
    text = re.sub(r"(?i)(bearer\s+)[\w.~-]+", r"\1<redacted>", text)
    text = re.sub(r"eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+", "<redacted>", text)
    return re.sub(
        r"""(?i)((?:access_token|refresh_token|password|auth_code)["']?\s*[:=]\s*["']?)[^\s,}"']+""",
        r"\1<redacted>",
        text,
    )


def ha_version(target: str) -> str:
    """The Home Assistant release a test target runs, read from uv.lock.

    Same chain as tests/test_version_sync.py: the group pins the plugin, and
    each plugin release pins one exact Home Assistant. Reading it here means
    the container runs the same release as `just test-ha <target>`, and that
    moving the pin moves both.
    """
    lock = tomllib.loads((REPO / "uv.lock").read_text(encoding="utf-8"))
    (project,) = [p for p in lock["package"] if p["name"] == "onesti-lock"]
    group = f"ha-{target}"
    deps = project["dev-dependencies"].get(group)
    if deps is None:
        raise Failure(f"uv.lock has no dependency group {group}")
    (plugin_version,) = [d["version"] for d in deps if d["name"] == PLUGIN]
    (plugin,) = [
        p for p in lock["package"] if p["name"] == PLUGIN and p["version"] == plugin_version
    ]
    (version,) = [d["version"] for d in plugin["dependencies"] if d["name"] == "homeassistant"]
    return str(version)


def image_for(target: str) -> str:
    """The image tag for a target.

    The tag, not a digest: the digest of a multi-architecture manifest list
    would pin one architecture, and this has to run on both an amd64 runner
    and an arm64 laptop. The tag names the exact Home Assistant release, which
    is what the test is about.
    """
    return f"{IMAGE_REPOSITORY}:{ha_version(target)}"


def minor_version() -> int:
    """The config entry MINOR_VERSION the built integration writes.

    Read out of the source that is being installed, so a bump in the
    integration never turns the seeded entry into a migration case by
    accident. A migration is tests_ha's job, with a stored shape that release
    actually wrote; here the entry is meant to be current.
    """
    source = (REPO / "custom_components/onesti_lock/config_flow.py").read_text(encoding="utf-8")
    match = re.search(r"^\s*MINOR_VERSION\s*=\s*(\d+)", source, re.MULTILINE)
    if not match:
        raise Failure("config_flow.py has no MINOR_VERSION")
    return int(match.group(1))


def build_integration(sha: str, run_dir: Path) -> tuple[str, str]:
    """Build the release ZIP and unpack it the way HACS unpacks it.

    Returns (resolved sha, sha256 of the ZIP). The ZIP is flat, so it goes
    straight into custom_components/onesti_lock without stripping a prefix;
    that assumption is checked here rather than trusted, since getting it
    wrong is exactly the kind of thing this test exists to catch.
    """
    resolved = command(["git", "rev-parse", sha]).strip()
    archive = run_dir / "onesti_lock.zip"
    output = command(
        [
            sys.executable,
            str(REPO / "scripts/release_publish.py"),
            "build",
            "--sha",
            resolved,
            "--output",
            str(archive),
        ]
    )
    digest = re.search(r"\b([0-9a-f]{64})\b", output)
    if not digest:
        raise Failure(f"release_publish.py build printed no sha256:\n{output}")

    target = run_dir / "integration"
    target.mkdir()
    with zipfile.ZipFile(archive) as zipped:
        names = zipped.namelist()
        if any(name.startswith("custom_components/") for name in names):
            raise Failure("the ZIP keeps a custom_components/ prefix; HACS unpacks it flat")
        zipped.extractall(target)
    if not (target / "manifest.json").is_file():
        raise Failure("the unpacked ZIP has no manifest.json at its root")
    manifest = json.loads((target / "manifest.json").read_text(encoding="utf-8"))
    if manifest["domain"] != "onesti_lock":
        raise Failure(f"the ZIP installs domain {manifest['domain']}, not onesti_lock")
    return resolved, digest.group(1)


def seed_config_entry() -> dict:
    """A stored config entry for a lock no radio can see.

    Written in the oldest store format (1.1) with only the keys that format
    had. Home Assistant's own store migration fills in everything added since,
    so the same file works on the minimum release and on current, and this
    harness does not have to track a storage schema that is not ours.
    """
    entry = {
        "entry_id": uuid.uuid4().hex,
        "version": 2,
        "minor_version": minor_version(),
        "domain": "onesti_lock",
        "title": "Onesti Lock (e2e)",
        "data": {"ieee": E2E_IEEE, "model": E2E_MODEL},
        "options": {"slots": {}},
        "source": "user",
        "unique_id": E2E_IEEE,
    }
    return {
        "version": 1,
        "minor_version": 1,
        "key": "core.config_entries",
        "data": {"entries": [entry]},
    }


def prepare(run_dir: Path) -> str:
    """Lay out /config: HA configuration, the seeded entry, the blueprints."""
    config = run_dir / "config"
    (config / ".storage").mkdir(parents=True)
    shutil.copy(HERE / "configuration.yaml", config / "configuration.yaml")
    (config / "automations.yaml").write_text("[]\n", encoding="utf-8")

    store = seed_config_entry()
    (config / ".storage/core.config_entries").write_text(json.dumps(store, indent=2))

    # The blueprints are repo files a user imports by hand, not part of the
    # ZIP, so they are copied from the working tree.
    blueprints = config / "blueprints/automation/onesti_lock"
    blueprints.mkdir(parents=True)
    for source in sorted((REPO / "blueprints/automation").glob("*.yaml")):
        shutil.copy(source, blueprints / source.name)
    return str(store["data"]["entries"][0]["entry_id"])


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


class Lab:
    """One disposable Compose project."""

    def __init__(self, directory: Path):
        self.directory = directory.resolve()
        self.state = json.loads((self.directory / "lab.json").read_text())
        project = self.state.get("project", "")
        if self.state.get("marker") != MARKER or not re.fullmatch(
            PROJECT_PREFIX + r"[a-f0-9]{12}", project
        ):
            raise Failure("not a lab this harness made")
        if self.state.get("directory") != str(self.directory):
            raise Failure("the lab directory moved; refusing to drive another Compose project")
        self.project = project
        self.env = {
            **os.environ,
            "E2E_RUN_DIR": str(self.directory),
            "E2E_HARNESS": str(HERE),
            "E2E_PORT": str(self.state["port"]),
            "E2E_IMAGE": self.state["image"],
        }

    @classmethod
    def create(cls, directory: Path, *, target: str, sha: str, keep: bool) -> Lab:
        directory.mkdir(parents=True, exist_ok=True)
        resolved, digest = build_integration(sha, directory)
        entry_id = prepare(directory)
        state = {
            "marker": MARKER,
            "project": PROJECT_PREFIX + uuid.uuid4().hex[:12],
            "directory": str(directory.resolve()),
            "port": free_port(),
            "target": target,
            "image": image_for(target),
            "sha": resolved,
            "zip_sha256": digest,
            "entry_id": entry_id,
            "keep": keep,
        }
        (directory / "lab.json").write_text(json.dumps(state, indent=2))
        return cls(directory)

    def compose(self, *args: str, timeout: int = 300) -> str:
        return command(
            [
                "docker",
                "compose",
                "--project-name",
                self.project,
                "--file",
                str(HERE / "compose.yaml"),
                *args,
            ],
            timeout=timeout,
            env=self.env,
        )

    def up(self) -> None:
        self.compose("up", "--detach", "--wait", "--wait-timeout", "300", timeout=420)

    def down(self) -> None:
        self.compose("down", "--volumes", "--timeout", "20", timeout=120)

    def drive(self, *args: str, timeout: int = 600) -> None:
        print(
            self.compose("exec", "-T", "ha", "python", "/harness/driver.py", *args, timeout=timeout),
            end="",
            flush=True,
        )

    def logs(self) -> str:
        try:
            return self.compose("logs", "--no-color", "--tail", "4000", timeout=60)
        except (Failure, subprocess.TimeoutExpired) as exc:
            return f"<could not read the container log: {exc}>"

    def evidence(self) -> Path:
        """Keep the redacted log, the report and what was built, then report."""
        destination = ARTIFACTS / self.project
        destination.mkdir(parents=True, exist_ok=True)
        auth = self.directory / "config/e2e-auth.json"
        secrets = tuple(json.loads(auth.read_text()).values()) if auth.exists() else ()
        report = self.directory / "config/report.json"
        if report.exists():
            (destination / "report.json").write_text(redact(report.read_text(), secrets))
        keys = ("project", "target", "image", "sha", "zip_sha256", "entry_id")
        (destination / "version.json").write_text(
            json.dumps({key: self.state[key] for key in keys}, indent=2)
        )
        (destination / "ha.log").write_text(redact(self.logs(), secrets))
        return destination


# Lines Home Assistant logs that mean the installed integration is broken, as
# opposed to the warnings every custom integration gets.
LOG_FAILURES = (
    "Error setting up entry",
    "Error during setup of component onesti_lock",
    "Setup failed for",
    "Unable to install package",
    "Error importing platform",
    "Unexpected exception",
)


def check_log(text: str) -> list[str]:
    """Fail on errors that name this integration, plus a few fatal ones.

    An ERROR from an unrelated component in a radio-less container is not this
    integration's fault, so the filter is on our own name, and on the handful
    of messages that mean nothing of ours could have worked.
    """
    problems = []
    for line in text.splitlines():
        fatal = any(marker in line for marker in LOG_FAILURES)
        if fatal or ("ERROR" in line and "onesti_lock" in line):
            problems.append(line.strip())
    return problems


def run(target: str, sha: str, *, keep: bool) -> int:
    directory = Path(tempfile.mkdtemp(prefix="onesti-e2e-"))
    lab = Lab.create(directory, target=target, sha=sha, keep=keep)
    print(
        f"target={target} image={lab.state['image']}\n"
        f"sha={lab.state['sha'][:12]} zip_sha256={lab.state['zip_sha256'][:16]}…\n"
        f"lab={directory} url=http://127.0.0.1:{lab.state['port']}",
        flush=True,
    )
    failure: str | None = None
    try:
        lab.up()
        lab.drive("check", "--entry-id", lab.state["entry_id"])
    except (Failure, subprocess.TimeoutExpired) as exc:
        failure = str(exc)
    finally:
        problems = check_log(lab.logs())
        destination = lab.evidence()
        if not keep:
            lab.down()
            shutil.rmtree(directory, ignore_errors=True)
        print(f"evidence: {destination}", flush=True)
    if failure:
        print(f"::error::e2e failed: {failure}", file=sys.stderr)
        return 1
    if problems:
        print("::error::Home Assistant logged errors about the integration:", file=sys.stderr)
        for line in problems[:20]:
            print(f"  {line}", file=sys.stderr)
        return 1
    print(f"e2e passed on {target}", flush=True)
    return 0


def cleanup() -> int:
    """Stop any lab left behind by a killed run. Touches nothing else."""
    listed = json.loads(command(["docker", "compose", "ls", "--all", "--format", "json"]))
    stray = [row["Name"] for row in listed if row["Name"].startswith(PROJECT_PREFIX)]
    for project in stray:
        print(f"stopping {project}", flush=True)
        command(
            ["docker", "compose", "--project-name", project, "down", "--volumes", "--timeout", "20"],
            env={
                **os.environ,
                "E2E_RUN_DIR": tempfile.gettempdir(),
                "E2E_HARNESS": str(HERE),
                "E2E_PORT": "0",
                "E2E_IMAGE": IMAGE_REPOSITORY,
            },
            timeout=120,
        )
    print(f"{len(stray)} lab(s) stopped", flush=True)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    runner = sub.add_parser("run", help="build, start, check, stop")
    runner.add_argument("--target", default="current", choices=("minimum", "current"))
    runner.add_argument("--sha", default="HEAD", help="the commit the ZIP is built from")
    runner.add_argument("--keep", action="store_true", help="leave the container running")
    sub.add_parser("cleanup", help="stop labs left behind by an interrupted run")
    args = parser.parse_args()
    if args.command == "cleanup":
        return cleanup()
    return run(args.target, args.sha, keep=args.keep)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Failure as error:
        print(f"::error::{error}", file=sys.stderr)
        sys.exit(1)
