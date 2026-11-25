"""Load and save app settings (settings.json in the user's config folder – see paths.py).

- Atomic save: write to a temp file in the same folder, fsync, then os.replace(). A crash or power
  cut mid-write leaves either the old file or the new one – never a half-written / empty file.
- Safe load: a corrupt file is kept aside as settings.json.corrupt-<time> and defaults are used,
  instead of the app refusing to start.
- MAGNETSTUDIO_SETTINGS / MAGNETSTUDIO_HOME (env vars) point elsewhere – used by the tests so they
  never touch the real settings.
- The Gemini API key is NOT stored here any more – see core/secrets.py (OS keychain).
"""
import json
import logging
import os
import tempfile
import time
from pathlib import Path

log = logging.getLogger(__name__)

from magnetstudio import paths

DEFAULTS = {
    "magnet_size": "7.5x10",
    "print_mode": "sheet",       # sheet (rows × cols on paper) · thermal (magnet per page) · a4
    "frame": None,
    "frame_landscape": None,     # PNG frame for landscape photos ("frame" = portrait / JSON)
    "sheet_printer": "",
    "paper": "15x20",            # 15x20 = 6x8" (Mitsubishi CP-D80DW and other dye-sub printers)
    "sheet_rows": 2,
    "sheet_cols": 2,
    "sheet_margins_mm": [1.5, 1.5, 1.5, 1.5],   # top, bottom, right, left
    "mark_width": "medium",
    "theme_mode": "auto",        # auto (follow Windows/macOS) · light · dark
    "exposure": 0,               # global sliders, −100…100
    "contrast": 0,
    "sharpness": 0,
    "cost_per_sheet": 0.0,       # event cost tracking (MagnetOti-style)
    "event_sheets": 0,           # sheets printed since "reset event"
    "event_cost": 0.0,
    "today_date": "",
    "today_sheets": 0,
    "watch_folder": "",
    "output_folder": "",         # "" = Documents/MagnetStudio/output (paths.resolve_output_dir)
    "thermal_printer": "",
    "a4_printer": "",
    "a4_margin_cm": 0.3,
    "a4_gap_cm": 0.2,
    "crop_marks": False,
    "enhance": False,            # Fast AI Enhancer (local LUT) before framing
    "enhance_preset": "dye_sub",
    "cloud_style": None,         # optional Gemini style, e.g. "print_ready"
    "gemini_model": "gemini-3.1-flash-image",
    "gemini_api_key": "",        # legacy only – moved to the OS keychain on first start
    "gemini_text_model": "gemini-3.8-flash",       # frame generator – Structured Output
    "gemini_art_model": "gemini-3.1-flash-image",  # frame generator – background art
    "photographer_credit": "שחר לוי גונן | 0525860073",  # vertical credit on generated frames
}


def settings_path() -> Path:
    """The settings file in use."""
    return paths.settings_file()


def load_settings(path: Path | None = None) -> dict:
    path = Path(path) if path else settings_path()
    data = dict(DEFAULTS)
    if not path.exists():
        return data
    try:
        stored = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(stored, dict):
            raise ValueError("settings file is not a JSON object")
        data.update(stored)
    except (OSError, ValueError) as e:  # JSONDecodeError is a ValueError
        backup = path.with_name(f"{path.name}.corrupt-{time.strftime('%Y%m%d-%H%M%S')}")
        try:
            path.replace(backup)
        except OSError:
            backup = None
        log.error("Settings file unreadable (%s) – using defaults; kept as %s", e, backup)
    return data


def save_settings(settings: dict, path: Path | None = None) -> bool:
    """Atomically write settings. Returns False (and logs) instead of raising on failure."""
    path = Path(path) if path else settings_path()
    tmp_name = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(settings, indent=2, ensure_ascii=False)
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, prefix=f".{path.name}.",
                                         suffix=".tmp", delete=False) as f:
            tmp_name = f.name
            f.write(payload)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_name, path)  # atomic on Windows and POSIX (same folder)
        return True
    except (OSError, TypeError, ValueError) as e:
        log.error("Could not save settings to %s: %s", path, e)
        if tmp_name:
            try:
                os.unlink(tmp_name)
            except OSError:
                pass
        return False
