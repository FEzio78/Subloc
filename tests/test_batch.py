import subloc.batch as batch
from subloc.pipeline import Options


def test_failure_does_not_stop_the_batch_and_phases_run_in_order(monkeypatch, tmp_path):
    videos = [tmp_path / f"Ep {n}.mkv" for n in (1, 2, 3)]
    for v in videos:
        v.write_bytes(b"")
    calls = []

    def fake_run(video, opt, rep, cancel):
        calls.append((video.name, "listen" if opt.transcribe_only else "translate"))
        if video.name == "Ep 2.mkv" and opt.transcribe_only:
            raise RuntimeError("damaged file")
        return None, []

    monkeypatch.setattr(batch, "run", fake_run)
    monkeypatch.setattr(batch, "unload_model", lambda: None)
    items = batch.run_batch(videos, Options(target="ar"))

    assert [it.status for it in items] == ["done", "failed", "done"]
    assert items[1].error == "damaged file"
    # all listening first (Whisper loaded once), then translation; the failed file is not translated
    assert calls == [
        ("Ep 1.mkv", "listen"),
        ("Ep 2.mkv", "listen"),
        ("Ep 3.mkv", "listen"),
        ("Ep 1.mkv", "translate"),
        ("Ep 3.mkv", "translate"),
    ]


def test_fingerprint_changes_when_a_file_is_replaced_with_same_size_and_date(tmp_path):
    import os

    from subloc.media import fingerprint

    f = tmp_path / "Ep 1.mkv"
    f.write_bytes(b"A" * 3_000_000)
    before = fingerprint(f)
    stat = f.stat()
    f.write_bytes(b"A" * 1_500_000 + b"B" + b"A" * 1_499_999)  # same size, one byte differs mid-file
    os.utime(f, ns=(stat.st_atime_ns, stat.st_mtime_ns))  # copies keep the old date
    assert fingerprint(f) != before


def test_find_videos_sorts_naturally_and_skips_non_video(tmp_path):
    for name in ("Ep 10.mkv", "Ep 2.mkv", "Ep 1.mp4", "Ep 1.ar.srt", "notes.txt"):
        (tmp_path / name).write_bytes(b"")
    assert [p.name for p in batch.find_videos([tmp_path])] == ["Ep 1.mp4", "Ep 2.mkv", "Ep 10.mkv"]


def test_queue_uses_each_files_own_subtitles_when_it_has_them(monkeypatch, tmp_path):
    from subloc.media import MediaInfo, Track

    videos = [tmp_path / f"Ep {n}.mkv" for n in (1, 2, 3)]
    for v in videos:
        v.write_bytes(b"")
    english = Track(0, "en", "English", "subrip")
    arabic = Track(0, "ar", "Arabic", "subrip")
    tracks = {"Ep 1.mkv": [english], "Ep 2.mkv": [], "Ep 3.mkv": [arabic]}
    monkeypatch.setattr(batch, "probe", lambda v: MediaInfo(60, 1280, 720, 24, [Track(0, "ja", "", "aac")],
                                                            tracks[v.name]))  # fmt: skip
    calls = []
    monkeypatch.setattr(batch, "run", lambda v, o, r, c: calls.append((v.name, o.transcribe_only, o.subs_track)))
    monkeypatch.setattr(batch, "unload_model", lambda: None)
    items = batch.run_batch(videos, Options(target="ar", prefer_builtin_subs=True))

    assert [it.status for it in items] == ["done", "done", "skipped"]  # Ep 3 already has Arabic subtitles
    assert calls == [("Ep 2.mkv", True, None),  # only the file without subtitles is listened to
                     ("Ep 1.mkv", False, 0), ("Ep 2.mkv", False, None)]  # fmt: skip
