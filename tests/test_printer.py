"""Quick printer check: detection + non-blocking spool test (dry run to PDF).

Run:  pytest tests/test_printer.py
Works without a physical printer (uses the PDF dry-run target).
"""
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

from PIL import Image, ImageDraw  # noqa: E402
from PyQt6.QtCore import QEventLoop, QTimer  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

from magnetstudio.services.printer import (DRY_RUN_PRINTER, PrintJob, PrintMode, PrintWorker,  # noqa: E402
                          get_available_printers, is_printer_available)
from magnetstudio.core.sizes import MAGNET_SIZES  # noqa: E402

OUT = ROOT / "output" / "tests"


def sample_images(n=6, key="7.5x10"):
    imgs = []
    for i in range(n):
        im = Image.new("RGB", MAGNET_SIZES[key].size_px, (40 * i % 255, 120, 200 - 25 * i))
        ImageDraw.Draw(im).text((40, 40), f"#{i + 1}", fill="white", font_size=150)
        imgs.append(im)
    return imgs


def run_worker(job: PrintJob, timeout_s=60):
    """Run a PrintWorker and count GUI-thread ticks while it works."""
    result, ticks, progress = {}, [0], []
    worker = PrintWorker(job)
    worker.succeeded.connect(lambda m: result.update(ok=m))
    worker.failed.connect(lambda m: result.update(err=m))
    worker.progress.connect(lambda d, t: progress.append((d, t)))

    loop = QEventLoop()
    worker.finished.connect(loop.quit)
    tick = QTimer(interval=10, timeout=lambda: ticks.__setitem__(0, ticks[0] + 1))
    tick.start()
    QTimer.singleShot(timeout_s * 1000, loop.quit)

    t0 = time.perf_counter()
    worker.start()
    returned_in = time.perf_counter() - t0  # start() must return immediately
    loop.exec()
    tick.stop()
    worker.wait()
    return result, ticks[0], progress, returned_in, time.perf_counter() - t0


def page_count(pdf: Path) -> int:
    return pdf.read_bytes().count(b"/Type /Page\n") or pdf.read_bytes().count(b"/Type /Page")


def _run() -> int:
    app = QApplication(sys.argv)  # noqa: F841
    failures = 0

    def check(cond, msg):
        nonlocal failures
        print(("  ✔ " if cond else "  ✘ ") + msg)
        failures += not cond

    print("1) Printer detection")
    printers = get_available_printers()
    print(f"   found: {printers}")
    check(isinstance(printers, list) and printers[-1] == DRY_RUN_PRINTER, "list ends with dry-run target")
    check(is_printer_available(DRY_RUN_PRINTER), "dry-run target always available")
    check(not is_printer_available("__no_such_printer__"), "unknown printer reported unavailable")

    for mode, n, expect_pages in ((PrintMode.A4, 6, 1), (PrintMode.A4, 7, 2), (PrintMode.THERMAL, 3, 3)):
        print(f"2) Spool test – {mode.value}, {n} magnets")
        job = PrintJob(mode=mode, printer_name=DRY_RUN_PRINTER, images=sample_images(n), out_dir=OUT)
        res, ticks, prog, start_s, total_s = run_worker(job)
        check("ok" in res, f"job succeeded ({res})")
        check(start_s < 0.05, f"worker.start() returned in {start_s * 1000:.1f} ms (non-blocking)")
        check(ticks > 0, f"GUI event loop kept ticking during job ({ticks} ticks in {total_s:.2f}s)")
        check(prog and prog[-1][0] == prog[-1][1] == expect_pages, f"progress reached {prog[-1] if prog else None}")
        if "ok" in res:
            pdf = Path(res["ok"].split(": ", 1)[1])
            check(pdf.exists() and page_count(pdf) == expect_pages, f"{pdf.name}: {page_count(pdf)} page(s)")

    print("3) Unavailable printer → graceful error")
    res, *_ = run_worker(PrintJob(mode=PrintMode.A4, printer_name="__no_such_printer__",
                                  images=sample_images(1)))
    check("err" in res and "ok" not in res, f"failed signal: {res.get('err')}")

    print("\nPASS" if not failures else f"\nFAIL ({failures})")
    return 1 if failures else 0


def test_printer():
    """Scenario test – every ✔/✘ line is printed; pytest shows them when a check fails."""
    assert _run() == 0, "check(s) failed – see the ✘ lines in the captured output"
