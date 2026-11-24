"""MagnetStudio – entry point (python -m magnetstudio, or the `magnetstudio` command)."""
import logging
import sys

from PyQt6.QtCore import QtMsgType, qInstallMessageHandler
from PyQt6.QtWidgets import QApplication

from magnetstudio import __version__
from magnetstudio.core.applog import install_exception_hooks, log_startup_banner, setup_logging
from magnetstudio.core.settings import load_settings, settings_path
from magnetstudio.ui.theme import apply_theme
from magnetstudio.ui.main_window import MainWindow

log = logging.getLogger("magnetstudio")


def _setup_fonts(app) -> None:
    """Register assets/fonts with Qt; fetch the Hebrew bundle in the background if empty."""
    from magnetstudio.core import fonts
    fonts.register_qt_fonts()
    if not fonts.custom_font_families() and fonts.FontDownloadWorker is not None:
        log.info("assets/fonts is empty – downloading the default Hebrew font bundle")
        worker = fonts.FontDownloadWorker(app)
        worker.done.connect(lambda new: new and (fonts.register_qt_fonts(), _refresh_pickers()))
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


def main() -> int:
    setup_logging()
    log_startup_banner(__version__)
    window = None

    def show_error(msg: str) -> None:  # unexpected exception → toast, app keeps running
        if window is not None:
            window.toast.show_message(msg, "error", 6000)

    install_exception_hooks(show_error)
    qInstallMessageHandler(_qt_message_handler)

    app = QApplication(sys.argv)
    app.setApplicationName("MagnetStudio")
    _setup_fonts(app)
    apply_theme(app)  # after fonts, so the UI font (Heebo) is available
    log.info("Settings: %s", settings_path())
    window = MainWindow(load_settings())
    window.show()
    code = app.exec()
    log.info("MagnetStudio exiting (code %s)", code)
    return code


if __name__ == "__main__":
    sys.exit(main())
