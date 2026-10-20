from subloc.models import Cue
from subloc.style import DEFAULT, PRESETS, SubStyle, _ass_color, ass_text


def test_colors_convert_to_ass_order_and_alpha():
    assert _ass_color("#F5C542") == "&H0042C5F5"  # BGR, opaque
    assert _ass_color("#000000", 0.6) == "&H66000000"  # 40% transparent


def test_ass_has_style_and_rtl_events_scaled_to_video():
    cues = [Cue(id=1, start=1.0, end=3.5, text="hi", translation="مرحبا!"),
            Cue(id=2, start=4.0, end=6.0, text="la", translation="لا لا", kind="song")]  # fmt: skip
    out = ass_text(cues, PRESETS["Boxed"], translated=True, lang="ar", width=1280, height=720)
    assert "PlayResY: 720" in out
    style = next(line for line in out.splitlines() if line.startswith("Style: Default"))
    fields = style.split(",")
    assert fields[2] == "36"  # 54 px at 1080p → 36 at 720p
    assert fields[15] == "3"  # box
    assert "Dialogue: 0,0:00:01.00,0:00:03.50,Default,,0,0,0,,\u200fمرحبا!\u200f" in out
    assert "{\\i1}" in out  # song lyrics in italics


def test_top_position_and_round_trip():
    s = SubStyle(position="top", text_color="#F5C542")
    assert ass_text([], s, True, "ar").splitlines()[10].split(",")[18] == "8"
    assert SubStyle.from_dict(s.to_dict()) == s
    assert PRESETS["Classic"] == DEFAULT
