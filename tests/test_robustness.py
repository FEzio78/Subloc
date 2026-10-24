import json
import time

import httpx
import pytest

from subloc.errors import ContextTooLong, ModelNotAvailable, TranslatorUnavailable
from subloc.llm import LMStudio
from subloc.models import Cue
from subloc.translate import translate


def cues(n):
    return [Cue(id=i, start=i, end=i + 0.9, text=f"Line {i}.") for i in range(1, n + 1)]


def answer(messages):
    """Translate every id found in the request as 'T<id>'."""
    ids = [json.loads(line)["id"] for line in messages[-1]["content"].splitlines() if line.startswith('{"id"')]
    return json.dumps({"lines": [{"id": i, "text": f"T{i}"} for i in ids]})


class FakeLLM:
    def __init__(self, max_lines=None, die_after=None):
        self.max_lines, self.die_after, self.calls = max_lines, die_after, 0

    def chat(self, model, messages, json_schema=None, temperature=0.2, reasoning="none"):
        self.calls += 1
        if self.die_after is not None and self.calls > self.die_after:
            raise TranslatorUnavailable("gone")
        n = sum(1 for line in messages[-1]["content"].splitlines() if line.startswith('{"id"'))
        if self.max_lines and n > self.max_lines:
            raise ContextTooLong("too long")
        return answer(messages)


def test_unreachable_server_fails_fast_with_a_clear_message():
    t0 = time.time()
    with pytest.raises(TranslatorUnavailable, match="Can't reach LM Studio"):
        LMStudio("http://127.0.0.1:9").list_models()
    assert time.time() - t0 < 10


def test_batches_that_do_not_fit_are_split():
    cs = cues(60)
    translate(cs, FakeLLM(max_lines=7), "m", "en", "ar", log=lambda m: None, workers=2)
    assert all(c.translation == f"T{c.id}" for c in cs)


def test_translator_dying_stops_the_job_and_keeps_progress():
    cs = cues(100)
    with pytest.raises(TranslatorUnavailable):
        translate(cs, FakeLLM(die_after=2), "m", "en", "ar", log=lambda m: None, workers=1)
    done = [c for c in cs if c.translation]
    assert 0 < len(done) < 100  # first batches kept, rest left for resume
    translate(cs, FakeLLM(), "m", "en", "ar", log=lambda m: None)  # resume
    assert all(c.translation for c in cs)


def fake_server(status, body):
    client = LMStudio("http://fake")
    client.http = httpx.Client(
        transport=httpx.MockTransport(lambda req: httpx.Response(status, text=body)), base_url="http://fake"
    )
    return client


def test_server_errors_become_readable():
    with pytest.raises(ContextTooLong):
        fake_server(
            400, '{"error":"The number of tokens to keep from the initial prompt is greater than the context length"}'
        ).chat("m", [])
    with pytest.raises(ModelNotAvailable, match="isn't available"):
        fake_server(404, '{"error":"model not found"}').chat("gemma", [])


def test_a_server_that_refuses_the_speaker_format_still_translates():
    from subloc.errors import SublocError

    class Picky:
        def __init__(self):
            self.refused = 0

        def chat(self, model, messages, json_schema=None, temperature=0.2, reasoning="none"):
            if "prefixItems" in json_schema["properties"]["lines"]:
                self.refused += 1
                raise SublocError("LM Studio returned an error (400).", "unsupported schema")
            return answer(messages)

    cs = cues(30)
    for c in cs:
        c.speaker, c.gender = ("S1", "male") if c.id % 2 else ("S2", "female")
    llm = Picky()
    translate(cs, llm, "m", "en", "ar", log=lambda m: None, workers=1)
    assert all(c.translation == f"T{c.id}" for c in cs)
    assert llm.refused == 1  # asked once in that format, then plainly


def test_projects_with_fields_this_version_does_not_know_still_load(tmp_path):
    from subloc.models import Project

    path = tmp_path / "v.subloc.json"
    word = {"start": 0, "end": 1, "text": "a", "x": 2}
    line = {"id": 1, "start": 0, "end": 1, "text": "a", "mood": "happy", "words": [word]}
    path.write_text(json.dumps({"video": "v.mp4", "future": 1, "cues": [line]}), encoding="utf-8")
    p = Project.load(path)
    assert p.cues[0].text == "a" and p.cues[0].words[0].text == "a"


def test_a_failing_quiet_speech_pass_keeps_the_first_pass(monkeypatch, tmp_path):
    import numpy as np

    from subloc import pipeline
    from subloc.media import MediaInfo

    video = tmp_path / "v.mp4"
    video.write_bytes(b"x")
    info = MediaInfo(duration=10.0, width=0, height=0, fps=None, audio=[], subtitles=[])
    monkeypatch.setattr(pipeline, "probe", lambda v: info)
    monkeypatch.setattr(pipeline, "fingerprint", lambda v: "f")
    monkeypatch.setattr(pipeline, "default_audio_track", lambda i: 0)

    class Track:
        title, lang = "", "en"

    info.audio = [Track()]

    class Decoded:
        samples, missing = np.zeros(16000 * 10, np.float32), 0.0

    monkeypatch.setattr(pipeline, "load_audio", lambda v, t: Decoded())
    monkeypatch.setattr(pipeline, "transcribe",
                        lambda *a, **k: ([Cue(id=0, start=1, end=3, text="Hello there.")], "en"))  # fmt: skip
    monkeypatch.setattr(pipeline, "unload_model", lambda: None)

    def broken(*a, **k):
        raise RuntimeError("no GPU memory")

    monkeypatch.setattr(pipeline, "rescue", broken)
    proj, _ = pipeline.run(video, pipeline.Options(transcribe_only=True, voices=False))
    assert [c.text for c in proj.cues] == ["Hello there."]
