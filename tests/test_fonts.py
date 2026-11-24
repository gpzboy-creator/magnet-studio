"""Custom font check: registry, Qt registration, Hebrew rendering without glyph clipping
at 300 DPI, live "add font", and the default-bundle downloader (simulated network).

Run:  pytest tests/test_fonts.py
"""
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

from PIL import Image, ImageDraw  # noqa: E402

from magnetstudio.core import fonts
from magnetstudio.paths import BUNDLED_FONTS_DIR as BUNDLED  # noqa: E402
from magnetstudio.core.templates import Template, TextLayer, compose_magnet, get_font, render_text_layer  # noqa: E402

OUT = ROOT / "output" / "tests"
failures = 0

SAMPLES = {
    "plain": "מזל טוב!",
    "nikud": "שָׁלוֹם וּבְרָכָה",          # marks above and below the letters
    "descenders": "ץף ךן ק – פרץ",
    "mixed": "חינה 18.09.2026 – Moran & Aviv",
    "multiline": "מורן ואביב\nחינה · 18.09.2026",
}


def check(cond, msg):
    global failures
    print(("  ✔ " if cond else "  ✘ ") + msg)
    failures += not cond


def alpha_sum(img: Image.Image) -> int:
    return sum(i * n for i, n in enumerate(img.getchannel("A").histogram()))


def reference_ink(layer: TextLayer) -> int:
    """Same text drawn on a huge canvas – nothing can be clipped there."""
    f = get_font(layer.font_family, layer.font_size, layer.bold, layer.font_path)
    pad = layer.font_size * 2
    lines = layer.text.split("\n")
    a, d = f.getmetrics()
    lh = round((a + d) * layer.line_spacing)
    w = int(max(f.getlength(s) for s in lines)) + 2 * pad
    canvas = Image.new("RGBA", (w, lh * len(lines) + 2 * pad), (0, 0, 0, 0))
    dr = ImageDraw.Draw(canvas)
    for i, s in enumerate(lines):
        dr.text((pad, pad + i * lh), s, font=f, fill=(0, 0, 0, 255),
                stroke_width=layer.stroke_width, stroke_fill=(0, 0, 0, 255))
    return alpha_sum(canvas)


def _run() -> int:
    OUT.mkdir(parents=True, exist_ok=True)

    print("1) Registry & family → file mapping")
    custom = fonts.custom_font_families()
    check({"Heebo", "Assistant", "Rubik", "Varela Round"} <= set(custom), f"bundled fonts found: {custom}")
    allf = fonts.available_font_families()
    check(allf[:len(custom)] == custom, "custom fonts listed before system fonts")
    for fam in ("Heebo", "Assistant", "Rubik"):
        r, b = fonts.resolve_font_path(fam), fonts.resolve_font_path(fam, bold=True)
        check(Path(r).parent == BUNDLED and r.endswith("Regular.ttf") and b.endswith("Bold.ttf"),
              f"{fam}: regular → {Path(r).name}, bold → {Path(b).name}")
    check(fonts.resolve_font_path("hEeBo") == fonts.resolve_font_path("Heebo"), "case-insensitive lookup")
    check(Path(fonts.resolve_font_path("No Such Font")).parent == BUNDLED,
          "unknown family falls back to a bundled Hebrew font")

    print("2) Qt registration")
    from PyQt6.QtGui import QFontDatabase
    from PyQt6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication(sys.argv)  # noqa: F841
    from magnetstudio.services.fonts_qt import register_qt_fonts
    qt_fams = register_qt_fonts()
    db_fams = set(QFontDatabase.families())
    check({"Heebo", "Assistant", "Rubik", "Varela Round"} <= db_fams, f"QFontDatabase knows {sorted(set(qt_fams))}")
    check(register_qt_fonts() == [], "registration is idempotent")
    check(all(fonts.resolve_font_path(q) and Path(fonts.resolve_font_path(q)).parent == BUNDLED
              for q in qt_fams), "every Qt family name maps back to its file for Pillow")

    print("3) Hebrew at 300 DPI – no glyph clipping")
    worst = 0.0
    old_box_worst = (0.0, "")
    tight = [f for f in ("FreeSerif", "DejaVu Serif", "Times New Roman") if fonts.resolve_font_path(f)
             and fonts.canonical_family(f) == f][:1]  # a system font with tight line metrics
    test_fams = custom + tight
    for fam in test_fams:
        for bold in (False, True):
            for key, text in SAMPLES.items():
                for stroke in (0, 6):
                    layer = TextLayer(text=text, font_family=fam, font_size=140, bold=bold,
                                      color="#000000FF", align="center", stroke_width=stroke,
                                      stroke_color="#000000FF")
                    img = render_text_layer(layer)
                    ref = reference_ink(layer)
                    got = alpha_sum(img)
                    loss = abs(ref - got) / max(1, ref)
                    worst = max(worst, loss)
                    if loss > 0.002:
                        check(False, f"{fam} bold={bold} {key} stroke={stroke}: {loss:.2%} ink lost")
                    # how much the old fixed layout box (no padding) would have cut off
                    lw, lh = img.info["layout_size"]
                    ox, oy = img.info["offset"]
                    old_loss = 1 - alpha_sum(img.crop((-ox, -oy, -ox + lw, -oy + lh))) / max(1, got)
                    if old_loss > old_box_worst[0]:
                        old_box_worst = (old_loss, f"{fam} {key}{' bold' if bold else ''}{' stroke' if stroke else ''}")
    combos = len(test_fams) * 2 * len(SAMPLES) * 2
    check(worst <= 0.002, f"{combos} renders ({', '.join(test_fams)} × weight × text × stroke): "
                          f"max ink loss {worst:.3%}")
    print(f"     (without padding the worst case would lose {old_box_worst[0]:.1%}: {old_box_worst[1]})")
    if tight:
        check(old_box_worst[0] > 0.005, "tight-metrics font proves the padding matters")
    # alignment: padding must not move glyphs relative to the layout box
    lay = TextLayer(text="מזל טוב", font_family="Rubik", font_size=120, width=800, align="right")
    img = render_text_layer(lay)
    f = get_font("Rubik", 120)
    ref = Image.new("RGBA", (800, 400), (0, 0, 0, 0))
    ImageDraw.Draw(ref).text((800 - f.getlength("מזל טוב"), 0), "מזל טוב", font=f, fill=(0, 0, 0, 255))
    rx0, _, rx1, _ = ref.getchannel("A").getbbox()
    ox, _ = img.info["offset"]
    x0, _, x1, _ = img.getchannel("A").getbbox()
    check((x0 + ox, x1 + ox) == (rx0, rx1), f"right alignment unchanged by padding (ink x {x0 + ox}–{x1 + ox})")

    print("4) 300 DPI magnet with a custom font")
    t = Template.new("7.5x10", "font test", slot_preset="border")
    s = t.slots[0]
    t.texts.append(TextLayer(text="שָׁלוֹם · מורן ואביב", font_family="Rubik", bold=True, font_size=78,
                             x=s.x, y=s.y + s.h + 20, width=s.w, color="#5A3E2BFF"))
    t.texts.append(TextLayer(text="18.09.2026", font_family="Varela Round", font_size=50,
                             x=s.x, y=s.y + s.h + 130, width=s.w, color="#5A3E2BFF"))
    magnet = compose_magnet(t, [Image.new("RGB", (1200, 1600), (120, 140, 170))])
    out = OUT / "fonts_magnet_7.5x10.png"
    magnet.save(out, dpi=(300, 300))
    with Image.open(out) as im:
        dpi = tuple(round(v) for v in im.info["dpi"])
        check(im.size == (886, 1181) and dpi == (300, 300), f"{out.name}: {im.size} @ {dpi} DPI")
    used = get_font("Rubik", 78, True).path
    check(Path(used).name == "Rubik-Bold.ttf", f"Pillow used {Path(used).name}")

    print("5) Variable font weight axis")
    scratch_vf = Path(os.environ.get("MAGNET_VF", "/nonexistent"))
    if scratch_vf.is_file():
        reg = alpha_sum(render_text_layer(TextLayer(text="שלום", font_path=str(scratch_vf), font_size=120)))
        bld = alpha_sum(render_text_layer(TextLayer(text="שלום", font_path=str(scratch_vf), font_size=120, bold=True)))
        check(bld > reg * 1.2, f"bold=True sets wght=700 on the variable font (+{bld / reg - 1:.0%} ink)")
    else:
        print("  – no variable font available, skipped (set MAGNET_VF=/path/to/VF.ttf)")

    print("6) Add font from disk – live refresh (into the user fonts dir, isolated per test)")
    real_dir = BUNDLED
    tmp = fonts.user_fonts_dir()
    try:
        fonts.refresh_fonts()
        donor = next((p for fam in ("FreeSerif", "DejaVu Serif", "Liberation Serif")
                      if (p := (fonts.font_index().get(fam) or {}).get("Regular"))), None)
        check(donor is not None, f"donor font for the test: {Path(donor).name if donor else None}")
        from magnetstudio.ui.designer import FontPicker, TemplateDesigner
        d = TemplateDesigner(profile="7.5x10")
        d.add_text()
        panel = d.props
        before = panel.font_picker.count()
        t0 = time.perf_counter()
        fam = panel._add_font_from_disk(donor)
        ms = (time.perf_counter() - t0) * 1000
        check(fam in fonts.custom_font_families() and (tmp / Path(donor).name).exists(),
              f"'{fam}' copied into the user fonts dir and listed as custom ({ms:.0f} ms)")
        check(not (BUNDLED / Path(donor).name).exists(), "nothing written into the (read-only) bundled folder")
        check(panel.font_picker.findData(fam) >= 0 and panel.font_picker.findText("★ " + fam) >= 0,
              f"picker refreshed without restart (★ {fam}; it moved from system → custom, {before}→"
              f"{panel.font_picker.count()} items)")
        idx = panel.font_picker.findData(fam)
        custom_end = panel.font_picker.findText("— גופני מערכת —")
        check(0 < idx < custom_end, "new font sits in the custom section (above system fonts)")
        check(d.props.item.layer.font_family == fam and panel.font_picker.currentData() == fam,
              "selected text layer switched to the new font")
        check(fam in QFontDatabase.families() or fonts.qt_family(fam) in QFontDatabase.families(),
              "registered with Qt immediately")
        n = len(list(tmp.glob("*")))
        fonts.add_font_file(donor)
        check(len(list(tmp.glob("*"))) == n, "adding the same font twice does not duplicate it")
        bad = tmp / "broken.ttf"
        bad.write_bytes(b"not a font")
        try:
            fonts.add_font_file(bad)
            check(False, "invalid font rejected")
        except ValueError as e:
            check(True, f"invalid font rejected: {e}")
        bad.unlink()
        other = FontPicker("Heebo")
        fonts.add_font_file(next(p for p in real_dir.glob("Heebo-Regular.ttf")))
        FontPicker.refresh_all()
        check(other.currentData() == "Heebo", "other open pickers keep their selection after refresh")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
        fonts.refresh_fonts()

    print("7) Default bundle downloader (as if the package shipped without fonts)")
    tmp = Path(tempfile.mkdtemp(prefix="msfonts_dl_"))
    real_download, real_instance = fonts._download, fonts._instance_static
    real_dirs, real_user = fonts.font_dirs, fonts.user_fonts_dir
    try:
        fonts.font_dirs = lambda: [tmp]
        fonts.user_fonts_dir = lambda: tmp
        src_dir = real_dir

        def fake_download(url, dst, timeout):  # serve from the bundled files instead of the network
            name = url.rsplit("/", 1)[-1]
            if name == "OFL.txt":
                lic = next(src_dir.glob("licenses/*.txt"), None)
                return bool(lic) and shutil.copy(lic, dst) is not None
            fam = name.split("%5B")[0].split("-")[0]
            files = {"VarelaRound": "VarelaRound-Regular.ttf"}
            src = src_dir / files.get(fam, f"{fam}-Regular.ttf")
            return src.exists() and shutil.copy(src, dst) is not None

        fonts._download = fake_download
        fonts._instance_static = lambda p, fam: [p.rename(p.with_name(f"{fam}-Regular.ttf"))
                                                  or p.with_name(f"{fam}-Regular.ttf")]
        new = fonts.ensure_default_fonts()
        check(len(new) == 4 and {"Heebo", "Assistant", "Rubik", "Varela Round"} <= set(fonts.custom_font_families()),
              f"empty folder → bundle installed: {sorted(new)}")
        check(fonts.ensure_default_fonts() == [], "non-empty folder → no download")
        check(len(list((tmp / "licenses").glob("*.txt"))) == 4, "OFL licenses saved next to the fonts")
        shutil.rmtree(tmp)
        tmp.mkdir()
        fonts._download = real_download
        fonts.GOOGLE_FONTS_RAW, real_url = "http://127.0.0.1:9/{dir}/{file}", fonts.GOOGLE_FONTS_RAW
        t0 = time.perf_counter()
        new = fonts.ensure_default_fonts(timeout=3)
        check(new == [] and not list(tmp.glob("*.ttf")), f"offline → skipped cleanly in {time.perf_counter() - t0:.2f}s")
        fonts.GOOGLE_FONTS_RAW = real_url
        if os.environ.get("MAGNET_ONLINE_TESTS") == "1":
            fonts._instance_static = real_instance
            shutil.rmtree(tmp)
            tmp.mkdir()
            new = fonts.ensure_default_fonts(timeout=30)
            check(len(new) >= 4, f"ONLINE: downloaded from Google Fonts: {sorted(new)}")
    finally:
        fonts._download, fonts._instance_static = real_download, real_instance
        fonts.font_dirs, fonts.user_fonts_dir = real_dirs, real_user
        fonts.refresh_fonts()
        shutil.rmtree(tmp, ignore_errors=True)

    print("\nPASS" if not failures else f"\nFAIL ({failures})")
    print(f"renders: {OUT}")
    return 1 if failures else 0


def test_fonts():
    """Scenario test – every ✔/✘ line is printed; pytest shows them when a check fails."""
    assert _run() == 0, f"{failures} check(s) failed – see the ✘ lines in the captured output"
