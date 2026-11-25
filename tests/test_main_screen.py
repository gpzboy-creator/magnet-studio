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


def _window(settings_update=None):  # noqa: D401
    from magnetstudio.core.settings import load_settings
    from magnetstudio.ui.main_window import MainWindow
    s = load_settings()
    s.update(cost_per_sheet=4.0, **(settings_update or {}))
    return MainWindow(s)


class FakePreview:
    """Stands in for PrintPreviewDialog: accepts at once with the chosen pages / action."""
    select = None          # None = all pages, else list of page indices
    action = "print"

    def __init__(self, pages, owners, info, parent=None):
        self.pages, self.owners, self.info = pages, owners, info
        FakePreview.last = self

    def exec(self):
        return True

    def selected_indices(self):
        return list(range(len(self.pages))) if FakePreview.select is None else FakePreview.select

    def selected_pages(self):
        return [self.pages[i] for i in self.selected_indices()]

    def selected_owners(self):
        return [o for i in self.selected_indices() for o in self.owners[i]]


def test_print_all_via_preview(qapp, tmp_path, monkeypatch):
    import magnetstudio.ui.main_window as mw
    from magnetstudio.services.print_queue import Stage
    monkeypatch.setattr(mw, "PrintPreviewDialog", FakePreview)
    FakePreview.select, FakePreview.action = None, "print"
    win = _window({"output_folder": str(tmp_path / "out"), "start_copies": 0})
    try:
        assert win.mode_box.currentData() == "sheet" and (win.rows_box.value(), win.cols_box.value()) == (2, 2)
        items = [win.add_photo(p, "manual", select=False) for p in _photos(tmp_path, 3)]
        assert list(win.grid.order) == [i.id for i in items]
        assert _wait(lambda: all(c._pix is not None for c in win.grid.cards.values())), "thumbnails rendered"
        win.grid.cards[items[0].id].set_copies(3, emit=True)
        win.grid.cards[items[2].id].set_copies(2, emit=True)
        text = win.summary_lbl.text()
        assert "סה״כ להדפסה: <b>5</b>" in text and "יש 3 מקומות פנויים" in text, text
        win.grid.cards[items[1].id].set_copies(3, emit=True)
        assert "הדפים מלאים" in win.summary_lbl.text()
        win.grid.cards[items[1].id].set_copies(0, emit=True)
        win._print_all()
        assert _wait(lambda: items[0].stage == Stage.PRINTED and items[2].stage == Stage.PRINTED)
        assert FakePreview.last.info["layout"] == "2×2" and len(FakePreview.last.pages) == 2
        assert FakePreview.last.owners[0] == [items[0].id] * 3 + [items[2].id], "copies side by side"
        assert items[1].stage == Stage.INCOMING, "a card with 0 copies is not printed"
        assert (items[0].copies_printed, items[2].copies_printed) == (3, 2)
        assert win.grid.total_copies() == 5, "copies stay on the cards after printing (like MagnetOti)"
        pdfs = list((tmp_path / "out").glob("*.pdf"))
        assert len(pdfs) == 1
        from pypdf import PdfReader
        pages = PdfReader(str(pdfs[0])).pages
        w_mm = float(pages[0].mediabox.width) / 72 * 25.4
        assert len(pages) == 2 and abs(w_mm - 152) < 2, f"two 15x20 sheets ({len(pages)}, {w_mm:.0f} mm)"
        s = win.settings
        assert (s["event_sheets"], s["today_sheets"], s["event_cost"]) == (2, 2, 8.0)
        assert "דפים הודפסו: 2" in win.sheets_chip.text() and "8.00" in win.cost_chip.text()

        # only page 2 → only its magnets are counted
        FakePreview.select = [1]
        win._print_all()
        assert _wait(lambda: items[2].copies_printed == 3 and not items[2].in_flight)
        assert items[0].copies_printed == 3 and win.settings["event_sheets"] == 3

        # download JPEG: every page saved at 300 DPI
        out = tmp_path / "jpegs"
        out.mkdir()
        monkeypatch.setattr(mw.QFileDialog, "getExistingDirectory", staticmethod(lambda *a, **k: str(out)))
        FakePreview.select = None
        win._print_all(action="jpeg")
        assert _wait(lambda: len(list(out.glob("*.jpg"))) == 2)
        with Image.open(next(out.glob("*.jpg"))) as im:
            assert round(im.info["dpi"][0]) == 300 and im.size == (1795, 2398)
    finally:
        FakePreview.select = None
        win.close()


def test_start_from_toggle(qapp, tmp_path):
    win = _window()
    try:
        assert win.start_btn.isChecked() and win.start_btn.text() == "התחל מ1"
        a = win.add_photo(_photos(tmp_path, 1)[0], "manual", select=False)
        assert win.grid.cards[a.id].copies() == 1, "new photos start with 1 copy"
        win.start_btn.setChecked(False)
        assert win.grid.cards[a.id].copies() == 0 and win.settings["start_copies"] == 0
        assert win.start_btn.text() == "התחל מ0"
    finally:
        win.close()


def test_preview_dialog_selection(qapp):
    from magnetstudio.ui.print_preview import PrintPreviewDialog
    pages = [Image.new("RGB", (300, 400), c) for c in ("red", "green", "blue")]
    owners = [["a", "a", "b", "b"], ["b", "c", "c", "c"], ["d"]]
    dlg = PrintPreviewDialog(pages, owners, {"printer": "P", "paper": '15x20 (6x8")', "size_mm": (158, 206),
                                             "layout": "2×2", "dpi": 300})
    assert dlg.selected_indices() == [0, 1, 2] and "3 מתוך 3" in dlg.sel_chip.text()
    dlg._toggle(1)
    assert dlg.selected_indices() == [0, 2] and dlg.selected_owners() == ["a", "a", "b", "b", "d"]
    assert "הדפס 2 דפים" in dlg.print_btn.text() and "158×206" in dlg.summary.text()
    dlg.range_radio.setChecked(True)
    dlg.from_box.setValue(2)
    dlg.to_box.setValue(3)
    assert dlg.selected_indices() == [1, 2]
    dlg.close()


def test_hot_folder_waits_for_a_full_sheet(qapp, tmp_path):
    from magnetstudio.services.print_queue import Stage
    win = _window({"output_folder": str(tmp_path / "out")})
    try:
        win.fill_sheet.setChecked(True)
        photos = _photos(tmp_path, 4)  # Hot Folder photos get the "כמות לתמונה חדשה" (1)
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
