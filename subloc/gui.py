"""Subloc desktop app: drop a video → subtitles in your language."""

import os
import subprocess
import sys
import threading
import traceback
from pathlib import Path

from PySide6.QtCore import QObject, QSettings, Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QComboBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from .llm import LMStudio
from .media import default_audio_track, probe
from .pipeline import Cancelled, Options, Reporter, run
from .subtitles import RTL
from .translate import LANGS, MAX_PARALLEL, PARALLEL

VIDEO_EXT = {".mp4", ".mkv", ".avi", ".mov", ".webm", ".m4v", ".ts", ".flv", ".wmv", ".mp3", ".wav", ".m4a"}
SOURCE_LANGS = ["ko", "ja", "en", "ru", "tr", "zh", "es", "fr", "de", "it", "pt", "hi", "th", "vi", "id", "ar"]
TARGET_LANGS = ["ar", "en"]
SPEECH_MODELS = [("large-v3", "Best quality"), ("large-v3-turbo", "Faster")]
STAGES = {
    "audio": "Step 1 of 3 · Reading audio",
    "transcribe": "Step 2 of 3 · Listening",
    "translate": "Step 3 of 3 · Translating",
    "done": "Done",
}


def fmt_time(t: float) -> str:
    h, rem = divmod(int(t), 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02}:{s:02}" if h else f"{m}:{s:02}"


# ---------------------------------------------------------------- background worker


class Worker(QObject):
    log = Signal(str)
    warning = Signal(str)
    stage = Signal(str, float, str)
    cues = Signal(list)
    finished = Signal(list)
    failed = Signal(str)

    def __init__(self, video: Path, opt: Options):
        super().__init__()
        self.video, self.opt = video, opt
        self.cancel = threading.Event()

    def start(self) -> None:
        worker = self

        class QtReporter(Reporter):
            def log(self, msg: str) -> None:
                worker.log.emit(msg)

            def warn(self, msg: str) -> None:
                worker.log.emit(f"WARNING: {msg}")
                worker.warning.emit(msg)

            def stage(self, name: str, frac: float, detail: str = "") -> None:
                worker.stage.emit(name, frac, detail)

            def cues(self, cues) -> None:
                worker.cues.emit([(c.start, c.text, c.translation or "") for c in cues])

        try:
            _, outputs = run(self.video, self.opt, QtReporter(), self.cancel)
            self.finished.emit([str(p) for p in outputs])
        except Cancelled:
            self.failed.emit("Stopped. Progress is saved — press Start to continue where it left off.")
        except Exception as e:
            self.log.emit(traceback.format_exc())
            self.failed.emit(str(e) or type(e).__name__)


# ---------------------------------------------------------------- drop zone


class DropZone(QFrame):
    picked = Signal(Path)

    def __init__(self):
        super().__init__()
        self.setAcceptDrops(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMinimumHeight(130)
        self.setObjectName("drop")
        self.title = QLabel("Drop a video here")
        self.title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        f = self.title.font()
        f.setPointSize(f.pointSize() + 6)
        f.setBold(True)
        self.title.setFont(f)
        self.sub = QLabel("or click to choose a file")
        self.sub.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.sub.setWordWrap(True)
        lay = QVBoxLayout(self)
        lay.addStretch()
        lay.addWidget(self.title)
        lay.addWidget(self.sub)
        lay.addStretch()
        self._hover(False)

    def _hover(self, on: bool) -> None:
        color = "palette(highlight)" if on else "palette(mid)"
        self.setStyleSheet(f"#drop {{ border: 2px dashed {color}; border-radius: 12px; }}")

    def show_file(self, path: Path, info: str) -> None:
        self.title.setText(path.name)
        self.sub.setText(info + "   ·   click or drop to change")

    def mousePressEvent(self, e) -> None:
        exts = " ".join(f"*{x}" for x in sorted(VIDEO_EXT))
        path, _ = QFileDialog.getOpenFileName(self, "Choose a video", "", f"Video/audio ({exts});;All files (*)")
        if path:
            self.picked.emit(Path(path))

    def dragEnterEvent(self, e) -> None:
        if e.mimeData().hasUrls():
            e.acceptProposedAction()
            self._hover(True)

    def dragLeaveEvent(self, e) -> None:
        self._hover(False)

    def dropEvent(self, e) -> None:
        self._hover(False)
        for url in e.mimeData().urls():
            p = Path(url.toLocalFile())
            if p.suffix.lower() in VIDEO_EXT:
                self.picked.emit(p)
                return


# ---------------------------------------------------------------- main window


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Subloc — subtitles for any video")
        self.resize(980, 720)
        self.settings = QSettings("Subloc", "Subloc")
        self.video: Path | None = None
        self.outputs: list[str] = []
        self.job: threading.Thread | None = None  # background job
        self.worker: Worker | None = None

        root = QWidget()
        self.setCentralWidget(root)
        lay = QVBoxLayout(root)
        lay.setContentsMargins(18, 18, 18, 18)
        lay.setSpacing(12)

        self.drop = DropZone()
        self.drop.picked.connect(self.set_video)
        lay.addWidget(self.drop)

        # Options
        grid = QGridLayout()
        grid.setHorizontalSpacing(10)
        self.src = QComboBox()
        self.src.addItem("Auto-detect", None)
        self.src.addItem("Mixed (changes during video)", "mixed")
        for code in SOURCE_LANGS:
            self.src.addItem(LANGS[code], code)
        self.tgt = QComboBox()
        for code in TARGET_LANGS:
            self.tgt.addItem(LANGS[code], code)
        self.speech = QComboBox()
        for mid, label in SPEECH_MODELS:
            self.speech.addItem(f"{label}  ({mid})", mid)
        self.model = QComboBox()
        self.model.setMinimumWidth(380)
        refresh = QToolButton()
        refresh.setText("⟳")
        refresh.setToolTip("Refresh the model list from LM Studio")
        refresh.clicked.connect(self.load_models)
        self.parallel = QComboBox()
        for n in range(1, MAX_PARALLEL + 1):
            self.parallel.addItem(f"{n} at once", n)
        self.parallel.setCurrentIndex(PARALLEL - 1)
        self.parallel.setToolTip(
            "How many translation requests LM Studio works on at the same time.\n"
            "2 is safe for most PCs. Higher can be faster if your GPU has free memory,\n"
            "but slower if the model no longer fits."
        )
        model_row = QHBoxLayout()
        model_row.addWidget(self.model, 1)
        model_row.addWidget(refresh)
        model_row.addWidget(self.parallel)

        grid.addWidget(QLabel("Spoken language"), 0, 0)
        grid.addWidget(self.src, 1, 0)
        grid.addWidget(QLabel("Subtitles in"), 0, 1)
        grid.addWidget(self.tgt, 1, 1)
        grid.addWidget(QLabel("Speech recognition"), 0, 2)
        grid.addWidget(self.speech, 1, 2)
        grid.addWidget(QLabel("Translator (LM Studio)"), 0, 3)
        grid.addLayout(model_row, 1, 3)
        grid.setColumnStretch(3, 1)

        # Per-file choices, only shown when the file offers them
        self.source_lbl = QLabel("Make subtitles from")
        self.source = QComboBox()
        self.source.currentIndexChanged.connect(self.on_source_changed)
        self.audio_lbl = QLabel("Audio track")
        self.audio = QComboBox()
        self.source_hint = QLabel("")
        self.source_hint.setStyleSheet("color: palette(placeholder-text);")
        self.source_hint.setWordWrap(True)
        grid.addWidget(self.source_lbl, 2, 0, 1, 2)
        grid.addWidget(self.source, 3, 0, 1, 2)
        grid.addWidget(self.audio_lbl, 2, 2)
        grid.addWidget(self.audio, 3, 2)
        grid.addWidget(self.source_hint, 3, 3)
        for w in (self.source_lbl, self.source, self.audio_lbl, self.audio, self.source_hint):
            w.setVisible(False)
        lay.addLayout(grid)

        # Start / stop + progress
        row = QHBoxLayout()
        self.start_btn = QPushButton("Start")
        self.start_btn.setMinimumHeight(40)
        self.start_btn.setMinimumWidth(140)
        f = self.start_btn.font()
        f.setPointSize(f.pointSize() + 2)
        f.setBold(True)
        self.start_btn.setFont(f)
        self.start_btn.setEnabled(False)
        self.start_btn.clicked.connect(self.start)
        self.stop_btn = QPushButton("Stop")
        self.stop_btn.setMinimumHeight(40)
        self.stop_btn.setEnabled(False)
        self.stop_btn.clicked.connect(self.stop)
        prog_col = QVBoxLayout()
        self.stage_lbl = QLabel("Choose a video to begin.")
        self.bar = QProgressBar()
        self.bar.setRange(0, 1000)
        self.bar.setTextVisible(False)
        self.detail = QLabel("")
        self.detail.setStyleSheet("color: palette(placeholder-text);")
        prog_col.addWidget(self.stage_lbl)
        prog_col.addWidget(self.bar)
        prog_col.addWidget(self.detail)
        self.warn_lbl = QLabel("")
        self.warn_lbl.setWordWrap(True)
        self.warn_lbl.setStyleSheet("color: #e8a33d;")
        self.warn_lbl.setVisible(False)
        prog_col.addWidget(self.warn_lbl)
        row.addWidget(self.start_btn)
        row.addWidget(self.stop_btn)
        row.addSpacing(8)
        row.addLayout(prog_col, 1)
        lay.addLayout(row)

        # Lines table
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["Time", "Original", "Translation"])
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setWordWrap(True)
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        hh.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        hh.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        lay.addWidget(self.table, 1)

        # Done actions + details
        bottom = QHBoxLayout()
        self.play_btn = QPushButton("▶  Play video")
        self.play_btn.clicked.connect(self.play)
        self.folder_btn = QPushButton("📂  Show subtitle files")
        self.folder_btn.clicked.connect(self.show_files)
        for b in (self.play_btn, self.folder_btn):
            b.setMinimumHeight(34)
            b.setVisible(False)
        self.details_btn = QToolButton()
        self.details_btn.setText("Details")
        self.details_btn.setCheckable(True)
        bottom.addWidget(self.play_btn)
        bottom.addWidget(self.folder_btn)
        bottom.addStretch()
        bottom.addWidget(self.details_btn)
        lay.addLayout(bottom)

        self.log_box = QPlainTextEdit()
        self.log_box.setReadOnly(True)
        self.log_box.setMaximumHeight(160)
        self.log_box.setFont(QFont("Consolas", 9))
        self.log_box.setVisible(False)
        self.details_btn.toggled.connect(self.log_box.setVisible)
        lay.addWidget(self.log_box)

        self.restore_settings()
        self.load_models()

    # ---------- settings

    def restore_settings(self) -> None:
        for combo, key in (
            (self.tgt, "target"),
            (self.speech, "speech"),
            (self.src, "source"),
            (self.parallel, "parallel"),
        ):
            val = self.settings.value(key)
            i = combo.findData(val) if val is not None else -1
            if i < 0 and isinstance(val, str) and val.isdigit():
                i = combo.findData(int(val))  # the registry may hand numbers back as text
            if i >= 0:
                combo.setCurrentIndex(i)

    def save_settings(self) -> None:
        self.settings.setValue("target", self.tgt.currentData())
        self.settings.setValue("speech", self.speech.currentData())
        self.settings.setValue("source", self.src.currentData())
        self.settings.setValue("model", self.model.currentData())
        self.settings.setValue("parallel", self.parallel.currentData())

    # ---------- models

    def load_models(self) -> None:
        self.model.clear()
        try:
            models = LMStudio(timeout=5).list_models()
        except Exception:
            self.model.addItem("LM Studio is not running — start its server, then press ⟳", None)
            return
        loaded = next((m for m in models if m.loaded), None)
        self.model.addItem(
            f"Use the loaded model ({loaded.id})" if loaded else "Use the loaded model (none loaded yet)", None
        )
        for m in models:
            label = ("● " if m.loaded else "    ") + m.id + (f"  —  {m.hint}" if m.hint else "")
            self.model.addItem(label, m.id)
        saved = self.settings.value("model")
        i = self.model.findData(saved) if saved else -1
        self.model.setCurrentIndex(max(i, 0))

    # ---------- flow

    def set_video(self, path: Path) -> None:
        if self.job:
            return
        try:
            info = probe(path)
        except Exception:
            QMessageBox.warning(self, "Can't open file", f"This file couldn't be read:\n{path}")
            return
        if not info.has_audio and not info.text_subtitles:
            QMessageBox.warning(self, "No audio", "This file has no audio track to transcribe.")
            return
        self.video = path
        extra = f"   ·   {info.width}×{info.height}" if info.width else ""
        self.drop.show_file(path, f"{fmt_time(info.duration)}{extra}")

        # Built-in subtitles → offer translating them (default: faster and usually more accurate)
        self.source.blockSignals(True)
        self.source.clear()
        if info.has_audio:
            self.source.addItem("🎧  Listen to the audio", None)
        for t in info.text_subtitles:
            name = t.title or (LANGS.get(t.lang, t.lang) if t.lang else f"Track {t.index + 1}")
            self.source.addItem(f"📄  Translate built-in subtitles: {name}", t.index)
        if info.text_subtitles:
            self.source.setCurrentIndex(1 if info.has_audio else 0)
        self.source.blockSignals(False)
        has_subs = bool(info.text_subtitles)
        self.source_lbl.setVisible(has_subs)
        self.source.setVisible(has_subs)

        # Several audio tracks → let the user pick (default: original language)
        self.audio.clear()
        for t in info.audio:
            lang = LANGS.get(t.lang, t.lang) if t.lang else "unknown language"
            self.audio.addItem(f"{t.index + 1} · {lang}" + (f" · {t.title}" if t.title else ""), t.index)
        if info.audio:
            self.audio.setCurrentIndex(default_audio_track(info))
        self.on_source_changed()
        self.start_btn.setEnabled(True)
        self.stage_lbl.setText("Ready. Press Start.")
        self.bar.setValue(0)
        self.detail.setText("")
        self.table.setRowCount(0)
        self.play_btn.setVisible(False)
        self.folder_btn.setVisible(False)

    def on_source_changed(self, *_) -> None:
        listening = self.source.currentData() is None
        self.src.setEnabled(listening)
        self.speech.setEnabled(listening)
        self.audio_lbl.setVisible(listening and self.audio.count() > 1)
        self.audio.setVisible(listening and self.audio.count() > 1)
        self.source_hint.setVisible(self.source.count() > 1)
        self.source_hint.setText(
            "Listens to the speech and writes what it hears."
            if listening
            else "Uses the subtitles already inside this file — faster, with professional timing."
        )

    def start(self) -> None:
        if not self.video:
            return
        self.save_settings()
        subs = self.source.currentData() if self.source.count() else None
        opt = Options(
            target=self.tgt.currentData(),
            source=self.src.currentData(),
            asr_model=self.speech.currentData(),
            llm_model=self.model.currentData(),
            audio_track=self.audio.currentData() if self.audio.count() else None,
            subs_track=subs,
            parallel=self.parallel.currentData(),
        )
        self.log_box.clear()
        self.warn_lbl.setVisible(False)
        self.outputs = []
        self.play_btn.setVisible(False)
        self.folder_btn.setVisible(False)
        self.start_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.drop.setEnabled(False)

        # Worker lives in the GUI thread; its signals are emitted from a plain Python thread,
        # so Qt queues them to the GUI thread. (A QThread + moveToThread crashed on cleanup.)
        self.worker = Worker(self.video, opt)
        self.worker.log.connect(self.log_box.appendPlainText)
        self.worker.stage.connect(self.on_stage)
        self.worker.warning.connect(self.on_warning)
        self.worker.cues.connect(self.on_cues)
        self.worker.finished.connect(self.on_finished)
        self.worker.failed.connect(self.on_failed)
        self.job = threading.Thread(target=self.worker.start, daemon=True)
        self.job.start()

    def stop(self) -> None:
        if self.worker:
            self.worker.cancel.set()
            self.stop_btn.setEnabled(False)
            self.stage_lbl.setText("Stopping…")

    def _end(self) -> None:
        self.job = self.worker = None
        self.start_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.drop.setEnabled(True)

    def on_warning(self, msg: str) -> None:
        self.warn_lbl.setText("⚠  " + msg)
        self.warn_lbl.setVisible(True)

    def on_stage(self, name: str, frac: float, detail: str) -> None:
        self.stage_lbl.setText(STAGES.get(name, name))
        self.bar.setValue(int(frac * 1000))
        self.detail.setText(detail[:120])

    def on_cues(self, rows: list) -> None:
        rtl = self.tgt.currentData() in RTL
        follow = self.table.rowCount() < len(rows)  # lines are still arriving: keep the newest visible
        self.table.setRowCount(len(rows))
        for r, (start, text, tr) in enumerate(rows):
            for col, val in enumerate((fmt_time(start), text, tr)):
                item = self.table.item(r, col)
                if item is None:
                    item = QTableWidgetItem()
                    if col == 2 and rtl:
                        item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                    self.table.setItem(r, col, item)
                if item.text() != val:
                    item.setText(val)
        if follow and self.job is not None:
            self.table.scrollToBottom()

    def on_finished(self, outputs: list) -> None:
        self.outputs = outputs
        self._end()
        self.stage_lbl.setText("Done — subtitles saved next to the video.")
        self.bar.setValue(1000)
        self.detail.setText("   ".join(Path(p).name for p in outputs))
        self.play_btn.setVisible(True)
        self.folder_btn.setVisible(True)

    def on_failed(self, msg: str) -> None:
        self._end()
        self.stage_lbl.setText(msg if msg.startswith("Stopped") else "Something went wrong")
        if not msg.startswith("Stopped"):
            self.detail.setText(msg[:200])
            self.details_btn.setChecked(True)

    def play(self) -> None:
        if self.video:
            os.startfile(self.video)  # default player; VLC/MPV pick up Video.<lang>.srt automatically

    def show_files(self) -> None:
        target = self.outputs[-1] if self.outputs else str(self.video)
        subprocess.Popen(["explorer", "/select,", os.path.normpath(target)])

    def closeEvent(self, e) -> None:
        if self.worker:
            self.worker.cancel.set()
        if self.job:
            self.job.join(5)
        self.save_settings()
        super().closeEvent(e)


def main() -> None:
    app = QApplication(sys.argv)
    app.setApplicationName("Subloc")
    w = MainWindow()
    w.show()
    if len(sys.argv) > 1 and Path(sys.argv[1]).exists():
        w.set_video(Path(sys.argv[1]))
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
