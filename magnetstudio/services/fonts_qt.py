"""Qt side of fonts: register the app fonts with Qt (for previews) and download them off-thread."""
from __future__ import annotations

from PyQt6.QtCore import QThread, pyqtSignal
from PyQt6.QtGui import QFontDatabase, QGuiApplication

from magnetstudio.core import fonts


def register_qt_fonts() -> list[str]:
    """Register every app font with Qt (idempotent). Needs a QGuiApplication."""
    if QGuiApplication.instance() is None:
        return []
    added: list[str] = []
    for path in fonts.custom_font_paths():
        if fonts.is_qt_registered(path):
            continue
        fid = QFontDatabase.addApplicationFont(path)
        fams = list(QFontDatabase.applicationFontFamilies(fid)) if fid >= 0 else []
        fonts.note_qt_families(path, fams)
        added += fams
    return sorted(set(added))


def add_font_file(src) -> str:
    """core.fonts.add_font_file + make it usable in Qt previews right away."""
    family = fonts.add_font_file(src)
    register_qt_fonts()
    return family


class FontDownloadWorker(QThread):
    """Runs ensure_default_fonts() off the GUI thread; register Qt fonts on `done`."""
    done = pyqtSignal(list)

    def run(self) -> None:
        self.done.emit(fonts.ensure_default_fonts())
