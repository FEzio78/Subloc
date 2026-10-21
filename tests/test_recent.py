"""The Home screen's recent-projects list (subloc/recent.py). No real media: placeholder files only."""

import os

import pytest

from subloc import recent
from subloc.models import Cue, Project
from subloc.pipeline import project_path


@pytest.fixture
def data(tmp_path, monkeypatch):
    folder = tmp_path / "data"
    monkeypatch.setattr(recent, "data_dir", lambda: folder)
    return folder


def video(folder, name="Episode 1.mkv"):
    folder.mkdir(parents=True, exist_ok=True)
    v = folder / name
    v.write_bytes(b"not really a video")
    return v


def write_project(v, translated: int, total: int = 4, target: str = "ar", mtime: float | None = None) -> None:
    cues = [Cue(id=i, start=i, end=i + 1, text=f"line {i}", translation=f"سطر {i}" if i <= translated else None)
            for i in range(1, total + 1)]  # fmt: skip
    path = project_path(v)
    Project(video=str(v), cues=cues, target_language=target).save(path)
    if mtime is not None:
        os.utime(path, (mtime, mtime))


def test_newest_first_without_duplicates(data, tmp_path):
    a, b = video(tmp_path / "show", "a.mkv"), video(tmp_path / "show", "b.mkv")
    items = recent.touch([], a, duration=1500)
    items = recent.touch(items, b)
    again = tmp_path / "SHOW" / "A.mkv" if os.name == "nt" else a  # Windows paths ignore case
    items = recent.touch(items, again)
    assert [r.path for r in items] == [again, b]
    assert items[0].duration == 1500  # kept from the first time


def test_list_is_capped(data, tmp_path):
    items: list = []
    for i in range(recent.LIMIT + 5):
        items = recent.touch(items, tmp_path / f"{i}.mkv")
    assert len(items) == recent.LIMIT
    assert items[0].path.name == f"{recent.LIMIT + 4}.mkv"


def test_status_follows_the_project_file(data, tmp_path):
    v = video(tmp_path)
    (item,) = recent.touch([], v)
    assert item.status() == "new"
    for translated, status in ((0, "heard"), (2, "partial"), (4, "done")):
        write_project(v, translated, mtime=1000.0 + translated)
        assert recent.summarize(item)
        assert item.status() == status
    assert (item.lines, item.translated, item.target, item.progress) == (4, 4, "ar", 1.0)
    v.unlink()
    assert item.status() == "missing"


def test_summary_is_read_again_only_after_a_change(data, tmp_path):
    v = video(tmp_path)
    write_project(v, 1, mtime=1000.0)
    (item,) = recent.touch([], v)
    assert item.translated == 1
    assert not recent.summarize(item)  # same file: not read again
    write_project(v, 3, mtime=2000.0)
    assert recent.summarize(item) and item.translated == 3


def test_saved_and_loaded(data, tmp_path):
    v = video(tmp_path, "حلقة ١.mkv")
    write_project(v, 2)
    items = recent.touch([], v, duration=42.0)
    recent.save(items)
    assert recent.load() == items
    assert recent.remove(recent.load(), v) == []


def test_damaged_list_starts_empty(data):
    data.mkdir()
    (data / "recent.json").write_text("{not json", encoding="utf-8")
    assert recent.load() == []
    (data / "recent.json").write_text('[{"video": "x.mkv", "unknown": 1}]', encoding="utf-8")
    assert [r.video for r in recent.load()] == ["x.mkv"]  # fields from newer/older versions are ignored


def test_thumbnail_names_are_per_video(data, tmp_path):
    a, b = recent.thumb_path(tmp_path / "a.mkv"), recent.thumb_path(tmp_path / "b.mkv")
    assert a != b and a.parent == data / "thumbs"
    if os.name == "nt":
        assert recent.thumb_path(tmp_path / "A.MKV") == a
