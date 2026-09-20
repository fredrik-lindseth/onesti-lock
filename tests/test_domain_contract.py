"""The domain name is written in a dozen places outside the integration.

manifest.json's `domain` decides the directory Home Assistant loads, the name
of the ZIP HACS installs, and every path the workflows, the justfile and the
scripts spell out by hand. The integration was once called `nimly_pro`, and
after the rename nothing but memory kept the copies together: a path left
behind still looks fine until CI checks out a tree where it does not exist.

This reads the domain once and holds everything else against it. Two small
neighbours ride along, because they are the same kind of rule: the reserved
slot floor that keeps slot 0 unwritable, and the model table in README, which
is the only place a user can look up what SUPPORTED_MODELS knows.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

from .conftest import load_component_module

REPO = Path(__file__).resolve().parents[1]

sys.path.insert(0, str(REPO / "scripts"))

import release_publish  # noqa: E402

const = load_component_module("const")

# Paths that name a component that is not ours. zha-toolkit is a separate HACS
# integration the interrogation runbook asks the user to install.
FOREIGN_COMPONENTS = {"zha_toolkit"}

# Everywhere outside the integration that may spell a custom_components path.
PATH_SOURCES = (
    sorted((REPO / ".github" / "workflows").glob("*.yml"))
    + [REPO / "justfile"]
    + sorted((REPO / "scripts").glob("*.py"))
    + sorted((REPO / "scripts").glob("*.sh"))
)

COMPONENT_PATH = re.compile(r"custom_components/([A-Za-z0-9_]+)")


def _manifest_path() -> Path:
    found = sorted((REPO / "custom_components").glob("*/manifest.json"))
    assert len(found) == 1, f"expected exactly one integration under custom_components/, found {found}"
    return found[0]


def _domain() -> str:
    return json.loads(_manifest_path().read_text(encoding="utf-8"))["domain"]


def _hacs() -> dict:
    return json.loads((REPO / "hacs.json").read_text(encoding="utf-8"))


def test_the_integration_directory_is_named_after_the_domain():
    domain = _domain()
    directory = _manifest_path().parent.name
    assert directory == domain, (
        f"manifest.json says the domain is {domain!r}, but it sits in custom_components/{directory}/. "
        f"Home Assistant loads an integration from the directory named after its domain."
    )


def test_hacs_json_installs_the_zip_named_after_the_domain():
    hacs = _hacs()
    domain = _domain()
    assert hacs["filename"] == f"{domain}.zip", (
        f"hacs.json filename is {hacs['filename']!r}, but the release asset is named from the "
        f"domain and is {domain}.zip. HACS would look for a file the release does not have."
    )


def test_hacs_json_hides_the_default_branch_while_it_installs_a_zip():
    hacs = _hacs()
    if not hacs.get("zip_release"):
        return
    assert hacs.get("hide_default_branch") is True, (
        "hacs.json sets zip_release but not hide_default_branch. Installing the default "
        "branch then 404s, because there is no ZIP on it. Set hide_default_branch to true."
    )


def test_the_release_script_derives_its_paths_from_the_domain():
    domain = _domain()
    assert release_publish.COMPONENT == f"custom_components/{domain}", (
        f"COMPONENT in scripts/release_publish.py is {release_publish.COMPONENT!r}, but the "
        f"domain is {domain!r}. The ZIP would be packed from a directory that does not exist."
    )
    assert release_publish.ASSET_NAME == f"{domain}.zip", (
        f"ASSET_NAME in scripts/release_publish.py is {release_publish.ASSET_NAME!r}, but "
        f"hacs.json fetches {domain}.zip."
    )


def test_every_custom_components_path_outside_the_integration_names_the_domain():
    domain = _domain()
    wrong = []
    for path in PATH_SOURCES:
        text = path.read_text(encoding="utf-8")
        for number, line in enumerate(text.splitlines(), start=1):
            for name in COMPONENT_PATH.findall(line):
                if name != domain and name not in FOREIGN_COMPONENTS:
                    wrong.append(f"{path.relative_to(REPO)}:{number} names custom_components/{name}")
    assert not wrong, (
        f"The domain is {domain!r}, so every path outside the integration must be "
        f"custom_components/{domain}. These are not:\n  " + "\n  ".join(wrong)
    )


def test_the_deploy_script_copies_the_domain_directory():
    domain = _domain()
    text = (REPO / "scripts" / "deploy_ha.sh").read_text(encoding="utf-8")
    match = re.search(r'^COMPONENT="([^"]+)"', text, re.MULTILINE)
    assert match, "scripts/deploy_ha.sh no longer sets COMPONENT, so this rule checks nothing"
    assert match.group(1) == domain, (
        f"scripts/deploy_ha.sh sets COMPONENT={match.group(1)!r}, but the domain is {domain!r}. "
        f"It would copy a directory that does not exist and leave Home Assistant untouched."
    )


def test_slot_zero_stays_out_of_reach():
    assert const.RESERVED_SLOTS_MIN >= 1, (
        f"RESERVED_SLOTS_MIN is {const.RESERVED_SLOTS_MIN}. At 0 the first user slot can be 0, "
        f"which is the master slot on every model, and set_pin would overwrite it. Keep it at 1."
    )


def test_every_supported_model_is_in_the_readme_table():
    readme = (REPO / "README.md").read_text(encoding="utf-8")
    rows = {line.split("|")[1].strip() for line in readme.splitlines() if line.startswith("| ") and "|" in line[2:]}
    missing = [model for model in const.SUPPORTED_MODELS if model not in rows]
    assert not missing, (
        f"SUPPORTED_MODELS in const.py has {missing}, but the model table in README.md has no row "
        f"for them. The table is where a user looks up whether their lock is known."
    )
