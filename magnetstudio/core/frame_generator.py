"""AI frame generator: free-text event description → ready Template.

Pipeline
  1. parse_event()          offline regex: event type, names, date, colors, style (Hebrew)
  2. generate_design()      Gemini Structured Output (google-genai + Pydantic FrameDesign)
     └ on any failure  →    build_preset_template()  (deterministic, fully offline)
  3. generate_art()         optional decorative background from a Gemini image model
     punch_alpha_holes()    slot areas made 100% transparent so the photo stays clean
  4. design_to_template()   clamps everything into the canvas safe area, auto-fits text

Note: Google shut down all Imagen models on 17 Aug 2026; the art step uses a Gemini
image model through the same SDK (generate_content + response_modalities=["IMAGE"]).
"""
from __future__ import annotations

import io
import logging
import re
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Literal

from PIL import Image, ImageChops, ImageDraw, ImageOps

from magnetstudio.core.settings import TEMPLATES_DIR
from magnetstudio.core.sizes import cm_to_px
from magnetstudio.core.templates import (LANDSCAPE, PORTRAIT, CanvasConfig, CreditLayer, GraphicLayer, PhotoSlot,
                            Template, TemplatePair, TextLayer, font_index, get_font, parse_color)

log = logging.getLogger(__name__)

DEFAULT_TEXT_MODEL = "gemini-3.8-flash"
DEFAULT_ART_MODEL = "gemini-3.1-flash-image"
GENERATED_DIR = TEMPLATES_DIR / "_generated"
ART_ASPECTS = {"1:1": 1, "2:3": 2 / 3, "3:2": 1.5, "3:4": 0.75, "4:3": 4 / 3,
               "9:16": 9 / 16, "16:9": 16 / 9, "21:9": 21 / 9}

Progress = Callable[[int, str], None]


class GeneratorUnavailable(RuntimeError):
    """Cloud generation not possible (no SDK / key / network / bad response)."""


# ============================================================== 1. offline parsing

HE = r"֐-׿"
HEB_MONTHS = {"ינואר": 1, "פברואר": 2, "מרץ": 3, "מרס": 3, "אפריל": 4, "מאי": 5, "יוני": 6,
              "יולי": 7, "אוגוסט": 8, "ספטמבר": 9, "אוקטובר": 10, "נובמבר": 11, "דצמבר": 12}

EVENT_TYPES = [  # (pattern, display label) – longest first
    ("בת מצווה|בת מצוה|בת-מצווה", "בת מצווה"), ("בר מצווה|בר מצוה|בר-מצווה", "בר מצווה"),
    ("יום הולדת|יומולדת|יום-הולדת", "יום הולדת"), ("שבת חתן", "שבת חתן"), ("ברית מילה", "ברית"),
    ("חינה|חנה", "חינה"), ("חתונה|חתונת", "חתונה"), ("אירוסין|אירוסים|ארוסין", "אירוסין"),
    ("בריתה|זבד הבת|שמחת בת", "שמחת בת"), ("ברית", "ברית"), ("מסיבת רווקות", "מסיבת רווקות"),
    ("מסיבה", "מסיבה"), ("כנס", "כנס"),
]

COLORS = {  # Hebrew color words → hex (longest match wins)
    "ורוד עתיק": "#C98A8E", "ירוק זית": "#6B6B3A", "כחול נייבי": "#1B2A4A", "אפור פחם": "#3A3A3A",
    "בורדו": "#6D1A36", "זהב": "#C9A24A", "זהוב": "#C9A24A", "כסף": "#B8BCC2", "כסוף": "#B8BCC2",
    "רוזגולד": "#B76E79", "ורוד": "#E8A1B5", "נייבי": "#1B2A4A", "כחול": "#1F3A68", "תכלת": "#8EC5E8",
    "טורקיז": "#1C9C9C", "ירוק": "#2F6B4F", "זית": "#6B6B3A", "מנטה": "#A8DCC6", "שחור": "#1A1A1A",
    "לבן": "#FFFFFF", "קרם": "#F5EBDD", "שמנת": "#F5EBDD", "בז'": "#D9C3A5", "בז": "#D9C3A5",
    "אדום": "#B3261E", "סגול": "#5B3A7A", "לילך": "#B9A3D6", "כתום": "#E07A2E", "צהוב": "#E8C547",
    "חרדל": "#C9A227", "חום": "#6B4A34", "אפור": "#8A8A8A", "פודרה": "#EBCFCB", "אפרסק": "#F4B79A",
    "terracotta": "#C2603E", "טרקוטה": "#C2603E",
}

STYLES = {  # keyword → ornament style
    "מרוקאי": "moroccan", "מרוקאית": "moroccan", "מזרחי": "moroccan", "ערבסק": "moroccan",
    "בוהו": "corners", "כפרי": "corners", "רוסטיק": "corners",
    "מינימליסטי": "minimal", "מינימליסטית": "minimal", "מינימלי": "minimal", "מודרני": "minimal",
    "נקי": "minimal", "קלאסי": "classic", "קלאסית": "classic", "אלגנטי": "classic",
    "אלגנטית": "classic", "יוקרתי": "classic", "וינטג'": "classic", "רטרו": "classic",
}

STYLE_PALETTES = {  # (background, accent)
    "moroccan": ("#5E1428", "#D4AF37"),
    "classic": ("#F6EFE6", "#8C6A52"),
    "corners": ("#F3E9DC", "#A0704B"),
    "minimal": ("#FFFFFF", "#222222"),
}

SERIF_HE = ["Noto Serif Hebrew", "Frank Ruehl CLM", "David", "Times New Roman", "FreeSerif"]
SANS_HE = ["Rubik", "Assistant", "Heebo", "Noto Sans Hebrew", "Arial", "Segoe UI", "DejaVu Sans"]


@dataclass
class EventInfo:
    raw: str
    event: str = ""            # "חינה"
    names: str = ""            # "מורן ואביב"
    name_a: str = ""           # "מורן"
    name_b: str = ""           # "אביב"
    title: str = ""            # main line to print
    date: str = ""             # "18.09.2026"
    colors: list[str] = field(default_factory=list)
    style: str = "classic"


_DATE_NUM = re.compile(r"(?<!\d)(\d{1,2})[./\-](\d{1,2})(?:[./\-](\d{2,4}))?(?!\d)")
_DATE_HEB = re.compile(rf"(?<!\d)(\d{{1,2}})\s*(?:ב|ל)?\s*({'|'.join(HEB_MONTHS)})\s*,?\s*(\d{{4}})?")
_NAMES = re.compile(rf"(?:^|\s)(?:ל|של\s+|לכבוד\s+)?([{HE}][{HE}'\"]+)\s+ו-?([{HE}][{HE}'\"]+)")
_STYLE_SPLIT = re.compile(r",|\s(?:בסגנון|סגנון|בגווני|בגוון|בצבעי|צבעים|בצבע)\s")


def _fmt_date(d: int | str, m: int | str, y: str | None) -> str:
    """Keep the digits as the user typed them ("13.8.2026" stays, "18.09.2026" stays); '.' separators."""
    if not (1 <= int(d) <= 31 and 1 <= int(m) <= 12):
        return ""
    if y and len(y) == 2:
        y = "20" + y
    return f"{d}.{m}" + (f".{y}" if y else "")


def parse_event(text: str) -> EventInfo:
    """Extract event type, names, date, colors and style from a free Hebrew description."""
    info = EventInfo(raw=text.strip())
    t = " ".join(text.split())

    date_span = None
    m = _DATE_HEB.search(t)
    if m:
        info.date = _fmt_date(m.group(1), HEB_MONTHS[m.group(2)], m.group(3))
        date_span = m.span()
    else:
        for m in _DATE_NUM.finditer(t):
            info.date = _fmt_date(m.group(1), m.group(2), m.group(3))
            if info.date:
                date_span = m.span()
                break

    # the "title clause": text before the date, or before the first style/color marker
    head = t[:date_span[0]] if date_span else t
    head = _STYLE_SPLIT.split(head)[0]
    head = re.split(r"\s[-–]\s", head)[0]
    head = re.sub(r"\s+(?:ב|ביום|בתאריך|תאריך)\s*$", "", head).strip(" ,.-–:")
    tail = t.replace(head, " ", 1)

    # colors in the order written, longest words first ("ורוד עתיק" beats "ורוד").
    # Looked up outside the title clause first, so "ברית לבן" isn't read as white.
    def find_colors(text: str) -> list[str]:
        low, found = text.lower(), []
        for word in sorted(COLORS, key=len, reverse=True):
            for cm in list(re.finditer(rf"(?:(?<![{HE}])|(?<=(?<![{HE}])[ובלהכמש])){re.escape(word)}(?![{HE}])", low)):
                found.append((cm.start(), COLORS[word]))
                low = low[:cm.start()] + " " * len(word) + low[cm.end():]
        return list(dict.fromkeys(c for _, c in sorted(found)))
    info.colors = find_colors(tail)

    for word, style in STYLES.items():
        if word in t:
            info.style = style
            break

    for pat, label in EVENT_TYPES:
        if re.search(pat, head):
            info.event = label
            break
    nm = _NAMES.search(head)
    if nm:
        info.names = f"{nm.group(1)} ו{nm.group(2)}"
        info.name_a, info.name_b = nm.group(1), nm.group(2)
    if info.names:
        info.title = info.names
    else:  # e.g. "יום הולדת 40 לדני" → event "יום הולדת 40", title "דני"
        rest = head
        for pat, _ in EVENT_TYPES:
            rest = re.sub(pat, "", rest, count=1)
        rest = rest.strip(" ,.-–:")
        num = re.match(r"^(\d{1,3})\s+(.*)$", rest)
        if num and info.event:
            info.event, rest = f"{info.event} {num.group(1)}", num.group(2)
        rest = re.sub(rf"^(?:של\s+|לכבוד\s+|ל(?=[{HE}]))", "", rest).strip(" ,.-–:")
        info.title = rest or info.event
    return info


# ============================================================== colors

def _rgb(h: str) -> tuple[int, int, int]:
    return parse_color(h)[:3]


def _hex(rgb) -> str:
    return "#{:02X}{:02X}{:02X}FF".format(*[max(0, min(255, int(round(v)))) for v in rgb[:3]])


def _lum(rgb) -> float:
    def ch(c):
        c /= 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = rgb[:3]
    return 0.2126 * ch(r) + 0.7152 * ch(g) + 0.0722 * ch(b)


def contrast(a, b) -> float:
    la, lb = sorted((_lum(a), _lum(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def _mix(a, b, t: float):
    return tuple(x + (y - x) * t for x, y in zip(a, b))


def ensure_contrast(fg: str, bg: str, target: float = 4.5) -> str:
    """Darken/lighten fg toward black/white until it reaches `target` contrast on bg."""
    f, b = _rgb(fg), _rgb(bg)
    toward = (0, 0, 0) if _lum(b) > 0.35 else (255, 255, 255)
    for i in range(21):
        c = _mix(f, toward, i / 20)
        if contrast(c, b) >= target:
            return _hex(c)
    return _hex(toward)


def palette_for(info: EventInfo) -> tuple[str, str, str]:
    """(background, accent, text) – accent for ornaments, text guaranteed readable."""
    cols = info.colors
    if len(cols) >= 2:
        bg, accent = cols[0], cols[1]
    elif len(cols) == 1:
        c = _rgb(cols[0])
        if _lum(c) > 0.55:
            bg, accent = cols[0], _hex(_mix(c, (0, 0, 0), 0.55))
        else:
            bg, accent = _hex(_mix(c, (255, 255, 255), 0.88)), cols[0]
    else:
        bg, accent = STYLE_PALETTES.get(info.style, STYLE_PALETTES["classic"])
    bg, accent = _hex(_rgb(bg)), _hex(_rgb(accent))
    text = ensure_contrast(accent, bg, 4.5)
    if contrast(_rgb(accent), _rgb(bg)) < 1.6:  # ornaments must still be visible
        accent = ensure_contrast(accent, bg, 2.0)
    return bg, accent, text


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


# ============================================================== offline preset template

def build_preset_template(prompt: str, profile: str = "7.5x10", slot_count: int | None = None,
                          info: EventInfo | None = None) -> Template:
    """Deterministic, fully offline frame: parsed Hebrew text + clean procedural ornament."""
    info = info or parse_event(prompt)
    canvas = CanvasConfig.from_profile(profile)
    bg, accent, text_color = palette_for(info)
    canvas.bg_color = bg
    count = slot_count or default_slot_count(profile)
    W, H = canvas.width, canvas.height
    m = safe_margin(canvas)

    lines: list[tuple[str, float, bool]] = []  # (text, size as fraction of W, bold)
    if info.event and info.event != info.title:
        lines.append((info.event, 0.07, False))
    if info.title:
        lines.append((info.title, 0.12, True))
    if info.date:
        lines.append((info.date, 0.06, False))
    n_lines = max(1, len(lines))

    strip = "strip" in profile
    footer_frac = (0.10 + 0.035 * n_lines) if strip else (0.11 + 0.045 * n_lines)
    top_extra = round(m * 1.9) if info.style == "moroccan" else 0
    slots = preset_slots(canvas, count, footer_frac, top_extra)

    family = _pick_family(SERIF_HE if info.style in ("classic", "moroccan") else SANS_HE)
    texts = [TextLayer(text=s, font_size=max(14, round(W * frac)), bold=bold, color=text_color,
                       align="center", font_family=family, z=10) for s, frac, bold in lines]
    y0 = max(s.y + s.h for s in slots) + round(m * 0.8)
    stack_texts(texts, m, y0, H - m, W - 2 * m, gap=round(m * 0.25))

    t = Template(name=(info.title or info.event or "מסגרת")[:40], canvas=canvas, slots=slots, texts=texts)
    t.graphics.append(GraphicLayer(path=_save_generated(draw_ornament(canvas, info.style, accent, slots),
                                                        "ornament"), w=W, h=H, z=1))
    return t


# ============================================================== Israeli magnet style
#
#  ┌────────────────────────────┬──┐   photo window (alpha 0) with corner flourishes
#  │ ❧                          │ c│   overlapping its edges (z above the photo)
#  │        PHOTO SLOT          │ r│
#  │                          ❧ │ e│   credit: vertical text on the right edge
#  ├────────────────────────────┤ d│
#  │   מורן   ♥   אביב          │ i│   footer bar: names + emblem + date
#  │        13.8.2026           │ t│   (landscape: one row, date at the side)
#  └────────────────────────────┴──┘

DEFAULT_CREDIT = "שחר לוי גונן | 0525860073"
EMBLEMS = {"heart": "לב", "rings": "טבעות", "wreath": "זר פרחים", "none": "ללא"}
FLOURISHES = {"olive": "ענפי זית", "watercolor": "צבעי מים", "none": "ללא"}

_EMBLEM_WORDS = [("טבעות|טבעת|💍", "rings"), ("זר|פרחים|פרח|💐", "wreath"), ("ללא סמל|בלי סמל", "none"),
                 ("לב|לבבות|❤|♥", "heart")]
_FLOURISH_WORDS = [("זית|ענפי", "olive"), ("צבעי מים|אקוורל|מים", "watercolor"),
                   ("ללא עיטור|בלי עיטור|נקי", "none")]


@dataclass
class FrameStyle:
    bg: str = "#FBF8F1FF"            # cream
    footer_bg: str = ""              # "" = same as bg
    name_color: str = "#3F4A26FF"    # dark olive
    date_color: str = "#6B7A4AFF"
    accent: str = "#6F8B3AFF"        # flourishes
    accent_2: str = "#8DA65AFF"
    emblem: str = "heart"            # heart | rings | wreath | none
    emblem_color: str = "#C1121FFF"  # red heart
    flourish: str = "olive"          # olive | watercolor | none
    name_family: str = "Rubik"
    date_family: str = "Assistant"
    credit_color: str = "#6C757DFF"


def style_from_info(info: EventInfo) -> FrameStyle:
    """Pick emblem / flourish / palette from the free-text request (defaults: olive + red heart)."""
    st = FrameStyle()
    t = info.raw
    for pat, em in _EMBLEM_WORDS:
        if re.search(pat, t):
            st.emblem = em
            break
    for pat, fl in _FLOURISH_WORDS:
        if re.search(pat, t):
            st.flourish = fl
            break
    if st.emblem == "rings":
        st.emblem_color = "#C9A24AFF"
    if info.colors:  # user colors: first → text/flourish tone, second → emblem/accent
        bg, accent, text = palette_for(info)
        if _lum(_rgb(bg)) > 0.6:      # light first color → keep it as the background
            st.bg, st.name_color = bg, text
        else:                          # dark/saturated first color → use it for text & flourishes
            st.name_color = ensure_contrast(info.colors[0], st.bg, 4.5)
            st.accent = _hex(_rgb(info.colors[0]))
            st.accent_2 = _hex(_mix(_rgb(info.colors[0]), (255, 255, 255), 0.35))
        st.date_color = _hex(_mix(_rgb(st.name_color), _rgb(st.bg), 0.25))
        if len(info.colors) > 1 and st.emblem != "heart":
            st.emblem_color = _hex(_rgb(info.colors[1]))
    if st.flourish == "watercolor" and not info.colors:
        st.accent, st.accent_2 = "#7FB3C8FF", "#A9CFDDFF"
        st.name_color, st.date_color = "#2F4F5FFF", "#557585FF"
    st.date_color = ensure_contrast(st.date_color, st.bg, 4.5)  # prints come out darker/flatter
    st.name_color = ensure_contrast(st.name_color, st.bg, 4.5)
    return st


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


# ---------- layout

def _text_w(t: TextLayer) -> float:
    f = get_font(t.font_family, t.font_size, t.bold, t.font_path)
    return f.getlength(t.text)


def build_israeli_template(info: EventInfo, profile: str = "7.5x10", orientation: str = PORTRAIT,
                           style: FrameStyle | None = None, credit_text: str | None = DEFAULT_CREDIT,
                           name: str = "") -> Template:
    """One single-photo frame in the standard Israeli magnet layout, for one orientation."""
    st = style or style_from_info(info)
    canvas = CanvasConfig.from_profile(profile, st.bg, orientation)
    W, H = canvas.width, canvas.height
    land = canvas.orientation == LANDSCAPE
    s = min(W, H)
    m = safe_margin(canvas)

    credit = None
    if credit_text:
        credit = CreditLayer(text=credit_text, color=st.credit_color, side="right", rotation=90)
    cw = credit.strip_width(canvas) if credit else 0
    ml = m
    mr = max(m, cw + round(m * 0.5)) if credit else m

    # --- footer content
    names_size, date_size = round(s * 0.085), round(s * 0.046)
    if land:
        names_size, date_size = round(s * 0.08), round(s * 0.042)
    name_fam = _pick_family([st.name_family] + SANS_HE)
    date_fam = _pick_family([st.date_family] + SANS_HE)
    a_txt, b_txt = info.name_a, info.name_b
    title = info.title if not (a_txt and b_txt) else ""
    texts: list[TextLayer] = []
    mk = lambda txt, size, fam, color, bold=False: TextLayer(  # noqa: E731
        text=txt, font_size=size, font_family=fam, color=color, bold=bold, align="center", z=10)
    t_a = mk(a_txt, names_size, name_fam, st.name_color, True) if a_txt else None
    t_b = mk(b_txt, names_size, name_fam, st.name_color, True) if b_txt else None
    t_title = mk(title, names_size, name_fam, st.name_color, True) if title else None
    t_event = mk(info.event, date_size, date_fam, st.date_color) if (title and info.event and info.event != title) else None
    t_date = mk(info.date, date_size, date_fam, st.date_color) if info.date else None

    names_line_h = lambda: text_height(t_a or t_b or t_title) if (t_a or t_b or t_title) else 0  # noqa: E731
    gap_v = round(m * 0.25)
    pad_v = round(m * 0.45)
    if land:
        content = max(names_line_h(), text_height(t_date) if t_date else 0) + \
            ((text_height(t_event) + gap_v) if t_event else 0)
    else:
        content = names_line_h() + ((text_height(t_date) + gap_v) if t_date else 0) + \
            ((text_height(t_event) + gap_v) if t_event else 0)
    fh = max(pad_v + content + m, round(H * 0.12))  # bottom keeps the full safe margin

    slot = PhotoSlot(ml, m, W - ml - mr, H - m - fh - round(m * 0.3), radius=0)
    fy0 = slot.y + slot.h + round(m * 0.3)
    fy1 = H - m
    fx0, fx1 = ml, W - mr

    # --- names row: [a] [emblem] [b]  (RTL: a on the right) or [title] [emblem]
    em_size = round(names_size * 0.9)
    emblem_img = draw_emblem(st.emblem, em_size, st)
    em_w = emblem_img.width if emblem_img else 0
    gap_h = round(names_size * 0.35)
    row_items = [x for x in (t_a, t_b, t_title) if x]
    date_w_land = (_text_w(t_date) + gap_h * 2) if (land and t_date) else 0
    row_max = (fx1 - fx0) - 2 * date_w_land - (2 * gap_h if land else 0)
    row_max = max(row_max, (fx1 - fx0) * 0.55)

    def row_width() -> float:
        ws = [_text_w(t) for t in row_items]
        return sum(ws) + (em_w + gap_h * 2 if emblem_img else gap_h * (len(ws) - 1))

    for _ in range(30):  # shrink names (and emblem) until the row fits
        if row_width() <= row_max or row_items[0].font_size <= 16:
            break
        for t in row_items:
            t.font_size = max(16, int(t.font_size * 0.93))
        if emblem_img:
            em_size = max(12, int(em_size * 0.93))
            emblem_img = draw_emblem(st.emblem, em_size, st)
            em_w = emblem_img.width

    ry = fy0 + pad_v + ((text_height(t_event) + gap_v) if t_event else 0)
    if not land and t_date:  # portrait: names row then date row, block centered in the footer
        block = names_line_h() + gap_v + text_height(t_date) + ((text_height(t_event) + gap_v) if t_event else 0)
        top = fy0 + max(0, ((fy1 - fy0) - block) // 2)
        ry = top + ((text_height(t_event) + gap_v) if t_event else 0)
    elif land:
        block = names_line_h() + ((text_height(t_event) + gap_v) if t_event else 0)
        top = fy0 + max(0, ((fy1 - fy0) - block) // 2)
        ry = top + ((text_height(t_event) + gap_v) if t_event else 0)
    cx = (fx0 + fx1) / 2
    total = row_width()
    x = cx + total / 2  # lay out right → left
    graphics: list[GraphicLayer] = []
    seq = [t_a, "EMBLEM", t_b] if (t_a and t_b) else [t_title or t_a or t_b, "EMBLEM"]
    if not emblem_img:
        seq = [i for i in seq if i != "EMBLEM"]
    for i, it in enumerate(seq):
        if it == "EMBLEM":
            x -= gap_h
            ey = ry + (names_line_h() - emblem_img.height) // 2
            graphics.append(GraphicLayer(path=_save_generated(emblem_img, f"emblem_{st.emblem}"),
                                         x=round(x - em_w), y=round(ey), w=emblem_img.width,
                                         h=emblem_img.height, z=6))
            x -= em_w + gap_h
        elif it is not None:
            w = _text_w(it)
            it.width = int(w) + 4
            it.x, it.y = round(x - w) - 2, ry
            texts.append(it)
            x -= w + (0 if emblem_img or i == len(seq) - 1 else gap_h)
    if t_event:
        t_event.x, t_event.width = fx0, fx1 - fx0
        t_event.y = ry - gap_v - text_height(t_event)
        texts.insert(0, t_event)
    if t_date:
        if land:  # date at the far (left) end of the footer row, vertically centered with names
            t_date.align = "left"
            t_date.x = fx0 + gap_h
            t_date.width = int(_text_w(t_date)) + 4
            t_date.y = ry + (names_line_h() - text_height(t_date)) // 2
        else:
            t_date.x, t_date.width = fx0, fx1 - fx0
            t_date.y = ry + names_line_h() + gap_v
        texts.append(t_date)

    # --- footer band (if a different colour) + corner flourishes over the photo edges
    deco = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    if st.footer_bg and st.footer_bg != st.bg:
        ImageDraw.Draw(deco).rectangle((0, fy0 - round(m * 0.3), W, H), fill=parse_color(st.footer_bg))
        graphics.append(GraphicLayer(path=_save_generated(deco, "footer"), w=W, h=H, z=-1))
    fs = round(min(slot.w, slot.h) * 0.32)
    fl = draw_flourish(st.flourish, fs, st)
    if fl is not None:
        over = round(fs * 0.16)  # how far the flourish reaches past the photo edge
        tl_x, tl_y = slot.x - over, slot.y - over
        br = fl.transpose(Image.Transpose.ROTATE_180)
        br_x = slot.x + slot.w - fs + min(over, round(m * 0.3))
        br_y = slot.y + slot.h - fs + round(fs * 0.07)  # only a small dip into the footer (names!)
        graphics.append(GraphicLayer(path=_save_generated(fl, f"flourish_{st.flourish}"),
                                     x=tl_x, y=tl_y, w=fs, h=fs, z=3))
        graphics.append(GraphicLayer(path=_save_generated(br, f"flourish_{st.flourish}"),
                                     x=br_x, y=br_y, w=fs, h=fs, z=3))

    t = Template(name=(name or info.names or info.title or "מסגרת")[:40], canvas=canvas, slots=[slot],
                 texts=texts, graphics=graphics, credit=credit)
    return t


def build_frame_pair(prompt: str = "", profile: str = "7.5x10", credit_text: str | None = DEFAULT_CREDIT,
                     info: EventInfo | None = None, style: FrameStyle | None = None) -> TemplatePair:
    """Portrait + landscape versions of the same single-photo Israeli-style frame."""
    info = info or parse_event(prompt)
    st = style or style_from_info(info)
    name = (info.names or info.title or "מסגרת")[:40]
    return TemplatePair(name=name, variants={
        o: build_israeli_template(info, profile, o, st, credit_text, name) for o in (PORTRAIT, LANDSCAPE)})


# ============================================================== structured output schema

try:
    from pydantic import BaseModel, Field

    class SlotSpec(BaseModel):
        """Photo window. All values are fractions of the canvas (0..1)."""
        x: float = Field(description="left edge, fraction of canvas width")
        y: float = Field(description="top edge, fraction of canvas height")
        w: float = Field(description="width, fraction of canvas width")
        h: float = Field(description="height, fraction of canvas height")
        radius: float = Field(0.0, description="corner radius, fraction of the slot's shorter side (0-0.3)")

    class TextSpec(BaseModel):
        role: Literal["event", "title", "date", "subtitle", "footer"]
        text: str = Field(description="exact text to print, Hebrew allowed")
        x: float = Field(description="left edge of the text box, fraction of canvas width")
        y: float = Field(description="top edge, fraction of canvas height")
        width: float = Field(description="text box width, fraction of canvas width")
        size: float = Field(description="font size as fraction of canvas width (0.03-0.15)")
        bold: bool = False
        color: str = Field(description="hex color #RRGGBB")
        align: Literal["right", "center", "left"] = "center"

    class FrameDesign(BaseModel):
        """Mirrors core.templates.Template, in canvas-relative units."""
        name: str
        bg_color: str = Field(description="hex #RRGGBB background")
        accent_color: str = Field(description="hex #RRGGBB for borders and ornaments")
        ornament: Literal["classic", "moroccan", "corners", "minimal"]
        font_style: Literal["serif", "sans"] = "serif"
        slots: list[SlotSpec]
        texts: list[TextSpec]
        art_prompt: str = Field(description="English prompt for a decorative background/border artwork; "
                                            "no text, no letters, no people, plain area where photos go")

    HAS_PYDANTIC = True
except ImportError:  # offline generator still works
    HAS_PYDANTIC = False
    FrameDesign = None  # type: ignore[assignment,misc]

try:
    from google import genai
    from google.genai import types as genai_types
    HAS_GENAI = True
except ImportError:
    genai = genai_types = None  # type: ignore[assignment]
    HAS_GENAI = False


DESIGN_INSTRUCTIONS = """You design printable photo-magnet frames for Israeli events.
Canvas: profile {profile}, {w}x{h} px at 300 DPI (aspect {aspect:.3f}). Use fractions 0..1 for all geometry.
Rules:
- Exactly {slots} photo slot(s). Slots are where camera photos appear; keep them large and inside the canvas.
- Keep every text and slot inside a safe margin of {margin:.3f} (fraction) from each edge.
- Texts must NOT overlap any slot. Usually place them in a band below the photos.
- Copy names, dates and Hebrew wording exactly as the user wrote them. Never invent names or dates.
  If the user gave no date, omit the date text.
- Choose colors that match the requested style/colors; text must be readable on bg_color.
- 2-4 short texts max. Hebrew is right-to-left; prefer align=center.
- art_prompt: English, describes only decorative border/background art in the requested style and palette,
  flat print-ready illustration, no text, no letters, no numbers, no people, no faces.
Offline hints parsed from the request (may be incomplete): {hints}
"""


def _client(api_key: str, client=None):
    if client is not None:
        return client
    if not HAS_GENAI:
        raise GeneratorUnavailable("google-genai לא מותקן")
    if not api_key:
        raise GeneratorUnavailable("לא הוגדר GEMINI_API_KEY")
    return genai.Client(api_key=api_key, http_options=genai_types.HttpOptions(timeout=45_000))


def generate_design(prompt: str, profile: str, slot_count: int, api_key: str = "",
                    model: str = DEFAULT_TEXT_MODEL, client=None, info: EventInfo | None = None) -> "FrameDesign":
    """Gemini Structured Output → validated FrameDesign. Raises GeneratorUnavailable."""
    if not HAS_PYDANTIC:
        raise GeneratorUnavailable("pydantic לא מותקן")
    c = _client(api_key, client)
    canvas = CanvasConfig.from_profile(profile)
    info = info or parse_event(prompt)
    hints = {"event": info.event, "title": info.title, "date": info.date, "colors": info.colors, "style": info.style}
    system = DESIGN_INSTRUCTIONS.format(profile=profile, w=canvas.width, h=canvas.height,
                                        aspect=canvas.width / canvas.height, slots=slot_count,
                                        margin=safe_margin(canvas) / min(canvas.width, canvas.height), hints=hints)
    try:
        cfg = genai_types.GenerateContentConfig(system_instruction=system, response_mime_type="application/json",
                                                response_schema=FrameDesign, temperature=0.6) if genai_types else None
        resp = c.models.generate_content(model=model, contents=prompt, config=cfg)
    except GeneratorUnavailable:
        raise
    except Exception as e:  # network, auth, quota, model not found…
        raise GeneratorUnavailable(f"Gemini: {e}") from e
    parsed = getattr(resp, "parsed", None)
    try:
        design = parsed if isinstance(parsed, FrameDesign) else FrameDesign.model_validate_json(resp.text or "")
    except Exception as e:
        raise GeneratorUnavailable(f"תשובת Gemini לא תואמת לסכמה: {e}") from e
    if not design.slots or not design.texts:
        raise GeneratorUnavailable("Gemini החזיר עיצוב ריק")
    return design


def _clampf(v, lo=0.0, hi=1.0) -> float:
    try:
        v = float(v)
    except (TypeError, ValueError):
        return lo
    return lo if v != v else max(lo, min(hi, v))  # NaN → lo


def _valid_hex(c: str, default: str) -> str:
    c = (c or "").strip()
    if re.fullmatch(r"#?[0-9a-fA-F]{6}([0-9a-fA-F]{2})?", c):
        return _hex(_rgb(c if c.startswith("#") else "#" + c))
    return default


def design_to_template(design: "FrameDesign", profile: str, slot_count: int | None = None) -> Template:
    """Convert a model design to a Template, clamping everything into the safe area."""
    canvas = CanvasConfig.from_profile(profile)
    W, H = canvas.width, canvas.height
    m = safe_margin(canvas)
    bg = _valid_hex(design.bg_color, "#F6EFE6FF")
    accent = _valid_hex(design.accent_color, "#8C6A52FF")
    canvas.bg_color = bg
    style = design.ornament if design.ornament in STYLE_PALETTES else "classic"

    slots = []
    for s in design.slots:
        x, y = _clampf(s.x) * W, _clampf(s.y) * H
        w, h = _clampf(s.w, 0.15) * W, _clampf(s.h, 0.1) * H
        x, y = max(m, x), max(m, y)
        w, h = min(w, W - m - x), min(h, H - m - y)
        if w >= W * 0.15 and h >= H * 0.08:
            slots.append(PhotoSlot(round(x), round(y), round(w), round(h),
                                   round(_clampf(s.radius, 0, 0.3) * min(w, h))))
    want = slot_count or len(slots) or default_slot_count(profile)
    if len(slots) != want:  # model ignored the count → deterministic layout
        slots = preset_slots(canvas, want, 0.25 if "strip" not in profile else 0.2)

    family = _pick_family(SERIF_HE if design.font_style == "serif" else SANS_HE)
    texts, misplaced = [], []
    for ts in design.texts[:5]:
        if not ts.text.strip():
            continue
        x = max(m, round(_clampf(ts.x) * W))
        width = min(round(_clampf(ts.width, 0.2) * W), W - m - x)
        if width < W * 0.3:
            x, width = m, W - 2 * m
        t = TextLayer(text=ts.text.strip(), x=x, y=round(_clampf(ts.y) * H), width=width,
                      font_size=round(_clampf(ts.size, 0.025, 0.2) * W), bold=ts.bold,
                      color=ensure_contrast(_valid_hex(ts.color, accent), bg, 3.0),
                      align=ts.align if ts.align in ("right", "center", "left") else "center",
                      font_family=family, z=10)
        fit_text(t, width)
        t.y = max(m, min(t.y, H - m - text_height(t)))
        box = (t.x, t.y, t.x + t.width, t.y + text_height(t))
        if any(_overlaps(box, (s.x, s.y, s.x + s.w, s.y + s.h)) for s in slots):
            misplaced.append(t)
        texts.append(t)
    if misplaced:  # re-stack every text in the free band under the photos
        y0 = max(s.y + s.h for s in slots) + round(m * 0.8)
        if H - m - y0 < H * 0.08:  # no room → shrink slots to make a footer
            slots = preset_slots(canvas, len(slots), 0.25 if "strip" not in profile else 0.2)
            y0 = max(s.y + s.h for s in slots) + round(m * 0.8)
        texts.sort(key=lambda t: t.y)
        stack_texts(texts, m, y0, H - m, W - 2 * m, gap=round(m * 0.25))

    t = Template(name=(design.name or "מסגרת AI")[:40], canvas=canvas, slots=slots, texts=texts)
    t.graphics.append(GraphicLayer(path=_save_generated(draw_ornament(canvas, style, accent, slots),
                                                        "ornament"), w=W, h=H, z=1))
    t.__dict__["_art_prompt"] = design.art_prompt  # transient, not saved to JSON
    t.__dict__["_accent"] = accent
    return t


# ============================================================== AI art (Gemini image)

def nearest_aspect(w: int, h: int) -> str:
    r = w / h
    return min(ART_ASPECTS, key=lambda k: abs(ART_ASPECTS[k] - r))


def generate_art(prompt: str, width: int, height: int, api_key: str = "",
                 model: str = DEFAULT_ART_MODEL, client=None) -> Image.Image:
    """Decorative artwork sized to the canvas. Raises GeneratorUnavailable."""
    c = _client(api_key, client)
    full = (f"{prompt}. Decorative printable frame artwork for a photo magnet. Flat, print-ready, "
            f"high detail, balanced margins. Absolutely no text, letters, numbers, logos, people or faces.")
    try:
        cfg = genai_types.GenerateContentConfig(
            response_modalities=["IMAGE"],
            image_config=genai_types.ImageConfig(aspect_ratio=nearest_aspect(width, height), image_size="2K"),
        ) if genai_types else None
        resp = c.models.generate_content(model=model, contents=full, config=cfg)
    except Exception as e:
        raise GeneratorUnavailable(f"יצירת רקע נכשלה: {e}") from e
    for cand in getattr(resp, "candidates", None) or []:
        for part in getattr(getattr(cand, "content", None), "parts", None) or []:
            data = getattr(getattr(part, "inline_data", None), "data", None)
            if data:
                img = Image.open(io.BytesIO(data)).convert("RGB")
                return ImageOps.fit(img, (width, height), method=Image.Resampling.LANCZOS)
    raise GeneratorUnavailable("מודל התמונה לא החזיר תמונה")


def add_art_layer(t: Template, art: Image.Image) -> None:
    """Put AI art above the photo plane with slot holes punched, and add a text panel for legibility."""
    c = t.canvas
    m = safe_margin(c)
    punched = punch_alpha_holes(art.resize((c.width, c.height), Image.Resampling.LANCZOS), t.slots)
    t.graphics.append(GraphicLayer(path=_save_generated(punched, "art"), w=c.width, h=c.height, z=0))
    if t.texts:  # readable panel behind the texts, above the art
        x0 = min(tx.x for tx in t.texts) - round(m * 0.4)
        y0 = min(tx.y for tx in t.texts) - round(m * 0.3)
        x1 = max(tx.x + (tx.width or c.width) for tx in t.texts) + round(m * 0.4)
        y1 = max(tx.y + text_height(tx) for tx in t.texts) + round(m * 0.3)
        panel = draw_ornament(c, "none", t.__dict__.get("_accent", "#00000000"), [],
                              text_panel=(max(0, x0), max(0, y0), min(c.width - 1, x1), min(c.height - 1, y1)),
                              panel_color=c.bg_color)
        t.graphics.append(GraphicLayer(path=_save_generated(panel, "panel"), w=c.width, h=c.height, z=2))


# ============================================================== orchestration

@dataclass
class GenerationResult:
    template: Template                   # portrait variant (or the only template)
    engine: str                          # "ai" | "offline"
    art: bool = False
    notes: list[str] = field(default_factory=list)
    pair: TemplatePair | None = None     # portrait + landscape (single-photo frames)

    @property
    def frame(self) -> "Template | TemplatePair":
        return self.pair or self.template


def _info_from_design(design: "FrameDesign", info: EventInfo) -> EventInfo:
    """Names/date/event chosen by the model, falling back to the offline parse."""
    out = EventInfo(raw=info.raw, event=info.event, names=info.names, name_a=info.name_a,
                    name_b=info.name_b, title=info.title, date=info.date, colors=list(info.colors),
                    style=info.style)
    for ts in design.texts:
        txt = ts.text.strip()
        if ts.role == "title" and txt:
            m = re.match(rf"^(.+?)\s+ו-?([{HE}].+)$", txt)
            if m and " " not in m.group(1).strip():
                out.name_a, out.name_b, out.names = m.group(1).strip(), m.group(2).strip(), txt
            else:
                out.title = txt
        elif ts.role == "date" and txt:
            out.date = txt
        elif ts.role == "event" and txt:
            out.event = txt
    return out


def _style_from_design(design: "FrameDesign", info: EventInfo) -> FrameStyle:
    st = style_from_info(info)
    if not info.colors:  # the model's palette, if the user didn't name colours
        st.bg = _valid_hex(design.bg_color, st.bg)
        st.accent = _valid_hex(design.accent_color, st.accent)
        st.accent_2 = _hex(_mix(_rgb(st.accent), (255, 255, 255), 0.35))
        title = next((t for t in design.texts if t.role == "title"), None)
        if title is not None:
            st.name_color = _valid_hex(title.color, st.name_color)
    st.name_color = ensure_contrast(st.name_color, st.bg, 4.5)
    st.date_color = ensure_contrast(st.date_color, st.bg, 4.5)
    return st


def generate_frame(prompt: str, profile: str = "7.5x10", slot_count: int | None = None,
                   use_ai: bool = True, use_art: bool = True, api_key: str = "",
                   text_model: str = DEFAULT_TEXT_MODEL, art_model: str = DEFAULT_ART_MODEL,
                   progress: Progress | None = None, client=None,
                   credit_text: str | None = DEFAULT_CREDIT, dual: bool = True) -> GenerationResult:
    """Never raises for cloud problems – falls back to the offline generator.

    Single-photo frames (the usual magnet) come out as a portrait + landscape pair in the
    Israeli layout (photo window, footer with names + emblem + date, side credit, corner
    flourishes). Multi-photo strips keep the classic stacked layout (one orientation).
    """
    say = progress or (lambda p, s: None)
    if not prompt.strip():
        raise ValueError("נא לתאר את האירוע")
    count = slot_count or default_slot_count(profile)
    pair_mode = dual and count == 1
    say(5, "מנתח את הבקשה…")
    info = parse_event(prompt)
    notes: list[str] = []
    cloud = use_ai and (client is not None or (HAS_GENAI and HAS_PYDANTIC and api_key))

    template, pair, engine, design = None, None, "offline", None
    if cloud:
        say(15, "מעצב עם Gemini (Structured Output)…")
        try:
            design = generate_design(prompt, profile, count, api_key, text_model, client, info)
            say(45, "ממיר את העיצוב לתבנית…")
            if pair_mode:
                pair = build_frame_pair(profile=profile, credit_text=credit_text,
                                        info=_info_from_design(design, info), style=_style_from_design(design, info))
            else:
                template = design_to_template(design, profile, count)
            engine = "ai"
        except GeneratorUnavailable as e:
            notes.append(str(e))
            say(45, "AI לא זמין – עובר למחולל אופליין")
    elif use_ai:
        notes.append("אין מפתח API / SDK – נבנה במחולל האופליין")
    if pair is None and template is None:
        say(50, "בונה מסגרת (אנכית + אופקית)…" if pair_mode else "בונה מסגרת וקטורית…")
        if pair_mode:
            pair = build_frame_pair(profile=profile, credit_text=credit_text, info=info)
        else:
            template = build_preset_template(prompt, profile, count, info)
    if template is not None and credit_text and template.credit is None:
        template.credit = CreditLayer(text=credit_text)

    targets = list(pair.variants.values()) if pair else [template]
    art = False
    if use_art and cloud:
        art_prompt = (design.art_prompt if design is not None and design.art_prompt else
                      f"{info.style} style ornamental border, colors {', '.join(info.colors) or 'elegant'}")
        try:
            for i, t in enumerate(targets):
                say(60 + 12 * i, f"יוצר רקע אמנותי (Gemini Image) – {t.orientation}…")
                img = generate_art(art_prompt, t.canvas.width, t.canvas.height, api_key, art_model, client)
                say(70 + 12 * i, "חותך חלונות שקופים (Alpha Hole Punch)…")
                add_art_layer(t, img)
            art = True
        except GeneratorUnavailable as e:
            notes.append(str(e))
            say(85, "רקע AI נכשל – ממשיך עם מסגרת וקטורית")
    say(100, "המסגרת מוכנה")
    log.info("Frame generated: engine=%s art=%s pair=%s profile=%s prompt=%r", engine, art,
             pair is not None, profile, prompt[:80])
    for n in notes:
        log.warning("Frame generator fallback: %s", n)
    return GenerationResult(pair.portrait if pair else template, engine, art, notes, pair)


# ============================================================== worker (Qt)

try:
    from PyQt6.QtCore import QThread, pyqtSignal

    class FrameGeneratorWorker(QThread):
        """Runs generate_frame off the GUI thread.

        progress(int, str) · finished(Template | TemplatePair) · failed(str)
        Note: `finished` intentionally shadows QThread.finished (per spec). It carries the
        TemplatePair for single-photo frames, else the Template; self.result has both.
        """
        progress = pyqtSignal(int, str)
        finished = pyqtSignal(object)
        failed = pyqtSignal(str)

        def __init__(self, prompt: str, profile: str, slot_count: int | None = None, use_ai: bool = True,
                     use_art: bool = True, api_key: str = "", text_model: str = DEFAULT_TEXT_MODEL,
                     art_model: str = DEFAULT_ART_MODEL, client=None, parent=None,
                     credit_text: str | None = DEFAULT_CREDIT, dual: bool = True):
            super().__init__(parent)
            self.kw = dict(prompt=prompt, profile=profile, slot_count=slot_count, use_ai=use_ai,
                           use_art=use_art, api_key=api_key, text_model=text_model,
                           art_model=art_model, client=client, credit_text=credit_text, dual=dual)
            self.result: GenerationResult | None = None

        def run(self) -> None:
            try:
                self.result = generate_frame(**self.kw, progress=lambda p, s: self.progress.emit(p, s))
                self.finished.emit(self.result.frame)
            except Exception as e:
                self.failed.emit(str(e))
except ImportError:
    FrameGeneratorWorker = None  # type: ignore[assignment,misc]
