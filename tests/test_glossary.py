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
