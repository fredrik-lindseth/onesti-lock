"""Blueprint inputs used in templates must be bound as variables.

HA exposes blueprint inputs only as the `!input` YAML tag, not as template
variables. A template that names an input directly renders it as undefined,
so a filter like `{% if only_unlock %}` silently never applies. Each input a
template refers to therefore needs a `name: !input name` line under the
top-level `variables:` block.

CI installs only ruff and pytest, so this reads the files with regular
expressions instead of PyYAML. The blueprints are small and regularly laid
out, and the sanity test below fails if the parsing stops finding inputs.
"""
from __future__ import annotations

import pathlib
import re

import pytest

BLUEPRINT_DIR = pathlib.Path(__file__).parent.parent / "blueprints" / "automation"
BLUEPRINTS = sorted(BLUEPRINT_DIR.glob("*.yaml"))

INPUT_KEY_RE = re.compile(r"^    (\w+):", re.MULTILINE)
BINDING_RE = re.compile(r"^  (\w+): !input (\w+)\s*$", re.MULTILINE)
TEMPLATE_RE = re.compile(r"\{\{.*?\}\}|\{%.*?%\}", re.DOTALL)
QUOTED_RE = re.compile(r"'[^']*'|\"[^\"]*\"")
IDENT_RE = re.compile(r"\b[A-Za-z_]\w*\b")


def _split(text: str) -> tuple[str, str]:
    """Return the `blueprint:` header and the automation body after it."""
    match = re.search(r"\n(?=\S)", text)
    assert match, "blueprint has no body after the header"
    return text[: match.end()], text[match.end() :]


def _inputs(header: str) -> set[str]:
    _, _, after = header.partition("\n  input:\n")
    return set(INPUT_KEY_RE.findall(after))


def _bound(body: str) -> set[str]:
    match = re.search(r"^variables:\n((?:  .*\n|#.*\n|\n)*)", body, re.MULTILINE)
    if not match:
        return set()
    return {name for name, source in BINDING_RE.findall(match.group(1)) if name == source}


def _template_names(body: str) -> set[str]:
    names: set[str] = set()
    for template in TEMPLATE_RE.findall(body):
        names.update(IDENT_RE.findall(QUOTED_RE.sub("", template)))
    return names


def test_blueprints_found():
    assert BLUEPRINTS, f"no blueprints under {BLUEPRINT_DIR}"


@pytest.mark.parametrize("path", BLUEPRINTS, ids=lambda p: p.name)
def test_inputs_are_parsed(path):
    header, _ = _split(path.read_text(encoding="utf-8"))
    assert _inputs(header), f"{path.name}: parsed no inputs, the regex is out of date"


@pytest.mark.parametrize("path", BLUEPRINTS, ids=lambda p: p.name)
def test_inputs_used_in_templates_are_bound(path):
    header, body = _split(path.read_text(encoding="utf-8"))
    unbound = (_inputs(header) & _template_names(body)) - _bound(body)
    assert not unbound, (
        f"{path.name}: inputs used in templates without a variables binding: "
        f"{sorted(unbound)}"
    )
