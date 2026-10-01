from __future__ import annotations

from pathlib import Path


def load_skills(skills_dir: Path) -> str:
    """Concatenate all Markdown skill files from the given directory."""
    if not skills_dir.is_dir():
        return ""
    parts: list[str] = []
    for path in sorted(skills_dir.glob("*.md")):
        parts.append(path.read_text(encoding="utf-8").strip())
    return "\n\n".join(parts)
