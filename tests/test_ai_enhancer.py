"""Enhancer check: LUT correctness, speed benchmark, memory leak check, cloud fallback, worker.

Run:  pytest tests/test_ai_enhancer.py
"""
import gc
import os
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

import numpy as np  # noqa: E402  (test-only: builds realistic photo-like pixels fast)
from PIL import Image  # noqa: E402

import magnetstudio.core.ai_enhancer as ae  # noqa: E402
from magnetstudio.core.ai_enhancer import PRESETS, build_lut, enhance, enhance_local  # noqa: E402

BUDGET_MS = 150
failures = 0


def check(cond, msg):
    global failures
    print(("  ✔ " if cond else "  ✘ ") + msg)
    failures += not cond


def photo_like(w, h, seed=0) -> Image.Image:
    """Smooth gradients + noise, so JPEG-ish content rather than flat colour."""
    rng = np.random.default_rng(seed)
    y, x = np.mgrid[0:h, 0:w].astype(np.float32)
    base = np.stack([128 + 100 * np.sin(x / w * 6), 90 + 80 * np.cos(y / h * 5),
                     70 + 60 * np.sin((x + y) / (w + h) * 9)], -1)
    base += rng.normal(0, 12, base.shape)
    return Image.fromarray(np.clip(base, 0, 255).astype(np.uint8), "RGB")


def rss_mb() -> float:
    try:
        import psutil
        return psutil.Process().memory_info().rss / 2**20
    except ImportError:
        pass
    try:
        with open("/proc/self/statm") as f:
            return int(f.read().split()[1]) * os.sysconf("SC_PAGE_SIZE") / 2**20
    except OSError:
        import resource
        return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024


def bench(img, runs=9) -> float:
    enhance_local(img)  # warm-up (LUT cache)
    ts = []
    for _ in range(runs):
        t = time.perf_counter()
        enhance_local(img)
        ts.append((time.perf_counter() - t) * 1000)
    return statistics.median(ts)


def _run() -> int:
    print("1) LUT correctness")
    for name, p in PRESETS.items():
        curve = build_lut(p)[:256]
        check(all(a <= b for a, b in zip(curve, curve[1:])) and curve[0] == p.black_out
              and curve[-1] == p.white_out, f"{name}: monotonic curve {curve[0]}→{curve[-1]}")
    dark = Image.new("RGB", (64, 64), (40, 40, 40))
    check(enhance_local(dark).getpixel((0, 0))[0] > 50, f"shadows lifted: 40 → {enhance_local(dark).getpixel((0, 0))[0]}")
    grey = enhance_local(Image.new("RGB", (8, 8), (128, 128, 128))).getpixel((0, 0))
    check(max(grey) - min(grey) <= 1, f"neutral grey stays neutral {grey}")
    col = Image.new("RGB", (8, 8), (180, 120, 90))
    r, g, b = enhance_local(col, "vivid").getpixel((0, 0))
    check((r - b) > (180 - 90), f"saturation boosted (R-B {180 - 90} → {r - b})")
    src = photo_like(400, 300)
    before = src.tobytes()
    out = enhance_local(src)
    check(src.tobytes() == before, "input image left untouched")
    check(out.mode == "RGB" and out.size == src.size and out.info.get("dpi") == (300, 300),
          "output RGB, same size, dpi=(300, 300)")
    rgba = enhance_local(Image.new("RGBA", (10, 10), (10, 20, 30, 128)))
    check(rgba.mode == "RGB", "RGBA input handled")

    print(f"2) Benchmark (budget {BUDGET_MS} ms, {os.cpu_count()} CPU cores)")
    for label, (w, h) in {"15x20 magnet @300DPI": (1772, 2362),
                          "A4 sheet @300DPI": (2480, 3508),
                          "24MP camera original": (6000, 4000)}.items():
        ms = bench(photo_like(w, h))
        check(ms < BUDGET_MS, f"{label:22s} {w}x{h} ({w * h / 1e6:.1f} MP): {ms:.0f} ms")

    print("3) Memory leak check (300 runs @ 15x20)")
    img = photo_like(1772, 2362, seed=1)
    for _ in range(20):
        enhance_local(img)
    gc.collect()
    start = rss_mb()
    for i in range(300):
        out = enhance_local(img, list(PRESETS)[i % len(PRESETS)])
    del out
    gc.collect()
    growth = rss_mb() - start
    check(growth < 25, f"RSS growth {growth:+.1f} MB (start {start:.0f} MB)")

    print("4) Cloud fallback (no network calls leave the machine)")
    small = photo_like(300, 400)
    res, engine = enhance(small, "dye_sub", cloud_style="print_ready", api_key="")
    check(engine == "local-fallback" and res.size == small.size, f"no API key → {engine}")
    ae.GEMINI_URL = "http://127.0.0.1:9/{model}"  # closed port = "no internet"
    t = time.perf_counter()
    res, engine = enhance(small, "dye_sub", cloud_style="print_ready", api_key="dummy")
    check(engine == "local-fallback", f"offline → {engine} in {(time.perf_counter() - t) * 1000:.0f} ms")
    check(res.info.get("dpi") == (300, 300), "fallback output keeps 300 DPI")

    print("5) EnhancementWorker (off the GUI thread)")
    from PyQt6.QtCore import QEventLoop, QTimer
    from PyQt6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication(sys.argv)  # noqa: F841
    got, fallbacks, ticks = [], [], [0]
    w = ae.EnhancementWorker([photo_like(1772, 2362, s) for s in range(3)], "dye_sub",
                             cloud_style="print_ready", api_key="dummy")
    w.enhanced.connect(lambda i, im, eng: got.append((i, im.size, eng)))
    w.fallback.connect(fallbacks.append)
    loop = QEventLoop()
    w.finished.connect(loop.quit)
    timer = QTimer(interval=5, timeout=lambda: ticks.__setitem__(0, ticks[0] + 1))
    timer.start()
    QTimer.singleShot(30_000, loop.quit)
    w.start()
    loop.exec()
    timer.stop()
    w.wait()
    check(len(got) == 3 and all(e == "local" for _, _, e in got), f"3 images enhanced locally {[g[0] for g in got]}")
    check(len(fallbacks) == 1, f"cloud failure reported once, then stayed local ({fallbacks[:1]})")
    check(ticks[0] > 0, f"GUI loop kept running ({ticks[0]} ticks)")

    print("6) Pipeline: crop → enhance → frame keeps 300 DPI")
    from magnetstudio.core.framer import make_enhance_filter, render_magnet
    out_dir = ROOT / "output" / "tests"
    out_dir.mkdir(parents=True, exist_ok=True)
    photo = out_dir / "enh_src.jpg"
    photo_like(3000, 2000).save(photo, quality=90)
    flt = make_enhance_filter({"enhance": True, "enhance_preset": "dye_sub"})
    before_img = render_magnet(photo, "7.5x10")
    after_img = render_magnet(photo, "7.5x10", photo_filter=flt)
    after_img.save(out_dir / "enh_after.jpg", dpi=(300, 300), quality=95)
    with Image.open(out_dir / "enh_after.jpg") as im:
        dpi = tuple(round(v) for v in im.info["dpi"])
    check(after_img.size == before_img.size and sorted(after_img.size) == [886, 1181] and dpi == (300, 300),
          f"magnet {after_img.size} @ {dpi} DPI")
    check(make_enhance_filter({"enhance": False}) is None, "toggle off → no filter")

    print("\nPASS" if not failures else f"\nFAIL ({failures})")
    return 1 if failures else 0


def test_ai_enhancer():
    """Scenario test – every ✔/✘ line is printed; pytest shows them when a check fails."""
    assert _run() == 0, f"{failures} check(s) failed – see the ✘ lines in the captured output"
