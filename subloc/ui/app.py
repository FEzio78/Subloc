"""Main window: connects the screens to the engine. All slow work runs on background threads; results come
back through Qt signals (queued onto the UI thread)."""

import bisect
import contextlib
import ctypes
import json
import os
import shutil
import sys
import threading
import time
from pathlib import Path
from typing import Any

from PySide6.QtCore import QFileSystemWatcher, QObject, QSettings, QStandardPaths, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QKeySequence, QPixmap, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QFileDialog,
    QInputDialog,
    QMainWindow,
    QMessageBox,
    QProgressDialog,
    QStackedWidget,
    QSystemTrayIcon,
    QVBoxLayout,
    QWidget,
)

from .. import batch, busy, library, power, proc, recent, update, voices
from ..batch import Item, find_videos, load_queue, save_queue
from ..burn import burn
from ..busy import BusyLock
from ..catalog import TRANSLATORS
from ..config import Config
from ..engine import BuiltinEngine
from ..glossary import Glossary
from ..glossary import folder_path as glossary_path
from ..langs import LANGS
from ..llm import LMStudio
from ..media import MediaInfo, default_audio_track, grab_frame, probe, subtitle_source
from ..models import Cue, Project
from ..pipeline import (
    Cancelled,
    Options,
    Reporter,
    project_path,
    retranslate_lines,
    run,
    update_line,
    write_outputs,
)
from ..service import version
from ..style import DEFAULT, PRESETS, SubStyle, write_ass
from ..subtitles import RTL
from . import icons
from . import theme as t
from .home_ctl import HomeMixin
from .i18n import rtl, set_language, tr, translate_tree
from .intro import play as play_intro
from .library_ctl import LibraryMixin
from .library_page import LibraryPage
from .lines import Row
from .pages import HomePage, JobPage, QueuePage, SettingsPage, select_data
from .player import available as player_available
from .queue_ctl import QueueMixin
from .setup import SetupWizard
from .shortcuts import SHORTCUTS, ShortcutsDialog
from .style_dialog import StyleDialog
from .widgets import TopBar, app_icon, fmt_time
from .widgets import toast as show_toast

PROGRAM_FILES = [Path(os.environ.get("PROGRAMFILES", "C:/Program Files")),
                 Path(os.environ.get("PROGRAMFILES(X86)", "C:/Program Files (x86)"))]  # fmt: skip
VLC_PATHS = [pf / "VideoLAN" / "VLC" / "vlc.exe" for pf in PROGRAM_FILES]


def reveal(path: Path) -> None:
    """Open the folder in Explorer with the file selected."""
    proc.popen(["explorer", "/select,", os.path.normpath(path)])


class Bus(QObject):
    # job
    log = Signal(str)
    warn = Signal(str)
    stage = Signal(str, float, str)
    cues = Signal(list)
    finished = Signal(list)
    failed = Signal(str)
    # misc
    engine = Signal(object)  # dict
    frame = Signal(int, bytes)
    line_done = Signal(str)  # error message or ""
    queue_item = Signal(int, str, str)
    queue_progress = Signal(int, float)
    queue_done = Signal()
    burn_progress = Signal(float)
    burn_done = Signal(str, str)
    thumb = Signal(str, float)  # video, duration (Home list thumbnail is ready)
    lib_progress = Signal(str)
    lib_scanned = Signal(object)  # library.Scan, or None when stopped
    update = Signal(object, str, bool)  # update.Release or None, error ("" = fine), asked by the user
    update_progress = Signal(float)
    update_ready = Signal(str, str)  # downloaded installer, error ("" = fine; "stopped")
    voices = Signal(float, str)  # speaker models download: fraction, error ("" = fine; fraction 1 = done)


def _rows(cues: list[Cue]) -> list[Row]:
    return [Row(c.id, c.start, c.end, c.text, c.translation, c.kind, c.speaker, c.gender, c.to) for c in cues]


class MainWindow(HomeMixin, LibraryMixin, QueueMixin, QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Subloc")
        self.resize(1320, 820)
        self.setMinimumSize(1040, 680)
        self.settings = QSettings("Subloc", "Subloc")
        self.bus = Bus()
        self.video: Path | None = None
        self.info: MediaInfo | None = None
        self.job: threading.Thread | None = None
        self.cancel = threading.Event()
        self.cues: list[Cue] = []
        self.frame_request = 0
        self.last_frame_at = 0.0
        self.started = time.time()
        self.queue: list[Item] = load_queue()  # kept between sessions
        self.busy = BusyLock("Subloc's window")  # the graphics card, shared with the command line and agents
        self._seen: dict[str, float] = {}  # list files' times when last read (the CLI or an agent may change them)
        for name, path in (("recent", recent._file()), ("library", library._file()), ("queue", batch._queue_file())):
            self._outside_change(name, path)  # the times at start: later changes came from outside
        self.queue_progress: dict[int, float] = {}
        self.tray: QSystemTrayIcon | None = None
        self.countdown_secs = 60  # before sleeping / shutting down after a queue
        self._burn_dialog: QProgressDialog | None = None
        self.queue_job: threading.Thread | None = None
        self.queue_cancel = threading.Event()
        self.sub_style = self._load_style()  # not .style: that would hide QWidget.style()
        self.cfg = Config.load()
        self.engine: BuiltinEngine | None = None
        self.recent = recent.load()
        self._thumb_tried: set[str] = set()
        self._thumb_job: threading.Thread | None = None
        self.lib = library.load()
        self.lib_job: threading.Thread | None = None
        self.lib_cancel = threading.Event()
        self._scans: list[tuple[str, bool]] = []  # (folder, deep) waiting to be read
        self.watcher = QFileSystemWatcher(self)
        self._changed: set[str] = set()
        self._change_timer = QTimer(self, singleShot=True, interval=3000)  # changes come in bursts

        root = QWidget()
        lay = QVBoxLayout(root)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        self.top = TopBar()
        self.top.navigate.connect(self.show_page)
        lay.addWidget(self.top)
        self.stack = QStackedWidget()
        self.home, self.jobp, self.queuep, self.settingsp = HomePage(), JobPage(), QueuePage(), SettingsPage()
        self.libp = LibraryPage()
        for p in (self.home, self.jobp, self.libp, self.queuep, self.settingsp):
            self.stack.addWidget(p)
        lay.addWidget(self.stack, 1)
        self.setCentralWidget(root)

        self._wire()
        self._bind_shortcuts()
        self._restore()
        self._show_recent()
        self._refresh_queue()
        self._update_watcher()
        self._make_engine()  # after the screens exist: it updates the Settings page
        translate_tree(self)
        self.engine_timer = QTimer(self, interval=12000)
        self.engine_timer.timeout.connect(self.check_engine)
        self.engine_timer.start()
        self.check_engine()
        QTimer.singleShot(5000, self._daily_update_check)  # only if the user chose "once a day"

    # ---------------------------------------------------------------- wiring

    def _wire(self) -> None:
        b = self.bus
        b.log.connect(lambda m: None)
        b.warn.connect(self._on_warn)
        b.stage.connect(self._on_stage)
        b.cues.connect(self._on_cues)
        b.finished.connect(self._on_finished)
        b.failed.connect(self._on_failed)
        b.engine.connect(self._on_engine)
        b.frame.connect(self._on_frame)
        b.line_done.connect(self._on_line_done)
        b.queue_item.connect(self._on_queue_item)
        b.queue_progress.connect(self._on_queue_progress)
        b.queue_done.connect(self._on_queue_done)
        b.burn_progress.connect(self._on_burn_progress)
        b.burn_done.connect(self._on_burn_done)
        b.thumb.connect(self._on_thumb)
        b.lib_progress.connect(self.libp.set_progress)
        b.lib_scanned.connect(self._on_lib_scanned)
        b.update.connect(self._on_update)
        b.update_progress.connect(lambda f: self.settingsp.show_update(tr("Downloading {n}…", n=f"{f:.0%}"), True))
        b.update_ready.connect(self._on_update_ready)
        lp = self.libp
        lp.add_folder.connect(self.add_library_folder)
        lp.refresh.connect(self.refresh_library)
        lp.remove_root.connect(self.remove_library_root)
        lp.watch.connect(self.set_library_watch)
        lp.open_video.connect(lambda v: self.open_video(Path(v)))
        lp.translate.connect(self.queue_from_library)
        lp.reveal.connect(lambda v: reveal(Path(v)))
        self.watcher.directoryChanged.connect(self._on_dir_changed)
        self._change_timer.timeout.connect(self._flush_changes)
        self.home.tgt.currentIndexChanged.connect(lambda *_: self._library_changed(save=False))

        self.home.files.connect(self.open_paths)
        self.home.open_recent.connect(self.open_recent)
        self.home.reveal_recent.connect(lambda v: reveal(Path(v)))
        self.home.remove_recent.connect(self.forget_recent)
        for c in (self.home.src, self.home.tgt, self.home.speech, self.home.model):
            c.currentIndexChanged.connect(self._save)
        j = self.jobp
        j.start.connect(self.start_job)
        j.stop.connect(self.stop_job)
        j.play.connect(self.toggle_play)
        j.open_external.connect(self.open_external)
        j.watch.connect(self.watch_now)
        j.player.position.connect(self._on_play_pos)
        j.player.playing.connect(self._on_playing)
        j.show_files.connect(self.show_files)
        j.edit_style.connect(self.edit_style)
        j.export.connect(self.export)
        j.seek.connect(self.preview_at)
        j.name_clicked.connect(self.edit_name)
        j.source.currentIndexChanged.connect(self._source_changed)
        j.view.line_clicked.connect(self._line_clicked)
        d = j.view.delegate
        d.edit_save.connect(self.save_line)
        d.edit_retranslate.connect(lambda cid: self.retranslate([cid]))
        d.edit_play.connect(self._play_from)
        d.edit_listener.connect(lambda cid, who: self.retranslate([cid], listener=who))
        self._last_subs_write = 0.0
        self._starts: list[float] = []
        q = self.queuep
        q.add.connect(self.add_to_queue_dialog)
        q.start.connect(self.start_queue)
        q.stop.connect(self.stop_queue)
        q.clear.connect(self.clear_queue)
        q.open_item.connect(lambda i: self.open_video(self.queue[i].video))
        q.reveal_item.connect(lambda i: reveal(self.queue[i].video))
        q.remove_item.connect(self.remove_from_queue)
        s = self.settingsp
        s.changed.connect(self._save)
        s.edit_style.connect(self.edit_style)
        s.run_setup.connect(self.run_setup)
        s.language.connect(self.change_language)
        s.shortcuts.connect(self.show_shortcuts)
        s.check_updates.connect(self.check_updates)
        s.get_voices.connect(self.get_voices)
        self.bus.voices.connect(self._on_voices)
        s.open_link.connect(lambda url: QDesktopServices.openUrl(QUrl(url)))

    def toast(self, text: str, kind: str = "info", action: tuple[str, Any] | None = None, secs: float = 4.0) -> None:
        """A short message at the bottom of the window that goes away by itself (for things that need no answer)."""
        show_toast(self, text, kind, action, secs)

    def show_page(self, key: str) -> None:
        """Home (new project + recent ones; the running video is listed first), Library, Queue or Settings."""
        pages = {"home": self.home, "library": self.libp, "queue": self.queuep, "settings": self.settingsp}
        if key == "home":
            self._show_recent()
        self.stack.setCurrentWidget(pages[key])
        if key == "library" and self.lib_job is None and self._outside_change("library", library._file()):
            self.lib = library.load()
            self._update_watcher()
        if key == "queue" and self.queue_job is None and self._outside_change("queue", batch._queue_file()):
            self.queue = load_queue()
            self.queue_progress.clear()
            self._refresh_queue()
        if key == "library":
            self._library_changed(save=False)
        self.top.select(key)

    # ---------------------------------------------------------------- lists others may change

    def _outside_change(self, name: str, path: Path) -> bool:
        """Did the file change since it was last read here? (The command line or an agent may have written it.)"""
        try:
            t = path.stat().st_mtime
        except OSError:
            return False
        changed = name in self._seen and t != self._seen[name]
        self._seen[name] = t
        return changed

    # ---------------------------------------------------------------- settings

    def _restore(self) -> None:
        s = self.settings
        select_data(self.home.src, s.value("source"))
        select_data(self.home.tgt, s.value("target", "ar"))
        select_data(self.home.speech, s.value("speech", self.cfg.speech_model))
        select_data(self.settingsp.parallel, s.value("parallel", 2))
        select_data(self.settingsp.glossary, str(s.value("glossary", "true")).lower() != "false")
        select_data(self.settingsp.intro, "off" if str(s.value("intro", "true")).lower() == "false" else "on")
        select_data(self.settingsp.update_check, str(s.value("update_check", "manual")))
        select_data(self.settingsp.voices, str(s.value("voices", "true")).lower() != "false")
        select_data(self.settingsp.scene_pass, str(s.value("scene_pass", "false")).lower() == "true")
        self._show_voices()
        self._show_style_name()

    def _save(self, *_) -> None:
        s = self.settings
        s.setValue("source", self.home.src.currentData())
        s.setValue("target", self.home.tgt.currentData())
        s.setValue("speech", self.home.speech.currentData())
        s.setValue("model", self.home.model.currentData())
        s.setValue("parallel", self.settingsp.parallel.currentData())
        s.setValue("glossary", "true" if self.settingsp.glossary.currentData() else "false")
        s.setValue("intro", "false" if self.settingsp.intro.currentData() == "off" else "true")
        s.setValue("update_check", self.settingsp.update_check.currentData())
        s.setValue("voices", "true" if self.settingsp.voices.currentData() else "false")
        s.setValue("scene_pass", "true" if self.settingsp.scene_pass.currentData() else "false")

    def _load_style(self) -> SubStyle:
        raw = self.settings.value("style")
        try:
            return SubStyle.from_dict(json.loads(str(raw))) if raw else DEFAULT
        except (ValueError, TypeError):
            return DEFAULT

    def _show_style_name(self) -> None:
        name = next((n for n, st in PRESETS.items() if st == self.sub_style), "Custom")
        self.settingsp.style_name.setText(tr(name))

    def options(self) -> Options:
        style = None if self.sub_style == DEFAULT else self.sub_style
        return Options(
            target=self.home.tgt.currentData(),
            source=self.home.src.currentData(),
            asr_model=self.home.speech.currentData(),
            llm_model=None if self.engine else self.home.model.currentData(),
            llm_url=self.cfg.server_url,
            engine=self.engine,
            parallel=self.settingsp.parallel.currentData() or 2,
            auto_glossary=bool(self.settingsp.glossary.currentData()),
            style=style,
            voices=bool(self.settingsp.voices.currentData()),
            scene_pass=bool(self.settingsp.scene_pass.currentData()),
        )

    # ---------------------------------------------------------------- translator status

    def _make_engine(self) -> None:
        """Subloc's own translator when Setup chose it; otherwise translation goes to cfg.server_url."""
        if self.engine is not None:
            self.engine.stop()
        self.engine = None
        path = self.cfg.builtin_model_path() if self.cfg.provider == "builtin" else None
        if path is not None:
            self.engine = BuiltinEngine(path, parallel=int(str(self.settings.value("parallel", 2) or 2)))
        self._show_translator_info()

    def _builtin_label(self) -> str:
        model = self.cfg.builtin_model
        return TRANSLATORS[model].label if model in TRANSLATORS else Path(model).stem

    def _show_translator_info(self) -> None:
        if self.cfg.provider == "builtin":
            self.settingsp.translator_info.setText(tr("Built-in · {m}", m=self._builtin_label()))
        else:
            self.settingsp.translator_info.setText(tr("Your server · {url}", url=self.cfg.server_url))

    def check_engine(self) -> None:
        if self.engine is not None:  # built-in: nothing to poll — ready if the model file is there
            ok = self.engine.model.exists()
            self.top.set_engine(tr("Translator ready · {model}", model=self._builtin_label()) if ok else
                                tr("Translator not installed — run Setup"), ok)  # fmt: skip
            self.home.set_models([], None, None)
            self.home.model.setItemText(0, tr("Built-in · {m}", m=self._builtin_label()))
            self.home.model.setEnabled(False)
            return
        self.home.model.setEnabled(True)
        url = self.cfg.server_url

        def work() -> None:
            try:
                models = LMStudio(url, timeout=4).list_models()
                self.bus.engine.emit({"ok": True, "models": models})
            except Exception as e:
                self.bus.engine.emit({"ok": False, "error": str(e)})

        threading.Thread(target=work, daemon=True).start()

    def _on_engine(self, st: dict) -> None:
        if not st["ok"]:
            self.top.set_engine(tr("LM Studio isn't running — start its server"), False)
            return
        models = st["models"]
        loaded = next((m for m in models if m.loaded), None)
        self.top.set_engine(
            tr("Translator ready · {model}", model=loaded.id.split("/")[-1])
            if loaded
            else tr("LM Studio is on — load a model"),
            bool(loaded),
        )
        items = [(m.id, ("● " if m.loaded else "") + m.id.split("/")[-1] + (f"  —  {m.hint}" if m.hint else ""))
                 for m in models]  # fmt: skip
        if [self.home.model.itemData(i) for i in range(1, self.home.model.count())] != [m.id for m in models]:
            self.home.set_models(items, loaded.id.split("/")[-1] if loaded else None, self.settings.value("model"))

    # ---------------------------------------------------------------- opening files

    def open_paths(self, paths: list[Path]) -> None:
        videos = find_videos(paths)
        if not videos:
            self.toast(tr("Those files aren't videos Subloc can read."), "warning")
            return
        if len(videos) == 1 and not paths[0].is_dir():
            self.open_video(videos[0])
        else:
            self.add_to_queue(videos)
            self.show_page("queue")

    def open_video(self, video: Path) -> None:
        if self.job is not None:
            self.toast(tr("Wait for the current video to finish, or stop it first."), "warning")
            return
        try:
            info = probe(video)
        except Exception as e:
            QMessageBox.warning(self, tr("Can't open this file"), str(e))
            return
        self.video, self.info = video.resolve(), info
        self._remember(self.video, info.duration)
        j = self.jobp
        j.player.pause()
        j.display.setCurrentWidget(j.preview)
        j.title.setText(video.name)
        j.meta.setText(f"{fmt_time(info.duration)} · " + (f"{info.width}×{info.height}" if info.width else "audio"))
        j.banner.hide()
        j.stages.reset()
        j.eta.setText("")

        j.source.blockSignals(True)
        j.source.clear()
        if info.has_audio:
            j.source.addItem(icons.icon("headphones", t.TEXT), tr("Listen to the speech"), None)
        for track in info.text_subtitles:
            name = track.title or (
                tr(LANGS.get(track.lang or "", track.lang or "")) or tr("Track {n}", n=track.index + 1)
            )
            j.source.addItem(icons.icon("captions", t.TEXT), tr("Built-in subtitles: {name}", name=name),
                             track.index)  # fmt: skip
        chosen = subtitle_source(info, self.home.tgt.currentData())
        if chosen is not None:  # people-made subtitles: faster, exact timing
            select_data(j.source, chosen)
        j.source.blockSignals(False)
        j.audio.clear()
        for track in info.audio:
            lang = tr(LANGS.get(track.lang or "", track.lang or "unknown language"))
            j.audio.addItem(f"{track.index + 1} · {lang}" + (f" · {track.title}" if track.title else ""), track.index)
        if info.audio:
            j.audio.setCurrentIndex(default_audio_track(info))
        self._source_changed()

        # Earlier work on this video?
        self.cues = []
        proj = self._load_project()
        target = self.home.tgt.currentData()
        if proj and proj.cues and proj.target_language == target and all(c.translation for c in proj.cues):
            self.cues = proj.cues
            self._show_cues(proj.cues)
            self._done_view(proj)
        else:
            self.jobp.lines.set_rows(_rows(proj.cues) if proj else [])
            self._update_timeline()
            j.set_state("ready")
        self.stack.setCurrentWidget(j)
        self.top.select("home")
        self.preview_at(min(info.duration * 0.1, 60.0))

    def _load_project(self) -> Project | None:
        if self.video is None:
            return None
        path = project_path(self.video)
        try:
            return Project.load(path) if path.exists() else None
        except Exception:
            return None

    def _source_changed(self, *_) -> None:
        j = self.jobp
        listening = j.source.currentData() is None
        j.audio_lbl.setVisible(listening and j.audio.count() > 1)
        j.audio.setVisible(listening and j.audio.count() > 1)
        j.source_lbl.setVisible(j.source.count() > 1)
        j.source.setVisible(j.source.count() > 1)
        j.choice_hint.setText(
            tr("Listens to the speech and writes what it hears.")
            if listening
            else tr("Uses the subtitles already inside this file — faster, with professional timing.")
        )

    # ---------------------------------------------------------------- running a job

    def start_job(self) -> None:
        if self.video is None or self.job is not None:
            return
        if not self._take_gpu(self.video.name):
            return
        self._save()
        opt = self.options()
        j = self.jobp
        if j.source.count() > 1 or j.source.currentData() is not None:
            opt.subs_track = j.source.currentData()
        if j.audio.count():
            opt.audio_track = j.audio.currentData()
        j.banner.hide()
        j.stages.reset(reading_subtitles=opt.subs_track is not None)
        j.set_state("working")
        self.cancel = threading.Event()
        self.started = time.time()
        bus, video = self.bus, self.video

        class R(Reporter):
            def log(self, msg: str) -> None:
                bus.log.emit(msg)

            def warn(self, msg: str) -> None:
                bus.warn.emit(msg)

            def stage(self, name: str, frac: float, detail: str = "") -> None:
                bus.stage.emit(name, frac, detail)

            def cues(self, cues) -> None:
                bus.cues.emit([Cue(**{**c.__dict__, "words": []}) for c in cues])

        def work() -> None:
            try:
                _, outputs = run(video, opt, R(), self.cancel)
                bus.finished.emit([str(p) for p in outputs])
            except Cancelled:
                bus.failed.emit(tr("Stopped. Progress is saved — press Start to continue where it left off."))
            except Exception as e:
                bus.failed.emit(str(e) or type(e).__name__)

        self.job = threading.Thread(target=work, daemon=True)
        self.job.start()
        self._update_awake()

    def stop_job(self) -> None:
        self.cancel.set()
        self.jobp.eta.setText(tr("Stopping…"))

    def _on_warn(self, msg: str) -> None:
        self.jobp.banner.say(msg, "warning")

    def _on_stage(self, name: str, frac: float, detail: str) -> None:
        st = self.jobp.stages
        if name == "audio":
            st.set("audio", "now", tr("Reading…"))
        elif name == "transcribe":
            st.set("audio", "done", tr("Read"))
            st.set("transcribe", "now", f"{frac:.0%}" if frac else tr("Starting…"))
        elif name == "voices":  # after listening: shown in the Listening box
            st.set("audio", "done", tr("Read"))
            st.set("transcribe", "now", tr("Voices {n}", n=f"{frac:.0%}") if frac else tr("Speakers…"))
        elif name == "listeners":  # before translating: shown in the Translating box
            for k, v in (("audio", tr("Read")), ("transcribe", tr("{n} lines", n=len(self.cues)))):
                if st.boxes[k].state != "done":
                    st.set(k, "done", v)
            if st.boxes["names"].state != "done":
                st.set("names", "done", tr("Skipped"))
            st.set("translate", "now", tr("Scenes {n}", n=f"{frac:.0%}"))
        elif name == "names":
            st.set("audio", "done", tr("Read"))
            if self.jobp.stages.boxes["transcribe"].state != "done":
                st.set("transcribe", "done", tr("{n} lines", n=len(self.cues)))
            found = detail.split(" ")[0] if detail else ""
            st.set("names", "done" if frac >= 1 else "now", tr("{n} found", n=found) if frac >= 1 else tr("Finding…"))
        elif name == "translate":
            for k, v in (("audio", tr("Read")), ("transcribe", tr("{n} lines", n=len(self.cues)))):
                if st.boxes[k].state != "done":
                    st.set(k, "done", v)
            if st.boxes["names"].state != "done":
                st.set("names", "done", tr("Skipped") if frac else "—")
            st.set("translate", "now", f"{frac:.0%}")
            if frac > 0.03:
                left = (time.time() - self.started) / frac * (1 - frac)
                self.jobp.eta.setText(tr("about {n} min left", n=max(1, round(left / 60))))

    def _on_cues(self, cues: list[Cue]) -> None:
        self.cues = cues
        self._show_cues(cues)
        done = [c for c in cues if c.translation]
        if self.job is not None and self.video:
            self.home.set_live(str(self.video), len(done) / len(cues) if cues else 0.0)
        if done and time.time() - self.last_frame_at > 2.5:  # follow the newest translated line
            self.last_frame_at = time.time()
            self._set_now(done[-1])

    def _show_cues(self, cues: list[Cue]) -> None:
        self._starts = [c.start for c in cues]
        if self.jobp.display.currentWidget() is self.jobp.player and time.time() - self._last_subs_write > 4:
            self._refresh_player_subs()
        j = self.jobp
        target = self.home.tgt.currentData()
        j.lines.rtl = target in RTL
        j.mode.set_text("translation", tr(LANGS.get(target, target)))  # Both · Original · <the language>
        j.lines.set_rows(_rows(cues))
        j.count.setText(str(len(cues)))
        self._update_timeline()

    def _update_timeline(self) -> None:
        dur = self.info.duration if self.info else 1.0
        heard = [(c.start, c.end) for c in self.cues]
        done = [(c.start, c.end) for c in self.cues if c.translation]
        n = len(self.cues)
        right = f"{len(done)} / {n}" if n else ""
        self.jobp.timeline.set_data(dur, heard, done, right)

    def _job_ended(self) -> None:
        self.job = None
        self._update_awake()
        self.home.set_live(None)
        self._show_recent()  # the project file changed: new status on its row
        if self.video:
            self._library_video_done(self.video)

    def _on_finished(self, outputs: list) -> None:
        self._job_ended()
        if self.video and not self.isActiveWindow():  # working in another window meanwhile: tell them
            self._notify(tr("Subtitles ready"), self.video.name)
        proj = self._load_project()
        if proj:
            self.cues = proj.cues
            self._show_cues(proj.cues)
            self._done_view(proj)
        took = time.time() - self.started
        self.jobp.meta.setText(tr("Done in {m} min · {n} lines", m=max(1, round(took / 60)), n=len(self.cues)))

    def _done_view(self, proj: Project) -> None:
        j = self.jobp
        j.stages.set("translate", "done", tr("Done"))
        names = []
        if self.video:
            g = Glossary.load(glossary_path(self.video), proj.target_language or "ar")
            full = " ".join(c.text for c in proj.cues)
            seen = set()
            for src, tgt in g.relevant(full).items():
                term = g.find(src)
                key = term.source if term else src
                if key not in seen:
                    seen.add(key)
                    names.append((key, tgt))
        j.set_names(names[:60])
        j.set_state("done")
        first = next((c for c in proj.cues if c.translation), None)
        self._show_player(first.start if first else 0.0)
        if proj.meta.get("audio_missing", 0) >= 0.02:
            self._on_warn(tr("This file is damaged: about {p} of the sound couldn't be read. Subtitles are missing in "
                             "those parts.", p=f"{proj.meta['audio_missing']:.0%}"))  # fmt: skip
        j.eta.setText("")

    def _on_failed(self, msg: str) -> None:
        self._job_ended()
        j = self.jobp
        j.set_state("failed")
        j.banner.say(msg, "info" if self.cancel.is_set() else "error")  # stopped by the user: not an error
        j.eta.setText("")

    # ---------------------------------------------------------------- preview

    def _line_clicked(self, cue_id: int) -> None:
        c = next((c for c in self.cues if c.id == cue_id), None)
        if not c:
            return
        if self.jobp.display.currentWidget() is self.jobp.player:
            self.jobp.lines.set_now(c.id)
            self.jobp.player.seek(c.start + 0.05)
        else:
            self._set_now(c)

    def _set_now(self, c: Cue) -> None:
        self.jobp.lines.set_now(c.id)
        self.jobp.timeline.set_playhead(c.start)
        rtl = self.home.tgt.currentData() in RTL
        self.jobp.preview.set_caption(c.translation or "", fmt_time(c.start), rtl)
        self._grab(c.start + min(0.4, c.duration / 2))

    def preview_at(self, sec: float) -> None:
        if self.jobp.display.currentWidget() is self.jobp.player:
            self.jobp.player.seek(sec)
            return
        c = next((c for c in self.cues if c.start <= sec <= c.end), None)
        if c:
            self.jobp.lines.set_now(c.id)
            self.jobp.view.scrollTo(self.jobp.lines.index(self.jobp.lines.row_of(c.id) or 0))
        self.jobp.timeline.set_playhead(sec)
        rtl = self.home.tgt.currentData() in RTL
        self.jobp.preview.set_caption(c.translation or "" if c else "", fmt_time(sec), rtl)
        self._grab(sec)

    def _grab(self, sec: float) -> None:
        if self.video is None or not (self.info and self.info.width):
            return
        self.frame_request += 1
        n, video = self.frame_request, self.video

        def work() -> None:
            with contextlib.suppress(Exception):  # a missing preview frame is not worth an error
                self.bus.frame.emit(n, grab_frame(video, sec, width=1280))

        threading.Thread(target=work, daemon=True).start()

    def _on_frame(self, n: int, data: bytes) -> None:
        if n != self.frame_request:
            return
        pix = QPixmap()
        pix.loadFromData(data)
        self.jobp.preview.set_frame(pix)

    # ---------------------------------------------------------------- review actions

    def save_line(self, cue_id: int, text: str) -> None:
        if self.video is None:
            return
        try:
            proj = update_line(self.video, cue_id, text, self.options())
        except Exception as e:
            QMessageBox.warning(self, tr("Couldn't save"), str(e))
            return
        self.cues = proj.cues
        self.jobp.view.close_editor()
        self._show_cues(proj.cues)
        if self.jobp.display.currentWidget() is self.jobp.player:
            self._refresh_player_subs()
        c = next((c for c in proj.cues if c.id == cue_id), None)
        if c:
            self._set_now(c)

    def retranslate(self, ids: list[int], listener: str | None = None) -> None:
        if self.video is None or self.job is not None:
            return
        video, opt = self.video, self.options()
        self.jobp.eta.setText(
            tr("Translating again…") if len(ids) == 1 else tr("Translating {n} lines again…", n=len(ids))
        )

        def work() -> None:
            try:
                retranslate_lines(video, ids, opt, listener=listener)
                self.bus.line_done.emit("")
            except Exception as e:
                self.bus.line_done.emit(str(e) or type(e).__name__)

        threading.Thread(target=work, daemon=True).start()

    def _on_line_done(self, err: str) -> None:
        self.jobp.eta.setText("")
        if err:
            QMessageBox.warning(self, tr("Couldn't translate"), err)
        proj = self._load_project()
        if proj:
            editing = self.jobp.view.editing_id
            self.jobp.view.close_editor()
            self.cues = proj.cues
            self._show_cues(proj.cues)
            if editing:
                self.jobp.view.open_editor(editing)

    def edit_name(self, source: str) -> None:
        if self.video is None:
            return
        target = self.home.tgt.currentData()
        path = glossary_path(self.video)
        g = Glossary.load(path, target)
        term = g.find(source)
        if term is None:
            return
        prompt = tr("How should “{name}” be written?", name=term.source)
        new, ok = QInputDialog.getText(self, tr("Change a name"), prompt, text=term.target)
        new = new.strip()
        if not ok or not new or new == term.target:
            return
        term.target, term.user = new, True  # user edits always win
        try:
            g.save(path)
        except OSError as e:
            QMessageBox.warning(self, tr("Couldn't save"), str(e))
            return
        forms = [f.lower() for f in term.forms()]
        ids = [c.id for c in self.cues if any(f in c.text.lower() for f in forms)]
        question = tr("Translate the {n} lines with this name again so they use “{name}”?", n=len(ids), name=new)
        if ids and QMessageBox.question(self, tr("Update lines"), question) == QMessageBox.StandardButton.Yes:
            self.retranslate(ids)
        proj = self._load_project()
        if proj:
            self._done_view(proj)

    def open_external(self) -> None:
        self.jobp.player.pause()
        if self.video:
            os.startfile(self.video)  # type: ignore[attr-defined]  # default player picks up Video.<lang>.srt

    # ---------------------------------------------------------------- built-in player

    def _play_subs_path(self) -> Path:
        """Subtitles for in-app playback: always .ass in the chosen look (an .srt would get mpv's own style)."""
        base = Path(QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppLocalDataLocation))
        folder = base / "playback"
        folder.mkdir(parents=True, exist_ok=True)
        return folder / "current.ass"

    def _write_play_subs(self) -> Path:
        assert self.info is not None
        path = self._play_subs_path()
        write_ass(self.cues, path, self.sub_style, True, self.home.tgt.currentData(),
                  self.info.width or 1920, self.info.height or 1080)  # fmt: skip
        self._last_subs_write = time.time()
        return path

    def _refresh_player_subs(self) -> None:
        if self.video and self.info:
            self.jobp.player.set_subtitles(self._write_play_subs())

    def _show_player(self, start: float) -> bool:
        """Switch the screen to the player, loaded with this video and its subtitles. False if no libmpv."""
        j = self.jobp
        if self.video is None or not player_available() or not (self.info and self.info.width):
            return False
        j.display.setCurrentWidget(j.player)
        if j.player.video != self.video:
            if not j.player.load(self.video, self._write_play_subs(), start):
                j.display.setCurrentWidget(j.preview)
                return False
        else:
            self._refresh_player_subs()
            j.player.seek(start)
        return True

    # ---------------------------------------------------------------- keyboard

    def _bind_shortcuts(self) -> None:
        actions: dict[str, Any] = {
            "open_video": self.home.choose_videos,
            "open_folder": self.home.choose_folder,
            "home": lambda: self.show_page("home"),
            "library": lambda: self.show_page("library"),
            "queue": lambda: self.show_page("queue"),
            "settings": lambda: self.show_page("settings"),
            "play": self._key_play,
            "start": self._key_start,
            "search": self._key_search,
            "refresh": lambda: self.refresh_library("") if self.lib.roots else None,
            "back": self._key_back,
            "help": self.show_shortcuts,
        }
        for sid, keys, _ in SHORTCUTS:
            QShortcut(QKeySequence(keys), self).activated.connect(actions[sid])

    def _key_play(self) -> None:
        j = self.jobp
        if self.stack.currentWidget() is j and (j.play_btn.isVisible() or j.display.currentWidget() is j.player):
            self.toggle_play()

    def _key_start(self) -> None:
        if self.stack.currentWidget() is self.jobp and self.jobp.start_btn.isVisible():
            self.start_job()
        elif self.stack.currentWidget() is self.queuep:
            self.start_queue()

    def _key_search(self) -> None:
        self.show_page("library")
        self.libp.search.setFocus()
        self.libp.search.selectAll()

    def _key_back(self) -> None:
        if self.stack.currentWidget() is self.jobp and self.jobp.view.editing_id is None:
            self.show_page("home")

    def show_shortcuts(self) -> None:
        ShortcutsDialog(self).exec()

    # ---------------------------------------------------------------- speakers and voices (optional models)

    def _show_voices(self) -> None:
        if voices.installed():
            self.settingsp.show_voices("ready")
        else:
            self.settingsp.show_voices("missing", tr("Download ({n} GB)", n=f"{voices.DOWNLOAD_GB:.2f}"))

    def get_voices(self) -> None:
        bus = self.bus
        self.settingsp.show_voices("downloading", tr("Downloading…"))

        def work() -> None:
            try:
                voices.install(lambda done, total: bus.voices.emit(min(done / max(total, 1), 0.999), ""))
                bus.voices.emit(1.0, "")
            except Exception as e:
                bus.voices.emit(0.0, str(e) or type(e).__name__)

        threading.Thread(target=work, daemon=True).start()

    def _on_voices(self, frac: float, err: str) -> None:
        if err:
            self._show_voices()
            self.toast(err, "warning", secs=8)
        elif frac >= 1:
            self._show_voices()
            self.toast(tr("Speakers and voices are ready. New videos get them after listening."), "ok")
        else:
            self.settingsp.show_voices("downloading", f"{frac:.0%}")

    # ---------------------------------------------------------------- updates (when asked, or daily if chosen)

    def check_updates(self, quiet: bool = False) -> None:
        """Ask GitHub for the newest release. `quiet` (the daily check): say something only if there is one."""
        bus = self.bus
        self.settings.setValue("update_last", time.time())

        def work() -> None:
            try:
                bus.update.emit(update.latest(), "", not quiet)
            except Exception as e:
                bus.update.emit(None, str(e) or type(e).__name__, not quiet)

        threading.Thread(target=work, daemon=True).start()
        if not quiet:
            self.toast(tr("Checking for updates…"), "info", secs=2)

    def _daily_update_check(self) -> None:
        if self.settingsp.update_check.currentData() != "daily":
            return
        try:
            last = float(str(self.settings.value("update_last", 0) or 0))
        except ValueError:
            last = 0.0
        if time.time() - last > 20 * 3600:
            self.check_updates(quiet=True)

    def _on_update(self, rel: update.Release | None, err: str, asked: bool) -> None:
        if err:
            if asked:
                self.toast(tr("Couldn't reach GitHub. Check the internet connection."), "warning")
            return
        mine = version()
        if rel is None or not update.is_newer(rel.version, mine):
            if asked:
                self.toast(tr("You have the latest version ({v}).", v=mine), "ok")
            return
        if update.app_dir() is None or not rel.installable:  # source tree, or no checked installer: the page
            self.toast(tr("Subloc {v} is available.", v=rel.version), "ok",
                       (tr("Download"), lambda: QDesktopServices.openUrl(QUrl(rel.page))), secs=12)  # fmt: skip
            return
        self.toast(tr("Subloc {v} is available.", v=rel.version), "ok",
                   (tr("Update now"), lambda: self.start_update(rel)), secs=15)  # fmt: skip

    def _busy_elsewhere(self) -> str:
        """What would an update interrupt? '' when nothing runs (here, on the command line, or for an agent)."""
        if self.job is not None or self.queue_job is not None:
            return tr("Subloc is still working. Let it finish or stop it, then update.")
        if not self.busy.held and (who := busy.holder()):
            return tr("Another Subloc is working ({who}). Update when it's done.", who=who)
        if update.app_dir() is not None and update.other_windows():
            return tr("Another Subloc window is open. Close it, then update.")
        return ""

    def start_update(self, rel: update.Release) -> None:
        if why := self._busy_elsewhere():
            self.toast(why, "warning", secs=8)
            return
        box = QMessageBox(self)
        box.setWindowTitle(tr("Update Subloc"))
        box.setText(tr("Download Subloc {v} ({n} MB) and install it?", v=rel.version, n=round(rel.size / 1e6)))
        box.setInformativeText(
            tr("Subloc closes, updates and opens again. Your settings, models and projects are kept.")
        )
        go = box.addButton(tr("Update now"), QMessageBox.ButtonRole.AcceptRole)
        notes = box.addButton(tr("What's new"), QMessageBox.ButtonRole.HelpRole)
        box.addButton(tr("Later"), QMessageBox.ButtonRole.RejectRole)
        box.exec()
        if box.clickedButton() is notes:
            QDesktopServices.openUrl(QUrl(rel.page))
            return
        if box.clickedButton() is not go:
            return
        bus = self.bus
        self.update_cancel = threading.Event()
        cancel = self.update_cancel
        self.settingsp.show_update(tr("Downloading…"), True)
        self.toast(tr("Downloading Subloc {v}…", v=rel.version), "info", secs=3)

        def work() -> None:
            try:
                path = update.fetch(rel, lambda d, t: bus.update_progress.emit(d / max(t, 1)), cancel)
                bus.update_ready.emit(str(path), "")
            except Exception as e:
                bus.update_ready.emit("", "stopped" if cancel.is_set() else (str(e) or type(e).__name__))

        threading.Thread(target=work, daemon=True).start()

    def _on_update_ready(self, path: str, err: str) -> None:
        self.settingsp.show_update()
        if err:
            if err != "stopped":
                QMessageBox.warning(self, tr("Couldn't update"), err)
            return
        if why := self._busy_elsewhere():  # something started while it downloaded: keep the file for later
            self.toast(why, "warning", secs=8)
            return
        try:
            update.run_installer(Path(path), reopen=True)
        except Exception as e:
            QMessageBox.warning(self, tr("Couldn't update"), str(e) or type(e).__name__)
            return
        self.toast(tr("Installing the update… Subloc opens again in a moment."), "ok", secs=3)
        QTimer.singleShot(800, self._quit_for_update)

    def _quit_for_update(self) -> None:
        """Close as usual (settings and queue saved; nothing runs, so no question), then end the process: the
        installer replaces this program's files and must find them free."""
        if self.close():
            QApplication.quit()

    def toggle_play(self) -> None:
        j = self.jobp
        if j.display.currentWidget() is not j.player:
            c = next((c for c in self.cues if c.id == j.lines.now_id), None)
            if not self._show_player(c.start if c else 0.0):
                self.open_external()  # no built-in player: use the system's
                return
            j.player.play()
            return
        j.player.toggle()

    def watch_now(self) -> None:
        done = [c for c in self.cues if c.translation]
        if self._show_player(done[0].start if done else 0.0):
            self.jobp.player.play()

    def _on_playing(self, playing: bool) -> None:
        self.jobp.play_btn.setText(tr("Pause") if playing else tr("Play with subtitles"))
        self.jobp.play_btn.setIcon(icons.icon("pause" if playing else "play", t.ACCENT_INK))

    def _on_play_pos(self, sec: float) -> None:
        j = self.jobp
        j.timeline.set_playhead(sec)
        i = bisect.bisect_right(self._starts, sec) - 1
        c = self.cues[i] if 0 <= i < len(self.cues) and sec <= self.cues[i].end + 0.5 else None
        if c and c.id != j.lines.now_id:
            j.lines.set_now(c.id)
            if j.player.is_playing() and j.view.editing_id is None:
                row = j.lines.row_of(c.id)
                if row is not None:
                    j.view.scrollTo(j.lines.index(row), QAbstractItemView.ScrollHint.PositionAtCenter)

    def _play_from(self, cue_id: int) -> None:
        c = next((c for c in self.cues if c.id == cue_id), None)
        player = shutil.which("vlc") or next((str(p) for p in VLC_PATHS if p.exists()), None)
        if c and player and self.video:
            proc.popen([player, f"--start-time={max(0.0, c.start - 1):.1f}", str(self.video)])
        else:
            self.open_external()

    def show_files(self) -> None:
        if self.video:
            srt = self.video.with_name(f"{self.video.stem}.{self.home.tgt.currentData()}.srt")
            reveal(srt if srt.exists() else self.video)

    def edit_style(self) -> None:
        c = next((c for c in self.cues if c.translation), None)
        dur = self.info.duration if self.info else 60.0
        dlg = StyleDialog(self, self.sub_style, self.video if (self.info and self.info.width) else None, dur,
                          (c.translation or "") if c else "", (c.start + 0.3) if c else dur * 0.1,
                          self.home.tgt.currentData())  # fmt: skip
        if dlg.exec() != StyleDialog.DialogCode.Accepted:
            return
        self.sub_style = dlg.chosen
        self.settings.setValue("style", json.dumps(self.sub_style.to_dict()))
        self._show_style_name()
        if self.jobp.display.currentWidget() is self.jobp.player:
            self._refresh_player_subs()
        proj = self._load_project()
        if proj and self.video and proj.cues and all(c.translation for c in proj.cues):
            write_outputs(
                self.video, proj, proj.target_language or "ar", None if self.sub_style == DEFAULT else self.sub_style
            )

    def export(self, kind: str) -> None:
        proj = self._load_project()
        if not (proj and self.video):
            return
        target = proj.target_language or "ar"
        if kind == "ass":
            paths = write_outputs(self.video, proj, target, self.sub_style)
            self._saved(paths[-1])
        elif kind == "srt_as":
            src = self.video.with_name(f"{self.video.stem}.{target}.srt")
            dest, _ = QFileDialog.getSaveFileName(self, tr("Save subtitles as"), str(src), tr("Subtitles (*.srt)"))
            if dest:
                shutil.copyfile(src, dest)
                self._saved(Path(dest))
        elif kind == "burn":
            self._burn(proj, target)

    def _burn(self, proj: Project, target: str) -> None:
        assert self.video is not None
        default = self.video.with_name(f"{self.video.stem}.{target}.subtitled.mp4")
        dest, _ = QFileDialog.getSaveFileName(self, tr("Save video with subtitles"), str(default), tr("Video (*.mp4)"))
        if not dest:
            return
        self.jobp.player.pause()
        dlg = QProgressDialog(tr("Making the video with subtitles…"), tr("Cancel"), 0, 1000, self)
        dlg.setWindowTitle(tr("Export"))
        dlg.setWindowModality(Qt.WindowModality.WindowModal)
        dlg.setMinimumDuration(0)
        dlg.setValue(0)
        cancel = threading.Event()
        dlg.canceled.connect(cancel.set)
        bus, video, cues, style = self.bus, self.video, list(proj.cues), self.sub_style

        def work() -> None:
            try:
                burn(video, cues, style, target, Path(dest), lambda f: bus.burn_progress.emit(f), cancel)
                bus.burn_done.emit(dest, "")
            except Exception as e:
                bus.burn_done.emit(dest, str(e) or type(e).__name__)

        self._burn_dialog = dlg
        threading.Thread(target=work, daemon=True).start()

    def _on_burn_progress(self, frac: float) -> None:
        if self._burn_dialog is not None:
            self._burn_dialog.setValue(int(frac * 1000))

    def _on_burn_done(self, dest: str, err: str) -> None:
        if self._burn_dialog is not None:
            self._burn_dialog.close()
            self._burn_dialog = None
        if err:
            if not err.startswith("Stopped"):
                QMessageBox.warning(self, tr("Export"), err)
            return
        self._saved(Path(dest))

    def _saved(self, path: Path) -> None:
        self.toast(tr("Saved: {name}", name=path.name), "ok", (tr("Show in folder"), lambda: reveal(path)), secs=7)

    # ---------------------------------------------------------------- shutdown

    def run_setup(self) -> None:
        if self.job is not None or self.queue_job is not None:
            self.toast(tr("Wait for the current video to finish, or stop it first."), "warning")
            return
        before = self.cfg.ui_lang
        if not run_setup_flow(self):
            return
        self.cfg = Config.load()
        if self.cfg.ui_lang != before:
            self.change_language(self.cfg.ui_lang, force=True)
            return
        self._make_engine()
        select_data(self.home.speech, self.cfg.speech_model)
        self.check_engine()

    def change_language(self, code: str, force: bool = False) -> None:
        if code == self.cfg.ui_lang and not force:
            return
        if self.job is not None or self.queue_job is not None:
            self.toast(tr("Wait for the current video to finish, or stop it first."), "warning")
            return
        self.cfg.ui_lang = code
        self.cfg.save()
        self._save()
        app = QApplication.instance()
        assert isinstance(app, QApplication)
        apply_language(app, code)
        new = MainWindow()
        new.setGeometry(self.geometry())
        new.show_page("settings")
        new.show()
        _windows.append(new)
        self._closing_for_restart = True
        self.close()
        _windows.remove(self)

    def closeEvent(self, e):
        self.lib_cancel.set()
        self.busy.release()
        if getattr(self, "_closing_for_restart", False):
            self.jobp.player.shutdown()
            if self.engine is not None:
                self.engine.stop()
            super().closeEvent(e)
            return
        running = self.job is not None or self.queue_job is not None
        if running and QMessageBox.question(
            self, tr("Quit Subloc?"), tr("Work is still running. Progress is saved — you can continue later. Quit now?")
        ) != QMessageBox.StandardButton.Yes:  # fmt: skip
            e.ignore()
            return
        self.cancel.set()
        self.queue_cancel.set()
        self._save()
        save_queue(self.queue)  # videos being worked on come back as "stopped", ready to continue
        power.keep_awake(False)
        if self.tray is not None:
            self.tray.hide()
        self.jobp.player.shutdown()
        if self.engine is not None:
            self.engine.stop()
        super().closeEvent(e)


def apply_language(app: QApplication, code: str) -> None:
    """Interface language + direction. Arabic mirrors the layout and uses the Arabic Plex face for all text."""
    set_language(code)
    app.setLayoutDirection(Qt.LayoutDirection.RightToLeft if rtl() else Qt.LayoutDirection.LeftToRight)
    t.load_fonts(arabic_first=rtl())
    app.setFont(t.font(10))
    app.setStyleSheet(t.stylesheet())


def run_setup_flow(parent) -> bool:
    """Show Setup; picking a language there re-opens it in that language. True if it was completed."""
    app = QApplication.instance()
    assert isinstance(app, QApplication)
    while True:
        wizard = SetupWizard(parent, Config.load())
        switched: list[str] = []

        def on_language(code: str, w: SetupWizard = wizard, picked: list[str] = switched) -> None:
            picked.append(code)
            w.reject()

        wizard.language_changed.connect(on_language)
        result = wizard.exec()
        if switched and switched[0] != Config.load().ui_lang:
            cfg = Config.load()
            cfg.ui_lang = switched[0]
            cfg.save()
            apply_language(app, cfg.ui_lang)
            continue
        if switched:
            continue
        return result == SetupWizard.DialogCode.Accepted


_windows: list["MainWindow"] = []  # keeps the current window alive (rebuilt when the language changes)


def main() -> None:
    if sys.platform == "win32":  # its own taskbar button and icon, not Python's
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("Subloc.Subloc")  # type: ignore[attr-defined]
    app = QApplication(sys.argv)
    app.setApplicationName("Subloc")
    app.setStyle("Fusion")
    cfg = Config.load()
    apply_language(app, cfg.ui_lang)
    app.setWindowIcon(app_icon())  # every window and the notifications; after apply_language (it needs the fonts)
    if not cfg.setup_done:
        run_setup_flow(None)
    w = MainWindow()
    _windows.append(w)
    w.show()
    if str(QSettings("Subloc", "Subloc").value("intro", "true")).lower() != "false":
        play_intro(w)  # Subloc → S → the logo, then the app (a click skips it; Settings turns it off)
    args = [Path(a) for a in sys.argv[1:] if Path(a).exists()]
    if args:
        QTimer.singleShot(0, lambda: w.open_paths(args))
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
