"""Dark UI check: theme, top-bar status widgets, queue cards and the print flow (Dry Run).

Run:  pytest tests/test_ui.py
"""
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

from PIL import Image  # noqa: E402
from PyQt6.QtCore import QEventLoop, Qt, QTimer  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

failures = 0


def check(cond, msg):
    global failures
    print(("  ✔ " if cond else "  ✘ ") + msg)
    failures += not cond


def wait_until(cond, timeout=20.0):
    end = time.time() + timeout
    while time.time() < end and not cond():
        loop = QEventLoop()
        QTimer.singleShot(30, loop.quit)
        loop.exec()
    return cond()


def _run() -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    from magnetstudio import app as app_main
    app_main._setup_fonts(app)
    from magnetstudio.ui import theme
    theme.apply_theme(app)

    print("1) Theme (AI Studio design tokens)")
    from magnetstudio.ui.theme import ThemeColors
    qss = app.styleSheet()
    for token in (ThemeColors.BG_ROOT, ThemeColors.BG_CARD, ThemeColors.BORDER_SUBTLE, ThemeColors.ACCENT_CYAN):
        check(token in qss, f"QSS uses {token}")
    check("-apple-system" not in qss, "no unsupported CSS font stack in QSS")
    check(app.font().families()[0] in ("Heebo", "Assistant"), f"UI font: {app.font().families()[0]}")
    check(app.layoutDirection() == Qt.LayoutDirection.RightToLeft, "app is right-to-left (Hebrew)")
    check(app.style().metaObject().className() == "QStyleSheetStyle", "stylesheet active on top of Fusion")

    from magnetstudio.services.printer import DRY_RUN_PRINTER
    from magnetstudio.core.settings import load_settings
    from magnetstudio.ui.components.queue_panel import QueueCardWidget, QueueItemStatus
    from magnetstudio.ui.main_window import MainWindow

    tmp = Path(tempfile.mkdtemp(prefix="msui_"))
    photos = []
    for i, c in enumerate([(200, 120, 90), (90, 140, 200)]):
        p = tmp / f"IMG_{i}.jpg"
        Image.new("RGB", (1600, 1200), c).save(p)
        photos.append(str(p))
    settings = load_settings()
    settings.update(output_folder=str(tmp / "out"), watch_folder=str(tmp / "hot"), print_count_total=100,
                    frame=None, enhance=False)
    win = MainWindow(settings)
    win.show()
    win.printer_box.setCurrentText(DRY_RUN_PRINTER)
    qp = win.queue_panel

    print("2) Queue panel chips")
    win._update_printer_chip()
    check(ThemeColors.ACCENT_AMBER in qp.printer_dot.styleSheet() and "בדיקה" in qp.printer_value.text(),
          f"printer chip: test state ({qp.printer_value.text()})")
    check(qp.count_lbl.text() == "100", "counter seeded with stored total")
    check(not qp.timer.isActive(), "pulse idle while Hot Folder is off")
    (tmp / "hot").mkdir()
    qp.hot_folder_toggle_requested.emit()          # same as clicking the chip
    check(win.auto_print.isChecked() and qp.timer.isActive() and "מאזין" in qp.folder_value.text(),
          f"clicking the Hot Folder chip starts watching + pulse ({qp.folder_value.text()})")
    qp.hot_folder_toggle_requested.emit()
    check(not win.auto_print.isChecked() and not qp.timer.isActive(), "second click stops it")

    print("3) Queue cards")
    item = win.add_photo(photos[0], "manual")
    card: QueueCardWidget = qp.cards[item.id]
    app.processEvents()
    check(card.height() == 88, f"card height {card.height()}px")
    check(card.status == QueueItemStatus.INCOMING and "התקבלה" in card.badge_lbl.text(), "badge: התקבלה")
    check("+1" in card.btn_copy.text() and card.btn_copy.text().endswith("עותק"), "'+1 עותק' button")
    check(card.thumb_label.pixmap() is not None and not card.thumb_label.pixmap().isNull(), "thumbnail loaded")
    check(win.photo_path == photos[0], "new photo shown in preview")

    print("4) Print flow (Dry Run)")
    seen = []
    orig = card.update_status
    card.update_status = lambda st: (seen.append(st.name), orig(st))[1]
    card.btn_reprint.click()
    ok = wait_until(lambda: item.status == "done")
    check(ok and item.copies_printed == 1 and card.status == QueueItemStatus.PRINTED,
          f"quick print → {card.status.name}, ×{item.copies_printed}")
    check("COMPOSED" in seen and "SPOOLING" in seen, f"badge passed through {seen}")
    card.btn_copy.click()
    card.btn_copy.click()
    ok = wait_until(lambda: item.status == "done" and item.copies_printed == 3)
    check(ok, f"'+1 עותק' twice → ×{item.copies_printed} printed")
    check("3" in card.time_lbl.text(), f"card meta: {card.time_lbl.text()}")
    check(qp.count_lbl.text() == "103" and win.settings["print_count_total"] == 103,
          f"counter {qp.count_lbl.text()}, persisted total {win.settings['print_count_total']}")
    win.copies_box.setValue(3)
    card.btn_reprint.click()
    wait_until(lambda: item.copies_printed == 6)
    check(qp.count_lbl.text() == "106", "counter counts magnets, not jobs (3 copies → +3)")
    win.copies_box.setValue(1)

    win.settings["enhance"] = True
    seen.clear()
    card.btn_copy.click()
    wait_until(lambda: item.copies_printed == 7)
    check("ENHANCED" in seen and seen.index("ENHANCED") < seen.index("SPOOLING"),
          f"enhancer on → ENHANCED before spooling {seen}")
    win.settings["enhance"] = False

    bad = tmp / "broken.jpg"
    bad.write_bytes(b"nope")
    bad_item = win.add_photo(str(bad), "drop", select=False)
    check(qp.cards[bad_item.id].thumb_label.text() == "IMG", "broken file → IMG placeholder thumbnail")
    win._print_item(bad_item.id)
    wait_until(lambda: bad_item.status == "failed")
    check(qp.cards[bad_item.id].status == QueueItemStatus.FAILED, f"broken file → FAILED ({bad_item.error})")

    print("5) Hot Folder end-to-end")
    win.auto_print.setChecked(True)
    before = len(win.items)
    Image.open(photos[1]).save(tmp / "hot" / "IMG_hot.jpg")
    ok = wait_until(lambda: len(win.items) == before + 1 and list(win.items.values())[-1].status == "done", 30)
    hot = list(win.items.values())[-1]
    check(ok and hot.source == "hot", f"new file → card ({hot.source}) → {hot.status}")
    win.auto_print.setChecked(False)
    win._printer_timer.stop()
    win.hide()

    print("\nPASS" if not failures else f"\nFAIL ({failures})")
    return 1 if failures else 0


def test_ui():
    """Scenario test – every ✔/✘ line is printed; pytest shows them when a check fails."""
    assert _run() == 0, f"{failures} check(s) failed – see the ✘ lines in the captured output"
