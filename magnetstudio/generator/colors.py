"""Color helpers: hex/RGB, WCAG contrast, readable text colors, palettes per style."""

from __future__ import annotations

from magnetstudio.core.templates import (
    parse_color,
)
from magnetstudio.generator.parse import EventInfo

STYLE_PALETTES = {  # (background, accent)
    "moroccan": ("#5E1428", "#D4AF37"),
    "classic": ("#F6EFE6", "#8C6A52"),
    "corners": ("#F3E9DC", "#A0704B"),
    "minimal": ("#FFFFFF", "#222222"),
}


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
