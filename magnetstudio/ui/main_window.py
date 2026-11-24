"""Main window (dark, Lightroom-style).

┌ TopBar: logo · ✨ enhancer · 🎨 designer · ⚙ ──────────────────────────────────────────────────┐
│ Controls panel │      Preview (press & hold = before)      │ QueuePanel: printer · Hot Folder ·  │
│                │                                           │ total prints chips + 88px cards     │
└ Status bar ─────────────────────────────────────────────────────────────────────────────────────┘
Layout is right-to-left (Hebrew): controls on the right, queue on the left.
"""
import logging
from collections import deque
from pathlib import Path

from PIL.ImageQt import ImageQt
from PyQt6.QtCore import QEvent, QMargins, QObject, Qt, QThread, QTimer, pyqtSignal
from PyQt6.QtGui import QAction, QPixmap
from PyQt6.QtWidgets import (QAbstractSpinBox, QApplication, QCheckBox, QComboBox, QFileDialog, QFrame,
                             QHBoxLayout, QLabel, QLineEdit, QPlainTextEdit, QTextEdit,
                             QMainWindow, QProgressBar, QPushButton, QSpinBox, QSplitter,
                             QToolButton, QVBoxLayout, QWidget)

from magnetstudio.core.framer import is_template, make_enhance_filter, render_magnet
from magnetstudio import paths
from magnetstudio.core.settings import save_settings
from magnetstudio.core.sizes import MAGNET_SIZES
from magnetstudio.core.templates import load_template
from magnetstudio.core.watcher import FolderWatcher
from magnetstudio.services.printer import (DRY_RUN_PRINTER, PrintJob, PrintMode, PrintWorker,
                                          get_available_printers, is_dry_run, is_printer_available)
from magnetstudio.ui.designer import TemplateDesigner
from magnetstudio.ui.settings_dialog import SettingsDialog
from magnetstudio.ui.toast import Toast
from magnetstudio.ui.components.queue_panel import QueueItemStatus, QueuePanel
from magnetstudio.ui.widgets import QueueItem

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


class _RenderThread(QThread):
    """Renders the enhanced preview off the GUI thread (cloud styles can take seconds)."""
    done = pyqtSignal(int, object)
    failed = pyqtSignal(int, str)

    def __init__(self, gen: int, fn, parent=None):
        super().__init__(parent)
        self.gen, self.fn = gen, fn

    def run(self):
        try:
            self.done.emit(self.gen, self.fn())
        except Exception as e:
            self.failed.emit(self.gen, str(e))


class PreviewLabel(QLabel):
    """Press and hold to see the original ("before"); release to return to "after"."""
    hold_changed = pyqtSignal(bool)

    def __init__(self, text=""):
        super().__init__(text)
        self._timer = QTimer(self, singleShot=True, interval=250,
                             timeout=lambda: self.hold_changed.emit(True))

    def mousePressEvent(self, e):
        self._timer.start()
        super().mousePressEvent(e)

    def mouseReleaseEvent(self, e):
        if self._timer.isActive():
            self._timer.stop()
        else:
            self.hold_changed.emit(False)
        super().mouseReleaseEvent(e)


def _section(title: str) -> QLabel:
    lbl = QLabel(title)
    lbl.setObjectName("PanelTitle")
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
        self._worker: PrintWorker | None = None
        self._active_job: PrintJob | None = None
        self._queue: deque[PrintJob] = deque()
        self._watcher: FolderWatcher | None = None
        self._bridge = _WatcherBridge()
        self._bridge.new_photo.connect(self._on_new_photo)
        self._before_pix: QPixmap | None = None
        self._after_pix: QPixmap | None = None
        self._preview_gen = 0
        self._render_threads: set[_RenderThread] = set()
        self.items: dict[str, QueueItem] = {}
        self._session_count = 0
        self.setAcceptDrops(True)

        self.setWindowTitle("MagnetStudio")
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.resize(1440, 860)
        self._build_ui()
        self.toast = Toast(self)
        self._refresh_printers()
        self.queue_panel.set_total_prints(int(self.settings.get("print_count_total", 0)))
        self._printer_timer = QTimer(self, interval=5000, timeout=self._update_printer_chip)
        self._printer_timer.start()
        # keyboard control of the queue (Space / ↑ / ↓ / Esc) wherever focus is in this window
        QApplication.instance().installEventFilter(self)

    # ================================================================ UI
    def _build_ui(self) -> None:
        self._build_top_bar()

        # ---- controls (right side in RTL)
        self.size_box = QComboBox()
        for key, size in MAGNET_SIZES.items():
            self.size_box.addItem(size.label, key)
        self.size_box.setCurrentIndex(max(0, self.size_box.findData(self.settings["magnet_size"])))
        self.size_box.currentIndexChanged.connect(self._refresh_preview)

        self.frame_box = QComboBox()
        self._reload_frames()
        self.frame_box.currentIndexChanged.connect(self._on_frame_changed)

        self.mode_box = QComboBox()
        self.mode_box.addItem("מדפסת טרמית – מגנט בודד", PrintMode.THERMAL.value)
        self.mode_box.addItem("פריסת A4 – כמה מגנטים לדף", PrintMode.A4.value)
        self.mode_box.setCurrentIndex(max(0, self.mode_box.findData(self.settings["print_mode"])))
        self.mode_box.currentIndexChanged.connect(self._select_saved_printer)

        self.printer_box = QComboBox()
        self.printer_box.currentIndexChanged.connect(self._update_printer_chip)
        refresh_btn = QPushButton("⟳")
        refresh_btn.setToolTip("רענן רשימת מדפסות")
        refresh_btn.setFixedWidth(42)
        refresh_btn.setProperty("icon-only", True)
        refresh_btn.clicked.connect(self._refresh_printers)
        printer_row = QHBoxLayout()
        printer_row.setSpacing(6)
        printer_row.addWidget(self.printer_box, 1)
        printer_row.addWidget(refresh_btn)
        printer_wrap = QWidget()
        printer_wrap.setLayout(printer_row)
        printer_row.setContentsMargins(0, 0, 0, 0)

        self.copies_box = QSpinBox()
        self.copies_box.setRange(1, 99)
        self.copies_box.setSuffix(" עותקים")

        open_btn = QPushButton("📂 הוסף תמונות…")
        open_btn.clicked.connect(self._open_photo)
        editor_btn = QPushButton("ערוך מסגרת / תבנית חדשה")
        editor_btn.setProperty("ghost", True)
        editor_btn.clicked.connect(self._open_designer)
        self.before_after = QCheckBox("הצג מקור (לפני השיפור)")
        self.before_after.toggled.connect(lambda on: self._show_preview(before=on))
        self.auto_print = QCheckBox("הדפסה אוטומטית מ-Hot Folder")
        self.auto_print.toggled.connect(self._toggle_auto_print)

        self.print_btn = QPushButton("🖨  הדפס")
        self.print_btn.setProperty("class", "primary")
        self.print_btn.setProperty("big", True)
        self.print_btn.clicked.connect(self._print_current)

        panel = QFrame()
        panel.setObjectName("Panel")
        panel.setFixedWidth(290)
        pl = QVBoxLayout(panel)
        pl.setContentsMargins(16, 16, 16, 16)
        pl.setSpacing(10)
        pl.addWidget(_section("תמונה"))
        pl.addWidget(open_btn)
        pl.addWidget(self.before_after)
        pl.addSpacing(8)
        pl.addWidget(_section("מגנט"))
        pl.addLayout(_field("גודל", self.size_box))
        pl.addLayout(_field("מסגרת / תבנית", self.frame_box))
        pl.addWidget(editor_btn)
        pl.addSpacing(8)
        pl.addWidget(_section("הדפסה"))
        pl.addLayout(_field("מצב", self.mode_box))
        pl.addLayout(_field("מדפסת", printer_wrap))
        pl.addLayout(_field("כמות", self.copies_box))
        pl.addWidget(self.auto_print)
        pl.addStretch()
        pl.addWidget(self.print_btn)

        # ---- preview (center)
        self.preview = PreviewLabel("גרור תמונה לכאן או בחר מהתור")
        self.preview.setObjectName("PreviewArea")
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview.setMinimumSize(380, 380)
        self.preview.setToolTip("לחיצה ארוכה = לפני השיפור")
        self.preview.hold_changed.connect(lambda held: self._show_preview(before=held))

        # ---- queue (left side in RTL): status chips + cards (ui/components/queue_panel.py)
        self.queue_panel = QueuePanel()
        self.queue_panel.setMinimumWidth(540)
        self.queue_panel.add_copy_job.connect(self._add_copy)
        self.queue_panel.reprint_job.connect(self._print_item)
        self.queue_panel.inspect_job.connect(self._select_item)
        self.queue_panel.hot_folder_toggle_requested.connect(lambda: self.auto_print.toggle())
        self.queue_panel.selection_changed.connect(self._select_item)
        self.queue_panel.keyboard_print.connect(self._on_keyboard_print)
        self.queue_panel.status_message.connect(
            lambda msg: self.statusBar().showMessage(msg, 4000) if msg else self.statusBar().clearMessage())

        split = QSplitter(Qt.Orientation.Horizontal)
        split.setChildrenCollapsible(False)
        split.setHandleWidth(12)
        split.addWidget(panel)
        split.addWidget(self.preview)
        split.addWidget(self.queue_panel)
        split.setStretchFactor(1, 1)
        split.setSizes([290, 580, 560])

        body = QWidget()
        bl = QVBoxLayout(body)
        bl.setContentsMargins(12, 12, 12, 12)
        bl.addWidget(split)

        root = QWidget()
        rl = QVBoxLayout(root)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.setSpacing(0)
        rl.addWidget(self.top_bar)
        rl.addWidget(body, 1)
        self.setCentralWidget(root)

        self.progress = QProgressBar()
        self.progress.setMaximumWidth(200)
        self.progress.hide()
        self.statusBar().addPermanentWidget(self.progress)
        self.statusBar().showMessage("מוכן")

    def _build_top_bar(self) -> None:
        bar = QFrame()
        bar.setObjectName("TopBar")
        bar.setFixedHeight(64)
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(18, 8, 18, 8)
        lay.setSpacing(10)

        logo = QHBoxLayout()
        logo.setSpacing(0)
        a, b = QLabel("Magnet"), QLabel("Studio")
        a.setObjectName("AppTitle")
        b.setObjectName("AppTitle")
        b.setProperty("accent", True)
        logo_w = QWidget()
        logo_w.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
        logo_w.setLayout(logo)
        logo.setContentsMargins(0, 0, 12, 0)
        logo.addWidget(a)
        logo.addWidget(b)
        lay.addWidget(logo_w)

        self.enhance_act = QAction("✨ שיפור חשיפה להדפסה", self, checkable=True)
        self.enhance_act.setToolTip("Fast AI Enhancer – הרמת צללים ורוויה מותאמת להדפסה, לפני הלבשת המסגרת")
        self.enhance_act.setChecked(bool(self.settings.get("enhance")))
        self.enhance_act.toggled.connect(self._toggle_enhance)
        designer_act = QAction("🎨 עורך מסגרות", self)
        designer_act.triggered.connect(self._open_designer)
        settings_act = QAction("⚙ הגדרות", self)
        settings_act.triggered.connect(self._open_settings)
        for act in (self.enhance_act, designer_act, settings_act):
            btn = QToolButton()
            btn.setDefaultAction(act)
            btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
            lay.addWidget(btn)

        lay.addStretch()
        self.top_bar = bar

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
                                     "לא נמצאו מדפסות – אפשר להדפיס לקובץ PDF לבדיקה")
        self._update_printer_chip()

    def _update_printer_chip(self) -> None:
        name = self.printer_box.currentText()
        if self._worker is not None:
            state = "printing"
        elif is_dry_run(name):
            state = "dry"
        else:
            state = "ready" if is_printer_available(name) else "offline"
        self.queue_panel.set_printer_state("PDF" if is_dry_run(name) else name,
                                           state in ("ready", "printing"),
                                           {"printing": "busy", "dry": "test"}.get(state))

    def _printer_key(self) -> str:
        return "a4_printer" if self.mode_box.currentData() == PrintMode.A4.value else "thermal_printer"

    def _select_saved_printer(self) -> None:
        saved = self.settings.get(self._printer_key()) or ""
        idx = self.printer_box.findText(saved)
        self.printer_box.setCurrentIndex(idx if idx >= 0 else 0)

    # ================================================================ queue
    def add_photo(self, path: str, source: str = "manual", select: bool = True) -> QueueItem:
        item = QueueItem(path=path, source=source)
        self.items[item.id] = item
        self.queue_panel.add_queue_card(item.id, path)
        if select:
            self.queue_panel.select(item.id)  # → selection_changed → _select_item
            self._select_item(item.id)
        return item

    def _select_item(self, item_id: str) -> None:
        if self.queue_panel.selected_id != item_id:
            self.queue_panel.select(item_id)
        item = self.items.get(item_id)
        if item and item.path != self.photo_path:
            self.photo_path = item.path
            self._refresh_preview()

    def _set_item_status(self, item_id: str, status: str, error: str = "",
                         shown: QueueItemStatus | None = None) -> None:
        """Update the model and the card badge. `shown` overrides the badge for pipeline steps."""
        item = self.items.get(item_id)
        if not item:
            return
        item.status = status
        item.error = error
        badge = shown or {
            "pending": QueueItemStatus.INCOMING, "queued": QueueItemStatus.INCOMING,
            "processing": QueueItemStatus.COMPOSED, "printing": QueueItemStatus.SPOOLING,
            "done": QueueItemStatus.PRINTED, "failed": QueueItemStatus.FAILED,
        }[status]
        # the counter is driven by _on_succeeded (it counts magnets, incl. extra copies)
        self.queue_panel.update_item_status(item_id, badge, count_printed=0)
        card = self.queue_panel.cards.get(item_id)
        if card is not None:
            card.set_printed(item.copies_printed)
            card.badge_lbl.setToolTip(error)

    def _print_item(self, item_id: str) -> None:
        item = self.items.get(item_id)
        if item:
            self.submit_job(self._make_job(item.path, self.copies_box.value(), item.id))

    def _on_keyboard_print(self, item_id: str, reprint: bool) -> None:
        """Space on the selected card (a reprint arrives here only after the double-tap)."""
        item = self.items.get(item_id)
        if not item:
            return
        if not reprint and (item.jobs_open > 0 or item.status in ("processing", "printing")):
            self.statusBar().showMessage("התמונה כבר בתור להדפסה", 3000)  # no double print on a fast double-tap
            return
        self.submit_job(self._make_job(item.path, self.copies_box.value(), item.id))
        if reprint and item.status == "queued":  # confirmed reprint → show it as spooling
            self._set_item_status(item_id, "queued", shown=QueueItemStatus.SPOOLING)
            self.statusBar().showMessage(f"הדפסה חוזרת: {Path(item.path).name}", 4000)

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
        item = self.items.get(item_id)
        if item:
            self.submit_job(self._make_job(item.path, 1, item.id))
            self.toast.show_message(f"עותק נוסף: {Path(item.path).name}", "info", 2000)

    # ================================================================ preview
    def _open_photo(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(self, "בחר תמונות", "", "Images (*.jpg *.jpeg *.png *.webp)")
        for i, p in enumerate(paths):
            self.add_photo(p, "manual", select=(i == len(paths) - 1))

    def _refresh_preview(self) -> None:
        if not self.photo_path:
            return
        self._preview_gen += 1
        gen, path = self._preview_gen, self.photo_path
        size, frame = self.size_box.currentData(), self.frame_box.currentData()
        try:
            before = render_magnet(path, size, frame)
        except Exception as e:
            log.exception("Preview failed for %s", path)
            self.toast.show_message(f"שגיאה בתצוגה: {e}", "error")
            return
        self._before_pix = QPixmap.fromImage(ImageQt(before))
        self._after_pix = None
        flt = make_enhance_filter(self.settings)
        self.before_after.setEnabled(flt is not None)
        if flt is None:
            self._show_preview()
            return
        self._show_preview(before=True)
        self.statusBar().showMessage("משפר תמונה…")
        th = _RenderThread(gen, lambda: render_magnet(path, size, frame, flt), self)
        th.done.connect(self._on_after_ready)
        th.failed.connect(lambda g, msg: g == self._preview_gen and self._on_failed(f"שיפור נכשל: {msg}"))
        th.finished.connect(lambda t=th: self._render_threads.discard(t))
        th.finished.connect(th.deleteLater)
        self._render_threads.add(th)
        th.start()

    def _on_after_ready(self, gen: int, img) -> None:
        if gen != self._preview_gen:  # a newer preview was requested meanwhile
            return
        self._after_pix = QPixmap.fromImage(ImageQt(img))
        self.statusBar().showMessage("✨ שיפור הופעל – לחיצה ארוכה על התמונה להשוואה", 4000)
        self._show_preview()

    def _show_preview(self, before: bool | None = None) -> None:
        if before is None:
            before = self.before_after.isChecked()
        pix = self._before_pix if before or self._after_pix is None else self._after_pix
        if pix is None:
            return
        target = self.preview.size().shrunkBy(QMargins(24, 24, 24, 24))
        self.preview.setPixmap(pix.scaled(target, Qt.AspectRatioMode.KeepAspectRatio,
                                          Qt.TransformationMode.SmoothTransformation))

    def resizeEvent(self, e) -> None:
        super().resizeEvent(e)
        QTimer.singleShot(0, self._show_preview)

    # ================================================================ enhancer / settings / drop
    def _toggle_enhance(self, on: bool) -> None:
        self.settings["enhance"] = on
        log.info("Enhancer %s", "on" if on else "off")
        self.persist_settings("enhancer toggle")
        self.statusBar().showMessage("✨ שיפור חשיפה פעיל" if on else "שיפור חשיפה כבוי", 3000)
        self._refresh_preview()

    def _open_settings(self) -> None:
        if SettingsDialog(self.settings, self).exec():
            self.persist_settings("settings dialog")
            self._refresh_preview()

    def _sync_ui_to_settings(self) -> None:
        """Copy the current UI choices (size, mode, printer) into the settings dict."""
        self.settings.update(magnet_size=self.size_box.currentData(),
                             print_mode=self.mode_box.currentData())
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
    def _make_job(self, photo_path: str, copies: int, tag: str = "") -> PrintJob:
        return PrintJob(
            mode=PrintMode(self.mode_box.currentData()),
            printer_name=self.printer_box.currentText() or DRY_RUN_PRINTER,
            photo_paths=[photo_path],
            magnet_size=self.size_box.currentData(),
            frame_path=self.frame_box.currentData(),
            photo_filter=make_enhance_filter(self.settings),
            copies=copies,
            out_dir=paths.resolve_output_dir(self.settings.get("output_folder")),
            job_name=f"MagnetStudio – {Path(photo_path).name}",
            layout_opts={"margin_cm": self.settings["a4_margin_cm"],
                         "gap_cm": self.settings["a4_gap_cm"],
                         "crop_marks": self.settings["crop_marks"]},
            tag=tag,
        )

    def _print_current(self) -> None:
        if not self.photo_path:
            self.toast.show_message("בחר תמונה קודם", "info")
            return
        item = next((i for i in self.items.values() if i.path == self.photo_path), None) \
            or self.add_photo(self.photo_path, "manual")
        self.submit_job(self._make_job(self.photo_path, self.copies_box.value(), item.id))

    def submit_job(self, job: PrintJob) -> None:
        """Queue a job; it runs in a PrintWorker so the UI stays responsive."""
        if not is_printer_available(job.printer_name):
            log.error("Printer unavailable: %r (job %s)", job.printer_name, job.tag)
            self._on_failed(f"המדפסת '{job.printer_name}' לא זמינה")
            if job.tag:
                self._set_item_status(job.tag, "failed", "המדפסת לא זמינה")
            self._refresh_printers()
            return
        self._queue.append(job)
        log.info("Queued [%s] %s ×%d (%d waiting)", job.tag or "-",
                 ", ".join(Path(p).name for p in job.photo_paths), job.copies, len(self._queue))
        if job.tag in self.items:
            self.items[job.tag].jobs_open += 1
            if self.items[job.tag].status not in ("processing", "printing"):
                self._set_item_status(job.tag, "queued")
        if self._worker is None:
            self._start_next()
        else:
            self.statusBar().showMessage(f"נוסף לתור ({len(self._queue)} ממתינים)")

    def _start_next(self) -> None:
        self._active_job = None
        if not self._queue:
            self._worker = None
            self.progress.hide()
            self.print_btn.setEnabled(True)
            self._update_printer_chip()
            return
        job = self._queue.popleft()
        w = PrintWorker(job, self)
        w.status.connect(self.statusBar().showMessage)
        w.progress.connect(self._on_progress)
        w.succeeded.connect(self._on_succeeded)
        w.failed.connect(self._on_failed)
        w.finished.connect(w.deleteLater)
        w.finished.connect(self._start_next)
        self._worker, self._active_job = w, job
        if job.tag:  # rendering: enhancer (if on) → frame / template
            self._set_item_status(job.tag, "processing", shown=QueueItemStatus.ENHANCED
                                  if job.photo_filter else QueueItemStatus.COMPOSED)
        self.progress.setRange(0, 0)  # busy indicator until pages are counted
        self.progress.show()
        self._update_printer_chip()
        w.start()

    def _on_progress(self, done: int, total: int) -> None:
        self.progress.setRange(0, max(1, total))
        self.progress.setValue(done)
        self.progress.setFormat(f"{done}/{total}")
        job = self._active_job
        if job and job.tag and job.tag in self.items:
            if done == 0:   # pages rendered, about to spool
                self._set_item_status(job.tag, "processing", shown=QueueItemStatus.COMPOSED)
            else:
                self._set_item_status(job.tag, "printing")

    def _finish_item_job(self, ok: bool, msg: str = "") -> None:
        job = self._active_job
        if not job or not job.tag or job.tag not in self.items:
            return
        item = self.items[job.tag]
        item.jobs_open = max(0, item.jobs_open - 1)
        if ok:
            item.copies_printed += job.magnet_count()
        status = ("queued" if item.jobs_open else "done") if ok else "failed"
        self._set_item_status(job.tag, status, "" if ok else msg)

    def _on_succeeded(self, msg: str) -> None:
        n = self._active_job.magnet_count() if self._active_job else 0
        self._session_count += n
        self.settings["print_count_total"] = int(self.settings.get("print_count_total", 0)) + n
        self.queue_panel.increment_print_counter(n)
        self._finish_item_job(True)
        self.persist_settings("print done")  # counter on disk right away
        log.info("Counter: +%d → total %d (session %d)", n, self.settings["print_count_total"],
                 self._session_count)
        self.statusBar().showMessage(msg, 8000)
        if not self._queue:
            short = f"נשמר לקובץ PDF: {Path(msg.split(': ', 1)[1]).name}" if msg.startswith("נשמר: ") else msg
            self.toast.show_message(short, "success", 2500)

    def _on_failed(self, msg: str) -> None:
        self._finish_item_job(False, msg)
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
        self.submit_job(self._make_job(path, 1, item.id))

    # ================================================================ shutdown
    def closeEvent(self, event) -> None:
        QApplication.instance().removeEventFilter(self)
        for th in list(self._render_threads):
            th.wait(3000)
        if self._watcher:
            self._watcher.stop()
        if self._worker is not None:
            self._queue.clear()
            self._worker.cancel()
            self._worker.wait(5000)
        self.persist_settings("close")
        log.info("Main window closed – %d magnet(s) printed this session", self._session_count)
        super().closeEvent(event)
