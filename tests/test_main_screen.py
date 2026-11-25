"""MagnetOti-style main screen: photo grid with copies, print all as 15x20 sheets, counters, Hot Folder
that waits for a full sheet, PNG frame pair, theme modes."""
import time
from pathlib import Path

from PIL import Image
from PyQt6.QtCore import QEventLoop, QTimer


def _wait(cond, timeout=30):
    end = time.time() + timeout
    while time.time() < end:
        if cond():
            return True
        loop = QEventLoop()
        QTimer.singleShot(50, loop.quit)
        loop.exec()
    return cond()


def _photos(tmp_path: Path, n: int) -> list[str]:
    out = []
    for i in range(n):
        p = tmp_path / f"IMG_{i}.jpg"
        Image.new("RGB", (1500, 2000) if i % 2 == 0 else (2000, 1500), (40 * i % 255, 120, 160)).save(p)
        out.append(str(p))
    return out


def _window(settings_update=None):
    from magnetstudio.core.settings import load_settings
    from magnetstudio.ui.main_window import MainWindow
    s = load_settings()
    s.update(cost_per_sheet=4.0, **(settings_update or {}))
    return MainWindow(s)


def test_print_all_as_sheets(qapp, tmp_path):
    from magnetstudio.services.print_queue import Stage
    win = _window({"output_folder": str(tmp_path / "out")})
    try:
        assert win.mode_box.currentData() == "sheet" and (win.rows_box.value(), win.cols_box.value()) == (2, 2)
        assert not win.grid.inner.isVisible() or not win.grid.order, "empty state first"
        items = [win.add_photo(p, "manual", select=False) for p in _photos(tmp_path, 3)]
        assert list(win.grid.order) == [i.id for i in items]
        assert _wait(lambda: all(c._pix is not None for c in win.grid.cards.values())), "thumbnails rendered"
        win.grid.cards[items[0].id].set_copies(3, emit=True)
        win.grid.cards[items[2].id].set_copies(2, emit=True)
        assert "5 עותקים · 2 דפים" in win.summary_lbl.text()
        win._print_all()
        assert _wait(lambda: items[0].stage == Stage.PRINTED and items[2].stage == Stage.PRINTED)
        assert items[1].stage == Stage.INCOMING, "a card with 0 copies is not printed"
        assert (items[0].copies_printed, items[2].copies_printed) == (3, 2)
        assert win.grid.total_copies() == 0, "copies reset after a successful print"
        pdfs = list((tmp_path / "out").glob("*.pdf"))
        assert len(pdfs) == 1
        from pypdf import PdfReader
        pages = PdfReader(str(pdfs[0])).pages
        w_mm = float(pages[0].mediabox.width) / 72 * 25.4
        assert len(pages) == 2 and abs(w_mm - 152) < 2, f"two 15x20 sheets ({len(pages)}, {w_mm:.0f} mm)"
        s = win.settings
        assert (s["event_sheets"], s["today_sheets"], s["event_cost"]) == (2, 2, 8.0)
        assert "דפים הודפסו: 2" in win.sheets_chip.text() and "8.00" in win.cost_chip.text()
        win.settings.update(event_sheets=0, event_cost=0.0)
    finally:
        win.close()


def test_hot_folder_waits_for_a_full_sheet(qapp, tmp_path):
    from magnetstudio.services.print_queue import Stage
    win = _window({"output_folder": str(tmp_path / "out")})
    try:
        win.fill_sheet.setChecked(True)
        photos = _photos(tmp_path, 4)
        for p in photos[:3]:
            win._on_new_photo(p)
        hot = list(win.items.values())
        assert all(i.stage == Stage.INCOMING for i in hot), "3 of 4 → still waiting"
        assert "3/4" in win.statusBar().currentMessage()
        win._on_new_photo(photos[3])
        hot = list(win.items.values())
        assert _wait(lambda: all(i.stage == Stage.PRINTED for i in hot)), "4th photo fills the sheet → printed"
        assert len(list((tmp_path / "out").glob("*.pdf"))) == 1, "one sheet, one job"
    finally:
        win.close()


def test_png_frame_pair_and_remove(qapp, tmp_path):
    from magnetstudio import paths
    from magnetstudio.core.sizes import get_size
    win = _window()
    try:
        w, h = get_size("7.5x10").size_px
        paths.user_templates_dir().mkdir(parents=True, exist_ok=True)
        port, land = paths.user_templates_dir() / "p.png", paths.user_templates_dir() / "l.png"
        Image.new("RGBA", (w, h), (255, 0, 0, 255)).save(port)
        Image.new("RGBA", (h, w), (0, 255, 0, 255)).save(land)
        win._reload_frames(select=str(port))
        win._on_frame_changed()
        win.settings["frame_landscape"] = str(land)
        win._update_frame_chips()
        assert win.portrait_btn.isChecked() and win.landscape_btn.isChecked()
        job = win._make_job(["a.jpg", "b.jpg"], [1, 2], "x,y")
        assert job.frame_path == str(port) and job.frame_landscape_path == str(land)
        assert job.photo_copies == [1, 2] and job.layout_opts["paper"] == "15x20"
        win._clear_frames()
        assert not win.portrait_btn.isChecked() and not win.settings["frame_landscape"]
        item = win.add_photo(_photos(tmp_path, 1)[0], "manual")
        win._remove_photo(item.id)
        assert item.id not in win.grid.cards and item.id not in win.items
    finally:
        win.close()


def test_theme_modes(qapp):
    from magnetstudio.ui import theme
    try:
        assert theme.set_mode("light") == "light" and theme.ThemeColors.BG_CARD == "#FFFFFF"
        assert "#FFFFFF" in theme.app_qss()
        assert theme.set_mode("dark") == "dark" and theme.ThemeColors.BG_ROOT == "#121316"
        assert theme.set_mode("auto", qapp) in ("light", "dark")
    finally:
        theme.set_mode("dark")
