"""Print jobs – the Qt-free half of printing.

PrintJob describes what to print; build_pages turns its images into printer pages (thermal: one
page per magnet, A4: best-fit sheets); prepare_jobs saves print-ready 300 DPI files.
The Qt half (QPrinter, PrintWorker) is magnetstudio/services/printer.py.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

from PIL import Image

from magnetstudio.core.layout import build_a4_sheets
from magnetstudio.core.sizes import DPI

DRY_RUN_PRINTER = "שמירה לקובץ PDF (בדיקה)"


class PrintMode(str, Enum):
    THERMAL = "thermal"
    A4 = "a4"


class PrintError(RuntimeError):
    """Raised for any print failure; the message is shown to the user."""



def is_dry_run(printer_name: str | None) -> bool:
    return not printer_name or printer_name == DRY_RUN_PRINTER



def build_pages(images: list[Image.Image], mode: PrintMode, **layout_opts) -> list[Image.Image]:
    """Thermal: one page per magnet. A4: magnets arranged on sheets (best-fit)."""
    if mode == PrintMode.THERMAL:
        return list(images)
    return build_a4_sheets(images, **layout_opts)


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
    photo_filter: object = None      # e.g. the print enhancer, applied after crop, before frame
    copies: int = 1
    out_dir: str | Path = ""        # "" → paths.default_output_dir()
    job_name: str = "MagnetStudio"
    layout_opts: dict = field(default_factory=dict)
    tag: str = ""                    # caller's id (e.g. queue card) – not used by the printer

    def magnet_count(self) -> int:
        n = len(self.images) + (1 if self.photo_paths and str(self.frame_path or "").lower().endswith(".json")
                                else len(self.photo_paths))
        return n * max(1, self.copies)

    def render_images(self) -> list[Image.Image]:
        imgs = list(self.images)
        if self.photo_paths:
            from magnetstudio.core.framer import is_template, render_magnet
            if is_template(self.frame_path):
                # one magnet per job; all photos fill the template's slots (strip)
                imgs.append(render_magnet(self.photo_paths, self.magnet_size, self.frame_path,
                                          self.photo_filter))
            else:
                imgs += [render_magnet(p, self.magnet_size, self.frame_path, self.photo_filter)
                         for p in self.photo_paths]
        return [img for img in imgs for _ in range(max(1, self.copies))]
