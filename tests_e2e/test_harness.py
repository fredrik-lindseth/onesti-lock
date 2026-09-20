"""The host side of the lab, tested without Docker.

`pytest tests/` runs in an environment without Home Assistant and without
Docker, and these are neither its business nor pytest's; they run from
`just e2e-harness` and from the e2e workflow, before a container is started.
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import run  # noqa: E402


class TestVersions(unittest.TestCase):
    def test_targets_resolve_to_the_versions_uv_lock_pins(self):
        for target in ("minimum", "current"):
            image = run.image_for(target)
            self.assertTrue(image.startswith(run.IMAGE_REPOSITORY + ":"))
            self.assertRegex(image.split(":")[-1], r"^20\d\d\.\d{1,2}\.\d+$")

    def test_the_minimum_container_runs_what_hacs_json_promises(self):
        hacs = json.loads((run.REPO / "hacs.json").read_text(encoding="utf-8"))
        self.assertEqual(run.ha_version("minimum"), hacs["homeassistant"])

    def test_unknown_target_is_refused(self):
        with self.assertRaises(run.Failure):
            run.ha_version("newest")


class TestSeed(unittest.TestCase):
    def test_entry_carries_the_current_config_flow_version(self):
        (entry,) = run.seed_config_entry()["data"]["entries"]
        self.assertEqual(entry["version"], 2)
        self.assertEqual(entry["minor_version"], run.minor_version())
        self.assertEqual(entry["domain"], "onesti_lock")

    def test_store_is_written_in_the_oldest_format_home_assistant_migrates(self):
        store = run.seed_config_entry()
        self.assertEqual((store["version"], store["minor_version"]), (1, 1))

    def test_prepare_lays_out_config_storage_and_blueprints(self):
        with tempfile.TemporaryDirectory() as directory:
            entry_id = run.prepare(Path(directory))
            config = Path(directory) / "config"
            stored = json.loads((config / ".storage/core.config_entries").read_text())
            self.assertEqual(stored["data"]["entries"][0]["entry_id"], entry_id)
            self.assertTrue((config / "configuration.yaml").is_file())
            self.assertTrue((config / "automations.yaml").is_file())
            copied = sorted(p.name for p in (config / "blueprints/automation/onesti_lock").iterdir())
            self.assertEqual(
                copied, sorted(p.name for p in (run.REPO / "blueprints/automation").glob("*.yaml"))
            )


class TestLogCheck(unittest.TestCase):
    def test_an_error_about_us_fails(self):
        line = "2026-09-20 ERROR (MainThread) [homeassistant.setup] onesti_lock boom"
        self.assertEqual(run.check_log(line), [line])

    def test_a_setup_failure_fails_whoever_it_names(self):
        self.assertTrue(run.check_log("ERROR Setup failed for 'zha': Integration not found"))

    def test_someone_elses_error_is_not_ours(self):
        self.assertEqual(run.check_log("ERROR [homeassistant.components.bluetooth] no adapter"), [])

    def test_the_usual_custom_integration_warning_passes(self):
        text = "WARNING We found a custom integration onesti_lock which has not been tested"
        self.assertEqual(run.check_log(text), [])


class TestRedaction(unittest.TestCase):
    def test_known_secrets_and_token_shapes_go(self):
        text = (
            'password: hunter2\nAuthorization: Bearer eyJabc.def-ghi.jkl\n'
            '"access_token": "abc123"\n'
        )
        cleaned = run.redact(text, ("hunter2",))
        for secret in ("hunter2", "abc123", "eyJabc.def-ghi.jkl"):
            self.assertNotIn(secret, cleaned)


class TestLabGuard(unittest.TestCase):
    def test_a_directory_that_is_not_a_lab_is_refused(self):
        with tempfile.TemporaryDirectory() as directory:
            (Path(directory) / "lab.json").write_text(json.dumps({"project": "prod"}))
            with self.assertRaises(run.Failure):
                run.Lab(Path(directory))

    def test_a_moved_lab_is_refused(self):
        with tempfile.TemporaryDirectory() as directory:
            state = {
                "marker": run.MARKER,
                "project": run.PROJECT_PREFIX + "0123456789ab",
                "directory": "/somewhere/else",
                "port": 8123,
                "image": "x",
            }
            (Path(directory) / "lab.json").write_text(json.dumps(state))
            with self.assertRaises(run.Failure):
                run.Lab(Path(directory))


if __name__ == "__main__":
    unittest.main()
