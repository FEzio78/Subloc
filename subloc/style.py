"""Subtitle look: presets, .ass output, and an exact preview.

SRT can't carry styling, so a chosen style is written as `Video.<lang>.ass` (honoured by VLC, MPV, MPC,
and used for burn-in). The preview renders a real frame of the video with libass through ffmpeg — the
same engine those players use — so what you see is what you get.
"""

import tempfile
from dataclasses import asdict, dataclass, replace
from pathlib import Path

from . import proc
from .media import _bin
from .models import Cue
from .subtitles import RLM, RTL, build_display

BASE_HEIGHT = 1080  # sizes are given for a 1080p frame and scale with the video


@dataclass(frozen=True)
class SubStyle:
    font: str = "Segoe UI"
    size: int = 54  # px at 1080p
    bold: bool = True
    text_color: str = "#FFFFFF"
    outline_color: str = "#000000"
    outline: float = 3.0  # px at 1080p; with a box: padding around the text
    shadow: float = 1.5
    box: bool = False  # background box behind the text
    box_color: str = "#000000"
    box_opacity: float = 0.6  # 0 = invisible, 1 = solid
    position: str = "bottom"  # bottom | top
    margin: int = 60  # px from the edge at 1080p

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "SubStyle":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


PRESETS: dict[str, SubStyle] = {
    "Classic": SubStyle(),
    "Boxed": SubStyle(box=True, outline=10.0, shadow=0.0, box_opacity=0.62),
    "Yellow": SubStyle(text_color="#F5C542"),
    "Large": SubStyle(size=68, outline=3.5, margin=70),
}
DEFAULT = PRESETS["Classic"]


def _ass_color(hex_rgb: str, opacity: float = 1.0) -> str:
    """#RRGGBB → &HAABBGGRR (ASS alpha: 00 = opaque)."""
    h = hex_rgb.lstrip("#")
    r, g, b = h[0:2], h[2:4], h[4:6]
    alpha = round((1 - max(0.0, min(1.0, opacity))) * 255)
    return f"&H{alpha:02X}{b}{g}{r}".upper()


def _style_line(s: SubStyle, height: int) -> str:
    k = height / BASE_HEIGHT
    if s.box:
        # BorderStyle 3: an opaque box drawn with the outline colour; Outline = padding.
        border, outline_col, back = 3, _ass_color(s.box_color, s.box_opacity), _ass_color("#000000", 0)
    else:
        border, outline_col, back = 1, _ass_color(s.outline_color), _ass_color("#000000", 0.5)
    align = 8 if s.position == "top" else 2
    fields = [
        "Default", s.font, str(round(s.size * k)), _ass_color(s.text_color), _ass_color(s.text_color),
        outline_col, back, "-1" if s.bold else "0", "0", "0", "0", "100", "100", "0", "0",
        str(border), f"{s.outline * k:.1f}", f"{s.shadow * k:.1f}", str(align),
        str(round(60 * k)), str(round(60 * k)), str(round(s.margin * k)), "1",
    ]  # fmt: skip
    return "Style: " + ",".join(fields)


def _ts(t: float) -> str:
    cs = round(max(t, 0) * 100)
    h, cs = divmod(cs, 360000)
    m, cs = divmod(cs, 6000)
    s, cs = divmod(cs, 100)
    return f"{h}:{m:02}:{s:02}.{cs:02}"


def ass_text(
    cues: list[Cue], style: SubStyle, translated: bool, lang: str | None, width: int = 1920, height: int = 1080
) -> str:
    rtl = lang in RTL
    head = [
        "[Script Info]",
        "; Made with Subloc",
        "ScriptType: v4.00+",
        f"PlayResX: {width}",
        f"PlayResY: {height}",
        "WrapStyle: 0",
        "ScaledBorderAndShadow: yes",
        "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, "
        "Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, "
        "MarginL, MarginR, MarginV, Encoding",
        _style_line(style, height),
        "",
        "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]
    events = []
    for d in build_display(cues, translated):
        lines = [f"{RLM}{ln}{RLM}" if rtl else ln for ln in d.lines]
        text = r"\N".join(ln.replace("{", "(").replace("}", ")") for ln in lines)
        if d.italic:
            text = r"{\i1}" + text
        events.append(f"Dialogue: 0,{_ts(d.start)},{_ts(d.end)},Default,,0,0,0,,{text}")
    return "\n".join(head + events) + "\n"


def write_ass(cues: list[Cue], path: Path, style: SubStyle, translated: bool, lang: str | None,
              width: int = 1920, height: int = 1080) -> None:  # fmt: skip
    path.write_text(ass_text(cues, style, translated, lang, width, height), encoding="utf-8-sig")


def render_preview(
    video: Path, at: float, text: str, style: SubStyle, lang: str | None, out_width: int = 1280,
    fonts_dir: Path | None = None,
) -> bytes:  # fmt: skip
    """PNG of the video frame at `at` seconds with `text` drawn in `style` by libass."""
    from .media import probe

    info = probe(video)
    w, h = info.width or 1920, info.height or 1080
    sample = [Cue(id=1, start=0.0, end=30.0, text=text, translation=text)]
    with tempfile.TemporaryDirectory(prefix="subloc-preview-") as tmp:
        # Run inside the temp folder and refer to the file by bare name: avoids ffmpeg filter-path
        # escaping of Windows drive letters and odd characters in the user's folder names.
        Path(tmp, "p.ass").write_text(ass_text(sample, style, True, lang, w, h), encoding="utf-8-sig")
        vf = "subtitles=p.ass" + (f":fontsdir='{fonts_dir.as_posix()}'" if fonts_dir else "")
        vf += f",scale={out_width}:-2"
        res = proc.run(
            [_bin("ffmpeg"), "-nostdin", "-v", "error", "-ss", f"{max(at, 0):.3f}", "-i", str(video.resolve()),
             "-frames:v", "1", "-vf", vf, "-f", "image2", "-c:v", "png", "-"],
            capture_output=True, cwd=tmp,
        )  # fmt: skip
    if not res.stdout:
        raise RuntimeError("Couldn't render the preview: " + res.stderr.decode(errors="replace")[-300:])
    return res.stdout


def with_changes(style: SubStyle, **changes) -> SubStyle:
    return replace(style, **changes)
