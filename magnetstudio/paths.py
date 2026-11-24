"""Where things live. Every file path in the app comes from here.

Two kinds of locations:

1. Bundled, read-only resources (fonts, sample templates, icons) – inside the package, so they are
   found the same way from source, from a pip install and from a PyInstaller build (sys._MEIPASS).
   The app never writes there: an installed app folder is usually not writable (Program Files,
   a signed .app bundle) and an update would wipe anything written into it.

2. Per-user, writable data – in the OS-standard folders (via platformdirs):

                 Windows                               macOS
   settings      %LOCALAPPDATA%\\MagnetStudio            ~/Library/Application Support/MagnetStudio
   templates,    %LOCALAPPDATA%\\MagnetStudio\\data       ~/Library/Application Support/MagnetStudio/data
   fonts
   logs          %LOCALAPPDATA%\\MagnetStudio\\Logs       ~/Library/Logs/MagnetStudio
   print output  Documents\\MagnetStudio                 ~/Documents/MagnetStudio

   MAGNETSTUDIO_HOME=<folder> puts all of them under one folder (tests, portable USB installs).
   MAGNETSTUDIO_SETTINGS / MAGNETSTUDIO_LOG_DIR override single locations.

Everything is a function (not a constant) so the environment is read at call time.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import platformdirs

APP_NAME = "MagnetStudio"
PACKAGE_DIR = Path(__file__).resolve().parent


# ---------------------------------------------------------------- bundled (read-only)

def resource_dir() -> Path:
    """Package folder with the bundled assets (PyInstaller unpacks it under sys._MEIPASS)."""
    base = getattr(sys, "_MEIPASS", None)
    if getattr(sys, "frozen", False) and base:
        return Path(base) / "magnetstudio"
    return PACKAGE_DIR


ASSETS_DIR = resource_dir() / "assets"
BUNDLED_FONTS_DIR = ASSETS_DIR / "fonts"
BUNDLED_TEMPLATES_DIR = ASSETS_DIR / "templates"
UI_ICONS_DIR = ASSETS_DIR / "ui"

# Pre-package source checkouts kept settings in <repo>/config/settings.json and user templates /
# fonts inside assets/. migrate.py copies them to the user folders once.
LEGACY_SETTINGS = PACKAGE_DIR.parent / "config" / "settings.json"


# ---------------------------------------------------------------- per-user (writable)

def _home() -> Path | None:
    env = os.environ.get("MAGNETSTUDIO_HOME")
    return Path(env) if env else None


def config_dir() -> Path:
    home = _home()
    return home / "config" if home else Path(platformdirs.user_config_dir(APP_NAME, appauthor=False))


def data_dir() -> Path:
    home = _home()
    return home / "data" if home else Path(platformdirs.user_data_dir(APP_NAME, appauthor=False)) / "data"


def log_dir() -> Path:
    env = os.environ.get("MAGNETSTUDIO_LOG_DIR")
    if env:
        return Path(env)
    home = _home()
    return home / "logs" if home else Path(platformdirs.user_log_dir(APP_NAME, appauthor=False))


def documents_dir() -> Path:
    """Where print files / PDF test prints go – a folder the photographer can find."""
    home = _home()
    return home / "documents" if home else Path(platformdirs.user_documents_dir()) / APP_NAME


def settings_file() -> Path:
    env = os.environ.get("MAGNETSTUDIO_SETTINGS")
    return Path(env) if env else config_dir() / "settings.json"


def user_templates_dir() -> Path:
    return data_dir() / "templates"


def user_fonts_dir() -> Path:
    return data_dir() / "fonts"


def generated_dir() -> Path:
    """Scratch layers made by the frame generator (copied next to a template when it is saved)."""
    return data_dir() / "_generated"


def default_output_dir() -> Path:
    return documents_dir() / "output"


def resolve_output_dir(setting: str | None) -> Path:
    """The output_folder setting: absolute path as is, relative → under the documents folder."""
    if not setting:
        return default_output_dir()
    p = Path(setting).expanduser()
    return p if p.is_absolute() else documents_dir() / p


def template_dirs() -> list[Path]:
    """Folders searched for frames: the user's own first (they win on equal names), then bundled."""
    return [user_templates_dir(), BUNDLED_TEMPLATES_DIR]
