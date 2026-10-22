"""Keyboard shortcuts: one list, used to create them (MainWindow) and to show them (F1, Settings)."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QGridLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from . import theme as t
from .i18n import tr
from .widgets import label

# (id, keys, what it does). Keys are Qt key sequences; Space and Return mean the keys themselves.
SHORTCUTS: list[tuple[str, str, str]] = [
    ("open_video", "Ctrl+O", "Open a video"),
    ("open_folder", "Ctrl+Shift+O", "Open a folder"),
    ("home", "Ctrl+1", "Home"),
    ("library", "Ctrl+2", "Library"),
    ("queue", "Ctrl+3", "Queue"),
    ("settings", "Ctrl+4", "Settings"),
    ("play", "Space", "Play or pause (on a video)"),
    ("start", "Ctrl+Return", "Start the video or the queue"),
    ("search", "Ctrl+F", "Search the library"),
    ("refresh", "F5", "Read the library folders again"),
    ("back", "Esc", "Back to Home (from a video)"),
    ("help", "F1", "Keyboard shortcuts"),
]


def _keycap(text: str) -> QLabel:
    k = QLabel(text)
    k.setAlignment(Qt.AlignmentFlag.AlignCenter)
    k.setStyleSheet(f"background: {t.SURFACE_2}; border: 1px solid {t.LINE}; border-bottom: 2px solid #3a3f46;"
                    f" border-radius: 6px; padding: 3px 8px; font-family: '{t.MONO}'; font-size: 9pt;")  # fmt: skip
    return k


class ShortcutsDialog(QDialog):
    def __init__(self, parent: QWidget | None):
        super().__init__(parent)
        self.setWindowTitle(tr("Keyboard shortcuts"))
        self.setObjectName("page")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 20, 24, 18)
        lay.setSpacing(14)
        lay.addWidget(label(tr("Keyboard shortcuts"), "title"))
        grid = QGridLayout()
        grid.setHorizontalSpacing(18)
        grid.setVerticalSpacing(8)
        for row, (_, keys, what) in enumerate(SHORTCUTS):
            caps = QWidget()
            cl = QGridLayout(caps)
            cl.setContentsMargins(0, 0, 0, 0)
            cl.setHorizontalSpacing(4)
            for i, part in enumerate(keys.replace("Return", "Enter").split("+")):
                cl.addWidget(_keycap(tr(part) if part in ("Space", "Enter", "Esc") else part), 0, i)
            # Key combinations read left to right in every language.
            caps.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
            grid.addWidget(caps, row, 0, Qt.AlignmentFlag.AlignLeading)
            grid.addWidget(label(tr(what)), row, 1)
        grid.setColumnStretch(1, 1)
        lay.addLayout(grid)
        close = QPushButton(tr("Close"))
        close.clicked.connect(self.accept)
        lay.addWidget(close, 0, Qt.AlignmentFlag.AlignTrailing)
