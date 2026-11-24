"""Template check: load the 7.5x10 sample (Hebrew text + 2 photo slots), render at 300 DPI,
verify text alignment and slot transparency, and drive the designer headlessly.

Run:  pytest tests/test_templates.py
"""
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

from PIL import Image, ImageDraw  # noqa: E402

from magnetstudio.core.templates import (HAS_RAQM, PhotoSlot, Template, TextLayer, compose_magnet,  # noqa: E402
                            load_template, render_overlay_frame, render_text_layer,
                            save_template, template_to_dict)

from magnetstudio.paths import BUNDLED_TEMPLATES_DIR  # noqa: E402

SAMPLE = BUNDLED_TEMPLATES_DIR / "sample_wedding_7.5x10.json"
OUT = ROOT / "output" / "tests"
failures = 0


def check(cond, msg):
    global failures
    print(("  ✔ " if cond else "  ✘ ") + msg)
    failures += not cond


def make_sample() -> Template:
    """The bundled sample: 7.5x10, two photo windows, Hebrew title + date."""
    t = Template.new("7.5x10", "דוגמה – חתונה", slot_preset=None)
    W, H = t.canvas.width, t.canvas.height          # 886 x 1181
    t.canvas.bg_color = "#F6EFE6FF"
    m, gap = 44, 24
    slot_w = (W - 2 * m - gap) // 2
    t.slots = [PhotoSlot(m, m, slot_w, 820, radius=24),
               PhotoSlot(m + slot_w + gap, m, slot_w, 820, radius=24)]
    t.texts = [
        TextLayer("מזל טוב! דנה ויוסי", x=m, y=900, width=W - 2 * m, font_size=78, bold=True,
                  color="#6B4A34FF", align="center"),
        TextLayer("24.10.2026 · אולמי הגן", x=m, y=1010, width=W - 2 * m, font_size=44,
                  color="#8C6A52FF", align="center"),
        TextLayer("Gpzboy", x=m, y=1095, width=W - 2 * m, font_size=34, color="#B39883FF", align="right"),
    ]
    return t


def ink_bbox(img: Image.Image):
    return img.getchannel("A").getbbox()


def _run() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    print(f"RTL engine: {'libraqm (full bidi)' if HAS_RAQM else 'python-bidi fallback'}")

    print("1) Sample template – save / load JSON")
    if not SAMPLE.exists():
        save_template(make_sample(), SAMPLE)
    t = load_template(SAMPLE)
    check((t.canvas.width, t.canvas.height) == (886, 1181), f"canvas {t.canvas.width}x{t.canvas.height} @ 300 DPI")
    check(len(t.slots) == 2, f"{len(t.slots)} photo slots")
    rt = load_template(save_template(t, OUT / "roundtrip.json"))
    check(template_to_dict(rt) == template_to_dict(t), "JSON round-trip is lossless")

    print("2) Overlay render")
    t0 = time.perf_counter()
    overlay = render_overlay_frame(t)
    first_ms = (time.perf_counter() - t0) * 1000
    t0 = time.perf_counter()
    overlay = render_overlay_frame(t)
    ms = (time.perf_counter() - t0) * 1000
    check(overlay.size == (886, 1181) and overlay.mode == "RGBA", f"RGBA {overlay.size}")
    check(ms < 300, f"render {ms:.0f} ms (first call {first_ms:.0f} ms incl. font scan)")
    for i, s in enumerate(t.slots):
        check(overlay.getpixel((s.x + s.w // 2, s.y + s.h // 2))[3] == 0, f"slot {i + 1} centre transparent")
        check(overlay.getpixel((s.x + 2, s.y + 2))[3] == 255, f"slot {i + 1} rounded corner stays opaque")
    check(overlay.getpixel((5, 5))[3] == 255, "frame border opaque")

    print("3) Hebrew text alignment")
    for layer in t.texts:
        img = render_text_layer(layer)
        x0, _, x1, _ = ink_bbox(img)
        ox = -img.info.get("offset", (0, 0))[0]          # image may be padded for overhangs
        box_w = img.info.get("layout_size", img.size)[0]
        left, right = x0 - ox, box_w - (x1 - ox)
        if layer.align == "center":
            ok = abs(left - right) <= 4
        elif layer.align == "right":
            ok = right <= 4
        else:
            ok = left <= 4
        check(ok, f"'{layer.text}' align={layer.align}: margins L={left}px R={right}px")
    # bidi sanity: logical Hebrew must not render reversed (compare with python-bidi visual order)
    try:
        from bidi import get_display
        from PIL import ImageChops, ImageFont
        from magnetstudio.core.templates import get_font
        f = get_font("", 60)
        a = render_text_layer(TextLayer("שלום עולם", font_size=60, color="#000000FF"))
        b = Image.new("RGBA", a.size, (0, 0, 0, 0))
        basic = ImageFont.truetype(f.path, 60, layout_engine=ImageFont.Layout.BASIC)
        ox, oy = a.info.get("offset", (0, 0))  # render may be padded for glyph overhang
        ImageDraw.Draw(b).text((-ox, -oy), get_display("שלום עולם"), font=basic, fill=(0, 0, 0, 255))
        diff = ImageChops.difference(a.getchannel("A"), b.getchannel("A")).point(lambda v: 255 if v > 128 else 0)
        changed = sum(diff.histogram()[255:]) / (a.width * a.height)
        check(changed < 0.02, f"Hebrew visual order matches bidi reference ({changed:.2%} px differ)")
    except ImportError:
        print("  – python-bidi not installed, skipped reference check")

    print("4) Composite with dummy photos → file")
    photos = []
    for i, c in enumerate([(70, 120, 190), (200, 120, 80)]):
        p = Image.new("RGB", (1200, 1600), c)
        ImageDraw.Draw(p).text((80, 80), f"PHOTO {i + 1}", fill="white", font_size=140)
        photos.append(p)
    magnet = compose_magnet(t, photos, overlay)
    out = OUT / "sample_7.5x10_render.png"
    magnet.save(out, dpi=(300, 300))
    overlay.save(OUT / "sample_7.5x10_overlay.png", dpi=(300, 300))
    with Image.open(out) as im:
        dpi = tuple(round(v) for v in im.info.get("dpi", (0, 0)))
        check(im.size == (886, 1181) and dpi == (300, 300), f"{out.name}: {im.size} @ {dpi} DPI")

    print("5) Designer (headless)")
    from PyQt6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication(sys.argv)
    from magnetstudio.core.settings import load_settings
    from magnetstudio.ui.designer import GraphicItem, SlotItem, TemplateDesigner, TextItem
    from magnetstudio.ui.main_window import MainWindow

    win = MainWindow(load_settings())
    d = TemplateDesigner(load_template(SAMPLE), SAMPLE)
    d.template_saved.connect(win.set_active_frame)
    d.frame_exported.connect(win.set_active_frame)
    items = d.scene.items()
    check(sum(isinstance(i, SlotItem) for i in items) == 2, "2 slot items on canvas")
    check(sum(isinstance(i, TextItem) for i in items) == 3, "3 text items on canvas")
    check(not d._dirty, "opening a template does not mark it dirty")

    d.add_text()
    logo = OUT / "logo.png"
    lg = Image.new("RGBA", (400, 200), (0, 0, 0, 0))
    ImageDraw.Draw(lg).rounded_rectangle((0, 0, 399, 199), 40, fill=(200, 60, 90, 220))
    lg.save(logo)
    g = d.add_graphic_from(str(logo))
    w0 = g.layer.w
    g.handle.setPos(w0 + 100, 0)   # drag resize handle → keeps aspect ratio
    check(g.layer.w == w0 + 100 and abs(g.layer.w / g.layer.h - 2) < 0.02,
          f"resize handle: {g.layer.w}x{g.layer.h} (aspect kept)")
    g.setPos(50, 60)
    check((g.layer.x, g.layer.y) == (50, 60), "drag updates layer position")

    d._apply_preset(d.preset_box.findData("strip4"))
    check(len(d.template.slots) == 4, "one click → 4-window strip")
    d.profile_box.setCurrentIndex(d.profile_box.findData("5x15_strip"))
    check((d.template.canvas.width, d.template.canvas.height) == (591, 1772), "profile switch → 5x15 strip canvas")

    exported = d.export_to_main()
    check(win.frame_box.currentData() == str(exported), f"export activates frame in main window ({exported.name})")
    check(win.size_box.currentData() == "5x15_strip", "main window size follows the frame")
    exported.unlink(missing_ok=True)

    print("\nPASS" if not failures else f"\nFAIL ({failures})")
    print(f"renders: {OUT}")
    return 1 if failures else 0


def test_templates():
    """Scenario test – every ✔/✘ line is printed; pytest shows them when a check fails."""
    assert _run() == 0, f"{failures} check(s) failed – see the ✘ lines in the captured output"
