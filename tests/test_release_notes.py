"""Tests for scripts/release_notes.py.

The release body is built from CHANGELOG.md. If the extraction breaks, users
get the wrong text or the release fails, so both what is there and what is
missing must behave predictably. The same goes for the rewrites the body gets:
absolute links, the lifted Action required and the compare link.

The short cut, built from bullets marked `<!--short-->`, is what HACS shows. The
section being written fails without a single marked bullet, while shipped
history, which was never marked, gives the whole section instead.
"""

from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

release_notes = importlib.import_module("release_notes")

FAKE_CHANGELOG = """# Changelog

Intro text.

## [2.1.0] - Unreleased

### Features

- Something not shipped <!--short-->

## [2.0.0] - 2026-02-01

### Bug fixes

- **A bullet**: with detail

### Features

- Another bullet

## [1.9.0]

## [1.8.0] - 2026-01-01

- Last section in the file
"""

URL = "https://example.test/owner/repo"


def write(path: Path, text: str) -> Path:
    path.write_text(text, encoding="utf-8")
    return path


class TestFindSection:
    def test_returns_the_section_without_heading_or_neighbours(self):
        section = release_notes.find_section(FAKE_CHANGELOG, "2.0.0")
        assert section is not None
        assert section.startswith("### Bug fixes")
        assert "Another bullet" in section
        assert "## [2.0.0]" not in section
        assert "Something not shipped" not in section
        assert "Last section" not in section

    def test_unreleased_heading_matches(self):
        section = release_notes.find_section(FAKE_CHANGELOG, "2.1.0")
        assert section is not None
        assert "Something not shipped" in section

    def test_last_section_runs_to_the_end_of_the_file(self):
        assert release_notes.find_section(FAKE_CHANGELOG, "1.8.0") == "- Last section in the file"

    def test_empty_section_counts_as_missing(self):
        assert release_notes.find_section(FAKE_CHANGELOG, "1.9.0") is None

    def test_unknown_or_partial_version_gives_none(self):
        assert release_notes.find_section(FAKE_CHANGELOG, "9.9.9") is None
        assert release_notes.find_section(FAKE_CHANGELOG, "2.0") is None

    def test_known_versions_in_file_order(self):
        assert release_notes.known_versions(FAKE_CHANGELOG) == ["2.1.0", "2.0.0", "1.9.0", "1.8.0"]

    def test_previous_version_is_the_one_below(self):
        assert release_notes.previous_version(FAKE_CHANGELOG, "2.0.0") == "1.9.0"
        assert release_notes.previous_version(FAKE_CHANGELOG, "1.8.0") is None


class TestAbsolutizeLinks:
    def _repo(self, tmp_path: Path) -> Path:
        (tmp_path / "docs").mkdir()
        write(tmp_path / "docs" / "debugging.md", "x")
        write(tmp_path / "README.md", "x")
        return tmp_path

    def _run(self, tmp_path: Path, text: str, version: str = "1.4.0") -> str:
        return release_notes.absolutize_links(text, version, repo_root=self._repo(tmp_path), repo_url=URL)

    def test_relative_file_becomes_absolute_against_the_tag(self, tmp_path):
        assert self._run(tmp_path, "[d](docs/debugging.md)") == f"[d]({URL}/blob/v1.4.0/docs/debugging.md)"

    def test_anchor_on_a_file_is_kept(self, tmp_path):
        result = self._run(tmp_path, "[b](./README.md#blueprints)")
        assert result == f"[b]({URL}/blob/v1.4.0/README.md#blueprints)"

    def test_bare_anchor_points_at_changelog(self, tmp_path):
        assert self._run(tmp_path, "[x](#features)") == f"[x]({URL}/blob/v1.4.0/CHANGELOG.md#features)"

    def test_absolute_urls_are_left_alone(self, tmp_path):
        text = "[a](https://example.org/x) [m](mailto:a@b.c) <https://example.org>"
        assert self._run(tmp_path, text) == text

    def test_reference_definition_and_angle_target(self, tmp_path):
        result = self._run(tmp_path, "[x][r] [y](<docs/debugging.md>)\n\n[r]: docs/debugging.md\n")
        assert f"[r]: {URL}/blob/v1.4.0/docs/debugging.md" in result
        assert f"[y]({URL}/blob/v1.4.0/docs/debugging.md)" in result

    def test_dead_links_fail_and_are_all_named(self, tmp_path):
        with pytest.raises(release_notes.DeadLinkError) as err:
            self._run(tmp_path, "[a](docs/gone.md) [b](missing.md) [c](../outside.md)")
        assert "docs/gone.md" in str(err.value)
        assert "missing.md" in str(err.value)
        assert "../outside.md" in str(err.value)


class TestLiftAction:
    SECTION = "### Features\n\n- A feature\n\n### Action required\n\n- Do this\n\n### Bug fixes\n\n- A fix"

    def test_action_moves_to_the_top_and_nothing_is_lost(self):
        lifted = release_notes.lift_action(self.SECTION, "1.4.0")
        assert lifted.startswith("### Action required\n\n- Do this")
        assert lifted.index("### Features") < lifted.index("### Bug fixes")
        assert sorted(lifted.split()) == sorted(self.SECTION.split())

    def test_lead_paragraph_stays_first(self):
        lifted = release_notes.lift_action("Lead.\n\n" + self.SECTION, "1.4.0")
        assert lifted.startswith("Lead.\n\n### Action required\n\n- Do this")

    def test_heading_match_ignores_case(self):
        lifted = release_notes.lift_action("### Features\n\n- A\n\n### ACTION REQUIRED\n\n- B", "1.4.0")
        assert lifted.startswith("### ACTION REQUIRED")

    def test_section_without_action_is_unchanged(self):
        assert release_notes.lift_action("### Features\n\n- A", "1.4.0") == "### Features\n\n- A"

    @pytest.mark.parametrize(
        "section",
        [
            "### Action required\n\n### Features\n\n- A",
            "### Features\n\n- A\n\n### Action required\n",
            "### Action required\n\n   \n\t\n### Features\n\n- A",
        ],
    )
    def test_empty_action_fails(self, section):
        with pytest.raises(release_notes.EmptyActionError) as err:
            release_notes.lift_action(section, "1.4.0")
        assert err.value.version == "1.4.0"


class TestShort:
    SECTION = """Lead line.

### Features

- A feature users notice <!--short-->
- A detail for the full log

### Action required

- Import the blueprints again

### Breaking changes

- A breaking change, change

  ```yaml
  a: 1
  ```

  to this. <!--short-->
- Another detail
"""

    def test_lead_action_and_marked_bullets_under_their_categories(self):
        short = release_notes.build_short(release_notes.lift_action(self.SECTION, "1.4.0"), "1.4.0")
        assert short.startswith("Lead line.")
        assert short.index("### Action required") < short.index("### Features")
        assert "- Import the blueprints again" in short
        assert "A feature users notice" in short
        assert "### Breaking changes\n\n- A breaking change" in short
        assert "a: 1" in short

    def test_unmarked_bullets_and_markers_stay_out(self):
        short = release_notes.build_short(self.SECTION, "1.4.0")
        assert "detail" not in short
        assert "<!--short-->" not in short
        assert "](CHANGELOG.md)" in short

    def test_no_marked_bullet_fails(self):
        with pytest.raises(release_notes.UnmarkedError) as err:
            release_notes.build_short("### Bug fixes\n\n- Nobody marked this\n", "1.4.0")
        assert err.value.version == "1.4.0"

    def test_marker_under_action_does_not_count(self):
        section = "### Action required\n\n- Do it <!--short-->\n\n### Bug fixes\n\n- A fix\n"
        with pytest.raises(release_notes.UnmarkedError):
            release_notes.build_short(section, "1.4.0")

    def test_spaces_inside_the_marker_are_accepted(self):
        assert "A fix" in release_notes.build_short("### Bug fixes\n\n- A fix <!-- short -->\n", "1.4.0")


class TestCli:
    def _repo(self, tmp_path: Path, changelog: str) -> list[str]:
        path = write(tmp_path / "CHANGELOG.md", changelog)
        return ["--changelog", str(path), "--repo-root", str(tmp_path)]

    def test_full_body_has_lifted_action_absolute_links_and_compare_link(self, tmp_path, capsys):
        write(tmp_path / "README.md", "x")
        args = self._repo(
            tmp_path,
            "## [2.0.0] - Unreleased\n\n### Bug fixes\n\n- See [readme](README.md)\n\n"
            "### Action required\n\n- Reload\n\n## [1.0.0] - 2026-01-01\n\n- Old\n",
        )
        assert release_notes.main(["v2.0.0", *args]) == 0
        out = capsys.readouterr().out
        assert out.startswith("### Action required")
        assert "](README.md)" not in out
        assert "/blob/v2.0.0/README.md" in out
        assert out.rstrip().endswith("/compare/v1.0.0...v2.0.0")

    def test_missing_section_exits_1_and_lists_what_is_there(self, tmp_path, capsys):
        assert release_notes.main(["9.9.9", *self._repo(tmp_path, FAKE_CHANGELOG)]) == 1
        err = capsys.readouterr().err
        assert "9.9.9" in err
        assert "2.0.0" in err

    def test_missing_file_exits_1(self, tmp_path, capsys):
        assert release_notes.main(["1.0.0", "--changelog", str(tmp_path / "nope.md")]) == 1
        assert "nope.md" in capsys.readouterr().err

    def test_dead_link_exits_1(self, tmp_path, capsys):
        args = self._repo(tmp_path, "## [3.0.0]\n\n- See [docs](docs/gone.md) <!--short-->\n")
        assert release_notes.main(["3.0.0", *args]) == 1
        assert "docs/gone.md" in capsys.readouterr().err

    def test_empty_action_exits_1(self, tmp_path, capsys):
        args = self._repo(tmp_path, "## [3.0.0]\n\n### Bug fixes\n\n- A fix\n\n### Action required\n")
        assert release_notes.main(["3.0.0", *args]) == 1
        assert "Action required" in capsys.readouterr().err

    def test_short_for_the_section_being_written_needs_markers(self, tmp_path, capsys):
        args = self._repo(tmp_path, "## [3.0.0]\n\n### Bug fixes\n\n- Nobody marked this\n")
        assert release_notes.main(["3.0.0", "--short", *args]) == 1
        err = capsys.readouterr().err
        assert "3.0.0" in err
        assert "<!--short-->" in err

    def test_short_for_shipped_history_gives_the_whole_section(self, tmp_path, capsys):
        args = self._repo(
            tmp_path,
            "## [4.0.0]\n\n- Newer <!--short-->\n\n## [3.0.0]\n\n### Bug fixes\n\n- Nobody marked this\n",
        )
        assert release_notes.main(["3.0.0", "--short", *args]) == 0
        captured = capsys.readouterr()
        assert "Nobody marked this" in captured.out
        assert "shipped" in captured.err


class TestRealChangelog:
    """The extraction has to work on the repo's own file, not only on fixtures."""

    def _changelog(self) -> str:
        return (REPO_ROOT / "CHANGELOG.md").read_text(encoding="utf-8")

    def test_every_section_builds_both_ways(self):
        """A relative link that rots fails here, not in the release job."""
        changelog = self._changelog()
        for version in release_notes.known_versions(changelog):
            assert release_notes.build_body(changelog, version)
            strict = release_notes.is_in_progress(changelog, version)
            assert release_notes.build_short_body(changelog, version, strict=strict)

    def test_manifest_version_has_a_section(self):
        """A bumped manifest without a CHANGELOG section must not reach a release."""
        manifest = json.loads(
            (REPO_ROOT / "custom_components" / "onesti_lock" / "manifest.json").read_text(encoding="utf-8")
        )
        assert manifest["version"] in release_notes.known_versions(self._changelog())

    def test_markers_go_at_the_end_of_a_line(self):
        """At the start of a bullet, GitHub can render the rest as raw text."""
        for line in self._changelog().splitlines():
            if "<!--short-->" in line:
                assert line.rstrip().endswith("<!--short-->"), line

    def test_short_note_stays_short(self):
        changelog = self._changelog()
        version = release_notes.known_versions(changelog)[0]
        short = release_notes.build_short_body(changelog, version)
        assert short is not None
        bullets = [line for line in short.splitlines() if line.startswith("- ")]
        assert len(bullets) <= 15, f"{len(bullets)} bullets is not a short note"

    def test_no_norwegian_left_in_the_changelog(self):
        """The repo is public and English; the early releases had Norwegian commit subjects."""
        text = self._changelog()
        assert not any(char in text for char in "æøåÆØÅ")
