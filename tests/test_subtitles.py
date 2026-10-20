"""Tests for the parts that don't need a GPU or LM Studio. Run: .venv/Scripts/python -m pytest"""

import json

from subloc.models import Cue, Word
from subloc.segment import continuation_flags, continues_previous, max_chars, segment
from subloc.subparse import guess_language, parse_ass, parse_srt
from subloc.subtitles import RLM, build_display, wrap, write_srt
from subloc.translate import _batches, _parse

ASS = """[Script Info]
Title: test

[V4+ Styles]
Format: Name, Fontname
Style: Default,Arial

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
Dialogue: 0,0:00:01.00,0:00:03.00,Default,,0,0,0,,{\\an5\\pos(720,100)}This story
Dialogue: 0,0:00:01.00,0:00:03.00,Default,,0,0,0,,{\\an5\\pos(720,200)}is fiction.
Dialogue: 0,0:00:04.00,0:00:06.00,Default,,0,0,0,,{\\i1}Running in the ninety{\\i0}\\N{\\i1}is a new way{\\i0}
Dialogue: 0,0:00:07.00,0:00:08.50,Default,,0,0,0,,Hey, Takumi!
Dialogue: 1,0:00:07.00,0:00:08.50,Default,,0,0,0,,Hey, Takumi!
Dialogue: 0,0:00:09.00,0:00:10.00,Default,,0,0,0,,{\\p1}m 0 0 l 100 0 100 100{\\p0}
"""


def cue(i, start, end, text, **kw):
    return Cue(id=i, start=start, end=end, text=text, **kw)


# ---------------------------------------------------------------- parsing existing subtitles


def test_ass_joins_sign_pieces_marks_songs_and_drops_drawings():
    cues = parse_ass(ASS)
    assert [c.text for c in cues] == ["This story is fiction.", "Running in the ninety is a new way", "Hey, Takumi!"]
    assert [c.kind for c in cues] == ["caption", "song", "dialogue"]
    assert cues[0].start == 1.0 and cues[0].end == 3.0
    assert [c.id for c in cues] == [1, 2, 3]


def test_srt_strips_tags_and_joins_lines():
    srt = "1\n00:00:01,000 --> 00:00:02,500\n<i>Hello</i>\nthere\n\n2\n00:01:00,250 --> 00:01:02,000\n{\\an8}Bye\n"
    cues = parse_srt(srt)
    assert [(c.start, c.end, c.text) for c in cues] == [(1.0, 2.5, "Hello there"), (60.25, 62.0, "Bye")]


def test_guess_language_rejects_wrong_tags():
    english = [cue(1, 0, 1, "Hey, Takumi! Quit zoning out!")]
    japanese = [cue(1, 0, 1, "拓海！ぼーっとするな！")]
    assert guess_language(english, "ja") is None  # English text tagged 'jpn'
    assert guess_language(english, "en") == "en"
    assert guess_language(japanese, "ja") == "ja"
    assert guess_language(japanese, "en") is None


# ---------------------------------------------------------------- segmentation


def test_long_segment_splits_at_pause():
    words = [
        Word(0.0, 0.5, " Hello"),
        Word(0.5, 1.0, " there."),
        Word(1.1, 1.5, " How"),
        Word(1.5, 2.0, " are"),
        Word(2.0, 2.4, " you"),
        Word(3.4, 3.8, " Fine"),
        Word(3.8, 4.2, " thanks."),
    ]
    out = segment([cue(0, 0.0, 4.2, "Hello there. How are you Fine thanks.", words=words)])
    assert [c.text for c in out] == ["Hello there. How are you", "Fine thanks."]


def test_dramatic_pause_does_not_split_short_japanese_line():
    # Whisper segment 'ここで殺すか' with a 2 s pause after 'ここ': must stay one subtitle.
    words = [
        Word(32.5, 33.3, "ここ"),
        Word(35.3, 35.6, "で"),
        Word(35.6, 35.8, "殺"),
        Word(35.8, 36.0, "す"),
        Word(36.0, 36.1, "か"),
    ]
    out = segment([cue(0, 32.5, 36.1, "ここで殺すか", words=words)])
    assert [c.text for c in out] == ["ここで殺すか"]


def test_continues_previous_only_for_unfinished_sentences():
    a = cue(1, 0, 1, "솔직히 멤버 중에")
    b = cue(2, 1.1, 2, "누가 제일 좋아요?")
    c = cue(3, 2.1, 3, "Next one.")
    assert continues_previous(a, b)
    assert not continues_previous(b, c)
    assert not continues_previous(None, a)


def test_capital_letter_starts_a_new_sentence_without_punctuation():
    # Whisper's Turkish often has no final punctuation; each line here is a different speaker.
    a = cue(1, 0, 1, "Bence bir an önce evlenmeleri lazım")
    b = cue(2, 1.1, 2, "Konuya gir konuya gir Meral")
    c = cue(3, 2.1, 3, "ve sonra eve gittik")
    assert not continues_previous(a, b)
    assert continues_previous(b, c)


def test_continuation_chains_are_capped():
    cues = [cue(i, i, i + 0.9, "и потом") for i in range(1, 11)]  # no punctuation, lowercase
    flags = continuation_flags(cues)
    longest = run = 0
    for f in flags:
        run = run + 1 if f else 0
        longest = max(longest, run)
    assert longest == 3  # groups of at most 4 cues


def test_max_chars_scales_with_duration():
    assert max_chars(cue(1, 0, 0.5, "x")) == 16
    assert max_chars(cue(1, 0, 3.0, "x")) == 51
    assert max_chars(cue(1, 0, 10.0, "x")) == 84


# ---------------------------------------------------------------- output


def test_wrap_splits_near_middle():
    assert wrap("short line") == ["short line"]
    lines = wrap("this is a fairly long subtitle line that needs two rows")
    assert len(lines) == 2 and all(len(x) <= 42 for x in lines)


def test_short_lines_pair_as_dialogue_but_not_mid_sentence():
    cues = [
        cue(1, 0.0, 0.4, "Why?", translation="لماذا؟"),
        cue(2, 0.5, 2.0, "Remember the intro?", translation="هل تتذكر المقدمة؟"),
        cue(3, 3.0, 3.4, "Honestly, among", translation="بصراحة، من بين"),
        cue(4, 3.5, 5.0, "the members?", translation="الأعضاء؟"),
    ]
    out = build_display(cues, translated=True)
    assert out[0].lines == ["- لماذا؟", "- هل تتذكر المقدمة؟"]
    assert len(out) == 3  # 3 and 4 are one sentence: not paired


def test_srt_rtl_marks_and_song_italics(tmp_path):
    cues = [cue(1, 1.0, 3.0, "hi", translation="مرحبا!"), cue(2, 4.0, 6.0, "la la", translation="لا لا", kind="song")]
    path = tmp_path / "x.ar.srt"
    write_srt(cues, path, translated=True, lang="ar")
    text = path.read_text(encoding="utf-8-sig")
    assert f"00:00:01,000 --> 00:00:03,000\n{RLM}مرحبا!{RLM}" in text
    assert f"<i>{RLM}لا لا{RLM}</i>" in text


# ---------------------------------------------------------------- translation plumbing


def test_batches_never_split_a_sentence():
    cues = [cue(i, i, i + 0.9, "word" if i % 30 != 24 else "unfinished") for i in range(1, 61)]
    flags = continuation_flags(cues)
    batches = _batches(cues)
    assert len(batches) > 1  # no punctuation still yields batches
    for b in batches:
        assert not flags[cues.index(b[0])]  # a batch never starts mid-group


def test_parse_repairs_a_miswritten_id_by_position():
    batch = [cue(i, i, i + 1, "x") for i in (531, 532, 533)]
    raw = json.dumps({"lines": [{"id": 531, "text": "أ"}, {"id": 532, "text": "ب"}, {"id": 503, "text": "ج"}]})
    assert _parse(raw, batch) == {531: "أ", 532: "ب", 533: "ج"}


def test_parse_keeps_good_lines_from_partial_answer():
    batch = [cue(i, i, i + 1, "x") for i in (1, 2, 3)]
    raw = json.dumps({"lines": [{"id": 1, "text": "أ"}, {"id": 3, "text": "ج"}]})
    assert _parse(raw, batch) == {1: "أ", 3: "ج"}  # 2 is re-asked on its own


def test_parse_salvages_cut_off_json():
    batch = [cue(i, i, i + 1, "x") for i in (1, 2, 3)]
    raw = '{"lines": [{"id": 1, "text": "مرحبا \\"صديقي\\""}, {"id": 2, "text": "وداعا"}, {"id": 3, "text": "نص مقطو'
    assert _parse(raw, batch) == {1: 'مرحبا "صديقي"', 2: "وداعا"}


def test_translations_that_slid_onto_the_wrong_line_are_rejected():
    # Real case (Initial D): every translation moved down one line. The copied "src" gives it away.
    batch = [cue(85, 0, 1, "え?"), cue(86, 1, 2, "不思議だな なんであんなことにみんな熱くなるのかな")]
    shifted = {
        "lines": [{"id": 85, "src": "なあ 五木", "text": "Hey, Itsuki."}, {"id": 86, "src": "え?", "text": "Huh?"}]
    }
    good = {"lines": [{"id": 85, "src": "え?", "text": "Huh?"}, {"id": 86, "src": "不思議だな", "text": "Strange..."}]}
    assert _parse(json.dumps(shifted, ensure_ascii=False), batch) == {}
    assert _parse(json.dumps(good, ensure_ascii=False), batch) == {85: "Huh?", 86: "Strange..."}


def test_parse_handles_code_fences():
    payload = {"lines": [{"id": 1, "text": " مرحبا "}, {"id": 2, "text": "وداعا"}]}
    assert _parse("```json\n" + json.dumps(payload, ensure_ascii=False) + "\n```") == {1: "مرحبا", 2: "وداعا"}


def test_arabic_output_never_contains_persian_letters():
    from subloc.langs import clean_output

    assert clean_output("سيريوژا وپاڤل وگوگل وچای", "ar") == "سيريوجا وبافل وغوغل وتشاي"
    assert clean_output("ژ", "fa") == "ژ"  # only Arabic targets are changed


def test_single_line_requests_are_not_rejected_by_the_alignment_check():
    # Real case: correct translation, but the model copied a context line into "src".
    batch = [cue(75, 0, 2, "Вы что-то увидели? Вас что-то напрягло?")]
    raw = {"lines": [{"id": 75, "src": "А что я мо", "text": "هل رأيت شيئًا؟"}]}
    assert _parse(json.dumps(raw, ensure_ascii=False), batch) == {75: "هل رأيت شيئًا؟"}


def test_no_speech_gives_no_cues_instead_of_crashing():
    assert segment([]) == []
