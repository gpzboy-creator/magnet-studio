"""Printing with Qt: thermal (one magnet per page) and A4 sheets, at 300 DPI.

- get_available_printers(): system printers (Windows & macOS via Qt), plus a
  virtual "dry run" target that prints to PDF – for dev machines with no printer.
- PrintWorker (QThread): sends a job in the background so the UI never blocks.
- print_pages(): the actual QPainter loop; QPainter.end() always runs (try/finally).

The Qt-free part (PrintJob, PrintMode, build_pages, …) is core/print_jobs.py; it is re-exported
here so callers can import everything printing-related from one place.
"""
from __future__ import annotations

import logging
import time
from pathlib import Path

from PIL import Image
from PyQt6.QtCore import QMarginsF, QRectF, QSizeF, QThread, pyqtSignal
from PyQt6.QtGui import QImage, QPageLayout, QPageSize, QPainter
from PyQt6.QtPrintSupport import QPrinter, QPrinterInfo

from magnetstudio import paths
from magnetstudio.core.print_jobs import (  # noqa: F401 (re-export)
    DRY_RUN_PRINTER,
    PrintError,
    PrintJob,
    PrintMode,
    build_pages,
    is_dry_run,
    prepare_jobs,
    save_print_file,
)
from magnetstudio.core.sizes import DPI, px_to_cm

log = logging.getLogger(__name__)

# ---------------------------------------------------------------- printers

def get_available_printers(include_dry_run: bool = True) -> list[str]:
    """System printer names (default printer first), plus the dry-run target."""
    names = list(QPrinterInfo.availablePrinterNames())
    default = QPrinterInfo.defaultPrinterName()
    if default in names:
        names.remove(default)
        names.insert(0, default)
    if include_dry_run:
        names.append(DRY_RUN_PRINTER)
    return names


def is_printer_available(printer_name: str) -> bool:
    if is_dry_run(printer_name):
        return True
    return not QPrinterInfo.printerInfo(printer_name).isNull()


# ---------------------------------------------------------------- pages

def _pil_to_qimage(img: Image.Image) -> QImage:
    rgb = img.convert("RGB")
    data = rgb.tobytes("raw", "RGB")
    # .copy() so the QImage owns its memory after `data` goes away
    return QImage(data, rgb.width, rgb.height, 3 * rgb.width, QImage.Format.Format_RGB888).copy()


def _page_layout_for(img: Image.Image, mode: PrintMode) -> QPageLayout:
    if mode == PrintMode.A4:
        size = QPageSize(QPageSize.PageSizeId.A4)
        orientation = QPageLayout.Orientation.Portrait
    else:
        w_mm, h_mm = px_to_cm(img.width) * 10, px_to_cm(img.height) * 10
        short, long_ = sorted((w_mm, h_mm))
        size = QPageSize(QSizeF(short, long_), QPageSize.Unit.Millimeter,
                         f"Magnet {short:g}x{long_:g}mm", QPageSize.SizeMatchPolicy.ExactMatch)
        orientation = (QPageLayout.Orientation.Landscape if w_mm > h_mm
                       else QPageLayout.Orientation.Portrait)
    return QPageLayout(size, orientation, QMarginsF(0, 0, 0, 0), QPageLayout.Unit.Millimeter)


def _make_printer(printer_name: str | None, pdf_path: Path | None, job_name: str) -> QPrinter:
    printer = QPrinter(QPrinter.PrinterMode.HighResolution)
    if pdf_path is not None:
        printer.setOutputFormat(QPrinter.OutputFormat.PdfFormat)
        printer.setOutputFileName(str(pdf_path))
    else:
        printer.setPrinterName(printer_name)
        if not printer.isValid():
            raise PrintError(f"המדפסת '{printer_name}' לא זמינה")
    printer.setResolution(DPI)
    printer.setFullPage(True)
    printer.setDocName(job_name)
    printer.setColorMode(QPrinter.ColorMode.Color)
    return printer


def print_pages(pages: list[Image.Image], mode: PrintMode, printer_name: str | None = None,
                pdf_path: str | Path | None = None, job_name: str = "MagnetStudio",
                progress=None, should_cancel=None) -> int:
    """Render pages to a system printer or to a PDF file. Returns pages printed.

    progress(done, total) and should_cancel() are optional callbacks.
    """
    if not pages:
        raise PrintError("אין מה להדפיס")
    pdf = Path(pdf_path) if pdf_path else None
    if pdf:
        pdf.parent.mkdir(parents=True, exist_ok=True)
    printer = _make_printer(printer_name, pdf, job_name)
    printer.setPageLayout(_page_layout_for(pages[0], mode))

    painter = QPainter()
    if not painter.begin(printer):
        raise PrintError("לא ניתן להתחיל הדפסה – בדוק שהמדפסת מחוברת ופנויה")
    done = 0
    try:
        for i, page in enumerate(pages):
            if should_cancel and should_cancel():
                printer.abort()
                break
            if i > 0 and not printer.newPage():
                raise PrintError("המדפסת דחתה עמוד חדש")
            qimg = _pil_to_qimage(page)
            target = QRectF(painter.viewport())
            # keep aspect ratio, center on the page
            scale = min(target.width() / qimg.width(), target.height() / qimg.height())
            w, h = qimg.width() * scale, qimg.height() * scale
            painter.drawImage(QRectF(target.x() + (target.width() - w) / 2,
                                     target.y() + (target.height() - h) / 2, w, h), qimg)
            done += 1
            if progress:
                progress(done, len(pages))
    finally:
        painter.end()  # always release the printer / spool handle
    return done


def dry_run(images: list[Image.Image], mode: PrintMode, out_dir: str | Path | None = None,
            **layout_opts) -> Path:
    """Print to a PDF file instead of a printer (dev / no printer connected)."""
    pages = build_pages(images, mode, **layout_opts)
    pdf = Path(out_dir or paths.default_output_dir()) / f"dryrun_{mode.value}_{time.strftime('%Y%m%d_%H%M%S')}.pdf"
    print_pages(pages, mode, pdf_path=pdf, job_name=f"MagnetStudio dry run ({mode.value})")
    return pdf


# ---------------------------------------------------------------- worker

class PrintWorker(QThread):
    """Runs one PrintJob off the GUI thread. Signals arrive on the GUI thread."""

    status = pyqtSignal(str)            # human-readable step
    progress = pyqtSignal(int, int)     # done, total
    succeeded = pyqtSignal(str)         # summary message (or PDF path)
    failed = pyqtSignal(str)            # error message

    def __init__(self, job: PrintJob, parent=None):
        super().__init__(parent)
        self.job = job
        self._cancel = False

    def cancel(self) -> None:
        self._cancel = True

    def _describe(self) -> str:
        j = self.job
        files = ", ".join(Path(p).name for p in j.photo_paths) or f"{len(j.images)} image(s)"
        return (f"[{j.tag or '-'}] {files} → {j.printer_name or 'PDF'} ({j.mode.value}, ×{j.copies}, "
                f"frame={Path(j.frame_path).name if j.frame_path else 'none'})")

    def run(self) -> None:
        job = self.job
        t0 = time.perf_counter()
        log.info("Print start %s", self._describe())
        try:
            if not is_printer_available(job.printer_name):
                raise PrintError(f"המדפסת '{job.printer_name}' לא זמינה")
            self.status.emit("מכין עמודים…")
            pages = build_pages(job.render_images(), job.mode, **job.layout_opts)
            self.progress.emit(0, len(pages))

            pdf = None
            if is_dry_run(job.printer_name):
                pdf = Path(job.out_dir or paths.default_output_dir()) / f"dryrun_{job.mode.value}_{time.strftime('%Y%m%d_%H%M%S')}.pdf"
                self.status.emit("שומר ל-PDF…")
            else:
                self.status.emit(f"שולח ל-{job.printer_name}…")

            done = print_pages(pages, job.mode, job.printer_name, pdf, job.job_name,
                               progress=lambda d, t: self.progress.emit(d, t),
                               should_cancel=lambda: self._cancel)
            secs = time.perf_counter() - t0
            if self._cancel:
                log.warning("Print cancelled %s", self._describe())
                self.failed.emit("ההדפסה בוטלה")
            elif pdf:
                log.info("Print done in %.1fs: %d page(s) → %s", secs, done, pdf)
                self.succeeded.emit(f"נשמר: {pdf}")
            else:
                log.info("Print done in %.1fs: %d page(s) spooled to %s", secs, done, job.printer_name)
                self.succeeded.emit(f"נשלחו {done} עמודים ל-{job.printer_name}")
        except PrintError as e:
            log.error("Print failed %s: %s", self._describe(), e)
            self.failed.emit(str(e))
        except FileNotFoundError as e:
            log.error("Print failed %s: file not found %s", self._describe(), e.filename)
            self.failed.emit(f"הקובץ לא נמצא: {Path(e.filename or '').name}")
        except Exception as e:  # never let the thread die silently
            from PIL import UnidentifiedImageError
            if isinstance(e, UnidentifiedImageError):
                log.error("Print failed %s: not a valid image", self._describe())
                self.failed.emit("הקובץ אינו תמונה תקינה")
            else:
                log.exception("Print failed %s", self._describe())  # full traceback in the log
                self.failed.emit(f"שגיאת הדפסה: {e}")
