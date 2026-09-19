"""Hold quality_scale.yaml to the rules hassfest enforces for core integrations.

hassfest skips quality_scale.yaml for custom integrations (validate_iqs_file
returns early when the integration is not core), so nothing upstream checks
ours. This test mirrors that validation: the same rule list, the same schema,
and the same tier check against manifest.json's quality_scale key.

The rule list is copied from script/hassfest/quality_scale.py in
home-assistant/core at dev 40fcd7dc6b37781291745e3d6c39601563e87349
(2026-09-19). A rule added upstream is a deliberate update here: copy the new
list, bump the commit above, and give the rule a status in the yaml.

tests/ runs without PyYAML, so the file is read by a small parser that
understands exactly the flat shape the file uses and fails on anything else.
"""

import json
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
COMPONENT = REPO / "custom_components" / "onesti_lock"
QUALITY_SCALE = COMPONENT / "quality_scale.yaml"
MANIFEST = COMPONENT / "manifest.json"

TIERS = ("bronze", "silver", "gold", "platinum")

RULES_BY_TIER = {
    "bronze": (
        "action-setup",
        "appropriate-polling",
        "brands",
        "common-modules",
        "config-flow",
        "config-flow-test-coverage",
        "dependency-transparency",
        "docs-actions",
        "docs-conditions",
        "docs-high-level-description",
        "docs-installation-instructions",
        "docs-removal-instructions",
        "docs-triggers",
        "entity-event-setup",
        "entity-unique-id",
        "has-entity-name",
        "runtime-data",
        "test-before-configure",
        "test-before-setup",
        "unique-config-entry",
    ),
    "silver": (
        "action-exceptions",
        "config-entry-unloading",
        "docs-configuration-parameters",
        "docs-installation-parameters",
        "entity-unavailable",
        "integration-owner",
        "log-when-unavailable",
        "parallel-updates",
        "reauthentication-flow",
        "test-coverage",
    ),
    "gold": (
        "devices",
        "diagnostics",
        "discovery",
        "discovery-update-info",
        "docs-data-update",
        "docs-examples",
        "docs-known-limitations",
        "docs-supported-devices",
        "docs-supported-functions",
        "docs-troubleshooting",
        "docs-use-cases",
        "dynamic-devices",
        "entity-category",
        "entity-device-class",
        "entity-disabled-by-default",
        "entity-translations",
        "exception-translations",
        "icon-translations",
        "reconfiguration-flow",
        "repair-issues",
        "stale-devices",
    ),
    "platinum": (
        "async-dependency",
        "inject-websession",
        "strict-typing",
    ),
}
ALL_RULES = [rule for tier in TIERS for rule in RULES_BY_TIER[tier]]


def parse_quality_scale(text: str) -> dict:
    """Parse the flat yaml shape quality_scale.yaml uses.

    Accepted: a top-level `rules:` mapping whose entries are either
    `rule: status` or a nested mapping of `status:` and `comment:`, where the
    comment is a plain scalar or a `|` block. Blank lines and `#` comment
    lines are skipped. Anything else raises ValueError, so a construct this
    parser does not understand can never be read as something it is not.
    """
    data: dict = {}
    rules: dict | None = None
    current: dict | None = None
    block_key: str | None = None
    block_lines: list[str] = []
    block_indent: int | None = None

    def close_block() -> None:
        nonlocal block_key, block_lines, block_indent
        if block_key is not None:
            current[block_key] = "\n".join(block_lines).rstrip("\n") + "\n"
        block_key, block_lines, block_indent = None, [], None

    for number, raw in enumerate(text.splitlines(), start=1):
        line = raw.rstrip()
        indent = len(line) - len(line.lstrip(" "))
        if "\t" in raw[: len(raw) - len(raw.lstrip())]:
            raise ValueError(f"line {number}: tab in indentation")

        if block_key is not None:
            if not line:
                block_lines.append("")
                continue
            if block_indent is None:
                if indent <= 4:
                    raise ValueError(f"line {number}: empty block scalar")
                block_indent = indent
            if indent >= block_indent:
                block_lines.append(line[block_indent:])
                continue
            close_block()

        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        key, sep, value = stripped.partition(":")
        if not sep or not key or " " in key:
            raise ValueError(f"line {number}: expected `key: value`, got {stripped!r}")
        value = value.strip()

        if indent == 0:
            if key in data:
                raise ValueError(f"line {number}: duplicate top-level key {key!r}")
            if value:
                raise ValueError(f"line {number}: top-level {key!r} must be a mapping")
            rules = data[key] = {}
            current = None
        elif indent == 2:
            if rules is None:
                raise ValueError(f"line {number}: rule before `rules:`")
            if key in rules:
                raise ValueError(f"line {number}: duplicate rule {key!r}")
            if value:
                rules[key] = value
                current = None
            else:
                current = rules[key] = {}
        elif indent == 4:
            if current is None:
                raise ValueError(f"line {number}: nested key outside a rule mapping")
            if key in current:
                raise ValueError(f"line {number}: duplicate key {key!r}")
            if value == "|":
                block_key = key
            elif value:
                current[key] = value
            else:
                raise ValueError(f"line {number}: {key!r} has no value")
        else:
            raise ValueError(f"line {number}: unexpected indentation {indent}")

    close_block()
    return data


def schema_errors(data: dict) -> list[str]:
    """The errors hassfest's SCHEMA would report for this data."""
    errors = []
    if set(data) != {"rules"}:
        errors.append(f"top-level keys must be exactly ['rules'], got {sorted(data)}")
    rules = data.get("rules", {})
    for rule in ALL_RULES:
        if rule not in rules:
            errors.append(f"missing rule {rule}")
    for rule, value in rules.items():
        if rule not in ALL_RULES:
            errors.append(f"unknown rule {rule}")
            continue
        if isinstance(value, str):
            if value not in {"todo", "done"}:
                errors.append(f"{rule}: {value!r} must be todo or done, or a mapping with a comment")
            continue
        if set(value) != {"status", "comment"}:
            errors.append(f"{rule}: mapping must have exactly status and comment, got {sorted(value)}")
            continue
        if value["status"] not in {"todo", "done", "exempt"}:
            errors.append(f"{rule}: unknown status {value['status']!r}")
        if not value["comment"].strip():
            errors.append(f"{rule}: comment is empty")
    return errors


def status(value) -> str:
    return value["status"] if isinstance(value, dict) else value


def tier_errors(rules: dict, declared: str | None) -> list[str]:
    """Rules not yet done or exempt at or below the declared tier, as hassfest reports them."""
    if declared not in TIERS:
        return []
    met = {rule for rule, value in rules.items() if status(value) in {"done", "exempt"}}
    errors = []
    for tier in TIERS[: TIERS.index(declared) + 1]:
        missing = sorted(set(RULES_BY_TIER[tier]) - met)
        if missing:
            errors.append(f"tier {tier} requires: {', '.join(missing)}")
    return errors


def _data() -> dict:
    return parse_quality_scale(QUALITY_SCALE.read_text(encoding="utf-8"))


def test_rule_list_matches_hassfest() -> None:
    assert len(ALL_RULES) == 54
    assert len(set(ALL_RULES)) == 54


def test_file_matches_hassfest_schema() -> None:
    assert schema_errors(_data()) == []


def test_rules_in_hassfest_order() -> None:
    # Not a hassfest requirement, but a file in the same order as the list is
    # the only way a reviewer can check it by eye.
    assert list(_data()["rules"]) == ALL_RULES


def test_declared_tier_is_met() -> None:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    declared = manifest.get("quality_scale")
    assert declared in (None, *TIERS, "internal", "legacy"), declared
    assert tier_errors(_data()["rules"], declared) == []


class TestGateItself:
    """The checks above only mean something if they fail on a broken file."""

    def full(self, value="done") -> dict:
        return {"rules": dict.fromkeys(ALL_RULES, value)}

    def test_missing_rule_fails(self) -> None:
        data = self.full()
        del data["rules"]["brands"]
        assert schema_errors(data) == ["missing rule brands"]

    def test_unknown_rule_fails(self) -> None:
        data = self.full()
        data["rules"]["made-up"] = "done"
        assert schema_errors(data) == ["unknown rule made-up"]

    def test_exempt_without_comment_fails(self) -> None:
        data = self.full()
        data["rules"]["brands"] = "exempt"
        assert schema_errors(data)
        data["rules"]["brands"] = {"status": "exempt"}
        assert schema_errors(data)
        data["rules"]["brands"] = {"status": "exempt", "comment": "  \n"}
        assert schema_errors(data)

    def test_unknown_status_fails(self) -> None:
        data = self.full()
        data["rules"]["brands"] = {"status": "skipped", "comment": "no"}
        assert schema_errors(data)

    def test_extra_key_fails(self) -> None:
        data = self.full()
        data["rules"]["brands"] = {"status": "done", "comment": "x", "note": "y"}
        assert schema_errors(data)
        data = self.full()
        data["extra"] = {}
        assert schema_errors(data)

    def test_declared_tier_needs_every_rule_up_to_it(self) -> None:
        rules = self.full()["rules"]
        rules["strict-typing"] = "todo"
        assert tier_errors(rules, "gold") == []
        assert tier_errors(rules, "platinum") == ["tier platinum requires: strict-typing"]
        rules["brands"] = "todo"
        assert tier_errors(rules, "bronze") == ["tier bronze requires: brands"]
        assert tier_errors(rules, None) == []

    def test_exempt_counts_as_met(self) -> None:
        rules = self.full({"status": "exempt", "comment": "n/a"})["rules"]
        assert tier_errors(rules, "platinum") == []


class TestParser:
    def test_block_and_plain_values(self) -> None:
        text = "rules:\n  # c\n  a: done\n  b:\n    status: exempt\n    comment: |\n      one\n\n      two\n  c:\n    status: todo\n    comment: plain\n"
        assert parse_quality_scale(text) == {
            "rules": {
                "a": "done",
                "b": {"status": "exempt", "comment": "one\n\ntwo\n"},
                "c": {"status": "todo", "comment": "plain"},
            }
        }

    @pytest.mark.parametrize(
        "text",
        [
            "rules:\n  a: done\n  a: todo\n",
            "rules:\n   a: done\n",
            "rules:\n  - a\n",
            "a: done\n",
            "rules:\n  b:\n    comment: |\n  c: done\n",
            "rules:\n\ta: done\n",
        ],
    )
    def test_rejects_what_it_does_not_understand(self, text: str) -> None:
        with pytest.raises(ValueError):
            parse_quality_scale(text)

    def test_agrees_with_pyyaml_when_available(self) -> None:
        yaml = pytest.importorskip("yaml")
        text = QUALITY_SCALE.read_text(encoding="utf-8")
        assert parse_quality_scale(text) == yaml.safe_load(text)
