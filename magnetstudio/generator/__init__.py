"""Frame generator: free-text event description → ready Template (or portrait + landscape pair).

  parse      offline Hebrew parsing (event, names, date, colors, style)
  colors     contrast-safe colors and palettes
  layout     safe margins, text fitting, slot presets
  styles     Israeli magnet style (emblem, flourish, palette)
  ornaments  procedural 300 DPI graphics + alpha hole punch
  presets    offline builders (classic, Israeli single photo, portrait/landscape pair)
  ai         Gemini Structured Output design + background art (optional)
  pipeline   generate_frame – orchestration with automatic offline fallback

The Qt worker is magnetstudio.services.generator_worker.FrameGeneratorWorker.
"""
from magnetstudio.generator.ai import (ART_ASPECTS, DEFAULT_ART_MODEL, DEFAULT_TEXT_MODEL, HAS_GENAI, HAS_PYDANTIC,
                                       FrameDesign, GeneratorUnavailable, SlotSpec, TextSpec, add_art_layer,
                                       design_to_template, generate_art, generate_design, nearest_aspect)
from magnetstudio.generator.colors import STYLE_PALETTES, contrast, ensure_contrast, palette_for
from magnetstudio.generator.layout import (default_slot_count, fit_text, preset_slots, safe_margin, stack_texts,
                                           text_height)
from magnetstudio.generator.ornaments import (GENERATED_DIR, draw_emblem, draw_flourish, draw_heart,
                                              draw_olive_branch, draw_ornament, draw_rings, draw_watercolor_corner,
                                              draw_wreath, punch_alpha_holes)
from magnetstudio.generator.parse import EventInfo, parse_event
from magnetstudio.generator.pipeline import GenerationResult, Progress, generate_frame
from magnetstudio.generator.presets import build_frame_pair, build_israeli_template, build_preset_template
from magnetstudio.generator.styles import DEFAULT_CREDIT, EMBLEMS, FLOURISHES, FrameStyle, style_from_info

__all__ = [
    "ART_ASPECTS", "DEFAULT_ART_MODEL", "DEFAULT_CREDIT", "DEFAULT_TEXT_MODEL", "EMBLEMS", "FLOURISHES",
    "GENERATED_DIR", "HAS_GENAI", "HAS_PYDANTIC", "STYLE_PALETTES",
    "EventInfo", "FrameDesign", "FrameStyle", "GenerationResult", "GeneratorUnavailable", "Progress",
    "SlotSpec", "TextSpec",
    "add_art_layer", "build_frame_pair", "build_israeli_template", "build_preset_template", "contrast",
    "default_slot_count", "design_to_template", "draw_emblem", "draw_flourish", "draw_heart",
    "draw_olive_branch", "draw_ornament", "draw_rings", "draw_watercolor_corner", "draw_wreath",
    "ensure_contrast", "fit_text", "generate_art", "generate_design", "generate_frame", "nearest_aspect",
    "palette_for", "parse_event", "preset_slots", "punch_alpha_holes", "safe_margin", "stack_texts",
    "style_from_info", "text_height",
]
