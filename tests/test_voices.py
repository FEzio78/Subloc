import json
import threading
from pathlib import Path

import numpy as np
import pytest

from subloc import pipeline, voices
from subloc.models import Cue, Project
from subloc.voices import Turn, decide, join_windows, label, speaker_of

SR = 16000


def cue(i, start, end):
    return Cue(id=i, start=start, end=end, text=f"line {i}")


class FakeGender:
    """P(female) read from the audio itself: each test writes the probability it wants into the samples."""

    def p_female(self, x):
        return float(np.median(x))


def audio_with(spans, seconds=20.0):
    """Audio whose value in each (start, end, p) span is p: FakeGender then answers p for lines there."""
    a = np.full(int(seconds * SR), 0.5, np.float32)
    for start, end, p in spans:
        a[int(start * SR) : int(end * SR)] = p
    return a


def test_speaker_is_the_one_heard_longest_during_the_line():
    turns = [Turn(0.0, 1.2, 3), Turn(1.0, 4.0, 5)]
    assert speaker_of(cue(1, 0.0, 3.0), turns) == 5
    assert speaker_of(cue(2, 0.0, 1.0), turns) == 3
    assert speaker_of(cue(3, 10.0, 12.0), turns) is None  # nobody talks there
    assert speaker_of(cue(4, 3.9, 8.0), turns) is None  # 0.1 s of 4.1 s: too little to say


def test_a_sure_line_decides_else_the_speaker_else_unknown():
    assert decide(0.95, 0.1) == "female"  # sure line beats a male speaker (two people under one label)
    assert decide(0.03, 0.9) == "male"
    assert decide(0.6, 0.9) == "female"  # unsure line: the speaker's overall voice
    assert decide(0.6, 0.5) is None  # neither is clear
    assert decide(0.8, None) == "female"  # no speaker: a line that leans clearly is enough
    assert decide(None, 0.2) == "male"  # too short to classify: the speaker's voice
    assert decide(None, None) is None


def test_label_names_speakers_in_order_and_sets_each_lines_voice():
    cues = [cue(1, 0, 2), cue(2, 2.5, 4.5), cue(3, 5, 7), cue(4, 7.5, 9.5), cue(5, 10, 10.3), cue(6, 15, 17)]
    turns = [Turn(0, 2, 7), Turn(2.5, 4.5, 2), Turn(5, 7, 7), Turn(7.5, 9.5, 2), Turn(10, 10.3, 2)]
    # speaker 7 (first heard → S1) is a man; speaker 2 (S2) a woman, but line 4 is someone else's sure male voice.
    audio = audio_with([(0, 2, 0.1), (2.5, 4.5, 0.8), (5, 7, 0.2), (7.5, 9.5, 0.02), (15, 17, 0.5)])
    speakers = label(cues, audio, turns, FakeGender())
    assert [c.speaker for c in cues] == ["S1", "S2", "S1", "S2", "S2", None]
    assert [c.gender for c in cues] == ["male", "female", "male", "male", None, None]
    assert speakers["S1"]["gender"] == "male" and speakers["S1"]["lines"] == 2
    # S2's overall voice mixes 0.8 and 0.02 over equal time: not clear, so line 5 (too short) stays unknown.
    assert speakers["S2"]["gender"] is None


def test_label_stops_when_asked():
    with pytest.raises(voices.Cancelled):
        label([cue(1, 0, 2)], audio_with([]), [], FakeGender(), should_stop=lambda: True)


def test_voice_facts_are_saved_with_the_project(tmp_path):
    c = cue(1, 0, 2)
    c.speaker, c.gender = "S2", "female"
    path = tmp_path / "v.subloc.json"
    Project(video="v.mp4", cues=[c]).save(path)
    back = Project.load(path).cues[0]
    assert (back.speaker, back.gender) == ("S2", "female")
    old = json.loads(path.read_text(encoding="utf-8"))
    for key in ("speaker", "gender"):
        del old["cues"][0][key]
    path.write_text(json.dumps(old), encoding="utf-8")
    assert Project.load(path).cues[0].gender is None  # projects saved before this still load


class FakeProcess:
    """nemo-speech on a folder: writes OUT/<name>.json for every WAV in it (each window says speaker 1 talks)."""

    def __init__(self, cmd, returncode=0):
        self.returncode, self.cmd = returncode, cmd
        if returncode == 0:
            out = Path(cmd[cmd.index("--output-dir") + 1])
            out.mkdir(parents=True, exist_ok=True)
            for wav in sorted(Path(cmd[2]).glob("*.wav")):
                assert wav.read_bytes()[:4] == b"RIFF"
                segs = {"segments": [{"start": 1.5, "end": 2.5, "speaker": 1}]}
                (out / f"{wav.stem}.json").write_text(json.dumps(segs), encoding="utf-8")

    def poll(self):
        return self.returncode

    def kill(self):
        pass

    def wait(self):
        return self.returncode


def test_diarize_tries_the_graphics_card_then_the_processor(monkeypatch, tmp_path):
    monkeypatch.setattr(voices, "exe", lambda: tmp_path / "nemo-speech.exe")
    seen = []

    def popen(cmd, **kw):
        seen.append(cmd[cmd.index("--device") + 1])
        return FakeProcess(cmd, returncode=1 if seen[-1] == "vulkan" else 0)

    monkeypatch.setattr(voices.proc, "popen", popen)
    turns = voices.diarize(np.zeros(SR, np.float32))
    assert seen == ["vulkan", "cpu"]
    assert turns == [Turn(1.5, 2.5, 1)]


def test_long_audio_is_heard_in_overlapping_windows(monkeypatch, tmp_path):
    monkeypatch.setattr(voices, "exe", lambda: tmp_path / "nemo-speech.exe")
    monkeypatch.setattr(voices.proc, "popen", lambda cmd, **kw: FakeProcess(cmd))
    monkeypatch.setattr(voices, "WINDOW", 10.0)
    monkeypatch.setattr(voices, "OVERLAP", 2.0)
    assert voices.window_starts(25.0) == [0.0, 8.0, 16.0]
    turns = voices.diarize(np.zeros(25 * SR, np.float32))
    assert [(t.start, t.end) for t in turns] == [(1.5, 2.5), (9.5, 10.5), (17.5, 18.5)]  # on the film's clock


def test_speakers_are_linked_through_the_overlap(monkeypatch):
    monkeypatch.setattr(voices, "OVERLAP", 10.0)
    first = [Turn(0, 50, 1), Turn(52, 58, 2), Turn(60, 95, 1)]  # window 0-100 s
    # window 90-190 s: its "2" talks with the first window's "1" in the overlap (90-100), its "1" is someone new
    second = [Turn(91, 99, 2), Turn(120, 150, 1), Turn(160, 170, 2)]
    turns = join_windows([first, second], [0.0, 90.0])
    assert [(t.start, t.speaker) for t in turns] == [(0, 1), (52, 2), (60, 1), (120, 3), (160, 1)]


def test_voices_step_is_skipped_without_its_models(monkeypatch, tmp_path):
    monkeypatch.setattr(voices, "ready", lambda: False)
    proj = Project(video="v.mp4", cues=[cue(1, 0, 2)])
    pipeline._voices(tmp_path / "v.mp4", pipeline.Options(), proj, lambda: None, pipeline.Reporter(),
                     threading.Event(), audio=np.zeros(SR, np.float32))  # fmt: skip
    assert "voices" not in proj.meta and proj.cues[0].speaker is None


def test_voices_step_runs_once_per_set_of_lines_and_never_fails_the_job(monkeypatch, tmp_path):
    monkeypatch.setattr(voices, "ready", lambda: True)
    monkeypatch.setattr(voices, "GenderModel", FakeGender)
    calls = []

    def diarize(audio, should_stop, log):
        calls.append(1)
        return [Turn(0, 2, 4)]

    monkeypatch.setattr(voices, "diarize", diarize)
    proj = Project(video="v.mp4", cues=[cue(1, 0, 2)], meta={"source": {"model": "x"}, "segment_v": 2})
    warnings = []
    rep = pipeline.Reporter()
    rep.warn = warnings.append  # type: ignore[method-assign]
    run = lambda: pipeline._voices(tmp_path / "v.mp4", pipeline.Options(), proj, lambda: None, rep,  # noqa: E731
                                   threading.Event(), audio=audio_with([(0, 2, 0.05)]))  # fmt: skip
    run()
    run()
    assert len(calls) == 1 and proj.cues[0].speaker == "S1" and proj.cues[0].gender == "male"
    proj.meta["segment_v"] = 3  # lines re-split: label them again

    def broken(audio, should_stop, log):
        raise RuntimeError("no Vulkan")

    monkeypatch.setattr(voices, "diarize", broken)
    run()
    assert warnings and "not affected" in warnings[0]


def voiced(spec):
    """Cues from (start, speaker, gender, text)."""
    out = []
    for i, (start, spk, g, text) in enumerate(spec, 1):
        c = cue(i, start, start + 2)
        c.text, c.speaker, c.gender = text, spk, g
        out.append(c)
    return out


def test_scenes_split_at_long_pauses_and_list_their_speakers():
    cs = voiced([(0, "S1", "male", "a"), (3, "S2", "female", "b"), (20, "S3", "female", "c"), (23, "S1", "male", "d")])
    assert voices.scenes(cs) == [1, 1, 2, 2]
    assert voices.roster(cs, voices.scenes(cs)) == {1: ["S1", "S2"], 2: ["S3", "S1"]}


def test_a_speakers_voice_needs_most_of_its_lines_to_agree():
    cs = voiced([(0, "S1", "male", "a"), (3, "S1", "male", "b"), (6, "S1", "female", "c"), (9, "S2", "male", "d"),
                 (12, "S2", "female", "e"), (15, "S3", None, "f")])  # fmt: skip
    assert voices.speaker_genders(cs) == {"S1": "male", "S2": None, "S3": None}


def test_without_voices_the_request_and_answer_format_stay_as_before():
    from subloc.translate import Who, _user, schema_for

    cs = [cue(1, 0, 2), cue(2, 3, 5)]
    assert Who.of(cs) is None
    text = _user(cs, [], [], {}, "English", "Arabic", "ar")
    assert '"speaker"' not in text and "People speaking" not in text and '"to"' not in text
    lines = schema_for(cs)["properties"]["lines"]
    assert "prefixItems" not in lines and list(lines["items"]["properties"]) == ["id", "src", "text"]


def test_with_voices_each_line_says_who_speaks_and_the_cast_is_listed():
    from subloc.translate import Who, _user

    cs = voiced([(0, "S1", "male", "Are you hungry?"), (3, "S2", "female", "No."), (20, "S3", None, "Hi.")])
    who = Who.of(cs)
    text = _user(cs[1:], cs[:1], [], {}, "English", "Arabic", "ar", who)
    first = json.loads(next(line for line in text.splitlines() if line.startswith('{"id": 2')))
    assert first["speaker"] == "S2" and first["voice"] == "woman" and first["scene"] == 1
    assert "[S1] English: Are you hungry?" in text  # context lines say who said them
    assert "scene 1: S1 (man), S2 (woman)" in text and "scene 2: S3" in text
    assert 'who the line is spoken to in "to"' in text


def test_the_listener_can_never_be_the_lines_own_speaker():
    from subloc.translate import TO_OTHER, Who, schema_for

    cs = voiced([(0, "S1", "male", "a"), (3, "S2", "female", "b")])
    who = Who.of(cs)
    lines = schema_for(cs, {c.id: who.choices(c) + TO_OTHER for c in cs})["properties"]["lines"]
    assert "items" not in lines  # beside prefixItems, llama.cpp would ignore the per-line rules
    first, second = lines["prefixItems"]
    assert first["properties"]["id"]["enum"] == [1] and second["properties"]["id"]["enum"] == [2]
    assert first["properties"]["to"]["enum"] == ["S2", "several", "unknown"]
    assert second["properties"]["to"]["enum"] == ["S1", "several", "unknown"]
    assert list(first["properties"]) == ["id", "src", "to", "text"]  # the listener is decided before writing


def test_the_translators_listener_is_kept_on_each_line():
    from subloc.translate import translate

    class LLM:
        def chat(self, model, messages, json_schema=None, temperature=0.2, reasoning="none"):
            assert "prefixItems" in json_schema["properties"]["lines"]
            assert "first decide who it is spoken to" in messages[0]["content"]
            return json.dumps({"lines": [{"id": 1, "src": "Are", "to": "S2", "text": "هل أنتِ جائعة؟"},
                                         {"id": 2, "src": "No", "to": "unknown", "text": "لا."}]})  # fmt: skip

    cs = voiced([(0, "S1", "male", "Are you hungry?"), (3, "S2", "female", "No.")])
    translate(cs, LLM(), "m", "en", "ar", log=lambda m: None, workers=1)
    assert [(c.to, c.translation) for c in cs] == [("S2", "هل أنتي جائعة؟"), (None, "لا.")]  # feminine you: visible ي


def test_fbank_has_80_bins_every_10_ms_and_no_level_offset():
    x = (np.random.default_rng(0).standard_normal(SR) * 0.1).astype(np.float32)
    f = voices.fbank(x)
    assert f.shape == (98, 80)
    assert np.allclose(voices.fbank(x * 4.0), f, atol=1e-3)  # louder audio, same features (means removed)
    assert voices.fbank(np.zeros(100, np.float32)).shape == (0, 80)


def unit(*v):
    a = np.array(v, np.float32)
    return a / np.linalg.norm(a)


def test_one_person_split_across_windows_gets_one_id(monkeypatch):
    monkeypatch.setattr(voices, "WINDOW", 100.0)
    monkeypatch.setattr(voices, "OVERLAP", 10.0)
    # windows own 0-95 s and 95-185 s. Ids 1 (window 0) and 3 (window 1) sound alike; 2 and 4 too, but 4 is a man
    # and 2 a woman; 5 sounds like 1 but speaks in window 0 as well, where the diarizer told them apart.
    turns = [Turn(10, 12, 1), Turn(20, 22, 2), Turn(120, 122, 3), Turn(130, 132, 4), Turn(40, 42, 5), Turn(140, 142, 5)]
    cs = [cue(i, t.start, t.end) for i, t in enumerate(turns, 1)]
    raw = [t.speaker for t in turns]
    prints = [unit(1, 0, 0), unit(0, 1, 0), unit(0.98, 0.1, 0), unit(0.1, 0.99, 0), unit(0.97, 0.05, 0.1),
              unit(0.97, 0.05, 0.1)]  # fmt: skip
    p = [0.1, 0.95, 0.1, 0.05, 0.1, 0.1]
    for c in cs:
        c.end = c.start + 5  # long enough to count as a voice (MIN_SPEAKER)
    assert voices.merge_by_voice(raw, prints, p, cs, turns) == [1, 2, 1, 4, 5, 5]


def test_lines_listened_to_again_get_their_speakers_again(monkeypatch, tmp_path):
    """Listening again with the same settings kept the old 'done' mark while the new lines had no labels."""
    monkeypatch.setattr(voices, "ready", lambda: True)
    monkeypatch.setattr(voices, "GenderModel", FakeGender)
    monkeypatch.setattr(voices, "Fingerprints", lambda: None)
    monkeypatch.setattr(voices, "diarize", lambda audio, should_stop, log: [Turn(0, 2, 4)])
    meta = {"source": {"model": "x"}, "segment_v": 2}
    proj = Project(video="v.mp4", cues=[cue(1, 0, 2)], meta=dict(meta))
    key = {"v": voices.VERSION, "source": meta["source"], "segment_v": 2}
    proj.meta["voices"] = {"key": key, "speakers": {"S1": {"gender": "male"}}}  # 'done', but the line is bare
    pipeline._voices(tmp_path / "v.mp4", pipeline.Options(), proj, lambda: None, pipeline.Reporter(),
                     threading.Event(), audio=audio_with([(0, 2, 0.05)]))  # fmt: skip
    assert proj.cues[0].speaker == "S1" and proj.cues[0].gender == "male"
