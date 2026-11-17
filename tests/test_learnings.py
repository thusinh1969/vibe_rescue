"""Tests for the team-learnings store written next to the handoff."""
from scripts import learnings


def test_add_normalises_and_renders(tmp_path):
    out = tmp_path / "VIBE_RESCUE"
    entry = learnings.add(out, "  retry   stays   at   4 ", files=["src/a.py"], author="tester")
    assert entry["text"] == "retry stays at 4"
    assert entry["files"] == ["src/a.py"]
    assert entry["author"] == "tester"
    assert (out / "learnings" / "learnings.jsonl").exists()
    assert "retry stays at 4" in (out / "learnings" / "LEARNINGS.md").read_text(encoding="utf-8")


def test_recent_is_newest_first(tmp_path):
    out = tmp_path / "VIBE_RESCUE"
    for text in ("one", "two", "three"):
        learnings.add(out, text, author="t")
    assert [entry["text"] for entry in learnings.recent(out, 2)] == ["three", "two"]


def test_check_matches_changed_files(tmp_path):
    out = tmp_path / "VIBE_RESCUE"
    learnings.add(out, "touching auth", files=["auth.py"], author="t")
    learnings.add(out, "touching ui", files=["ui.py"], author="t")
    hits = learnings.check(out, ["auth.py", "README.md"])
    assert [entry["text"] for entry in hits] == ["touching auth"]


def test_broken_line_is_skipped(tmp_path):
    out = tmp_path / "VIBE_RESCUE"
    learnings.add(out, "valid", author="t")
    path = out / "learnings" / "learnings.jsonl"
    path.write_text(path.read_text(encoding="utf-8") + "{not json}\n", encoding="utf-8")
    assert [entry["text"] for entry in learnings.load(out)] == ["valid"]
