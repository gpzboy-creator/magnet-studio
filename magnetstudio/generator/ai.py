"""Gemini: Structured Output design (Pydantic FrameDesign), clamping it into a valid Template,
and background art from a Gemini image model (Imagen was shut down on 17 Aug 2026)."""

from __future__ import annotations

import io
import re
from typing import Literal

from PIL import Image, ImageOps

from magnetstudio.core.templates import (
    CanvasConfig,
    GraphicLayer,
    PhotoSlot,
    Template,
    TextLayer,
)
from magnetstudio.generator.colors import STYLE_PALETTES, _hex, _rgb, ensure_contrast
from magnetstudio.generator.layout import (
    SANS_HE,
    SERIF_HE,
    _overlaps,
    _pick_family,
    default_slot_count,
    fit_text,
    preset_slots,
    safe_margin,
    stack_texts,
    text_height,
)
from magnetstudio.generator.ornaments import _save_generated, draw_ornament, punch_alpha_holes
from magnetstudio.generator.parse import EventInfo, parse_event

DEFAULT_TEXT_MODEL = "gemini-3.8-flash"
DEFAULT_ART_MODEL = "gemini-3.1-flash-image"
ART_ASPECTS = {"1:1": 1, "2:3": 2 / 3, "3:2": 1.5, "3:4": 0.75, "4:3": 4 / 3,
               "9:16": 9 / 16, "16:9": 16 / 9, "21:9": 21 / 9}


class GeneratorUnavailable(RuntimeError):
    """Cloud generation not possible (no SDK / key / network / bad response)."""


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
    FrameDesign = SlotSpec = TextSpec = None  # type: ignore[assignment,misc]

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
