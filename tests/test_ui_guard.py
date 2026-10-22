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


SPAWNERS = {
    "subprocess": {"run", "Popen", "call", "check_call", "check_output", "getoutput", "getstatusoutput"},
    "asyncio": {"create_subprocess_exec", "create_subprocess_shell"},
    "os": {"system", "popen"},  # plus every os.spawn*, os.posix_spawn*, os.exec* (see _spawns)
}


def _spawns(module: str, func: str) -> bool:
    return func in SPAWNERS.get(module, ()) or (module == "os" and func.startswith(("spawn", "posix_spawn", "exec")))


def test_every_process_starts_without_a_console_window():
    """The app runs under pythonw (no console), so on Windows every console program it starts directly gets a
    black window that flashes up and closes, many times per video. All starts must go through subloc/proc.py,
    which hides them. (os.startfile is fine: it opens a file in its default app.)"""
    pkg = Path(__file__).resolve().parent.parent / "subloc"
    skip = {pkg / "proc.py"}  # the helper itself
    offenders = []
    for path in sorted(set(pkg.rglob("*.py")) - skip):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            names: list[str] = []
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                    and isinstance(node.func.value, ast.Name)):  # fmt: skip
                names = [f"{node.func.value.id}.{node.func.attr}"]
            elif isinstance(node, ast.ImportFrom) and node.module in SPAWNERS:
                names = [f"{node.module}.{a.name}" for a in node.names]
            offenders += [f"{path.relative_to(pkg.parent)}:{node.lineno} {n}" for n in names
                          if _spawns(*n.split(".", 1))]  # fmt: skip
    assert not offenders, "start these through subloc.proc.run / popen: " + ", ".join(offenders)


def test_proc_helpers_hide_the_window(monkeypatch):
    import subprocess
    import sys

    from subloc import proc

    seen = []
    monkeypatch.setattr(subprocess, "run", lambda cmd, **kw: seen.append(kw))
    monkeypatch.setattr(subprocess, "Popen", lambda cmd, **kw: seen.append(kw))
    proc.run(["ffprobe"], capture_output=True)
    proc.popen(["ffmpeg"], cwd=".")
    assert [kw["creationflags"] for kw in seen] == [proc.NO_WINDOW] * 2
    assert seen[0]["capture_output"] and seen[1]["cwd"] == "."
    if sys.platform == "win32":
        assert proc.NO_WINDOW == subprocess.CREATE_NO_WINDOW != 0
