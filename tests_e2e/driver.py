"""Ask the container's own Home Assistant what came up, over its real APIs.

Runs inside the container (`docker compose exec ... python /harness/driver.py`),
because aiohttp is already there and the API never has to leave loopback. The
credentials belong to a throwaway user in a throwaway container and are kept
out of stdout and out of the report.

Every check is named, and every check is an assertion about the integration
as HACS installed it: the unpacked ZIP under /config/custom_components.
"""

from __future__ import annotations

import asyncio
import json
import re
import sys
import time
from pathlib import Path
from typing import Any

import aiohttp

BASE = "http://127.0.0.1:8123"
INSTALLED = Path("/config/custom_components/onesti_lock")
AUTH = Path("/config/e2e-auth.json")
REPORT = Path("/config/report.json")
SEED = Path("/config/seed.json")
ENTRY_STORE = Path("/config/.storage/core.config_entries")
DOMAIN = "onesti_lock"
SERVICES = ("set_pin", "clear_pin", "set_name", "clear_slot")
# 10 user slots, the activity sensor, and the three capability sensors.
EXPECTED_ENTITIES = 14
BLUEPRINTS = ("goodnight_lock.yaml", "lock_connectivity_alert.yaml", "unlock_activity_notify.yaml")
# The template lock in configuration.yaml, which stands in for the lock ZHA
# would have given the blueprints.
STANDIN_LOCK = "lock.e2e_stand_in"
STANDIN_NAME = "E2E stand-in"
# How long a check waits for something Home Assistant does in the background:
# a delayed store write, an automation run, a notification.
PATIENCE_S = 30


class CheckFailed(AssertionError):
    """A named check that did not hold."""


def entry_version() -> tuple[int, int]:
    """The config entry version the installed ZIP writes, from its own source.

    Read here rather than written down, so bumping MINOR_VERSION moves what
    the migration checks expect along with it.
    """
    source = (INSTALLED / "config_flow.py").read_text(encoding="utf-8")
    found = {
        name: int(match.group(1))
        for name in ("VERSION", "MINOR_VERSION")
        if (match := re.search(rf"^\s*{name}\s*=\s*(\d+)", source, re.MULTILINE))
    }
    if len(found) != 2:
        raise CheckFailed("config_flow.py in the ZIP has no VERSION/MINOR_VERSION")
    return found["VERSION"], found["MINOR_VERSION"]


class Driver:
    def __init__(self, session: aiohttp.ClientSession, entry_id: str):
        self.session = session
        self.entry_id = entry_id
        self.token = ""
        self.results: list[dict[str, Any]] = []
        self.translations = json.loads(
            (INSTALLED / "translations/en.json").read_text(encoding="utf-8")
        )
        # What run.py seeded: the four entries and the registry rows the 2.2
        # one was given.
        self.seed = json.loads(SEED.read_text(encoding="utf-8"))
        self.entry_version = entry_version()

    # -- plumbing --

    async def api(
        self,
        path: str,
        body: Any | None = None,
        *,
        method: str | None = None,
        form: dict | None = None,
        quote_errors: bool = False,
    ) -> Any:
        verb = method or ("POST" if body is not None or form else "GET")
        headers = {"Authorization": f"Bearer {self.token}"} if self.token else {}
        async with self.session.request(
            verb, BASE + path, json=body, data=form, headers=headers
        ) as response:
            if response.status >= 400:
                # Response bodies are quoted only where the caller knows the
                # endpoint cannot echo a credential. Config validation says
                # what is wrong with a blueprint; /auth/token does not.
                detail = f": {(await response.text())[:600]}" if quote_errors else ""
                raise RuntimeError(f"{verb} {path}: HTTP {response.status}{detail}")
            return await response.json()

    async def ws(self, type_: str, **payload: Any) -> Any:
        async with self.session.ws_connect(BASE + "/api/websocket") as socket:
            if (await socket.receive_json())["type"] != "auth_required":
                raise RuntimeError("no auth_required from the WebSocket API")
            await socket.send_json({"type": "auth", "access_token": self.token})
            if (await socket.receive_json())["type"] != "auth_ok":
                raise RuntimeError("WebSocket authentication failed")
            await socket.send_json({"id": 1, "type": type_, **payload})
            answer = await socket.receive_json()
            if not answer.get("success"):
                raise RuntimeError(f"WebSocket {type_} failed: {answer.get('error')}")
            return answer["result"]

    async def wait_for_start(self) -> None:
        deadline = time.monotonic() + 300
        last = "no answer"
        while time.monotonic() < deadline:
            try:
                await self.api("/api/onboarding")
                return
            except (aiohttp.ClientError, RuntimeError, TimeoutError) as exc:
                last = str(exc)
            await asyncio.sleep(0.5)
        raise RuntimeError(f"Home Assistant did not answer within 300 s ({last})")

    async def onboard(self) -> None:
        """Create the throwaway user and finish onboarding, as the frontend does."""
        import secrets

        # A username that is not a substring of anything in the evidence: the
        # redactor replaces every occurrence of it, and "e2e" would black out
        # half the report.
        credentials = {"username": "labuser", "password": secrets.token_urlsafe(24)}
        answer = await self.api(
            "/api/onboarding/users",
            {
                "name": "Lab user",
                "username": credentials["username"],
                "password": credentials["password"],
                "client_id": BASE + "/",
                "language": "en",
            },
        )
        tokens = await self.api(
            "/auth/token",
            form={
                "grant_type": "authorization_code",
                "code": answer["auth_code"],
                "client_id": BASE + "/",
            },
        )
        self.token = tokens["access_token"]
        AUTH.write_text(json.dumps({**credentials, "token": self.token}))
        AUTH.chmod(0o600)
        status = await self.api("/api/onboarding")
        done = {row["step"] for row in status if row["done"]}
        for step, body in (
            ("core_config", {}),
            ("analytics", {}),
            ("integration", {"client_id": BASE + "/", "redirect_uri": BASE + "/"}),
        ):
            if step not in done:
                await self.api(f"/api/onboarding/{step}", body)

    async def wait_running(self) -> None:
        deadline = time.monotonic() + 180
        state = "?"
        while time.monotonic() < deadline:
            config = await self.api("/api/config")
            state = config.get("state", "?")
            if state == "RUNNING":
                return
            await asyncio.sleep(0.5)
        raise RuntimeError(f"Home Assistant stopped at state {state}")

    def record(self, name: str, proof: str, **data: Any) -> None:
        self.results.append({"check": name, "proof": proof, **data})
        print(f"ok  {name}: {proof}", flush=True)

    # -- checks --

    async def check_component_loaded(self) -> None:
        config = await self.api("/api/config")
        if DOMAIN not in config["components"]:
            raise CheckFailed("onesti_lock is not among the loaded components")
        version = json.loads((INSTALLED / "manifest.json").read_text())["version"]
        self.record(
            "component_loaded",
            f"Home Assistant {config['version']} loaded onesti_lock {version} from the ZIP",
            ha_version=config["version"],
            integration_version=version,
        )

    async def check_entry_loaded(self) -> None:
        entries = await self.api(f"/api/config/config_entries/entry?domain={DOMAIN}")
        entry = next((row for row in entries if row["entry_id"] == self.entry_id), None)
        if entry is None:
            raise CheckFailed("the seeded config entry is gone")
        if entry["state"] != "loaded":
            raise CheckFailed(f"the config entry is {entry['state']}, not loaded")
        self.record(
            "entry_loaded",
            "the seeded config entry set up without a Zigbee radio",
            title=entry["title"],
        )

    async def check_entities(self) -> list[dict]:
        registry = await self.ws("config/entity_registry/list")
        ours = [row for row in registry if row.get("config_entry_id") == self.entry_id]
        if len(ours) != EXPECTED_ENTITIES:
            raise CheckFailed(
                f"{len(ours)} entities from the entry, expected {EXPECTED_ENTITIES}: "
                + ", ".join(sorted(row["entity_id"] for row in ours))
            )
        if any(row["platform"] != DOMAIN for row in ours):
            raise CheckFailed("an entity is not on the onesti_lock platform")
        # The three capability sensors are diagnostics the integration turns
        # off until someone needs them, so they have a registry entry and no
        # state. Checking that here keeps the name check below from reading a
        # 404 as a broken name.
        disabled = {row["unique_id"].split("-", 1)[1] for row in ours if row.get("disabled_by")}
        if disabled != {"pin-users", "pin-length-min", "pin-length-max"}:
            raise CheckFailed(f"the disabled-by-default sensors are {sorted(disabled)}")
        self.record(
            "entities_created",
            f"{len(ours)} sensors in the registry, all on the onesti_lock platform, "
            f"{len(disabled)} of them diagnostics that are off by default",
            entities=sorted(row["entity_id"] for row in ours),
        )
        return ours

    async def check_entity_names(self, entities: list[dict]) -> None:
        """The names in the frontend are the translated ones from the ZIP.

        This is the regression a unit test missed once: an _attr_name fallback
        disabled every translated name, and only a running Home Assistant
        showed it. The expected text is read from the installed translation
        file, so the check follows a rename instead of freezing one wording.
        """
        names = self.translations["entity"]["sensor"]
        expected = {
            "activity": names["last_activity"]["name"],
            "slot-3": names["slot"]["name"].format(slot=3),
            "slot-12": names["slot"]["name"].format(slot=12),
        }
        seen = {}
        for key, wanted in expected.items():
            entity = next(
                (row for row in entities if row["unique_id"] == f"{self.entry_id}-{key}"), None
            )
            if entity is None:
                raise CheckFailed(f"no entity with unique id …-{key}")
            state = await self.api(f"/api/states/{entity['entity_id']}")
            friendly = state["attributes"].get("friendly_name", "")
            if not friendly.endswith(wanted):
                raise CheckFailed(
                    f"{entity['entity_id']} is called {friendly!r}, expected it to end in {wanted!r}"
                )
            seen[entity["entity_id"]] = friendly
        self.record("entity_names_translated", "entity names come from translations/en.json", names=seen)

    async def check_services(self) -> None:
        services = await self.api("/api/services")
        ours = next((row for row in services if row["domain"] == DOMAIN), None)
        if ours is None:
            raise CheckFailed("onesti_lock registered no services")
        missing = [name for name in SERVICES if name not in ours["services"]]
        if missing:
            raise CheckFailed(f"services missing: {', '.join(missing)}")
        if "code" not in ours["services"]["set_pin"].get("fields", {}):
            raise CheckFailed("set_pin has no code field, so services.yaml did not load")
        self.record(
            "services_registered",
            "all four services are registered with the fields from services.yaml",
            services=sorted(ours["services"]),
        )

    async def check_config_flow(self) -> None:
        """Starting the config flow reaches our own code and aborts as documented.

        Without a radio ZHA has no gateway, so zha_not_found is the whole
        answer this container can give. That it is *that* reason, and not an
        unknown error, is what says the flow module imported and ran.
        """
        result = await self.api(
            "/api/config/config_entries/flow",
            {"handler": DOMAIN, "show_advanced_options": False},
        )
        if result.get("type") != "abort" or result.get("reason") != "zha_not_found":
            raise CheckFailed(f"the config flow answered {result.get('type')}/{result.get('reason')}")
        self.record(
            "config_flow_runs", "the config flow starts and aborts with zha_not_found"
        )

    async def check_options_flow(self) -> None:
        result = await self.api("/api/config/config_entries/options/flow", {"handler": self.entry_id})
        if result.get("type") != "menu":
            raise CheckFailed(f"the options flow opened as {result.get('type')}, expected a menu")
        expected = set(self.translations["options"]["step"]["init"]["menu_options"])
        shown = set(result.get("menu_options", []))
        if shown != expected:
            raise CheckFailed(f"the menu shows {sorted(shown)}, translations describe {sorted(expected)}")
        await self.api(
            f"/api/config/config_entries/options/flow/{result['flow_id']}", method="DELETE"
        )
        self.record(
            "options_flow_opens",
            "the PIN management menu opens with every option the translations name",
            menu_options=sorted(shown),
        )

    async def check_translations(self) -> None:
        """The frontend's own translation load finds the ZIP's strings.

        Same call the frontend makes, so a file Home Assistant cannot parse or
        a key it will not accept shows up as a missing string here rather than
        as an empty dialog in front of a user.
        """
        seen = {}
        for category in ("config", "options", "entity", "exceptions"):
            resources = await self.ws(
                "frontend/get_translations",
                language="en",
                category=category,
                integration=[DOMAIN],
            )
            flat = resources["resources"]
            for key, value in _flatten(self.translations.get(category, {})):
                full = f"component.{DOMAIN}.{category}.{key}"
                if flat.get(full) != value:
                    raise CheckFailed(f"{full} did not load ({flat.get(full)!r})")
            seen[category] = sum(1 for key in flat if key.startswith(f"component.{DOMAIN}."))
        self.record("translations_load", "every English string in the ZIP is served to the frontend", counts=seen)

    async def check_blueprints_parse(self) -> None:
        listed = await self.ws("blueprint/list", domain="automation")
        for name in BLUEPRINTS:
            path = f"onesti_lock/{name}"
            entry = listed.get(path)
            if entry is None:
                raise CheckFailed(f"{path} was not picked up by Home Assistant")
            if "error" in entry:
                raise CheckFailed(f"{path} failed to load: {entry['error']}")
        self.record(
            "blueprints_parse",
            f"Home Assistant loaded all {len(BLUEPRINTS)} blueprints without an error",
        )

    async def check_blueprints_instantiate(self, activity_entity: str) -> dict[str, str]:
        """Every blueprint survives HA's own automation validation and runs.

        The config API validates a blueprint automation the way the UI does:
        inputs are substituted and the resulting triggers, conditions and
        actions are validated. A 200 plus a running automation entity means
        the blueprint is usable, not just parseable.
        """
        wanted = {
            "goodnight_lock.yaml": {"lock_entity": STANDIN_LOCK},
            "lock_connectivity_alert.yaml": {"lock_entity": STANDIN_LOCK},
            "unlock_activity_notify.yaml": {"activity_sensor": activity_entity},
        }
        created = {}
        for name, inputs in wanted.items():
            config_id = f"e2e_{name.removesuffix('.yaml')}"
            try:
                await self.api(
                    f"/api/config/automation/config/{config_id}",
                    {
                        "alias": config_id,
                        "use_blueprint": {"path": f"onesti_lock/{name}", "input": inputs},
                    },
                    quote_errors=True,
                )
            except RuntimeError as error:
                raise CheckFailed(f"{name} is not a usable automation: {error}") from error
            created[name] = await self._wait_for_automation(config_id)
        self.record(
            "blueprints_instantiate",
            "an automation from each blueprint validated and is running",
            automations=sorted(created.values()),
        )
        return created

    # -- the blueprints, actually triggered --

    async def _wait(self, what: str, probe: Any) -> Any:
        """Poll until a probe returns something truthy, or give up saying what."""
        deadline = time.monotonic() + PATIENCE_S
        while time.monotonic() < deadline:
            found = await probe()
            if found:
                return found
            await asyncio.sleep(0.25)
        raise CheckFailed(f"{what} (waited {PATIENCE_S} s)")

    async def _write_state(self, entity_id: str, state: str, attributes: dict) -> None:
        """Put a state on the bus the way the lock's own data would arrive.

        There is no radio, so nothing can make the activity sensor move by
        itself, and the lock entity ZHA would own does not exist. Writing the
        state is how the trigger these blueprints listen for is produced; the
        automation that follows is Home Assistant's own, unhelped.
        """
        await self.api(
            f"/api/states/{entity_id}", {"state": state, "attributes": attributes}
        )

    async def _notification(self, needle: str) -> dict | None:
        for notification in await self.ws("persistent_notification/get"):
            if needle in notification.get("message", ""):
                return notification
        return None

    async def check_blueprint_locks_the_door(self, automations: dict[str, str]) -> None:
        """The goodnight blueprint's action reaches the lock it was given.

        Its own trigger is a time of day, which is Home Assistant's to fire,
        so the automation is triggered by hand and what the blueprint does
        after that is read off the stand-in lock.
        """
        await self.api("/api/services/lock/unlock", {"entity_id": STANDIN_LOCK})
        await self._wait(
            "the stand-in lock would not unlock",
            lambda: self._state_is(STANDIN_LOCK, "unlocked"),
        )
        await self.api(
            "/api/services/automation/trigger",
            {"entity_id": automations["goodnight_lock.yaml"], "skip_condition": True},
        )
        await self._wait(
            "the goodnight blueprint ran but the door never locked",
            lambda: self._state_is(STANDIN_LOCK, "locked"),
        )
        self.record(
            "blueprint_goodnight_locks",
            "triggering the goodnight automation locked the stand-in lock",
        )

    async def _state_is(self, entity_id: str, state: str) -> bool:
        return (await self.api(f"/api/states/{entity_id}"))["state"] == state

    async def check_blueprint_notifies_on_return(self) -> None:
        """A lock that comes back from unavailable gets the blueprint's alert.

        The offline half waits out a timer measured in minutes and is not
        worth the wall clock; the return fires at once and runs the same
        choose, the same templates and the same notification call.
        """
        for state in ("unavailable", "locked"):
            await self._write_state(
                STANDIN_LOCK, state, {"friendly_name": STANDIN_NAME}
            )
        notification = await self._wait(
            "the connectivity blueprint sent no notification when the lock returned",
            lambda: self._notification(f"{STANDIN_NAME} is available again"),
        )
        if notification["title"] != "Door lock back online":
            raise CheckFailed(f"the notification is titled {notification['title']!r}")
        if "(locked)" not in notification["message"]:
            raise CheckFailed(f"the notification does not say the new state: {notification['message']!r}")
        self.record(
            "blueprint_connectivity_notifies",
            "a lock returning from unavailable produced the blueprint's own notification",
            message=" ".join(notification["message"].split()),
        )

    async def check_blueprint_notifies_on_unlock(self, activity_entity: str) -> None:
        """Someone unlocking the door reaches the notification a user reads.

        Two writes: the first is the activity the sensor already held, since
        the blueprint ignores a change out of unknown, and it is a lock, which
        its condition filters away. The second is the unlock, and the text
        that comes out is the blueprint's templates run over the activity
        sensor's attributes.
        """
        for action, user in (("lock", "Ola"), ("unlock", "Kari")):
            await self._write_state(
                activity_entity,
                f"{user} {action}ed with code",
                {
                    "friendly_name": "Onesti Lock Last activity",
                    "user_name": user,
                    "user_slot": 3,
                    "action": action,
                    "source": "keypad",
                },
            )
            # mode: single. Let the run the first write starts finish and be
            # filtered out by the condition before the second arrives.
            await asyncio.sleep(0.5)
        notification = await self._wait(
            "the unlock blueprint sent no notification for the unlock",
            lambda: self._notification("Kari unlocked via keypad"),
        )
        if notification["title"] != "Door lock: unlock":
            raise CheckFailed(f"the notification is titled {notification['title']!r}")
        if await self._notification("Ola locked via keypad"):
            raise CheckFailed("the blueprint notified about a lock, with unlock only set")
        self.record(
            "blueprint_unlock_notifies",
            "an unlock on the activity sensor notified who did it and how, and a lock did not",
            message=notification["message"],
        )

    # -- the migration --

    async def stored_entries(self) -> dict[str, dict]:
        """The config entries as they are on disk, keyed by entry id.

        The stored version is the only place the result of a migration shows:
        the API does not report an entry's version. Home Assistant writes the
        store on a delay, so this waits for the 2.2 entry to arrive at the
        installed version rather than reading the file once.
        """
        entry_id = self.seed["migrated"]["entry_id"]
        return await self._wait(
            f"the migrated entry never reached {self._version_text()} on disk",
            lambda: self._entries_once(entry_id),
        )

    def _version_text(self) -> str:
        return "{}.{}".format(*self.entry_version)

    async def _entries_once(self, entry_id: str) -> dict[str, dict] | None:
        rows = {
            row["entry_id"]: row
            for row in json.loads(ENTRY_STORE.read_text(encoding="utf-8"))["data"]["entries"]
        }
        row = rows.get(entry_id, {})
        if (row.get("version"), row.get("minor_version")) == self.entry_version:
            return rows
        return None

    async def check_migrated_entries_load(self, stored: dict[str, dict]) -> None:
        """Every entry below the current version comes up at it, and loaded."""
        entries = await self.api(f"/api/config/config_entries/entry?domain={DOMAIN}")
        states = {row["entry_id"]: row["state"] for row in entries}
        for name in ("current", "migrated", "legacy"):
            entry_id = self.seed[name]["entry_id"]
            row = stored.get(entry_id)
            if row is None:
                raise CheckFailed(f"the {name} entry is not in the store")
            if (row["version"], row["minor_version"]) != self.entry_version:
                raise CheckFailed(
                    f"the {name} entry is stored as "
                    f"{row['version']}.{row['minor_version']}, not {self._version_text()}"
                )
            if states.get(entry_id) != "loaded":
                raise CheckFailed(f"the {name} entry is {states.get(entry_id)}, not loaded")
        self.record(
            "migration_reaches_current_version",
            f"the 2.1 and 2.2 entries migrated to {self._version_text()} and set up",
        )

    async def check_migration_strips_has_rfid(self, stored: dict[str, dict]) -> None:
        """2.1 -> 2.2 drops has_rfid and leaves the rest of the slot alone."""
        legacy = self.seed["legacy"]
        slots = stored[legacy["entry_id"]]["options"]["slots"]
        slot = slots.get(legacy["slot"])
        if slot is None:
            raise CheckFailed(f"slot {legacy['slot']} is gone from the 2.1 entry")
        if "has_rfid" in slot:
            raise CheckFailed(f"the migrated slot still carries has_rfid: {slot}")
        if slot.get("name") != "Per" or slot.get("has_pin") is not True:
            raise CheckFailed(f"the migrated slot lost the user's own data: {slot}")
        self.record(
            "migration_2_1_strips_has_rfid",
            "an entry that skipped 2.2 came through with has_rfid gone and the slot kept",
            slot=slot,
        )

    async def check_registry_keys_rewritten(self, registry: list[dict]) -> None:
        """The 2.2 keys on the IEEE address became keys on the entry id.

        Both registries, and nothing duplicated: a migration that left the old
        unique ids behind would show up here as the seeded rows plus a full
        new set, and as a second device beside the seeded one.
        """
        migrated = self.seed["migrated"]
        entry_id, ieee = migrated["entry_id"], migrated["ieee"]
        ours = [row for row in registry if row.get("config_entry_id") == entry_id]
        if len(ours) != EXPECTED_ENTITIES:
            raise CheckFailed(
                f"{len(ours)} entities on the migrated entry, expected {EXPECTED_ENTITIES}: "
                + ", ".join(sorted(f"{row['entity_id']} ({row['unique_id']})" for row in ours))
            )
        stale = [row["unique_id"] for row in ours if not row["unique_id"].startswith(f"{entry_id}-")]
        if stale:
            raise CheckFailed(f"unique ids that are still not keyed on the entry id: {stale}")
        devices = await self.ws("config/device_registry/list")
        theirs = [row for row in devices if entry_id in row.get("config_entries", [])]
        if len(theirs) != 1:
            raise CheckFailed(
                f"{len(theirs)} devices on the migrated entry: "
                + ", ".join(str(row.get("identifiers")) for row in theirs)
            )
        (device,) = theirs
        if device["id"] != migrated["device_id"]:
            raise CheckFailed("the device was replaced rather than rewritten in place")
        # The device identifier is the other half of the same rewrite. The
        # IEEE address is still the device's serial number, which is where it
        # belongs; what must be gone is the address as a key.
        if [list(pair) for pair in device["identifiers"]] != [[DOMAIN, entry_id]]:
            raise CheckFailed(f"the device identifiers are {device['identifiers']}, not the entry id")
        if any(ieee in row["unique_id"] for row in ours):
            raise CheckFailed("an entity unique id still holds the IEEE address")
        self.record(
            "migration_rewrites_registry_keys",
            f"{len(ours)} entities and one device, all keyed on the entry id and none duplicated",
            device_id=device["id"],
        )

    async def check_migration_keeps_customisation(
        self, registry: list[dict], stored: dict[str, dict]
    ) -> None:
        """What the user renamed, disabled and filled in is still there.

        This is the part of the 2.3 migration a user would notice going
        wrong: entity ids are what their dashboards and automations name, and
        a rename that comes back as the default name is a support thread.
        """
        migrated = self.seed["migrated"]
        entry_id = migrated["entry_id"]
        by_entity_id = {row["entity_id"]: row for row in registry}
        for seeded in migrated["entities"]:
            row = by_entity_id.get(seeded["entity_id"])
            if row is None:
                raise CheckFailed(f"{seeded['entity_id']} did not survive the migration")
            if row["unique_id"] != f"{entry_id}-{seeded['key']}":
                raise CheckFailed(
                    f"{seeded['entity_id']} is keyed {row['unique_id']}, not on the entry id"
                )
            if row["name"] != seeded["name"]:
                raise CheckFailed(
                    f"{seeded['entity_id']} is named {row['name']!r}, not {seeded['name']!r}"
                )
            if row.get("disabled_by") != seeded["disabled_by"]:
                raise CheckFailed(
                    f"{seeded['entity_id']} is disabled by {row.get('disabled_by')!r}, "
                    f"not {seeded['disabled_by']!r}"
                )
        devices = await self.ws("config/device_registry/list")
        (device,) = [row for row in devices if entry_id in row.get("config_entries", [])]
        if device.get("name_by_user") != migrated["device_name"]:
            raise CheckFailed(f"the device is no longer called {migrated['device_name']!r}")
        # What the frontend puts on the renamed entity. A user-set name takes
        # the whole friendly name, so losing it in the migration would show up
        # here as the device name and the translated one instead.
        renamed = next(row for row in migrated["entities"] if row["name"])
        state = await self.api(f"/api/states/{renamed['entity_id']}")
        friendly = state["attributes"].get("friendly_name")
        if friendly != renamed["name"]:
            raise CheckFailed(f"the renamed entity is shown as {friendly!r}")
        # The slot data itself is in the entry, not in the state: without a
        # radio the sensors are unavailable and carry no attributes.
        slots = stored[entry_id]["options"]["slots"]
        if slots != migrated["slots"]:
            raise CheckFailed(f"the slots the user filled in came through as {slots}")
        self.record(
            "migration_keeps_what_the_user_set",
            "entity ids, a rename, a disabled entity, the device name and the slot data survived",
            renamed=friendly,
        )

    async def check_newer_entry_refused(self, registry: list[dict]) -> None:
        """An entry from a newer major version is refused, not guessed at."""
        future = self.seed["future"]
        entries = await self.api(f"/api/config/config_entries/entry?domain={DOMAIN}")
        row = next((row for row in entries if row["entry_id"] == future["entry_id"]), None)
        if row is None:
            raise CheckFailed("the entry from a newer release is gone")
        if row["state"] != "migration_error":
            raise CheckFailed(f"the newer entry is {row['state']}, expected migration_error")
        adopted = [r["entity_id"] for r in registry if r.get("config_entry_id") == future["entry_id"]]
        if adopted:
            raise CheckFailed(f"the refused entry still created entities: {adopted}")
        self.record(
            "newer_entry_refused",
            "an entry written by a newer major version does not load and creates nothing",
        )

    async def _wait_for_automation(self, config_id: str) -> str:
        deadline = time.monotonic() + 60
        last = "not created"
        while time.monotonic() < deadline:
            states = await self.api("/api/states")
            for state in states:
                if state["entity_id"].startswith("automation.") and state["attributes"].get(
                    "id"
                ) == config_id:
                    if state["state"] == "on":
                        return state["entity_id"]
                    last = f"state {state['state']}"
            await asyncio.sleep(0.5)
        raise CheckFailed(f"the automation from {config_id} never started ({last})")

    async def run(self) -> None:
        await self.wait_for_start()
        await self.onboard()
        await self.wait_running()
        await self.check_component_loaded()
        await self.check_entry_loaded()
        entities = await self.check_entities()
        await self.check_entity_names(entities)
        await self.check_services()
        await self.check_config_flow()
        await self.check_options_flow()
        await self.check_translations()
        await self.check_blueprints_parse()
        activity = next(
            row["entity_id"] for row in entities if row["unique_id"] == f"{self.entry_id}-activity"
        )
        automations = await self.check_blueprints_instantiate(activity)
        await self.check_blueprint_locks_the_door(automations)
        await self.check_blueprint_notifies_on_return()
        await self.check_blueprint_notifies_on_unlock(activity)
        # The migration ran at startup, long before any of this. What it left
        # behind is read at the end, so a failure here is about the migration
        # and not about a check that has not run yet.
        stored = await self.stored_entries()
        registry = await self.ws("config/entity_registry/list")
        await self.check_migrated_entries_load(stored)
        await self.check_migration_strips_has_rfid(stored)
        await self.check_registry_keys_rewritten(registry)
        await self.check_migration_keeps_customisation(registry, stored)
        await self.check_newer_entry_refused(registry)


def _flatten(data: Any, prefix: str = "") -> list[tuple[str, str]]:
    """Every leaf string in a translation section, as dotted key and value."""
    if isinstance(data, str):
        return [(prefix, data)]
    if not isinstance(data, dict):
        return []
    out: list[tuple[str, str]] = []
    for key, value in data.items():
        out.extend(_flatten(value, f"{prefix}.{key}" if prefix else key))
    return out


async def main() -> int:
    entry_id = sys.argv[sys.argv.index("--entry-id") + 1]
    async with aiohttp.ClientSession() as session:
        driver = Driver(session, entry_id)
        try:
            await driver.run()
        except (CheckFailed, RuntimeError, aiohttp.ClientError, TimeoutError) as error:
            driver.results.append({"check": "failed", "proof": str(error)})
            REPORT.write_text(json.dumps(driver.results, indent=2))
            print(f"FAILED: {error}", file=sys.stderr, flush=True)
            return 1
        REPORT.write_text(json.dumps(driver.results, indent=2))
        print(f"{len(driver.results)} checks passed", flush=True)
        return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
