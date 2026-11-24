# AI Studio design spec – live print queue panel

> Original input from Google AI Studio, pasted by Shahar. Integrated into ui/theme.py,
> ui/main_window.py and ui/components/queue_panel.py (adapted). Kept for reference only.

```python
"""
ui/components/queue_panel.py - High-Glance Live Print Queue Panel
MagnetStudio (PyQt6)
"""

from __future__ import annotations

import time
from enum import Enum
from pathlib import Path
from typing import Dict, Optional

from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QPixmap
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ui.theme import ThemeColors


class QueueItemStatus(Enum):
    INCOMING = ("Incoming", ThemeColors.TEXT_SECONDARY, "rgba(173, 181, 189, 0.15)")
    ENHANCED = ("Enhanced", ThemeColors.ACCENT_CYAN, "rgba(0, 210, 196, 0.15)")
    COMPOSED = ("Composed", "#9D4EDD", "rgba(157, 78, 221, 0.15)")
    SPOOLING = ("Spooling", ThemeColors.ACCENT_AMBER, "rgba(255, 183, 3, 0.15)")
    PRINTED = ("Printed", ThemeColors.ACCENT_MINT, "rgba(6, 214, 160, 0.15)")
    FAILED = ("Failed", ThemeColors.ACCENT_CORAL, "rgba(239, 71, 111, 0.15)")

    def __init__(self, label: str, fg_color: str, bg_color: str):
        self.label = label
        self.fg_color = fg_color
        self.bg_color = bg_color


class QueueCardWidget(QFrame):
    """Visual queue card featuring instant thumbnail, status badge, and touch buttons."""
    copy_requested = pyqtSignal(str)     # job_id
    reprint_requested = pyqtSignal(str)  # job_id
    inspect_requested = pyqtSignal(str)  # job_id

    def __init__(
        self,
        job_id: str,
        photo_path: str,
        status: QueueItemStatus = QueueItemStatus.INCOMING,
        copies: int = 1,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.job_id = job_id
        self.photo_path = photo_path
        self.status = status
        self.copies = copies

        self.setProperty("class", "card")
        self.setFixedHeight(88)

        self._init_ui()
        self.update_status(status)

    def _init_ui(self) -> None:
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 8, 12, 8)
        layout.setSpacing(12)

        # 1. Square Thumbnail
        self.thumb_label = QLabel()
        self.thumb_label.setFixedSize(70, 70)
        self.thumb_label.setStyleSheet(
            f"background-color: {ThemeColors.BG_ROOT}; border-radius: 4px; border: 1px solid {ThemeColors.BORDER_SUBTLE};"
        )
        self.thumb_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._load_thumbnail()
        layout.addWidget(self.thumb_label)

        # 2. Metadata Info
        info_layout = QVBoxLayout()
        info_layout.setSpacing(4)
        info_layout.setAlignment(Qt.AlignmentFlag.AlignVCenter)

        file_name = Path(self.photo_path).name if self.photo_path else f"Job #{self.job_id}"
        self.title_lbl = QLabel(file_name)
        self.title_lbl.setFont(QFont("Arial", 11, QFont.Weight.Bold))
        self.title_lbl.setStyleSheet(f"color: {ThemeColors.TEXT_PRIMARY};")

        meta_layout = QHBoxLayout()
        meta_layout.setSpacing(8)

        # Status badge pill
        self.badge_lbl = QLabel()
        self.badge_lbl.setFont(QFont("Arial", 9, QFont.Weight.Bold))
        self.badge_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.badge_lbl.setFixedHeight(20)

        # Time label
        self.time_lbl = QLabel(time.strftime("%H:%M:%S"))
        self.time_lbl.setStyleSheet(f"color: {ThemeColors.TEXT_MUTED}; font-size: 11px;")

        meta_layout.addWidget(self.badge_lbl)
        meta_layout.addWidget(self.time_lbl)
        meta_layout.addStretch()

        info_layout.addWidget(self.title_lbl)
        info_layout.addLayout(meta_layout)
        layout.addLayout(info_layout, stretch=1)

        # 3. Action Buttons
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(6)

        self.btn_inspect = QPushButton("Inspect")
        self.btn_inspect.setProperty("class", "action-btn")
        self.btn_inspect.clicked.connect(lambda: self.inspect_requested.emit(self.job_id))

        self.btn_copy = QPushButton("+1 Copy")
        self.btn_copy.setProperty("class", "action-btn")
        self.btn_copy.clicked.connect(lambda: self.copy_requested.emit(self.job_id))

        self.btn_reprint = QPushButton("Reprint")
        self.btn_reprint.setProperty("class", "action-btn")
        self.btn_reprint.clicked.connect(lambda: self.reprint_requested.emit(self.job_id))

        btn_layout.addWidget(self.btn_inspect)
        btn_layout.addWidget(self.btn_copy)
        btn_layout.addWidget(self.btn_reprint)
        layout.addLayout(btn_layout)

    def _load_thumbnail(self) -> None:
        if self.photo_path and Path(self.photo_path).exists():
            pix = QPixmap(self.photo_path)
            if not pix.isNull():
                scaled = pix.scaled(
                    70, 70,
                    Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                    Qt.TransformationMode.SmoothTransformation,
                )
                self.thumb_label.setPixmap(scaled)
                return
        self.thumb_label.setText("IMG")
        self.thumb_label.setStyleSheet(f"color: {ThemeColors.TEXT_MUTED}; font-weight: bold;")

    def update_status(self, status: QueueItemStatus) -> None:
        self.status = status
        self.badge_lbl.setText(f"  {status.label.upper()}  ")
        self.badge_lbl.setStyleSheet(
            f"color: {status.fg_color}; "
            f"background-color: {status.bg_color}; "
            f"border: 1px solid {status.fg_color}; "
            f"border-radius: 4px;"
        )


class QueuePanel(QWidget):
    """Top-level queue viewport with printer metrics and photo stream."""
    reprint_job = pyqtSignal(str)
    inspect_job = pyqtSignal(str)
    add_copy_job = pyqtSignal(str)

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._cards: Dict[str, QueueCardWidget] = {}
        self._pulse_state = False
        self._total_prints = 0

        self._init_ui()
        self._init_pulse_timer()

    def _init_ui(self) -> None:
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(12, 12, 12, 12)
        main_layout.setSpacing(12)

        # TOP BAR
        top_bar = QHBoxLayout()
        top_bar.setSpacing(10)

        # Chip 1: Printer Status
        self.printer_chip = QFrame()
        self.printer_chip.setProperty("class", "card")
        self.printer_chip.setFixedHeight(54)
        p_layout = QHBoxLayout(self.printer_chip)
        p_layout.setContentsMargins(14, 6, 14, 6)

        self.printer_dot = QLabel("●")
        self.printer_dot.setStyleSheet(f"color: {ThemeColors.ACCENT_MINT}; font-size: 16px;")
        self.printer_title = QLabel("PRINTER")
        self.printer_title.setStyleSheet(f"color: {ThemeColors.TEXT_MUTED}; font-size: 10px; font-weight: bold;")
        self.printer_value = QLabel("Ready (DNP DS620)")
        self.printer_value.setStyleSheet(f"color: {ThemeColors.TEXT_PRIMARY}; font-size: 12px; font-weight: bold;")

        p_text_box = QVBoxLayout()
        p_text_box.setSpacing(1)
        p_text_box.addWidget(self.printer_title)
        p_text_box.addWidget(self.printer_value)

        p_layout.addWidget(self.printer_dot)
        p_layout.addLayout(p_text_box)
        top_bar.addWidget(self.printer_chip, stretch=3)

        # Chip 2: Hot Folder Pulse Indicator
        self.folder_chip = QFrame()
        self.folder_chip.setProperty("class", "card")
        self.folder_chip.setFixedHeight(54)
        f_layout = QHBoxLayout(self.folder_chip)
        f_layout.setContentsMargins(14, 6, 14, 6)

        self.pulse_dot = QLabel("⚡")
        self.pulse_dot.setStyleSheet(f"color: {ThemeColors.ACCENT_CYAN}; font-size: 14px;")
        self.folder_title = QLabel("HOT FOLDER")
        self.folder_title.setStyleSheet(f"color: {ThemeColors.TEXT_MUTED}; font-size: 10px; font-weight: bold;")
        self.folder_value = QLabel("Listening: /SD_Card/DCIM")
        self.folder_value.setStyleSheet(f"color: {ThemeColors.TEXT_PRIMARY}; font-size: 12px; font-weight: bold;")

        f_text_box = QVBoxLayout()
        f_text_box.setSpacing(1)
        f_text_box.addWidget(self.folder_title)
        f_text_box.addWidget(self.folder_value)

        f_layout.addWidget(self.pulse_dot)
        f_layout.addLayout(f_text_box)
        top_bar.addWidget(self.folder_chip, stretch=3)

        # Chip 3: Total Prints Counter
        self.counter_chip = QFrame()
        self.counter_chip.setProperty("class", "card")
        self.counter_chip.setFixedHeight(54)
        c_layout = QHBoxLayout(self.counter_chip)
        c_layout.setContentsMargins(14, 6, 14, 6)

        c_text_box = QVBoxLayout()
        c_text_box.setSpacing(1)
        c_title = QLabel("TOTAL PRINTS")
        c_title.setStyleSheet(f"color: {ThemeColors.TEXT_MUTED}; font-size: 10px; font-weight: bold;")
        self.count_lbl = QLabel("0")
        self.count_lbl.setStyleSheet(f"color: {ThemeColors.ACCENT_CYAN}; font-size: 16px; font-weight: 800;")
        c_text_box.addWidget(c_title)
        c_text_box.addWidget(self.count_lbl)

        c_layout.addLayout(c_text_box)
        top_bar.addWidget(self.counter_chip, stretch=2)

        main_layout.addLayout(top_bar)

        # CARD STREAM
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        self.cards_container = QWidget()
        self.cards_layout = QVBoxLayout(self.cards_container)
        self.cards_layout.setContentsMargins(0, 0, 0, 0)
        self.cards_layout.setSpacing(8)
        self.cards_layout.addStretch()

        self.scroll_area.setWidget(self.cards_container)
        main_layout.addWidget(self.scroll_area, stretch=1)

    def _init_pulse_timer(self) -> None:
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._toggle_pulse)
        self.timer.start(1000)

    def _toggle_pulse(self) -> None:
        self._pulse_state = not self._pulse_state
        color = ThemeColors.ACCENT_CYAN if self._pulse_state else ThemeColors.TEXT_MUTED
        self.pulse_dot.setStyleSheet(f"color: {color}; font-size: 14px;")

    def add_queue_card(
        self,
        job_id: str,
        photo_path: str,
        status: QueueItemStatus = QueueItemStatus.INCOMING,
        copies: int = 1,
    ) -> None:
        card = QueueCardWidget(job_id=job_id, photo_path=photo_path, status=status, copies=copies)
        card.copy_requested.connect(self.add_copy_job.emit)
        card.reprint_requested.connect(self.reprint_job.emit)
        card.inspect_requested.connect(self.inspect_job.emit)

        self._cards[job_id] = card
        self.cards_layout.insertWidget(0, card)

    def update_item_status(self, job_id: str, status: QueueItemStatus) -> None:
        if job_id in self._cards:
            self._cards[job_id].update_status(status)
            if status == QueueItemStatus.PRINTED:
                self.increment_print_counter()

    def set_printer_state(self, name: str, online: bool) -> None:
        if online:
            self.printer_dot.setStyleSheet(f"color: {ThemeColors.ACCENT_MINT}; font-size: 16px;")
            self.printer_value.setText(f"Ready ({name})")
        else:
            self.printer_dot.setStyleSheet(f"color: {ThemeColors.ACCENT_CORAL}; font-size: 16px;")
            self.printer_value.setText(f"Offline ({name})")

    def set_hot_folder(self, folder_path: str, active: bool = True) -> None:
        folder_name = Path(folder_path).name or folder_path
        self.folder_value.setText(f"Watching: {folder_name}" if active else "Inactive")
        if not active:
            self.timer.stop()
            self.pulse_dot.setStyleSheet(f"color: {ThemeColors.TEXT_MUTED}; font-size: 14px;")
        elif not self.timer.isActive():
            self.timer.start(1000)

    def increment_print_counter(self, amount: int = 1) -> None:
        self._total_prints += amount
        self.count_lbl.setText(str(self._total_prints))
```
