"""Team learnings, captured next to the handoff and reused by the next session.

The idea (not the code) comes from trailhq/Trail-Code's ``.trail/`` learnings layer,
which is MIT licensed. This implementation is original and standard-library only:
an append-only JSONL file plus a regenerated Markdown view inside
``VIBE_RESCUE/learnings/``.

Vietnamese: ghi lại điều team đã học được (quyết định, cạm bẫy) để phiên sau đọc
trước khi sửa. Không AI, không mạng; mỗi entry có timestamp, git HEAD và files.
"""
from __future__ import annotations

import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path

JSONL = "learnings.jsonl"
MARKDOWN = "LEARNINGS.md"


def _dir(out: Path) -> Path:
    path = out / "learnings"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _git(project: Path | None, *args: str) -> str:
    if project is None:
        return ""
    try:
        done = subprocess.run(["git", "-C", str(project), *args],
                              capture_output=True, text=True, check=False)
    except OSError:
        return ""
    return done.stdout.strip() if done.returncode == 0 else ""


def add(out: Path, text: str, *, files: list[str] | None = None,
        project: Path | None = None, author: str | None = None) -> dict:
    """Append one learning; returns the stored entry."""
    entry = {
        "at": datetime.now(UTC).isoformat(timespec="seconds"),
        "text": " ".join(text.split()),
        "files": sorted({name for name in (files or []) if name}),
        "head": _git(project, "rev-parse", "--short", "HEAD"),
        "author": author or _git(project, "config", "user.name") or "",
    }
    with (_dir(out) / JSONL).open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
    render(out)
    return entry


def load(out: Path) -> list[dict]:
    path = out / "learnings" / JSONL
    if not path.exists():
        return []
    entries = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            entries.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return entries


def recent(out: Path, limit: int = 10) -> list[dict]:
    """Newest first."""
    return load(out)[-limit:][::-1]


def check(out: Path, files: list[str]) -> list[dict]:
    """Learnings that mention any of these files — read them before changing one."""
    wanted = set(files)
    return [entry for entry in load(out) if wanted & set(entry.get("files") or [])]


def render(out: Path) -> Path:
    entries = load(out)
    lines = ["# Learnings — what the team worked out", "",
             "Append with `./vr note \"...\"`; this file is regenerated from `learnings.jsonl`.",
             "Newest last, same as the file.", ""]
    for entry in entries:
        where = f" — {', '.join(entry['files'])}" if entry.get("files") else ""
        lines.append(f"- {entry['at']} · {entry.get('author') or '?'}{where}: {entry['text']}")
    path = _dir(out) / MARKDOWN
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path
