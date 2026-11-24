"""✨ AI frame generator dialog: free-text description → Template, in a background thread."""
from __future__ import annotations

from PIL import Image
from PIL.ImageQt import ImageQt
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import (QCheckBox, QComboBox, QDialog, QFormLayout, QHBoxLayout, QLabel,
                             QLineEdit, QPlainTextEdit, QProgressBar, QPushButton, QVBoxLayout)

from magnetstudio.core.secrets import get_api_key
from magnetstudio.generator import (DEFAULT_ART_MODEL, DEFAULT_CREDIT, DEFAULT_TEXT_MODEL, HAS_GENAI,
                                  HAS_PYDANTIC)
from magnetstudio.services.generator_worker import FrameGeneratorWorker
from magnetstudio.core.sizes import MAGNET_SIZES
from magnetstudio.core.templates import LANDSCAPE, PORTRAIT, Template, TemplatePair, compose_magnet

EXAMPLES = [
    "חתונה של נועה ואורי 13.8.2026, זית עדין עם לב אדום",
    "חינה למורן ואביב 18.09.2026, סגנון מרוקאי בגווני בורדו וזהב",
    "חתונת נועה ואורי 03.06.2027, אלגנטי בגווני לבן וזהב",
    "בר מצווה לאיתי 12 בנובמבר 2026, כחול נייבי וכסף",
    "יום הולדת 40 לדני – מינימליסטי שחור לבן",
]

ACCENT_BUTTON_CSS = """
QPushButton, QToolButton {
  color: #06201E; font-weight: 700; padding: 6px 14px; border-radius: 8px; border: none;
  background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #00D2C4, stop:1 #0090E0);
}
QPushButton:hover, QToolButton:hover {
  background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #2EE6D9, stop:1 #22A6F0);
}
QPushButton:disabled { background: #9a9a9a; }
"""


def _sample_photos(orientation: str = PORTRAIT) -> list[Image.Image]:
    size = (1600, 1200) if orientation == LANDSCAPE else (1200, 1600)
    return [Image.new("RGB", size, c) for c in ((128, 146, 168), (156, 136, 124), (118, 152, 134), (150, 140, 170))]


class FrameGeneratorDialog(QDialog):
    template_ready = pyqtSignal(object)   # Template, emitted on "apply"

    def __init__(self, profile: str = "7.5x10", settings: dict | None = None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("✨ מחולל מסגרות AI")
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.settings = settings or {}
        self.api_key = get_api_key(self.settings)
        self.worker: FrameGeneratorWorker | None = None
        self.result: Template | None = None
        self.resize(960, 640)

        self.prompt = QPlainTextEdit()
        self.prompt.setPlaceholderText("תאר את האירוע: סוג, שמות, תאריך, סגנון וצבעים…\n"
                                       f"לדוגמה: {EXAMPLES[0]}")
        self.prompt.setFixedHeight(90)

        chips = QHBoxLayout()
        for ex in EXAMPLES:
            b = QPushButton(ex.split(",")[0].split("–")[0].strip())
            b.setToolTip(ex)
            b.setStyleSheet("QPushButton{border:1px solid #bbb;border-radius:10px;padding:3px 10px;}")
            b.clicked.connect(lambda _, e=ex: self.prompt.setPlainText(e))
            chips.addWidget(b)
        chips.addStretch()

        self.profile = QComboBox()
        for key, size in MAGNET_SIZES.items():
            self.profile.addItem(size.label, key)
        self.profile.setCurrentIndex(max(0, self.profile.findData(profile)))
        self.profile.currentIndexChanged.connect(self._default_slots)

        self.credit = QLineEdit(self.settings.get("photographer_credit") or DEFAULT_CREDIT)
        self.credit.setPlaceholderText("ריק = ללא קרדיט")

        self.slots = QComboBox()
        self.slots.addItem("אוטומטי", None)
        for n in (1, 2, 3, 4):
            self.slots.addItem(f"{n} {'חלון' if n == 1 else 'חלונות'}", n)

        cloud_ok = bool(self.api_key) and HAS_GENAI and HAS_PYDANTIC
        self.use_ai = QCheckBox("עיצוב חכם עם Gemini (Structured Output)")
        self.use_art = QCheckBox("רקע אמנותי AI (Gemini Image) + Alpha Hole Punch")
        for cb in (self.use_ai, self.use_art):
            cb.setChecked(cloud_ok)
            cb.setEnabled(cloud_ok)
        if cloud_ok:
            mode = "🌐 מחובר לענן – אם יש תקלה, עובר אוטומטית למחולל האופליין"
        elif not HAS_GENAI:
            mode = "🔌 מצב אופליין – google-genai לא מותקן (pip install google-genai)"
        else:
            mode = "🔌 מצב אופליין – אין GEMINI_API_KEY (הגדרות ⚙ בחלון הראשי)"
        self.mode_label = QLabel(mode)
        self.mode_label.setStyleSheet("color:#666;")

        form = QFormLayout()
        form.addRow("תיאור", self.prompt)
        form.addRow("", chips)
        form.addRow("גודל מגנט", self.profile)
        form.addRow("חלונות תמונה", self.slots)
        form.addRow("קרדיט צלם", self.credit)
        form.addRow("", QLabel("תמונה אחת → נוצרות גרסה אנכית ואופקית; המערכת בוחרת לפי התמונה מהמצלמה"))
        form.addRow("", self.use_ai)
        form.addRow("", self.use_art)
        form.addRow("", self.mode_label)

        self.preview = QLabel("התצוגה המקדימה תופיע כאן")
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview.setMinimumSize(420, 420)
        self.preview.setStyleSheet("background:#3a3f47; color:#ccc; border-radius:8px;")

        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.hide()
        self.status = QLabel("")
        self.status.setWordWrap(True)

        self.generate_btn = QPushButton("✨ צור מסגרת")
        self.generate_btn.setStyleSheet(ACCENT_BUTTON_CSS)
        self.generate_btn.clicked.connect(self.generate)
        self.apply_btn = QPushButton("החל על הקנבס")
        self.apply_btn.setEnabled(False)
        self.apply_btn.clicked.connect(self.apply)
        close_btn = QPushButton("סגור")
        close_btn.clicked.connect(self.reject)

        buttons = QHBoxLayout()
        buttons.addWidget(self.generate_btn)
        buttons.addWidget(self.apply_btn)
        buttons.addStretch()
        buttons.addWidget(close_btn)

        left = QVBoxLayout()
        left.addLayout(form)
        left.addWidget(self.progress)
        left.addWidget(self.status)
        left.addStretch()
        left.addLayout(buttons)

        root = QHBoxLayout(self)
        root.addLayout(left, 3)
        root.addWidget(self.preview, 2)

    def _default_slots(self):
        self.slots.setCurrentIndex(0)

    # ---- generation
    def generate(self) -> None:
        text = self.prompt.toPlainText().strip()
        if not text:
            self.status.setText("נא לתאר את האירוע")
            return
        if self.worker is not None and self.worker.isRunning():
            return
        self.result = None
        self.apply_btn.setEnabled(False)
        self.generate_btn.setEnabled(False)
        self.progress.setValue(0)
        self.progress.show()
        w = FrameGeneratorWorker(
            text, self.profile.currentData(), self.slots.currentData(),
            use_ai=self.use_ai.isChecked(), use_art=self.use_art.isChecked() and self.use_ai.isEnabled(),
            api_key=self.api_key,
            text_model=self.settings.get("gemini_text_model") or DEFAULT_TEXT_MODEL,
            art_model=self.settings.get("gemini_art_model") or DEFAULT_ART_MODEL, parent=self,
            credit_text=self.credit.text().strip() or None)
        w.progress.connect(self._on_progress)
        w.finished.connect(self._on_finished)
        w.failed.connect(self._on_failed)
        self.worker = w
        w.start()

    def _on_progress(self, pct: int, msg: str) -> None:
        self.progress.setValue(pct)
        self.status.setText(msg)

    def _on_finished(self, frame: "Template | TemplatePair") -> None:
        self.result = frame
        res = self.worker.result if self.worker else None
        if self.credit.text().strip():
            self.settings["photographer_credit"] = self.credit.text().strip()
        img = self._preview_image(frame)
        pix = QPixmap.fromImage(ImageQt(img.convert("RGBA")))
        self.preview.setPixmap(pix.scaled(self.preview.size(), Qt.AspectRatioMode.KeepAspectRatio,
                                          Qt.TransformationMode.SmoothTransformation))
        engine = {"ai": "Gemini", "offline": "מחולל אופליין"}.get(res.engine if res else "", "")
        extra = " + רקע AI" if res and res.art else ""
        if isinstance(frame, TemplatePair):
            extra += " · אנכי + אופקי"
        notes = f"\n⚠ {res.notes[0]}" if res and res.notes and self.use_ai.isChecked() else ""
        self.status.setText(f"✔ מוכן ({engine}{extra}). לחץ \"החל על הקנבס\" או צור שוב.{notes}")
        self.generate_btn.setEnabled(True)
        self.apply_btn.setEnabled(True)
        self.progress.hide()

    @staticmethod
    def _preview_image(frame: "Template | TemplatePair") -> Image.Image:
        """Single template, or both orientations side by side (equal height)."""
        if not isinstance(frame, TemplatePair):
            return compose_magnet(frame, _sample_photos(frame.orientation))
        imgs = [compose_magnet(t, _sample_photos(o)) for o, t in frame.variants.items()]
        h = max(i.height for i in imgs)
        imgs = [i.resize((round(i.width * h / i.height), h)) for i in imgs]
        gap = h // 20
        sheet = Image.new("RGB", (sum(i.width for i in imgs) + gap * (len(imgs) - 1), h), (58, 63, 71))
        x = 0
        for i in imgs:
            sheet.paste(i, (x, 0))
            x += i.width + gap
        return sheet

    def _on_failed(self, msg: str) -> None:
        self.status.setText(f"✘ {msg}")
        self.generate_btn.setEnabled(True)
        self.progress.hide()

    def apply(self) -> None:
        if self.result is not None:
            self.template_ready.emit(self.result)
            self.accept()

    def done(self, r: int) -> None:  # never close with a thread still running
        if self.worker is not None and self.worker.isRunning():
            self.worker.wait(60_000)
        super().done(r)
