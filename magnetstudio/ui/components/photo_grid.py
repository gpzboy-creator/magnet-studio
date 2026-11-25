"""Photo grid (MagnetOti-style main view): one card per photo, showing the finished magnet (frame on),
with ☆ favourite, a status badge and a copies stepper (− n +).

The grid only displays and reports user actions (signals); copies / favourites live in the cards and
the window reads them when printing. Card order = arrival order. Reflows on resize.
"""
from __future__ import annotations

from PyQt6.QtCore import QSize, Qt, pyqtSignal
from PyQt6.QtGui import QImage, QPixmap
from PyQt6.QtWidgets import (QFrame, QGridLayout, QHBoxLayout, QLabel, QMenu, QPushButton, QScrollArea,
                             QSizePolicy, QToolButton, QVBoxLayout, QWidget)

from magnetstudio.ui.widgets import ltr


class PhotoCard(QFrame):
    copies_changed = pyqtSignal(str, int)
    clicked = pyqtSignal(str)
    double_clicked = pyqtSignal(str)
    star_toggled = pyqtSignal(str, bool)
    remove_requested = pyqtSignal(str)

    def __init__(self, item_id: str, name: str, width: int = 260, parent=None):
        super().__init__(parent)
        self.item_id = item_id
        self.name = name
        self._copies = 0
        self._pix: QPixmap | None = None
        self.setObjectName("PhotoCard")
        self.setProperty("selected", False)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip(name)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 8, 8, 8)
        lay.setSpacing(6)

        self.thumb = QLabel("…")
        self.thumb.setObjectName("CardThumb")
        self.thumb.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(self.thumb, 1)

        # overlays on the photo (positioned in resizeEvent)
        self.star = QToolButton(self.thumb)
        self.star.setObjectName("CardOverlay")
        self.star.setCheckable(True)
        self.star.setText("☆")
        self.star.setToolTip("מועדף")
        self.star.toggled.connect(self._on_star)
        self.badge = QLabel("", self.thumb)
        self.badge.setObjectName("CardBadge")
        self.badge.hide()

        # copies stepper
        row = QHBoxLayout()
        row.setSpacing(4)
        row.addStretch()
        self.minus = QToolButton()
        self.minus.setObjectName("Stepper")
        self.minus.setText("−")
        self.minus.setAutoRepeat(True)
        self.minus.clicked.connect(lambda: self.set_copies(self._copies - 1, emit=True))
        self.count = QLabel("0")
        self.count.setObjectName("StepperValue")
        self.count.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.count.setMinimumWidth(28)
        self.plus = QToolButton()
        self.plus.setObjectName("Stepper")
        self.plus.setText("+")
        self.plus.setAutoRepeat(True)
        self.plus.clicked.connect(lambda: self.set_copies(self._copies + 1, emit=True))
        for w in (self.plus, self.count, self.minus):      # RTL: + on the right, like MagnetOti
            w.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            row.addWidget(w)
        row.addStretch()
        lay.addLayout(row)
        self.star.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.set_width(width)

    # ---------------------------------------------------------------- api
    def set_width(self, w: int) -> None:
        self.setFixedWidth(w)
        self.thumb.setFixedHeight(int(w * 0.92))
        self._rescale()

    def set_image(self, img: QImage) -> None:
        self._pix = QPixmap.fromImage(img)
        self._rescale()

    def set_copies(self, n: int, emit: bool = False) -> None:
        n = max(0, min(99, int(n)))
        if n == self._copies:
            return
        self._copies = n
        self.count.setText(str(n))
        self.setProperty("has-copies", n > 0)
        self.style().unpolish(self)
        self.style().polish(self)
        if emit:
            self.copies_changed.emit(self.item_id, n)

    def copies(self) -> int:
        return self._copies

    def is_starred(self) -> bool:
        return self.star.isChecked()

    def set_selected(self, on: bool) -> None:
        self.setProperty("selected", on)
        self.style().unpolish(self)
        self.style().polish(self)

    def set_badge(self, text: str, color: str = "") -> None:
        self.badge.setText(ltr(text) if text else "")
        self.badge.setVisible(bool(text))
        self.badge.setStyleSheet(f"background: {color};" if color else "")
        self.badge.adjustSize()
        self._place_overlays()

    # ---------------------------------------------------------------- internals
    def _on_star(self, on: bool) -> None:
        self.star.setText("★" if on else "☆")
        self.star_toggled.emit(self.item_id, on)

    def _rescale(self) -> None:
        if self._pix is not None:
            self.thumb.setPixmap(self._pix.scaled(self.thumb.size() - QSize(4, 4),
                                                  Qt.AspectRatioMode.KeepAspectRatio,
                                                  Qt.TransformationMode.SmoothTransformation))
        self._place_overlays()

    def _place_overlays(self) -> None:
        self.star.adjustSize()
        # RTL widget: x=0 is the visual left; MagnetOti has ☆ top-left and the badge bottom-right
        self.star.move(6, 6)
        self.badge.move(max(0, self.thumb.width() - self.badge.width() - 6),
                        max(0, self.thumb.height() - self.badge.height() - 6))

    def resizeEvent(self, e) -> None:
        super().resizeEvent(e)
        self._rescale()

    def mouseReleaseEvent(self, e) -> None:
        if e.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self.item_id)
        super().mouseReleaseEvent(e)

    def mouseDoubleClickEvent(self, e) -> None:
        self.double_clicked.emit(self.item_id)

    def contextMenuEvent(self, e) -> None:
        menu = QMenu(self)
        menu.addAction("הצג בגדול", lambda: self.double_clicked.emit(self.item_id))
        menu.addAction("הסר מהרשימה", lambda: self.remove_requested.emit(self.item_id))
        menu.exec(e.globalPos())


class PhotoGrid(QScrollArea):
    """Scrollable, reflowing grid of PhotoCards with an empty-state drop zone."""
    upload_clicked = pyqtSignal()
    copies_changed = pyqtSignal(str, int)
    card_clicked = pyqtSignal(str)
    card_double_clicked = pyqtSignal(str)
    remove_requested = pyqtSignal(str)
    star_toggled = pyqtSignal(str, bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("PhotoGrid")
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.cards: dict[str, PhotoCard] = {}
        self.order: list[str] = []
        self.selected_id: str | None = None
        self.card_width = 260
        self._cols = 0

        self.inner = QWidget()
        self.inner.setObjectName("GridInner")
        self.grid = QGridLayout(self.inner)
        self.grid.setContentsMargins(16, 16, 16, 16)
        self.grid.setHorizontalSpacing(16)
        self.grid.setVerticalSpacing(16)
        self.grid.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignHCenter)

        # empty state – like MagnetOti: a big drop zone and an upload button
        self.empty = QWidget()
        el = QVBoxLayout(self.empty)
        el.setAlignment(Qt.AlignmentFlag.AlignCenter)
        zone = QFrame()
        zone.setObjectName("DropZone")
        zone.setFixedSize(420, 260)
        zl = QVBoxLayout(zone)
        zl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon = QLabel("🖼")
        icon.setObjectName("DropIcon")
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title = QLabel("גררו תמונות לכאן")
        title.setObjectName("DropTitle")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        sub = QLabel("או לחצו על הכפתור למטה")
        sub.setObjectName("Dim")
        sub.setAlignment(Qt.AlignmentFlag.AlignCenter)
        for w in (icon, title, sub):
            zl.addWidget(w)
        up = QPushButton("📂  העלאת תמונות")
        up.setObjectName("UploadBig")
        up.setFixedWidth(420)
        up.clicked.connect(self.upload_clicked)
        foot = QLabel("<b>MagnetStudio</b><br>הלבשת מסגרות והדפסת מגנטים לאירועים")
        foot.setObjectName("Dim")
        foot.setAlignment(Qt.AlignmentFlag.AlignCenter)
        el.addWidget(zone, 0, Qt.AlignmentFlag.AlignHCenter)
        el.addSpacing(18)
        el.addWidget(up, 0, Qt.AlignmentFlag.AlignHCenter)
        el.addSpacing(24)
        el.addWidget(foot)

        self.stack = QWidget()
        sl = QVBoxLayout(self.stack)
        sl.setContentsMargins(0, 0, 0, 0)
        sl.addWidget(self.empty, 1)
        sl.addWidget(self.inner)
        self.inner.hide()
        self.setWidget(self.stack)

    # ---------------------------------------------------------------- cards
    def add_card(self, item_id: str, name: str) -> PhotoCard:
        card = PhotoCard(item_id, name, self.card_width)
        card.copies_changed.connect(self.copies_changed)
        card.clicked.connect(self._on_clicked)
        card.double_clicked.connect(self.card_double_clicked)
        card.remove_requested.connect(self.remove_requested)
        card.star_toggled.connect(self.star_toggled)
        self.cards[item_id] = card
        self.order.append(item_id)
        self.empty.hide()
        self.inner.show()
        self._reflow(force=True)
        return card

    def remove_card(self, item_id: str) -> None:
        card = self.cards.pop(item_id, None)
        if card is None:
            return
        self.order.remove(item_id)
        self.grid.removeWidget(card)
        card.deleteLater()
        if self.selected_id == item_id:
            self.selected_id = None
        if not self.order:
            self.inner.hide()
            self.empty.show()
        self._reflow(force=True)

    def select(self, item_id: str | None) -> None:
        if self.selected_id in self.cards:
            self.cards[self.selected_id].set_selected(False)
        self.selected_id = item_id if item_id in self.cards else None
        if self.selected_id:
            card = self.cards[self.selected_id]
            card.set_selected(True)
            self.ensureWidgetVisible(card, 20, 20)

    def set_card_width(self, w: int) -> None:
        self.card_width = max(140, min(520, int(w)))
        for c in self.cards.values():
            c.set_width(self.card_width)
        self._reflow(force=True)

    def total_copies(self) -> int:
        return sum(c.copies() for c in self.cards.values())

    def batch(self) -> list[tuple[str, int]]:
        """(item id, copies) for every card with copies > 0, in grid order."""
        return [(i, self.cards[i].copies()) for i in self.order if self.cards[i].copies() > 0]

    # ---------------------------------------------------------------- layout
    def _on_clicked(self, item_id: str) -> None:
        self.select(item_id)
        self.card_clicked.emit(item_id)

    def _reflow(self, force: bool = False) -> None:
        avail = self.viewport().width() - 32
        cols = max(1, (avail + 16) // (self.card_width + 16))
        if cols == self._cols and not force:
            return
        self._cols = cols
        for i in reversed(range(self.grid.count())):
            self.grid.takeAt(i)
        for n, item_id in enumerate(self.order):
            self.grid.addWidget(self.cards[item_id], n // cols, n % cols)

    def resizeEvent(self, e) -> None:
        super().resizeEvent(e)
        self._reflow()

    def sizeHint(self) -> QSize:
        return QSize(800, 600)


def card_policy() -> QSizePolicy:
    return QSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
