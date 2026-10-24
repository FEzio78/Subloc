import json
import threading

from subloc import addressee, pipeline
from subloc.models import Cue, Project
from subloc.translate import Who, translate
from subloc.voices import likely_speaker


def voiced(spec):
    """Cues from (start, speaker, gender, text)."""
    out = []
    for i, (start, spk, g, text) in enumerate(spec, 1):
        c = Cue(id=i, start=start, end=start + 2, text=text)
        c.speaker, c.gender = spk, g
        out.append(c)
    return out


COUPLE = [(0, "S1", "male", "Are you hungry?"), (3, "S2", "female", "No."), (6, "S1", "male", "Sit down."),
          (20, "S3", "female", "Hi."), (23, "S4", "male", "Hello.")]  # fmt: skip


def test_whole_scenes_are_packed_and_long_ones_split_with_context(monkeypatch):
    monkeypatch.setattr(addressee, "LISTEN_BATCH", 4)
    monkeypatch.setattr(addressee, "CONTEXT", 1)
    cs = voiced([(i * 3, "S1", "male", f"l{i}") for i in range(6)] + [(60, "S2", "female", "a"), (63, "S3", None, "b")])
    who = Who.of(cs)
    parts = addressee.chunks(cs, who.scene)
    assert [[c.id for c in lines] for _, lines, _ in parts] == [[1, 2, 3, 4], [5, 6], [7, 8]]
    assert [c.id for c in parts[1][0]] == [4]  # the long scene's second piece sees the line before it
    assert [c.id for c in parts[0][2]] == [5]


def test_a_mislabelled_line_is_given_to_the_one_other_person_with_its_voice():
    cs = voiced([*COUPLE[:3], (9, "S1", "male", "Now.")])
    cs[2].gender = "female"  # under S1 (a man's voice on his other lines) but a woman's voice: S2 said it
    who = Who.of(cs)
    assert likely_speaker(cs[2], who.people[1], who.voice) == "S2"
    assert who.choices(cs[2]) == ["S1"]
    assert who.choices(cs[0]) == ["S2"]  # only this scene's people, never the line's own speaker


def test_listeners_come_from_the_lines_own_scene_and_bad_answers_are_dropped():
    cs = voiced(COUPLE)
    who = Who.of(cs)
    choices = {c.id: who.choices(c) for c in cs}
    schema = addressee.schema_for(cs, choices)["properties"]["lines"]["prefixItems"]
    assert schema[0]["properties"]["to"]["enum"] == ["S2", "several", "unknown"]
    assert schema[3]["properties"]["to"]["enum"] == ["S4", "several", "unknown"]  # scene 2 knows no S1/S2
    answer = json.dumps({"lines": [{"id": 1, "to": "S2"}, {"id": 2, "to": "unknown"}, {"id": 3, "to": "S1"},
                                   {"id": 4, "to": "S2"}, {"id": 5, "to": "several"}]})  # fmt: skip
    # line 3 can't be to its own speaker, line 4 not to someone from another scene
    assert addressee._parse(answer, cs, choices) == {1: "S2", 2: None, 5: "several"}


class LLM:
    """Listener pass: S1's lines go to S2. Translation: checks it was told the listener, answers feminine."""

    def __init__(self):
        self.calls = []

    def chat(self, model, messages, json_schema=None, temperature=0.2, reasoning="none"):
        user = messages[-1]["content"]
        self.calls.append(user)
        ids = [json.loads(line)["id"] for line in user.splitlines() if line.startswith('{"id"')]
        if "Do not translate anything" in messages[0]["content"]:
            return json.dumps({"lines": [{"id": i, "to": "S2" if i in (1, 3) else "unknown"} for i in ids]})
        assert '"to": "S2", "to_voice": "woman"' in user
        # the decided listener is written again just before each translation, and can only be that one
        assert [i["properties"]["to"]["enum"] for i in json_schema["properties"]["lines"]["prefixItems"]] == [
            ["S2" if i in (1, 3) else "unknown"] for i in ids
        ]
        return json.dumps({"lines": [{"id": i, "src": "", "text": f"T{i}"} for i in ids]})


def test_translation_takes_the_listeners_as_decided():
    cs = voiced(COUPLE[:3])
    who = Who.of(cs)
    llm = LLM()
    found = addressee.decide(cs, llm, "m", "en", who.scene, who.people, who.voice, log=lambda m: None, workers=1)
    assert found == {1: "S2", 2: None, 3: "S2"}
    translate(cs, llm, "m", "en", "ar", log=lambda m: None, workers=1, listeners=found)
    assert [(c.to, c.translation) for c in cs] == [("S2", "T1"), (None, "T2"), ("S2", "T3")]


def test_the_scene_pass_is_saved_and_not_asked_again(monkeypatch, tmp_path):
    proj = Project(video="v.mp4", cues=voiced(COUPLE[:3]), meta={"voices": {"key": {"v": 2}}})
    calls = []

    def decide(*a, **kw):
        calls.append(1)
        return {1: "S2", 3: "S2"}

    monkeypatch.setattr(addressee, "decide", decide)
    args = (tmp_path / "v.mp4", pipeline.Options(scene_pass=True), proj, lambda: None, pipeline.Reporter(),
            threading.Event(), None, "m", {"target": "ar", "model": "m"}, 1)  # fmt: skip
    assert pipeline._listeners(*args) == {1: "S2", 3: "S2"}
    assert pipeline._listeners(*args) == {1: "S2", 3: "S2"}
    assert len(calls) == 1
    off = (tmp_path / "v.mp4", pipeline.Options(scene_pass=False), *args[2:])
    assert pipeline._listeners(*off) is None


def test_a_listener_set_by_hand_is_used_and_kept(monkeypatch, tmp_path):
    seen = []

    class Fake:
        def chat(self, model, messages, json_schema=None, temperature=0.2, reasoning="none"):
            user = messages[-1]["content"]
            seen.append((messages[0]["content"], user, json_schema))
            ids = [json.loads(line)["id"] for line in user.splitlines() if line.startswith('{"id"')]
            return json.dumps({"lines": [{"id": i, "src": "", "to": "woman", "text": "لكي"} for i in ids]})

    video = tmp_path / "v.mp4"
    video.write_bytes(b"")
    cs = [Cue(id=1, start=0, end=2, text="For you.", translation="لك"), Cue(id=2, start=3, end=5, text="Ok.")]
    Project(video=str(video), cues=cs, target_language="ar").save(pipeline.project_path(video))
    monkeypatch.setattr(pipeline, "_client", lambda opt: Fake())
    monkeypatch.setattr(pipeline, "write_outputs", lambda *a: [])
    opt = pipeline.Options(llm_model="m", auto_glossary=False)
    proj = pipeline.retranslate_lines(video, [1], opt, listener="woman")
    system, user, schema = seen[-1]
    assert '"to": "woman", "to_voice": "woman"' in user and "set by the user" in system  # no voices needed
    assert schema["properties"]["lines"]["prefixItems"][0]["properties"]["to"]["enum"] == ["woman"]
    assert proj.cues[0].translation == "لكي" and proj.cues[0].to == "woman"
    assert pipeline.fixed_listeners(Project.load(pipeline.project_path(video))) == {1: "woman"}
    proj.cues[0].text = "Something else."  # the line changed: the old choice no longer applies
    assert pipeline.fixed_listeners(proj) == {}


def test_a_few_listeners_set_by_hand_leave_the_others_to_the_translator():
    """One line fixed by the user must not switch every other line to 'unknown' (it did: 5 of 481 kept a listener)."""
    seen = {}

    class Fake:
        def chat(self, model, messages, json_schema=None, temperature=0.2, reasoning="none"):
            items = json_schema["properties"]["lines"]["prefixItems"]
            seen["enums"] = [i["properties"]["to"]["enum"] for i in items]
            seen["system"] = messages[0]["content"]
            ids = [i["properties"]["id"]["enum"][0] for i in items]
            to = {1: "S2", 2: "S1", 3: "woman"}
            return json.dumps({"lines": [{"id": i, "src": "", "to": to[i], "text": f"T{i}"} for i in ids]})

    cs = voiced(COUPLE[:3])
    translate(cs, Fake(), "m", "en", "ar", log=lambda m: None, workers=1, listeners={3: "woman"})
    assert seen["enums"] == [["S2", "several", "unknown"], ["S1", "several", "unknown"], ["woman"]]
    assert "first decide who it is spoken to" in seen["system"] and "set by the user" in seen["system"]
    assert [c.to for c in cs] == ["S2", "S1", "woman"]
