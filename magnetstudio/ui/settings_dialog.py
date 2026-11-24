"""Settings dialog: enhancer preset and optional Gemini cloud styles."""
from PyQt6.QtWidgets import (QComboBox, QDialog, QDialogButtonBox, QFormLayout, QLabel,
                             QLineEdit, QPushButton)

from magnetstudio.core.ai_enhancer import CLOUD_STYLES, DEFAULT_GEMINI_MODEL, PRESET_LABELS

_CLOUD_LABELS = {"print_ready": "מוכן להדפסה", "warm_party": "מסיבה חמימה", "bw_classic": "שחור-לבן קלאסי"}


class SettingsDialog(QDialog):
    def __init__(self, settings: dict, parent=None):
        super().__init__(parent)
        self.setWindowTitle("הגדרות")
        self.settings = settings
        form = QFormLayout(self)

        self.preset = QComboBox()
        for key, label in PRESET_LABELS.items():
            self.preset.addItem(label, key)
        self.preset.setCurrentIndex(max(0, self.preset.findData(settings.get("enhance_preset"))))
        form.addRow("פריסט מקומי (LUT)", self.preset)

        self.credit = QLineEdit(settings.get("photographer_credit", ""))
        self.credit.setPlaceholderText("שם | טלפון – מופיע אנכית בצד המסגרת")
        form.addRow("קרדיט צלם", self.credit)

        form.addRow(QLabel("<b>סגנונות ענן – Gemini (אופציונלי)</b>"))
        self.cloud = QComboBox()
        self.cloud.addItem("כבוי – מקומי בלבד", None)
        for key in CLOUD_STYLES:
            self.cloud.addItem(_CLOUD_LABELS.get(key, key), key)
        self.cloud.setCurrentIndex(max(0, self.cloud.findData(settings.get("cloud_style"))))
        form.addRow("סגנון ענן", self.cloud)

        self.key = QLineEdit(settings.get("gemini_api_key", ""))
        self.key.setEchoMode(QLineEdit.EchoMode.Password)
        self.key.setPlaceholderText("GEMINI_API_KEY (או משתנה סביבה)")
        form.addRow("מפתח API", self.key)

        self.model = QLineEdit(settings.get("gemini_model") or DEFAULT_GEMINI_MODEL)
        form.addRow("מודל", self.model)
        form.addRow(QLabel("אם אין אינטרנט או שהענן נכשל – המערכת עוברת אוטומטית ל-LUT המקומי.\n"
                           "סגנון ענן מוסיף כמה שניות לכל תמונה."))

        from magnetstudio.core.applog import log_file
        logs_btn = QPushButton("📄 פתח תיקיית לוגים")
        logs_btn.setToolTip(str(log_file()))
        logs_btn.clicked.connect(self._open_logs)
        form.addRow("לוג", logs_btn)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    @staticmethod
    def _open_logs():
        from PyQt6.QtCore import QUrl
        from PyQt6.QtGui import QDesktopServices
        from magnetstudio.core.applog import log_dir
        d = log_dir()
        d.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(d)))

    def _save(self):
        self.settings.update(photographer_credit=self.credit.text().strip(),
                             enhance_preset=self.preset.currentData(),
                             cloud_style=self.cloud.currentData(),
                             gemini_api_key=self.key.text().strip(),
                             gemini_model=self.model.text().strip() or DEFAULT_GEMINI_MODEL)
        self.accept()
