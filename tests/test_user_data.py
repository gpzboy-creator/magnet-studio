"""Step 4: per-user folders, legacy migration, API key in the keychain, Qt-free core."""
import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


def test_paths_follow_magnetstudio_home(isolated_user_dirs):
    from magnetstudio import paths
    home = isolated_user_dirs
    assert paths.config_dir() == home / "config"
    assert paths.data_dir() == home / "data"
    assert paths.user_templates_dir() == home / "data" / "templates"
    assert paths.user_fonts_dir() == home / "data" / "fonts"
    assert paths.generated_dir() == home / "data" / "_generated"
    assert paths.default_output_dir() == home / "documents" / "output"
    assert paths.resolve_output_dir("") == paths.default_output_dir()
    assert paths.resolve_output_dir("event_x") == home / "documents" / "event_x"
    abs_out = home / "elsewhere"
    assert paths.resolve_output_dir(str(abs_out)) == abs_out
    # bundled resources live inside the package, never under the user folder
    assert paths.BUNDLED_TEMPLATES_DIR.is_relative_to(paths.PACKAGE_DIR)
    assert (paths.BUNDLED_FONTS_DIR / "Heebo-Regular.ttf").exists()


def test_paths_default_to_os_folders(monkeypatch):
    from magnetstudio import paths
    for v in ("MAGNETSTUDIO_HOME", "MAGNETSTUDIO_SETTINGS", "MAGNETSTUDIO_LOG_DIR"):
        monkeypatch.delenv(v, raising=False)
    for d in (paths.config_dir(), paths.data_dir(), paths.log_dir(), paths.documents_dir()):
        assert "MagnetStudio" in str(d)
        assert not d.is_relative_to(paths.PACKAGE_DIR), f"{d} must not be inside the app folder"


@pytest.mark.parametrize("pkg", ["magnetstudio.core", "magnetstudio.generator"])
def test_core_and_generator_import_without_qt(pkg):
    """core/ and generator/ must work in a process where PyQt6 cannot be imported at all."""
    code = textwrap.dedent(f"""
        import importlib, pkgutil, sys
        class BlockQt:
            def find_spec(self, name, path=None, target=None):
                if name == "PyQt6" or name.startswith("PyQt6."):
                    raise ImportError("PyQt6 blocked for this test")
        sys.meta_path.insert(0, BlockQt())
        pkg = importlib.import_module("{pkg}")
        for m in pkgutil.iter_modules(pkg.__path__, "{pkg}."):
            importlib.import_module(m.name)
        assert not any(k.startswith("PyQt6") for k in sys.modules), "PyQt6 got imported"
        print("ok")
    """)
    r = subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True,
                       env=dict(os.environ, PYTHONPATH=str(ROOT)), timeout=60)
    assert r.returncode == 0 and "ok" in r.stdout, r.stderr[-2000:]


def _legacy_tree(root: Path) -> Path:
    (root / "config").mkdir(parents=True)
    (root / "config" / "settings.json").write_text(json.dumps({"frame": None, "copies": 3,
                                                               "gemini_api_key": "legacy-key"}))
    t = root / "assets" / "templates"
    (t / "wedding_dana_assets").mkdir(parents=True)
    (t / "wedding_dana.json").write_text("{}")
    (t / "wedding_dana_assets" / "logo.png").write_bytes(b"png")
    (t / "bar_mitzva.png").write_bytes(b"png")
    (t / "sample_wedding_7.5x10.json").write_text("{}")   # bundled sample – not user data
    (t / "_generated").mkdir()
    (t / "_generated" / "tmp.png").write_bytes(b"png")      # scratch – not user data
    f = root / "assets" / "fonts"
    f.mkdir(parents=True)
    (f / "Heebo-Regular.ttf").write_bytes(b"bundled")
    (f / "MyScript.ttf").write_bytes(b"user font")
    return root


def test_legacy_migration(tmp_path):
    from magnetstudio import paths
    from magnetstudio.core.migrate import migrate_legacy
    from magnetstudio.core.settings import load_settings
    legacy = _legacy_tree(tmp_path / "old_install")

    copied = migrate_legacy(legacy)
    assert len(copied) == 5, copied
    assert load_settings()["copies"] == 3
    ut = paths.user_templates_dir()
    assert {p.name for p in ut.iterdir()} == {"wedding_dana.json", "wedding_dana_assets", "bar_mitzva.png"}
    assert (ut / "wedding_dana_assets" / "logo.png").exists()
    assert [p.name for p in paths.user_fonts_dir().iterdir()] == ["MyScript.ttf"]
    assert (legacy / "config" / "settings.json").exists(), "legacy files are copied, never moved"

    assert migrate_legacy(legacy) == [], "runs once (marker)"
    (paths.config_dir() / ".migrated-from-legacy").unlink()
    paths.settings_file().write_text(json.dumps({"copies": 9}))
    migrate_legacy(legacy)
    assert json.loads(paths.settings_file().read_text())["copies"] == 9, "never overwrites newer data"


def test_api_key_goes_to_keychain(memory_keyring):
    from magnetstudio.core import secrets
    from magnetstudio.core.settings import load_settings, save_settings
    s = load_settings()
    s["gemini_api_key"] = "plain-old-key"
    save_settings(s)

    s = load_settings()
    assert secrets.migrate_plaintext_key(s) is True
    save_settings(s)
    assert load_settings()["gemini_api_key"] == "", "no plain-text copy left in settings.json"
    assert "plain-old-key" not in Path(os.environ["MAGNETSTUDIO_SETTINGS"]).read_text()
    assert secrets.get_api_key(load_settings()) == "plain-old-key"
    assert secrets.migrate_plaintext_key(load_settings()) is False, "nothing left to migrate"

    assert secrets.store_api_key(s, "  new-key ") == "keychain"
    assert secrets.get_api_key(s) == "new-key" and s["gemini_api_key"] == ""
    os.environ["GEMINI_API_KEY"] = "env-key"
    try:
        assert secrets.get_api_key(s) == "env-key", "environment variable wins"
    finally:
        del os.environ["GEMINI_API_KEY"]
    secrets.store_api_key(s, "")
    assert secrets.get_api_key(s) == "" and memory_keyring.store == {}, "empty value deletes the key"


def test_api_key_without_keychain(monkeypatch):
    """Headless Linux / no backend: the key stays in settings.json, the app keeps working."""
    import keyring
    from keyring.backends import fail

    from magnetstudio.core import secrets
    monkeypatch.setattr(keyring, "get_keyring", lambda: fail.Keyring())
    s = {"gemini_api_key": "k1"}
    assert secrets.keyring_available() is False
    assert secrets.migrate_plaintext_key(s) is False and s["gemini_api_key"] == "k1"
    assert secrets.store_api_key(s, "k2") == "settings" and secrets.get_api_key(s) == "k2"


def test_frame_list_merges_user_and_bundled(qapp):
    from magnetstudio import paths
    from magnetstudio.ui.main_window import frame_files
    ut = paths.user_templates_dir()
    ut.mkdir(parents=True)
    bundled = sorted(p.name for p in paths.BUNDLED_TEMPLATES_DIR.glob("*.json"))
    assert bundled, "package ships sample templates"
    (ut / "my_frame.json").write_text("{}")
    (ut / bundled[0]).write_text("{}")          # user copy of a sample overrides it
    (ut / "overlay.png").write_bytes(b"png")
    files = frame_files()
    names = [f.name for f in files]
    assert "my_frame.json" in names and "overlay.png" in names
    assert names.count(bundled[0]) == 1 and next(f for f in files if f.name == bundled[0]).parent == ut
    assert names.index("overlay.png") > max(names.index(n) for n in names if n.endswith(".json"))


def test_generator_scratch_goes_to_user_data():
    from PIL import Image

    from magnetstudio import paths
    from magnetstudio.generator.ornaments import _save_generated
    out = Path(_save_generated(Image.new("RGBA", (10, 10)), "t"))
    assert out.parent == paths.generated_dir() and out.exists()
    assert not out.is_relative_to(paths.PACKAGE_DIR)


def test_designer_never_writes_into_package(qapp):
    from magnetstudio import paths
    from magnetstudio.ui.designer import TemplateDesigner
    sample = next(paths.BUNDLED_TEMPLATES_DIR.glob("sample_*.json"))
    d = TemplateDesigner(profile="7.5x10")
    d.path = sample
    target = d._default_path(".json")
    assert target.parent == paths.user_templates_dir() and target.name == sample.name
    d.path = None
    assert d._default_path(".json").parent == paths.user_templates_dir()
    d.close()
