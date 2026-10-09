"""Skill registry. Each skill is a folder with a SKILL.md (YAML frontmatter + instructions),
the same format the Claude Agent SDK uses. Skills are versioned files, not ad-hoc prompts,
so product/content owners can edit them without touching Python."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

BUNDLED_DIR = Path(__file__).resolve().parent.parent / "skills"


@dataclass(frozen=True)
class Skill:
    name: str
    route: str
    description: str
    instructions: str
    max_tokens: int
    artifact_kind: str | None = None


def parse_skill(path: Path) -> Skill:
    raw = path.read_text(encoding="utf-8")
    if not raw.startswith("---"):
        raise ValueError(f"{path} has no frontmatter")
    end = raw.find("\n---", 3)
    meta = yaml.safe_load(raw[3:end]) or {}
    for key in ("name", "route", "description"):
        if key not in meta:
            raise ValueError(f"{path}: frontmatter missing '{key}'")
    return Skill(
        name=meta["name"], route=meta["route"], description=meta["description"],
        instructions=raw[end + 4 :].strip(), max_tokens=int(meta.get("max_tokens", 1500)),
        artifact_kind=meta.get("artifact_kind"),
    )


class SkillRegistry:
    def __init__(self, directory: str | Path | None = None):
        self.directory = Path(directory) if directory else BUNDLED_DIR
        self._by_route: dict[str, Skill] = {}
        self.reload()

    def reload(self) -> None:
        skills = [parse_skill(p) for p in sorted(self.directory.glob("*/SKILL.md"))]
        self._by_route = {s.route: s for s in skills}

    def for_route(self, route: str) -> Skill:
        return self._by_route[route]

    def all(self) -> list[Skill]:
        return list(self._by_route.values())
