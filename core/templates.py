"""Magnet templates: data model, JSON save/load and fast Pillow rendering at 300 DPI.

Layer order (bottom → top):
    background color
    layers with z < 0          ("behind the photo", e.g. a texture under a rounded slot)
    photo slots                (transparent holes in the overlay – the photo shows here)
    layers with z >= 0         (text, logos – drawn over the photo)

    credit                     (photographer credit, vertical along a side edge – always on top)

Hebrew / RTL: rendered with libraqm when Pillow has it (full bidi + shaping);
otherwise falls back to python-bidi reordering, so Hebrew is never reversed.

Dual orientation: a TemplatePair holds a "portrait" and a "landscape" Template in one JSON
file; pick_variant() chooses the one matching the camera photo (after EXIF rotation).
"""
from __future__ import annotations

import json
import re
import shutil
import uuid
from dataclasses import asdict, dataclass, field, fields
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageOps

from core.sizes import DPI, MAGNET_SIZES, get_size

TEMPLATE_VERSION = 2
ROOT = Path(__file__).resolve().parent.parent

_RTL_CHARS = re.compile(r"[\u0590-\u05FF\u0600-\u06FF\uFB1D-\uFDFF\uFE70-\uFEFF]")


def _new_id() -> str:
    return uuid.uuid4().hex[:8]


# ============================================================== data model

PORTRAIT, LANDSCAPE = "portrait", "landscape"


@dataclass
class CanvasConfig:
    profile: str = "7.5x10"
    width: int = 0          # px @ 300 DPI
    height: int = 0
    bg_color: str = "#FFFFFFFF"
    orientation: str = ""   # portrait | landscape ("" = infer from width/height)

    def __post_init__(self):
        if not self.width or not self.height:
            w, h = get_size(self.profile).size_px
            if self.orientation == LANDSCAPE:
                w, h = max(w, h), min(w, h)
            elif self.orientation == PORTRAIT:
                w, h = min(w, h), max(w, h)
            self.width, self.height = w, h
        if self.orientation not in (PORTRAIT, LANDSCAPE):
            self.orientation = LANDSCAPE if self.width > self.height else PORTRAIT

    @classmethod
    def from_profile(cls, profile: str, bg_color: str = "#FFFFFFFF",
                     orientation: str = PORTRAIT) -> "CanvasConfig":
        """Profile sizes are portrait (e.g. 7.5x10 → 886x1181); landscape swaps them."""
        return cls(profile, 0, 0, bg_color, orientation)


@dataclass
class PhotoSlot:
    x: int
    y: int
    w: int
    h: int
    radius: int = 0          # rounded corners (px)
    id: str = field(default_factory=_new_id)


@dataclass
class TextLayer:
    text: str = "טקסט"
    x: int = 0
    y: int = 0
    width: int = 0           # box width; 0 = auto (fit text)
    font_family: str = ""    # "" = default font with Hebrew support
    font_path: str = ""      # explicit .ttf/.otf (overrides family)
    font_size: int = 80      # px @ 300 DPI (≈ 19pt)
    bold: bool = False
    color: str = "#000000FF"
    align: str = "center"    # right | center | left
    direction: str = "auto"  # auto | rtl | ltr
    line_spacing: float = 1.0
    stroke_width: int = 0
    stroke_color: str = "#FFFFFFFF"
    z: int = 10
    id: str = field(default_factory=_new_id)


@dataclass
class GraphicLayer:
    path: str
    x: int = 0
    y: int = 0
    w: int = 0               # 0 = native size
    h: int = 0
    opacity: float = 1.0
    z: int = 5
    id: str = field(default_factory=_new_id)


@dataclass
class CreditLayer:
    """Photographer credit: one line of text, rotated 90° and pinned along a side edge.

    Rendered with an exact transpose (no resampling) so it stays pixel-sharp.
    rotation 90 = counter-clockwise, 270 = clockwise. For Hebrew (RTL) the line starts at its
    right end, so 90 reads top → bottom and 270 reads bottom → top.
    """
    text: str = "שחר לוי גונן | 0525860073"
    side: str = "right"          # right | left
    rotation: int = 90           # 90 | 270
    font_family: str = "Heebo"
    font_size: int = 0           # px @ 300 DPI; 0 = auto (3% of the short canvas side)
    bold: bool = False
    color: str = "#6C757DFF"     # subtle grey
    align: str = "center"        # center | top | bottom  (position along the edge)
    margin: int = -1             # gap between the text and the canvas edge, px; -1 = auto
    enabled: bool = True

    def size_px(self, canvas: "CanvasConfig") -> int:
        return self.font_size or max(14, round(min(canvas.width, canvas.height) * 0.03))

    def edge_margin(self, canvas: "CanvasConfig") -> int:
        return self.margin if self.margin >= 0 else max(6, round(self.size_px(canvas) * 0.45))

    def strip_width(self, canvas: "CanvasConfig") -> int:
        """Width of the side strip the credit occupies (for layout reservation)."""
        f = get_font(self.font_family, self.size_px(canvas), self.bold)
        a, d = f.getmetrics()
        return self.edge_margin(canvas) + a + d


@dataclass
class Template:
    name: str = "תבנית חדשה"
    canvas: CanvasConfig = field(default_factory=CanvasConfig)
    slots: list[PhotoSlot] = field(default_factory=list)
    texts: list[TextLayer] = field(default_factory=list)
    graphics: list[GraphicLayer] = field(default_factory=list)
    credit: CreditLayer | None = None
    version: int = TEMPLATE_VERSION

    @property
    def orientation(self) -> str:
        return self.canvas.orientation

    @classmethod
    def new(cls, profile: str = "7.5x10", name: str = "תבנית חדשה",
            slot_preset: str | None = "full") -> "Template":
        t = cls(name=name, canvas=CanvasConfig.from_profile(profile))
        if slot_preset:
            t.slots = slot_preset_layout(t.canvas, slot_preset)
        return t

    def layers(self) -> list[TextLayer | GraphicLayer]:
        """All drawable layers, sorted by z (stable)."""
        return sorted([*self.graphics, *self.texts], key=lambda l: l.z)


@dataclass
class TemplatePair:
    """Portrait + landscape versions of one frame design (saved as one JSON file)."""
    name: str = "מסגרת"
    variants: dict[str, Template] = field(default_factory=dict)

    @property
    def portrait(self) -> Template | None:
        return self.variants.get(PORTRAIT)

    @property
    def landscape(self) -> Template | None:
        return self.variants.get(LANDSCAPE)

    @property
    def profile(self) -> str:
        return next(iter(self.variants.values())).canvas.profile

    def pick(self, orientation: str) -> Template:
        """Variant for `orientation`, falling back to whatever exists."""
        return self.variants.get(orientation) or next(iter(self.variants.values()))


def photo_orientation(img_or_size) -> str:
    """'landscape' if wider than tall, else 'portrait' (square → portrait)."""
    w, h = img_or_size.size if hasattr(img_or_size, "size") else img_or_size
    return LANDSCAPE if w > h else PORTRAIT


def pick_variant(frame: "Template | TemplatePair", photo) -> Template:
    return frame.pick(photo_orientation(photo)) if isinstance(frame, TemplatePair) else frame


# ============================================================== slot presets

SLOT_PRESETS = {
    "full": "מלא (Full bleed)",
    "border": "עם שוליים ומקום לטקסט",
    "strip3": "סטריפ – 3 תמונות",
    "strip4": "סטריפ – 4 תמונות",
}


def slot_preset_layout(canvas: CanvasConfig, preset: str) -> list[PhotoSlot]:
    W, H = canvas.width, canvas.height
    if preset == "full":
        return [PhotoSlot(0, 0, W, H)]
    m = round(min(W, H) * 0.05)                 # side margin
    if preset == "border":
        footer = round(H * 0.18)
        return [PhotoSlot(m, m, W - 2 * m, H - m - footer)]
    if preset in ("strip3", "strip4"):
        n = 3 if preset == "strip3" else 4
        footer = round(H * 0.16)
        gap = round(m * 0.6)
        slot_h = (H - m - footer - gap * (n - 1)) // n
        return [PhotoSlot(m, m + i * (slot_h + gap), W - 2 * m, slot_h) for i in range(n)]
    raise ValueError(f"Unknown slot preset: {preset}")


# ============================================================== JSON

def _from_dict(cls, d: dict):
    names = {f.name for f in fields(cls)}
    return cls(**{k: v for k, v in d.items() if k in names})


def template_to_dict(t: Template) -> dict:
    return asdict(t)


def template_from_dict(d: dict, base_dir: Path | None = None) -> Template:
    t = Template(
        name=d.get("name", "תבנית"),
        canvas=_from_dict(CanvasConfig, d.get("canvas", {})),
        slots=[_from_dict(PhotoSlot, s) for s in d.get("slots", [])],
        texts=[_from_dict(TextLayer, s) for s in d.get("texts", [])],
        graphics=[_from_dict(GraphicLayer, s) for s in d.get("graphics", [])],
        credit=_from_dict(CreditLayer, d["credit"]) if d.get("credit") else None,
        version=d.get("version", TEMPLATE_VERSION),
    )
    if base_dir:  # graphic paths are stored relative to the JSON file
        for g in t.graphics:
            p = Path(g.path)
            if not p.is_absolute():
                g.path = str((base_dir / p).resolve())
        for tx in t.texts:
            if tx.font_path and not Path(tx.font_path).is_absolute():
                tx.font_path = str((base_dir / tx.font_path).resolve())
    return t


def _portable_dict(t: Template, path: Path, copy_assets: bool) -> dict:
    """Template → dict with asset paths relative to `path` (assets copied to <stem>_assets/)."""
    assets_dir = path.parent / f"{path.stem}_assets"
    data = template_to_dict(t)

    def portable(src: str) -> str:
        p = Path(src).resolve()
        outside = path.parent.resolve() not in p.parents
        scratch = "_generated" in p.parts  # generator output is temporary → always copy
        if copy_assets and p.exists() and (outside or scratch):
            assets_dir.mkdir(exist_ok=True)
            dst = assets_dir / p.name
            if p != dst.resolve():
                shutil.copy2(p, dst)
            p = dst.resolve()
        try:
            return p.relative_to(path.parent.resolve()).as_posix()
        except ValueError:
            return str(p)

    for g in data["graphics"]:
        g["path"] = portable(g["path"])
    for tx in data["texts"]:
        if tx["font_path"]:
            tx["font_path"] = portable(tx["font_path"])
    return data


def save_template(t: Template, path: str | Path, copy_assets: bool = True) -> Path:
    """Save as JSON. Graphics are copied next to the JSON so the template is portable."""
    path = Path(path).with_suffix(".json")
    path.parent.mkdir(parents=True, exist_ok=True)
    data = _portable_dict(t, path, copy_assets)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def save_frame(frame: "Template | TemplatePair", path: str | Path, copy_assets: bool = True) -> Path:
    """Save a single template or a portrait/landscape pair (one JSON file)."""
    if isinstance(frame, Template):
        return save_template(frame, path, copy_assets)
    path = Path(path).with_suffix(".json")
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {"kind": "pair", "version": TEMPLATE_VERSION, "name": frame.name,
            "variants": {k: _portable_dict(v, path, copy_assets) for k, v in frame.variants.items()}}
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def load_frame(path: str | Path) -> "Template | TemplatePair":
    """Load a single template or a portrait/landscape pair."""
    path = Path(path)
    d = json.loads(path.read_text(encoding="utf-8"))
    if d.get("kind") == "pair":
        return TemplatePair(name=d.get("name", path.stem),
                            variants={k: template_from_dict(v, path.parent) for k, v in d["variants"].items()})
    return template_from_dict(d, path.parent)


def load_template(path: str | Path, orientation: str = PORTRAIT) -> Template:
    """Load one Template. For a pair file, returns the requested variant (portrait by default)."""
    frame = load_frame(path)
    return frame.pick(orientation) if isinstance(frame, TemplatePair) else frame


# ============================================================== fonts
# (font discovery / Qt registration / Pillow mapping live in core/fonts.py)

from core.fonts import (DEFAULT_FAMILIES, FONTS_DIR, HAS_RAQM, available_font_families,  # noqa: E402,F401
                        font_index, get_font, resolve_font_path)


# ============================================================== colors

def parse_color(c: str) -> tuple[int, int, int, int]:
    """'#RGB', '#RRGGBB' or '#RRGGBBAA' → RGBA tuple."""
    c = c.strip().lstrip("#")
    if len(c) == 3:
        c = "".join(ch * 2 for ch in c)
    if len(c) == 6:
        c += "FF"
    return tuple(int(c[i:i + 2], 16) for i in (0, 2, 4, 6))  # type: ignore[return-value]


# ============================================================== text rendering

def is_rtl(text: str) -> bool:
    return bool(_RTL_CHARS.search(text))


def _bidi_display(line: str) -> str:
    """Visual reordering for when libraqm is unavailable."""
    try:
        from bidi import get_display          # python-bidi >= 0.5
    except ImportError:
        try:
            from bidi.algorithm import get_display  # python-bidi < 0.5
        except ImportError:
            return line[::-1] if is_rtl(line) else line
    return get_display(line)


def render_text_layer(layer: TextLayer) -> Image.Image:
    """Render one text layer to an RGBA image.

    The layout box is (width × line metrics), but glyphs may reach outside it – Hebrew
    nikud above the ascender, descenders, stroke, italic overhang. The image is padded
    to the real ink extents so nothing is clipped; img.info["offset"] = (dx, dy) is where
    the image's top-left sits relative to (layer.x, layer.y). Layout positions don't move.
    """
    font = get_font(layer.font_family, max(1, int(layer.font_size)), layer.bold, layer.font_path)
    lines = layer.text.split("\n") or [""]
    rtl_text = layer.direction == "rtl" or (layer.direction == "auto" and is_rtl(layer.text))
    stroke = max(0, int(layer.stroke_width))

    kw = {}
    if HAS_RAQM:
        # with raqm, fribidi handles mixed Hebrew/English/numbers per line
        if layer.direction in ("rtl", "ltr"):
            kw["direction"] = layer.direction
        shown = lines
    else:
        shown = [_bidi_display(l) for l in lines]

    ascent, descent = font.getmetrics()
    line_h = round((ascent + descent) * layer.line_spacing)
    widths = [font.getlength(s, **kw) if s else 0 for s in shown]
    box_w = max(1, int(layer.width) if layer.width > 0 else int(max(widths, default=0)) + 2 * stroke)
    box_h = max(1, line_h * len(shown) + (ascent + descent - line_h) + 2 * stroke)

    align = layer.align or ("right" if rtl_text else "left")
    placed = []  # (x, y, text) in layout-box coordinates
    ink = [0, 0, box_w, box_h]  # union of layout box and real glyph bounds
    for i, (s, w) in enumerate(zip(shown, widths)):
        if not s:
            continue
        if align == "center":
            x = (box_w - w) / 2
        elif align == "right":
            x = box_w - w - stroke
        else:
            x = stroke
        y = stroke + i * line_h
        l, t, r, b = font.getbbox(s, stroke_width=stroke, **kw)
        ink = [min(ink[0], x + l), min(ink[1], y + t), max(ink[2], x + r), max(ink[3], y + b)]
        placed.append((x, y, s))

    dx = int(max(0, -ink[0]) + 0.999)
    dy = int(max(0, -ink[1]) + 0.999)
    W = int(ink[2] + dx + 0.999) + 1
    H = int(ink[3] + dy + 0.999) + 1
    img = Image.new("RGBA", (max(1, W), max(1, H)), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    for x, y, s in placed:
        draw.text((x + dx, y + dy), s, font=font, fill=parse_color(layer.color),
                  stroke_width=stroke, stroke_fill=parse_color(layer.stroke_color), **kw)
    img.info["offset"] = (-dx, -dy)
    img.info["layout_size"] = (box_w, box_h)
    return img


# ============================================================== graphics

@lru_cache(maxsize=64)
def _load_png(path: str, mtime: float) -> Image.Image:
    return Image.open(path).convert("RGBA")


def render_graphic_layer(layer: GraphicLayer) -> Image.Image | None:
    p = Path(layer.path)
    if not p.exists():
        return None
    img = _load_png(str(p), p.stat().st_mtime)
    w, h = layer.w or img.width, layer.h or img.height
    if (w, h) != img.size:
        img = img.resize((max(1, int(w)), max(1, int(h))), Image.Resampling.LANCZOS)
    if layer.opacity < 1:
        img = img.copy()
        img.putalpha(img.getchannel("A").point(lambda a: int(a * max(0.0, layer.opacity))))
    return img


def _composite(base: Image.Image, img: Image.Image, x: int, y: int) -> None:
    """alpha_composite that tolerates layers partly off-canvas."""
    x, y = int(x), int(y)
    left, top = max(0, -x), max(0, -y)
    right, bottom = min(img.width, base.width - x), min(img.height, base.height - y)
    if right <= left or bottom <= top:
        return
    base.alpha_composite(img, dest=(x + left, y + top), source=(left, top, right, bottom))


def _draw_layer(base: Image.Image, layer) -> None:
    if isinstance(layer, TextLayer):
        if layer.text.strip():
            img = render_text_layer(layer)
            ox, oy = img.info.get("offset", (0, 0))
            _composite(base, img, layer.x + ox, layer.y + oy)
    else:
        g = render_graphic_layer(layer)
        if g is not None:
            _composite(base, g, layer.x, layer.y)


def _slots_mask(t: Template) -> Image.Image:
    """L mask: 255 = overlay visible, 0 = photo hole."""
    mask = Image.new("L", (t.canvas.width, t.canvas.height), 255)
    draw = ImageDraw.Draw(mask)
    for s in t.slots:
        box = (s.x, s.y, s.x + s.w - 1, s.y + s.h - 1)
        if s.radius > 0:
            draw.rounded_rectangle(box, radius=s.radius, fill=0)
        else:
            draw.rectangle(box, fill=0)
    return mask


# ============================================================== public render API

def render_credit_layer(credit: CreditLayer, canvas: CanvasConfig) -> tuple[Image.Image, int, int]:
    """Credit text rotated by an exact transpose; returns (RGBA image, x, y) on the canvas."""
    size = credit.size_px(canvas)
    layer = TextLayer(text=credit.text, font_family=credit.font_family, font_size=size, bold=credit.bold,
                      color=credit.color, align="center", direction="auto")
    img = render_text_layer(layer)
    # tight crop around the ink (keeps the line metrics in the rotated direction stable)
    bbox = img.getchannel("A").getbbox() or (0, 0, img.width, img.height)
    img = img.crop((bbox[0], 0, bbox[2], img.height))  # full line height kept → stable strip width
    method = Image.Transpose.ROTATE_90 if credit.rotation == 90 else Image.Transpose.ROTATE_270
    rot = img.transpose(method)   # lossless: pixels are moved, never resampled
    margin = credit.edge_margin(canvas)
    x = margin if credit.side == "left" else canvas.width - margin - rot.width
    if credit.align == "top":
        y = margin
    elif credit.align == "bottom":
        y = canvas.height - margin - rot.height
    else:
        y = (canvas.height - rot.height) // 2
    return rot, int(x), int(y)


def render_overlay_frame(t: Template) -> Image.Image:
    """Transparent PNG frame: background + graphics + text, photo slots left transparent."""
    c = t.canvas
    frame = Image.new("RGBA", (c.width, c.height), parse_color(c.bg_color))
    layers = t.layers()
    for layer in (l for l in layers if l.z < 0):
        _draw_layer(frame, layer)
    if t.slots:
        frame.putalpha(ImageChops.multiply(frame.getchannel("A"), _slots_mask(t)))
    for layer in (l for l in layers if l.z >= 0):
        _draw_layer(frame, layer)
    if t.credit is not None and t.credit.enabled and t.credit.text.strip():
        img, x, y = render_credit_layer(t.credit, c)
        _composite(frame, img, x, y)
    frame.info["dpi"] = (DPI, DPI)
    return frame


def compose_magnet(t: Template, photos: list[Image.Image], overlay: Image.Image | None = None,
                   photo_filter=None) -> Image.Image:
    """Final RGB magnet: photos fitted into slots (cycled if fewer photos than slots), frame on top.
    photo_filter(img) -> img is applied to each fitted slot photo (e.g. the print enhancer)."""
    c = t.canvas
    out = Image.new("RGBA", (c.width, c.height), (255, 255, 255, 255))
    for i, s in enumerate(t.slots):
        if not photos:
            break
        photo = ImageOps.fit(photos[i % len(photos)].convert("RGB"), (s.w, s.h),
                             method=Image.Resampling.LANCZOS)
        if photo_filter:
            photo = photo_filter(photo)
        photo = photo.convert("RGBA")
        out.alpha_composite(photo, dest=(s.x, s.y))
    out.alpha_composite(overlay if overlay is not None else render_overlay_frame(t))
    result = out.convert("RGB")
    result.info["dpi"] = (DPI, DPI)
    return result


def compose_auto(frame: "Template | TemplatePair", photos: list[Image.Image], photo_filter=None) -> Image.Image:
    """Pick the variant matching the first photo's orientation, then compose."""
    return compose_magnet(pick_variant(frame, photos[0]), photos, photo_filter=photo_filter)


def export_frame_png(t: Template, path: str | Path) -> Path:
    """Export the overlay as a ready-to-use transparent PNG at 300 DPI."""
    path = Path(path).with_suffix(".png")
    path.parent.mkdir(parents=True, exist_ok=True)
    render_overlay_frame(t).save(path, dpi=(DPI, DPI))
    return path


def profiles() -> dict[str, str]:
    return {k: v.label for k, v in MAGNET_SIZES.items()}
