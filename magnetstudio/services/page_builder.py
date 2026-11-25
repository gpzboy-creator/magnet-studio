"""PageBuilder – renders a batch PrintJob into finished printer pages off the GUI thread, for the print
preview and for "download JPEG". Each page also gets the card ids of the magnets on it, so printing only
some pages still counts copies per card correctly.
"""
from __future__ import annotations

import logging

from PyQt6.QtCore import QThread, pyqtSignal

from magnetstudio.core.print_jobs import PrintJob, build_pages, magnets_per_page

log = logging.getLogger(__name__)


def build_job_pages(job: PrintJob, progress=None):
    """→ (pages, owners per page). Pure function (used by the thread and by tests)."""
    imgs, owners = job.render_with_owners(progress)
    if not imgs:
        return [], []
    per = magnets_per_page(job.mode, imgs[0].size, **job.layout_opts)
    pages = build_pages(imgs, job.mode, **job.layout_opts)
    return pages, [owners[i * per:(i + 1) * per] for i in range(len(pages))]


class PageBuilder(QThread):
    progress = pyqtSignal(int, int)        # photos rendered, total photos
    done = pyqtSignal(list, list)          # pages (PIL images), owners per page (list[list[str]])
    failed = pyqtSignal(str)

    def __init__(self, job: PrintJob, parent=None):
        super().__init__(parent)
        self.job = job

    def run(self) -> None:
        try:
            pages, owners = build_job_pages(self.job, lambda d, t: self.progress.emit(d, t))
            self.done.emit(pages, owners)
        except Exception as e:  # noqa: BLE001 – shown to the user, full trace in the log
            log.exception("Building print pages failed")
            self.failed.emit(str(e))
