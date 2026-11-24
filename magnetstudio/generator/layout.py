"""Text and photo-slot layout: safe margins, auto-fitting text, slot presets, font choice."""

from __future__ import annotations

from magnetstudio.core.sizes import cm_to_px
from magnetstudio.core.templates import (
    CanvasConfig,
    PhotoSlot,
    TextLayer,
    font_index,
    get_font,
)

SERIF_HE = ["Noto Serif Hebrew", "Frank Ruehl CLM", "David", "Times New Roman", "FreeSerif"]
SANS_HE = ["Rubik", "Assistant", "Heebo", "Noto Sans Hebrew", "Arial", "Segoe UI", "DejaVu Sans"]


def _pick_family(prefer: list[str]) -> str:
    idx = {k.lower(): k for k in font_index()}
    for fam in prefer:
        if fam.lower() in idx:
            return idx[fam.lower()]
    return ""


# ============================================================== text layout helpers

def safe_margin(canvas: CanvasConfig) -> int:
    return max(cm_to_px(0.3), round(min(canvas.width, canvas.height) * 0.04))


def text_height(layer: TextLayer) -> int:
    f = get_font(layer.font_family, layer.font_size, layer.bold, layer.font_path)
    a, d = f.getmetrics()
    n = max(1, layer.text.count("\n") + 1)
    return round((a + d) * layer.line_spacing) * (n - 1) + a + d + 2 * layer.stroke_width


def fit_text(layer: TextLayer, max_w: int, min_size: int = 14) -> TextLayer:
    """Shrink font_size until every line fits in max_w."""
    while layer.font_size > min_size:
        f = get_font(layer.font_family, layer.font_size, layer.bold, layer.font_path)
        widest = max((f.getlength(line) for line in layer.text.split("\n") if line), default=0)
        if widest + 2 * layer.stroke_width <= max_w:
            break
        layer.font_size = max(min_size, int(layer.font_size * 0.93))
    return layer


def stack_texts(texts: list[TextLayer], x: int, y0: int, y1: int, width: int, gap: int) -> None:
    """Fit and vertically center a list of text layers inside [y0, y1]."""
    if not texts:
        return
    for t in texts:
        t.x, t.width = x, width
        fit_text(t, width)
    for _ in range(25):  # shrink everything together until the stack fits
        total = sum(text_height(t) for t in texts) + gap * (len(texts) - 1)
        if total <= (y1 - y0) or all(t.font_size <= 14 for t in texts):
            break
        for t in texts:
            t.font_size = max(14, int(t.font_size * 0.92))
    y = y0 + max(0, ((y1 - y0) - total) // 2)
    for t in texts:
        t.y = y
        y += text_height(t) + gap


def _overlaps(a: tuple[int, int, int, int], b: tuple[int, int, int, int]) -> bool:
    return a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]


# ============================================================== slots

def preset_slots(canvas: CanvasConfig, count: int, footer_frac: float, top_extra: int = 0) -> list[PhotoSlot]:
    W, H = canvas.width, canvas.height
    m = safe_margin(canvas)
    gap = round(m * 0.6)
    footer = round(H * footer_frac)
    top = m + top_extra
    avail_h = H - top - footer
    radius = round(min(W, H) * 0.02)
    if count <= 1:
        return [PhotoSlot(m, top, W - 2 * m, avail_h, radius)]
    if count == 2 and W / H > 0.5:  # side by side
        w = (W - 2 * m - gap) // 2
        return [PhotoSlot(m + i * (w + gap), top, w, avail_h, radius) for i in range(2)]
    h = (avail_h - gap * (count - 1)) // count  # vertical stack (strips)
    return [PhotoSlot(m, top + i * (h + gap), W - 2 * m, h, radius) for i in range(count)]


def default_slot_count(profile: str) -> int:
    return 3 if "strip" in profile else 1


# ---------- layout

def _text_w(t: TextLayer) -> float:
    f = get_font(t.font_family, t.font_size, t.bold, t.font_path)
    return f.getlength(t.text)
