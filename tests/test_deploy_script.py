"""`scripts/deploy_ha.sh` in dry-run: the order the steps come in.

A deploy to the real instance cannot be tested here, so what is checked is the
thing that would hurt if it were wrong: the backup tarball is made before
anything on the box is touched, the staging directory is proven complete before
the installed integration is removed, and the removal never stands alone. The
dry-run prints exactly the commands it would have run, so the printed order is
the real order.

A stub `ssh` on PATH proves the dry-run really runs nothing: if the script
reached it, the stub would leave a file behind and fail the run.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "deploy_ha.sh"


def index_of(lines: list[str], needle: str) -> int:
    for i, line in enumerate(lines):
        if needle in line:
            return i
    raise AssertionError(f"{needle!r} not in output:\n" + "\n".join(lines))


def indices_of(lines: list[str], needle: str) -> list[int]:
    return [i for i, line in enumerate(lines) if needle in line]


@pytest.fixture(scope="module")
def stub_path(tmp_path_factory: pytest.TempPathFactory) -> tuple[str, Path]:
    """PATH with an ssh/scp that refuses to run and records the attempt."""
    bindir = tmp_path_factory.mktemp("stubbin")
    marker = bindir / "was-called"
    for name in ("ssh", "scp"):
        stub = bindir / name
        stub.write_text(f'#!/bin/sh\necho "$0 $*" >> "{marker}"\nexit 97\n')
        stub.chmod(0o755)
    return f"{bindir}{os.pathsep}{os.environ['PATH']}", marker


def run_script(stub_path: tuple[str, Path], *args: str) -> list[str]:
    path, marker = stub_path
    proc = subprocess.run(
        ["bash", str(SCRIPT), *args],
        capture_output=True,
        text=True,
        cwd=REPO,
        env={**os.environ, "PATH": path},
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    assert not marker.exists(), f"dry-run reached the network: {marker.read_text()}"
    return proc.stdout.splitlines()


def test_script_is_executable_and_parses() -> None:
    assert SCRIPT.exists()
    assert os.access(SCRIPT, os.X_OK)
    subprocess.run(["bash", "-n", str(SCRIPT)], check=True)


def test_usage_without_a_command(stub_path: tuple[str, Path]) -> None:
    path, _ = stub_path
    proc = subprocess.run(
        ["bash", str(SCRIPT)],
        capture_output=True,
        text=True,
        cwd=REPO,
        env={**os.environ, "PATH": path},
        check=False,
    )
    assert proc.returncode == 1
    assert "deploy_ha.sh deploy" in proc.stdout


def test_backup_comes_before_anything_else(stub_path: tuple[str, Path]) -> None:
    lines = run_script(stub_path, "--dry-run", "deploy")
    backup = index_of(lines, "tar czf /config/onesti_lock-backup-")
    assert backup < min(indices_of(lines, "rm -rf")), "something is removed before the backup"
    # The backup is also read back before it is trusted.
    assert index_of(lines, "tar tzf /config/onesti_lock-backup-") < index_of(lines, "rm -rf")


def test_staging_is_complete_before_the_installed_copy_is_removed(
    stub_path: tuple[str, Path],
) -> None:
    lines = run_script(stub_path, "--dry-run", "deploy")
    copy = index_of(lines, "tar xzf - -C /config/custom_components/onesti_lock.new")
    verify = index_of(lines, "test -f /config/custom_components/onesti_lock.new/manifest.json")
    swap = index_of(lines, "rm -rf /config/custom_components/onesti_lock ")
    assert copy < verify < swap
    # The verification counts the files, not just the presence of one.
    assert "-name '*.py' | wc -l" in lines[verify]


def test_the_installed_copy_is_never_removed_on_its_own(
    stub_path: tuple[str, Path],
) -> None:
    lines = run_script(stub_path, "--dry-run", "deploy")
    for i in indices_of(lines, "rm -rf /config/custom_components/onesti_lock "):
        assert "mv /config/custom_components/onesti_lock.new" in lines[i], (
            "removal and move must be one command, or a dropped connection leaves "
            f"/config without the integration: {lines[i]}"
        )


def test_pycache_is_left_behind(stub_path: tuple[str, Path]) -> None:
    lines = run_script(stub_path, "--dry-run", "deploy")
    copy = lines[index_of(lines, "tar czf - -C")]
    assert "--exclude __pycache__" in copy
    assert "--exclude '*.pyc'" in copy


def test_check_then_restart_then_states(stub_path: tuple[str, Path]) -> None:
    lines = run_script(stub_path, "--dry-run", "deploy")
    swap = index_of(lines, "mv /config/custom_components/onesti_lock.new")
    check = index_of(lines, "ha core check")
    restart = index_of(lines, "ha core restart")
    states = index_of(lines, "ha.sh states sensor.dorlasen_")
    assert swap < check < restart < states


def test_deploy_prints_how_to_get_back(stub_path: tuple[str, Path]) -> None:
    lines = run_script(stub_path, "--dry-run", "deploy")
    assert any("deploy_ha.sh restore /config/onesti_lock-backup-" in line for line in lines)


def test_restore_reads_the_tarball_before_removing(stub_path: tuple[str, Path]) -> None:
    tarball = "/config/onesti_lock-backup-20260101-000000.tar.gz"
    lines = run_script(stub_path, "--dry-run", "restore", tarball)
    listed = index_of(lines, f"tar tzf {tarball}")
    removed = index_of(lines, "rm -rf onesti_lock")
    assert listed < removed
    # Removal and extraction are one command, as in the deploy swap.
    assert f"tar xzf {tarball}" in lines[removed]
    assert index_of(lines, "ha core restart") > removed


def test_restore_needs_a_tarball(stub_path: tuple[str, Path]) -> None:
    path, _ = stub_path
    proc = subprocess.run(
        ["bash", str(SCRIPT), "--dry-run", "restore"],
        capture_output=True,
        text=True,
        cwd=REPO,
        env={**os.environ, "PATH": path},
        check=False,
    )
    assert proc.returncode != 0
    assert "restore <tarball>" in proc.stderr
