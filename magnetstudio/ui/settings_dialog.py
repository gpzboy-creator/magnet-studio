"""Settings dialog: enhancer preset and optional Gemini cloud styles."""
from PyQt6.QtWidgets import (QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox, QFormLayout, QLabel,
                             QLineEdit, QPushButton)

from magnetstudio import paths
from magnetstudio.core import secrets
from magnetstudio.core.ai_enhancer import CLOUD_STYLES, DEFAULT_GEMINI_MODEL, PRESET_LABELS

_CLOUD_LABELS = {"print_ready": "מוכן להדפסה", "warm_party": "מסיבה חמימה", "bw_classic": "שחור-לבן קלאסי"}


class SettingsDialog(QDialog):
    def __init__(self, settings: dict, parent=None):
        super().__init__(parent)
        self.setWindowTitle("הגדרות")
        self.settings = settings
        form = QFormLayout(self)

        self.theme_mode = QComboBox()
        for key, label in (("auto", "אוטומטי – לפי Windows / Mac"), ("light", "בהיר"), ("dark", "כהה")):
            self.theme_mode.addItem(label, key)
        self.theme_mode.setCurrentIndex(max(0, self.theme_mode.findData(settings.get("theme_mode", "auto"))))
        self.theme_mode.setToolTip("נכנס לתוקף בהפעלה הבאה של התוכנה")
        form.addRow("מצב תצוגה", self.theme_mode)

        self.cost = QDoubleSpinBox()
        self.cost.setRange(0, 1000)
        self.cost.setDecimals(2)
        self.cost.setSuffix(" ₪")
        self.cost.setValue(float(settings.get("cost_per_sheet") or 0))
        form.addRow("עלות לדף", self.cost)

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

        # the key lives in the OS keychain (Keychain / Credential Manager), not in settings.json
        self._initial_key = secrets.get_secret(secrets.GEMINI_KEY) or settings.get("gemini_api_key", "")
        self.key = QLineEdit(self._initial_key)
        self.key.setEchoMode(QLineEdit.EchoMode.Password)
        self.key.setPlaceholderText("GEMINI_API_KEY (או משתנה סביבה)")
        self.key.setToolTip("נשמר במחזיק המפתחות של מערכת ההפעלה" if secrets.keyring_available()
                            else "אין מחזיק מפתחות זמין – נשמר בקובץ ההגדרות")
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
        data_btn = QPushButton("📁 פתח תיקיית תבניות וגופנים")
        data_btn.setToolTip(str(paths.data_dir()))
        data_btn.clicked.connect(lambda: self._open_dir(paths.data_dir()))
        form.addRow("נתונים", data_btn)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    @staticmethod
    def _open_dir(d):
        from PyQt6.QtCore import QUrl
        from PyQt6.QtGui import QDesktopServices
        d.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(d)))

    @classmethod
    def _open_logs(cls):
        cls._open_dir(paths.log_dir())

    def _save(self):
        self.settings.update(theme_mode=self.theme_mode.currentData(), cost_per_sheet=self.cost.value(),
                             photographer_credit=self.credit.text().strip(),
                             enhance_preset=self.preset.currentData(),
                             cloud_style=self.cloud.currentData(),
                             gemini_model=self.model.text().strip() or DEFAULT_GEMINI_MODEL)
        if self.key.text().strip() != self._initial_key:
            secrets.store_api_key(self.settings, self.key.text())
        self.accept()
