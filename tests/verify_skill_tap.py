#!/usr/bin/env python3
"""Verify the repository is a complete Hermes multi-skill GitHub tap."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SKILLS = ("clawchat-officecli", "create-hermes-boot-hook", "tarot-arcana")
ALLOWED_DIRS = ("references", "templates", "scripts", "assets", "examples")
REFERENCE_RE = re.compile(
    r"(?:\]\(|`|(?:^|[\s\"']))"
    r"((?:references|templates|scripts|assets|examples)/[^\s)`\"'<>]+)",
    re.MULTILINE,
)


def referenced_paths(skill_md: str) -> set[str]:
    return {
        match.group(1).rstrip(".,;:")
        for match in REFERENCE_RE.finditer(skill_md.replace("\\", "/"))
    }


def support_files(skill_dir: Path) -> set[str]:
    files: set[str] = set()
    for dirname in ALLOWED_DIRS:
        root = skill_dir / dirname
        if not root.exists():
            continue
        for path in root.rglob("*"):
            if path.is_file() and "__pycache__" not in path.parts:
                files.add(path.relative_to(skill_dir).as_posix())
    return files


def main() -> int:
    errors: list[str] = []

    for skill in SKILLS:
        skill_dir = ROOT / "skills" / skill
        skill_md_path = skill_dir / "SKILL.md"
        if not skill_md_path.is_file():
            errors.append(f"missing skills/{skill}/SKILL.md")
            continue

        text = skill_md_path.read_text(encoding="utf-8")
        referenced = referenced_paths(text)
        existing = support_files(skill_dir)

        for rel_path in sorted(referenced):
            if not (skill_dir / rel_path).is_file():
                errors.append(f"{skill}: referenced file is missing: {rel_path}")

        for rel_path in sorted(existing - referenced):
            errors.append(f"{skill}: support file is not directly referenced: {rel_path}")

    for legacy in (
        ROOT / "creative" / "tarot-arcana",
        ROOT / "productivity" / "clawchat-officecli",
        ROOT / "create-hermes-boot-hook",
    ):
        if legacy.exists():
            errors.append(f"legacy skill directory still exists: {legacy.relative_to(ROOT)}")

    metadata_path = ROOT / "skills.sh.json"
    if not metadata_path.is_file():
        errors.append("missing skills.sh.json")
    else:
        try:
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            errors.append(f"invalid skills.sh.json: {exc}")
        else:
            expected = [
                {"title": "Productivity", "skills": ["clawchat-officecli"]},
                {"title": "Automation", "skills": ["create-hermes-boot-hook"]},
                {"title": "Creative", "skills": ["tarot-arcana"]},
            ]
            if metadata.get("$schema") != "https://skills.sh/schemas/skills.sh.schema.json":
                errors.append("skills.sh.json has an incorrect $schema")
            if metadata.get("groupings") != expected:
                errors.append("skills.sh.json has incorrect category groupings")

    readme_requirements = (
        "hermes skills tap add clawling/clawchat-skills",
        "hermes skills install clawling/clawchat-skills/clawchat-officecli",
        "hermes skills install clawling/clawchat-skills/create-hermes-boot-hook",
        "hermes skills install clawling/clawchat-skills/tarot-arcana",
        "skills/clawchat-officecli/",
        "skills/create-hermes-boot-hook/",
        "skills/tarot-arcana/",
    )
    for filename in ("README.md", "README_zh.md"):
        path = ROOT / filename
        text = path.read_text(encoding="utf-8") if path.is_file() else ""
        for requirement in readme_requirements:
            if requirement not in text:
                errors.append(f"{filename}: missing {requirement}")

    runtime_requirements = {
        "skills/clawchat-officecli/scripts/office-live-directory.py": (
            'parent.parent / "assets" / "web"',
        ),
        "skills/tarot-arcana/scripts/draw-tarot.mjs": (
            'join(SKILL_ROOT, "assets", "deck.json")',
        ),
        "skills/tarot-arcana/scripts/liveware/server.py": (
            'skill_root / "assets" / "liveware"',
            'parents[2] / "assets" / "deck.json"',
        ),
        "skills/tarot-arcana/scripts/liveware/setup.py": (
            '_HERMES_HOME / "plugins" / "clawchat"',
        ),
    }
    for relative_path, required_fragments in runtime_requirements.items():
        text = (ROOT / relative_path).read_text(encoding="utf-8")
        for fragment in required_fragments:
            if fragment not in text:
                errors.append(f"{relative_path}: missing runtime path {fragment}")

    if errors:
        for error in errors:
            print(f"FAIL: {error}", file=sys.stderr)
        return 1

    print("PASS: Hermes skill tap structure is complete")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
