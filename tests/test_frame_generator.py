"""Frame generator check: Hebrew parsing, offline presets, structured-output mapping,
alpha hole punch, cloud fallback, worker threading, and designer integration.

No network: the Gemini client is mocked (same call shape as google-genai).
Run:  python tests/test_frame_generator.py
"""
import io
import os
import shutil
import sys
import time
from pathlib import Path
from types import SimpleNamespace as NS

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PIL import Image, ImageDraw  # noqa: E402

import core.frame_generator as fg  # noqa: E402
from core.frame_generator import (FrameDesign, SlotSpec, TextSpec, build_preset_template,  # noqa: E402
                                  design_to_template, generate_frame, parse_event,
                                  punch_alpha_holes, safe_margin, text_height)
from core.templates import PhotoSlot, compose_magnet, load_template, render_overlay_frame, save_template  # noqa: E402

OUT = ROOT / "output" / "tests"
failures = 0


def check(cond, msg):
    global failures
    print(("  ✔ " if cond else "  ✘ ") + msg)
    failures += not cond


def layout_ok(t) -> tuple[bool, str]:
    """Texts inside the safe margin and never overlapping a photo slot."""
    m, W, H = safe_margin(t.canvas), t.canvas.width, t.canvas.height
    for tx in t.texts:
        h = text_height(tx)
        if tx.x < m - 1 or tx.x + tx.width > W - m + 1 or tx.y < m - 1 or tx.y + h > H - m + 1:
            return False, f"'{tx.text}' outside safe area"
        for s in t.slots:
            if tx.x < s.x + s.w and s.x < tx.x + tx.width and tx.y < s.y + s.h and s.y < tx.y + h:
                return False, f"'{tx.text}' overlaps a slot"
    for s in t.slots:
        if s.x < 0 or s.y < 0 or s.x + s.w > W or s.y + s.h > H:
            return False, "slot outside canvas"
    return True, "ok"


# ---------------------------------------------------------------- mock Gemini

def _png_bytes(w=1024, h=1536):
    art = Image.new("RGB", (w, h), (120, 20, 50))
    d = ImageDraw.Draw(art)
    for i in range(0, w, 40):
        d.line([(i, 0), (w - i, h)], fill=(212, 175, 55), width=6)
    buf = io.BytesIO()
    art.save(buf, "PNG")
    return buf.getvalue()


class MockModels:
    def __init__(self, design=None, fail=False, art=True, raw_text=None):
        self.design, self.fail, self.art, self.raw_text = design, fail, art, raw_text
        self.calls = []

    def generate_content(self, model, contents, config=None):
        self.calls.append(NS(model=model, contents=contents, config=config))
        if self.fail:
            raise ConnectionError("network unreachable")
        if config is not None and config.response_modalities == ["IMAGE"]:
            parts = [NS(inline_data=NS(data=_png_bytes()))] if self.art else [NS(inline_data=None)]
            return NS(candidates=[NS(content=NS(parts=parts))])
        if self.raw_text is not None:
            return NS(parsed=None, text=self.raw_text)
        return NS(parsed=self.design, text=self.design.model_dump_json())


def mock_client(**kw):
    return NS(models=MockModels(**kw))


GOOD_DESIGN = FrameDesign(
    name="חינה מרוקאית", bg_color="#5E1428", accent_color="#D4AF37", ornament="moroccan", font_style="serif",
    slots=[SlotSpec(x=0.06, y=0.08, w=0.88, h=0.66, radius=0.04)],
    texts=[TextSpec(role="event", text="חינה", x=0.06, y=0.77, width=0.88, size=0.06, color="#D4AF37"),
           TextSpec(role="title", text="מורן ואביב", x=0.06, y=0.83, width=0.88, size=0.11, bold=True, color="#D4AF37"),
           TextSpec(role="date", text="18.09.2026", x=0.06, y=0.92, width=0.88, size=0.05, color="#D4AF37")],
    art_prompt="Moroccan zellige arabesque border, burgundy and gold",
)


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)

    print("1) Hebrew parsing (regex, offline)")
    cases = {
        "חינה למורן ואביב 18.09.2026, סגנון מרוקאי בגווני בורדו וזהב":
            ("חינה", "מורן ואביב", "18.09.2026", "moroccan", 2),
        "בר מצווה לאיתי 12 בנובמבר 2026 בצבעי כחול נייבי וכסף": ("בר מצווה", "איתי", "12.11.2026", "classic", 2),
        "יום הולדת 40 לדני - מסיבה בסגנון מינימליסטי שחור לבן": ("יום הולדת 40", "דני", "", "minimal", 2),
        "בת מצווה של שירה, ורוד עתיק וזהב, בוהו": ("בת מצווה", "שירה", "", "corners", 2),
        "ברית לבן של רון ומיכל 1.1": ("ברית", "רון ומיכל", "1.1", "classic", 0),
    }
    for text, (ev, title, date, style, ncol) in cases.items():
        i = parse_event(text)
        ok = (i.event, i.title, i.date, i.style, len(i.colors)) == (ev, title, date, style, ncol)
        check(ok, f"{text[:34]:34s} → {i.event} | {i.title} | {i.date or '-'} | {i.style} | {len(i.colors)} צבעים")

    print("2) Offline preset templates (all profiles)")
    renders = []
    for prof, n in (("7.5x10", 1), ("7.5x10", 2), ("10x10", 2), ("15x20", 1), ("5x15_strip", 3), ("5x15_strip", 4)):
        t0 = time.perf_counter()
        t = build_preset_template("חינה למורן ואביב 18.09.2026, סגנון מרוקאי בגווני בורדו וזהב", prof, n)
        ms = (time.perf_counter() - t0) * 1000
        ok, why = layout_ok(t)
        ov = render_overlay_frame(t)
        holes = all(ov.getpixel((s.x + s.w // 2, s.y + s.h // 2))[3] == 0 for s in t.slots)
        check(ok and holes and len(t.slots) == n, f"{prof:10s} × {n}: {why}, holes transparent, {ms:.0f} ms")
        renders.append(compose_magnet(t, [Image.new("RGB", (900, 1200), (128, 146, 168))]))
    check(parse_event("Corporate event").title != "", "non-Hebrew prompt still produces a title")

    print("3) Alpha Hole Punch")
    art = Image.new("RGB", (886, 1181), (200, 50, 80))
    slots = [PhotoSlot(40, 40, 380, 600, radius=30), PhotoSlot(460, 40, 380, 600)]
    p = punch_alpha_holes(art, slots)
    inside = all(p.getpixel((s.x + dx, s.y + dy))[3] == 0 for s in slots
                 for dx, dy in ((s.w // 2, s.h // 2), (s.w - 1, s.h // 2), (s.w // 2, 0)))
    check(inside, "slot interior + edges 100% transparent")
    check(p.getpixel((5, 5))[3] == 255 and p.getpixel((440, 300))[3] == 255, "art outside slots fully opaque")
    check(p.getpixel((41, 41))[3] == 255, "rounded corner keeps art (no square hole)")
    check(art.mode == "RGB", "source image untouched")

    print("4) Structured output → Template (mock Gemini)")
    client = mock_client(design=GOOD_DESIGN)
    res = generate_frame("חינה למורן ואביב 18.09.2026", "7.5x10", 1, use_ai=True, use_art=True, client=client)
    calls = client.models.calls
    cfg = calls[0].config
    check(cfg.response_mime_type == "application/json" and cfg.response_schema is FrameDesign,
          "request uses response_schema=FrameDesign, JSON mime type")
    check("מורן ואביב" in calls[0].contents and "Exactly 1 photo slot" in cfg.system_instruction,
          "prompt + slot count sent")
    check(calls[1].config.response_modalities == ["IMAGE"] and calls[1].config.image_config.aspect_ratio == "3:4",
          f"art request: IMAGE modality, aspect {calls[1].config.image_config.aspect_ratio}")
    t = res.template
    check(res.engine == "ai" and res.art, f"engine={res.engine}, art={res.art}")
    check(res.pair is not None and set(res.pair.variants) == {"portrait", "landscape"},
          "single-photo frame → portrait + landscape pair")
    check(sorted(x.text for x in t.texts) == sorted(["מורן", "אביב", "18.09.2026"]),
          f"names/date from the model, names split around the emblem: {[x.text for x in t.texts]}")
    check(all(v.credit is not None for v in res.pair.variants.values()), "credit on both variants")
    check(sum(c.config is not None and c.config.response_modalities == ["IMAGE"] for c in calls) == 2,
          "one art image per orientation")
    art_layer = [g for g in t.graphics if Path(g.path).name.startswith("art_")][0]
    a = Image.open(art_layer.path)
    s = t.slots[0]
    check(art_layer.z >= 0 and a.getpixel((s.x + s.w // 2, s.y + s.h // 2))[3] == 0,
          f"art above photo (z={art_layer.z}) with slot punched")
    final = compose_magnet(t, [Image.new("RGB", (900, 1200), (10, 200, 10))])
    px = final.getpixel((s.x + s.w // 2, s.y + s.h // 2))
    check(px == (10, 200, 10), f"photo shows clean through the frame {px}")
    ok, why = layout_ok(t)
    check(ok, f"AI layout valid: {why}")
    final.save(OUT / "ai_mock_7.5x10.png", dpi=(300, 300))
    renders.insert(0, final)

    print("5) Clamping a bad model response")
    bad = FrameDesign(
        name="", bg_color="burgundy", accent_color="#zzzzzz", ornament="classic",
        slots=[SlotSpec(x=-0.2, y=0.0, w=1.5, h=1.2), SlotSpec(x=0.5, y=0.5, w=0.01, h=0.01)],
        texts=[TextSpec(role="title", text="מזל טוב", x=0.4, y=0.4, width=0.1, size=0.9, color="#FFFFFF"),
               TextSpec(role="date", text="  ", x=0, y=0, width=1, size=0.05, color="#000000")],
        art_prompt="")
    t = design_to_template(bad, "10x10", 1)
    ok, why = layout_ok(t)
    check(ok and len(t.slots) == 1 and len(t.texts) == 1, f"repaired: {why}, 1 slot, empty text dropped")
    check(t.canvas.bg_color.startswith("#") and len(t.canvas.bg_color) == 9, f"invalid colors replaced ({t.canvas.bg_color})")
    raw = mock_client(raw_text=GOOD_DESIGN.model_dump_json())
    r2 = generate_frame("חינה", "7.5x10", 1, use_art=False, client=raw)
    check(r2.engine == "ai", "falls back to JSON text when .parsed is empty")
    junk = mock_client(raw_text="not json")
    r3 = generate_frame("חינה למורן ואביב 18.09.2026", "7.5x10", 1, use_art=False, client=junk)
    check(r3.engine == "offline" and r3.notes, "unparseable JSON → offline generator")

    print("6) Cloud failure → offline fallback")
    r = generate_frame("חינה למורן ואביב 18.09.2026, בורדו וזהב", "5x15_strip", 3,
                       client=mock_client(design=GOOD_DESIGN, fail=True))
    check(r.engine == "offline" and not r.art and len(r.template.slots) == 3, f"network error → {r.engine}, notes: {r.notes[0][:40]}")
    r = generate_frame("חינה למורן ואביב", "7.5x10", None, use_ai=True, api_key="")
    check(r.engine == "offline", "no API key → offline (no network attempted)")
    r = generate_frame("חינה", "7.5x10", 1, client=mock_client(design=GOOD_DESIGN, art=False))
    check(r.engine == "ai" and not r.art, "art model returns no image → vector frame kept")

    print("7) JSON round-trip of a generated template")
    tdir = OUT / "gen_tpl"
    shutil.rmtree(tdir, ignore_errors=True)
    path = save_template(res.template, tdir / "henna.json")
    t2 = load_template(path)
    same = render_overlay_frame(t2).tobytes() == render_overlay_frame(res.template).tobytes()
    check(same and (tdir / "henna_assets").is_dir(), "saved + reloaded renders identically, assets copied")

    print("8) FrameGeneratorWorker (QThread)")
    from PyQt6.QtCore import QEventLoop, QTimer
    from PyQt6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication(sys.argv)  # noqa: F841
    for label, client in (("mock Gemini", mock_client(design=GOOD_DESIGN)),
                          ("failing cloud", mock_client(design=GOOD_DESIGN, fail=True))):
        got, prog, errs, ticks = [], [], [], [0]
        w = fg.FrameGeneratorWorker("חינה למורן ואביב 18.09.2026", "7.5x10", 1, client=client)
        w.progress.connect(lambda p, s: prog.append(p))
        w.finished.connect(got.append)
        w.failed.connect(errs.append)
        loop = QEventLoop()
        w.finished.connect(lambda _: loop.quit())
        w.failed.connect(lambda _: loop.quit())
        tm = QTimer(interval=5, timeout=lambda: ticks.__setitem__(0, ticks[0] + 1))
        tm.start()
        QTimer.singleShot(30_000, loop.quit)
        t0 = time.perf_counter()
        w.start()
        start_ms = (time.perf_counter() - t0) * 1000
        loop.exec()
        tm.stop()
        w.wait()
        check(len(got) == 1 and not errs and prog[-1] == 100 and prog == sorted(prog),
              f"{label}: finished(Template), progress {prog[0]}→{prog[-1]}, engine={w.result.engine}")
        check(start_ms < 50 and ticks[0] > 0, f"{label}: non-blocking (start {start_ms:.1f} ms, {ticks[0]} GUI ticks)")
    w = fg.FrameGeneratorWorker("   ", "7.5x10")
    errs = []
    w.failed.connect(errs.append)
    w.start()
    w.wait()
    app.processEvents()
    check(errs == ["נא לתאר את האירוע"], "empty prompt → failed(str)")

    print("9) Designer integration")
    from ui.designer import TemplateDesigner
    from ui.frame_generator_dialog import FrameGeneratorDialog
    d = TemplateDesigner(profile="7.5x10")
    check(d.ai_btn.text() == "✨ מחולל AI", "toolbar button present")
    dlg = FrameGeneratorDialog("5x15_strip", {}, d)
    dlg.template_ready.connect(d.apply_generated)
    check(not dlg.use_ai.isEnabled(), "no key → cloud options disabled, offline label shown")
    dlg.prompt.setPlainText("חתונת נועה ואורי 03.06.2027, אלגנטי בגווני לבן וזהב")
    loop = QEventLoop()
    dlg.generate()
    dlg.worker.finished.connect(lambda _: QTimer.singleShot(0, loop.quit))
    QTimer.singleShot(30_000, loop.quit)
    loop.exec()
    dlg.worker.wait()
    check(dlg.apply_btn.isEnabled() and dlg.preview.pixmap() is not None, "dialog shows preview, apply enabled")
    dlg.apply()
    check(d.template.canvas.profile == "5x15_strip" and len(d.template.slots) == 3 and d._dirty,
          f"canvas replaced: {d.template.name} ({d.template.canvas.profile}, {len(d.template.slots)} slots)")
    check(d.profile_box.currentData() == "5x15_strip", "designer size selector follows")

    # contact sheet for a visual check
    H = 800
    row = [im.resize((round(im.width * H / im.height), H)) for im in renders[:5]]
    sheet = Image.new("RGB", (sum(r.width for r in row) + 20 * (len(row) + 1), H + 40), "#444")
    x = 20
    for r_ in row:
        sheet.paste(r_, (x, 20))
        x += r_.width + 20
    sheet.save(OUT / "frame_generator_sheet.png")

    print("\nPASS" if not failures else f"\nFAIL ({failures})")
    print(f"renders: {OUT}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
