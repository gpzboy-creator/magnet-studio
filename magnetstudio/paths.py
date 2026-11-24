"""Where things live. Every file path in the app comes from here.

Bundled, read-only resources (fonts, sample templates, icons) live inside the package, so they
are found the same way when running from source, from a pip install or from a PyInstaller build.
"""
from __future__ import annotations

import sys
from pathlib import Path

PACKAGE_DIR = Path(__file__).resolve().parent


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

# Legacy (pre-package) settings location: <repo>/config/settings.json
LEGACY_SETTINGS = PACKAGE_DIR.parent / "config" / "settings.json"
