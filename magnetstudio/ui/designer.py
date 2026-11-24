"""Template designer: QGraphicsView/QGraphicsScene editor for magnet frames.

Scene units = canvas pixels at 300 DPI, so what you place is what prints.
Text is previewed with the same Pillow renderer used for printing
(core.templates.render_text_layer) – Hebrew/RTL looks identical in both.
"""
from __future__ import annotations

from pathlib import Path

from PIL import Image
from PIL.ImageQt import ImageQt
from PyQt6.QtCore import QPointF, QRectF, Qt, pyqtSignal
from PyQt6.QtGui import (QAction, QBrush, QColor, QKeySequence, QPainter, QPen, QPixmap,
                         QShortcut)
from PyQt6.QtWidgets import (QCheckBox, QColorDialog, QComboBox, QDialog, QDockWidget,
                             QDoubleSpinBox, QFileDialog, QFormLayout, QGraphicsItem,
                             QGraphicsPixmapItem, QGraphicsRectItem, QGraphicsScene,
                             QGraphicsView, QLabel, QLineEdit, QMainWindow, QMessageBox,
                             QPlainTextEdit, QPushButton, QScrollArea, QSpinBox, QToolBar,
                             QVBoxLayout, QWidget)

from magnetstudio.core import fonts as font_registry
from magnetstudio.core.image_processor import load_image
from magnetstudio.core.settings import TEMPLATES_DIR, load_settings
from magnetstudio.core.templates import (LANDSCAPE, PORTRAIT, SLOT_PRESETS, CanvasConfig, CreditLayer, GraphicLayer,
                            PhotoSlot, Template, TemplatePair, TextLayer, compose_magnet,
                            export_frame_png, load_frame, parse_color, render_credit_layer,
                            render_graphic_layer, render_overlay_frame, render_text_layer,
                            save_frame, slot_preset_layout)
from magnetstudio.core.sizes import MAGNET_SIZES

PHOTO_PLANE_Z = -0.5   # slots sit between z<0 layers (behind photo) and z>=0 layers


def pil_to_pixmap(img: Image.Image) -> QPixmap:
    return QPixmap.fromImage(ImageQt(img.convert("RGBA")))


def qcolor(hex_rgba: str) -> QColor:
    r, g, b, a = parse_color(hex_rgba)
    return QColor(r, g, b, a)


def hex_rgba(c: QColor) -> str:
    return f"#{c.red():02X}{c.green():02X}{c.blue():02X}{c.alpha():02X}"


# ============================================================== scene items

class ResizeHandle(QGraphicsRectItem):
    """Bottom-right handle; dragging it resizes the parent item."""
    SIZE = 12

    def __init__(self, parent: "BoxItem"):
        super().__init__(-self.SIZE / 2, -self.SIZE / 2, self.SIZE, self.SIZE, parent)
        self.setBrush(QBrush(QColor("#1976d2")))
        self.setPen(QPen(Qt.GlobalColor.white, 1))
        self.setFlags(QGraphicsItem.GraphicsItemFlag.ItemIsMovable |
                      QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges |
                      QGraphicsItem.GraphicsItemFlag.ItemIgnoresTransformations)
        self.setCursor(Qt.CursorShape.SizeFDiagCursor)
        self.setZValue(10_000)
        self.hide()

    def itemChange(self, change, value):
        if change == QGraphicsItem.GraphicsItemChange.ItemPositionChange and self.parentItem():
            p: QPointF = value
            w, h = self.parentItem().resize_to(max(10, p.x()), max(10, p.y()))
            return QPointF(w, h)
        return super().itemChange(change, value)


class LayerItemMixin:
    """Common behaviour: movable, selectable, writes geometry back to its layer."""
    kind = "layer"

    def _init_flags(self, designer: "TemplateDesigner"):
        self.designer = designer
        self.setFlags(QGraphicsItem.GraphicsItemFlag.ItemIsMovable |
                      QGraphicsItem.GraphicsItemFlag.ItemIsSelectable |
                      QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges)
        self.setCursor(Qt.CursorShape.SizeAllCursor)

    def _layer_pos_changed(self, pos: QPointF):
        if getattr(self, "_syncing", False):
            return
        self.layer.x, self.layer.y = round(pos.x()), round(pos.y())
        self.designer.on_item_geometry_changed(self)

    def itemChange(self, change, value):
        if change == QGraphicsItem.GraphicsItemChange.ItemPositionChange:
            return QPointF(round(value.x()), round(value.y()))
        if change == QGraphicsItem.GraphicsItemChange.ItemPositionHasChanged:
            self._layer_pos_changed(value)
        if change == QGraphicsItem.GraphicsItemChange.ItemSelectedHasChanged:
            handle = getattr(self, "handle", None)
            if handle:
                handle.setVisible(bool(value))
        return super().itemChange(change, value)


class TextItem(LayerItemMixin, QGraphicsPixmapItem):
    kind = "text"

    def __init__(self, layer: TextLayer, designer):
        super().__init__()
        self.layer = layer
        self._init_flags(designer)
        self.sync_from_layer()

    def sync_from_layer(self):
        self._syncing = True
        try:
            img = render_text_layer(self.layer)
            self.setTransformationMode(Qt.TransformationMode.SmoothTransformation)  # zoomed canvas
            self.setPixmap(pil_to_pixmap(img))
            self.setOffset(*img.info.get("offset", (0, 0)))  # ink may extend past the layout box
            self.setPos(self.layer.x, self.layer.y)
            self.setZValue(self.layer.z)
        finally:
            self._syncing = False

    def paint(self, painter, option, widget=None):
        super().paint(painter, option, widget)
        if self.isSelected():
            painter.setPen(QPen(QColor("#1976d2"), 0, Qt.PenStyle.DashLine))
            painter.drawRect(self.boundingRect())

    def mouseDoubleClickEvent(self, event):
        self.designer.props.focus_text()
        super().mouseDoubleClickEvent(event)


class BoxItem(LayerItemMixin):
    """Items with an explicit w/h (graphics, slots) and a resize handle."""
    keep_aspect = False

    def resize_to(self, w: float, h: float) -> tuple[float, float]:
        if getattr(self, "_syncing", False):
            return self.box_size()
        if self.keep_aspect and self._aspect:
            h = w / self._aspect
        self.set_size(round(w), round(h))
        self.designer.on_item_geometry_changed(self)
        return self.box_size()


class GraphicItem(BoxItem, QGraphicsPixmapItem):
    kind = "graphic"
    keep_aspect = True

    def __init__(self, layer: GraphicLayer, designer):
        super().__init__()
        self.layer = layer
        self._init_flags(designer)
        src = Image.open(layer.path)
        self._aspect = src.width / src.height
        if not layer.w or not layer.h:
            layer.w, layer.h = src.size
        self.handle = ResizeHandle(self)
        self.sync_from_layer()

    def box_size(self):
        return self.layer.w, self.layer.h

    def set_size(self, w, h):
        self.layer.w, self.layer.h = max(1, w), max(1, h)
        img = render_graphic_layer(self.layer)
        self.setTransformationMode(Qt.TransformationMode.SmoothTransformation)
        self.setPixmap(pil_to_pixmap(img) if img else QPixmap(int(w), int(h)))

    def sync_from_layer(self):
        self._syncing = True
        try:
            self.set_size(self.layer.w, self.layer.h)
            self.setPos(self.layer.x, self.layer.y)
            self.setZValue(self.layer.z)
            self.handle.setPos(self.layer.w, self.layer.h)
        finally:
            self._syncing = False

    def paint(self, painter, option, widget=None):
        super().paint(painter, option, widget)
        if self.isSelected():
            painter.setPen(QPen(QColor("#1976d2"), 0, Qt.PenStyle.DashLine))
            painter.drawRect(self.boundingRect())


class SlotItem(BoxItem, QGraphicsRectItem):
    kind = "slot"

    def __init__(self, layer: PhotoSlot, designer, index: int):
        super().__init__()
        self.layer = layer
        self.index = index
        self._aspect = None
        self._init_flags(designer)
        self.handle = ResizeHandle(self)
        self.sync_from_layer()

    def box_size(self):
        return self.layer.w, self.layer.h

    def set_size(self, w, h):
        self.layer.w, self.layer.h = max(1, w), max(1, h)
        self.prepareGeometryChange()
        self.setRect(0, 0, self.layer.w, self.layer.h)

    def sync_from_layer(self):
        self._syncing = True
        try:
            self.set_size(self.layer.w, self.layer.h)
            self.setPos(self.layer.x, self.layer.y)
            self.setZValue(PHOTO_PLANE_Z)
            self.handle.setPos(self.layer.w, self.layer.h)
        finally:
            self._syncing = False

    def paint(self, painter: QPainter, option, widget=None):
        r = self.rect()
        sample: QPixmap | None = self.designer.sample_pixmap
        painter.save()
        if self.layer.radius:
            from PyQt6.QtGui import QPainterPath
            path = QPainterPath()
            path.addRoundedRect(r, self.layer.radius, self.layer.radius)
            painter.setClipPath(path)
        if sample:
            scaled = sample.scaled(int(r.width()), int(r.height()),
                                   Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                                   Qt.TransformationMode.SmoothTransformation)
            sx, sy = (scaled.width() - r.width()) / 2, (scaled.height() - r.height()) / 2
            painter.drawPixmap(r, scaled, QRectF(sx, sy, r.width(), r.height()))
        else:
            painter.fillRect(r, QColor(160, 170, 185, 150))
            painter.fillRect(r, QBrush(QColor(255, 255, 255, 90), Qt.BrushStyle.BDiagPattern))
            painter.setPen(QColor(40, 50, 70))
            f = painter.font()
            f.setPixelSize(max(14, int(min(r.width(), r.height()) / 8)))
            painter.setFont(f)
            painter.drawText(r, Qt.AlignmentFlag.AlignCenter, f"📷 תמונה {self.index + 1}")
        painter.restore()
        pen = QPen(QColor("#1976d2") if self.isSelected() else QColor(60, 70, 90), 0,
                   Qt.PenStyle.DashLine)
        painter.setPen(pen)
        painter.drawRect(r)


class CreditItem(QGraphicsPixmapItem):
    """Photographer credit – pinned to a side edge (selectable to edit, not draggable)."""
    kind = "credit"

    def __init__(self, credit: CreditLayer, designer):
        super().__init__()
        self.layer = credit
        self.designer = designer
        self.setFlags(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable)
        self.setToolTip("קרדיט צלם – קבוע בשולי הצד")
        self.sync_from_layer()

    def sync_from_layer(self):
        self.setTransformationMode(Qt.TransformationMode.SmoothTransformation)
        img, x, y = render_credit_layer(self.layer, self.designer.template.canvas)
        self.setPixmap(pil_to_pixmap(img))
        self.setPos(x, y)
        self.setZValue(9_000)
        self.setVisible(self.layer.enabled)

    def paint(self, painter, option, widget=None):
        super().paint(painter, option, widget)
        if self.isSelected():
            painter.setPen(QPen(QColor("#1976d2"), 0, Qt.PenStyle.DashLine))
            painter.drawRect(self.boundingRect())


# ============================================================== view

class CanvasView(QGraphicsView):
    def __init__(self, scene):
        super().__init__(scene)
        self.setRenderHints(QPainter.RenderHint.Antialiasing | QPainter.RenderHint.SmoothPixmapTransform)
        self.setDragMode(QGraphicsView.DragMode.RubberBandDrag)
        self.setBackgroundBrush(QColor("#3a3f47"))
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)

    def fit(self):
        self.fitInView(self.sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)

    def wheelEvent(self, e):
        if e.modifiers() & Qt.KeyboardModifier.ControlModifier:
            f = 1.15 if e.angleDelta().y() > 0 else 1 / 1.15
            self.scale(f, f)
        else:
            super().wheelEvent(e)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self.fit()


# ============================================================== properties panel

class ColorButton(QPushButton):
    changed = pyqtSignal(str)

    def __init__(self, color: str, alpha=True):
        super().__init__()
        self.alpha = alpha
        self.set_color(color)
        self.clicked.connect(self._pick)

    def set_color(self, color: str):
        self.color = color
        c = qcolor(color)
        self.setText(color)
        fg = "black" if c.lightness() > 128 else "white"
        self.setStyleSheet(f"background: rgba({c.red()},{c.green()},{c.blue()},{c.alpha()}); color:{fg};")

    def _pick(self):
        if self.alpha:
            c = QColorDialog.getColor(qcolor(self.color), self, "בחר צבע",
                                      QColorDialog.ColorDialogOption.ShowAlphaChannel)
        else:
            c = QColorDialog.getColor(qcolor(self.color), self, "בחר צבע")
        if c.isValid():
            self.set_color(hex_rgba(c))
            self.changed.emit(self.color)


class FontPicker(QComboBox):
    """Font combobox: custom fonts (assets/fonts) first, then system fonts.
    Each name is previewed in its own typeface. Live-refreshes when fonts are added."""
    family_changed = pyqtSignal(str)
    _instances: "list[FontPicker]" = []

    def __init__(self, family: str = "", parent=None):
        super().__init__(parent)
        self.setMaxVisibleItems(20)
        self.setMinimumWidth(170)
        self.populate(family)
        self.currentIndexChanged.connect(lambda _: self.family_changed.emit(self.currentData() or ""))
        FontPicker._instances.append(self)
        self.destroyed.connect(lambda *_: FontPicker._instances.remove(self)
                               if self in FontPicker._instances else None)

    def populate(self, select: str = "") -> None:
        from PyQt6.QtGui import QFont
        self.blockSignals(True)
        self.clear()
        self.addItem("(ברירת מחדל)", "")
        custom = font_registry.custom_font_families()
        if custom:
            self._header("— גופנים מותאמים (assets/fonts) —")
            for fam in custom:
                self.addItem("★ " + fam, fam)
                self.setItemData(self.count() - 1, QFont(font_registry.qt_family(fam), 11),
                                 Qt.ItemDataRole.FontRole)
            self._header("— גופני מערכת —")
        for fam in font_registry.system_font_families():
            self.addItem(fam, fam)
        self.set_family(select)
        self.blockSignals(False)

    def _header(self, text: str) -> None:
        self.addItem(text, None)
        model = self.model()
        item = model.item(self.count() - 1) if hasattr(model, "item") else None
        if item is not None:
            item.setEnabled(False)
            item.setSelectable(False)

    def set_family(self, family: str) -> None:
        idx = self.findData(family) if family else 0
        if idx < 0:  # case-insensitive / Qt alias match
            canon = font_registry.canonical_family(family)
            idx = self.findData(canon) if canon else -1
        blocked = self.blockSignals(True)
        self.setCurrentIndex(idx if idx >= 0 else 0)
        self.blockSignals(blocked)

    @classmethod
    def refresh_all(cls) -> None:
        for picker in list(cls._instances):
            try:
                picker.populate(picker.currentData() or "")
            except RuntimeError:  # widget already deleted
                cls._instances.remove(picker)


class PropertiesPanel(QScrollArea):
    def __init__(self, designer: "TemplateDesigner"):
        super().__init__()
        self.designer = designer
        self.item = None
        self._updating = False
        self._text_edit: QPlainTextEdit | None = None
        self._geo: dict[str, QSpinBox] = {}
        self.setWidgetResizable(True)
        self.setMinimumWidth(340)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.show_item(None)

    # ---- build
    def show_item(self, item):
        self.item = item
        self._geo, self._text_edit = {}, None
        w = QWidget()
        form = QFormLayout(w)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        form.setContentsMargins(12, 12, 12, 12)
        if item is None:
            self._canvas_form(form)
        elif item.kind == "credit":
            self._credit_form(form, item.layer)
        else:
            title = {"text": "טקסט", "graphic": "אלמנט גרפי", "slot": "חלון תמונה"}[item.kind]
            form.addRow(QLabel(f"<b>{title}</b>"))
            if item.kind == "text":
                self._text_form(form, item.layer)
            self._geometry_form(form, item)
            if item.kind == "graphic":
                keep = QCheckBox("שמור יחס גובה-רוחב")
                keep.setChecked(item.keep_aspect)
                keep.toggled.connect(lambda v: setattr(item, "keep_aspect", v))
                form.addRow(keep)
                op = QDoubleSpinBox(); op.setRange(0, 1); op.setSingleStep(0.05); op.setValue(item.layer.opacity)
                op.valueChanged.connect(lambda v: self._set(item, "opacity", v))
                form.addRow("שקיפות", op)
            if item.kind == "slot":
                rad = QSpinBox(); rad.setRange(0, 1000); rad.setValue(item.layer.radius)
                rad.valueChanged.connect(lambda v: self._set(item, "radius", v))
                form.addRow("פינות מעוגלות", rad)
            delete = QPushButton("מחק")
            delete.clicked.connect(self.designer.delete_selected)
            form.addRow(delete)
        self.setWidget(w)

    def _credit_form(self, form: QFormLayout, C: CreditLayer):
        d = self.designer
        form.addRow(QLabel("<b>קרדיט צלם</b>"))
        if d.pair is not None:
            form.addRow(QLabel("השינויים חלים על הגרסה האנכית והאופקית"))
        text = QLineEdit(C.text)
        text.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        text.textChanged.connect(lambda v: d.update_credit(text=v))
        form.addRow("טקסט", text)
        size = QSpinBox(); size.setRange(0, 400); size.setSpecialValueText("אוטומטי"); size.setValue(C.font_size)
        size.setSuffix(" px")
        size.valueChanged.connect(lambda v: d.update_credit(font_size=v))
        form.addRow("גודל", size)
        color = ColorButton(C.color)
        color.changed.connect(lambda v: d.update_credit(color=v))
        form.addRow("צבע", color)
        side = QComboBox()
        side.addItem("ימין", "right"); side.addItem("שמאל", "left")
        side.setCurrentIndex(side.findData(C.side))
        side.currentIndexChanged.connect(lambda _: d.update_credit(side=side.currentData()))
        form.addRow("צד", side)
        rot = QComboBox()
        rot.addItem("↺ נגד כיוון השעון (עברית נקראת מלמעלה למטה)", 90)
        rot.addItem("↻ עם כיוון השעון (עברית נקראת מלמטה למעלה)", 270)
        rot.setCurrentIndex(rot.findData(C.rotation))
        rot.currentIndexChanged.connect(lambda _: d.update_credit(rotation=rot.currentData()))
        form.addRow("כיוון", rot)
        align = QComboBox()
        for label, val in (("מרכז", "center"), ("למעלה", "top"), ("למטה", "bottom")):
            align.addItem(label, val)
        align.setCurrentIndex(align.findData(C.align))
        align.currentIndexChanged.connect(lambda _: d.update_credit(align=align.currentData()))
        form.addRow("מיקום", align)
        remove = QPushButton("הסר קרדיט")
        remove.clicked.connect(d.delete_selected)
        form.addRow(remove)

    def _canvas_form(self, form: QFormLayout):
        t = self.designer.template
        form.addRow(QLabel("<b>קנבס</b>"))
        name = QLineEdit(t.name)
        name.textChanged.connect(lambda v: setattr(t, "name", v))
        form.addRow("שם תבנית", name)
        form.addRow("גודל", QLabel(f"{t.canvas.width} x {t.canvas.height} px @ 300 DPI"))
        bg = ColorButton(t.canvas.bg_color)
        bg.changed.connect(self.designer.set_background)
        form.addRow("רקע", bg)
        form.addRow(QLabel("בחר אלמנט כדי לערוך אותו.\n"
                           "Z שלילי = מאחורי התמונה, Z ≥ 0 = מעל התמונה."))

    def _text_form(self, form: QFormLayout, L: TextLayer):
        te = QPlainTextEdit(L.text)
        te.setFixedHeight(80)
        te.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        te.textChanged.connect(lambda: self._set(self.item, "text", te.toPlainText()))
        self._text_edit = te
        form.addRow("טקסט", te)

        self.font_picker = FontPicker(L.font_family)
        self.font_picker.family_changed.connect(lambda fam: self._set_font_family(fam))
        form.addRow("גופן", self.font_picker)

        add_font = QPushButton("➕ הוסף גופן מהמחשב…")
        add_font.setToolTip("מעתיק TTF/OTF לתיקיית assets/fonts ומוסיף אותו מיד לרשימה")
        add_font.clicked.connect(self._add_font_from_disk)
        form.addRow("", add_font)
        if L.font_path:
            form.addRow("", QLabel(f"קובץ מוצמד: {Path(L.font_path).name}"))

        size = QSpinBox(); size.setRange(6, 2000); size.setValue(L.font_size); size.setSuffix(" px")
        size.valueChanged.connect(lambda v: self._set(self.item, "font_size", v))
        form.addRow("גודל", size)

        bold = QCheckBox("מודגש"); bold.setChecked(L.bold)
        bold.toggled.connect(lambda v: self._set(self.item, "bold", v))
        form.addRow(bold)

        color = ColorButton(L.color)
        color.changed.connect(lambda v: self._set(self.item, "color", v))
        form.addRow("צבע", color)

        align = QComboBox()
        for label, val in (("ימין", "right"), ("מרכז", "center"), ("שמאל", "left")):
            align.addItem(label, val)
        align.setCurrentIndex(align.findData(L.align))
        align.currentIndexChanged.connect(lambda _: self._set(self.item, "align", align.currentData()))
        form.addRow("יישור", align)

        direction = QComboBox()
        for label, val in (("אוטומטי", "auto"), ("ימין-לשמאל (RTL)", "rtl"), ("שמאל-לימין (LTR)", "ltr")):
            direction.addItem(label, val)
        direction.setCurrentIndex(direction.findData(L.direction))
        direction.currentIndexChanged.connect(lambda _: self._set(self.item, "direction", direction.currentData()))
        form.addRow("כיוון", direction)

        spacing = QDoubleSpinBox(); spacing.setRange(0.5, 3); spacing.setSingleStep(0.05); spacing.setValue(L.line_spacing)
        spacing.valueChanged.connect(lambda v: self._set(self.item, "line_spacing", v))
        form.addRow("ריווח שורות", spacing)

        stroke = QSpinBox(); stroke.setRange(0, 100); stroke.setValue(L.stroke_width)
        stroke.valueChanged.connect(lambda v: self._set(self.item, "stroke_width", v))
        form.addRow("קו מתאר", stroke)
        stroke_c = ColorButton(L.stroke_color)
        stroke_c.changed.connect(lambda v: self._set(self.item, "stroke_color", v))
        form.addRow("צבע קו מתאר", stroke_c)

    def _geometry_form(self, form: QFormLayout, item):
        L = item.layer
        fields_ = [("x", "X"), ("y", "Y")]
        if item.kind == "text":
            fields_ += [("width", "רוחב תיבה (0=אוטו)")]
        else:
            fields_ += [("w", "רוחב"), ("h", "גובה")]
        if item.kind != "slot":
            fields_ += [("z", "Z (שכבה)")]
        for attr, label in fields_:
            sb = QSpinBox()
            sb.setRange(-100 if attr == "z" else -5000, 100 if attr == "z" else 10000)
            sb.setValue(int(getattr(L, attr)))
            sb.valueChanged.connect(lambda v, a=attr: self._set(self.item, a, v))
            self._geo[attr] = sb
            form.addRow(label, sb)

    # ---- updates
    def _set(self, item, attr, value):
        if self._updating or item is None:
            return
        setattr(item.layer, attr, value)
        if attr == "w" and getattr(item, "keep_aspect", False) and item._aspect:
            item.layer.h = round(value / item._aspect)
        item.sync_from_layer()
        self.refresh_geometry()
        self.designer.mark_dirty()

    def _set_font_family(self, family: str):
        if self.item is not None and self.item.layer.font_path:
            self.item.layer.font_path = ""  # picking a family replaces a pinned file
        self._set(self.item, "font_family", family)

    def _add_font_from_disk(self, path: str | None = None):
        if path is None:
            path, _ = QFileDialog.getOpenFileName(self, "בחר קובץ גופן", "", "Fonts (*.ttf *.otf)")
        if not path:
            return None
        try:
            family = font_registry.add_font_file(path)
        except Exception as e:
            QMessageBox.warning(self, "הוספת גופן נכשלה", str(e))
            return None
        FontPicker.refresh_all()
        if self.item is not None and self.item.kind == "text":
            self._set_font_family(family)
            self.font_picker.set_family(family)
        self.designer.statusBar().showMessage(f"הגופן '{family}' נוסף ל-assets/fonts", 5000)
        return family

    def refresh_geometry(self):
        if not self.item:
            return
        self._updating = True
        try:
            for attr, sb in self._geo.items():
                sb.setValue(int(getattr(self.item.layer, attr)))
        finally:
            self._updating = False

    def focus_text(self):
        if self._text_edit:
            self._text_edit.setFocus()
            self._text_edit.selectAll()


# ============================================================== designer window

class TemplateDesigner(QMainWindow):
    template_saved = pyqtSignal(str)   # JSON path
    frame_exported = pyqtSignal(str)   # PNG path

    def __init__(self, template: "Template | TemplatePair | None" = None, path: str | Path | None = None,
                 profile: str = "7.5x10", parent=None):
        super().__init__(parent)
        self.setWindowFlag(Qt.WindowType.Window)
        self.pair: TemplatePair | None = None
        self.variant = PORTRAIT
        self._set_frame(template or Template.new(profile, slot_preset="border"))
        self.path: Path | None = Path(path) if path else None
        self.sample_pixmap: QPixmap | None = None
        self._dirty = False

        self.scene = QGraphicsScene(self)
        self.scene.selectionChanged.connect(self._on_selection)
        self.view = CanvasView(self.scene)
        self.setCentralWidget(self.view)

        self.props = PropertiesPanel(self)
        dock = QDockWidget("מאפיינים", self)
        dock.setWidget(self.props)
        dock.setFeatures(QDockWidget.DockWidgetFeature.NoDockWidgetFeatures)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, dock)

        self._build_toolbar()
        for key in (QKeySequence(QKeySequence.StandardKey.Delete), QKeySequence("Backspace")):
            sc = QShortcut(key, self.view)  # only while the canvas has focus
            sc.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
            sc.activated.connect(self.delete_selected)
        QShortcut(QKeySequence(QKeySequence.StandardKey.Save), self).activated.connect(lambda: self.save())

        self.resize(1200, 820)
        self.rebuild_scene()
        self._update_title()

    # ---- toolbar
    def _build_toolbar(self):
        tb = QToolBar("כלים")
        tb.setMovable(False)
        self.addToolBar(tb)

        self.profile_box = QComboBox()
        for key, size in MAGNET_SIZES.items():
            self.profile_box.addItem(size.label, key)
        self.profile_box.setCurrentIndex(self.profile_box.findData(self.template.canvas.profile))
        self.profile_box.currentIndexChanged.connect(self._change_profile)
        tb.addWidget(QLabel(" גודל: "))
        tb.addWidget(self.profile_box)
        self.orient_box = QComboBox()
        self.orient_box.addItem("▯ אנכי", PORTRAIT)
        self.orient_box.addItem("▭ אופקי", LANDSCAPE)
        self.orient_box.currentIndexChanged.connect(self._switch_variant)
        tb.addWidget(QLabel(" כיוון: "))
        tb.addWidget(self.orient_box)
        tb.addSeparator()

        from magnetstudio.ui.frame_generator_dialog import ACCENT_BUTTON_CSS
        self.ai_btn = QPushButton("✨ מחולל AI")
        self.ai_btn.setToolTip("צור מסגרת מתיאור חופשי (Gemini / אופליין)")
        self.ai_btn.setStyleSheet(ACCENT_BUTTON_CSS)
        self.ai_btn.clicked.connect(self.open_ai_generator)
        tb.addWidget(self.ai_btn)
        tb.addSeparator()

        def act(text, slot, tip=""):
            a = QAction(text, self)
            a.setToolTip(tip or text)
            a.triggered.connect(slot)
            tb.addAction(a)
            return a

        act("＋ טקסט", self.add_text, "הוסף שכבת טקסט חי")
        act("＋ גרפיקה", self.add_graphic, "הוסף PNG שקוף (לוגו / אלמנט)")
        act("＋ חלון תמונה", self.add_slot, "הוסף חלון תמונה")
        act("＋ קרדיט צלם", self.add_credit, "קרדיט אנכי קבוע בשולי הצד")

        self.preset_box = QComboBox()
        self.preset_box.addItem("פריסת חלונות…", None)
        for key, label in SLOT_PRESETS.items():
            self.preset_box.addItem(label, key)
        self.preset_box.activated.connect(self._apply_preset)
        tb.addWidget(self.preset_box)
        tb.addSeparator()

        act("⬆ קדימה", lambda: self._shift_z(+1), "הבא שכבה קדימה")
        act("⬇ אחורה", lambda: self._shift_z(-1), "שלח שכבה אחורה")
        act("🗑", self.delete_selected, "מחק (Delete)")
        tb.addSeparator()
        act("🖼 תמונת דוגמה", self.load_sample, "הצג תמונת דוגמה בחלונות")
        act("👁 תצוגת הדפסה", self.preview_render, "רינדור Pillow כפי שיודפס")
        act("⤢ התאם", self.view.fit, "התאם לחלון")
        tb.addSeparator()
        act("📄 תבנית חדשה", self.new_template, "תבנית חדשה בפרופיל הנבחר")
        act("📂 טען תבנית", self.open_template, "טען תבנית JSON")
        act("💾 שמור תבנית", lambda: self.save(), "שמור כתבנית JSON ל-assets/templates (Ctrl+S)")
        act("⚡ ייצא לשימוש מיידי", lambda: self.export_to_main(), "מרנדר את המסגרת ומפעיל אותה בחלון הראשי")
        act("📤 ייצא PNG…", lambda: self.export_png(), "שמור מסגרת PNG למיקום לבחירתך")

    # ---- scene
    def rebuild_scene(self):
        self.scene.clear()
        c = self.template.canvas
        self.scene.setSceneRect(QRectF(-40, -40, c.width + 80, c.height + 80))
        self.bg_item = self.scene.addRect(QRectF(0, 0, c.width, c.height), QPen(Qt.PenStyle.NoPen),
                                          QBrush(qcolor(c.bg_color)))
        self.bg_item.setZValue(-10_000)
        for i, s in enumerate(self.template.slots):
            self.scene.addItem(SlotItem(s, self, i))
        for g in self.template.graphics:
            if Path(g.path).exists():
                self.scene.addItem(GraphicItem(g, self))
        for t in self.template.texts:
            self.scene.addItem(TextItem(t, self))
        self.credit_item = None
        if self.template.credit is not None:
            self.credit_item = CreditItem(self.template.credit, self)
            self.scene.addItem(self.credit_item)
        self._sync_orientation_box()
        self.view.fit()
        self.props.show_item(None)

    def _selected(self):
        items = [i for i in self.scene.selectedItems() if isinstance(i, (LayerItemMixin, CreditItem))]
        return items[0] if len(items) == 1 else None

    # ---- portrait / landscape pairs
    def _set_frame(self, frame: "Template | TemplatePair") -> None:
        if isinstance(frame, TemplatePair):
            self.pair = frame
            if self.variant not in frame.variants:
                self.variant = next(iter(frame.variants))
            self.template = frame.variants[self.variant]
        else:
            self.pair = None
            self.template = frame
            self.variant = frame.orientation

    def _sync_orientation_box(self) -> None:
        if not hasattr(self, "orient_box"):
            return
        self.orient_box.blockSignals(True)
        self.orient_box.setCurrentIndex(self.orient_box.findData(self.template.orientation))
        self.orient_box.setEnabled(self.pair is not None and len(self.pair.variants) > 1)
        self.orient_box.setToolTip("מעבר בין הגרסה האנכית לאופקית של המסגרת" if self.pair
                                   else "לתבנית הזו יש כיוון אחד בלבד")
        self.orient_box.blockSignals(False)

    def _switch_variant(self) -> None:
        o = self.orient_box.currentData()
        if self.pair is None or o not in self.pair.variants or o == self.variant:
            self._sync_orientation_box()
            return
        self.variant = o
        self.template = self.pair.variants[o]  # edits live in the pair's objects
        self.rebuild_scene()
        self._update_title()

    def frame(self) -> "Template | TemplatePair":
        return self.pair or self.template

    def _templates(self) -> list[Template]:
        return list(self.pair.variants.values()) if self.pair else [self.template]

    # ---- credit
    def add_credit(self) -> None:
        settings = getattr(self.parent(), "settings", None) or load_settings()
        text = settings.get("photographer_credit") or CreditLayer().text
        for t in self._templates():
            if t.credit is None:
                t.credit = CreditLayer(text=text)
            t.credit.enabled = True
        self.rebuild_scene()
        if self.credit_item:
            self._select_only(self.credit_item)
        self.mark_dirty()

    def update_credit(self, **changes) -> None:
        for t in self._templates():  # same credit on both orientations
            if t.credit is not None:
                for k, v in changes.items():
                    setattr(t.credit, k, v)
        if self.credit_item:
            self.credit_item.sync_from_layer()
        self.mark_dirty()

    def _on_selection(self):
        try:
            self.props.show_item(self._selected())
        except RuntimeError:  # scene being cleared
            pass

    def on_item_geometry_changed(self, item):
        if self.props.item is item:
            self.props.refresh_geometry()
        self.mark_dirty()

    def mark_dirty(self):
        if not self._dirty:
            self._dirty = True
            self._update_title()

    def _update_title(self):
        name = self.path.name if self.path else "ללא שם"
        which = ""
        if self.pair is not None:
            which = " · " + ("אנכי" if self.variant == PORTRAIT else "אופקי")
        self.setWindowTitle(f"עורך תבניות – {name}{which}{' *' if self._dirty else ''}")

    def _center(self, w, h):
        c = self.template.canvas
        return (c.width - w) // 2, (c.height - h) // 2

    def _select_only(self, item):
        self.scene.clearSelection()
        item.setSelected(True)

    # ---- add / remove
    def add_text(self):
        c = self.template.canvas
        layer = TextLayer(text="מזל טוב!", width=c.width - 2 * round(c.width * 0.05),
                          font_size=max(24, c.width // 10))
        layer.x = round(c.width * 0.05)
        layer.y = round(c.height * 0.85)
        self.template.texts.append(layer)
        item = TextItem(layer, self)
        self.scene.addItem(item)
        self._select_only(item)
        self.props.focus_text()
        self.mark_dirty()

    def add_graphic(self):
        path, _ = QFileDialog.getOpenFileName(self, "בחר PNG", "", "Images (*.png *.webp)")
        if path:
            self.add_graphic_from(path)

    def add_graphic_from(self, path: str) -> GraphicItem:
        c = self.template.canvas
        src = Image.open(path)
        scale = min(1.0, (c.width * 0.4) / src.width, (c.height * 0.4) / src.height)
        w, h = round(src.width * scale), round(src.height * scale)
        layer = GraphicLayer(path=str(Path(path).resolve()), w=w, h=h)
        layer.x, layer.y = self._center(w, h)
        self.template.graphics.append(layer)
        item = GraphicItem(layer, self)
        self.scene.addItem(item)
        self._select_only(item)
        self.mark_dirty()
        return item

    def add_slot(self):
        c = self.template.canvas
        w, h = c.width // 2, c.height // 3
        slot = PhotoSlot(*self._center(w, h), w, h)
        self.template.slots.append(slot)
        item = SlotItem(slot, self, len(self.template.slots) - 1)
        self.scene.addItem(item)
        self._select_only(item)
        self.mark_dirty()

    def _apply_preset(self, index: int):
        key = self.preset_box.itemData(index)
        self.preset_box.setCurrentIndex(0)
        if not key:
            return
        self.template.slots = slot_preset_layout(self.template.canvas, key)
        self.rebuild_scene()
        self.mark_dirty()

    def delete_selected(self):
        for item in [i for i in self.scene.selectedItems() if isinstance(i, CreditItem)]:
            for t in self._templates():
                t.credit = None
            self.scene.removeItem(item)
            self.credit_item = None
        for item in [i for i in self.scene.selectedItems() if isinstance(i, LayerItemMixin)]:
            lst = {"text": self.template.texts, "graphic": self.template.graphics,
                   "slot": self.template.slots}[item.kind]
            lst.remove(item.layer)
            self.scene.removeItem(item)
        for i, it in enumerate(sorted((x for x in self.scene.items() if isinstance(x, SlotItem)),
                                      key=lambda s: self.template.slots.index(s.layer))):
            it.index = i
            it.update()
        self.props.show_item(None)
        self.mark_dirty()

    def _shift_z(self, delta: int):
        item = self._selected()
        if item and item.kind != "slot":
            item.layer.z += delta
            item.sync_from_layer()
            self.props.refresh_geometry()
            self.mark_dirty()

    # ---- canvas
    def set_background(self, color: str):
        self.template.canvas.bg_color = color
        self.bg_item.setBrush(QBrush(qcolor(color)))
        self.mark_dirty()

    def _change_profile(self):
        key = self.profile_box.currentData()
        if key == self.template.canvas.profile:
            return
        for tpl in self._templates():  # a pair changes size together, each keeps its orientation
            old = tpl.canvas
            new = CanvasConfig.from_profile(key, old.bg_color, old.orientation)
            sx, sy = new.width / old.width, new.height / old.height
            for s in tpl.slots:  # stretch slots to the new canvas
                s.x, s.y, s.w, s.h = round(s.x * sx), round(s.y * sy), round(s.w * sx), round(s.h * sy)
            k = min(sx, sy)
            for g in tpl.graphics:  # keep graphics' aspect ratio
                g.x, g.y, g.w, g.h = round(g.x * sx), round(g.y * sy), round(g.w * k), round(g.h * k)
            for t in tpl.texts:
                t.x, t.y = round(t.x * sx), round(t.y * sy)
                t.width, t.font_size = round(t.width * sx), max(6, round(t.font_size * k))
            tpl.canvas = new
        self.rebuild_scene()
        self.mark_dirty()

    def load_sample(self):
        path, _ = QFileDialog.getOpenFileName(self, "תמונת דוגמה", "", "Images (*.jpg *.jpeg *.png *.webp)")
        if path:
            self.set_sample_image(load_image(path))

    def set_sample_image(self, img: Image.Image):
        self.sample_pixmap = pil_to_pixmap(img)
        for it in self.scene.items():
            if isinstance(it, SlotItem):
                it.update()

    def preview_render(self):
        if self.sample_pixmap:
            photo = Image.fromqpixmap(self.sample_pixmap)
            img = compose_magnet(self.template, [photo])
        else:
            img = render_overlay_frame(self.template)
        dlg = QDialog(self)
        dlg.setWindowTitle("תצוגת הדפסה (300 DPI)")
        lay = QVBoxLayout(dlg)
        lbl = QLabel()
        pix = pil_to_pixmap(img)
        lbl.setPixmap(pix.scaled(560, 760, Qt.AspectRatioMode.KeepAspectRatio,
                                 Qt.TransformationMode.SmoothTransformation))
        lbl.setStyleSheet("background: repeating-conic-gradient(#ddd 0% 25%, #fff 0% 50%) 50% / 20px 20px;")
        lay.addWidget(lbl)
        lay.addWidget(QLabel(f"{img.width} x {img.height} px"))
        dlg.exec()

    # ---- files
    def _default_path(self, suffix: str) -> Path:
        name = self.pair.name if self.pair else self.template.name
        safe = "".join(ch for ch in name if ch.isalnum() or ch in " _-").strip() or "template"
        return (self.path.with_suffix(suffix) if self.path
                else TEMPLATES_DIR / f"{safe}_{self.template.canvas.profile}{suffix}")

    def save(self, path: str | Path | None = None) -> Path | None:
        if path is None:
            if self.path is None:
                chosen, _ = QFileDialog.getSaveFileName(self, "שמור תבנית", str(self._default_path(".json")),
                                                        "Template (*.json)")
                if not chosen:
                    return None
                path = chosen
            else:
                path = self.path
        try:
            self.path = save_frame(self.frame(), path)
            # reload so graphic paths point at the copied assets
            self._set_frame(load_frame(self.path))
            self.rebuild_scene()
        except Exception as e:
            QMessageBox.warning(self, "שמירה נכשלה", str(e))
            return None
        self._dirty = False
        self._update_title()
        self.statusBar().showMessage(f"נשמר: {self.path}", 5000)
        self.template_saved.emit(str(self.path))
        return self.path

    def export_png(self, path: str | Path | None = None) -> Path | None:
        if path is None:
            chosen, _ = QFileDialog.getSaveFileName(self, "ייצא מסגרת", str(self._default_path(".png")),
                                                    "PNG (*.png)")
            if not chosen:
                return None
            path = chosen
        out = export_frame_png(self.template, path)  # current orientation
        self.statusBar().showMessage(f"יוצא: {out}", 5000)
        self.frame_exported.emit(str(out))
        return out

    def export_to_main(self) -> Path:
        """Make this frame the active one in the main window.

        A portrait/landscape pair is saved as one JSON (so the main window keeps picking the
        variant per photo); a single template is rendered to a ready PNG overlay."""
        if self.pair is not None:
            out = save_frame(self.pair, TEMPLATES_DIR / self._default_path(".json").name)
            self.statusBar().showMessage(f"המסגרת (אנכי + אופקי) הופעלה בחלון הראשי: {out.name}", 5000)
            self.frame_exported.emit(str(out))
            return out
        out = export_frame_png(self.template, TEMPLATES_DIR / self._default_path(".png").name)
        self.statusBar().showMessage(f"המסגרת הופעלה בחלון הראשי: {out.name}", 5000)
        self.frame_exported.emit(str(out))
        return out

    # ---- AI generator
    def open_ai_generator(self):
        from magnetstudio.ui.frame_generator_dialog import FrameGeneratorDialog
        settings = getattr(self.parent(), "settings", None) or load_settings()
        dlg = FrameGeneratorDialog(self.template.canvas.profile, settings, self)
        dlg.template_ready.connect(self.apply_generated)
        dlg.exec()

    def apply_generated(self, frame: "Template | TemplatePair") -> None:
        """Replace the canvas with a generated template or pair (asks to save unsaved work first)."""
        if not self._confirm_discard():
            return
        self.variant = PORTRAIT
        self._set_frame(frame)
        self.path = None
        self.profile_box.blockSignals(True)
        self.profile_box.setCurrentIndex(self.profile_box.findData(self.template.canvas.profile))
        self.profile_box.blockSignals(False)
        self.rebuild_scene()
        self._dirty = True
        self._update_title()
        self.statusBar().showMessage("המסגרת נוצרה – אפשר לערוך, לשמור או לייצא", 6000)

    def new_template(self):
        if not self._confirm_discard():
            return
        self._set_frame(Template.new(self.profile_box.currentData(), slot_preset="border"))
        self.path = None
        self._dirty = False
        self.rebuild_scene()
        self._update_title()

    def open_template(self):
        if not self._confirm_discard():
            return
        path, _ = QFileDialog.getOpenFileName(self, "פתח תבנית", str(TEMPLATES_DIR), "Template (*.json)")
        if path:
            self._set_frame(load_frame(path))
            self.path = Path(path)
            self.profile_box.blockSignals(True)
            self.profile_box.setCurrentIndex(self.profile_box.findData(self.template.canvas.profile))
            self.profile_box.blockSignals(False)
            self._dirty = False
            self.rebuild_scene()
            self._update_title()

    def _confirm_discard(self) -> bool:
        if not self._dirty:
            return True
        r = QMessageBox.question(self, "שינויים לא שמורים", "לשמור את השינויים?",
                                 QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard |
                                 QMessageBox.StandardButton.Cancel)
        if r == QMessageBox.StandardButton.Save:
            return self.save() is not None
        return r == QMessageBox.StandardButton.Discard

    def closeEvent(self, e):
        if self._confirm_discard():
            e.accept()
        else:
            e.ignore()
