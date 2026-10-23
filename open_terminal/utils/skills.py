"""Small filesystem helpers for terminal-owned Agent Skills."""

from __future__ import annotations

import os

from open_terminal.utils.fs import UserFS

MAX_SKILL_RESOURCE_DEPTH = 4
MAX_SKILL_RESOURCE_FILES = 50


def join_skill_path(base: str, child: str) -> str:
    if os.path.isabs(child):
        return os.path.normpath(child)
    return os.path.normpath(os.path.join(base, child))


def parse_skill_frontmatter(text: str) -> tuple[dict[str, str], str]:
    if not text.startswith("---\n"):
        return {}, text.strip()
    end = text.find("\n---", 4)
    if end < 0:
        return {}, text.strip()

    frontmatter: dict[str, str] = {}
    lines = text[4:end].splitlines()
    idx = 0
    while idx < len(lines):
        line = lines[idx]
        if not line.strip() or line.lstrip().startswith("#") or ":" not in line:
            idx += 1
            continue
        key, value = line.split(":", 1)
        key = key.strip()
        value = value.strip()
        if value in {">", "|"}:
            block = []
            idx += 1
            while idx < len(lines) and (lines[idx].startswith(" ") or lines[idx].startswith("\t")):
                block.append(lines[idx].strip())
                idx += 1
            frontmatter[key] = "\n".join(block) if value == "|" else " ".join(block)
            continue
        frontmatter[key] = value.strip("\"'")
        idx += 1

    body_start = text.find("\n", end + 1)
    body = text[body_start + 1 :].strip() if body_start >= 0 else ""
    return frontmatter, body


async def list_skill_resources(fs: UserFS, skill_dir: str) -> list[str]:
    resources: list[str] = []

    async def walk(directory: str, prefix: str = "", depth: int = 0):
        if depth >= MAX_SKILL_RESOURCE_DEPTH or len(resources) >= MAX_SKILL_RESOURCE_FILES:
            return
        for entry in await fs.listdir(directory):
            if len(resources) >= MAX_SKILL_RESOURCE_FILES:
                break
            name = str(entry.get("name") or "")
            if not name or name.startswith(".") or name == "SKILL.md":
                continue
            rel = f"{prefix}/{name}" if prefix else name
            path = join_skill_path(directory, name)
            if entry.get("type") == "file":
                resources.append(rel)
            elif entry.get("type") == "directory":
                await walk(path, rel, depth + 1)

    await walk(skill_dir)
    return resources[:MAX_SKILL_RESOURCE_FILES]
