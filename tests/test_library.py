"""The Library index (subloc/library.py) and recursive folder search. Placeholder files only, no real media;
reading tracks inside files (ffprobe) is replaced by a stub."""

import pytest

from subloc import batch, library
from subloc.library import Library, Video, add_root, apply, lang_code, remove_root, scan_folder
from subloc.models import Cue, Project
from subloc.pipeline import project_path


@pytest.fixture(autouse=True)
def no_ffprobe(tmp_path, monkeypatch):
    monkeypatch.setattr(library, "data_dir", lambda: tmp_path / "data")
    probed: list[str] = []

    def fake(v: Video) -> None:
        probed.append(v.name)
        v.inner, v.inner_text, v.probed = (["en"], True, f"{v.size}:{v.mtime}") if "Inner" in v.name else (
            [], False, f"{v.size}:{v.mtime}")  # fmt: skip

    monkeypatch.setattr(library, "read_tracks", fake)
    return probed


def touch(path, data=b"x"):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


@pytest.fixture
def shows(tmp_path):
    root = tmp_path / "Anime"
    s1 = root / "Show" / "Season 1"
    touch(s1 / "Ep 1.mkv")
    touch(s1 / "Ep 1.ar.srt")
    touch(s1 / "Ep 2.mkv")
    touch(s1 / "Ep 2.eng.forced.srt")
    touch(s1 / "Ep 10.mkv")
    touch(s1 / "Sample" / "sample.mkv")  # release sample: skipped
    touch(root / ".hidden" / "x.mkv")
    touch(root / "Show" / "Inner Subs.mkv")
    touch(root / "Theme.mp3")  # music: not a library video
    movie = touch(root / "Movie.mp4")
    cues = [Cue(id=i, start=i, end=i + 1, text="x", translation="ص" if i == 1 else None) for i in (1, 2)]
    Project(video=str(movie), cues=cues, target_language="ar").save(project_path(movie))
    return root


def statuses(lib: Library, target="ar") -> dict[str, str]:
    return {v.name: v.status(target) for v in lib.videos}


def test_language_from_subtitle_names():
    assert [lang_code(t) for t in ("ar", "ARA", "Arabic", "ar-SA", "en_US", "eng", "forced", "mixed")] == [
        "ar", "ar", "ar", "ar", "en", "en", None, None]  # fmt: skip


def test_scan_finds_every_video_with_its_status(shows, no_ffprobe):
    lib = Library()
    assert add_root(lib, shows)
    apply(lib, scan_folder(str(shows), lib))
    assert statuses(lib) == {
        "Ep 1.mkv": "done",  # Arabic file next to it
        "Ep 2.mkv": "other",  # English subtitles: quick to translate
        "Ep 10.mkv": "none",
        "Inner Subs.mkv": "other",  # English track inside
        "Movie.mp4": "partial",  # Subloc translated 1 of 2 lines
    }
    v = {v.name: v for v in lib.videos}
    assert v["Ep 2.mkv"].other_language("ar") == "en" and v["Movie.mp4"].progress == 0.5
    assert statuses(lib, "en")["Ep 2.mkv"] == "done"
    assert sorted(no_ffprobe) == sorted(statuses(lib))
    # A second scan of unchanged files doesn't read their tracks again.
    no_ffprobe.clear()
    apply(lib, scan_folder(str(shows), lib))
    assert no_ffprobe == [] and len(lib.videos) == 5


def test_change_in_one_folder(shows, no_ffprobe):
    lib = Library()
    add_root(lib, shows)
    apply(lib, scan_folder(str(shows), lib))
    show = shows / "Show"
    touch(show / "Season 2" / "Ep 1.mkv")  # new subfolder: read in full
    (show / "Inner Subs.mkv").unlink()
    touch(show / "Season 1" / "Ep 10.ara.srt")  # in a folder that didn't change: not seen yet
    no_ffprobe.clear()
    apply(lib, scan_folder(str(show), lib, deep=False))
    names = statuses(lib)
    assert "Inner Subs.mkv" not in names and names["Ep 10.mkv"] == "none"
    assert any(v.path.endswith(r"Season 2\Ep 1.mkv") or v.path.endswith("Season 2/Ep 1.mkv") for v in lib.videos)
    assert no_ffprobe == ["Ep 1.mkv"]  # only the new video
    # Removing a subfolder drops its videos when its parent is read again.
    for f in (shows / "Show" / "Season 2").iterdir():
        f.unlink()
    (shows / "Show" / "Season 2").rmdir()
    apply(lib, scan_folder(str(show), lib, deep=False))
    assert sum(v.name == "Ep 1.mkv" for v in lib.videos) == 1
    assert not any("Season 2" in d for d in lib.folders)


def test_refresh_after_subloc_wrote_subtitles(shows):
    lib = Library()
    add_root(lib, shows)
    apply(lib, scan_folder(str(shows), lib))
    ep10 = shows / "Show" / "Season 1" / "Ep 10.mkv"
    touch(ep10.with_name("Ep 10.ar.srt"))
    assert library.refresh_video(lib, ep10)
    assert statuses(lib)["Ep 10.mkv"] == "done" and len(lib.videos) == 5
    assert not library.refresh_video(lib, shows.parent / "elsewhere.mkv")


def test_roots_inside_each_other(tmp_path):
    lib = Library()
    assert add_root(lib, tmp_path / "Anime" / "Show")
    assert not add_root(lib, tmp_path / "Anime" / "Show" / "Season 1")  # already in the library
    assert add_root(lib, tmp_path / "Anime")  # takes in the folder inside it
    assert lib.roots == [str(tmp_path / "Anime")]


def test_remove_and_reload(shows):
    lib = Library(watch=True)
    add_root(lib, shows)
    apply(lib, scan_folder(str(shows), lib))
    library.save(lib)
    assert library.load() == lib
    remove_root(lib, str(shows))
    assert lib.videos == [] and lib.folders == [] and lib.roots == []
    assert (shows / "Movie.mp4").exists()  # nothing on disk is touched


def test_damaged_index_starts_empty(tmp_path):
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "library.json").write_text("[1, 2", encoding="utf-8")
    assert library.load() == Library()


def test_dropped_folder_includes_subfolders_in_order(shows):
    names = [p.relative_to(shows).as_posix() for p in batch.find_videos([shows])]
    assert names == ["Movie.mp4", "Show/Inner Subs.mkv", "Show/Season 1/Ep 1.mkv", "Show/Season 1/Ep 2.mkv",
                     "Show/Season 1/Ep 10.mkv", "Theme.mp3"]  # fmt: skip
