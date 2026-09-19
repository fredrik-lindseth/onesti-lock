#!/usr/bin/env python3
"""Print the release notes for one version, taken from CHANGELOG.md.

The `## [X.Y.Z]` section in CHANGELOG.md is the release note. The text lives
in the repo, so it is reviewed with the code and cannot vanish with a
hand-edited GitHub release.

The output differs from the raw section in three ways:

* Relative links become absolute URLs pinned to the release tag. In the repo
  `](docs/debugging.md)` works, but in a release body it resolves against
  `/releases/tag/` and is dead. The tag, not `main`, keeps the link showing
  the file as it was at the release.
* `### Action required` becomes the first category, right after any lead
  paragraph, wherever it was written, so a step the user has to take is not
  buried under Bug fixes.
* The compare link against the previous version in the file comes last.

`--short` prints a second cut of the same text: the lead paragraph, all of
`### Action required`, the bullets marked with `<!--short-->` under their own
category headings, and a link to the full changelog. That is the release
body, which HACS shows in a narrow update panel inside Home Assistant. Both
cuts come from CHANGELOG.md, so there is still one text to write.

Usage:
    python3 scripts/release_notes.py 1.4.0
    python3 scripts/release_notes.py 1.4.0 --short
    python3 scripts/release_notes.py 1.4.0 --changelog path/to/CHANGELOG.md

Prints to stdout and exits 0. Exits 1 with a message on stderr when the
section is missing or empty, a relative link points at a file that does not
exist, or `### Action required` has no bullets under it, so a workflow stops
instead of publishing an empty release, a dead link or a bare heading. With
`--short`, the top section (the one being written) also fails when no bullet
carries the marker, since an empty short note is worse than none.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from urllib.parse import quote

REPO_ROOT = Path(__file__).resolve().parent.parent
CHANGELOG = REPO_ROOT / "CHANGELOG.md"
REPO_URL = "https://github.com/fredrik-lindseth/onesti-lock"

# The category for steps the user must take after upgrading.
ACTION = "Action required"

# Marks a bullet for the short note. An HTML comment is invisible when
# CHANGELOG.md is rendered on GitHub. It goes last in the bullet: placed first,
# GitHub sometimes renders the rest of the line as raw text.
#
#     - **Every slot can be named.** ... <!--short-->
MARKER_TEXT = "<!--short-->"
MARKER = re.compile(r"[ \t]*<!--\s*short\s*-->")

# "## [1.3.0] - 2026-08-23" and "## [1.4.0] - Unreleased" are both in use.
SECTION = re.compile(r"^## \[(?P<version>[^\]]+)\]\s*(?:-\s*\S.*?)?\s*$")

# A category heading such as "### Bug fixes".
CATEGORY = re.compile(r"^### +(?P<name>.+?)\s*$")

BULLET = re.compile(r"^[-*] +\S")

# Markdown links and images: `](target)` with an optional title. A target in
# angle brackets is the only way to write a path with spaces.
LINK = re.compile(r"\]\((?:<(?P<angle>[^<>\n]*)>|(?P<target>[^)\s]+))(?P<title>\s+\"[^\"]*\")?\)")

# Reference definition: `[ref]: target "title"` on its own line. The link
# itself (`[text][ref]`) carries no target, so this is where it gets rewritten.
REFERENCE = re.compile(
    r"^(?P<pre>\s{0,3}\[[^\]\n]+\]:[ \t]*)"
    r"(?:<(?P<angle>[^<>\n]*)>|(?P<target>\S+))"
    r"(?P<title>[ \t]+(?:\"[^\"\n]*\"|\'[^\'\n]*\'|\([^)\n]*\)))?[ \t]*$",
    re.MULTILINE,
)

# "https:", "mailto:" and "//example.com" are already absolute.
ABSOLUTE = re.compile(r"^(?:[a-zA-Z][a-zA-Z0-9+.\-]*:|//)")


class DeadLinkError(Exception):
    """A relative link points at something that is not in the repo."""


class EmptyActionError(Exception):
    """`### Action required` has no content under it."""

    def __init__(self, version: str, heading: str) -> None:
        super().__init__(f"the section for {version} has '{heading}' with nothing under it")
        self.version = version
        self.heading = heading


class UnmarkedError(Exception):
    """A section has no bullet marked for the short note."""

    def __init__(self, version: str) -> None:
        super().__init__(f"the section for {version} has no bullet marked with {MARKER_TEXT}")
        self.version = version


def find_section(changelog: str, version: str) -> str | None:
    """The text under `## [version]`, without the heading itself.

    None when the version has no section, or a section with no text: a
    release without notes is no better than a missing section.
    """
    lines = changelog.splitlines()
    start: int | None = None
    end = len(lines)

    for number, line in enumerate(lines):
        match = SECTION.match(line)
        if not match:
            continue
        if start is None:
            if match.group("version") == version:
                start = number + 1
        else:
            end = number
            break

    if start is None:
        return None

    text = "\n".join(lines[start:end]).strip("\n")
    return text if text.strip() else None


def known_versions(changelog: str) -> list[str]:
    """Every version with a section, newest first as the file lists them."""
    return [m.group("version") for line in changelog.splitlines() if (m := SECTION.match(line))]


def previous_version(changelog: str, version: str) -> str | None:
    """The version listed right below this one, which it is compared against."""
    versions = known_versions(changelog)
    if version not in versions:
        return None
    index = versions.index(version)
    return versions[index + 1] if index + 1 < len(versions) else None


def is_in_progress(changelog: str, version: str) -> bool:
    """Whether this is the top section, the one being written.

    Everything below it has shipped. History is not marked after the fact, so
    the marker check applies to the top section only.
    """
    versions = known_versions(changelog)
    return bool(versions) and versions[0] == version


def _absolute_url(target: str, tag: str, repo_root: Path, repo_url: str, dead: list[str]) -> str:
    """One link target made absolute. Missing files are collected in `dead`."""
    if ABSOLUTE.match(target):
        return target

    if target.startswith("#"):
        # An anchor in CHANGELOG.md itself. The release page has none of the
        # rest of the file, so point at the file in the repo.
        return f"{repo_url}/blob/{tag}/CHANGELOG.md{target}"

    path, _, anchor = target.partition("#")
    path = path.removeprefix("./")
    if not path:
        dead.append(target)
        return target

    resolved = (repo_root / path).resolve()
    try:
        relative = resolved.relative_to(repo_root.resolve())
    except ValueError:
        dead.append(target)
        return target
    if not resolved.exists():
        dead.append(target)
        return target

    url = f"{repo_url}/blob/{tag}/{quote(relative.as_posix())}"
    return f"{url}#{anchor}" if anchor else url


def absolutize_links(
    text: str,
    version: str,
    *,
    repo_root: Path = REPO_ROOT,
    repo_url: str = REPO_URL,
) -> str:
    """Make relative links absolute against the release tag.

    Covers inline links and images, targets in angle brackets and reference
    definitions. Autolinks (`<https://...>`) need a scheme to be links at all,
    so they are always absolute and left alone. Raises DeadLinkError when a
    relative link points at nothing, listing every such target.
    """
    tag = f"v{version}"
    dead: list[str] = []

    def new_target(match: re.Match[str]) -> str:
        angle = match.group("angle")
        if angle is None:
            return _absolute_url(match.group("target"), tag, repo_root, repo_url, dead)
        target = _absolute_url(angle, tag, repo_root, repo_url, dead)
        # An absolute URL has no spaces and needs no brackets; an untouched
        # target keeps them.
        return f"<{target}>" if target == angle else target

    def replace_link(match: re.Match[str]) -> str:
        return f"]({new_target(match)}{match.group('title') or ''})"

    def replace_reference(match: re.Match[str]) -> str:
        return f"{match.group('pre')}{new_target(match)}{match.group('title') or ''}"

    result = REFERENCE.sub(replace_reference, text)
    result = LINK.sub(replace_link, result)

    if dead:
        raise DeadLinkError(", ".join(dict.fromkeys(dead)))
    return result


def _is_action(name: str | None) -> bool:
    return name is not None and name.casefold() == ACTION.casefold()


def lift_action(text: str, version: str) -> str:
    """Make `### Action required` the first category of the section.

    The order in CHANGELOG.md should not decide whether the user sees it.
    Text without the category comes back unchanged. The category with no
    content raises EmptyActionError: lifted to the top of a published
    release, a bare heading looks broken and alarms people for nothing.
    """
    lines = text.splitlines()
    start: int | None = None
    end = len(lines)

    for number, line in enumerate(lines):
        match = CATEGORY.match(line)
        if not match:
            continue
        if start is None:
            if _is_action(match.group("name")):
                start = number
        else:
            end = number
            break

    if start is None:
        return text

    if not any(line.strip() for line in lines[start + 1 : end]):
        raise EmptyActionError(version, lines[start].strip())

    # The lead paragraph, if any, stays first: the category goes in front of
    # the first category heading, not in front of the lead.
    first = next(number for number, line in enumerate(lines) if CATEGORY.match(line))
    if start == first:
        return text

    block = list(lines[start:end])
    while block and not block[-1].strip():
        block.pop()
    lead = lines[:first]
    rest = lines[first:start] + lines[end:]
    while rest and not rest[-1].strip():
        rest.pop()

    return "\n".join([*lead, *block, "", *rest]).strip("\n")


def split_categories(text: str) -> tuple[str, list[tuple[str, list[str]]]]:
    """Split a section into its lead text and (category, bullets) pairs.

    The lead is whatever stands before the first `###` heading. A bullet is
    the line starting with `-` or `*` plus the lines below it up to the next
    bullet, heading or blank line, so a wrapped bullet stays whole. An
    indented block after a blank line (a YAML example under a bullet) belongs
    to the bullet too.
    """
    lead: list[str] = []
    categories: list[tuple[str, list[str]]] = []
    current: list[str] | None = None

    def close() -> None:
        nonlocal current
        if current is not None:
            while current and not current[-1].strip():
                current.pop()
            categories[-1][1].append("\n".join(current))
            current = None

    for line in text.splitlines():
        match = CATEGORY.match(line)
        if match:
            close()
            categories.append((match.group("name"), []))
            continue
        if not categories:
            lead.append(line)
            continue
        if BULLET.match(line):
            close()
            current = [line]
            continue
        if current is not None and (line.strip() == "" or line.startswith((" ", "\t"))):
            current.append(line)
            continue
        close()

    close()
    return "\n".join(lead).strip("\n"), categories


def strip_markers(text: str) -> str:
    """Remove `<!--short-->` from text that is going out."""
    return MARKER.sub("", text)


def marked_bullets(section: str) -> list[tuple[str, list[str]]]:
    """The marked bullets per category, outside `### Action required`.

    Action required goes into the short note whole, so a marker there adds
    nothing and does not count.
    """
    _, categories = split_categories(section)
    result = []
    for name, bullets in categories:
        if _is_action(name):
            continue
        marked = [bullet for bullet in bullets if MARKER.search(bullet)]
        if marked:
            result.append((name, marked))
    return result


def build_short(section: str, version: str) -> str:
    """The short note: lead, Action required, marked bullets, changelog link.

    Raises UnmarkedError when no bullet is marked. A note that only says "see
    the changelog" tells the reader less than nothing.
    """
    lead, categories = split_categories(section)
    marked = marked_bullets(section)
    if not marked:
        raise UnmarkedError(version)

    parts: list[str] = []
    if lead:
        parts += [lead, ""]
    for name, bullets in categories:
        if _is_action(name) and bullets:
            parts += [f"### {name}", "", *bullets, ""]
    for name, bullets in marked:
        parts += [f"### {name}", "", *bullets, ""]
    parts.append("Every change in this release is in [CHANGELOG.md](CHANGELOG.md).")
    return strip_markers("\n".join(parts))


def _with_compare_link(body: str, changelog: str, version: str, repo_url: str) -> str:
    previous = previous_version(changelog, version)
    if previous is None:
        return body
    return f"{body}\n\n---\n\n**Full changelog**: {repo_url}/compare/v{previous}...v{version}"


def build_body(
    changelog: str,
    version: str,
    *,
    repo_root: Path = REPO_ROOT,
    repo_url: str = REPO_URL,
) -> str | None:
    """The whole section with Action required lifted and absolute links."""
    section = find_section(changelog, version)
    if section is None:
        return None
    body = strip_markers(lift_action(section, version))
    body = absolutize_links(body, version, repo_root=repo_root, repo_url=repo_url)
    return _with_compare_link(body, changelog, version, repo_url)


def build_short_body(
    changelog: str,
    version: str,
    *,
    repo_root: Path = REPO_ROOT,
    repo_url: str = REPO_URL,
    strict: bool = True,
) -> str | None:
    """The short release body with absolute links.

    `strict=False` falls back to the whole section when nothing is marked.
    That is the answer for a shipped version: it was written before markers
    existed, and an old note should still be printable.
    """
    section = find_section(changelog, version)
    if section is None:
        return None
    lifted = lift_action(section, version)
    try:
        short = build_short(lifted, version)
    except UnmarkedError:
        if strict:
            raise
        short = strip_markers(lifted)
    short = absolutize_links(short, version, repo_root=repo_root, repo_url=repo_url)
    return _with_compare_link(short, changelog, version, repo_url)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Print the CHANGELOG.md section for a version.")
    parser.add_argument("version", help="the version, with or without a v prefix, e.g. 1.4.0")
    parser.add_argument("--changelog", type=Path, default=CHANGELOG, help="path to CHANGELOG.md")
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=REPO_ROOT,
        help="root that relative links are checked against (default: this repo)",
    )
    parser.add_argument(
        "--short",
        action="store_true",
        help="only the lead, Action required and the marked bullets, plus a changelog link",
    )
    args = parser.parse_args(argv)

    version = args.version.removeprefix("v")

    try:
        changelog = args.changelog.read_text(encoding="utf-8")
    except OSError as err:
        print(f"Could not read {args.changelog}: {err}", file=sys.stderr)
        return 1

    strict = is_in_progress(changelog, version)

    try:
        if args.short:
            body = build_short_body(changelog, version, repo_root=args.repo_root, strict=strict)
            if body is not None and not strict and not marked_bullets(find_section(changelog, version) or ""):
                print(
                    f"The section for {version} has shipped and has no marked bullets. Printing the whole section.",
                    file=sys.stderr,
                )
        else:
            body = build_body(changelog, version, repo_root=args.repo_root)
    except UnmarkedError as err:
        print(
            f"The section '## [{err.version}]' in {args.changelog} has no bullet marked\n"
            f"with {MARKER_TEXT}, so the short release note would be empty.\n"
            "Put the marker at the end of the bullets a user will notice:\n"
            f"  - **Every slot can be named.** ... {MARKER_TEXT}\n"
            "The marker is an HTML comment and does not show when CHANGELOG.md is rendered.",
            file=sys.stderr,
        )
        return 1
    except DeadLinkError as err:
        print(
            f"A relative link points at something that is not in {args.repo_root}: {err}\n"
            "Fix the path in CHANGELOG.md or use an absolute URL. A dead link in a\n"
            "published release can only be fixed by editing the release by hand.",
            file=sys.stderr,
        )
        return 1
    except EmptyActionError as err:
        print(
            f"The section '## [{err.version}]' in {args.changelog} has\n"
            f"'{err.heading}' with no bullets under it.\n"
            "Write the bullets or delete the heading. The category is moved to the\n"
            "top of the release note, so empty it becomes a bare heading for every user.",
            file=sys.stderr,
        )
        return 1

    if body is None:
        print(
            f"No section '## [{version}]' with content in {args.changelog}.\n"
            f"Sections in the file: {', '.join(known_versions(changelog)) or '(none)'}\n"
            "The release note must be in CHANGELOG.md before the version ships.",
            file=sys.stderr,
        )
        return 1

    print(body)
    return 0


if __name__ == "__main__":
    sys.exit(main())
