"""Israeli magnet frame style: photo window + footer (names ♥ date) + side credit + corner flourishes,
in portrait and landscape, with automatic orientation selection.

Builds the "זית עדין" (subtle olive) sample, renders a landscape and a portrait dummy photo through it,
and checks readability, credit sharpness and a clean photo window.

Run:  pytest tests/test_frames_style.py
"""
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

from PIL import Image, ImageDraw, ImageFilter, ImageOps  # noqa: E402

from magnetstudio.generator import (DEFAULT_CREDIT, build_frame_pair, contrast, safe_margin,  # noqa: E402
                                  text_height)
from magnetstudio.core.framer import render_magnet  # noqa: E402
from magnetstudio.core.templates import (LANDSCAPE, PORTRAIT, TemplatePair, compose_auto, export_frame_png,  # noqa: E402
                            load_frame, parse_color, render_credit_layer, render_overlay_frame, save_frame)

OUT = ROOT / "output" / "tests"
PROMPT = "חתונה של נועה ואורי 13.8.2026, זית עדין עם לב אדום"
failures = 0


def check(cond, msg):
    global failures
    print(("  ✔ " if cond else "  ✘ ") + msg)
    failures += not cond


def dummy_photo(w: int, h: int, seed: int) -> Image.Image:
    """Busy, high-detail photo (gradient + bokeh + stripes) so any haze/tint would show."""
    import random
    rnd = random.Random(seed)
    im = Image.new("RGB", (w, h))
    d = ImageDraw.Draw(im)
    for y in range(h):
        t = y / h
        d.line([(0, y), (w, y)], fill=(int(40 + 200 * t), int(90 + 80 * (1 - t)), int(200 - 120 * t)))
    blobs = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    bd = ImageDraw.Draw(blobs)
    for _ in range(60):
        r = rnd.randint(w // 60, w // 12)
        x, y = rnd.randint(0, w), rnd.randint(0, h)
        bd.ellipse((x - r, y - r, x + r, y + r), fill=(255, 240, 200, rnd.randint(30, 90)))
    im = Image.alpha_composite(im.convert("RGBA"), blobs.filter(ImageFilter.GaussianBlur(w / 200))).convert("RGB")
    d = ImageDraw.Draw(im)
    for x in range(0, w, max(8, w // 90)):  # fine stripes → detail everywhere
        d.line([(x, int(h * 0.55)), (x, h)], fill=(30, 30, 40), width=2)
    return im


def px(im: Image.Image) -> list:
    """Pixel list (Pillow 12+ get_flattened_data; getdata on older versions)."""
    return list(im.get_flattened_data() if hasattr(im, "get_flattened_data") else im.getdata())


def _run() -> int:
    OUT.mkdir(parents=True, exist_ok=True)

    print("1) Sample template – 'זית עדין' (names + red heart + date + photographer credit)")
    pair = build_frame_pair(PROMPT, "7.5x10", DEFAULT_CREDIT)
    check(isinstance(pair, TemplatePair) and set(pair.variants) == {PORTRAIT, LANDSCAPE},
          "pair with portrait + landscape")
    sizes = {o: (t.canvas.width, t.canvas.height) for o, t in pair.variants.items()}
    check(sizes == {PORTRAIT: (886, 1181), LANDSCAPE: (1181, 886)}, f"canvas sizes {sizes}")

    for o, t in pair.variants.items():
        print(f"   · {o}")
        W, H = t.canvas.width, t.canvas.height
        m = safe_margin(t.canvas)
        texts = {x.text: x for x in t.texts}
        check({"נועה", "אורי", "13.8.2026"} <= set(texts), f"footer texts {sorted(texts)} (date as typed)")
        emblem = [g for g in t.graphics if Path(g.path).name.startswith("emblem_heart")]
        heart = Image.open(emblem[0].path).convert("RGBA") if emblem else None
        red = heart and heart.getpixel((heart.width // 2, heart.height // 2))
        check(bool(emblem) and red[0] > 150 and red[1] < 60 and red[3] > 200, f"red heart emblem {red}")
        a, b = texts["נועה"], texts["אורי"]
        em = emblem[0]
        check(a.x > em.x + em.w - 2 and b.x + b.width < em.x + 2, "RTL order: נועה (right) ♥ אורי (left)")
        slot = t.slots[0]
        footer_top = slot.y + slot.h
        check(all(x.y >= footer_top for x in t.texts) and em.y >= footer_top, "names / heart / date in the footer bar")
        check(all(x.y + text_height(x) <= H - m + 1 for x in t.texts), "footer keeps the bottom safe margin")
        if o == LANDSCAPE:
            check(abs(texts["13.8.2026"].y - a.y) < text_height(a), "landscape: date on the names row (spread out)")
        else:
            check(texts["13.8.2026"].y > a.y + text_height(a) - 2, "portrait: date under the names (narrow)")

        cr = t.credit
        check(cr is not None and cr.text == DEFAULT_CREDIT and cr.side == "right" and cr.rotation in (90, 270),
              f"credit layer: '{cr.text}' right, rotated {cr.rotation}°")
        cimg, cx, cy = render_credit_layer(cr, t.canvas)
        check(cx >= slot.x + slot.w and cx + cimg.width <= W, f"credit sits in the right margin (x={cx}, slot ends {slot.x + slot.w})")
        check(cimg.height > cimg.width * 4, f"credit is vertical ({cimg.width}x{cimg.height})")
        check(contrast(parse_color(cr.color)[:3], parse_color(t.canvas.bg_color)[:3]) >= 4.0,
              f"credit grey {cr.color} readable on {t.canvas.bg_color}")

        fl = [g for g in t.graphics if Path(g.path).name.startswith("flourish_olive")]
        sx0, sy0, sx1, sy1 = slot.x, slot.y, slot.x + slot.w, slot.y + slot.h
        overlap = [g for g in fl if g.x < sx1 and g.x + g.w > sx0 and g.y < sy1 and g.y + g.h > sy0  # touches photo
                   and (g.x < sx0 or g.y < sy0 or g.x + g.w > sx1 or g.y + g.h > sy1)]           # and its margin
        check(len(fl) == 2 and len(overlap) == 2, "two olive corner flourishes overlapping the photo edges")
        hits = [(g, x) for g in fl for x in t.texts
                if g.x < x.x + x.width and g.x + g.w > x.x and g.y < x.y + text_height(x) and g.y + g.h > x.y]
        flourish_ink = []
        for g, x in hits:  # boxes may touch – make sure no actual leaf pixel lands on a text box
            img = Image.open(g.path).convert("RGBA").resize((g.w, g.h))
            box = (max(0, x.x - g.x), max(0, x.y - g.y), min(g.w, x.x + x.width - g.x), min(g.h, x.y + text_height(x) - g.y))
            if box[2] > box[0] and box[3] > box[1] and img.getchannel("A").crop(box).getbbox():
                flourish_ink.append(x.text)
        check(not flourish_ink, f"flourishes never touch the footer text {flourish_ink or ''}")

        ov = render_overlay_frame(t)
        check(ov.size == (W, H) and ov.mode == "RGBA" and ov.info.get("dpi") == (300, 300),
              f"render_overlay_frame → RGBA {ov.size} @ 300 DPI")
        png = export_frame_png(t, OUT / f"olive_overlay_{o}.png")
        with Image.open(png) as im:
            check(im.size == (W, H) and tuple(round(v) for v in im.info["dpi"]) == (300, 300),
                  f"{png.name}: {im.size} @ 300 DPI")
        centre = ov.getpixel((slot.x + slot.w // 2, slot.y + slot.h // 2))[3]
        check(centre == 0, "photo window alpha = 0")

    print("2) Automatic orientation from the camera photo")
    tmp = Path(tempfile.mkdtemp(prefix="msframes_"))
    pair_path = save_frame(pair, tmp / "olive.json")
    land_photo, port_photo = dummy_photo(3000, 2000, 1), dummy_photo(2000, 3000, 2)
    land_photo.save(tmp / "land.jpg", quality=92)
    port_photo.save(tmp / "port.jpg", quality=92)
    # portrait shot stored sideways with an EXIF rotation flag (what many cameras/phones do)
    exif = Image.Exif()
    exif[0x0112] = 6  # rotate 90° CW on display
    port_photo.transpose(Image.Transpose.ROTATE_90).save(tmp / "port_exif.jpg", quality=92, exif=exif)
    for name, expect in (("land.jpg", (1181, 886)), ("port.jpg", (886, 1181)), ("port_exif.jpg", (886, 1181))):
        img = render_magnet(tmp / name, "7.5x10", pair_path)
        check(img.size == expect, f"{name:14s} → {img.size} ({'landscape' if expect[0] > expect[1] else 'portrait'} frame)")
    from magnetstudio.core.printer import PrintJob, PrintMode
    job = PrintJob(mode=PrintMode.THERMAL, printer_name="", photo_paths=[str(tmp / "land.jpg")],
                   magnet_size="7.5x10", frame_path=str(pair_path))
    check(job.render_images()[0].size == (1181, 886), "print jobs pick the variant too")

    print("3) Readability, sharp credit, clean photo window (dummy photos)")
    renders = {}
    for o, photo in ((LANDSCAPE, land_photo), (PORTRAIT, port_photo)):
        t = pair.variants[o]
        magnet = compose_auto(pair, [photo])
        renders[o] = magnet
        magnet.save(OUT / f"olive_magnet_{o}.png", dpi=(300, 300))
        bg = parse_color(t.canvas.bg_color)[:3]

        # names: solid ink in the name colour, high contrast on the footer
        for tx in t.texts:
            crop = magnet.crop((tx.x, tx.y, tx.x + tx.width, tx.y + text_height(tx)))
            ink = [p for p in px(crop) if sum(abs(a - b) for a, b in zip(p, bg)) > 120]
            want = parse_color(tx.color)[:3]
            solid = [p for p in ink if sum(abs(a - b) for a, b in zip(p, want)) < 40]
            ratio = contrast(want, bg)
            check(len(ink) > tx.font_size * 20 and len(solid) > 0.3 * len(ink) and ratio >= 4.5,
                  f"{o}: '{tx.text}' readable – {tx.font_size}px, contrast {ratio:.1f}:1, "
                  f"{len(solid) / max(1, len(ink)):.0%} solid ink")

        # credit: pixel-exact vs. the transposed text → no resampling blur
        cimg, cx, cy = render_credit_layer(t.credit, t.canvas)
        expected = Image.new("RGBA", cimg.size, bg + (255,))
        expected.alpha_composite(cimg)
        got = magnet.crop((cx, cy, cx + cimg.width, cy + cimg.height))
        diff = max(max(abs(a - b) for a, b in zip(p, q)) for p, q in zip(px(got), px(expected.convert("RGB"))))
        alpha = px(cimg.getchannel("A"))
        solid_px = sum(v == 255 for v in alpha) / max(1, sum(v > 0 for v in alpha))
        check(diff <= 1 and solid_px > 0.3, f"{o}: credit pixel-exact (max diff {diff}), {solid_px:.0%} fully solid glyph pixels")

        # photo window: every pixel not covered by a flourish is exactly the photo
        slot = t.slots[0]
        fitted = ImageOps.fit(photo, (slot.w, slot.h), method=Image.Resampling.LANCZOS)
        ov_alpha = render_overlay_frame(t).getchannel("A").crop((slot.x, slot.y, slot.x + slot.w, slot.y + slot.h))
        win = magnet.crop((slot.x, slot.y, slot.x + slot.w, slot.y + slot.h))
        clear = mismatch = covered = 0
        for p, q, a in zip(px(win), px(fitted), px(ov_alpha)):
            if a == 0:
                clear += 1
                mismatch += p != q
            else:
                covered += 1
        cov = covered / (clear + covered)
        check(mismatch == 0, f"{o}: photo untouched through the window ({clear:,} px identical)")
        check(0.005 < cov < 0.08, f"{o}: flourishes cover {cov:.1%} of the photo (subtle corner overlap)")
        w, h = ov_alpha.size
        centre_cov = sum(1 for y in range(h // 4, 3 * h // 4, 4) for x in range(w // 4, 3 * w // 4, 4)
                         if ov_alpha.getpixel((x, y)))
        check(centre_cov == 0, f"{o}: centre of the photo completely clear")

    print("4) JSON round-trip + designer")
    back = load_frame(pair_path)
    same = all(render_overlay_frame(back.variants[o]).tobytes() == render_overlay_frame(pair.variants[o]).tobytes()
               for o in pair.variants)
    check(isinstance(back, TemplatePair) and same, "pair saved/loaded as one JSON, renders identical")
    from PyQt6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication(sys.argv)  # noqa: F841
    from magnetstudio.ui.designer import CreditItem, TemplateDesigner
    d = TemplateDesigner(back, pair_path)
    check(d.orient_box.isEnabled() and d.template.orientation == PORTRAIT, "designer opens the pair (portrait first)")
    check(any(isinstance(i, CreditItem) for i in d.scene.items()), "credit shown on the canvas")
    d.orient_box.setCurrentIndex(d.orient_box.findData(LANDSCAPE))
    check(d.template.orientation == LANDSCAPE and d.scene.sceneRect().width() > d.scene.sceneRect().height(),
          "orientation switch → landscape canvas")
    d.update_credit(text="שחר לוי גונן | צילום מגנטים")
    check(all(v.credit.text == "שחר לוי גונן | צילום מגנטים" for v in d.pair.variants.values()),
          "credit edit applies to both orientations")
    d.save(tmp / "olive_edited.json")
    again = load_frame(tmp / "olive_edited.json")
    check(isinstance(again, TemplatePair) and again.landscape.credit.text.endswith("צילום מגנטים"),
          "saved back as a pair")

    # contact sheet
    H = 760
    row = [im.resize((round(im.width * H / im.height), H)) for im in (renders[LANDSCAPE], renders[PORTRAIT])]
    sheet = Image.new("RGB", (sum(r.width for r in row) + 60, H + 40), (40, 42, 46))
    x = 20
    for r in row:
        sheet.paste(r, (x, 20))
        x += r.width + 20
    sheet.save(OUT / "olive_sheet.png")

    print("\nPASS" if not failures else f"\nFAIL ({failures})")
    print(f"renders: {OUT}")
    return 1 if failures else 0


def test_frames_style():
    """Scenario test – every ✔/✘ line is printed; pytest shows them when a check fails."""
    assert _run() == 0, f"{failures} check(s) failed – see the ✘ lines in the captured output"
