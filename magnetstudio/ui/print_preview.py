"""Print preview (MagnetOti-style): every printer page, click a page to include / exclude it, all pages or
a range, zoom, a summary – then print the selected pages or save them as JPEG files."""
from __future__ import annotations

from PIL import Image
from PIL.ImageQt import ImageQt
from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import (QButtonGroup, QDialog, QFrame, QGridLayout, QHBoxLayout, QLabel, QPushButton,
                             QRadioButton, QScrollArea, QSlider, QSpinBox, QVBoxLayout, QWidget)

from magnetstudio.ui.widgets import ltr


class PageTile(QFrame):
    toggled = pyqtSignal(int)

    def __init__(self, index: int, total: int, pix: QPixmap, parent=None):
        super().__init__(parent)
        self.index, self.total, self._pix = index, total, pix
        self.setObjectName("PageTile")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 8, 8, 8)
        lay.setSpacing(6)
        self.caption = QLabel()
        self.caption.setObjectName("PageCaption")
        self.caption.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.image = QLabel()
        self.image.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(self.caption)
        lay.addWidget(self.image)
        self.check = QLabel("✓", self.image)
        self.check.setObjectName("PageCheck")
        self.check.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.check.setFixedSize(28, 28)
        self.selected = True
        self.set_height(380)
        self.set_selected(True)

    def set_height(self, h: int) -> None:
        pix = self._pix.scaledToHeight(h, Qt.TransformationMode.SmoothTransformation)
        self.image.setPixmap(pix)
        self.image.setFixedSize(pix.size())
        self.check.move(pix.width() - 34, 6)

    def set_selected(self, on: bool) -> None:
        self.selected = on
        self.check.setVisible(on)
        self.caption.setText(f"דף {self.index + 1} מתוך {self.total}" + (" – נבחר להדפסה" if on else " – לא יודפס"))
        self.setProperty("selected", on)
        self.style().unpolish(self)
        self.style().polish(self)

    def mouseReleaseEvent(self, e) -> None:
        if e.button() == Qt.MouseButton.LeftButton:
            self.toggled.emit(self.index)


class PrintPreviewDialog(QDialog):
    """info: printer, paper (label), size_mm (w, h), layout ("2×2"), dpi."""

    def __init__(self, pages: list[Image.Image], owners: list[list[str]], info: dict, parent=None):
        super().__init__(parent)
        self.setWindowTitle("תצוגה מקדימה להדפסה")
        self.setObjectName("PreviewDialog")
        self.pages, self.owners, self.info = pages, owners, info
        self.action: str | None = None           # "print" | "jpeg"
        self.resize(1200, 820)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # header
        head = QFrame()
        head.setObjectName("PreviewHead")
        hl = QHBoxLayout(head)
        hl.setContentsMargins(20, 12, 20, 12)
        title = QLabel("🖨  תצוגה מקדימה להדפסה")
        title.setObjectName("PanelHeading")
        self.sel_chip = QLabel()
        self.sel_chip.setObjectName("CounterChip")
        self.sel_chip.setProperty("accent", True)
        hl.addWidget(title)
        hl.addStretch()
        hl.addWidget(self.sel_chip)
        root.addWidget(head)

        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)
        root.addLayout(body, 1)

        # side panel (right in RTL)
        side = QFrame()
        side.setObjectName("PrintPanel")
        side.setFixedWidth(300)
        sl = QVBoxLayout(side)
        sl.setContentsMargins(16, 16, 16, 16)
        sl.setSpacing(10)
        self.all_radio = QRadioButton("כל הדפים")
        self.range_radio = QRadioButton("טווח עמודים")
        grp = QButtonGroup(self)
        grp.addButton(self.all_radio)
        grp.addButton(self.range_radio)
        self.all_radio.setChecked(True)
        self.from_box, self.to_box = QSpinBox(), QSpinBox()
        for b in (self.from_box, self.to_box):
            b.setRange(1, max(1, len(pages)))
        self.to_box.setValue(len(pages))
        self.tiles: list[PageTile] = []          # built below; signals connected after they exist
        rng = QHBoxLayout()
        rng.addWidget(QLabel("מ-"))
        rng.addWidget(self.from_box)
        rng.addWidget(QLabel("עד"))
        rng.addWidget(self.to_box)
        sl.addWidget(self.all_radio)
        sl.addWidget(self.range_radio)
        sl.addLayout(rng)
        for label, value in (("מדפסת", info.get("printer", "")), ("גודל נייר", info.get("paper", "")),
                             ("פריסה", info.get("layout", "")), ("איכות", f"{info.get('dpi', 300)} DPI")):
            box = QFrame()
            box.setObjectName("InfoRow")
            bl = QVBoxLayout(box)
            bl.setContentsMargins(10, 6, 10, 6)
            bl.setSpacing(0)
            k = QLabel(label)
            k.setObjectName("Dim")
            v = QLabel(ltr(str(value)))
            v.setObjectName("InfoValue")
            bl.addWidget(k)
            bl.addWidget(v)
            sl.addWidget(box)
        self.summary = QLabel()
        self.summary.setObjectName("SummaryBox")
        self.summary.setWordWrap(True)
        sl.addWidget(self.summary)
        sl.addStretch()
        body.addWidget(side)

        # pages
        center = QVBoxLayout()
        center.setSpacing(0)
        bar = QFrame()
        bar.setObjectName("ToolRow")
        bl = QHBoxLayout(bar)
        bl.setContentsMargins(16, 6, 16, 6)
        hint = QLabel("👆 לחצו על דף כדי לבחור או לבטל אותו")
        hint.setObjectName("Dim")
        self.zoom = QSlider(Qt.Orientation.Horizontal)
        self.zoom.setRange(200, 900)
        self.zoom.setValue(380)
        self.zoom.setFixedWidth(260)
        self.zoom.valueChanged.connect(self._zoom)
        bl.addWidget(hint)
        bl.addStretch()
        bl.addWidget(QLabel("🔍"))
        bl.addWidget(self.zoom)
        center.addWidget(bar)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setObjectName("PhotoGrid")
        inner = QWidget()
        inner.setObjectName("GridInner")
        self.grid = QGridLayout(inner)
        self.grid.setContentsMargins(20, 20, 20, 20)
        self.grid.setSpacing(18)
        self.grid.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignHCenter)
        for i, page in enumerate(pages):
            small = page.copy()
            small.thumbnail((900, 900), Image.Resampling.LANCZOS)
            tile = PageTile(i, len(pages), QPixmap.fromImage(ImageQt(small.convert("RGB"))))
            tile.toggled.connect(self._toggle)
            self.tiles.append(tile)
        self.scroll.setWidget(inner)
        center.addWidget(self.scroll, 1)
        body.addLayout(center, 1)

        # footer
        foot = QFrame()
        foot.setObjectName("PreviewFoot")
        fl = QHBoxLayout(foot)
        fl.setContentsMargins(20, 12, 20, 12)
        self.print_btn = QPushButton()
        self.print_btn.setProperty("class", "primary")
        self.print_btn.clicked.connect(lambda: self._finish("print"))
        jpeg = QPushButton("⬇  שמירה כ-JPEG…")
        jpeg.clicked.connect(lambda: self._finish("jpeg"))
        cancel = QPushButton("ביטול")
        cancel.setProperty("ghost", True)
        cancel.clicked.connect(self.reject)
        fl.addWidget(self.print_btn)
        fl.addWidget(jpeg)
        fl.addStretch()
        fl.addWidget(cancel)
        root.addWidget(foot)
        for b in (self.from_box, self.to_box):
            b.valueChanged.connect(self._apply_range)
        self.all_radio.toggled.connect(self._apply_range)
        self._layout_tiles()
        self._update()

    # ---------------------------------------------------------------- selection
    def selected_indices(self) -> list[int]:
        return [t.index for t in self.tiles if t.selected]

    def selected_pages(self) -> list[Image.Image]:
        return [self.pages[i] for i in self.selected_indices()]

    def selected_owners(self) -> list[str]:
        return [o for i in self.selected_indices() for o in self.owners[i]]

    def _toggle(self, index: int) -> None:
        self.tiles[index].set_selected(not self.tiles[index].selected)
        self._update()

    def _apply_range(self, *_):
        lo, hi = sorted((self.from_box.value(), self.to_box.value()))
        for t in self.tiles:
            t.set_selected(self.all_radio.isChecked() or lo <= t.index + 1 <= hi)
        self._update()

    def _zoom(self, h: int) -> None:
        for t in self.tiles:
            t.set_height(h)
        self._layout_tiles()

    def _layout_tiles(self) -> None:
        for i in reversed(range(self.grid.count())):
            self.grid.takeAt(i)
        width = max(1, self.tiles[0].image.width() + 40) if self.tiles else 1
        cols = max(1, (self.scroll.viewport().width() - 40) // width)
        for n, t in enumerate(self.tiles):
            self.grid.addWidget(t, n // cols, n % cols)

    def resizeEvent(self, e) -> None:
        super().resizeEvent(e)
        QTimer.singleShot(0, self._layout_tiles)      # after the scroll area got its new width

    def showEvent(self, e) -> None:
        super().showEvent(e)
        QTimer.singleShot(0, self._layout_tiles)

    def _update(self) -> None:
        n, total = len(self.selected_indices()), len(self.pages)
        magnets = len([o for o in self.selected_owners()])
        self.sel_chip.setText(ltr(f"✓ {n} מתוך {total} דפים נבחרו"))
        w, h = self.info.get("size_mm") or (0, 0)
        self.summary.setText(
            "<b>סיכום</b><br>"
            f"סה״כ דפים: {total}<br>דפים שנבחרו: {n}<br>מגנטים בדפים שנבחרו: {magnets}"
            + (f"<br>גודל דף: {w:g}×{h:g} מ״מ" if w else ""))
        self.print_btn.setText(f"🖨  הדפס {n} דפים")
        self.print_btn.setEnabled(n > 0)

    def _finish(self, action: str) -> None:
        if not self.selected_indices():
            return
        self.action = action
        self.accept()
