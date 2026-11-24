"""pytest setup shared by every test.

- Qt runs offscreen (no display needed – CI, cloud, SSH).
- Each test gets its own settings file, log folder and user-data folder, so a test can never
  touch the real settings / templates / log of the person running it.
"""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402


@pytest.fixture(autouse=True)
def isolated_user_dirs(tmp_path, monkeypatch):
    home = tmp_path / "magnetstudio_home"
    monkeypatch.setenv("MAGNETSTUDIO_HOME", str(home))
    monkeypatch.setenv("MAGNETSTUDIO_SETTINGS", str(home / "config" / "settings.json"))
    monkeypatch.setenv("MAGNETSTUDIO_LOG_DIR", str(home / "logs"))
    yield home


@pytest.fixture(scope="session")
def qapp():
    from PyQt6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])
