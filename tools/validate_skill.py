#!/usr/bin/env python3
"""Repository-owned Skill package checks; no installed Codex runtime required.

Keep validation available in clean CI checkouts as well as developer machines.
This checks package structure, not the quality of a role's judgment or behavior.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import yaml


def validate_skill(directory: Path) -> None:
    """Raise ValueError for invalid metadata or unfinished instruction stubs."""
    skill = directory / "SKILL.md"
    if not skill.is_file():
        raise ValueError("SKILL.md not found")
    content = skill.read_text(encoding="utf-8")
    header = re.match(r"\A---\n(.*?)\n---(?:\n|$)", content, re.DOTALL)
    if header is None:
        raise ValueError("Missing or invalid YAML frontmatter")
    try:
        metadata = yaml.safe_load(header.group(1))
    except yaml.YAMLError as error:
        raise ValueError(f"Invalid YAML frontmatter: {error}") from error
    if not isinstance(metadata, dict):
        raise ValueError("Frontmatter must be a mapping")
    allowed = {"name", "description", "license", "allowed-tools", "metadata"}
    if set(metadata) - allowed:
        raise ValueError("Unexpected frontmatter properties")

    name = metadata.get("name")
    if not isinstance(name, str) or not 1 <= len(name) <= 64:
        raise ValueError("name must be a nonempty string of at most 64 characters")
    if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", name):
        raise ValueError("name must use lowercase hyphen-case")
    description = metadata.get("description")
    if not isinstance(description, str) or not 1 <= len(description.strip()) <= 1024:
        raise ValueError("description must be a nonempty string of at most 1024 characters")
    if any(character in description for character in "<>"):
        raise ValueError("description must not contain angle brackets")
    if description.lstrip().startswith("[TODO:"):
        raise ValueError("description contains an unfinished TODO placeholder")

    # Examples may legitimately demonstrate TODO syntax inside fenced code.
    active_fence = ""
    for line in content[header.end():].splitlines():
        fence = re.match(r"^\s*(?:(?:[-+*]|\d+[.)])\s+)?(`{3,}|~{3,})(.*)$", line)
        if fence:
            marker, suffix = fence.groups()
            if not active_fence:
                active_fence = marker
            elif marker[0] == active_fence[0] and len(marker) >= len(active_fence) and not suffix.strip():
                active_fence = ""
        elif not active_fence and re.fullmatch(r" {0,3}\[TODO:.*\]\s*", line):
            raise ValueError("Skill instructions contain an unfinished TODO placeholder")


def main() -> int:
    if len(sys.argv) != 2:
        print("Usage: python tools/validate_skill.py <skill_directory>", file=sys.stderr)
        return 2
    try:
        validate_skill(Path(sys.argv[1]))
    except (OSError, ValueError) as error:
        print(str(error), file=sys.stderr)
        return 1
    print("Skill is valid!")
    return 0


if __name__ == "__main__":
    sys.exit(main())
