"""
ui/components/queue_panel.py - High-Glance Live Print Queue Panel
MagnetStudio (PyQt6)

Source: Google AI Studio design, integrated into MagnetStudio. Changes are marked [MagnetStudio]:
  - Hebrew labels (the app UI is Hebrew/RTL); English originals kept in comments.
  - Thumbnails via ui.widgets.make_thumb (JPEG draft decode + EXIF rotation) instead of
    QPixmap(path), which decoded full 24MP originals on the GUI thread.
  - Hot-folder pulse starts only when a folder is active (it blinked while "Inactive").
  - Counter counts magnets (update_item_status(..., count_printed=n)) and can be seeded
    with the persisted total (set_total_prints).
  - set_printer_state(..., state=) adds "busy" / "test" states and elides long printer names.
  - folder chip emits hot_folder_toggle_requested when clicked.
  - keyboard: selected card (↑/↓), Space prints; a photo that was already PRINTED needs a
    double-tap within 1.5 s (ReprintGuard) – Esc / ↑ / ↓ cancel. The Reprint button (mouse/touch)
    prints immediately. Card buttons never take keyboard focus, so Space can't "click" them.
"""

from __future__ import annotations

import time
from enum import Enum
from pathlib import Path
from typing import Dict, Optional

from PyQt6.QtCore import QEvent, QObject, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QFont
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
from ui.widgets import ltr, make_thumb


class QueueItemStatus(Enum):
    # [MagnetStudio] Hebrew labels. Originals: Incoming / Enhanced / Composed / Spooling / Printed / Failed
    INCOMING = ("התקבלה", ThemeColors.TEXT_SECONDARY, "rgba(173, 181, 189, 0.15)")
    ENHANCED = ("משופרת", ThemeColors.ACCENT_CYAN, "rgba(0, 210, 196, 0.15)")
    COMPOSED = ("מורכבת", "#9D4EDD", "rgba(157, 78, 221, 0.15)")
    SPOOLING = ("בהדפסה", ThemeColors.ACCENT_AMBER, "rgba(255, 183, 3, 0.15)")
    PRINTED = ("הודפסה", ThemeColors.ACCENT_MINT, "rgba(6, 214, 160, 0.15)")
    FAILED = ("נכשלה", ThemeColors.ACCENT_CORAL, "rgba(239, 71, 111, 0.15)")

    def __init__(self, label: str, fg_color: str, bg_color: str):
        self.label = label
        self.fg_color = fg_color
        self.bg_color = bg_color


REPRINT_CONFIRM_MS = 1500
REPRINT_WARNING = "⚠️ כבר הודפס! לחץ שוב [רווח] להדפסה חוזרת"


class ReprintGuard(QObject):
    """Double-tap confirmation for keyboard reprints.

    press(job_id) → True only for a second press on the same job within `window_ms`.
    The first press arms the guard; the timer (or cancel()) disarms it.
    """
    armed = pyqtSignal(str)       # job_id
    disarmed = pyqtSignal(str)    # job_id (timeout, cancel or confirm)

    def __init__(self, window_ms: int = REPRINT_CONFIRM_MS, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self.window_ms = window_ms
        self.armed_id: Optional[str] = None
        self._armed_at = 0.0
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.cancel)

    def is_armed(self, job_id: Optional[str] = None) -> bool:
        return self.armed_id is not None and (job_id is None or self.armed_id == job_id)

    def press(self, job_id: str) -> bool:
        within = (time.monotonic() - self._armed_at) * 1000 <= self.window_ms
        if self.is_armed(job_id) and within:
            self.cancel()
            return True
        self.cancel()
        self.armed_id, self._armed_at = job_id, time.monotonic()
        self._timer.start(self.window_ms)
        self.armed.emit(job_id)
        return False

    def cancel(self) -> None:
        self._timer.stop()
        if self.armed_id is not None:
            job_id, self.armed_id = self.armed_id, None
            self.disarmed.emit(job_id)


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
        self.printed = 0  # [MagnetStudio] magnets printed from this photo
        self.created = time.strftime("%H:%M:%S")

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
        # [MagnetStudio] app font (Hebrew-capable Heebo) instead of a hard-coded "Arial"
        title_font = QFont(self.font())
        title_font.setPointSize(11)
        title_font.setWeight(QFont.Weight.Bold)
        self.title_lbl.setFont(title_font)
        self.title_lbl.setStyleSheet(f"color: {ThemeColors.TEXT_PRIMARY};")
        self.title_lbl.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.title_lbl.setToolTip(self.photo_path)

        meta_layout = QHBoxLayout()
        meta_layout.setSpacing(8)

        # Status badge pill
        self.badge_lbl = QLabel()
        badge_font = QFont(self.font())
        badge_font.setPointSize(9)
        badge_font.setWeight(QFont.Weight.Bold)
        self.badge_lbl.setFont(badge_font)
        self.badge_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.badge_lbl.setFixedHeight(20)

        # Time label
        self.time_lbl = QLabel(self.created)
        self.time_lbl.setStyleSheet(f"color: {ThemeColors.TEXT_MUTED}; font-size: 11px;")
        # [MagnetStudio] long hints (reprint warning) must not widen the card past the panel
        self.time_lbl.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.time_lbl.setMinimumWidth(40)

        meta_layout.addWidget(self.badge_lbl)
        meta_layout.addWidget(self.time_lbl, 1)  # [MagnetStudio] takes the free space, never forces width

        info_layout.addWidget(self.title_lbl)
        info_layout.addLayout(meta_layout)
        layout.addLayout(info_layout, stretch=1)

        # 3. Action Buttons  [MagnetStudio] Hebrew: Inspect → תצוגה, +1 Copy → +1 עותק, Reprint → הדפס
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(6)

        self.btn_inspect = QPushButton("תצוגה")
        self.btn_inspect.setProperty("class", "action-btn")
        self.btn_inspect.setToolTip("הצג בתצוגה המקדימה")
        self.btn_inspect.clicked.connect(lambda: self.inspect_requested.emit(self.job_id))

        self.btn_copy = QPushButton(f"{ltr('+1')} עותק")
        self.btn_copy.setProperty("class", "action-btn")
        self.btn_copy.setToolTip("הדפס עותק נוסף")
        self.btn_copy.clicked.connect(lambda: self.copy_requested.emit(self.job_id))

        self.btn_reprint = QPushButton("הדפס")
        self.btn_reprint.setProperty("class", "action-btn")
        self.btn_reprint.setToolTip("הדפסה מהירה")
        self.btn_reprint.clicked.connect(lambda: self.reprint_requested.emit(self.job_id))

        for b in (self.btn_inspect, self.btn_copy, self.btn_reprint):
            b.setFocusPolicy(Qt.FocusPolicy.NoFocus)  # Space must never "click" a card button
        btn_layout.addWidget(self.btn_inspect)
        btn_layout.addWidget(self.btn_copy)
        btn_layout.addWidget(self.btn_reprint)
        layout.addLayout(btn_layout)

        self._blink_on = False
        self._blink = QTimer(self)
        self._blink.setInterval(220)
        self._blink.timeout.connect(self._toggle_blink)
        self.reprint_armed = False

    def _load_thumbnail(self) -> None:
        if self.photo_path and Path(self.photo_path).exists():
            try:  # [MagnetStudio] fast draft decode + EXIF rotation, rounded 70px
                from PIL import Image
                with Image.open(self.photo_path) as im:
                    im.verify()
                self.thumb_label.setPixmap(make_thumb(self.photo_path, 70))
                return
            except Exception:
                pass
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
        busy = status in (QueueItemStatus.ENHANCED, QueueItemStatus.COMPOSED, QueueItemStatus.SPOOLING)
        self.btn_reprint.setEnabled(not busy)

    # [MagnetStudio] selection + reprint confirmation visuals
    def set_selected(self, on: bool) -> None:
        self.setProperty("selected", on)
        self.style().unpolish(self)
        self.style().polish(self)

    def set_reprint_armed(self, on: bool) -> None:
        self.reprint_armed = on
        if on:
            self.badge_lbl.setText("  ⚠️ כבר הודפס!  ")
            self.badge_lbl.setStyleSheet(
                f"color: #071716; background-color: {ThemeColors.ACCENT_AMBER}; "
                f"border: 1px solid {ThemeColors.ACCENT_AMBER}; border-radius: 4px;")
            self.title_lbl.setText("לחץ שוב [רווח] להדפסה חוזרת")  # title line has the most room
            self.title_lbl.setStyleSheet(f"color: {ThemeColors.ACCENT_AMBER};")
            self._blink_on = False
            self._toggle_blink()
            self._blink.start()
        else:
            self._blink.stop()
            self.setStyleSheet("")
            self.title_lbl.setText(Path(self.photo_path).name if self.photo_path else f"Job #{self.job_id}")
            self.title_lbl.setStyleSheet(f"color: {ThemeColors.TEXT_PRIMARY};")
            self.update_status(self.status)
            self.set_printed(self.printed)

    def _toggle_blink(self) -> None:
        self._blink_on = not self._blink_on
        color = ThemeColors.ACCENT_AMBER if self._blink_on else ThemeColors.BORDER_SUBTLE
        self.setStyleSheet(f'QFrame[class="card"] {{ border: 2px solid {color}; }}')

    def set_printed(self, count: int) -> None:
        """[MagnetStudio] show how many magnets were printed from this photo."""
        self.printed = count
        self.time_lbl.setText(self.created + (f" · {ltr('×' + str(count))} הודפסו" if count else ""))


class QueuePanel(QWidget):
    """Top-level queue viewport with printer metrics and photo stream."""
    reprint_job = pyqtSignal(str)
    inspect_job = pyqtSignal(str)
    add_copy_job = pyqtSignal(str)
    hot_folder_toggle_requested = pyqtSignal()  # [MagnetStudio]
    keyboard_print = pyqtSignal(str, bool)       # [MagnetStudio] job_id, is_reprint
    selection_changed = pyqtSignal(str)          # [MagnetStudio]
    status_message = pyqtSignal(str)             # [MagnetStudio] text for the status bar

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._cards: Dict[str, QueueCardWidget] = {}
        self._order: list[str] = []          # display order, top → bottom
        self.selected_id: Optional[str] = None
        self._pulse_state = False
        self._total_prints = 0
        self.guard = ReprintGuard(parent=self)
        self.guard.armed.connect(lambda j: self._set_armed(j, True))
        self.guard.disarmed.connect(lambda j: self._set_armed(j, False))

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
        self.printer_title = QLabel("מדפסת")  # PRINTER
        self.printer_title.setStyleSheet(f"color: {ThemeColors.TEXT_MUTED}; font-size: 10px; font-weight: bold;")
        self.printer_value = QLabel("—")
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
        self.folder_chip.setCursor(Qt.CursorShape.PointingHandCursor)
        self.folder_chip.setToolTip("לחץ להפעלה / כיבוי של Hot Folder")
        self.folder_chip.installEventFilter(self)
        f_layout = QHBoxLayout(self.folder_chip)
        f_layout.setContentsMargins(14, 6, 14, 6)

        self.pulse_dot = QLabel("⚡")
        self.pulse_dot.setStyleSheet(f"color: {ThemeColors.TEXT_MUTED}; font-size: 14px;")
        self.folder_title = QLabel("HOT FOLDER")
        self.folder_title.setStyleSheet(f"color: {ThemeColors.TEXT_MUTED}; font-size: 10px; font-weight: bold;")
        self.folder_value = QLabel("כבוי")  # Inactive
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
        c_title = QLabel("סה״כ הדפסות")  # TOTAL PRINTS
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
        # [MagnetStudio] not started here – set_hot_folder(active=True) starts it

    def _toggle_pulse(self) -> None:
        self._pulse_state = not self._pulse_state
        color = ThemeColors.ACCENT_CYAN if self._pulse_state else ThemeColors.TEXT_MUTED
        self.pulse_dot.setStyleSheet(f"color: {color}; font-size: 14px;")

    def eventFilter(self, obj, event) -> bool:  # [MagnetStudio] clickable folder chip
        if obj is self.folder_chip and event.type() == QEvent.Type.MouseButtonRelease:
            self.hot_folder_toggle_requested.emit()
            return True
        return super().eventFilter(obj, event)

    def add_queue_card(
        self,
        job_id: str,
        photo_path: str,
        status: QueueItemStatus = QueueItemStatus.INCOMING,
        copies: int = 1,
    ) -> QueueCardWidget:
        card = QueueCardWidget(job_id=job_id, photo_path=photo_path, status=status, copies=copies)
        card.copy_requested.connect(self.add_copy_job.emit)
        card.reprint_requested.connect(self._on_reprint_button)
        card.inspect_requested.connect(self.inspect_job.emit)

        self._cards[job_id] = card
        self._order.insert(0, job_id)
        self.cards_layout.insertWidget(0, card)
        return card

    # ---------------------------------------------------- [MagnetStudio] keyboard + guard
    def _on_reprint_button(self, job_id: str) -> None:
        """Mouse / touch on Reprint is deliberate → print immediately, no confirmation."""
        self.guard.cancel()
        self.reprint_job.emit(job_id)

    def select(self, job_id: Optional[str]) -> None:
        if job_id == self.selected_id or (job_id is not None and job_id not in self._cards):
            return
        if self.selected_id in self._cards:
            self._cards[self.selected_id].set_selected(False)
        self.selected_id = job_id
        if job_id is not None:
            card = self._cards[job_id]
            card.set_selected(True)
            self.scroll_area.ensureWidgetVisible(card, 0, 8)
            self.selection_changed.emit(job_id)

    def select_next(self, delta: int = 1) -> Optional[str]:
        if not self._order:
            return None
        if self.selected_id not in self._order:
            self.select(self._order[0])
        else:
            i = max(0, min(len(self._order) - 1, self._order.index(self.selected_id) + delta))
            self.select(self._order[i])
        return self.selected_id

    def _set_armed(self, job_id: str, on: bool) -> None:
        card = self._cards.get(job_id)
        if card is not None:
            card.set_reprint_armed(on)
        self.status_message.emit(REPRINT_WARNING if on else "")

    def handle_key(self, key: int) -> bool:
        """Space / ↑ / ↓ / Esc for the queue. Returns True when the key was used."""
        if key in (Qt.Key.Key_Up, Qt.Key.Key_Down):
            self.guard.cancel()  # moving away cancels a pending reprint
            self.select_next(-1 if key == Qt.Key.Key_Up else 1)
            return True
        if key == Qt.Key.Key_Escape:
            if self.guard.is_armed():
                self.guard.cancel()
                self.status_message.emit("ההדפסה החוזרת בוטלה")
                return True
            return False
        if key != Qt.Key.Key_Space:
            return False
        if self.selected_id is None:
            self.select_next(0)
            if self.selected_id is None:
                return True
        job_id = self.selected_id
        card = self._cards[job_id]
        if card.status in (QueueItemStatus.ENHANCED, QueueItemStatus.COMPOSED, QueueItemStatus.SPOOLING):
            self.status_message.emit("התמונה כבר בדרך למדפסת")
            return True
        if card.status == QueueItemStatus.PRINTED:
            if not self.guard.press(job_id):
                return True  # first tap: warning shown, nothing printed
            card.update_status(QueueItemStatus.SPOOLING)
            self.keyboard_print.emit(job_id, True)
        else:
            self.guard.cancel()
            self.keyboard_print.emit(job_id, False)
        self.select_next(1)  # auto-advance
        return True

    def update_item_status(self, job_id: str, status: QueueItemStatus, count_printed: int = 1) -> None:
        if job_id in self._cards:
            self._cards[job_id].update_status(status)
            if status == QueueItemStatus.PRINTED:
                self.increment_print_counter(count_printed)

    def set_printer_state(self, name: str, online: bool, state: Optional[str] = None) -> None:
        # [MagnetStudio] optional state: "busy" (printing) / "test" (PDF dry run)
        fm = self.printer_value.fontMetrics()
        short = fm.elidedText(name, Qt.TextElideMode.ElideMiddle, 120)
        self.printer_value.setToolTip(name)
        if state == "busy":
            color, text = ThemeColors.ACCENT_CYAN, f"מדפיסה ({short})"
        elif state == "test":
            color, text = ThemeColors.ACCENT_AMBER, "מצב בדיקה (PDF)"
        elif online:
            color, text = ThemeColors.ACCENT_MINT, f"מוכנה ({short})"   # Ready
        else:
            color, text = ThemeColors.ACCENT_CORAL, f"לא זמינה ({short})"  # Offline
        self.printer_dot.setStyleSheet(f"color: {color}; font-size: 16px;")
        self.printer_value.setText(text)

    def set_hot_folder(self, folder_path: str, active: bool = True) -> None:
        folder_name = Path(folder_path).name or folder_path
        self.folder_value.setText(f"מאזין: {folder_name}" if active else "כבוי")  # Watching / Inactive
        self.folder_chip.setToolTip(f"מאזין לתיקייה: {folder_path}" if active else "לחץ להפעלת Hot Folder")
        if not active:
            self.timer.stop()
            self.pulse_dot.setStyleSheet(f"color: {ThemeColors.TEXT_MUTED}; font-size: 14px;")
        elif not self.timer.isActive():
            self.timer.start(1000)

    def increment_print_counter(self, amount: int = 1) -> None:
        self._total_prints += amount
        self.count_lbl.setText(f"{self._total_prints:,}")

    def set_total_prints(self, total: int) -> None:
        """[MagnetStudio] seed the counter with the persisted total."""
        self._total_prints = int(total)
        self.count_lbl.setText(f"{self._total_prints:,}")

    @property
    def cards(self) -> Dict[str, QueueCardWidget]:
        return self._cards
