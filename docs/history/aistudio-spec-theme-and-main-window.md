# AI Studio design spec – theme + main window

> Original input from Google AI Studio, pasted by Shahar. Integrated into ui/theme.py,
> ui/main_window.py and ui/components/queue_panel.py (adapted). Kept for reference only.

הנה שני קבצי הממשק והעיצוב החדשים מ-Google AI Studio. אנא צור/עדכן אותם, שלב אותם בחלון הראשי, והרץ את האפליקציה על תצוגה וירטואלית כדי להפיק צילום מסך:

1. צור את ui/theme.py:
```python
"""
ui/theme.py - Dark High-Contrast Design System & QSS for MagnetStudio
Adobe Lightroom / Capture One style engineered for dark event banquet halls.
"""

from __future__ import annotations

from dataclasses import dataclass
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import QApplication


@dataclass(frozen=True)
class ThemeColors:
    """Exact color palette and design tokens for MagnetStudio."""
    # Backgrounds
    BG_ROOT: str = "#121316"        # Deep charcoal base
    BG_CARD: str = "#1A1C20"        # Slightly lighter surface (cards, panels)
    BG_ELEVATED: str = "#24272D"    # Inputs, elevated buttons
    BG_HIGHLIGHT: str = "#2F333B"   # Active / selected item background

    # Borders
    BORDER_SUBTLE: str = "#2E323A"  # 1px structural frame border

    # Typography
    TEXT_PRIMARY: str = "#F8F9FA"   # Bright crisp text (headings, key metrics)
    TEXT_SECONDARY: str = "#ADB5BD" # Subtle labels, secondary metadata
    TEXT_MUTED: str = "#6C757D"     # Low-emphasis text, inactive timestamps

    # Semantics & Accents
    ACCENT_CYAN: str = "#00D2C4"    # Main active accent (ready, primary actions)
    ACCENT_MINT: str = "#06D6A0"    # Ready / success state (printed, online)
    ACCENT_AMBER: str = "#FFB703"   # Processing / warning (spooling, rendering)
    ACCENT_CORAL: str = "#EF476F"   # Error / offline state (failed, disconnected)

    # Interactivity Tint Helpers
    ACCENT_CYAN_HOVER: str = "#20E5D7"
    ACCENT_CYAN_PRESSED: str = "#00B5A8"

    # Cross-component aliases
    BG_SURFACE: str = BG_CARD
    BORDER_FOCUS: str = ACCENT_CYAN


def get_theme_qss() -> str:
    """
    Returns the complete Qt Style Sheet (QSS) for MagnetStudio.
    Features touch-friendly sizing (minimum 36-42px targets), high-contrast
    elements for low-light environments, and sleek minimal scrollbars.
    """
    return f"""
    /* ==========================================================================
       GLOBAL BASE & WINDOWS
       ========================================================================== */
    QMainWindow, QDialog, QWidget {{
        background-color: {ThemeColors.BG_ROOT};
        color: {ThemeColors.TEXT_PRIMARY};
        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
        font-size: 13px;
        selection-background-color: {ThemeColors.ACCENT_CYAN};
        selection-color: #071716;
    }}

    /* ==========================================================================
       CARDS & PANELS
       ========================================================================== */
    QFrame[class="card"], .card {{
        background-color: {ThemeColors.BG_CARD};
        border: 1px solid {ThemeColors.BORDER_SUBTLE};
        border-radius: 6px;
    }}

    QFrame[class="card"]:hover, .card:hover {{
        border: 1px solid {ThemeColors.ACCENT_CYAN};
    }}

    QScrollArea {{
        background-color: transparent;
        border: none;
    }}

    QScrollArea > QWidget > QWidget {{
        background-color: transparent;
    }}

    /* ==========================================================================
       BUTTONS (TOUCH TARGET: 36-42px)
       ========================================================================== */
    QPushButton {{
        background-color: {ThemeColors.BG_ELEVATED};
        color: {ThemeColors.TEXT_PRIMARY};
        border: 1px solid {ThemeColors.BORDER_SUBTLE};
        border-radius: 6px;
        padding: 8px 16px;
        font-size: 13px;
        font-weight: 600;
        min-height: 22px;
    }}

    QPushButton:hover {{
        background-color: {ThemeColors.BG_HIGHLIGHT};
        border-color: {ThemeColors.TEXT_SECONDARY};
    }}

    QPushButton:pressed {{
        background-color: {ThemeColors.BG_CARD};
        border-color: {ThemeColors.ACCENT_CYAN};
    }}

    QPushButton:disabled {{
        background-color: {ThemeColors.BG_CARD};
        color: {ThemeColors.TEXT_MUTED};
        border-color: {ThemeColors.BORDER_SUBTLE};
    }}

    /* Action Buttons (Queue Card quick touch actions) */
    QPushButton[class="action-btn"], QPushButton.action-btn {{
        background-color: {ThemeColors.BG_ELEVATED};
        color: {ThemeColors.TEXT_PRIMARY};
        border: 1px solid {ThemeColors.BORDER_SUBTLE};
        border-radius: 6px;
        padding: 6px 14px;
        font-size: 12px;
        font-weight: 600;
        min-height: 24px;
    }}

    QPushButton[class="action-btn"]:hover, QPushButton.action-btn:hover {{
        background-color: {ThemeColors.ACCENT_CYAN};
        color: #071716;
        border: 1px solid {ThemeColors.ACCENT_CYAN};
    }}

    QPushButton[class="action-btn"]:pressed, QPushButton.action-btn:pressed {{
        background-color: {ThemeColors.ACCENT_CYAN_PRESSED};
        color: #071716;
        border: 1px solid {ThemeColors.ACCENT_CYAN_PRESSED};
    }}

    /* Primary Accent Button */
    QPushButton[class="primary"], QPushButton.primary {{
        background-color: {ThemeColors.ACCENT_CYAN};
        color: #071716;
        border: 1px solid {ThemeColors.ACCENT_CYAN};
        font-weight: 700;
    }}

    QPushButton[class="primary"]:hover, QPushButton.primary:hover {{
        background-color: {ThemeColors.ACCENT_CYAN_HOVER};
        border-color: {ThemeColors.ACCENT_CYAN_HOVER};
    }}

    QPushButton[class="primary"]:pressed, QPushButton.primary:pressed {{
        background-color: {ThemeColors.ACCENT_CYAN_PRESSED};
        border-color: {ThemeColors.ACCENT_CYAN_PRESSED};
    }}

    /* ==========================================================================
       INPUT CONTROLS
       ========================================================================== */
    QLineEdit, QSpinBox, QDoubleSpinBox {{
        background-color: {ThemeColors.BG_CARD};
        color: {ThemeColors.TEXT_PRIMARY};
        border: 1px solid {ThemeColors.BORDER_SUBTLE};
        border-radius: 6px;
        padding: 7px 12px;
        min-height: 20px;
    }}

    QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus {{
        border: 1px solid {ThemeColors.ACCENT_CYAN};
        background-color: {ThemeColors.BG_ELEVATED};
    }}

    QComboBox {{
        background-color: {ThemeColors.BG_CARD};
        color: {ThemeColors.TEXT_PRIMARY};
        border: 1px solid {ThemeColors.BORDER_SUBTLE};
        border-radius: 6px;
        padding: 7px 14px;
        min-height: 20px;
        font-weight: 500;
    }}

    QComboBox:hover {{
        border-color: {ThemeColors.TEXT_SECONDARY};
    }}

    QComboBox:focus {{
        border-color: {ThemeColors.ACCENT_CYAN};
    }}

    QComboBox::drop-down {{
        border: none;
        width: 24px;
    }}

    QComboBox::down-arrow {{
        image: none;
        border-left: 5px solid transparent;
        border-right: 5px solid transparent;
        border-top: 5px solid {ThemeColors.TEXT_SECONDARY};
        margin-right: 8px;
    }}

    QComboBox QAbstractItemView {{
        background-color: {ThemeColors.BG_ELEVATED};
        color: {ThemeColors.TEXT_PRIMARY};
        border: 1px solid {ThemeColors.BORDER_SUBTLE};
        selection-background-color: {ThemeColors.ACCENT_CYAN};
        selection-color: #071716;
        outline: none;
        padding: 4px;
    }}

    /* ==========================================================================
       CHECKBOX & RADIO (TOUCH SIZED)
       ========================================================================== */
    QCheckBox, QRadioButton {{
        color: {ThemeColors.TEXT_PRIMARY};
        spacing: 10px;
        font-size: 13px;
    }}

    QCheckBox::indicator, QRadioButton::indicator {{
        width: 20px;
        height: 20px;
        background-color: {ThemeColors.BG_CARD};
        border: 1px solid {ThemeColors.BORDER_SUBTLE};
        border-radius: 4px;
    }}

    QRadioButton::indicator {{
        border-radius: 10px;
    }}

    QCheckBox::indicator:hover, QRadioButton::indicator:hover {{
        border-color: {ThemeColors.ACCENT_CYAN};
    }}

    QCheckBox::indicator:checked, QRadioButton::indicator:checked {{
        background-color: {ThemeColors.ACCENT_CYAN};
        border-color: {ThemeColors.ACCENT_CYAN};
    }}

    /* ==========================================================================
       PROGRESS BARS
       ========================================================================== */
    QProgressBar {{
        background-color: {ThemeColors.BG_CARD};
        border: 1px solid {ThemeColors.BORDER_SUBTLE};
        border-radius: 4px;
        height: 8px;
        text-align: center;
        color: transparent;
    }}

    QProgressBar::chunk {{
        background-color: {ThemeColors.ACCENT_CYAN};
        border-radius: 3px;
    }}

    /* ==========================================================================
       MINIMAL HARDWARE-SCALED SCROLLBARS
       ========================================================================== */
    QScrollBar:vertical {{
        background-color: transparent;
        width: 8px;
        margin: 0;
    }}

    QScrollBar::handle:vertical {{
        background-color: {ThemeColors.BG_HIGHLIGHT};
        min-height: 30px;
        border-radius: 4px;
    }}

    QScrollBar::handle:vertical:hover {{
        background-color: {ThemeColors.TEXT_SECONDARY};
    }}

    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical,
    QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
        background: none;
        height: 0px;
    }}

    QScrollBar:horizontal {{
        background-color: transparent;
        height: 8px;
        margin: 0;
    }}

    QScrollBar::handle:horizontal {{
        background-color: {ThemeColors.BG_HIGHLIGHT};
        min-width: 30px;
        border-radius: 4px;
    }}

    QScrollBar::handle:horizontal:hover {{
        background-color: {ThemeColors.TEXT_SECONDARY};
    }}

    QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal,
    QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {{
        background: none;
        width: 0px;
    }}

    /* ==========================================================================
       STATUS BAR
       ========================================================================== */
    QStatusBar {{
        background-color: {ThemeColors.BG_CARD};
        border-top: 1px solid {ThemeColors.BORDER_SUBTLE};
        color: {ThemeColors.TEXT_SECONDARY};
        font-size: 12px;
    }}
    """


def apply_theme(app: QApplication) -> None:
    """Convenience helper to apply the QSS stylesheet and base typography to the app."""
    app.setStyleSheet(get_theme_qss())
    app.setFont(QFont("-apple-system, BlinkMacSystemFont, Segoe UI, Roboto, Helvetica", 10))