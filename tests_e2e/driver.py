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
import sys
import time
from pathlib import Path
from typing import Any

import aiohttp

BASE = "http://127.0.0.1:8123"
INSTALLED = Path("/config/custom_components/onesti_lock")
AUTH = Path("/config/e2e-auth.json")
REPORT = Path("/config/report.json")
DOMAIN = "onesti_lock"
SERVICES = ("set_pin", "clear_pin", "set_name", "clear_slot")
# 10 user slots, the activity sensor, and the three capability sensors.
EXPECTED_ENTITIES = 14
BLUEPRINTS = ("goodnight_lock.yaml", "lock_connectivity_alert.yaml", "unlock_activity_notify.yaml")


class CheckFailed(AssertionError):
    """A named check that did not hold."""


class Driver:
    def __init__(self, session: aiohttp.ClientSession, entry_id: str):
        self.session = session
        self.entry_id = entry_id
        self.token = ""
        self.results: list[dict[str, Any]] = []
        self.translations = json.loads(
            (INSTALLED / "translations/en.json").read_text(encoding="utf-8")
        )

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

    async def check_blueprints_instantiate(self, activity_entity: str) -> None:
        """Every blueprint survives HA's own automation validation and runs.

        The config API validates a blueprint automation the way the UI does:
        inputs are substituted and the resulting triggers, conditions and
        actions are validated. A 200 plus a running automation entity means
        the blueprint is usable, not just parseable.
        """
        wanted = {
            "goodnight_lock.yaml": {"lock_entity": "lock.e2e_stand_in"},
            "lock_connectivity_alert.yaml": {"lock_entity": "lock.e2e_stand_in"},
            "unlock_activity_notify.yaml": {"activity_sensor": activity_entity},
        }
        created = []
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
            created.append(await self._wait_for_automation(config_id))
        self.record(
            "blueprints_instantiate",
            "an automation from each blueprint validated and is running",
            automations=created,
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
        await self.check_blueprints_instantiate(activity)


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
