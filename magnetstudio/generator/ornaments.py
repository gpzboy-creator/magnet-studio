"""Procedural 300 DPI graphics: borders, hearts, rings, wreaths, olive branches, watercolor,
and the alpha hole punch that keeps photo windows 100% transparent."""

from __future__ import annotations

import uuid

from PIL import Image, ImageChops, ImageDraw

from magnetstudio.core.settings import TEMPLATES_DIR
from magnetstudio.core.templates import (
    CanvasConfig,
    PhotoSlot,
    parse_color,
)
from magnetstudio.generator.colors import _hex, _mix, _rgb
from magnetstudio.generator.layout import safe_margin
from magnetstudio.generator.styles import FrameStyle

GENERATED_DIR = TEMPLATES_DIR / "_generated"


# ============================================================== ornaments (procedural, 300 DPI)

def draw_ornament(canvas: CanvasConfig, style: str, accent: str, slots: list[PhotoSlot],
                  text_panel: tuple[int, int, int, int] | None = None, panel_color: str = "") -> Image.Image:
    W, H = canvas.width, canvas.height
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    ac = parse_color(accent)
    m = safe_margin(canvas)
    lw = max(2, round(W / 260))
    thin = max(1, lw // 2)

    if text_panel and panel_color:
        r, g, b, _ = parse_color(panel_color)
        d.rounded_rectangle(text_panel, radius=round(m * 0.6), fill=(r, g, b, 225))

    if style in ("classic", "moroccan"):
        o = round(m * 0.45)
        d.rectangle((o, o, W - 1 - o, H - 1 - o), outline=ac, width=lw)
        o2 = o + lw + max(4, round(W * 0.008))
        d.rectangle((o2, o2, W - 1 - o2, H - 1 - o2), outline=ac, width=thin)
    if style == "moroccan":  # small diamonds along the border + domes over the slots
        o = round(m * 0.45)
        step = max(24, round(W / 14))
        s = max(4, round(W / 120))
        for x in range(o + step // 2, W - o, step):
            for y in (o, H - 1 - o):
                d.polygon([(x, y - s), (x + s, y), (x, y + s), (x - s, y)], fill=ac)
        for sl in slots:
            dome_h = round(min(sl.w * 0.22, m * 1.6))
            if sl.y - dome_h > o + lw * 2:
                d.arc((sl.x, sl.y - dome_h, sl.x + sl.w, sl.y + dome_h), 180, 360, fill=ac, width=lw)
    if style == "corners":
        L = round(min(W, H) * 0.12)
        o = round(m * 0.5)
        for cx, cy, dx, dy in ((o, o, 1, 1), (W - 1 - o, o, -1, 1), (o, H - 1 - o, 1, -1), (W - 1 - o, H - 1 - o, -1, -1)):
            d.line([(cx, cy), (cx + dx * L, cy)], fill=ac, width=lw)
            d.line([(cx, cy), (cx, cy + dy * L)], fill=ac, width=lw)
            r = max(3, lw)
            d.ellipse((cx + dx * L - r, cy - r, cx + dx * L + r, cy + r), fill=ac)
            d.ellipse((cx - r, cy + dy * L - r, cx + r, cy + dy * L + r), fill=ac)
    if style != "minimal":  # thin outline around each photo window
        pad = max(3, round(W * 0.007))
        for sl in slots:
            box = (sl.x - pad, sl.y - pad, sl.x + sl.w - 1 + pad, sl.y + sl.h - 1 + pad)
            d.rounded_rectangle(box, radius=sl.radius + pad if sl.radius else 0, outline=ac, width=thin)
    else:  # minimal: short divider under the photos
        if slots:
            y = max(s.y + s.h for s in slots) + round(m * 0.6)
            d.line([(W * 0.4, y), (W * 0.6, y)], fill=ac, width=thin)
    return img


# ============================================================== alpha hole punch

def punch_alpha_holes(img: Image.Image, slots: list[PhotoSlot], bleed: int = 0) -> Image.Image:
    """Return an RGBA copy where every slot area (± bleed px) is 100% transparent."""
    out = img.convert("RGBA")
    mask = Image.new("L", out.size, 255)
    d = ImageDraw.Draw(mask)
    for s in slots:
        box = (s.x - bleed, s.y - bleed, s.x + s.w - 1 + bleed, s.y + s.h - 1 + bleed)
        if s.radius > 0:
            d.rounded_rectangle(box, radius=s.radius + bleed, fill=0)
        else:
            d.rectangle(box, fill=0)
    out.putalpha(ImageChops.multiply(out.getchannel("A"), mask))
    return out


def _save_generated(img: Image.Image, tag: str) -> str:
    GENERATED_DIR.mkdir(parents=True, exist_ok=True)
    path = GENERATED_DIR / f"{tag}_{uuid.uuid4().hex[:8]}.png"
    img.save(path, dpi=(300, 300))
    return str(path)


# ---------- procedural graphics (drawn at 4x, downscaled → smooth anti-aliased edges)

_SS = 4


def _finish(img: Image.Image, size: tuple[int, int]) -> Image.Image:
    return img.resize(size, Image.Resampling.LANCZOS)


def draw_heart(size: int, color: str) -> Image.Image:
    import math
    S = size * _SS
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    pts = []
    for i in range(400):
        t = 2 * math.pi * i / 400
        x = 16 * math.sin(t) ** 3
        y = 13 * math.cos(t) - 5 * math.cos(2 * t) - 2 * math.cos(3 * t) - math.cos(4 * t)
        pts.append((S / 2 + x * S / 34, S * 0.46 - y * S / 34))
    ImageDraw.Draw(img).polygon(pts, fill=parse_color(color))
    return _finish(img, (size, size))


def draw_rings(size: int, color: str) -> Image.Image:
    S = size * _SS
    img = Image.new("RGBA", (int(S * 1.4), S), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    r, w = S * 0.36, max(_SS * 2, int(S * 0.09))
    c = parse_color(color)
    for cx in (S * 0.5, S * 0.9):
        d.ellipse((cx - r, S / 2 - r, cx + r, S / 2 + r), outline=c, width=w)
    d.polygon([(S * 0.5, S * 0.06), (S * 0.43, S * 0.15), (S * 0.5, S * 0.21), (S * 0.57, S * 0.15)],
              fill=(255, 255, 255, 230))  # small stone highlight
    return _finish(img, (int(size * 1.4), size))


def _leaf(d: ImageDraw.ImageDraw, cx: float, cy: float, length: float, width: float, angle: float, fill) -> None:
    """Pointed lens-shaped leaf centered at (cx, cy) rotated by `angle` radians."""
    import math
    pts = []
    for i in range(24):
        t = i / 23
        x = (t - 0.5) * length
        y = width / 2 * math.sin(math.pi * t)
        pts.append((x, y))
    pts += [(x, -y) for x, y in reversed(pts)]
    ca, sa = math.cos(angle), math.sin(angle)
    d.polygon([(cx + x * ca - y * sa, cy + x * sa + y * ca) for x, y in pts], fill=fill)


def draw_wreath(size: int, color: str, berry: str = "#C1121FFF") -> Image.Image:
    import math
    S = size * _SS
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    R = S * 0.36
    c = parse_color(color)
    for i in range(18):
        a = 2 * math.pi * i / 18
        cx, cy = S / 2 + R * math.cos(a), S / 2 + R * math.sin(a)
        _leaf(d, cx, cy, S * 0.2, S * 0.08, a + math.pi / 2 + (0.5 if i % 2 else -0.5), c)
    for i in range(6):
        a = 2 * math.pi * (i + 0.5) / 6
        cx, cy = S / 2 + R * 0.78 * math.cos(a), S / 2 + R * 0.78 * math.sin(a)
        rr = S * 0.035
        d.ellipse((cx - rr, cy - rr, cx + rr, cy + rr), fill=parse_color(berry))
    return _finish(img, (size, size))


def draw_emblem(kind: str, size: int, style: FrameStyle) -> Image.Image | None:
    if kind == "heart":
        return draw_heart(size, style.emblem_color)
    if kind == "rings":
        return draw_rings(size, style.emblem_color)
    if kind == "wreath":
        return draw_wreath(size, style.accent, style.emblem_color)
    return None


def draw_olive_branch(size: int, leaf: str, leaf_2: str, olive: str = "#3D4A26FF") -> Image.Image:
    """Olive branch growing from the top-left corner along both edges."""
    import math
    S = size * _SS
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    stem_c = parse_color(_hex(_mix(_rgb(leaf), (60, 50, 30), 0.45)))
    stems = [((0.10, 0.10), (0.55, 0.02), (0.97, 0.22)),   # along the top edge
             ((0.10, 0.10), (0.02, 0.50), (0.20, 0.95))]   # along the left edge
    for si, (p0, p1, p2) in enumerate(stems):
        pts = []
        for i in range(60):
            t = i / 59
            x = (1 - t) ** 2 * p0[0] + 2 * (1 - t) * t * p1[0] + t ** 2 * p2[0]
            y = (1 - t) ** 2 * p0[1] + 2 * (1 - t) * t * p1[1] + t ** 2 * p2[1]
            pts.append((x * S, y * S))
        d.line(pts, fill=stem_c, width=max(_SS, int(S * 0.014)), joint="curve")
        for k, t in enumerate([0.14, 0.24, 0.34, 0.44, 0.54, 0.64, 0.74, 0.84, 0.93]):
            i = int(t * 59)
            (x0, y0), (x1, y1) = pts[max(0, i - 1)], pts[min(59, i + 1)]
            ang = math.atan2(y1 - y0, x1 - x0)
            side = 1 if k % 2 else -1
            L = S * (0.18 - 0.06 * t)
            off = L * 0.48
            a = ang + side * 0.75
            _leaf(d, pts[i][0] + off * math.cos(a), pts[i][1] + off * math.sin(a), L, L * 0.34, a,
                  parse_color(leaf if (k + si) % 3 else leaf_2))
            if k in (2, 5) and si == 0 or k == 4 and si == 1:  # a few olives
                ox, oy = pts[i][0] - side * S * 0.03 * math.sin(ang), pts[i][1] + side * S * 0.03 * math.cos(ang)
                r = S * 0.022
                d.ellipse((ox - r * 0.8, oy - r, ox + r * 0.8, oy + r), fill=parse_color(olive))
    return _finish(img, (size, size))


def draw_watercolor_corner(size: int, c1: str, c2: str, seed: int = 3) -> Image.Image:
    import random

    from PIL import ImageFilter
    rnd = random.Random(seed)
    S = size * 2
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    for i in range(14):
        r = rnd.uniform(0.08, 0.22) * S
        t = rnd.uniform(0, 1)
        x, y = (t * 0.8 * S, rnd.uniform(0, 0.18) * S) if i % 2 else (rnd.uniform(0, 0.18) * S, t * 0.8 * S)
        col = parse_color(c1 if i % 3 else c2)
        d.ellipse((x - r, y - r, x + r, y + r), fill=col[:3] + (rnd.randint(40, 90),))
    img = img.filter(ImageFilter.GaussianBlur(S * 0.03))
    return img.resize((size, size), Image.Resampling.LANCZOS)


def draw_flourish(kind: str, size: int, style: FrameStyle) -> Image.Image | None:
    if kind == "olive":
        return draw_olive_branch(size, style.accent, style.accent_2)
    if kind == "watercolor":
        return draw_watercolor_corner(size, style.accent, style.accent_2)
    return None
