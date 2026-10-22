"""Visual identity: colour tokens, fonts and the application stylesheet (from design/mockup.html)."""

from pathlib import Path

from PySide6.QtGui import QColor, QFont, QFontDatabase

FONTS_DIR = Path(__file__).resolve().parent.parent / "assets" / "fonts"

# Colour tokens — dark, cinema-like, with subtitle yellow as the single accent.
BG = "#0d0e10"
SURFACE = "#15171a"
SURFACE_2 = "#1c1f23"
SURFACE_3 = "#24282d"
LINE = "#2b2f35"
TEXT = "#eceef0"
MUTED = "#8a9098"
FAINT = "#5b6169"
ACCENT = "#f5c542"  # subtitle yellow
ACCENT_INK = "#1b1500"
OK = "#5cc489"
WARN = "#e8a33d"
ERR = "#e5616a"

SANS = "Segoe UI Variable Text"
ARABIC = "Segoe UI"
MONO = "Cascadia Mono"
SERIF = "Georgia"  # the logo and the name "Subloc"; IBM Plex Serif when bundled


def qcolor(hex_rgb: str, alpha: float = 1.0) -> QColor:
    c = QColor(hex_rgb)
    c.setAlphaF(alpha)
    return c


def load_fonts(arabic_first: bool = False) -> None:
    """Use bundled IBM Plex (Latin + Arabic + Mono share one design) when present; otherwise fall back to
    Windows' Segoe UI / Cascadia Mono, which also cover Arabic."""
    global SANS, ARABIC, MONO, SERIF
    if FONTS_DIR.is_dir():
        for f in FONTS_DIR.glob("*.[ot]tf"):
            QFontDatabase.addApplicationFont(str(f))
    families = set(QFontDatabase.families())
    if "IBM Plex Sans" in families:
        SANS = "IBM Plex Sans"
    if "IBM Plex Sans Arabic" in families:
        ARABIC = "IBM Plex Sans Arabic"
    if "IBM Plex Mono" in families:
        MONO = "IBM Plex Mono"
    if "IBM Plex Serif" in families:
        SERIF = "IBM Plex Serif"
    if arabic_first:  # Plex Sans Arabic also contains Latin, designed to match
        SANS = ARABIC


def font(size: float = 10, weight: QFont.Weight = QFont.Weight.Normal, family: str | None = None) -> QFont:
    f = QFont(family or SANS)
    f.setPointSizeF(size)
    f.setWeight(weight)
    f.setHintingPreference(QFont.HintingPreference.PreferNoHinting)
    return f


def stylesheet() -> str:
    from .i18n import rtl

    CHEVRON = (FONTS_DIR.parent / "chevron.svg").as_posix()
    CLOSED = (FONTS_DIR.parent / ("chevron-left.svg" if rtl() else "chevron-right.svg")).as_posix()
    return f"""
    QWidget {{ color: {TEXT}; font-family: "{SANS}"; font-size: 10pt; }}
    QMainWindow, #page {{ background: {BG}; }}
    QToolTip {{ background: {SURFACE_3}; color: {TEXT}; border: 1px solid {LINE}; padding: 6px 8px; }}

    #topbar {{ background: {SURFACE}; border-bottom: 1px solid {LINE}; }}
    #brand {{ font-family: "{SERIF}"; font-size: 15pt; font-weight: 400; color: {ACCENT}; }}
    QPushButton#nav {{ background: transparent; border: none; color: {MUTED}; padding: 6px 12px;
                       border-radius: 7px; font-weight: 500; }}
    QPushButton#nav:hover {{ color: {TEXT}; }}
    QPushButton#nav:checked {{ color: {TEXT}; background: {SURFACE_3}; }}
    #engine {{ color: {MUTED}; font-size: 9pt; }}

    #card {{ background: {SURFACE}; border: 1px solid {LINE}; border-radius: 12px; }}
    #muted {{ color: {MUTED}; }}
    #faint {{ color: {FAINT}; }}
    #fieldLabel {{ color: {MUTED}; font-size: 8.5pt; }}
    #title {{ font-size: 13pt; font-weight: 600; }}
    #hero {{ font-size: 19pt; font-weight: 600; }}
    #dropTitle {{ color: {ACCENT}; font-size: 14pt; font-weight: 600; }}
    #mono {{ font-family: "{MONO}"; color: {MUTED}; font-size: 9pt; }}
    #warning {{ color: {WARN}; }}
    #error {{ color: {ERR}; }}

    QComboBox {{ background: transparent; border: none; padding: 2px 0; font-weight: 500; }}
    QComboBox::drop-down {{ border: none; width: 18px; }}
    QComboBox::down-arrow {{ image: url({CHEVRON}); width: 10px; height: 10px; }}
    QPushButton::menu-indicator {{ image: url({CHEVRON}); subcontrol-position: right center;
                                   subcontrol-origin: padding; right: 8px; }}
    QPushButton[menu="true"] {{ padding-right: 26px; }}
    QComboBox QAbstractItemView {{ background: {SURFACE_2}; border: 1px solid {LINE}; selection-background-color:
                                  {SURFACE_3}; outline: none; padding: 4px; }}
    QComboBox#boxed {{ background: {SURFACE_2}; border: 1px solid {LINE}; border-radius: 7px; padding: 5px 8px; }}

    QPushButton {{ background: {SURFACE_2}; border: 1px solid {LINE}; border-radius: 8px; padding: 8px 14px;
                   font-weight: 500; }}
    QPushButton:hover {{ background: {SURFACE_3}; }}
    QPushButton:disabled {{ color: {FAINT}; }}
    QPushButton#primary {{ background: {ACCENT}; color: {ACCENT_INK}; border-color: {ACCENT}; font-weight: 600; }}
    QPushButton#primary:hover {{ background: #ffd25a; }}
    QPushButton#primary:disabled {{ background: {SURFACE_3}; color: {FAINT}; border-color: {LINE}; }}
    QPushButton#ghost {{ background: transparent; }}
    QPushButton#chip {{ padding: 3px 9px; border-radius: 6px; font-size: 9pt; color: {MUTED};
                        background: {SURFACE}; }}
    QPushButton#chip:hover {{ color: {TEXT}; }}
    QPushButton#chipAccent {{ padding: 3px 9px; border-radius: 6px; font-size: 9pt; color: {ACCENT};
                              background: {SURFACE}; border-color: #6b5a26; }}
    QPushButton#seg {{ background: transparent; border: none; border-radius: 5px; padding: 3px 10px;
                       color: {MUTED}; font-size: 9pt; }}
    QPushButton#seg:checked {{ background: {SURFACE_3}; color: {TEXT}; }}
    #segGroup {{ background: {SURFACE_2}; border: 1px solid {LINE}; border-radius: 7px; }}

    QLineEdit, QPlainTextEdit, QSpinBox, QDoubleSpinBox {{ background: {BG}; border: 1px solid {LINE};
        border-radius: 7px; padding: 6px 8px; selection-background-color: #6b5a26; }}
    QLineEdit:focus, QPlainTextEdit:focus {{ border-color: #8a7330; }}

    QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
    QScrollBar::handle:vertical {{ background: {SURFACE_3}; border-radius: 4px; min-height: 30px; }}
    QScrollBar::handle:vertical:hover {{ background: #343a41; }}
    QScrollBar::add-line, QScrollBar::sub-line, QScrollBar::add-page, QScrollBar::sub-page {{
        background: none; height: 0; }}
    QListView {{ background: transparent; border: none; outline: none; }}

    QTreeWidget#library {{ background: {SURFACE}; border: 1px solid {LINE}; border-radius: 12px; padding: 4px;
                           outline: none; }}
    QTreeWidget#library::item {{ padding: 5px 2px; border: none; }}
    QTreeWidget#library::item:hover {{ background: {SURFACE_2}; }}
    QTreeWidget#library::item:selected {{ background: {SURFACE_3}; color: {TEXT}; }}
    QTreeWidget#library::branch {{ background: transparent; }}
    QTreeWidget#library::branch:has-children:closed {{ image: url({CLOSED}); }}
    QTreeWidget#library::branch:has-children:open {{ image: url({CHEVRON}); }}
    QHeaderView::section {{ background: {SURFACE}; color: {MUTED}; border: none; border-bottom: 1px solid {LINE};
                            padding: 6px 8px; font-size: 9pt; }}
    QCheckBox#watch {{ spacing: 8px; color: {MUTED}; }}

    #toast {{ background: {SURFACE_3}; border: 1px solid #3a3f46; border-radius: 10px; }}
    QPushButton#toastAction {{ background: transparent; border: none; color: {ACCENT}; font-weight: 600;
                              padding: 4px 8px; }}
    QPushButton#toastAction:hover {{ background: #343a41; }}
    QPushButton#toastClose {{ background: transparent; border: none; padding: 4px; border-radius: 6px; }}
    QPushButton#toastClose:hover {{ background: #343a41; }}

    QSlider::groove:horizontal {{ height: 4px; background: {SURFACE_3}; border-radius: 2px; }}
    QSlider::sub-page:horizontal {{ background: {ACCENT}; border-radius: 2px; }}
    QSlider::handle:horizontal {{ background: {TEXT}; width: 14px; height: 14px; margin: -5px 0; border-radius: 7px; }}
    QCheckBox::indicator {{ width: 16px; height: 16px; border-radius: 4px; border: 1px solid {LINE};
                            background: {BG}; }}
    QCheckBox::indicator:checked {{ background: {ACCENT}; border-color: {ACCENT}; }}
    """
