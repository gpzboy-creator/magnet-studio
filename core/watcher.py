"""Watch an input folder and report new images (event mode)."""
import logging
import time
from pathlib import Path
from typing import Callable

from watchdog.events import FileSystemEvent, FileSystemEventHandler
from watchdog.observers import Observer

log = logging.getLogger(__name__)

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".heic", ".webp"}


class _NewImageHandler(FileSystemEventHandler):
    def __init__(self, callback: Callable[[Path], None]):
        self.callback = callback

    def on_created(self, event: FileSystemEvent) -> None:
        path = Path(str(event.src_path))
        if not event.is_directory and path.suffix.lower() in IMAGE_EXTS:
            _wait_until_stable(path)
            log.info("Hot folder: new file %s", path.name)
            self.callback(path)


def _wait_until_stable(path: Path, timeout: float = 10.0) -> None:
    """Wait until the file stops growing (still being copied)."""
    last, start = -1, time.time()
    while time.time() - start < timeout:
        try:
            size = path.stat().st_size
        except FileNotFoundError:
            return
        if size == last and size > 0:
            return
        last = size
        time.sleep(0.3)
    log.warning("Hot folder: %s still changing after %.0fs – processing anyway", path.name, timeout)


class FolderWatcher:
    def __init__(self, folder: str | Path, callback: Callable[[Path], None]):
        self.folder = Path(folder)
        self._observer = Observer()
        self._observer.schedule(_NewImageHandler(callback), str(self.folder), recursive=False)

    def start(self) -> None:
        self.folder.mkdir(parents=True, exist_ok=True)
        self._observer.start()
        log.info("Hot folder watching %s", self.folder)

    def stop(self) -> None:
        self._observer.stop()
        self._observer.join()
