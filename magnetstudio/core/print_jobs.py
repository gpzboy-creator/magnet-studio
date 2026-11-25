"""Print jobs – the Qt-free half of printing.

PrintJob describes what to print; build_pages turns its images into printer pages (sheet: rows ×
cols on e.g. 15x20 paper – the main mode; thermal: one page per magnet; A4: best-fit sheets);
prepare_jobs saves print-ready 300 DPI files.
The Qt half (QPrinter, PrintWorker) is magnetstudio/services/printer.py.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

from PIL import Image

from magnetstudio.core.layout import build_a4_sheets, build_grid_sheets
from magnetstudio.core.sizes import DPI

DRY_RUN_PRINTER = "שמירה לקובץ PDF (בדיקה)"


class PrintMode(str, Enum):
    SHEET = "sheet"        # rows × cols on a printer sheet (15x20 dye-sub: 2×2 magnets 7.5x10)
    THERMAL = "thermal"    # one magnet per page
    A4 = "a4"              # A4, best-fit with auto orientation


class PrintError(RuntimeError):
    """Raised for any print failure; the message is shown to the user."""



def is_dry_run(printer_name: str | None) -> bool:
    return not printer_name or printer_name == DRY_RUN_PRINTER



def magnets_per_page(mode: PrintMode, magnet_px: tuple[int, int] | None = None, **layout_opts) -> int:
    """How many magnets one printed page holds in this mode."""
    if mode == PrintMode.THERMAL:
        return 1
    if mode == PrintMode.SHEET:
        from magnetstudio.core.layout import SheetSpec
        return SheetSpec.from_opts(layout_opts).per_sheet
    from magnetstudio.core.layout import plan_grid
    try:
        return plan_grid(magnet_px or (886, 1181), layout_opts.get("margin_cm", 0.3),
                         layout_opts.get("gap_cm", 0.2)).per_page
    except ValueError:
        return 1


def build_pages(images: list[Image.Image], mode: PrintMode, **layout_opts) -> list[Image.Image]:
    """Sheet: rows × cols grid. Thermal: one page per magnet. A4: best-fit sheets."""
    if mode == PrintMode.THERMAL:
        return list(images)
    if mode == PrintMode.SHEET:
        return build_grid_sheets(images, **layout_opts)
    return build_a4_sheets(images, **{k: v for k, v in layout_opts.items()
                                      if k in ("margin_cm", "gap_cm", "crop_marks", "allow_rotate")})


def save_print_file(img: Image.Image, path: str | Path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    img.save(path, dpi=(DPI, DPI), quality=95)
    return path


def prepare_jobs(images: list[Image.Image], mode: PrintMode, out_dir: str | Path,
                 **layout_opts) -> list[Path]:
    """Save print-ready JPG files (300 DPI) for the chosen mode."""
    out_dir = Path(out_dir)
    pages = build_pages(images, mode, **layout_opts)
    return [save_print_file(p, out_dir / f"{mode.value}_{i:03d}.jpg") for i, p in enumerate(pages, 1)]


@dataclass
class PrintJob:
    """Either pass ready `images`, or `photo_paths` + `magnet_size` (+ `frame_path`)
    and the worker will fit/frame them in the background thread."""
    mode: PrintMode
    printer_name: str
    images: list[Image.Image] = field(default_factory=list)
    photo_paths: list[str | Path] = field(default_factory=list)
    magnet_size: str | None = None
    frame_path: str | Path | None = None
    frame_landscape_path: str | Path | None = None   # PNG for landscape photos (frame_path = portrait)
    photo_copies: list[int] = field(default_factory=list)   # per photo; overrides `copies` when given
    pages_ready: bool = False        # `images` are finished printer pages (from the print preview)
    magnets: int | None = None       # magnet count when pages_ready (for the counters)
    photo_filter: object = None      # e.g. the print enhancer, applied after crop, before frame
    copies: int = 1
    out_dir: str | Path = ""        # "" → paths.default_output_dir()
    job_name: str = "MagnetStudio"
    layout_opts: dict = field(default_factory=dict)
    tag: str = ""                    # caller's id (e.g. queue card) – not used by the printer

    def _copies_for(self, i: int) -> int:
        if self.photo_copies:
            return max(0, int(self.photo_copies[i])) if i < len(self.photo_copies) else 0
        return max(1, self.copies)

    def magnet_count(self) -> int:
        if self.magnets is not None:
            return self.magnets
        if self.photo_copies and self.photo_paths:
            return len(self.images) * max(1, self.copies) + sum(self._copies_for(i) for i in range(len(self.photo_paths)))
        n = len(self.images) + (1 if self.photo_paths and str(self.frame_path or "").lower().endswith(".json")
                                else len(self.photo_paths))
        return n * max(1, self.copies)

    def render_with_owners(self, progress=None) -> tuple[list[Image.Image], list[str]]:
        """Every magnet to print and the card id it belongs to (tag "id1,id2,…" ↔ photo_paths).
        Each photo is rendered once; its copies are the same image object, so they sit side by side."""
        from magnetstudio.core.framer import render_magnet
        ids = self.tag.split(",") if self.tag else []
        imgs, owners = [], []
        total = len(self.photo_paths)
        for i, p in enumerate(self.photo_paths):
            n = self._copies_for(i)
            if n:
                magnet = render_magnet(p, self.magnet_size, self.frame_path, self.photo_filter,
                                       frame_landscape=self.frame_landscape_path)
                imgs += [magnet] * n
                owners += [ids[i] if i < len(ids) else ""] * n
            if progress:
                progress(i + 1, total)
        return imgs, owners

    def render_images(self) -> list[Image.Image]:
        if self.pages_ready:
            return list(self.images)
        out = [img for img in self.images for _ in range(max(1, self.copies))]
        if not self.photo_paths:
            return out
        from magnetstudio.core.framer import is_template, render_magnet
        if is_template(self.frame_path) and not self.photo_copies:
            # one magnet per job; all photos fill the template's slots (strip)
            magnet = render_magnet(self.photo_paths, self.magnet_size, self.frame_path, self.photo_filter)
            return out + [magnet] * max(1, self.copies)
        for i, p in enumerate(self.photo_paths):
            n = self._copies_for(i)
            if n:
                magnet = render_magnet(p, self.magnet_size, self.frame_path, self.photo_filter,
                                       frame_landscape=self.frame_landscape_path)
                out += [magnet] * n
        return out
