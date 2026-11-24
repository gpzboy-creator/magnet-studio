"""Israeli magnet style: FrameStyle (palette, emblem, flourish) chosen from the request."""

from __future__ import annotations

import re
from dataclasses import dataclass

from magnetstudio.generator.colors import _hex, _lum, _mix, _rgb, ensure_contrast, palette_for
from magnetstudio.generator.parse import EventInfo

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
