"""ThumbnailRenderer – renders the photo grid's "finished magnet" thumbnails off the GUI thread.

One worker thread, a newest-first request list per card. A generation number invalidates old work:
when the frame, size or sliders change, the window bumps the generation and re-requests every card;
results from the previous generation are dropped.
"""
from __future__ import annotations

import logging
import threading
from dataclasses import dataclass

from PIL.ImageQt import ImageQt
from PyQt6.QtCore import QThread, pyqtSignal
from PyQt6.QtGui import QImage

from magnetstudio.core.framer import render_magnet_preview

log = logging.getLogger(__name__)


@dataclass
class ThumbParams:
    size_key: str
    frame_path: str | None = None
    frame_landscape: str | None = None
    photo_filter: object = None
    max_side: int = 420


# Running renderers are kept alive here: Qt aborts the process if a QThread object is destroyed while
# its thread still runs (e.g. a window that is dropped without close()).
_RUNNING: set["ThumbnailRenderer"] = set()


class ThumbnailRenderer(QThread):
    ready = pyqtSignal(str, int, QImage)     # item id, generation, image
    failed = pyqtSignal(str, str)            # item id, message

    IDLE_EXIT_S = 1.5      # the thread ends when idle, so it is never left running on its own

    def __init__(self, parent=None):
        super().__init__(None)              # not owned by the window – see _RUNNING
        self.started.connect(lambda: _RUNNING.add(self))
        self._lock = threading.Condition()
        self._todo: dict[str, tuple[int, str, ThumbParams]] = {}
        self._stop = False
        self.generation = 0
        # work that arrived while the thread was finishing → start again
        self.finished.connect(self._restart_if_needed)

    def request(self, item_id: str, path: str, params: ThumbParams) -> None:
        with self._lock:
            self._todo[item_id] = (self.generation, path, params)
            self._lock.notify()
        if not self.isRunning():
            _RUNNING.add(self)
            self.start(QThread.Priority.LowPriority)

    def invalidate(self) -> int:
        """New generation: queued and in-flight work for older settings is dropped."""
        with self._lock:
            self.generation += 1
            self._todo.clear()
            return self.generation

    def stop(self) -> None:
        with self._lock:
            self._stop = True
            self._lock.notify()
        self.wait(3000)

    def _restart_if_needed(self) -> None:
        _RUNNING.discard(self)
        with self._lock:
            pending = bool(self._todo) and not self._stop
        if pending:
            _RUNNING.add(self)
            self.start(QThread.Priority.LowPriority)

    def run(self) -> None:
        while True:
            with self._lock:
                if not self._todo and not self._stop:
                    self._lock.wait(self.IDLE_EXIT_S)
                if self._stop or not self._todo:
                    return
                item_id = next(iter(self._todo))
                gen, path, params = self._todo.pop(item_id)
            try:
                img = render_magnet_preview(path, params.size_key, params.frame_path, params.photo_filter,
                                            params.frame_landscape, params.max_side)
                self.ready.emit(item_id, gen, QImage(ImageQt(img.convert("RGB"))).copy())
            except Exception as e:  # noqa: BLE001 – a bad file must not stop the other thumbnails
                log.warning("Thumbnail failed for %s: %s", path, e)
                self.failed.emit(item_id, str(e))
