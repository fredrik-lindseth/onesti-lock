"""Every document in docs/ has a row in the documentation map, and every row has a document.

The map is how an agent finds out what is already written down before it
writes the same thing again, and it rots quietly: a new file under docs/ is
simply absent from it, and a renamed one leaves a row pointing at nothing. Two
rows were missing the day this was written, and nothing said so.

The table is found by its heading rather than by file, so it can move out of
AGENTS.md and into a document of its own without this test becoming wrong.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
DOCS = REPO / "docs"

HEADING = re.compile(r"^#+\s+Documentation map\s*$", re.IGNORECASE)
NEXT_HEADING = re.compile(r"^#+\s")
# The first cell of a table row, when it is a backticked path.
ROW_PATH = re.compile(r"^\|\s*`([^`]+)`\s*\|")

# Vendor manuals are copyright and gitignored; only their index is tracked.
IGNORED = ("docs/manuals/",)
KEPT = ("docs/manuals/README.md",)


def _map_rows() -> tuple[Path, set[str]]:
    """The file holding the documentation map, and the paths its rows name."""
    candidates = [REPO / "AGENTS.md", REPO / "README.md", *sorted(DOCS.rglob("*.md"))]
    for candidate in candidates:
        if not candidate.is_file():
            continue
        lines = candidate.read_text(encoding="utf-8").splitlines()
        for index, line in enumerate(lines):
            if not HEADING.match(line):
                continue
            rows = set()
            for row in lines[index + 1 :]:
                if NEXT_HEADING.match(row):
                    break
                match = ROW_PATH.match(row)
                if match:
                    rows.add(match.group(1))
            return candidate, rows
    raise AssertionError(
        "No file holds a 'Documentation map' heading. It was in AGENTS.md; if it moved, it kept "
        "neither the heading nor this test, and nothing now says which documents exist."
    )


def _tracked_docs() -> list[str]:
    found = []
    for path in sorted(DOCS.rglob("*.md")):
        relative = path.relative_to(REPO).as_posix()
        if relative.startswith(IGNORED) and relative not in KEPT:
            continue
        found.append(relative)
    return found


def test_every_document_has_a_row_in_the_map():
    where, rows = _map_rows()
    missing = [doc for doc in _tracked_docs() if doc not in rows]
    assert not missing, (
        f"The documentation map in {where.relative_to(REPO)} has no row for {missing}. Add one line "
        f"per file saying what is in it, or an agent will write the same document a second time."
    )


def test_every_row_in_the_map_points_at_a_file():
    where, rows = _map_rows()
    gone = sorted(row for row in rows if not (REPO / row).exists())
    assert not gone, (
        f"The documentation map in {where.relative_to(REPO)} has rows for {gone}, which do not "
        f"exist. A renamed or deleted document leaves the row behind."
    )
