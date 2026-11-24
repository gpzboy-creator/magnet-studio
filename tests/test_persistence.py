"""Step 1 + 2: immediate (atomic) settings save after every print, and the application log.

Run:  pytest tests/test_persistence.py
"""
import json
import logging
import os
import subprocess
import sys
import tempfile
import textwrap
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HOME = Path(tempfile.mkdtemp(prefix="ms_persist_"))

from PIL import Image  # noqa: E402
from PyQt6.QtCore import QEventLoop, QTimer  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

from magnetstudio.core import applog  # noqa: E402
from magnetstudio.core.settings import DEFAULTS, load_settings, save_settings, settings_path  # noqa: E402

failures = 0


def check(cond, msg):
    global failures
    print(("  ✔ " if cond else "  ✘ ") + msg)
    failures += not cond


def wait_until(cond, timeout=20.0) -> bool:
    end = time.time() + timeout
    while time.time() < end and not cond():
        loop = QEventLoop()
        QTimer.singleShot(30, loop.quit)
        loop.exec()
    return cond()


def log_text() -> str:
    for h in logging.getLogger().handlers:
        h.flush()
    return applog.log_file().read_text(encoding="utf-8") if applog.log_file().exists() else ""


def run_child(code: str, timeout=60) -> subprocess.CompletedProcess:
    env = dict(os.environ, PYTHONPATH=str(ROOT), MAGNETSTUDIO_LOG_DIR=str(HOME / "child_logs"),
               MAGNETSTUDIO_SETTINGS=str(HOME / "child_settings.json"))
    return subprocess.run([sys.executable, "-c", textwrap.dedent(code)], cwd=ROOT, env=env,
                          capture_output=True, text=True, timeout=timeout)


def _run() -> int:
    os.environ["MAGNETSTUDIO_SETTINGS"] = str(HOME / "settings.json")  # restored by conftest
    os.environ["MAGNETSTUDIO_LOG_DIR"] = str(HOME / "logs")
    log_path = applog.setup_logging(directory=HOME / "logs", console=False)
    check(log_path == HOME / "logs" / "magnetstudio.log", f"log file: {log_path}")
    check(settings_path() == HOME / "settings.json", "MAGNETSTUDIO_SETTINGS redirects the settings file")

    print("1) Atomic settings save")
    p = HOME / "a.json"
    check(save_settings({"x": 1, "שם": "שחר"}, p) and json.loads(p.read_text(encoding="utf-8"))["שם"] == "שחר",
          "save + reload (UTF-8 Hebrew)")
    real_replace = os.replace

    def boom(*a, **k):
        raise OSError("simulated crash / disk full during write")
    os.replace = boom
    try:
        ok = save_settings({"x": 2}, p)
    finally:
        os.replace = real_replace
    check(not ok and json.loads(p.read_text(encoding="utf-8"))["x"] == 1,
          "write fails half-way → old file intact, returns False (no exception)")
    check(not list(HOME.glob(".a.json.*.tmp")), "no temp files left behind")
    check(not save_settings({"bad": object()}, p) and json.loads(p.read_text(encoding="utf-8"))["x"] == 1,
          "unserializable value → nothing written, old file intact")
    check("Could not save settings" in log_text(), "save failures are logged")

    print("2) Corrupt settings file → defaults, file kept aside")
    bad = HOME / "corrupt.json"
    bad.write_text('{"magnet_size": "10x10", "print_count_total": 41', encoding="utf-8")  # truncated
    data = load_settings(bad)
    backups = list(HOME.glob("corrupt.json.corrupt-*"))
    check(data == DEFAULTS and not bad.exists() and len(backups) == 1,
          f"app starts with defaults; broken file saved as {backups[0].name if backups else None}")
    check("Settings file unreadable" in log_text(), "logged as an error")
    (HOME / "list.json").write_text("[1, 2]", encoding="utf-8")
    check(load_settings(HOME / "list.json") == DEFAULTS, "valid JSON but not an object → defaults")

    print("3) Counter + setup on disk after every print (no app close)")
    app = QApplication.instance() or QApplication(sys.argv)
    from magnetstudio import app as app_main
    app_main._setup_fonts(app)
    from magnetstudio.ui.theme import apply_theme
    apply_theme(app)
    from magnetstudio.core.printer import DRY_RUN_PRINTER
    from magnetstudio.ui.main_window import MainWindow

    photos = []
    for i, c in enumerate([(200, 120, 90), (90, 140, 200)]):
        ph = HOME / f"IMG_{i}.jpg"
        Image.new("RGB", (1600, 1200), c).save(ph)
        photos.append(str(ph))
    st = load_settings()
    st.update(output_folder=str(HOME / "out"), print_count_total=500, frame=None, enhance=False)
    save_settings(st)
    win = MainWindow(load_settings())
    win.show()
    win.printer_box.setCurrentText(DRY_RUN_PRINTER)
    win.size_box.setCurrentIndex(win.size_box.findData("10x10"))

    item = win.add_photo(photos[0], "manual")
    win._print_item(item.id)
    check(wait_until(lambda: item.status == "done"), "print 1 done")
    disk = load_settings()  # what a fresh start after a crash would see
    check(disk["print_count_total"] == 501, f"counter on disk right after the print: {disk['print_count_total']}")
    check(disk["magnet_size"] == "10x10" and disk["thermal_printer"] == DRY_RUN_PRINTER,
          "current size + printer saved too")
    win.copies_box.setValue(3)
    win._print_item(item.id)
    check(wait_until(lambda: item.copies_printed == 4) and load_settings()["print_count_total"] == 504,
          "3 copies → +3 on disk (504)")
    win.copies_box.setValue(1)
    win.enhance_act.setChecked(True)
    check(load_settings()["enhance"] is True, "enhancer toggle saved immediately")
    win.enhance_act.setChecked(False)

    print("4) Save failure during an event → one warning, printing continues")
    real_path = os.environ["MAGNETSTUDIO_SETTINGS"]
    blocked = HOME / "blocked"
    blocked.mkdir()
    os.environ["MAGNETSTUDIO_SETTINGS"] = str(blocked)  # a folder: every save fails
    toasts = []
    orig_toast = win.toast.show_message
    win.toast.show_message = lambda m, kind="info", ms=4000: (toasts.append((m, kind)), orig_toast(m, kind, ms))
    for _ in range(2):
        before = item.copies_printed
        win._print_item(item.id)
        wait_until(lambda: item.copies_printed == before + 1)
    errors = [m for m, k in toasts if k == "error" and "הגדרות" in m]
    check(item.copies_printed == 6 and len(errors) == 1, f"2 prints OK, save-error toast shown once ({len(errors)})")
    os.environ["MAGNETSTUDIO_SETTINGS"] = real_path
    win._save_error_shown = False

    print("5) What the log records")
    bad_img = HOME / "broken.jpg"
    bad_img.write_bytes(b"not an image")
    b_item = win.add_photo(str(bad_img), "drop", select=False)
    win._print_item(b_item.id)
    wait_until(lambda: b_item.status == "failed")
    junk_frame = HOME / "junk.json"
    junk_frame.write_text("{oops", encoding="utf-8")
    win.settings["frame"] = str(junk_frame)
    j_item = win.add_photo(photos[1], "manual", select=False)
    job = win._make_job(photos[1], 1, j_item.id)
    job.frame_path = str(junk_frame)
    win.submit_job(job)
    wait_until(lambda: j_item.status == "failed")
    win.settings["frame"] = None
    (HOME / "hot").mkdir()
    win.settings["watch_folder"] = str(HOME / "hot")
    win.auto_print.setChecked(True)
    Image.open(photos[1]).save(HOME / "hot" / "IMG_hot.jpg")
    wait_until(lambda: any(i.source == "hot" and i.status == "done" for i in win.items.values()), 30)
    win.auto_print.setChecked(False)
    text = log_text()
    for needle, what in [("Printers found:", "printers at startup"),
                         ("Queued [", "job queued"),
                         ("Print start [", "print start with file, printer, mode, copies"),
                         ("Print done in", "print done with duration"),
                         ("Counter: +1 → total 501", "counter progression"),
                         ("not a valid image", "bad photo"),
                         ("Traceback (most recent call last)", "full traceback for unexpected errors"),
                         ("Hot folder watching", "hot folder on"),
                         ("Hot folder: new file IMG_hot.jpg", "new hot-folder file"),
                         ("Hot folder off", "hot folder off"),
                         ("Enhancer on", "enhancer toggle"),
                         ("Could not save settings", "settings save failure")]:
        check(needle in text, f"log has {what}")
    check("broken.jpg" in text and "IMG_1.jpg" in text, "log lines name the file")
    win._printer_timer.stop()
    app.removeEventFilter(win)
    win.hide()

    print("6) Log rotation")
    rot_dir = HOME / "rot"
    applog.setup_logging(directory=rot_dir, console=False)
    big = logging.getLogger("rotation-test")
    for i in range(45000):  # ≈ 7.5 MB → must stop at 1 + 5 backups
        big.info("line %05d %s", i, "x" * 120)
    files = sorted(p.name for p in rot_dir.iterdir())
    sizes = [p.stat().st_size for p in rot_dir.iterdir()]
    check(len(files) == 6 and max(sizes) <= applog.MAX_BYTES + 500, f"{len(files)} files, max {max(sizes):,} bytes")
    applog.setup_logging(directory=HOME / "logs", console=False)

    print("7) Unexpected exception in the UI → logged, app keeps running")
    crash_code = """
        import os, sys
        from PyQt6.QtCore import QTimer
        from PyQt6.QtWidgets import QApplication
        from magnetstudio.core import applog
        applog.setup_logging(console=False)
        if sys.argv[-1] == "hooks":
            applog.install_exception_hooks(lambda m: print("TOAST:", m, flush=True))
        app = QApplication(sys.argv)
        def bad_slot():
            raise RuntimeError("boom in a slot")
        QTimer.singleShot(100, bad_slot)
        QTimer.singleShot(600, lambda: (print("ALIVE", flush=True), app.quit()))
        app.exec()
        """
    with_hooks = run_child(crash_code.replace("sys.argv[-1]", '"hooks"'))
    without = run_child(crash_code)
    child_log = (HOME / "child_logs" / "magnetstudio.log").read_text(encoding="utf-8")
    check(with_hooks.returncode == 0 and "ALIVE" in with_hooks.stdout, "with hooks: app survives the exception")
    check("TOAST: שגיאה לא צפויה: boom in a slot" in with_hooks.stdout, "user gets an error toast")
    check("Uncaught exception" in child_log and "boom in a slot" in child_log and "bad_slot" in child_log,
          "exception + traceback in the log")
    check(without.returncode != 0 and "ALIVE" not in without.stdout,
          f"control – without hooks PyQt6 aborts the whole app (exit {without.returncode})")
    thread_code = """
        import threading
        from magnetstudio.core import applog
        applog.setup_logging(console=False)
        applog.install_exception_hooks()
        t = threading.Thread(target=lambda: 1 / 0, name="watchdog-ish"); t.start(); t.join()
        print("ALIVE")
        """
    r = run_child(thread_code)
    child_log = (HOME / "child_logs" / "magnetstudio.log").read_text(encoding="utf-8")
    check(r.returncode == 0 and "Uncaught exception in thread watchdog-ish" in child_log
          and "ZeroDivisionError" in child_log, "exceptions in background threads are logged")

    print("8) Real startup: python -m magnetstudio")
    start_code = """
        import sys, runpy
        from PyQt6.QtCore import QTimer
        from PyQt6.QtWidgets import QApplication
        orig = QApplication.__init__
        def init(self, *a, **k):
            orig(self, *a, **k)
            QTimer.singleShot(1500, QApplication.quit)
        QApplication.__init__ = init
        sys.argv = ["magnetstudio"]
        try:
            runpy.run_module("magnetstudio", run_name="__main__")
        except SystemExit as e:
            print("EXIT", e.code)
        """
    r = run_child(start_code)
    child_log = (HOME / "child_logs" / "magnetstudio.log").read_text(encoding="utf-8")
    check("EXIT 0" in r.stdout, f"starts and exits cleanly ({r.stdout.strip() or r.stderr[-200:]})")
    from magnetstudio import __version__
    for needle in (f"MagnetStudio {__version__} starting", "PyQt6 ", "Settings: ", "Printers found:", "exiting (code 0)"):
        check(needle in child_log, f"startup log: '{needle.strip()}'")
    check(json.loads((HOME / "child_settings.json").read_text(encoding="utf-8"))["magnet_size"] == "7.5x10",
          "settings written on close")
    check(app_main._qt_message_handler is not None, "Qt warnings are routed to the log")
    from PyQt6.QtCore import QtMsgType
    app_main._qt_message_handler(QtMsgType.QtWarningMsg, None, "QPrinter: test warning")
    check("qt: QPrinter: test warning" in log_text(), "Qt warning appears in the log")

    print("\nPASS" if not failures else f"\nFAIL ({failures})")
    return 1 if failures else 0


def test_persistence():
    """Scenario test – every ✔/✘ line is printed; pytest shows them when a check fails."""
    assert _run() == 0, f"{failures} check(s) failed – see the ✘ lines in the captured output"
