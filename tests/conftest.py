"""pytest setup shared by every test.

- Qt runs offscreen (no display needed – CI, cloud, SSH).
- Each test gets its own settings file, log folder and user-data folder, so a test can never
  touch the real settings / templates / log of the person running it.
- The OS keychain is replaced by an in-memory one, so no test reads or writes a real API key.
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


class MemoryKeyring:
    """Minimal keyring backend kept in a dict (installed for every test)."""
    priority = 1

    def __init__(self):
        self.store: dict[tuple[str, str], str] = {}

    def get_password(self, service, user):
        return self.store.get((service, user))

    def set_password(self, service, user, password):
        self.store[(service, user)] = password

    def delete_password(self, service, user):
        import keyring.errors
        if self.store.pop((service, user), None) is None:
            raise keyring.errors.PasswordDeleteError(user)


@pytest.fixture(autouse=True)
def memory_keyring(monkeypatch):
    import keyring
    from keyring.backend import KeyringBackend

    class _Backend(MemoryKeyring, KeyringBackend):
        pass

    kr = _Backend()
    monkeypatch.setattr(keyring, "get_keyring", lambda: kr)
    monkeypatch.setattr(keyring, "get_password", kr.get_password)
    monkeypatch.setattr(keyring, "set_password", kr.set_password)
    monkeypatch.setattr(keyring, "delete_password", kr.delete_password)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    yield kr
