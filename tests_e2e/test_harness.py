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
    def entries(self):
        plan = run.seed_plan()
        return plan, {
            row["entry_id"]: row for row in run.seed_config_entry(plan)["data"]["entries"]
        }

    def test_the_current_entry_carries_the_current_config_flow_version(self):
        plan, entries = self.entries()
        entry = entries[plan["current"]["entry_id"]]
        self.assertEqual(entry["version"], 2)
        self.assertEqual(entry["minor_version"], run.minor_version())
        self.assertEqual(entry["domain"], "onesti_lock")

    def test_one_entry_per_stored_shape_a_user_can_start_from(self):
        plan, entries = self.entries()
        versions = {
            name: (entries[plan[name]["entry_id"]]["version"],
                   entries[plan[name]["entry_id"]]["minor_version"])
            for name in ("migrated", "legacy", "future")
        }
        self.assertEqual(versions["migrated"], (2, 2))
        self.assertEqual(versions["legacy"], (2, 1))
        self.assertEqual(versions["future"][0], run.major_version() + 1)

    def test_the_2_1_entry_carries_the_field_that_migration_strips(self):
        plan, entries = self.entries()
        slot = entries[plan["legacy"]["entry_id"]]["options"]["slots"][plan["legacy"]["slot"]]
        self.assertIn("has_rfid", slot)

    def test_store_is_written_in_the_oldest_format_home_assistant_migrates(self):
        stores = [run.seed_config_entry(), *run.seed_registries(run.seed_plan())]
        for store in stores:
            self.assertEqual((store["version"], store["minor_version"]), (1, 1))

    def test_the_seeded_registries_are_keyed_on_the_ieee_address(self):
        plan = run.seed_plan()
        devices, entities = run.seed_registries(plan)
        ieee = plan["migrated"]["ieee"]
        (device,) = devices["data"]["devices"]
        self.assertEqual(device["identifiers"], [["onesti_lock", ieee]])
        # No connections: a migration that failed to rewrite the identifier
        # must show up as a second device, not be merged into this one.
        self.assertEqual(device["connections"], [])
        self.assertTrue(
            all(row["unique_id"].startswith(f"{ieee}-") for row in entities["data"]["entities"])
        )
        self.assertTrue(any(row["name"] for row in entities["data"]["entities"]))
        self.assertTrue(any(row["disabled_by"] == "user" for row in entities["data"]["entities"]))

    def test_prepare_lays_out_config_storage_and_blueprints(self):
        with tempfile.TemporaryDirectory() as directory:
            plan = run.prepare(Path(directory))
            config = Path(directory) / "config"
            stored = json.loads((config / ".storage/core.config_entries").read_text())
            seeded = {row["entry_id"] for row in stored["data"]["entries"]}
            self.assertEqual(seeded, {plan[name]["entry_id"] for name in plan})
            self.assertEqual(json.loads((config / "seed.json").read_text()), plan)
            for name in ("core.device_registry", "core.entity_registry"):
                self.assertTrue((config / ".storage" / name).is_file())
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

    def test_the_refusal_of_the_entry_from_the_future_is_expected(self):
        (allowed,) = run.log_allowed()
        self.assertEqual(run.check_log(f"2026-09-20 ERROR [x] {allowed} which is higher"), [])

    def test_the_same_refusal_about_another_entry_still_fails(self):
        line = "ERROR Config entry Front door for onesti_lock has version 9 which is higher"
        self.assertTrue(run.check_log(line))

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
