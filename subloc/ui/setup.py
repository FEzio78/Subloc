"""First-run setup: language → this PC → translator → install → done. Re-runnable from Settings."""

import os
import threading
from pathlib import Path

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import (
    QButtonGroup,
    QDialog,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QProgressBar,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from .. import FROZEN, cuda, hardware
from ..catalog import PRESETS, SPEECH, TRANSLATORS, Preset, recommend
from ..config import Config, models_dir
from ..download import Cancelled, download
from ..llm import LMStudio
from . import theme as t
from .i18n import UI_LANGS, tr, translate_tree
from .widgets import Banner, BrandMark, label


class _Bus(QObject):
    hw = Signal(object)
    test = Signal(bool, str)
    progress = Signal(str, float, str)  # item key, 0..1, detail
    item_done = Signal(str, str)  # item key, error ("" = ok)
    all_done = Signal()


class Card(QFrame):
    """A selectable option card (radio-like)."""

    clicked = Signal()

    def __init__(self, title: str, lines: list[str], tag: str = ""):
        super().__init__()
        self.setObjectName("optcard")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.selected = False
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 14, 16, 14)
        lay.setSpacing(4)
        head = QHBoxLayout()
        head.addWidget(label(title, "title"))
        head.addStretch()
        self.tag = label(tag, "tag")
        self.tag.setVisible(bool(tag))
        head.addWidget(self.tag)
        lay.addLayout(head)
        for ln in lines:
            w = label(ln, "muted")
            w.setWordWrap(True)
            lay.addWidget(w)
        self._style()

    def set_selected(self, on: bool) -> None:
        self.selected = on
        self._style()

    def _style(self) -> None:
        border = t.ACCENT if self.selected else t.LINE
        bg = "#1d1b14" if self.selected else t.SURFACE
        self.setStyleSheet(
            f"#optcard {{ background: {bg}; border: 1px solid {border}; border-radius: 12px; }}"
            f"#tag {{ color: {t.ACCENT_INK}; background: {t.ACCENT}; border-radius: 8px; padding: 2px 8px;"
            f" font-size: 8.5pt; font-weight: 600; }}"
        )

    def mousePressEvent(self, e):
        self.clicked.emit()


class Step(QWidget):
    """Numbered progress dots across the top of the wizard."""

    def __init__(self, n: int):
        super().__init__()
        self.n, self.i = n, 0
        self.setFixedHeight(10)

    def set(self, i: int) -> None:
        self.i = i
        self.update()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w = 28
        gap = 8
        total = self.n * w + (self.n - 1) * gap
        x = (self.width() - total) / 2
        for k in range(self.n):
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(t.ACCENT if k <= self.i else t.SURFACE_3))
            p.drawRoundedRect(int(x), 3, w, 4, 2, 2)
            x += w + gap


class SetupWizard(QDialog):
    language_changed = Signal(str)  # the app rebuilds the wizard in the new language

    def __init__(self, parent=None, cfg: Config | None = None):
        super().__init__(parent)
        self.setWindowTitle(tr("Setup"))
        self.resize(980, 700)
        self.setStyleSheet(f"QDialog {{ background: {t.BG}; }}")
        self.cfg = cfg or Config.load()
        self.bus = _Bus()
        self.hw: hardware.Hardware | None = None
        self.preset: Preset = PRESETS["balanced"]
        self.provider = self.cfg.provider if self.cfg.setup_done else "builtin"
        self.custom_model: Path | None = None
        self.cancel = threading.Event()
        self.installing = False
        self.rows_holder: QWidget | None = None

        root = QVBoxLayout(self)
        root.setContentsMargins(36, 26, 36, 26)
        root.setSpacing(18)
        self.steps = Step(5)
        root.addWidget(self.steps)
        self.stack = QStackedWidget()
        root.addWidget(self.stack, 1)
        nav = QHBoxLayout()
        self.back_btn = QPushButton(tr("Back"))
        self.back_btn.setObjectName("ghost")
        self.back_btn.clicked.connect(self.back)
        self.next_btn = QPushButton(tr("Next"))
        self.next_btn.setObjectName("primary")
        self.next_btn.setMinimumWidth(150)
        self.next_btn.clicked.connect(self.next)
        nav.addWidget(self.back_btn)
        nav.addStretch()
        nav.addWidget(self.next_btn)
        root.addLayout(nav)

        self.stack.addWidget(self._page_welcome())
        self.stack.addWidget(self._page_pc())
        self.stack.addWidget(self._page_translator())
        self.stack.addWidget(self._page_install())
        self.stack.addWidget(self._page_done())

        self.bus.hw.connect(self._on_hw)
        self.bus.test.connect(self._on_test)
        self.bus.progress.connect(self._on_progress)
        self.bus.item_done.connect(self._on_item_done)
        self.bus.all_done.connect(self._on_all_done)
        translate_tree(self)
        self._go(0)
        threading.Thread(target=lambda: self.bus.hw.emit(hardware.detect()), daemon=True).start()

    # ---------------------------------------------------------------- pages

    def _page_welcome(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.addStretch()
        mark = BrandMark(40)
        row = QHBoxLayout()
        row.addStretch()
        row.addWidget(mark)
        brand = label("Subloc", "brand")
        brand.setStyleSheet("font-size: 24pt;")  # sized to the bigger mark on this page
        row.addWidget(brand)
        row.addStretch()
        lay.addLayout(row)
        title = label("Subtitles for any video, made on your own PC.", "hero")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(title)
        sub = label(
            "This short setup picks the right models for this computer. Nothing you watch is ever uploaded.", "muted"
        )
        sub.setAlignment(Qt.AlignmentFlag.AlignCenter)
        sub.setWordWrap(True)
        lay.addWidget(sub)
        lay.addSpacing(26)
        lay.addWidget(self._center(label("Language · اللغة", "fieldLabel")))
        langs = QHBoxLayout()
        langs.addStretch()
        self.lang_group = QButtonGroup(self)
        for code, name in UI_LANGS:
            b = QPushButton(name)
            b.setObjectName("seg")
            b.setCheckable(True)
            b.setMinimumWidth(140)
            b.setChecked(code == self.cfg.ui_lang)
            b.clicked.connect(lambda _=False, c=code: self.language_changed.emit(c))
            self.lang_group.addButton(b)
            langs.addWidget(b)
        langs.addStretch()
        seg = QFrame()
        seg.setObjectName("segGroup")
        langs.setContentsMargins(3, 3, 3, 3)
        seg.setLayout(langs)
        lay.addWidget(self._center(seg))
        lay.addStretch()
        return w

    def _page_pc(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setSpacing(14)
        lay.addWidget(label("Your PC", "hero"))
        self.hw_label = label("Checking this computer…", "muted")
        lay.addWidget(self.hw_label)
        cards = QHBoxLayout()
        cards.setSpacing(12)
        self.preset_cards: dict[str, Card] = {}
        for key, p in PRESETS.items():
            sp, trm = SPEECH[p.speech], TRANSLATORS[p.translator]
            c = Card(
                tr(p.label),
                [
                    tr("Speech: Whisper {m}", m=sp.id),
                    tr("Translator: {m}", m=trm.label),
                    tr("Download: about {n} GB", n=f"{p.download_gb:.1f}"),
                    tr(p.speed),
                ],
            )
            c.clicked.connect(lambda k=key: self._pick_preset(k))
            self.preset_cards[key] = c
            cards.addWidget(c)
        lay.addLayout(cards)
        self.preset_note = label("", "faint")
        self.preset_note.setWordWrap(True)
        lay.addWidget(self.preset_note)
        lay.addStretch()
        return w

    def _page_translator(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setSpacing(14)
        lay.addWidget(label("Translator", "hero"))
        lay.addWidget(label("Which program translates the subtitles?", "muted"))
        row = QHBoxLayout()
        row.setSpacing(12)
        self.builtin_card = Card(
            tr("Built-in"),
            [
                tr("Subloc installs and runs the translator itself. No other app needed."),
                tr("Works offline after setup."),
            ],
            tr("Recommended"),
        )
        self.server_card = Card(
            tr("My own server"),
            [
                tr("LM Studio, Ollama, llama.cpp or any OpenAI-compatible address."),
                tr("For people who already run local models."),
            ],
        )
        self.builtin_card.clicked.connect(lambda: self._pick_provider("builtin"))
        self.server_card.clicked.connect(lambda: self._pick_provider("server"))
        row.addWidget(self.builtin_card)
        row.addWidget(self.server_card)
        lay.addLayout(row)

        self.builtin_extra = QWidget()
        bl = QHBoxLayout(self.builtin_extra)
        bl.setContentsMargins(0, 0, 0, 0)
        self.model_file_label = label("", "faint")
        pick = QPushButton(tr("Use a model file I already have (.gguf)…"))
        pick.setObjectName("ghost")
        pick.clicked.connect(self._pick_gguf)
        bl.addWidget(pick)
        bl.addWidget(self.model_file_label, 1)
        lay.addWidget(self.builtin_extra)

        self.server_extra = QFrame()
        self.server_extra.setObjectName("card")
        sl = QVBoxLayout(self.server_extra)
        sl.setContentsMargins(16, 14, 16, 14)
        sl.addWidget(label("Server address", "fieldLabel"))
        addr = QHBoxLayout()
        self.url = QLineEdit(self.cfg.server_url)
        test = QPushButton(tr("Test connection"))
        test.clicked.connect(self._test)
        addr.addWidget(self.url, 1)
        addr.addWidget(test)
        sl.addLayout(addr)
        self.test_result = Banner()
        sl.addWidget(self.test_result)
        lay.addWidget(self.server_extra)
        lay.addStretch()
        self._pick_provider(self.provider)
        return w

    def _page_install(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setSpacing(12)
        lay.addWidget(label("Install", "hero"))
        self.install_summary = label("", "muted")
        self.install_summary.setWordWrap(True)
        lay.addWidget(self.install_summary)
        self.rows: dict[str, tuple[QLabel, QProgressBar, QLabel]] = {}
        box = QFrame()
        box.setObjectName("card")
        self.rows_layout = QVBoxLayout(box)
        self.rows_layout.setContentsMargins(18, 14, 18, 14)
        self.rows_layout.setSpacing(12)
        lay.addWidget(box)
        self.install_error = label("", "error")
        self.install_error.setWordWrap(True)
        lay.addWidget(self.install_error)
        lay.addWidget(label("You can stop and continue later — finished parts are kept.", "faint"))
        lay.addStretch()
        return w

    def _page_done(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.addStretch()
        title = label("You're all set", "hero")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(title)
        self.done_summary = label("", "muted")
        self.done_summary.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.done_summary.setWordWrap(True)
        lay.addWidget(self.done_summary)
        lay.addWidget(self._center(label("Drop a video on Subloc to make subtitles.", "faint")))
        lay.addStretch()
        return w

    @staticmethod
    def _center(widget: QWidget) -> QWidget:
        holder = QWidget()
        row = QHBoxLayout(holder)
        row.setContentsMargins(0, 0, 0, 0)
        row.addStretch()
        row.addWidget(widget)
        row.addStretch()
        return holder

    # ---------------------------------------------------------------- navigation

    def _go(self, i: int) -> None:
        self.stack.setCurrentIndex(i)
        self.steps.set(i)
        self.back_btn.setVisible(0 < i < 4 and not self.installing)
        self.next_btn.setEnabled(True)
        self.next_btn.setText({3: tr("Install"), 4: tr("Open Subloc")}.get(i, tr("Next")))
        if i == 3:
            self._prepare_install()

    def back(self) -> None:
        if self.stack.currentIndex() > 0:
            self._go(self.stack.currentIndex() - 1)

    def next(self) -> None:
        i = self.stack.currentIndex()
        if i == 2 and self.provider == "server" and not self.url.text().strip():
            self.test_result.say(tr("Enter the server address first."), "warning")
            return
        if i == 3:
            if self.installing:
                self.cancel.set()
                return
            self._install()
            return
        if i == 4:
            self._save()
            self.accept()
            return
        self._go(i + 1)

    # ---------------------------------------------------------------- PC + presets

    def _on_hw(self, hw: hardware.Hardware) -> None:
        self.hw = hw
        free = hardware.free_disk_gb(models_dir())
        self.hw_label.setText(tr("Found: {hw} · {free} GB free disk", hw=hw.summary, free=f"{free:.0f}"))
        rec = recommend(hw)
        for key, card in self.preset_cards.items():
            card.tag.setText(tr("Recommended for this PC"))
            card.tag.setVisible(key == rec.key)
        self._pick_preset(rec.key)

    def _pick_preset(self, key: str) -> None:
        self.preset = PRESETS[key]
        for k, c in self.preset_cards.items():
            c.set_selected(k == key)
        trm = TRANSLATORS[self.preset.translator]
        if self.hw and self.hw.nvidia and self.hw.vram_gb < trm.min_vram_gb:
            self.preset_note.setText(
                tr(
                    "This translator needs about {n} GB of graphics memory; on this PC it "
                    "will run partly on the processor and be slower.",
                    n=f"{trm.min_vram_gb:.0f}",
                )
            )
        elif self.hw and not self.hw.nvidia:
            self.preset_note.setText(
                tr(
                    "No NVIDIA graphics card found: everything runs on the processor or "
                    "built-in graphics. It works, just slower."
                )
            )
        else:
            self.preset_note.setText("")

    # ---------------------------------------------------------------- translator choice

    def _pick_provider(self, which: str) -> None:
        self.provider = which
        self.builtin_card.set_selected(which == "builtin")
        self.server_card.set_selected(which == "server")
        self.builtin_extra.setVisible(which == "builtin")
        self.server_extra.setVisible(which == "server")

    def _pick_gguf(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, tr("Choose a model file"), "", "GGUF (*.gguf)")
        if path:
            self.custom_model = Path(path)
            self.model_file_label.setText(Path(path).name)

    def _test(self) -> None:
        url = self.url.text().strip()
        self.test_result.say(tr("Connecting…"), "info")

        def work() -> None:
            try:
                models = LMStudio(url, timeout=6).list_models()
                loaded = [m.id for m in models if m.loaded]
                if loaded:
                    self.bus.test.emit(True, tr("Connected. Loaded model: {m}", m=loaded[0]))
                elif models:
                    self.bus.test.emit(
                        True, tr("Connected. {n} models available — load one in your server.", n=len(models))
                    )
                else:
                    self.bus.test.emit(False, tr("Connected, but the server has no models."))
            except Exception as e:
                self.bus.test.emit(False, str(e))

        threading.Thread(target=work, daemon=True).start()

    def _on_test(self, ok: bool, msg: str) -> None:
        self.test_result.say(msg, "ok" if ok else "error")

    # ---------------------------------------------------------------- install

    def _items(self) -> list[tuple[str, str, float, bool]]:
        """(key, title, size GB, already present)"""
        sp = SPEECH[self.preset.speech]
        items = []
        if self.hw and self.hw.nvidia and FROZEN:
            # The installed app: the NVIDIA libraries come as a download, unless the PC already has them (Setup ran
            # before, or NVIDIA's CUDA Toolkit + cuDNN are installed). The source tree has them in .venv.
            present = cuda.installed() or bool(cuda.system_dirs())
            items.append(("cuda", tr("NVIDIA graphics card support (CUDA)"), cuda.DOWNLOAD_GB, present))
        items.append(("speech", tr("Speech recognition · Whisper {m}", m=sp.id), sp.size_gb, _whisper_present(sp.id)))
        if self.provider == "builtin" and self.hw and self.hw.nvidia and FROZEN:
            # The installer carries only the Vulkan/processor build of llama.cpp; NVIDIA's comes as a download.
            items.append(("llama_cuda", tr("Built-in translator · engine for NVIDIA cards"), cuda.LLAMA_CUDA_SIZE / 1e9,
                          cuda.llama_installed()))  # fmt: skip
        if self.provider == "builtin" and self.custom_model is None:
            trm = TRANSLATORS[self.preset.translator]
            path = models_dir() / "llm" / trm.file
            items.append(("translator", tr("Translator · {m}", m=trm.label), trm.size_gb, path.exists()))
        return items

    def _prepare_install(self) -> None:
        # Rebuild the list in a fresh container (simpler than emptying nested layouts).
        if self.rows_holder is not None:
            self.rows_holder.deleteLater()
        self.rows_holder = QWidget()
        rows_layout = QVBoxLayout(self.rows_holder)
        rows_layout.setContentsMargins(0, 0, 0, 0)
        rows_layout.setSpacing(12)
        self.rows_layout.addWidget(self.rows_holder)
        self.rows.clear()
        items = self._items()
        need = sum(size for _, _, size, present in items if not present)
        free = hardware.free_disk_gb(models_dir())
        self.install_summary.setText(
            tr(
                "About {n} GB to download into {path}. Free space: {free} GB.",
                n=f"{need:.1f}",
                path=str(models_dir()),
                free=f"{free:.0f}",
            )
            if need
            else tr("Everything needed is already on this PC.")
        )
        for key, title, size, present in items:
            row = QVBoxLayout()
            head = QHBoxLayout()
            head.addWidget(label(title))
            head.addStretch()
            state = label(tr("Already installed") if present else f"{size:.1f} GB", "muted")
            if present:
                state.setStyleSheet(f"color: {t.OK};")
            head.addWidget(state)
            row.addLayout(head)
            bar = QProgressBar()
            bar.setRange(0, 1000)
            bar.setValue(1000 if present else 0)
            bar.setTextVisible(False)
            bar.setFixedHeight(6)
            bar.setStyleSheet(
                f"QProgressBar {{ background: {t.SURFACE_3}; border: none; border-radius: 3px; }}"
                f"QProgressBar::chunk {{ background: {t.ACCENT}; border-radius: 3px; }}"
            )
            row.addWidget(bar)
            rows_layout.addLayout(row)
            self.rows[key] = (state, bar, label(""))
        self.install_error.setText("")
        if need and free < need + 2:
            self.install_error.setText(
                tr("Not enough free disk space. Free at least {n} GB and try again.", n=f"{need + 2 - free:.0f}")
            )
            self.next_btn.setEnabled(False)

    def _install(self) -> None:
        self.installing = True
        self.cancel = threading.Event()
        self.install_error.setText("")
        self.back_btn.setVisible(False)
        self.next_btn.setText(tr("Stop"))
        self.next_btn.setObjectName("")
        self.next_btn.setStyleSheet("")
        items = [(k, s) for k, _, s, present in self._items() if not present]
        preset, bus, cancel = self.preset, self.bus, self.cancel

        def work() -> None:
            for key, size in items:
                try:
                    if key == "llama_cuda":
                        cuda.install_llama(
                            lambda done, total: bus.progress.emit(
                                "llama_cuda", done / max(total, 1), f"{done / 1e9:.2f} / {total / 1e9:.2f} GB"
                            ),
                            cancel,
                        )
                    elif key == "cuda":
                        cuda.install(
                            lambda done, total: bus.progress.emit(
                                "cuda", done / max(total, 1), f"{done / 1e9:.1f} / {total / 1e9:.1f} GB"
                            ),
                            cancel,
                        )
                    elif key == "speech":
                        _fetch_whisper(
                            SPEECH[preset.speech].id, size, lambda f, d: bus.progress.emit("speech", f, d), cancel
                        )
                    else:
                        trm = TRANSLATORS[preset.translator]
                        download(
                            trm.url,
                            models_dir() / "llm" / trm.file,
                            trm.sha256,
                            lambda done, total: bus.progress.emit(
                                "translator", done / max(total, 1), f"{done / 1e9:.1f} / {total / 1e9:.1f} GB"
                            ),
                            cancel,
                        )
                    bus.item_done.emit(key, "")
                except Cancelled:
                    bus.item_done.emit(key, "stopped")
                    break
                except Exception as e:
                    bus.item_done.emit(key, str(e) or type(e).__name__)
                    break
            bus.all_done.emit()

        threading.Thread(target=work, daemon=True).start()

    def _on_progress(self, key: str, frac: float, detail: str) -> None:
        if key in self.rows:
            state, bar, _ = self.rows[key]
            bar.setValue(int(frac * 1000))
            state.setText(detail or f"{frac:.0%}")

    def _on_item_done(self, key: str, err: str) -> None:
        state, bar, _ = self.rows[key]
        if not err:
            bar.setValue(1000)
            state.setText(tr("Installed"))
            state.setStyleSheet(f"color: {t.OK};")
        elif err == "stopped":
            state.setText(tr("Stopped"))
        else:
            self.install_error.setText(err)

    def _on_all_done(self) -> None:
        self.installing = False
        self.next_btn.setObjectName("primary")
        self.next_btn.setStyleSheet("")
        self.next_btn.style().unpolish(self.next_btn)
        self.next_btn.style().polish(self.next_btn)
        if all(bar.value() >= 1000 for _, bar, _ in self.rows.values()):
            self._finish_summary()
            self._go(4)
        else:
            self.next_btn.setText(tr("Install"))
            self.back_btn.setVisible(True)

    def _finish_summary(self) -> None:
        if self.provider == "builtin":
            model = self.custom_model.name if self.custom_model else TRANSLATORS[self.preset.translator].label
            translator = tr("built-in translator ({m})", m=model)
        else:
            translator = tr("your server at {url}", url=self.url.text().strip())
        self.done_summary.setText(
            tr("Speech: Whisper {s} · Translation: {t}", s=SPEECH[self.preset.speech].id, t=translator)
        )

    def _save(self) -> None:
        cfg = self.cfg
        cfg.setup_done = True
        cfg.provider = self.provider
        cfg.server_url = self.url.text().strip() or cfg.server_url
        cfg.speech_model = self.preset.speech
        if self.provider == "builtin":
            cfg.builtin_model = str(self.custom_model) if self.custom_model else self.preset.translator
        cfg.save()

    def reject(self) -> None:
        if self.installing:
            self.cancel.set()
        super().reject()


# ---------------------------------------------------------------- Whisper model download (via faster-whisper)


def _whisper_dir(name: str) -> Path:
    return Path(os.environ.get("HF_HOME", str(models_dir() / "hf"))) / "hub" / f"models--Systran--faster-whisper-{name}"


def _whisper_present(name: str) -> bool:
    """In Subloc's model cache or the user's standard Hugging Face cache (other Whisper tools)."""
    from ..asr import local_model

    return local_model(name) is not None


def _folder_size(path: Path) -> int:
    return sum(f.stat().st_size for f in path.rglob("*") if f.is_file()) if path.exists() else 0


def _fetch_whisper(name: str, size_gb: float, on_progress, cancel: threading.Event) -> None:
    """faster-whisper downloads through the Hugging Face cache; progress = folder size vs expected size."""
    from faster_whisper.utils import download_model

    error: list[BaseException] = []
    done = threading.Event()

    def run() -> None:
        try:
            download_model(name)
        except BaseException as e:
            error.append(e)
        finally:
            done.set()

    threading.Thread(target=run, daemon=True).start()
    folder = _whisper_dir(name)
    total = size_gb * 1e9
    while not done.wait(0.5):
        if cancel.is_set():
            raise Cancelled()  # the background download finishes or is resumed next time
        have = _folder_size(folder)
        on_progress(min(0.99, have / total), f"{have / 1e9:.1f} / {size_gb:.1f} GB")
    if error:
        raise error[0]
