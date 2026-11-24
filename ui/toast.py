"""Small non-blocking toast message shown at the bottom of a window."""
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import QLabel, QWidget

_STYLES = {
    "info": "background:#323232; color:white;",
    "success": "background:#2e7d32; color:white;",
    "error": "background:#c62828; color:white;",
}


class Toast(QLabel):
    def __init__(self, parent: QWidget):
        super().__init__(parent)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setWordWrap(True)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self._timer = QTimer(self, singleShot=True, timeout=self.hide)
        self.hide()

    def show_message(self, text: str, kind: str = "info", ms: int = 4000) -> None:
        self.setText(text)
        self.setStyleSheet(_STYLES.get(kind, _STYLES["info"]) +
                           "padding:10px 18px; border-radius:8px; font-size:14px;")
        parent = self.parentWidget()
        self.setMaximumWidth(int(parent.width() * 0.8))
        self.adjustSize()
        self.move((parent.width() - self.width()) // 2, parent.height() - self.height() - 50)
        self.raise_()
        self.show()
        self._timer.start(ms)
