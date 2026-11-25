"""Main window – MagnetOti-style layout (light by default), plus the live print queue.

┌ TopBar: MagnetStudio · ⚙ 🎨 ✨ · zoom ·················· sheets printed · cost · reset event ┐
├ ToolRow: upload · size · enhancer · frames: [template ▾] portrait PNG · landscape PNG · none · ⚡ live ┤
│ Print panel (right)  │  Photo grid: card = finished magnet + ☆ + copies (− n +)  │ Live queue (left, │
│ printer · paper ·    │                                                           │ optional)         │
│ rows × cols · marks  │                                                           │                   │
│ margins · 🖨 print   │                                                           │                   │
└ Status: ready · photos/copies · exposure · contrast · sharpness · today N sheets · version ─────────┘
Layout is right-to-left (Hebrew). Printing "all" = one sheet job with every card's copies.
"""
import datetime
import logging
import math
import shutil
from pathlib import Path

from PIL.ImageQt import ImageQt
from PyQt6.QtCore import QEvent, QObject, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QAction, QPixmap
from PyQt6.QtWidgets import (QAbstractSpinBox, QApplication, QProgressDialog, QCheckBox, QComboBox, QDialog, QDoubleSpinBox,
                             QFileDialog, QFrame, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPlainTextEdit, QProgressBar, QPushButton, QScrollArea, QSlider,
                             QSpinBox, QSplitter, QTextEdit, QToolButton, QVBoxLayout, QWidget,
                             QMainWindow)

from magnetstudio import __version__, paths
from magnetstudio.core.framer import is_template, make_enhance_filter, render_magnet
from magnetstudio.core.layout import auto_grid, plan_grid
from magnetstudio.core.settings import save_settings
from magnetstudio.core.sizes import MAGNET_SIZES, PAPER_SIZES, get_size
from magnetstudio.core.templates import load_template
from magnetstudio.core.watcher import FolderWatcher
from magnetstudio.services.print_queue import PrintQueueController, QueueItem, Stage
from magnetstudio.services.page_builder import PageBuilder
from magnetstudio.services.printer import (DRY_RUN_PRINTER, PrintJob, PrintMode, get_available_printers,
                                          is_dry_run, is_printer_available, media_size_mm)
from magnetstudio.services.thumbnails import ThumbnailRenderer, ThumbParams
from magnetstudio.ui.components.photo_grid import PhotoGrid
from magnetstudio.ui.components.queue_panel import QueueItemStatus, QueuePanel
from magnetstudio.ui.designer import TemplateDesigner
from magnetstudio.ui.print_preview import PrintPreviewDialog
from magnetstudio.ui.settings_dialog import SettingsDialog
from magnetstudio.ui.theme import ThemeColors
from magnetstudio.ui.toast import Toast
from magnetstudio.ui.widgets import ltr

log = logging.getLogger(__name__)

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp"}



def frame_files() -> list[Path]:
    """Frames for the picker: the user's templates, then the bundled samples (user wins on a name
    clash). JSON templates first, then ready PNG overlays."""
    seen: dict[str, Path] = {}
    for d in paths.template_dirs():
        if d.is_dir():
            for f in d.iterdir():
                if f.suffix.lower() in (".json", ".png") and not f.name.startswith(("_", ".")):
                    seen.setdefault(f.name, f)
    return sorted(seen.values(), key=lambda f: (f.suffix.lower() != ".json", f.stem.lower()))

class _WatcherBridge(QObject):
    """watchdog calls back on its own thread; this hops the event to the GUI thread."""
    new_photo = pyqtSignal(str)


def _section(title: str) -> QLabel:
    lbl = QLabel(title)
    lbl.setObjectName("PanelTitle")
    return lbl


def _dim(text: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setObjectName("Dim")
    return lbl


def _field(label: str, widget: QWidget) -> QVBoxLayout:
    box = QVBoxLayout()
    box.setSpacing(4)
    lbl = QLabel(label)
    lbl.setObjectName("Dim")
    box.addWidget(lbl)
    box.addWidget(widget)
    return box


class MainWindow(QMainWindow):
    def __init__(self, settings: dict):
        super().__init__()
        self.settings = settings
        self.photo_path: str | None = None
        self._designer: TemplateDesigner | None = None
        # the print queue's state lives in the controller; this window only displays it
        self.queue = PrintQueueController(self._job_for_item, int(settings.get("print_count_total", 0)), parent=self)
        self._watcher: FolderWatcher | None = None
        self._bridge = _WatcherBridge()
        self._bridge.new_photo.connect(self._on_new_photo)
        self.thumbs = ThumbnailRenderer(self)
        self.thumbs.ready.connect(self._on_thumb)
        self.thumbs.failed.connect(lambda item_id, msg: self.grid.cards.get(item_id) and
                                   self.grid.cards[item_id].set_badge("שגיאה", ThemeColors.ACCENT_CORAL))
        self._rethumb_timer = QTimer(self, singleShot=True, interval=350, timeout=self._rerender_thumbs)
        self.setAcceptDrops(True)

        self.setWindowTitle("MagnetStudio")
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.resize(1440, 880)
        self._roll_today()
        self._build_ui()
        self.toast = Toast(self)
        self._connect_queue()
        self._refresh_printers()
        self._update_media()
        self.queue_panel.set_total_prints(int(self.settings.get("print_count_total", 0)))
        self._update_counters()
        self._update_summary()
        self._printer_timer = QTimer(self, interval=5000, timeout=self._update_printer_chip)
        self._printer_timer.start()
        # keyboard control of the queue (Space / ↑ / ↓ / Esc) wherever focus is in this window
        QApplication.instance().installEventFilter(self)

    # ================================================================ UI
    def _build_ui(self) -> None:
        self._build_top_bar()
        self._build_tool_row()
        panel = self._build_print_panel()

        # ---- photo grid (center)
        self.grid = PhotoGrid()
        self.grid.upload_clicked.connect(self._open_photo)
        self.grid.card_clicked.connect(self._select_item)
        self.grid.card_double_clicked.connect(self._show_large)
        self.grid.copies_changed.connect(lambda *_: self._update_summary())
        self.grid.remove_requested.connect(self._remove_photo)
        self.grid.set_card_width(int(self.settings.get("card_width", 250)))

        # ---- live queue (left side in RTL): status chips + cards (ui/components/queue_panel.py)
        self.queue_panel = QueuePanel()
        self.queue_panel.setMinimumWidth(420)
        self.queue_panel.add_copy_job.connect(self._add_copy)
        self.queue_panel.reprint_job.connect(self._print_item)
        self.queue_panel.inspect_job.connect(self._select_item)
        self.queue_panel.hot_folder_toggle_requested.connect(lambda: self.auto_print.toggle())
        self.queue_panel.selection_changed.connect(self._select_item)
        self.queue_panel.keyboard_print.connect(self._on_keyboard_print)
        self.queue_panel.status_message.connect(
            lambda msg: self.statusBar().showMessage(msg, 4000) if msg else self.statusBar().clearMessage())
        self.queue_panel.setVisible(bool(self.settings.get("show_live_queue", False)))

        split = QSplitter(Qt.Orientation.Horizontal)
        split.setChildrenCollapsible(False)
        split.setHandleWidth(1)
        split.addWidget(panel)
        split.addWidget(self.grid)
        split.addWidget(self.queue_panel)
        split.setStretchFactor(1, 1)
        split.setSizes([330, 900, 460])

        root = QWidget()
        rl = QVBoxLayout(root)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.setSpacing(0)
        rl.addWidget(self.top_bar)
        rl.addWidget(self.tool_row)
        rl.addWidget(split, 1)
        self.setCentralWidget(root)
        self._build_status_bar()

    def _build_top_bar(self) -> None:
        bar = QFrame()
        bar.setObjectName("TopBar")
        bar.setFixedHeight(60)
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(16, 8, 16, 8)
        lay.setSpacing(8)

        settings_act = QAction("⚙", self, toolTip="הגדרות", triggered=self._open_settings)
        designer_act = QAction("🎨", self, toolTip="עורך מסגרות ותבניות", triggered=self._open_designer)
        for act in (settings_act, designer_act):
            btn = QToolButton()
            btn.setDefaultAction(act)
            btn.setObjectName("IconBtn")
            lay.addWidget(btn)
        zoom = QFrame()
        zoom.setObjectName("ZoomBox")
        zl = QHBoxLayout(zoom)
        zl.setContentsMargins(6, 0, 6, 0)
        zl.setSpacing(2)
        for text, delta, tip in (("🔍+", 40, "כרטיסים גדולים יותר"), ("🔍−", -40, "כרטיסים קטנים יותר")):
            b = QToolButton()
            b.setText(text)
            b.setObjectName("IconBtn")
            b.setToolTip(tip)
            b.clicked.connect(lambda _=False, d=delta: self._zoom_cards(d))
            zl.addWidget(b)
        lay.addWidget(zoom)

        lay.addStretch()
        title = QLabel("MAGNETSTUDIO")
        title.setObjectName("BrandTitle")
        lay.addWidget(title)
        lay.addStretch()

        self.reset_btn = QPushButton("↻  איפוס אירוע")
        self.reset_btn.setProperty("ghost", True)
        self.reset_btn.setToolTip("מאפס את מוני האירוע (דפים ועלות) – המונה הכללי נשמר")
        self.reset_btn.clicked.connect(self._reset_event)
        self.cost_chip = QPushButton()
        self.cost_chip.setObjectName("CounterChip")
        self.cost_chip.setProperty("accent", True)
        self.cost_chip.setToolTip("עלות האירוע – העלות לדף נקבעת בהגדרות")
        self.cost_chip.clicked.connect(self._open_settings)
        self.sheets_chip = QLabel()
        self.sheets_chip.setObjectName("CounterChip")
        for w in (self.reset_btn, self.cost_chip, self.sheets_chip):
            lay.addWidget(w)
        self.top_bar = bar

    def _build_tool_row(self) -> None:
        row = QFrame()
        row.setObjectName("ToolRow")
        lay = QHBoxLayout(row)
        lay.setContentsMargins(16, 8, 16, 8)
        lay.setSpacing(8)

        self.size_box = QComboBox()
        for key, size in MAGNET_SIZES.items():
            self.size_box.addItem(f"⛶  {size.label}", key)
        self.size_box.setCurrentIndex(max(0, self.size_box.findData(self.settings["magnet_size"])))
        self.size_box.currentIndexChanged.connect(self._on_size_changed)
        self.size_box.setObjectName("SizeChip")

        self.enhance_act = QAction("✨ שיפור להדפסה", self, checkable=True)
        self.enhance_act.setToolTip("Fast AI Enhancer – הרמת צללים ורוויה מותאמת להדפסה, לפני הלבשת המסגרת")
        self.enhance_act.setChecked(bool(self.settings.get("enhance")))
        self.enhance_act.toggled.connect(self._toggle_enhance)
        enhance_btn = QToolButton()
        enhance_btn.setDefaultAction(self.enhance_act)

        frames_lbl = QLabel("מסגרות:")
        frames_lbl.setObjectName("Dim")
        self.frame_box = QComboBox()
        self.frame_box.setMinimumWidth(170)
        self._reload_frames()
        self.frame_box.currentIndexChanged.connect(self._on_frame_changed)
        self.portrait_btn = self._frame_chip("מסגרת אורך", "portrait")
        self.landscape_btn = self._frame_chip("מסגרת רוחב", "landscape")
        none_btn = QPushButton("ללא מסגרת")
        none_btn.setProperty("chip", True)
        none_btn.clicked.connect(self._clear_frames)

        self.live_btn = QPushButton("⚡ תור חי")
        self.live_btn.setProperty("chip", True)
        self.live_btn.setCheckable(True)
        self.live_btn.setChecked(bool(self.settings.get("show_live_queue", False)))
        self.live_btn.setToolTip("תור הדפסה חי + Hot Folder (מקלדת: רווח מדפיס, ↑/↓ בחירה)")
        self.live_btn.toggled.connect(self._toggle_live_panel)

        upload = QPushButton("📂  העלאת תמונות")
        upload.setProperty("chip", True)
        upload.clicked.connect(self._open_photo)

        self.start_btn = QPushButton()
        self.start_btn.setProperty("chip", True)
        self.start_btn.setCheckable(True)
        self.start_btn.setChecked(int(self.settings.get("start_copies", 1)) == 1)
        self.start_btn.setToolTip("כמה עותקים מקבלת כל תמונה שמעלים: 1 (מדפיסים הכול) או 0 (בוחרים ידנית)")
        self.start_btn.toggled.connect(self._toggle_start_copies)
        self._label_start_btn()

        for w in (upload, self.size_box, self.start_btn, enhance_btn):
            lay.addWidget(w)
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.VLine)
        sep.setObjectName("Sep")
        lay.addWidget(sep)
        for w in (frames_lbl, self.frame_box, self.portrait_btn, self.landscape_btn, none_btn):
            lay.addWidget(w)
        lay.addStretch()
        lay.addWidget(self.live_btn)
        self.tool_row = row
        self._update_frame_chips()

    def _frame_chip(self, text: str, which: str) -> QPushButton:
        btn = QPushButton(text)
        btn.setProperty("chip", True)
        btn.setCheckable(True)
        btn.setToolTip("לחיצה: בחירת קובץ PNG שקוף בגודל המגנט · קליק ימני: הסרה")
        btn.clicked.connect(lambda _=False, w=which: self._choose_png_frame(w))
        btn.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        btn.customContextMenuRequested.connect(lambda _pos, w=which: self._clear_png_frame(w))
        return btn

    def _build_print_panel(self) -> QWidget:
        s = self.settings
        self.mode_box = QComboBox()
        self.mode_box.addItem("דף מגנטים (שורות × עמודות)", PrintMode.SHEET.value)
        self.mode_box.addItem("מדפסת טרמית – מגנט לדף", PrintMode.THERMAL.value)
        self.mode_box.addItem("A4 – כמה שנכנס", PrintMode.A4.value)
        self.mode_box.setCurrentIndex(max(0, self.mode_box.findData(s["print_mode"])))
        self.mode_box.currentIndexChanged.connect(self._on_mode_changed)

        self.printer_box = QComboBox()
        self.printer_box.currentIndexChanged.connect(self._update_printer_chip)
        self.printer_box.currentIndexChanged.connect(lambda *_: self._update_media())
        refresh_btn = QPushButton("🖨  בחר מדפסת / רענן")
        refresh_btn.setProperty("tonal", True)
        refresh_btn.clicked.connect(self._refresh_printers)

        self.paper_box = QComboBox()
        for key, paper in PAPER_SIZES.items():
            self.paper_box.addItem(f"{paper.label} ס\"מ" if key != "A4" else "A4", key)
        self.paper_box.setCurrentIndex(max(0, self.paper_box.findData(s.get("paper", "15x20"))))
        self.paper_box.currentIndexChanged.connect(self._on_paper_changed)

        self.rows_box, self.cols_box = QSpinBox(), QSpinBox()
        for box, key in ((self.rows_box, "sheet_rows"), (self.cols_box, "sheet_cols")):
            box.setRange(1, 6)
            box.setValue(int(s.get(key, 2)))
            box.valueChanged.connect(lambda *_: self._update_summary())

        self.marks_check = QCheckBox("סימוני חיתוך")
        self.marks_check.setChecked(bool(s.get("crop_marks")))
        self.mark_width_box = QComboBox()
        for key, label in (("thin", "דק"), ("medium", "בינוני"), ("thick", "עבה")):
            self.mark_width_box.addItem(label, key)
        self.mark_width_box.setCurrentIndex(max(0, self.mark_width_box.findData(s.get("mark_width", "medium"))))

        self.margin_boxes = []
        margins = list(s.get("sheet_margins_mm") or [1.5] * 4)
        for v in margins[:4]:
            box = QDoubleSpinBox()
            box.setRange(0, 30)
            box.setDecimals(1)
            box.setSingleStep(0.5)
            box.setSuffix(" מ\"מ")
            box.setValue(float(v))
            self.margin_boxes.append(box)

        self.copies_box = QSpinBox()
        self.copies_box.setRange(1, 99)
        self.copies_box.setSuffix(" עותקים")
        self.copies_box.setToolTip("כמות לתמונה חדשה מ-Hot Folder, ולהדפסה מהתור החי (רווח)")

        self.auto_print = QCheckBox("הדפסה אוטומטית מ-Hot Folder")
        self.auto_print.toggled.connect(self._toggle_auto_print)
        self.fill_sheet = QCheckBox("לחכות לדף מלא לפני הדפסה")
        self.fill_sheet.setChecked(bool(s.get("hot_fill_sheet", True)))
        self.fill_sheet.setToolTip("במצב דף מגנטים: תמונות מ-Hot Folder מצטברות עד שהדף מתמלא (לא מבזבז נייר)")

        self.summary_lbl = QLabel()
        self.summary_lbl.setObjectName("SummaryBox")
        self.summary_lbl.setWordWrap(True)
        self.summary_lbl.setTextFormat(Qt.TextFormat.RichText)
        self._media_mm = None
        self.jpeg_btn = QPushButton("⬇  הורדה (JPEG)")
        self.jpeg_btn.setToolTip("שמירת דפי ההדפסה כקובצי JPEG לתיקייה")
        self.jpeg_btn.clicked.connect(lambda: self._print_all(action="jpeg"))
        self.print_btn = QPushButton("🖨  הדפס")
        self.print_btn.setProperty("class", "primary")
        self.print_btn.setProperty("big", True)
        self.print_btn.clicked.connect(self._print_all)

        for cb in (self.mode_box, self.printer_box, self.paper_box, self.mark_width_box):
            cb.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
            cb.setMinimumContentsLength(6)
        for sp in (self.rows_box, self.cols_box, self.copies_box, *self.margin_boxes):
            sp.setMinimumWidth(60)

        body = QWidget()
        body.setObjectName("PanelBody")
        pl = QVBoxLayout(body)
        pl.setContentsMargins(16, 16, 16, 16)
        pl.setSpacing(8)
        head = QLabel("🖨  הגדרות הדפסה")
        head.setObjectName("PanelHeading")
        pl.addWidget(head)
        self.count_lbl = QLabel()
        self.count_lbl.setObjectName("Dim")
        pl.addWidget(self.count_lbl)
        pl.addLayout(_field("מצב הדפסה", self.mode_box))
        pl.addLayout(_field("מדפסת", self.printer_box))
        pl.addWidget(refresh_btn)
        self.sheet_box = QWidget()
        sl = QVBoxLayout(self.sheet_box)
        sl.setContentsMargins(0, 0, 0, 0)
        sl.setSpacing(8)
        sl.addLayout(_field("גודל נייר", self.paper_box))
        grid = QGridLayout()
        grid.setHorizontalSpacing(8)
        grid.addWidget(_dim("שורות"), 0, 0)
        grid.addWidget(_dim("עמודות"), 0, 1)
        grid.addWidget(self.rows_box, 1, 0)
        grid.addWidget(self.cols_box, 1, 1)
        sl.addWidget(_section("פריסה"))
        sl.addLayout(grid)
        marks = QHBoxLayout()
        marks.addWidget(self.marks_check)
        marks.addWidget(self.mark_width_box, 1)
        sl.addLayout(marks)
        sl.addWidget(_section("שוליים"))
        mg = QGridLayout()
        mg.setHorizontalSpacing(8)
        for i, label in enumerate(("עליון", "תחתון", "ימין", "שמאל")):
            mg.addWidget(_dim(label), (i // 2) * 2, i % 2)
            mg.addWidget(self.margin_boxes[i], (i // 2) * 2 + 1, i % 2)
        sl.addLayout(mg)
        pl.addWidget(self.sheet_box)
        pl.addWidget(_section("Hot Folder"))
        pl.addLayout(_field("כמות לתמונה חדשה", self.copies_box))
        pl.addWidget(self.auto_print)
        pl.addWidget(self.fill_sheet)
        pl.addStretch()

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(body)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        panel = QFrame()
        panel.setObjectName("PrintPanel")
        panel.setFixedWidth(330)
        outer = QVBoxLayout(panel)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        outer.addWidget(scroll, 1)
        foot = QVBoxLayout()
        foot.setContentsMargins(16, 8, 16, 16)
        foot.addWidget(self.summary_lbl)
        foot.addWidget(self.print_btn)
        foot.addWidget(self.jpeg_btn)
        outer.addLayout(foot)
        self._on_mode_changed(save=False)
        return panel

    def _build_status_bar(self) -> None:
        sb = self.statusBar()
        sb.setObjectName("BottomBar")
        self.progress = QProgressBar()
        self.progress.setMaximumWidth(160)
        self.progress.hide()
        sb.addPermanentWidget(self.progress)
        self.sliders: dict[str, QSlider] = {}
        for key, label in (("exposure", "חשיפה"), ("contrast", "ניגודיות"), ("sharpness", "חדות")):
            box = QFrame()
            box.setObjectName("SliderBox")
            bl = QHBoxLayout(box)
            bl.setContentsMargins(10, 0, 10, 0)
            bl.setSpacing(6)
            name = QLabel(label)
            sl = QSlider(Qt.Orientation.Horizontal)
            sl.setRange(-100, 100)
            sl.setValue(int(self.settings.get(key) or 0))
            sl.setFixedWidth(110)
            val = QLabel(ltr(str(sl.value())))
            val.setMinimumWidth(28)
            sl.valueChanged.connect(lambda v, k=key, lbl=val: self._on_slider(k, v, lbl))
            sl.setToolTip("לחיצה כפולה על הערך מאפסת")
            val.mouseDoubleClickEvent = lambda _e, s_=sl: s_.setValue(0)
            for w in (name, sl, val):
                bl.addWidget(w)
            self.sliders[key] = sl
            sb.addPermanentWidget(box)
        self.counts_lbl = QLabel()
        self.counts_lbl.setObjectName("Dim")
        sb.insertPermanentWidget(0, self.counts_lbl)
        self.today_lbl = QLabel()
        self.today_lbl.setObjectName("Dim")
        ver = QLabel(ltr(f"v{__version__}"))
        ver.setObjectName("Dim")
        sb.addPermanentWidget(self.today_lbl)
        sb.addPermanentWidget(ver)
        sb.showMessage("מוכן")

    # ================================================================ printers
    def _refresh_printers(self) -> None:
        current = self.printer_box.currentText()
        self.printer_box.blockSignals(True)
        self.printer_box.clear()
        self.printer_box.addItems(get_available_printers())
        self.printer_box.blockSignals(False)
        if current and self.printer_box.findText(current) >= 0:
            self.printer_box.setCurrentText(current)
        else:
            self._select_saved_printer()
        real = self.printer_box.count() - 1
        log.info("Printers found: %s", [self.printer_box.itemText(i) for i in range(real)] or "none")
        self.statusBar().showMessage(f"נמצאו {real} מדפסות" if real else
                                     "לא נמצאו מדפסות – אפשר להדפיס לקובץ PDF לבדיקה", 6000)
        self._update_printer_chip()

    def _update_printer_chip(self) -> None:
        name = self.printer_box.currentText()
        if self.queue.is_busy:
            state = "printing"
        elif is_dry_run(name):
            state = "dry"
        else:
            state = "ready" if is_printer_available(name) else "offline"
        self.queue_panel.set_printer_state("PDF" if is_dry_run(name) else name,
                                           state in ("ready", "printing"),
                                           {"printing": "busy", "dry": "test"}.get(state))

    def _printer_key(self) -> str:
        return {PrintMode.A4.value: "a4_printer", PrintMode.SHEET.value: "sheet_printer"}.get(
            self.mode_box.currentData(), "thermal_printer")

    def _select_saved_printer(self) -> None:
        saved = self.settings.get(self._printer_key()) or ""
        idx = self.printer_box.findText(saved)
        self.printer_box.setCurrentIndex(idx if idx >= 0 else 0)

    # ================================================================ queue (display only)
    # Stage → card badge. QUEUED after an earlier print shows "בהדפסה" (a reprint on its way).
    _BADGES = {Stage.INCOMING: QueueItemStatus.INCOMING, Stage.ENHANCING: QueueItemStatus.ENHANCED,
               Stage.COMPOSING: QueueItemStatus.COMPOSED, Stage.SPOOLING: QueueItemStatus.SPOOLING,
               Stage.PRINTED: QueueItemStatus.PRINTED, Stage.FAILED: QueueItemStatus.FAILED}

    @property
    def items(self) -> dict[str, QueueItem]:
        return self.queue.items

    def _connect_queue(self) -> None:
        q = self.queue
        q.item_added.connect(self._on_item_added)
        q.item_changed.connect(self._show_item)
        q.busy_changed.connect(self._on_busy_changed)
        q.status.connect(self.statusBar().showMessage)
        q.progress.connect(self._on_progress)
        q.job_succeeded.connect(self._on_succeeded)
        q.job_failed.connect(self._on_failed)
        q.printer_unavailable.connect(lambda _name: self._refresh_printers())

    def _show_item(self, item_id: str) -> None:
        item = self.queue.get(item_id)
        if item is None:
            return
        badge = (QueueItemStatus.SPOOLING if item.copies_printed else QueueItemStatus.INCOMING) \
            if item.stage == Stage.QUEUED else self._BADGES[item.stage]
        # the total counter is driven by _on_succeeded (it counts magnets, incl. extra copies)
        self.queue_panel.update_item_status(item_id, badge, count_printed=0)
        card = self.queue_panel.cards.get(item_id)
        if card is not None:
            card.set_printed(item.copies_printed)
            card.badge_lbl.setToolTip(item.error)
        gcard = self.grid.cards.get(item_id)
        if gcard is not None:
            C = ThemeColors
            text, color = {
                Stage.ENHANCING: ("בעיבוד", C.ACCENT_AMBER), Stage.COMPOSING: ("בעיבוד", C.ACCENT_AMBER),
                Stage.SPOOLING: ("בהדפסה", C.ACCENT_AMBER), Stage.QUEUED: ("ממתין", C.ACCENT_AMBER),
                Stage.FAILED: ("נכשל", C.ACCENT_CORAL),
            }.get(item.stage, (f"הודפס ×{item.copies_printed}" if item.copies_printed else "", C.ACCENT_MINT))
            gcard.set_badge(text, color)
            gcard.setToolTip(item.error or item.name)

    def _on_item_added(self, item_id: str) -> None:
        item = self.queue.items[item_id]
        self.queue_panel.add_queue_card(item_id, item.path)
        card = self.grid.add_card(item_id, item.name)
        card.set_copies(self.copies_box.value() if item.source == "hot"
                        else int(self.settings.get("start_copies", 1)))
        self.thumbs.request(item_id, item.path, self._thumb_params())
        self._update_summary()

    def add_photo(self, path: str, source: str = "manual", select: bool = True) -> QueueItem:
        item = self.queue.add_photo(path, source)
        if select:
            self.queue_panel.select(item.id)  # → selection_changed → _select_item
            self._select_item(item.id)
        return item

    def _select_item(self, item_id: str) -> None:
        if self.queue_panel.selected_id != item_id:
            self.queue_panel.select(item_id)
        if self.grid.selected_id != item_id:
            self.grid.select(item_id)
        item = self.queue.get(item_id)
        if item:
            self.photo_path = item.path

    def _remove_photo(self, item_id: str) -> None:
        item = self.queue.get(item_id)
        if item is None or item.in_flight:
            self.toast.show_message("אי אפשר להסיר תמונה שנמצאת בהדפסה", "info")
            return
        self.grid.remove_card(item_id)
        self.queue_panel.remove_card(item_id)
        self.queue.items.pop(item_id, None)
        self._update_summary()

    def _print_item(self, item_id: str) -> None:
        self.queue.print_item(item_id, self.copies_box.value())

    def _on_keyboard_print(self, item_id: str, reprint: bool) -> None:
        """Space on the selected card (a reprint arrives here only after the double-tap)."""
        item = self.queue.get(item_id)
        if item is None:
            return
        if not self.queue.print_item(item_id, self.copies_box.value(), allow_duplicate=reprint):
            if item.in_flight:
                self.statusBar().showMessage("התמונה כבר בתור להדפסה", 3000)  # fast double-tap
            return
        if reprint:
            self.statusBar().showMessage(f"הדפסה חוזרת: {item.name}", 4000)

    # Space / ↑ / ↓ / Esc → queue, unless the user is typing somewhere
    _TEXT_INPUTS = (QLineEdit, QAbstractSpinBox, QPlainTextEdit, QTextEdit)
    _QUEUE_KEYS = (Qt.Key.Key_Space, Qt.Key.Key_Up, Qt.Key.Key_Down, Qt.Key.Key_Escape)

    def eventFilter(self, obj, event) -> bool:
        if (event.type() == QEvent.Type.KeyPress and event.key() in self._QUEUE_KEYS
                and not event.modifiers() & ~Qt.KeyboardModifier.KeypadModifier
                and isinstance(obj, QWidget) and obj.window() is self):
            focus = QApplication.focusWidget()
            typing = isinstance(focus, self._TEXT_INPUTS)
            in_combo = isinstance(focus, QComboBox)
            if typing or (in_combo and event.key() != Qt.Key.Key_Space):
                if self.queue_panel.guard.is_armed():  # navigating elsewhere still cancels
                    self.queue_panel.guard.cancel()
                return False
            if event.isAutoRepeat() and event.key() == Qt.Key.Key_Space:
                return True  # a held-down Space is not a double tap
            return self.queue_panel.handle_key(event.key())
        return super().eventFilter(obj, event)

    def _add_copy(self, item_id: str) -> None:
        if self.queue.print_item(item_id, 1):
            self.toast.show_message(f"עותק נוסף: {self.queue.items[item_id].name}", "info", 2000)

    # ================================================================ grid / thumbnails
    def _open_photo(self) -> None:
        files, _ = QFileDialog.getOpenFileNames(self, "בחר תמונות", "", "Images (*.jpg *.jpeg *.png *.webp)")
        for i, p in enumerate(files):
            self.add_photo(p, "manual", select=(i == len(files) - 1))
        if files:
            self.toast.show_message(f"הועלו {len(files)} תמונות", "success", 2500)

    def _thumb_params(self) -> ThumbParams:
        frame = self.frame_box.currentData()
        return ThumbParams(self.size_box.currentData(), frame,
                           None if is_template(frame) else self.settings.get("frame_landscape"),
                           make_enhance_filter(self.settings), max_side=520)

    def _rerender_thumbs(self) -> None:
        self.thumbs.invalidate()
        params = self._thumb_params()
        for item_id in self.grid.order:
            item = self.queue.get(item_id)
            if item:
                self.thumbs.request(item_id, item.path, params)

    def _refresh_preview(self) -> None:
        """Frame / size / enhancer / sliders changed → re-render every card (debounced)."""
        self._rethumb_timer.start()

    def _on_thumb(self, item_id: str, gen: int, img) -> None:
        if gen == self.thumbs.generation and item_id in self.grid.cards:
            self.grid.cards[item_id].set_image(img)

    def _zoom_cards(self, delta: int) -> None:
        self.grid.set_card_width(self.grid.card_width + delta)
        self.settings["card_width"] = self.grid.card_width

    def _show_large(self, item_id: str) -> None:
        item = self.queue.get(item_id)
        if item is None:
            return
        try:
            frame = self.frame_box.currentData()
            img = render_magnet(item.path, self.size_box.currentData(), frame, make_enhance_filter(self.settings),
                                frame_landscape=None if is_template(frame) else self.settings.get("frame_landscape"))
        except Exception as e:
            log.exception("Large preview failed for %s", item.path)
            self.toast.show_message(f"שגיאה בתצוגה: {e}", "error")
            return
        dlg = QDialog(self)
        dlg.setWindowTitle(item.name)
        lay = QVBoxLayout(dlg)
        lbl = QLabel()
        screen = self.screen().availableGeometry()
        pix = QPixmap.fromImage(ImageQt(img)).scaled(int(screen.width() * 0.6), int(screen.height() * 0.8),
                                                     Qt.AspectRatioMode.KeepAspectRatio,
                                                     Qt.TransformationMode.SmoothTransformation)
        lbl.setPixmap(pix)
        lay.addWidget(lbl)
        dlg.exec()

    def _on_slider(self, key: str, value: int, label: QLabel) -> None:
        label.setText(ltr(str(value)))
        self.settings[key] = value
        self._refresh_preview()

    def _toggle_live_panel(self, on: bool) -> None:
        self.queue_panel.setVisible(on)
        self.settings["show_live_queue"] = on

    def _update_summary(self) -> None:
        """Counts under the grid / on the print button: photos · copies · sheets."""
        if not hasattr(self, "grid"):
            return
        photos, copies = len(self.grid.order), self.grid.total_copies()
        sheets = self._sheets_for(copies)
        self.count_lbl.setText(ltr(f"🖼 {photos} תמונות"))
        frames = sum(1 for f in (self.frame_box.currentData(), self.settings.get("frame_landscape")) if f)
        self.summary_lbl.setText(self._summary_html(copies, sheets))
        self.print_btn.setText(f"🖨  הדפס ({copies})" if copies else "🖨  הדפס")
        self._counts_text = f"תמונות: {photos} · עותקים: {copies} · מסגרות: {frames}"
        if hasattr(self, "counts_lbl"):
            self.counts_lbl.setText(self._counts_text)

    def _summary_html(self, copies: int, sheets: int) -> str:
        """MagnetOti-style summary: total · capacity · pages · free slots on the last page."""
        C = ThemeColors
        if not copies:
            return f"<span style='color:{C.TEXT_MUTED}'>בחרו כמות (+) בכרטיסי התמונות</span>"
        lines = [f"🖼 סה״כ להדפסה: <b>{copies}</b>"]
        if self.mode_box.currentData() == PrintMode.SHEET.value:
            r, c = self.rows_box.value(), self.cols_box.value()
            per = r * c
            lines.append(f"▦ קיבולת לדף: {ltr(f'{r}×{c} = {per}')}")
            lines.append(f"📄 סה״כ עמודים: <b>{sheets}</b>")
            free = sheets * per - copies
            if free:
                lines.append(f"<span style='color:{C.ACCENT_CORAL}'>⚠ יש {free} מקומות פנויים בדף האחרון</span>")
            else:
                lines.append(f"<span style='color:{C.ACCENT_MINT}'>✔ אין מקומות פנויים — הדפים מלאים</span>")
            w, h = self._sheet_size_mm()
            lines.append(f"<span style='color:{C.TEXT_MUTED}'>גודל דף: {ltr(f'{w:g}×{h:g}')} מ״מ</span>")
        else:
            lines.append(f"📄 סה״כ עמודים: <b>{sheets}</b>")
        return "<br>".join(lines)

    def _sheets_for(self, magnets: int) -> int:
        if magnets <= 0:
            return 0
        mode = self.mode_box.currentData()
        if mode == PrintMode.SHEET.value:
            return math.ceil(magnets / max(1, self.rows_box.value() * self.cols_box.value()))
        if mode == PrintMode.A4.value:
            try:
                per = plan_grid(get_size(self.size_box.currentData()).size_px,
                                self.settings["a4_margin_cm"], self.settings["a4_gap_cm"]).per_page
            except ValueError:
                per = 1
            return math.ceil(magnets / max(1, per))
        return magnets

    # ================================================================ mode / paper / size
    def _on_mode_changed(self, *_args, save: bool = True) -> None:
        self.sheet_box.setVisible(self.mode_box.currentData() == PrintMode.SHEET.value)
        self.fill_sheet.setVisible(self.mode_box.currentData() == PrintMode.SHEET.value)
        if hasattr(self, "grid"):
            self._select_saved_printer()
            self._update_summary()

    def _on_paper_changed(self) -> None:
        rows, cols = auto_grid(get_size(self.size_box.currentData()).size_px, self.paper_box.currentData())
        self.rows_box.setValue(rows)
        self.cols_box.setValue(cols)
        self._update_media()

    def _update_media(self) -> None:
        """The printer driver's real media for the chosen paper (CP-D80DW 6x8 = 158×206 mm)."""
        paper = PAPER_SIZES[self.paper_box.currentData()]
        try:
            self._media_mm = media_size_mm(self.printer_box.currentText(),
                                           (paper.width_cm * 10, paper.height_cm * 10))
        except Exception:  # noqa: BLE001 – driver query must never break the UI
            log.exception("Media size query failed")
            self._media_mm = None
        if self._media_mm:
            log.info("Media for %s on %s: %s mm", paper.key, self.printer_box.currentText(), self._media_mm)
        self._update_summary()

    def _sheet_size_mm(self) -> tuple[float, float]:
        paper = PAPER_SIZES[self.paper_box.currentData()]
        return self._media_mm or (paper.width_cm * 10, paper.height_cm * 10)

    # ---- start copies (1 / 0)
    def _label_start_btn(self) -> None:
        self.start_btn.setText("התחל מ1" if self.start_btn.isChecked() else "התחל מ0")

    def _toggle_start_copies(self, on: bool) -> None:
        old, new = (0, 1) if on else (1, 0)
        self.settings["start_copies"] = new
        self._label_start_btn()
        for item_id, card in self.grid.cards.items():       # untouched cards follow the switch
            item = self.queue.get(item_id)
            if card.copies() == old and item is not None and not item.copies_printed:
                card.set_copies(new)
        self._update_summary()

    def _on_size_changed(self) -> None:
        self._on_paper_changed()
        self._refresh_preview()

    # ================================================================ counters (sheets / cost / today)
    def _roll_today(self) -> None:
        today = datetime.date.today().isoformat()
        if self.settings.get("today_date") != today:
            self.settings.update(today_date=today, today_sheets=0)

    def _update_counters(self) -> None:
        s = self.settings
        self.sheets_chip.setText(ltr(f"דפים הודפסו: {int(s.get('event_sheets', 0))}"))
        self.cost_chip.setText(ltr(f"✎ עלות: {float(s.get('event_cost', 0)):.2f} ₪"))
        self.today_lbl.setText(ltr(f"🖨 היום: {int(s.get('today_sheets', 0))} דפים"))

    def _count_sheets(self, sheets: int) -> None:
        self._roll_today()
        s = self.settings
        s["event_sheets"] = int(s.get("event_sheets", 0)) + sheets
        s["today_sheets"] = int(s.get("today_sheets", 0)) + sheets
        s["event_cost"] = round(float(s.get("event_cost", 0)) + sheets * float(s.get("cost_per_sheet") or 0), 2)
        self._update_counters()

    def _reset_event(self) -> None:
        if QMessageBox.question(self, "איפוס אירוע", "לאפס את מוני האירוע (דפים ועלות)?\n"
                                "המונה הכללי של המגנטים לא מתאפס.") != QMessageBox.StandardButton.Yes:
            return
        self.settings.update(event_sheets=0, event_cost=0.0)
        self._update_counters()
        self.persist_settings("reset event")
        self.toast.show_message("מוני האירוע אופסו", "success")

    # ================================================================ enhancer / settings / drop
    def _toggle_enhance(self, on: bool) -> None:
        self.settings["enhance"] = on
        log.info("Enhancer %s", "on" if on else "off")
        self.persist_settings("enhancer toggle")
        self.statusBar().showMessage("✨ שיפור חשיפה פעיל" if on else "שיפור חשיפה כבוי", 3000)
        self._refresh_preview()

    def _open_settings(self) -> None:
        mode = self.settings.get("theme_mode")
        if SettingsDialog(self.settings, self).exec():
            self.persist_settings("settings dialog")
            self._update_counters()
            self._refresh_preview()
            if self.settings.get("theme_mode") != mode:
                self.toast.show_message("מצב התצוגה ישתנה בהפעלה הבאה של התוכנה", "info", 4000)

    def _sync_ui_to_settings(self) -> None:
        """Copy the current UI choices (size, mode, printer) into the settings dict."""
        self.settings.update(magnet_size=self.size_box.currentData(),
                             print_mode=self.mode_box.currentData(),
                             paper=self.paper_box.currentData(),
                             sheet_rows=self.rows_box.value(), sheet_cols=self.cols_box.value(),
                             sheet_margins_mm=[b.value() for b in self.margin_boxes],
                             crop_marks=self.marks_check.isChecked(),
                             mark_width=self.mark_width_box.currentData(),
                             hot_fill_sheet=self.fill_sheet.isChecked())
        if self.printer_box.currentText():
            self.settings[self._printer_key()] = self.printer_box.currentText()

    def persist_settings(self, reason: str = "") -> bool:
        """Write settings to disk now (atomic). Called after every print, so a crash or power
        cut mid-event never loses the print counter or the setup."""
        self._sync_ui_to_settings()
        ok = save_settings(self.settings)
        if ok:
            log.debug("Settings saved (%s)", reason)
        elif not getattr(self, "_save_error_shown", False):
            self._save_error_shown = True  # warn once, not after every print
            self.toast.show_message("לא ניתן לשמור את ההגדרות – פרטים בקובץ הלוג", "error", 6000)
        return ok

    def dragEnterEvent(self, e) -> None:
        if any(Path(u.toLocalFile()).suffix.lower() in IMAGE_EXTS for u in e.mimeData().urls()):
            e.acceptProposedAction()

    def dropEvent(self, e) -> None:
        paths = [u.toLocalFile() for u in e.mimeData().urls()
                 if Path(u.toLocalFile()).suffix.lower() in IMAGE_EXTS]
        for i, p in enumerate(paths):
            self.add_photo(p, "drop", select=(i == len(paths) - 1))

    # ================================================================ frames / designer
    def _reload_frames(self, select: str | None = None) -> None:
        current = select or self.frame_box.currentData() or self.settings.get("frame")
        self.frame_box.blockSignals(True)
        self.frame_box.clear()
        self.frame_box.addItem("ללא מסגרת", None)
        for f in frame_files():
            self.frame_box.addItem(f"{'📐' if f.suffix == '.json' else '🖼'} {f.stem}", str(f))
        idx = self.frame_box.findData(str(current)) if current else 0
        self.frame_box.setCurrentIndex(max(0, idx))
        self.frame_box.blockSignals(False)

    def _on_frame_changed(self) -> None:
        path = self.frame_box.currentData()
        self.settings["frame"] = path
        if path:  # a template / frame defines its own canvas size
            try:
                profile = self._profile_of(path)
                idx = self.size_box.findData(profile)
                if idx >= 0:
                    self.size_box.blockSignals(True)
                    self.size_box.setCurrentIndex(idx)
                    self.size_box.blockSignals(False)
            except Exception as e:
                log.exception("Cannot load frame %s", path)
                self.toast.show_message(f"לא ניתן לטעון תבנית: {e}", "error")
        log.info("Active frame: %s", Path(path).name if path else "none")
        self.persist_settings("frame")
        self._update_frame_chips()
        self._refresh_preview()

    @staticmethod
    def _profile_of(path: str) -> str | None:
        if is_template(path):
            return load_template(path).canvas.profile  # same profile for both variants of a pair
        from PIL import Image
        with Image.open(path) as im:
            size = im.size
        for key, ms in MAGNET_SIZES.items():
            if size in (ms.size_px, ms.size_px[::-1]):
                return key
        return None

    def _update_frame_chips(self) -> None:
        frame = self.frame_box.currentData()
        port = bool(frame) and not is_template(frame)
        land = bool(self.settings.get("frame_landscape")) and not is_template(frame)
        for btn, on, name in ((self.portrait_btn, port, frame), (self.landscape_btn, land,
                                                                   self.settings.get("frame_landscape"))):
            btn.setChecked(on)
            btn.setText(("✓ " if on else "") + btn.text().lstrip("✓ "))
            btn.setToolTip((f"{Path(name).name} · " if on and name else "")
                           + "לחיצה: בחירת PNG שקוף · קליק ימני: הסרה")
        if hasattr(self, "grid"):
            self._update_summary()

    def _choose_png_frame(self, which: str) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "בחר מסגרת PNG (שקופה, בגודל המגנט)", "", "PNG (*.png)")
        self._update_frame_chips()            # undo the checkable toggle if cancelled
        if not path:
            return
        dest_dir = paths.user_templates_dir()
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / Path(path).name
        if Path(path).resolve() != dest.resolve():
            shutil.copy2(path, dest)          # keep it even if the original moves
        if which == "portrait":
            self._reload_frames(select=str(dest))
            self._on_frame_changed()
        else:
            self.settings["frame_landscape"] = str(dest)
            self._update_frame_chips()
            self.persist_settings("landscape frame")
            self._refresh_preview()
        self.toast.show_message(f"הועלתה והוחלה {'מסגרת אורך' if which == 'portrait' else 'מסגרת רוחב'}",
                                "success")

    def _clear_png_frame(self, which: str) -> None:
        if which == "portrait":
            self.frame_box.setCurrentIndex(0)
        else:
            self.settings["frame_landscape"] = None
            self._update_frame_chips()
            self.persist_settings("landscape frame")
            self._refresh_preview()

    def _clear_frames(self) -> None:
        self.settings["frame_landscape"] = None
        self.frame_box.setCurrentIndex(0)
        self._update_frame_chips()
        self._refresh_preview()

    def set_active_frame(self, path: str) -> None:
        """Make `path` (PNG or JSON) the overlay for the preview, prints and auto-print."""
        self._reload_frames(select=path)
        self._on_frame_changed()
        self.toast.show_message(f"מסגרת פעילה: {Path(path).stem}", "success")

    def _open_designer(self) -> None:
        if self._designer is not None and self._designer.isVisible():
            self._designer.raise_()
            self._designer.activateWindow()
            return
        path = self.frame_box.currentData()
        if is_template(path):
            from magnetstudio.core.templates import load_frame
            d = TemplateDesigner(load_frame(path), path, parent=self)
        else:
            d = TemplateDesigner(profile=self.size_box.currentData(), parent=self)
        d.template_saved.connect(self.set_active_frame)
        d.frame_exported.connect(self.set_active_frame)
        self._designer = d
        d.show()

    # ================================================================ printing
    def _job_for_item(self, item: QueueItem, copies: int) -> PrintJob:
        """The controller's job_factory: what to print comes from the current UI choices."""
        return self._make_job(item.path, copies, item.id)

    def _layout_opts(self) -> dict:
        return {"paper": self.paper_box.currentData(), "rows": self.rows_box.value(), "cols": self.cols_box.value(),
                "margins_mm": tuple(b.value() for b in self.margin_boxes), "crop_marks": self.marks_check.isChecked(),
                "mark_width": self.mark_width_box.currentData(), "paper_mm": self._media_mm,
                "margin_cm": self.settings["a4_margin_cm"], "gap_cm": self.settings["a4_gap_cm"]}

    def _make_job(self, photo_path: str | list[str], copies: int | list[int], tag: str = "") -> PrintJob:
        photos = [photo_path] if isinstance(photo_path, str) else list(photo_path)
        frame = self.frame_box.currentData()
        return PrintJob(
            mode=PrintMode(self.mode_box.currentData()),
            printer_name=self.printer_box.currentText() or DRY_RUN_PRINTER,
            photo_paths=photos,
            magnet_size=self.size_box.currentData(),
            frame_path=frame,
            frame_landscape_path=None if is_template(frame) else self.settings.get("frame_landscape"),
            photo_filter=make_enhance_filter(self.settings),
            copies=copies if isinstance(copies, int) else 1,
            photo_copies=[] if isinstance(copies, int) else list(copies),
            out_dir=paths.resolve_output_dir(self.settings.get("output_folder")),
            job_name=f"MagnetStudio – {Path(photos[0]).name}" + (f" (+{len(photos) - 1})" if len(photos) > 1 else ""),
            layout_opts=self._layout_opts(),
            tag=tag,
        )

    def _batch_job(self) -> PrintJob | None:
        batch = self.grid.batch()
        if not batch and self.grid.selected_id:          # nothing counted → the selected photo ×1
            batch = [(self.grid.selected_id, 1)]
        if not batch:
            self.toast.show_message("בחרו כמות עותקים בכרטיסי התמונות (+)", "info")
            return None
        ids = [i for i, _ in batch]
        return self._make_job([self.queue.items[i].path for i in ids], [n for _, n in batch], ",".join(ids))

    def _print_all(self, action: str = "preview") -> None:
        """"Print": build every page (background) → print preview → print the selected pages.
        action="jpeg": build the pages and save them as JPEG files."""
        job = self._batch_job()
        if job is None:
            return
        dlg = QProgressDialog("יוצר דפי הדפסה…", "", 0, max(1, len(job.photo_paths)), self)
        dlg.setWindowTitle("MagnetStudio")
        dlg.setCancelButton(None)
        dlg.setMinimumDuration(300)
        dlg.setWindowModality(Qt.WindowModality.WindowModal)
        builder = PageBuilder(job, self)
        builder.progress.connect(lambda d, _t: dlg.setValue(d))
        builder.failed.connect(lambda msg: (dlg.close(), self._on_failed(f"יצירת הדפים נכשלה: {msg}")))
        builder.done.connect(lambda pages, owners: (dlg.close(), self._after_pages(job, pages, owners, action)))
        builder.finished.connect(builder.deleteLater)
        self._builder = builder
        builder.start()

    def _after_pages(self, job: PrintJob, pages: list, owners: list, action: str) -> None:
        if not pages:
            return
        if action == "jpeg":
            self._save_pages_jpeg(pages)
            return
        r, c = self.rows_box.value(), self.cols_box.value()
        w, h = self._sheet_size_mm()
        sheet = job.mode == PrintMode.SHEET
        info = {"printer": "PDF (בדיקה)" if is_dry_run(job.printer_name) else job.printer_name,
                "paper": PAPER_SIZES[self.paper_box.currentData()].label if sheet else self.mode_box.currentText(),
                "size_mm": (w, h) if sheet else None, "layout": f"{r}×{c}" if sheet else "-", "dpi": 300}
        preview = PrintPreviewDialog(pages, owners, info, self)
        if not preview.exec():
            return
        if preview.action == "jpeg":
            self._save_pages_jpeg(preview.selected_pages())
            return
        sel_owners = preview.selected_owners()
        ids = list(dict.fromkeys(o for o in sel_owners if o))
        pjob = PrintJob(mode=job.mode, printer_name=job.printer_name, images=preview.selected_pages(),
                        pages_ready=True, magnets=len(sel_owners), tag=",".join(ids),
                        photo_copies=[sel_owners.count(i) for i in ids], out_dir=job.out_dir,
                        job_name=job.job_name, layout_opts=job.layout_opts)
        if self.queue.submit(pjob):
            n = len(preview.selected_indices())
            self.statusBar().showMessage(f"נשלח להדפסה: {len(sel_owners)} מגנטים · {n} דפים", 5000)

    def _save_pages_jpeg(self, pages: list) -> None:
        folder = QFileDialog.getExistingDirectory(self, "בחר תיקייה לשמירת דפי ההדפסה")
        if not folder:
            return
        stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        for i, page in enumerate(pages, 1):
            page.save(Path(folder) / f"MagnetStudio_{stamp}_{i:03d}.jpg", quality=95, dpi=(300, 300))
        log.info("Saved %d page(s) as JPEG to %s", len(pages), folder)
        self.toast.show_message(f"נשמרו {len(pages)} דפים כ-JPEG", "success", 3000)

    def _print_current(self) -> None:
        self._print_all()

    def submit_job(self, job: PrintJob) -> None:
        """Queue a ready-made job (e.g. from a script / test)."""
        if self.queue.submit(job) and self.queue.waiting:
            self.statusBar().showMessage(f"נוסף לתור ({self.queue.waiting} ממתינים)")

    def _on_busy_changed(self, busy: bool) -> None:
        if busy:
            self.progress.setRange(0, 0)  # busy indicator until pages are counted
            self.progress.show()
        else:
            self.progress.hide()
            self.print_btn.setEnabled(True)
        self._update_printer_chip()

    def _on_progress(self, done: int, total: int) -> None:
        self.progress.setRange(0, max(1, total))
        self.progress.setValue(done)
        self.progress.setFormat(f"{done}/{total}")

    def _on_succeeded(self, msg: str, magnets: int) -> None:
        job = self.queue.active_job
        if job is not None:
            # pages actually printed (a preview job may hold a partial selection); copies stay on the
            # cards like in MagnetOti – the card badge shows "הודפס ×n"
            self._count_sheets(len(job.images) if job.pages_ready else self._sheets_for(magnets))
        self.settings["print_count_total"] = self.queue.total_printed
        self.queue_panel.increment_print_counter(magnets)
        self.persist_settings("print done")  # counter on disk right away
        self.statusBar().showMessage(msg, 8000)
        if not self.queue.waiting:
            short = f"נשמר לקובץ PDF: {Path(msg.split(': ', 1)[1]).name}" if msg.startswith("נשמר: ") else msg
            self.toast.show_message(short, "success", 2500)

    def _on_failed(self, msg: str) -> None:
        self.statusBar().showMessage(msg, 8000)
        self.toast.show_message(msg, "error", 6000)

    # ================================================================ hot folder / auto print
    def _toggle_auto_print(self, on: bool) -> None:
        if on:
            folder = self.settings.get("watch_folder") or QFileDialog.getExistingDirectory(
                self, "בחר תיקייה למעקב")
            if not folder:
                self.auto_print.setChecked(False)
                return
            self.settings["watch_folder"] = folder
            try:
                self._watcher = FolderWatcher(folder, lambda p: self._bridge.new_photo.emit(str(p)))
                self._watcher.start()
            except OSError as e:
                log.error("Cannot watch folder %s: %s", folder, e)
                self._watcher = None
                self.toast.show_message(f"לא ניתן להאזין לתיקייה: {e}", "error", 6000)
                self.auto_print.setChecked(False)
                return
            self.persist_settings("hot folder on")
            self.queue_panel.set_hot_folder(folder, active=True)
            self.statusBar().showMessage(f"מאזין לתיקייה: {folder}")
        else:
            if self._watcher:
                self._watcher.stop()
                self._watcher = None
            self.queue_panel.set_hot_folder("", active=False)
            log.info("Hot folder off")
            self.statusBar().showMessage("הדפסה אוטומטית כבויה")

    def _on_new_photo(self, path: str) -> None:
        item = self.add_photo(path, "hot")
        if self.mode_box.currentData() != PrintMode.SHEET.value or not self.fill_sheet.isChecked():
            self.queue.print_item(item.id, self.copies_box.value())
            self.grid.cards[item.id].set_copies(0)
            return
        # sheet mode: collect Hot Folder photos until a full sheet, then print them together
        per = max(1, self.rows_box.value() * self.cols_box.value())
        pending = [(i, self.grid.cards[i].copies()) for i in self.grid.order
                   if self.queue.items[i].source == "hot" and not self.queue.items[i].in_flight
                   and self.grid.cards[i].copies() > 0]
        waiting = sum(n for _, n in pending)
        if waiting < per:
            self.statusBar().showMessage(f"Hot Folder: {waiting}/{per} מגנטים לדף הבא", 4000)
            return
        ids = [i for i, _ in pending]
        self.queue.submit(self._make_job([self.queue.items[i].path for i in ids], [n for _, n in pending],
                                         ",".join(ids)))

    # ================================================================ shutdown
    def closeEvent(self, event) -> None:
        QApplication.instance().removeEventFilter(self)
        self.thumbs.stop()
        if self._watcher:
            self._watcher.stop()
        self.queue.shutdown()
        self.persist_settings("close")
        log.info("Main window closed – %d magnet(s) printed this session", self.queue.session_printed)
        super().closeEvent(event)
