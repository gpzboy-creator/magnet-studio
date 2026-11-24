"""Double-tap confirmation guard for keyboard reprints (Space) in the print queue.

Run:  python tests/test_queue_guard.py
"""
import os
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
# never touch the real settings / log while testing (MainWindow saves after every print)
import tempfile as _tf  # noqa: E402
_TEST_HOME = _tf.mkdtemp(prefix="ms_test_")
os.environ.setdefault("MAGNETSTUDIO_SETTINGS", os.path.join(_TEST_HOME, "settings.json"))
os.environ.setdefault("MAGNETSTUDIO_LOG_DIR", os.path.join(_TEST_HOME, "logs"))

from PIL import Image  # noqa: E402
from PyQt6.QtCore import QEventLoop, Qt, QTimer  # noqa: E402
from PyQt6.QtTest import QTest  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

failures = 0


def check(cond, msg):
    global failures
    print(("  ✔ " if cond else "  ✘ ") + msg)
    failures += not cond


def wait(ms: int) -> None:
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


def wait_until(cond, timeout=20.0) -> bool:
    end = time.time() + timeout
    while time.time() < end and not cond():
        wait(30)
    return cond()


def main() -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    import main as app_main
    app_main._setup_fonts(app)
    from ui.theme import apply_theme
    apply_theme(app)

    from core.printer import DRY_RUN_PRINTER
    from core.settings import load_settings
    from ui.components.queue_panel import REPRINT_CONFIRM_MS, QueueItemStatus, ReprintGuard
    from ui.main_window import MainWindow

    print("1) ReprintGuard (unit)")
    g = ReprintGuard(window_ms=300)
    check(g.press("a") is False and g.is_armed("a"), "first press arms, does not confirm")
    check(g.press("a") is True and not g.is_armed(), "second press on the same job confirms")
    g.press("a")
    check(g.press("b") is False and g.is_armed("b"), "press on another job re-arms for that job")
    g.cancel()
    g.press("a")
    wait(400)
    check(not g.is_armed() and g.press("a") is False, "after the window expires, a press only arms again")
    g.cancel()
    check(REPRINT_CONFIRM_MS == 1500, "window is 1.5 s")

    tmp = Path(tempfile.mkdtemp(prefix="msguard_"))
    photos = []
    for i, c in enumerate([(200, 120, 90), (90, 140, 200), (120, 190, 110)]):
        p = tmp / f"IMG_{i}.jpg"
        Image.new("RGB", (1600, 1200), c).save(p)
        photos.append(str(p))
    st = load_settings()
    st.update(output_folder=str(tmp / "out"), print_count_total=0, frame=None, enhance=False)
    win = MainWindow(st)
    win.show()
    win.printer_box.setCurrentText(DRY_RUN_PRINTER)
    qp = win.queue_panel

    items = [win.add_photo(p, "manual") for p in photos]   # newest on top: IMG_2, IMG_1, IMG_0
    first = items[1]                                        # IMG_1 – middle card (has a card below it)
    win._print_item(first.id)
    check(wait_until(lambda: first.status == "done"), "setup: IMG_1 printed → PRINTED")
    card = qp.cards[first.id]
    check(card.status == QueueItemStatus.PRINTED, "card badge PRINTED")

    sent = []
    real_submit = win.submit_job
    win.submit_job = lambda job: sent.append(job.tag)      # spy: record, don't print

    def space():
        QTest.keyClick(win, Qt.Key.Key_Space)

    print("2) Single Space on a printed photo → nothing is sent")
    qp.select(first.id)
    space()
    check(sent == [], "no print command after one Space")
    check(qp.guard.is_armed(first.id) and card.reprint_armed, "card in 'waiting for confirmation' state")
    check("כבר הודפס" in card.badge_lbl.text() and "לחץ שוב [רווח] להדפסה חוזרת" == card.title_lbl.text(),
          f"warning on the card: '{card.badge_lbl.text().strip()}' / '{card.title_lbl.text()}'")
    fm = card.title_lbl.fontMetrics()
    check(fm.horizontalAdvance(card.title_lbl.text()) <= card.title_lbl.width() + 2,
          f"hint fits on the card ({fm.horizontalAdvance(card.title_lbl.text())} ≤ {card.title_lbl.width()} px)")
    check("כבר הודפס! לחץ שוב [רווח] להדפסה חוזרת" in win.statusBar().currentMessage(),
          "warning in the status bar")
    blink_states = set()
    for _ in range(4):
        blink_states.add(card.styleSheet())
        wait(230)
    check(card._blink.isActive() and len(blink_states) == 2 and any("#FFB703" in s for s in blink_states),
          "amber border is blinking")
    vp = qp.scroll_area.viewport().width()
    check(all(c.width() <= vp for c in qp.cards.values()) and card.btn_reprint.geometry().left() >= 0,
          f"warning text doesn't push the cards wider than the panel ({max(c.width() for c in qp.cards.values())} ≤ {vp})")
    wait(REPRINT_CONFIRM_MS - 800)
    check(not qp.guard.is_armed() and not card.reprint_armed and card.status == QueueItemStatus.PRINTED
          and "הודפסה" in card.badge_lbl.text() and card.styleSheet() == ""
          and card.title_lbl.text() == Path(first.path).name,
          "after 1.5 s the card is back to normal PRINTED")
    check(sent == [], "still nothing sent")

    print("3) Double Space within 1.5 s → reprint sent, SPOOLING, auto-advance")
    qp.select(first.id)
    space()
    wait(250)
    space()
    check(sent == [first.id], f"exactly one print command ({len(sent)})")
    check(card.status == QueueItemStatus.SPOOLING, f"badge → {card.status.name}")
    check(qp.selected_id == items[0].id, "selection moved to the next card (auto-advance)")
    qp.select(items[0].id)
    space()
    space()
    check(qp.selected_id == items[0].id, "at the end of the queue the selection stays on the last card")
    sent.clear()
    card.update_status(QueueItemStatus.PRINTED)          # reset for the next checks
    sent.clear()

    print("4) Arrow keys / Esc cancel the pending reprint")
    for key, name in ((Qt.Key.Key_Down, "↓"), (Qt.Key.Key_Up, "↑"), (Qt.Key.Key_Escape, "Esc")):
        qp.select(first.id)
        space()
        armed = qp.guard.is_armed(first.id)
        QTest.keyClick(win, key)
        cancelled = not qp.guard.is_armed() and not card.reprint_armed
        space() if key == Qt.Key.Key_Escape else None   # after Esc, Space must only re-arm
        check(armed and cancelled and sent == [], f"{name}: confirmation cancelled, nothing printed")
        qp.guard.cancel()
    qp.select(first.id)
    QTest.keyClick(win, Qt.Key.Key_Escape)
    check(qp.selected_id == first.id, "Esc keeps the selection")
    space()
    QTest.keyClick(win, Qt.Key.Key_Down)
    check(qp.selected_id != first.id, "↓ cancels and moves to the next card")
    qp.guard.cancel()

    print("5) Reprint button (mouse / touch) → immediate, no confirmation")
    qp.select(first.id)
    card.btn_reprint.click()
    check(sent == [first.id] and not qp.guard.is_armed(), "button prints at once")
    sent.clear()
    qp.select(first.id)
    space()
    card.btn_reprint.click()
    check(sent == [first.id] and not qp.guard.is_armed() and not card.reprint_armed,
          "button while armed: prints once and clears the warning")
    sent.clear()

    print("6) Unprinted photo → single Space prints at once and advances")
    fresh = items[2]                                        # IMG_2 – top card, never printed
    qp.select(fresh.id)
    space()
    check(sent == [fresh.id] and not qp.guard.is_armed(), "one Space is enough for a new photo")
    check(qp.selected_id == first.id, "advanced to the next card (down the list)")
    sent.clear()

    print("7) Space can't sneak past the guard")
    qp.select(first.id)
    win.print_btn.setFocus()
    space()
    check(sent == [] and qp.guard.is_armed(first.id), "focused 'הדפס' button: Space goes to the guard, not the button")
    qp.guard.cancel()
    check(all(b.focusPolicy() == Qt.FocusPolicy.NoFocus for b in (card.btn_reprint, card.btn_copy, card.btn_inspect)),
          "card buttons never take keyboard focus")
    qp.select(first.id)
    ev_press = __import__("PyQt6.QtGui", fromlist=["QKeyEvent"]).QKeyEvent
    from PyQt6.QtCore import QEvent
    app.sendEvent(win, ev_press(QEvent.Type.KeyPress, Qt.Key.Key_Space, Qt.KeyboardModifier.NoModifier, " ", False, 1))
    app.sendEvent(win, ev_press(QEvent.Type.KeyPress, Qt.Key.Key_Space, Qt.KeyboardModifier.NoModifier, " ", True, 1))
    check(sent == [] and qp.guard.is_armed(first.id), "holding Space down (auto-repeat) is not a double tap")
    qp.guard.cancel()
    win.copies_box.setFocus()
    qp.select(first.id)
    space()
    check(sent == [] and not qp.guard.is_armed(), "while typing in a number field, Space is left alone")

    print("8) End-to-end: confirmed reprint really prints")
    win.submit_job = real_submit
    win.setFocus()
    qp.select(first.id)
    before = first.copies_printed
    space()
    wait(200)
    space()
    check(wait_until(lambda: first.copies_printed == before + 1 and first.status == "done"),
          f"printed again (×{first.copies_printed}), badge {qp.cards[first.id].status.name}")

    new = win.add_photo(photos[0], "manual")
    qp.select(new.id)
    space()                      # prints and auto-advances to the next card
    QTest.keyClick(win, Qt.Key.Key_Up)
    check(qp.selected_id == new.id, "↑ goes back to the photo that is being printed")
    space()                      # impatient second tap while it is still queued / printing
    check(wait_until(lambda: new.status == "done") and wait_until(lambda: False, 1.5) is False
          and new.copies_printed == 1, f"Space on a photo already in the print queue is ignored (×{new.copies_printed})")

    win._printer_timer.stop()
    app.removeEventFilter(win)
    win.hide()  # not close(): closeEvent would save these test settings to config/settings.json
    print("\nPASS" if not failures else f"\nFAIL ({failures})")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
