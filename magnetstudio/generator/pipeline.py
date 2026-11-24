"""generate_frame(): parse → Gemini design (or offline) → optional AI art → Template / pair.
Never raises for cloud problems – falls back to the offline builders."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Callable

from magnetstudio.core.templates import (
    CreditLayer,
    Template,
    TemplatePair,
)
from magnetstudio.generator.ai import (
    DEFAULT_ART_MODEL,
    DEFAULT_TEXT_MODEL,
    HAS_GENAI,
    HAS_PYDANTIC,
    FrameDesign,
    GeneratorUnavailable,
    _valid_hex,
    add_art_layer,
    design_to_template,
    generate_art,
    generate_design,
)
from magnetstudio.generator.colors import _hex, _mix, _rgb, ensure_contrast
from magnetstudio.generator.layout import default_slot_count
from magnetstudio.generator.parse import HE, EventInfo, parse_event
from magnetstudio.generator.presets import build_frame_pair, build_preset_template
from magnetstudio.generator.styles import DEFAULT_CREDIT, FrameStyle, style_from_info

log = logging.getLogger(__name__)

Progress = Callable[[int, str], None]


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
