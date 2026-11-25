"""15x20 sheet printing (rows × cols), per-photo copies, PNG frame pairs, global adjustments."""
from PIL import Image, ImageChops

from magnetstudio.core.layout import SheetSpec, auto_grid, build_grid_sheets, fit_into_cell, sheet_cells
from magnetstudio.core.print_jobs import PrintJob, PrintMode, build_pages
from magnetstudio.core.sizes import PAPER_SIZES, get_paper, get_size, mm_to_px


def test_paper_sizes():
    assert get_paper("15x20").size_px == (1795, 2398)       # 6x8" at 300 DPI
    assert PAPER_SIZES["15x20"].label == '15.2x20.3 (6x8")'


def test_auto_grid_7_5x10_on_15x20_is_2x2():
    assert auto_grid(get_size("7.5x10").size_px, "15x20") == (2, 2)
    assert auto_grid(get_size("10x10").size_px, "15x20") == (2, 1)
    assert auto_grid(get_size("15x20").size_px, "15x20") == (1, 1)


def test_cells_respect_margins():
    spec = SheetSpec(paper="15x20", rows=2, cols=2, margins_mm=(1.5, 1.5, 1.5, 1.5))
    cells = sheet_cells(spec)
    assert len(cells) == 4
    m = mm_to_px(1.5)
    x, y, w, h = cells[0]
    assert (x, y) == (m, m)
    pw, ph = get_paper("15x20").size_px
    x3, y3, w3, h3 = cells[3]
    assert abs((x3 + w3) - (pw - m)) <= 1 and abs((y3 + h3) - (ph - m)) <= 1
    # a 7.5x10 magnet nearly fills its cell
    assert w / get_size("7.5x10").size_px[0] > 0.97


def test_mixed_orientations_fill_cells_without_crop():
    portrait = Image.new("RGB", get_size("7.5x10").size_px, (200, 30, 30))
    landscape = Image.new("RGB", get_size("7.5x10").size_px[::-1], (30, 30, 200))
    pages = build_grid_sheets([portrait, landscape, portrait, landscape, portrait], paper="15x20", rows=2, cols=2)
    assert len(pages) == 2 and pages[0].size == get_paper("15x20").size_px
    assert pages[0].info["dpi"] == (300, 300)
    _, _, w, h = sheet_cells(SheetSpec())[1]
    fitted = fit_into_cell(landscape, w, h)
    assert fitted.height > fitted.width, "landscape magnet rotated into the portrait cell"
    # second cell is blue (the landscape magnet), page 2 has one magnet and white elsewhere
    x, y, w, h = sheet_cells(SheetSpec())[1]
    assert pages[0].getpixel((x + w // 2, y + h // 2)) == (30, 30, 200)
    x, y, w, h = sheet_cells(SheetSpec())[3]
    assert pages[1].getpixel((x + w // 2, y + h // 2)) == (255, 255, 255)


def test_crop_marks_only_outside_photos():
    img = Image.new("RGB", get_size("7.5x10").size_px, (0, 0, 0))
    with_marks = build_grid_sheets([img] * 4, paper="15x20", crop_marks=True, mark_width="thick")[0]
    without = build_grid_sheets([img] * 4, paper="15x20", crop_marks=False)[0]
    assert ImageChops.difference(with_marks, without).getbbox() is not None, "marks visible in margins"
    x, y, w, h = sheet_cells(SheetSpec())[0]
    assert with_marks.getpixel((x + w // 2, y + h // 2)) == (0, 0, 0), "never on top of a photo"


def test_sheet_mode_and_per_photo_copies(tmp_path):
    photos = []
    for i, size in enumerate([(1500, 2000), (2000, 1500), (1500, 2000)]):
        p = tmp_path / f"p{i}.jpg"
        Image.new("RGB", size, (i * 80, 100, 100)).save(p)
        photos.append(str(p))
    job = PrintJob(mode=PrintMode.SHEET, printer_name="", photo_paths=photos, magnet_size="7.5x10",
                   photo_copies=[2, 0, 3], layout_opts={"paper": "15x20", "rows": 2, "cols": 2})
    assert job.magnet_count() == 5
    imgs = job.render_images()
    assert len(imgs) == 5
    pages = build_pages(imgs, PrintMode.SHEET, **job.layout_opts)
    assert len(pages) == 2


def test_png_frame_pair_by_orientation(tmp_path):
    from magnetstudio.core.framer import render_magnet
    w, h = get_size("7.5x10").size_px
    port, land = tmp_path / "port.png", tmp_path / "land.png"
    f = Image.new("RGBA", (w, h), (0, 0, 0, 0)); f.paste((255, 0, 0, 255), (0, 0, w, 40)); f.save(port)
    f = Image.new("RGBA", (h, w), (0, 0, 0, 0)); f.paste((0, 255, 0, 255), (0, 0, h, 40)); f.save(land)
    pp, lp = tmp_path / "pp.jpg", tmp_path / "lp.jpg"
    Image.new("RGB", (1500, 2000), "white").save(pp)
    Image.new("RGB", (2000, 1500), "white").save(lp)
    a = render_magnet(pp, "7.5x10", port, frame_landscape=land)
    b = render_magnet(lp, "7.5x10", port, frame_landscape=land)
    assert a.height > a.width and a.getpixel((10, 10)) == (255, 0, 0)
    assert b.width > b.height and b.getpixel((10, 10)) == (0, 255, 0)
    c = render_magnet(lp, "7.5x10", None, frame_landscape=land)      # only a landscape frame given
    assert c.getpixel((10, 10)) == (0, 255, 0)


def test_adjustments_filter():
    from magnetstudio.core.framer import make_enhance_filter
    assert make_enhance_filter({"enhance": False}) is None
    f = make_enhance_filter({"enhance": False, "exposure": 40})
    img = Image.new("RGB", (10, 10), (100, 100, 100))
    assert f(img).getpixel((5, 5))[0] > 100
    f = make_enhance_filter({"enhance": True, "exposure": -40})
    assert f(img).getpixel((5, 5))[0] < 140


def test_driver_media_size(qapp, monkeypatch):
    """Mitsubishi CP-D80DW's 6x8 media is 158×206 mm – the sheet is laid out on the real media."""
    from PyQt6.QtCore import QSizeF
    from PyQt6.QtGui import QPageSize

    import magnetstudio.services.printer as pr

    class FakeInfo:
        def isNull(self):
            return False

        def supportedPageSizes(self):
            mm = QPageSize.Unit.Millimeter
            return [QPageSize(QPageSize.PageSizeId.A4), QPageSize(QSizeF(158, 206), mm, "6x8"),
                    QPageSize(QSizeF(102, 152), mm, "4x6")]

    monkeypatch.setattr(pr.QPrinterInfo, "printerInfo", staticmethod(lambda name: FakeInfo()))
    assert pr.media_size_mm("CP-D80DW", (152, 203)) == (158.0, 206.0)
    assert pr.media_size_mm("CP-D80DW", (89, 127)) is None, "no 3.5x5 media → nominal size"
    assert pr.media_size_mm(pr.DRY_RUN_PRINTER, (152, 203)) is None
    page = build_grid_sheets([Image.new("RGB", get_size("7.5x10").size_px)], paper="15x20", paper_mm=(158, 206))[0]
    assert page.size == (mm_to_px(158), mm_to_px(206))
