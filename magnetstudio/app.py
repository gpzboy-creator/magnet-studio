"""MagnetStudio – entry point (python -m magnetstudio, or the `magnetstudio` command)."""
import logging
import os
import signal
import sys

from PyQt6.QtCore import QTimer, QtMsgType, qInstallMessageHandler
from PyQt6.QtWidgets import QApplication

from magnetstudio import __version__
from magnetstudio import paths
from magnetstudio.core.applog import install_exception_hooks, log_startup_banner, setup_logging
from magnetstudio.core.migrate import migrate_legacy
from magnetstudio.core.secrets import migrate_plaintext_key
from magnetstudio.core.settings import load_settings, save_settings, settings_path
from magnetstudio.ui.theme import apply_theme
from magnetstudio.ui.main_window import MainWindow

log = logging.getLogger("magnetstudio")


def _setup_fonts(app) -> None:
    """Register the app fonts with Qt; fetch the Hebrew bundle in the background if there are none."""
    from magnetstudio.core import fonts
    from magnetstudio.services.fonts_qt import FontDownloadWorker, register_qt_fonts
    register_qt_fonts()
    if not fonts.custom_font_families():
        log.info("No app fonts found – downloading the default Hebrew font bundle")
        worker = FontDownloadWorker(app)
        worker.done.connect(lambda new: new and (register_qt_fonts(), _refresh_pickers()))
        worker.start()
        app._font_worker = worker  # keep a reference while it runs


def _refresh_pickers() -> None:
    from magnetstudio.ui.designer import FontPicker
    FontPicker.refresh_all()


_QT_LEVELS = {QtMsgType.QtDebugMsg: logging.DEBUG, QtMsgType.QtInfoMsg: logging.INFO,
              QtMsgType.QtWarningMsg: logging.WARNING, QtMsgType.QtCriticalMsg: logging.ERROR,
              QtMsgType.QtFatalMsg: logging.CRITICAL}
_QT_NOISE = ("propagateSizeHints", "This plugin does not support")


def _qt_message_handler(msg_type, context, message) -> None:
    """Qt's own warnings (printer, fonts, stylesheet) into the log instead of a lost console."""
    if any(n in message for n in _QT_NOISE):
        return
    logging.getLogger("qt").log(_QT_LEVELS.get(msg_type, logging.WARNING), message)


def _install_signal_handlers(app) -> None:
    """Ctrl+C in a terminal / `kill` / logout → close the window normally (settings are saved).
    Qt's event loop never returns to Python on its own, so a short timer lets the handler run."""
    def stop(signum, _frame):
        log.info("Signal %s – closing", signal.Signals(signum).name)
        app.closeAllWindows()
        app.quit()
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, stop)
    timer = QTimer(app)
    timer.timeout.connect(lambda: None)
    timer.start(250)


def _qt_versions() -> str:
    from PyQt6.QtCore import PYQT_VERSION_STR, QT_VERSION_STR
    return f"Qt {QT_VERSION_STR}, PyQt {PYQT_VERSION_STR}"


def _prepare_user_data() -> dict:
    """First-run work before the window: copy data from an old install, keychain the API key."""
    migrate_legacy()
    paths.user_templates_dir().mkdir(parents=True, exist_ok=True)
    settings = load_settings()
    if migrate_plaintext_key(settings):
        save_settings(settings)
    return settings


def main() -> int:
    setup_logging()
    log_startup_banner(__version__, _qt_versions())
    window = None

    def show_error(msg: str) -> None:  # unexpected exception → toast, app keeps running
        if window is not None:
            window.toast.show_message(msg, "error", 6000)

    install_exception_hooks(show_error)
    qInstallMessageHandler(_qt_message_handler)

    app = QApplication(sys.argv)
    app.setApplicationName("MagnetStudio")
    _install_signal_handlers(app)
    _setup_fonts(app)
    apply_theme(app)  # after fonts, so the UI font (Heebo) is available
    log.info("Settings: %s | data: %s", settings_path(), paths.data_dir())
    window = MainWindow(_prepare_user_data())
    if os.environ.get("MAGNETSTUDIO_START_MAXIMIZED"):   # live preview in the browser (.devcontainer)
        window.showMaximized()
    else:
        window.show()
    smoke_ms = os.environ.get("MAGNETSTUDIO_EXIT_AFTER_MS")  # CI smoke test of run.bat / run.sh
    if smoke_ms:
        log.info("Smoke test: closing after %s ms", smoke_ms)
        QTimer.singleShot(int(smoke_ms), lambda: (app.closeAllWindows(), app.quit()))
    code = app.exec()
    log.info("MagnetStudio exiting (code %s)", code)
    return code


if __name__ == "__main__":
    sys.exit(main())
