"""`tools/esphome/ble-debug-proxy.yaml`: the board by the door is not open.

The firmware is flashed by hand and nothing in this repository runs it, so
the one thing worth a test is the thing that is invisible until someone else
finds it: an ESP32 within radio range of the lock that any host on the LAN
can talk to or reflash. ESPHome leaves both off unless the config asks for
them, and the ready-made image this build replaced had neither.

Nothing here compiles the config; that needs ESPHome and the secrets.
"""

from __future__ import annotations

from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

CONFIG = Path(__file__).resolve().parents[1] / "tools" / "esphome" / "ble-debug-proxy.yaml"
README = CONFIG.parent / "README.md"


class Secret:
    """A `!secret name` reference, kept as the name it points at."""

    def __init__(self, name: str) -> None:
        self.name = name

    def __eq__(self, other: object) -> bool:
        return isinstance(other, Secret) and other.name == self.name

    def __repr__(self) -> str:
        return f"!secret {self.name}"


class EsphomeLoader(yaml.SafeLoader):
    """ESPHome's own tags, so the config parses without ESPHome installed."""


EsphomeLoader.add_constructor("!secret", lambda loader, node: Secret(loader.construct_scalar(node)))
EsphomeLoader.add_multi_constructor("!", lambda loader, suffix, node: f"!{suffix}")


@pytest.fixture(scope="module")
def config() -> dict:
    with CONFIG.open() as handle:
        return yaml.load(handle, Loader=EsphomeLoader)


def test_the_api_is_encrypted(config: dict) -> None:
    """Without a key, anyone on the LAN can read the proxy and act on it."""
    key = config["api"].get("encryption", {}).get("key")
    assert isinstance(key, Secret), f"the API takes no encryption key: {config['api'].get('encryption')}"
    assert key.name == "api_encryption_key"


def test_ota_needs_a_password(config: dict) -> None:
    """Without one, anyone on the LAN can flash their own firmware onto it."""
    for entry in config["ota"]:
        password = entry.get("password")
        assert isinstance(password, Secret), f"{entry.get('platform')} OTA has no password: {entry}"
        assert password.name == "ota_password"


def test_no_secret_is_written_out_in_the_config(config: dict) -> None:
    """Credentials come from secrets.yaml, which is not in this repository."""
    for key, value in [
        ("ssid", config["wifi"]["ssid"]),
        ("password", config["wifi"]["password"]),
        ("api key", config["api"]["encryption"]["key"]),
    ]:
        assert isinstance(value, Secret), f"{key} is written into the config: {value!r}"


def test_the_readme_names_every_secret_the_config_reads(config: dict) -> None:
    """A secret the reader does not know about is a flash that fails at the end."""
    text = CONFIG.read_text()
    wanted = {line.split("!secret", 1)[1].strip() for line in text.splitlines() if "!secret" in line}
    assert wanted == {"wifi_ssid", "wifi_password", "api_encryption_key", "ota_password"}
    readme = README.read_text()
    for name in wanted:
        assert name in readme, f"{name} is read by the config but not mentioned in README.md"
