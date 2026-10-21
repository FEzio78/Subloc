"""Regenerate the README screenshots from a synthetic demo (generated video, invented dialogue).

    .venv/Scripts/python tools/make_screenshots.py

No real video is used, so screenshots never contain anyone's media. Needs ffmpeg; no translator needed
(the demo project already has its translations). Writes docs/screenshots/*.png.
"""

import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "docs" / "screenshots"

LINES = [
    ("Where are you going at this hour?", "إلى أين تذهب في هذا الوقت؟"),
    ("I just needed some air.", "كنت أحتاج فقط إلى بعض الهواء."),
    ("Then why is your bag packed?", "إذًا لماذا حزمت حقيبتك؟"),
    ("I never said I was leaving tonight.", "لم أقل إنني سأرحل الليلة."),
    ("And tomorrow?", "وماذا عن الغد؟"),
    ("I don't know.", "لا أعرف."),
    ("Jihoon, look at me.", "جيهون، انظر إليّ."),
    ("What will Mom do if you leave?", "وماذا ستفعل أمي إن رحلت؟"),
    ("Did you tell Seoyeon?", "هل أخبرت سويون؟"),
    ("Not yet. I'll call her from Busan.", "ليس بعد. سأتصل بها من بوسان."),
    ("I'll wait for you at the Han River bridge.", "سأنتظرك عند جسر نهر هان."),
    ("Don't be late this time.", "لا تتأخر هذه المرة."),
]


def make_demo(folder: Path) -> Path:
    from subloc.glossary import Glossary, Term
    from subloc.models import Cue, Project

    video = folder / "The Long Road - Episode 3.mkv"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i",
                    "gradients=s=1920x1080:c0=0x3c4a55:c1=0x1a1e23:c2=0x4a3f36:n=3:speed=0.01:d=480",
                    "-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo", "-t", "480", "-c:v", "libx264",
                    "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-c:a", "aac", str(video)], check=True)  # fmt: skip
    cues, t = [], 8.0
    for i, (en, ar) in enumerate(LINES * 4, 1):
        cues.append(Cue(id=i, start=t, end=t + 2.8, text=en, translation=ar, source="subs"))
        t += 9.5
    Project(video=str(video), language="en", cues=cues, target_language="ar").save(
        video.with_name(video.stem + ".subloc.json")
    )
    Glossary("ar", [Term("Jihoon", "جيهون"), Term("Seoyeon", "سويون"), Term("Busan", "بوسان", "place"),
                    Term("Han River", "نهر هان", "place")]).save(folder / "subloc.glossary.json")  # fmt: skip
    return video


def make_recent(folder: Path, main_video: Path) -> None:
    """Invented earlier projects for the Home list, in every state. The list lives in the temp folder, so the
    developer's own recent.json (and its thumbnails) never appears in a screenshot."""
    import time

    import subloc.ui.pages as pages
    from subloc import recent
    from subloc.models import Cue, Project

    data = folder / "data"
    recent.data_dir = lambda: data  # type: ignore[assignment]
    # Show tidy library folders instead of the temp folder (whose path holds the developer's user name).
    pages.folder_label = lambda v: "D:\\Series\\" + v.stem.split(" - ")[0] if " - " in v.stem else "D:\\Videos"
    demos = [  # name, colours, translated share (None = no project yet), opened hours ago
        ("The Long Road - Episode 4.mkv", "0x2f3d4a:c1=0x101418:c2=0x5a4632", 0.4, 0.3),
        ("Night Market - Episode 1.mkv", "0x4a2f3a:c1=0x16101a:c2=0x2f4a46", 0.0, 26),
        ("Summer Lecture.mp4", "0x3a4a2f:c1=0x141810:c2=0x46324a", None, 75),
    ]
    items: list = []
    for name, colours, share, hours in demos:
        v = folder / name
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i",
                        f"gradients=s=1280x720:c0={colours}:n=3:speed=0.02:d=40", "-t", "40", "-c:v", "libx264",
                        "-preset", "ultrafast", "-pix_fmt", "yuv420p", str(v)], check=True)  # fmt: skip
        if share is not None:
            n = len(LINES)
            cues = [Cue(id=i, start=i * 3.0, end=i * 3.0 + 2, text=en, translation=ar if i <= n * share else None)
                    for i, (en, ar) in enumerate(LINES, 1)]  # fmt: skip
            Project(video=str(v), language="en", cues=cues, target_language="ar").save(
                v.with_name(v.stem + ".subloc.json")
            )
        items = recent.touch(items, v)
        items[0].opened = time.time() - hours * 3600
    items = recent.touch(items, main_video)
    items[0].opened = time.time() - 2 * 3600
    items.append(recent.Recent(str(folder / "Old Trailer.mp4"), opened=time.time() - 9 * 86400))  # moved away
    items.sort(key=lambda r: -r.opened)
    for r in items:
        if r.path.exists():
            _, r.duration = recent.make_thumb(r.path)
    recent.save(items)


def main() -> None:
    import subloc.ui.app as A
    from subloc.config import Config
    from subloc.style import PRESETS
    from subloc.ui.setup import SetupWizard
    from subloc.ui.style_dialog import StyleDialog

    OUT.mkdir(parents=True, exist_ok=True)
    tmp = Path(tempfile.mkdtemp(prefix="subloc-shots-"))
    video = make_demo(tmp)
    make_recent(tmp, video)
    A.Config.load = classmethod(lambda cls: Config(setup_done=True))  # don't touch the developer's settings
    # Show the translator as ready (the real check would depend on whatever runs on this PC).
    A.MainWindow.check_engine = lambda self: self.top.set_engine(  # type: ignore[method-assign]
        A.tr("Translator ready · {model}", model="Gemma 4 26B"), True
    )
    app = QApplication([])
    app.setStyle("Fusion")
    state: dict = {}
    steps: list = []

    def at(ms: int, fn) -> None:
        steps.append((ms, fn))

    def shot(name: str, widget=None):
        def f():
            app.processEvents()
            (widget or state["w"]).grab().save(str(OUT / f"{name}.png"))
            print("saved", name)

        return f

    def window(lang: str):
        def f():
            if "w" in state:
                state["w"].close()
            A.apply_language(app, lang)
            w = A.MainWindow()
            w.resize(1320, 820)
            w.show()
            state["w"] = w

        return f

    def working():
        w = state["w"]
        w.open_video(video)
        j = w.jobp
        j.player.shutdown()  # its position updates would move the highlighted line
        j.display.setCurrentWidget(j.preview)
        j.set_state("working")
        j.stages.reset(reading_subtitles=True)
        w.started -= 40
        partial = [c if i < 18 else type(c)(**{**c.__dict__, "translation": None}) for i, c in enumerate(w.cues)]
        w._on_stage("translate", 0.38, "")
        w._on_cues(partial)
        w._set_now(partial[17])

    def review():
        w = state["w"]
        w.job = None
        w.jobp.player.shutdown()
        proj = w._load_project()
        w.cues = proj.cues
        w._show_cues(proj.cues)
        w._done_view(proj)
        w.jobp.player.shutdown()
        w.jobp.display.setCurrentWidget(w.jobp.preview)  # the player surface can't be captured; show a frame
        w._set_now(proj.cues[6])
        w.jobp.view.open_editor(7)

    def style():
        d = StyleDialog(state["w"], PRESETS["Boxed"], video, 480.0, LINES[3][1], 37.0, "ar")
        d.show()
        state["d"] = d

    def setup():
        state["d"].close()
        s = SetupWizard(None, Config())
        s.show()
        s._go(1)
        state["s"] = s

    at(300, window("en"))
    at(1500, shot("home"))
    at(200, working)
    at(2500, shot("working"))
    at(200, review)
    at(2500, shot("review"))
    at(200, style)
    at(2500, lambda: shot("style", state["d"])())
    at(200, setup)
    at(3500, lambda: shot("setup", state["s"])())
    at(200, lambda: state["s"].close())
    at(200, window("ar"))
    at(1500, shot("home-ar"))
    at(200, working)
    at(2500, shot("working-ar"))
    at(300, app.quit)
    t = 0
    for ms, fn in steps:
        t += ms
        QTimer.singleShot(t, fn)
    app.exec()


if __name__ == "__main__":
    main()
