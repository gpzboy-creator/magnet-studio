"""One-time move of data from the pre-package layout to the per-user folders.

Older versions kept everything next to the code:
  config/settings.json            → <config dir>/settings.json
  assets/templates/<user files>   → <data dir>/templates/      (the bundled samples stay bundled)
  assets/fonts/<user-added fonts> → <data dir>/fonts/          (the bundled fonts stay bundled)

Files are copied, never moved or deleted, and nothing that already exists is overwritten,
so running it again is harmless. A marker file records that it ran.
"""
from __future__ import annotations

import logging
import shutil
from pathlib import Path

from magnetstudio import paths

log = logging.getLogger(__name__)

MARKER = ".migrated-from-legacy"
BUNDLED_FONTS = {"Heebo-Regular.ttf", "Heebo-Bold.ttf", "Assistant-Regular.ttf", "Assistant-Bold.ttf",
                 "Rubik-Regular.ttf", "Rubik-Bold.ttf", "VarelaRound-Regular.ttf"}
BUNDLED_TEMPLATE_PREFIX = "sample_"


def _copy(src: Path, dst: Path) -> bool:
    if dst.exists():
        return False
    dst.parent.mkdir(parents=True, exist_ok=True)
    if src.is_dir():
        shutil.copytree(src, dst)
    else:
        shutil.copy2(src, dst)
    return True


def migrate_legacy(legacy_root: Path | None = None) -> list[str]:
    """Copy legacy data into the user folders. Returns what was copied (for the log / tests)."""
    root = Path(legacy_root) if legacy_root else paths.LEGACY_SETTINGS.parent.parent
    marker = paths.config_dir() / MARKER
    if marker.exists():
        return []
    copied: list[str] = []
    try:
        legacy_settings = root / "config" / "settings.json"
        if legacy_settings.is_file() and _copy(legacy_settings, paths.settings_file()):
            copied.append(f"settings: {legacy_settings}")

        for tdir in (root / "assets" / "templates", root / "magnetstudio" / "assets" / "templates"):
            if not tdir.is_dir():
                continue
            for item in tdir.iterdir():
                if item.name.startswith((BUNDLED_TEMPLATE_PREFIX, "_", ".")) or item.name == "README.md":
                    continue
                if item.suffix.lower() in (".json", ".png") or item.name.endswith("_assets"):
                    if _copy(item, paths.user_templates_dir() / item.name):
                        copied.append(f"template: {item.name}")

        for fdir in (root / "assets" / "fonts", root / "magnetstudio" / "assets" / "fonts"):
            if not fdir.is_dir():
                continue
            for f in fdir.iterdir():
                if f.suffix.lower() in (".ttf", ".otf") and f.name not in BUNDLED_FONTS:
                    if _copy(f, paths.user_fonts_dir() / f.name):
                        copied.append(f"font: {f.name}")

        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text("\n".join(copied) or "nothing to migrate", encoding="utf-8")
    except OSError as e:  # never block startup – try again next time
        log.error("Migration from %s failed: %s", root, e)
        return copied
    for c in copied:
        log.info("Migrated %s", c)
    return copied
