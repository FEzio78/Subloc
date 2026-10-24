import json

from subloc.glossary import Glossary, Term, extract, merge_into
from subloc.models import Cue


def test_relevant_matches_inflected_forms_and_variants():
    g = Glossary("ar", [Term("Демятков", "ديمياتكوف", variants=["Демитков"]), Term("Takumi", "تاكومي")])
    assert g.relevant("Сестра Ефима Демяткова пишет") == {"Демятков": "ديمياتكوف"}
    assert g.relevant("брат Демиткова") == {"Демитков": "ديمياتكوف"}
    assert g.relevant("nothing here") == {}


def test_existing_spelling_wins_and_variants_merge():
    g = Glossary("ar", [Term("Takumi", "تاكومي", user=True)])
    merge_into(g, Glossary("ar", [Term("Takumi", "تاكمي", variants=["Takkumi"]), Term("Itsuki", "إتسuki")]))
    assert g.find("takkumi").target == "تاكومي"
    assert g.find("Takumi").user
    assert len(g.terms) == 2


def test_load_survives_broken_or_other_language_file(tmp_path):
    p = tmp_path / "subloc.glossary.json"
    p.write_text("{ not json", encoding="utf-8")
    assert Glossary.load(p, "ar").terms == []
    p.write_text(json.dumps({"target_lang": "en", "terms": [{"source": "A", "target": "B"}]}), encoding="utf-8")
    assert Glossary.load(p, "ar").terms == []
    Glossary("ar", [Term("A", "ب")]).save(p)
    assert Glossary.load(p, "ar").find("a").target == "ب"


class FakeLLM:
    """Returns a canned glossary answer, one per chunk."""

    def __init__(self, answer):
        self.answer = answer

    def chat(self, model, messages, json_schema=None, temperature=0.2, reasoning="none"):
        return json.dumps(self.answer, ensure_ascii=False)


def test_extract_drops_invented_names_and_unheard_variants():
    cues = [Cue(id=1, start=0, end=1, text="Демятков, иди сюда!"), Cue(id=2, start=1, end=2, text="Где Демитков?")]
    answer = {
        "terms": [
            {"source": "Демятков", "variants": ["Демитков", "Демидов"], "target": "ديمياتكوف", "type": "person"},
            {"source": "Москва", "variants": [], "target": "موسكو", "type": "place"},  # never said
        ]
    }
    found = extract(cues, FakeLLM(answer), "m", "Russian", "Arabic", Glossary("ar"), log=lambda m: None)
    assert [t.source for t in found.terms] == ["Демятков"]
    assert found.terms[0].variants == ["Демитков"]


def test_codes_and_digit_word_names_are_never_transliterated():
    from subloc.langs import fixed_name

    assert fixed_name("Eight-Six") == "86"
    assert fixed_name("S13") == "S13"
    assert fixed_name("AE86") == "AE86"
    assert fixed_name("No. 2 driver") is None  # a phrase with a number is still translated
    assert fixed_name("Takumi") is None
    assert fixed_name("One") is None  # a single word isn't treated as a number name


def test_a_name_said_to_a_known_voice_gives_that_person_a_gender():
    from subloc.glossary import Glossary, Term, _calls
    from subloc.models import Cue

    assert _calls("Meryem, gel buraya!", "Meryem") and _calls("Neredesin, Meryem?", "Meryem")
    assert not _calls("Meryem eve gitti.", "Meryem")  # talking about her, not to her
    g = Glossary("ar", [Term("Meryem", "مريم"), Term("Kemal", "كمال", gender="female", gender_from="user"),
                        Term("Ankara", "أنقرة", type="place")])  # fmt: skip

    def line(i, text, to):
        c = Cue(id=i, start=i, end=i + 1, text=text)
        c.to = to
        return c

    cues = [line(1, "Meryem, gel!", "S2"), line(2, "Neredesin, Meryem?", "S2"), line(3, "Kemal, dur!", "S1"),
            line(4, "Kemal, bak!", "S1"), line(5, "Ankara, güzel!", "S1")]  # fmt: skip
    assert g.learn_genders(cues, {"S1": "male", "S2": "female"}) == 1
    assert (g.find("Meryem").gender, g.find("Meryem").gender_from) == ("female", "voices")
    assert g.find("Kemal").gender == "female"  # the user's choice stays
    assert g.find("Ankara").gender is None  # places have none
    assert g.gender_of("meryem") == "female"


def test_one_vote_is_not_enough():
    from subloc.glossary import Glossary, Term
    from subloc.models import Cue

    g = Glossary("ar", [Term("Meryem", "مريم")])
    c = Cue(id=1, start=0, end=1, text="Meryem, gel!")
    c.to = "S2"
    assert g.learn_genders([c], {"S2": "female"}) == 0 and g.find("Meryem").gender is None
