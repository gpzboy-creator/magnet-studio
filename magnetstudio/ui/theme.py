"""
ui/theme.py - Dark High-Contrast Design System & QSS for MagnetStudio
Adobe Lightroom / Capture One style engineered for dark event banquet halls.

Source: Google AI Studio design (ThemeColors + get_theme_qss), integrated into MagnetStudio.
Integration changes are marked [MagnetStudio]:
  - QSS font-family stack removed (Qt has no -apple-system; it overrode the bundled Hebrew font).
    The app font is set with QFont.setFamilies in apply_theme instead.
  - apply_theme also sets right-to-left direction, Fusion style and a dark palette.
  - APP_QSS adds rules for MagnetStudio-specific widgets (top bar, panels, designer, dialogs).
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
        /* [MagnetStudio] font-family stack removed – see apply_theme() */
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


# ============================================================== [MagnetStudio] integration

C = ThemeColors


from magnetstudio.paths import UI_ICONS_DIR as _UI_ICONS_DIR  # noqa: E402

_ICONS = _UI_ICONS_DIR.as_posix()

# Labels / checkboxes must not repaint BG_ROOT on top of cards (the QWidget rule above would).
APP_QSS = f"""
    QLabel, QCheckBox, QRadioButton {{ background: transparent; }}
    QFrame[class="card"][selected="true"] {{ border: 1px solid {C.ACCENT_CYAN}; background-color: {C.BG_HIGHLIGHT}; }}

    /* Combo / spin arrows: the CSS border-triangle trick draws a small square in Qt → SVG chevrons */
    QComboBox::down-arrow {{ image: url({_ICONS}/chevron-down.svg); width: 12px; height: 12px;
                             border: none; margin: 0 8px; }}
    QSpinBox, QDoubleSpinBox {{ padding-left: 26px; }}
    QSpinBox::up-button, QSpinBox::down-button, QDoubleSpinBox::up-button, QDoubleSpinBox::down-button {{
        subcontrol-origin: border; width: 24px; border: none; background: transparent; }}
    QSpinBox::up-button, QDoubleSpinBox::up-button {{ subcontrol-position: top left; }}
    QSpinBox::down-button, QDoubleSpinBox::down-button {{ subcontrol-position: bottom left; }}
    QSpinBox::up-button:hover, QSpinBox::down-button:hover,
    QDoubleSpinBox::up-button:hover, QDoubleSpinBox::down-button:hover {{ background: {C.BG_HIGHLIGHT}; }}
    QSpinBox::up-arrow, QDoubleSpinBox::up-arrow {{ image: url({_ICONS}/chevron-up.svg); width: 10px; height: 10px; }}
    QSpinBox::down-arrow, QDoubleSpinBox::down-arrow {{ image: url({_ICONS}/chevron-down.svg); width: 10px; height: 10px; }}
    QPushButton[icon-only="true"] {{ padding: 0; font-size: 16px; }}
    QToolTip {{ background: {C.BG_ELEVATED}; color: {C.TEXT_PRIMARY}; border: 1px solid {C.BORDER_SUBTLE}; padding: 4px 8px; }}

    #TopBar {{ background: {C.BG_CARD}; border-bottom: 1px solid {C.BORDER_SUBTLE}; }}
    #AppTitle {{ font-size: 16px; font-weight: 700; color: {C.TEXT_PRIMARY}; }}
    #AppTitle[accent="true"] {{ color: {C.ACCENT_CYAN}; }}
    #Panel {{ background: {C.BG_CARD}; border: 1px solid {C.BORDER_SUBTLE}; border-radius: 6px; }}
    #PreviewArea {{ background: {C.BG_ROOT}; border: 1px dashed {C.BORDER_SUBTLE}; border-radius: 6px; color: {C.TEXT_MUTED}; }}
    #PanelTitle {{ color: {C.TEXT_MUTED}; font-size: 10px; font-weight: 700; letter-spacing: 1px; }}
    QLabel#Dim {{ color: {C.TEXT_SECONDARY}; }}

    QToolButton {{
        background: {C.BG_ELEVATED}; color: {C.TEXT_PRIMARY}; border: 1px solid {C.BORDER_SUBTLE};
        border-radius: 6px; padding: 8px 14px; font-weight: 600;
    }}
    QToolButton:hover {{ background: {C.BG_HIGHLIGHT}; border-color: {C.TEXT_SECONDARY}; }}
    QToolButton:checked {{ background: rgba(0, 210, 196, 0.14); color: {C.ACCENT_CYAN}; border-color: {C.ACCENT_CYAN}; }}
    QPushButton[ghost="true"] {{ background: transparent; color: {C.TEXT_SECONDARY}; }}
    QPushButton[ghost="true"]:hover {{ color: {C.TEXT_PRIMARY}; border-color: {C.ACCENT_CYAN}; }}
    QPushButton[class="primary"][big="true"] {{ font-size: 15px; padding: 11px 16px; }}

    QPlainTextEdit, QTextEdit {{
        background: {C.BG_CARD}; color: {C.TEXT_PRIMARY}; border: 1px solid {C.BORDER_SUBTLE}; border-radius: 6px;
        selection-background-color: {C.ACCENT_CYAN}; selection-color: #071716;
    }}
    QPlainTextEdit:focus, QTextEdit:focus {{ border-color: {C.ACCENT_CYAN}; }}
    QSplitter::handle {{ background: {C.BG_ROOT}; }}

    /* designer / dialogs */
    QToolBar {{ background: {C.BG_CARD}; border: none; border-bottom: 1px solid {C.BORDER_SUBTLE}; spacing: 6px; padding: 4px; }}
    QDockWidget {{ color: {C.TEXT_SECONDARY}; }}
    QDockWidget::title {{ background: {C.BG_CARD}; padding: 6px; border-bottom: 1px solid {C.BORDER_SUBTLE}; }}
    QGraphicsView {{ border: none; }}
    QMenu {{ background: {C.BG_ELEVATED}; border: 1px solid {C.BORDER_SUBTLE}; padding: 4px; }}
    QMenu::item:selected {{ background: {C.BG_HIGHLIGHT}; color: {C.ACCENT_CYAN}; }}
"""

# Hebrew-capable UI fonts, best first (Heebo / Assistant ship in assets/fonts).
UI_FONT_FAMILIES = ["Heebo", "Assistant", "Segoe UI", "SF Pro Text", "Helvetica Neue", "Arial"]

# Short aliases used elsewhere in the app
ACCENT = C.ACCENT_CYAN
OK, WARN, ERR = C.ACCENT_MINT, C.ACCENT_AMBER, C.ACCENT_CORAL
TEXT_MUTED, BG_HIGHLIGHT = C.TEXT_MUTED, C.BG_HIGHLIGHT


def _palette():
    from PyQt6.QtGui import QColor, QPalette
    p = QPalette()
    roles = {
        QPalette.ColorRole.Window: C.BG_ROOT, QPalette.ColorRole.WindowText: C.TEXT_PRIMARY,
        QPalette.ColorRole.Base: C.BG_CARD, QPalette.ColorRole.AlternateBase: C.BG_ELEVATED,
        QPalette.ColorRole.Text: C.TEXT_PRIMARY, QPalette.ColorRole.Button: C.BG_ELEVATED,
        QPalette.ColorRole.ButtonText: C.TEXT_PRIMARY, QPalette.ColorRole.Highlight: C.ACCENT_CYAN,
        QPalette.ColorRole.HighlightedText: QColor("#071716"), QPalette.ColorRole.ToolTipBase: C.BG_ELEVATED,
        QPalette.ColorRole.ToolTipText: C.TEXT_PRIMARY, QPalette.ColorRole.PlaceholderText: C.TEXT_MUTED,
        QPalette.ColorRole.Link: C.ACCENT_CYAN, QPalette.ColorRole.Mid: C.BORDER_SUBTLE,
    }
    for role, color in roles.items():
        p.setColor(role, QColor(color))
    for role in (QPalette.ColorRole.Text, QPalette.ColorRole.ButtonText, QPalette.ColorRole.WindowText):
        p.setColor(QPalette.ColorGroup.Disabled, role, QColor(C.TEXT_MUTED))
    return p


def apply_theme(app: QApplication) -> None:
    """Convenience helper to apply the QSS stylesheet and base typography to the app."""
    from PyQt6.QtCore import Qt
    # [MagnetStudio] Hebrew UI: RTL app-wide. Without it Qt lays out widget text as LTR
    # paragraphs and mixed strings ("+1 עותק", "מ-Hot Folder", leading emoji) come out scrambled.
    app.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
    # [MagnetStudio] Fusion + dark palette: same look on Windows and macOS, dark native dialogs.
    app.setStyle("Fusion")
    app.setPalette(_palette())
    app.setStyleSheet(get_theme_qss() + APP_QSS)
    # [MagnetStudio] QFont takes a list of families (a CSS-style "a, b, c" string is one invalid name).
    font = QFont()
    font.setFamilies(UI_FONT_FAMILIES)
    font.setPointSize(10)
    app.setFont(font)


def repolish(widget) -> None:
    """Re-apply QSS after changing a dynamic property."""
    widget.style().unpolish(widget)
    widget.style().polish(widget)
    widget.update()
