"""PrintQueueController – the print queue's state, in one place, without widgets.

Owns:
  items     photo cards (QueueItem), by id, in arrival order
  jobs      PrintJobs waiting for the printer (FIFO)
  worker    the one PrintWorker running now (jobs never run in parallel – one printer, one spool)
  counters  magnets printed this session / in total

The window only *displays* this state (via the signals) and asks for actions (add_photo,
print_item, submit). What a job prints – size, frame, printer, copies – is decided by the
`job_factory(item, copies)` the window supplies, so the controller stays UI-agnostic and testable
with a fake worker.

Stage of a card (a card may have several jobs: copies, reprints):

    INCOMING ─► QUEUED ─► ENHANCING ─► COMPOSING ─► SPOOLING ─► PRINTED
                  ▲          (enhancer on)                        │
                  └─────────── another job for the same card ◄────┘      any step ─► FAILED
"""
from __future__ import annotations

import logging
import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Callable

from PyQt6.QtCore import QObject, pyqtSignal

from magnetstudio.core.print_jobs import PrintJob
from magnetstudio.services.printer import PrintWorker, is_printer_available

log = logging.getLogger(__name__)


class Stage(str, Enum):
    INCOMING = "incoming"     # on the list, never sent
    QUEUED = "queued"         # has a job waiting for the printer
    ENHANCING = "enhancing"   # worker: crop + print enhancer
    COMPOSING = "composing"   # worker: frame / template; pages ready
    SPOOLING = "spooling"     # worker: pages going to the printer
    PRINTED = "printed"       # last job done, nothing waiting
    FAILED = "failed"         # last job failed (error in QueueItem.error)

    @property
    def busy(self) -> bool:
        return self in (Stage.ENHANCING, Stage.COMPOSING, Stage.SPOOLING)


@dataclass
class QueueItem:
    """One photo in the queue (a card). Several print jobs may refer to it."""
    path: str
    source: str = "manual"            # manual | hot | drop
    stage: Stage = Stage.INCOMING
    copies_printed: int = 0           # magnets printed from this photo, all jobs
    jobs_open: int = 0                # jobs queued or running for this photo
    error: str = ""
    added: float = field(default_factory=time.time)
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:10])

    @property
    def in_flight(self) -> bool:
        return self.jobs_open > 0 or self.stage.busy

    @property
    def name(self) -> str:
        return Path(self.path).name


JobFactory = Callable[[QueueItem, int], PrintJob]


class PrintQueueController(QObject):
    item_added = pyqtSignal(str)            # item id
    item_changed = pyqtSignal(str)          # item id – stage / copies / error changed
    busy_changed = pyqtSignal(bool)         # worker started / queue drained
    status = pyqtSignal(str)                # human-readable step from the worker
    progress = pyqtSignal(int, int)         # pages done, total (0, 0 = rendering)
    job_succeeded = pyqtSignal(str, int)    # worker message, magnets printed
    job_failed = pyqtSignal(str)            # error message
    printer_unavailable = pyqtSignal(str)   # printer name – the window should refresh its list

    def __init__(self, job_factory: JobFactory, total_printed: int = 0, *,
                 worker_cls=PrintWorker, printer_check=is_printer_available, parent=None):
        super().__init__(parent)
        self.job_factory = job_factory
        self.items: dict[str, QueueItem] = {}
        self.jobs: deque[PrintJob] = deque()
        self.worker = None
        self.active_job: PrintJob | None = None
        self.session_printed = 0
        self.total_printed = int(total_printed)
        self._worker_cls = worker_cls
        self._printer_check = printer_check

    # ---------------------------------------------------------------- items
    def add_photo(self, path: str, source: str = "manual") -> QueueItem:
        item = QueueItem(path=str(path), source=source)
        self.items[item.id] = item
        log.info("Queue +%s [%s] from %s", item.name, item.id, source)
        self.item_added.emit(item.id)
        return item

    def get(self, item_id: str | None) -> QueueItem | None:
        return self.items.get(item_id) if item_id else None

    def find_by_path(self, path: str) -> QueueItem | None:
        return next((i for i in self.items.values() if i.path == str(path)), None)

    def _set_stage(self, item: QueueItem, stage: Stage, error: str = "") -> None:
        item.stage, item.error = stage, error
        self.item_changed.emit(item.id)

    # ---------------------------------------------------------------- actions
    @property
    def is_busy(self) -> bool:
        return self.worker is not None

    @property
    def waiting(self) -> int:
        return len(self.jobs)

    def print_item(self, item_id: str, copies: int = 1, *, allow_duplicate: bool = True) -> bool:
        """Make a job for a card (via job_factory) and queue it.

        allow_duplicate=False refuses while the card already has a job waiting / running – a fast
        double Space must not print the photo twice. Returns False when nothing was queued."""
        item = self.get(item_id)
        if item is None:
            return False
        if not allow_duplicate and item.in_flight:
            log.info("Ignored: %s is already in the print queue", item.name)
            return False
        return self.submit(self.job_factory(item, max(1, int(copies))))

    def submit(self, job: PrintJob) -> bool:
        """Queue a job; jobs run one at a time in a worker thread."""
        item = self.get(job.tag)
        if not self._printer_check(job.printer_name):
            msg = f"המדפסת '{job.printer_name}' לא זמינה"
            log.error("Printer unavailable: %r (job %s)", job.printer_name, job.tag or "-")
            if item:
                self._set_stage(item, Stage.FAILED, "המדפסת לא זמינה")
            self.job_failed.emit(msg)
            self.printer_unavailable.emit(job.printer_name)
            return False
        self.jobs.append(job)
        log.info("Queued [%s] %s ×%d (%d waiting)", job.tag or "-",
                 ", ".join(Path(p).name for p in job.photo_paths), job.copies, len(self.jobs))
        if item:
            item.jobs_open += 1
            # waiting behind another job → QUEUED; printer idle → the worker sets the next stage
            # right away (no QUEUED flash on the card)
            if self.worker is not None and not item.stage.busy:
                self._set_stage(item, Stage.QUEUED)
        if self.worker is None:
            self._start_next()
        return True

    # ---------------------------------------------------------------- worker
    def _start_next(self) -> None:
        self.active_job = None
        if not self.jobs:
            if self.worker is not None:
                self.worker = None
                self.busy_changed.emit(False)
            return
        job = self.jobs.popleft()
        w = self._worker_cls(job, self)
        w.status.connect(self.status)
        w.progress.connect(self._on_progress)
        w.succeeded.connect(self._on_succeeded)
        w.failed.connect(self._on_failed)
        w.finished.connect(w.deleteLater)
        w.finished.connect(self._start_next)
        was_idle = self.worker is None
        self.worker, self.active_job = w, job
        item = self.get(job.tag)
        if item:
            self._set_stage(item, Stage.ENHANCING if job.photo_filter else Stage.COMPOSING)
        if was_idle:
            self.busy_changed.emit(True)
        w.start()

    def _on_progress(self, done: int, total: int) -> None:
        self.progress.emit(done, total)
        item = self.get(self.active_job.tag if self.active_job else None)
        if item:
            self._set_stage(item, Stage.COMPOSING if done == 0 else Stage.SPOOLING)

    def _finish_item(self, ok: bool, error: str = "") -> None:
        job = self.active_job
        item = self.get(job.tag if job else None)
        if item is None:
            return
        item.jobs_open = max(0, item.jobs_open - 1)
        if ok:
            item.copies_printed += job.magnet_count()
            self._set_stage(item, Stage.QUEUED if item.jobs_open else Stage.PRINTED)
        else:
            self._set_stage(item, Stage.FAILED, error)

    def _on_succeeded(self, msg: str) -> None:
        n = self.active_job.magnet_count() if self.active_job else 0
        self.session_printed += n
        self.total_printed += n
        self._finish_item(True)
        log.info("Counter: +%d → total %d (session %d)", n, self.total_printed, self.session_printed)
        self.job_succeeded.emit(msg, n)

    def _on_failed(self, msg: str) -> None:
        self._finish_item(False, msg)
        self.job_failed.emit(msg)

    # ---------------------------------------------------------------- shutdown
    def shutdown(self, timeout_ms: int = 5000) -> None:
        """Drop waiting jobs and stop the running one (app closing)."""
        self.jobs.clear()
        w = self.worker
        if w is not None:
            w.cancel()
            w.wait(timeout_ms)
