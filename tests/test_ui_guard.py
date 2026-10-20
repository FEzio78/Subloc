"""Guard against a bug made four times while building the UI: storing an attribute whose name hides a Qt
method (self.style, self.size, self.thread, self.screen…). Qt calls those methods internally, so
shadowing them breaks things in odd ways. Scans the UI source; needs no display."""

import ast
from pathlib import Path

from PySide6.QtWidgets import QDialog, QMainWindow, QWidget

UI = Path(__file__).resolve().parent.parent / "subloc" / "ui"
QT_NAMES = {n for cls in (QWidget, QMainWindow, QDialog) for n in dir(cls) if callable(getattr(cls, n, None))}


def test_no_attribute_hides_a_qt_method():
    offenders = []
    for path in UI.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target] if isinstance(
                node, ast.AnnAssign) else []  # fmt: skip
            for t in targets:
                if (isinstance(t, ast.Attribute) and isinstance(t.value, ast.Name) and t.value.id == "self"
                        and t.attr in QT_NAMES):  # fmt: skip
                    offenders.append(f"{path.name}:{node.lineno} self.{t.attr}")
    assert not offenders, "attributes that hide Qt methods: " + ", ".join(offenders)


def test_no_invisible_direction_characters_in_source():
    """Bidi marks must be written as escapes (\u200f), never as raw invisible characters: an invisible
    character in code can't be seen in review and has slipped in several times through tooling."""
    invisible = {
        chr(c) for c in (0x200E, 0x200F, 0x202A, 0x202B, 0x202C, 0x202D, 0x202E, 0x2066, 0x2067, 0x2068, 0x2069)
    }
    root = Path(__file__).resolve().parent.parent
    bad = [str(f.relative_to(root)) for d in ("subloc", "tests", "tools") for f in (root / d).rglob("*.py")
           if invisible & set(f.read_text(encoding="utf-8"))]  # fmt: skip
    assert not bad, f"raw direction marks in: {bad}"
