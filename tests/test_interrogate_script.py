"""`scripts/interrogate_lock.sh` in dry-run: what it would send to the lock.

The script is run by hand against a real lock, so what is checked here is what
would be expensive or dangerous to get wrong: that it never sends a command
that writes (Set PIN Code, Clear PIN Code, lock, unlock, or anything at all to
the unknown 0xFEA2 cluster), that it never reads attribute 0x0101, which is
the last PIN in plaintext, and that the PIN walk turns the zigpy debug log off
again after it is done.

A stub `ssh` on PATH proves the dry-run really sends nothing: if the script
reached it, the stub would leave a file behind and fail the run.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "interrogate_lock.sh"

DOORLOCK = 257
# Door Lock commands that change something on the lock. Get PIN Code (0x06) is
# the only one this script is allowed to send.
WRITING_COMMANDS = {0x00, 0x01, 0x05, 0x07}


@pytest.fixture(scope="module")
def stub_path(tmp_path_factory: pytest.TempPathFactory) -> tuple[str, Path]:
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
        ["bash", str(SCRIPT), "--dry-run", *args],
        capture_output=True,
        text=True,
        cwd=REPO,
        env={**os.environ, "PATH": path},
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    assert not marker.exists(), f"dry-run reached the network: {marker.read_text()}"
    return proc.stdout.splitlines()


def calls(lines: list[str]) -> list[tuple[str, dict]]:
    """Every service call the dry-run printed, as (service, data)."""
    found = []
    for line in lines:
        match = re.match(r"^CALL (\S+) (\{.*\})$", line)
        if match:
            found.append((match.group(1), json.loads(match.group(2))))
    return found


def all_blocks(stub_path: tuple[str, Path]) -> list[tuple[str, dict]]:
    found: list[tuple[str, dict]] = []
    for block in ("check", "basic", "bindings", "discover", "doorlock", "pins"):
        found += calls(run_script(stub_path, block))
    return found


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
    assert "interrogate_lock.sh check" in proc.stdout


def test_nothing_is_ever_written_to_the_lock(stub_path: tuple[str, Path]) -> None:
    for service, data in all_blocks(stub_path):
        assert service != "zha_toolkit.attr_write", f"attribute write: {data}"
        assert service != "zha.issue_zigbee_cluster_command", f"cluster command: {data}"
        if service == "zha_toolkit.zcl_cmd":
            assert data["cluster"] == DOORLOCK, f"command to another cluster: {data}"
            assert data["cmd"] not in WRITING_COMMANDS, f"writing command: {data}"


def test_the_unknown_cluster_is_only_ever_discovered(stub_path: tuple[str, Path]) -> None:
    """0xFEA2's commands are unknown, so sending one would be firing blind."""
    for service, data in all_blocks(stub_path):
        assert data.get("cluster") != 0xFEA2, f"{service} aimed at 0xFEA2: {data}"


def test_the_plaintext_pin_attribute_is_never_read(stub_path: tuple[str, Path]) -> None:
    """0x0101 on the Door Lock cluster is the last PIN used, in BCD."""
    for service, data in all_blocks(stub_path):
        if service == "zha_toolkit.attr_read":
            assert not (data["cluster"] == DOORLOCK and data["attribute"] == 0x0101), data


def test_the_pin_walk_only_sends_get_pin_code(stub_path: tuple[str, Path]) -> None:
    lines = run_script(stub_path, "pins", "3", "800")
    commands = [d for s, d in calls(lines) if s == "zha_toolkit.zcl_cmd"]
    assert [d["args"] for d in commands] == [[3], [800]]
    assert all(d["cmd"] == 0x06 for d in commands)


def test_the_pin_walk_turns_the_debug_log_off_again(stub_path: tuple[str, Path]) -> None:
    lines = run_script(stub_path, "pins", "3")
    levels = [d for s, d in calls(lines) if s == "logger.set_level"]
    assert len(levels) == 2, "debug is turned on and off, once each"
    assert levels[0]["zigpy.zcl"] == "debug"
    assert levels[-1]["zigpy.zcl"] != "debug"


def test_the_default_walk_covers_the_boundaries(stub_path: tuple[str, Path]) -> None:
    lines = run_script(stub_path, "pins")
    slots = [d["args"][0] for s, d in calls(lines) if s == "zha_toolkit.zcl_cmd"]
    # The master/user split, the NumberOfPINUsersSupported ceiling, the 8-bit
    # boundary behind the 16-bit slot width, the BLE range and one illegal slot.
    for slot in (0, 2, 3, 49, 50, 51, 255, 256, 300, 800, 999, 1000):
        assert slot in slots, f"slot {slot} is a boundary and belongs in the walk"
    assert len(slots) < 40, "the walk is sampled, not a sweep of every slot"


def test_discovery_runs_a_manufacturer_pass(stub_path: tuple[str, Path]) -> None:
    """0x0100 and 0x0101 are manufacturer-specific and hide from a plain scan."""
    scans = [d for s, d in calls(run_script(stub_path, "discover")) if s.endswith("scan_device")]
    assert len(scans) == 2
    assert "manf" not in scans[0]
    assert scans[1]["manf"] == 0x1234


def test_collect_masks_the_values_it_reads_back(stub_path: tuple[str, Path]) -> None:
    lines = "\n".join(run_script(stub_path, "collect"))
    assert "attribute_value" in lines and "<masked>" in lines, "scan values reach the terminal raw"
    assert "[0-9]{4,}" in lines, "log lines reach the terminal with digit runs intact"
