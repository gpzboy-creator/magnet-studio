"""Application log: rotating file in the user's log folder + crash hooks.

Log folder (MAGNETSTUDIO_LOG_DIR overrides):
  Windows  %LOCALAPPDATA%\\MagnetStudio\\Logs
  macOS    ~/Library/Logs/MagnetStudio            (also visible in Console.app)
  Linux    $XDG_STATE_HOME/MagnetStudio/logs  (~/.local/state/…)

magnetstudio.log rotates at 1 MB, 5 backups kept (≈ 6 MB max).

install_exception_hooks() routes uncaught exceptions (main thread and other threads) to the log.
Without it, PyQt6 aborts the whole app on an exception inside a slot – mid-event that means a
closed app and a lost queue; with it, the error is logged and the app keeps running.
"""
from __future__ import annotations

import logging
import logging.handlers
import os
import platform
import sys
import threading
from pathlib import Path
from typing import Callable

LOG_NAME = "magnetstudio.log"
MAX_BYTES = 1_000_000
BACKUPS = 5
FORMAT = "%(asctime)s %(levelname)-7s %(name)s: %(message)s"

_file_handler: logging.Handler | None = None


def log_dir() -> Path:
    env = os.environ.get("MAGNETSTUDIO_LOG_DIR")
    if env:
        return Path(env)
    home = Path.home()
    if sys.platform == "win32":
        return Path(os.environ.get("LOCALAPPDATA", home / "AppData" / "Local")) / "MagnetStudio" / "Logs"
    if sys.platform == "darwin":
        return home / "Library" / "Logs" / "MagnetStudio"
    return Path(os.environ.get("XDG_STATE_HOME", home / ".local" / "state")) / "MagnetStudio" / "logs"


def log_file() -> Path:
    return log_dir() / LOG_NAME


def setup_logging(level: int = logging.INFO, directory: Path | None = None, console: bool = True) -> Path:
    """Configure the root logger once (idempotent). Returns the log file path.
    If the folder can't be created, logs go to the console only – the app still starts."""
    global _file_handler
    root = logging.getLogger()
    root.setLevel(level)
    fmt = logging.Formatter(FORMAT)
    path = (Path(directory) if directory else log_dir()) / LOG_NAME

    if _file_handler is not None:  # re-setup (e.g. tests pointing at another folder)
        root.removeHandler(_file_handler)
        _file_handler.close()
        _file_handler = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        _file_handler = logging.handlers.RotatingFileHandler(path, maxBytes=MAX_BYTES, backupCount=BACKUPS,
                                                             encoding="utf-8", delay=False)
        _file_handler.setFormatter(fmt)
        root.addHandler(_file_handler)
    except OSError as e:
        print(f"MagnetStudio: cannot write log file {path}: {e}", file=sys.stderr)

    if console and not any(getattr(h, "_magnet_console", False) for h in root.handlers):
        ch = logging.StreamHandler(sys.stderr)
        ch.setLevel(logging.WARNING)
        ch.setFormatter(fmt)
        ch._magnet_console = True  # type: ignore[attr-defined]
        root.addHandler(ch)

    for noisy in ("watchdog", "PIL", "urllib3", "httpx", "httpcore", "google_genai"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    return path


def log_startup_banner(version: str = "") -> None:
    log = logging.getLogger("magnetstudio")
    log.info("=" * 60)
    log.info("MagnetStudio %s starting – Python %s, %s %s", version, platform.python_version(),
             platform.system(), platform.release())
    try:
        from PyQt6.QtCore import PYQT_VERSION_STR, QT_VERSION_STR
        from PIL import __version__ as pil_version
        log.info("PyQt6 %s / Qt %s / Pillow %s", PYQT_VERSION_STR, QT_VERSION_STR, pil_version)
    except Exception:  # noqa: BLE001 – banner must never fail
        pass
    log.info("Log file: %s", log_file())


def install_exception_hooks(on_error: Callable[[str], None] | None = None) -> None:
    """Log uncaught exceptions instead of crashing. on_error(short message) may show a toast."""
    log = logging.getLogger("magnetstudio.crash")

    def notify(exc: BaseException) -> None:
        if on_error is not None:
            try:
                on_error(f"שגיאה לא צפויה: {exc}")
            except Exception:  # noqa: BLE001
                pass

    def excepthook(exc_type, exc, tb):
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc, tb)
            return
        log.critical("Uncaught exception", exc_info=(exc_type, exc, tb))
        notify(exc)

    def thread_hook(args: threading.ExceptHookArgs) -> None:
        if args.exc_type is SystemExit:
            return
        name = args.thread.name if args.thread else "?"
        log.critical("Uncaught exception in thread %s", name,
                     exc_info=(args.exc_type, args.exc_value, args.exc_traceback))

    sys.excepthook = excepthook
    threading.excepthook = thread_hook
