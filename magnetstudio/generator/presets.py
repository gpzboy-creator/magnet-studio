"""Offline frame builders: classic multi-slot frame, the Israeli single-photo frame and its
portrait + landscape pair."""

from __future__ import annotations

from PIL import Image, ImageDraw

from magnetstudio.core.templates import (
    LANDSCAPE,
    PORTRAIT,
    CanvasConfig,
    CreditLayer,
    GraphicLayer,
    PhotoSlot,
    Template,
    TemplatePair,
    TextLayer,
    parse_color,
)
from magnetstudio.generator.colors import palette_for
from magnetstudio.generator.layout import (
    SANS_HE,
    SERIF_HE,
    _pick_family,
    _text_w,
    default_slot_count,
    preset_slots,
    safe_margin,
    stack_texts,
    text_height,
)
from magnetstudio.generator.ornaments import _save_generated, draw_emblem, draw_flourish, draw_ornament
from magnetstudio.generator.parse import EventInfo, parse_event
from magnetstudio.generator.styles import DEFAULT_CREDIT, FrameStyle, style_from_info

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
