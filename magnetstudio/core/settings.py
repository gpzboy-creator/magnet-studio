"""Load and save app settings (config/settings.json).

- Atomic save: write to a temp file in the same folder, fsync, then os.replace(). A crash or power
  cut mid-write leaves either the old file or the new one – never a half-written / empty file.
- Safe load: a corrupt file is kept aside as settings.json.corrupt-<time> and defaults are used,
  instead of the app refusing to start.
- MAGNETSTUDIO_SETTINGS (env var) points to another file – used by the tests so they never touch
  the real settings.
"""
import json
import logging
import os
import tempfile
import time
from pathlib import Path

log = logging.getLogger(__name__)

from magnetstudio.paths import BUNDLED_TEMPLATES_DIR, LEGACY_SETTINGS

ROOT = LEGACY_SETTINGS.parent.parent          # repo root (output/ lives here for now)
SETTINGS_PATH = LEGACY_SETTINGS
TEMPLATES_DIR = BUNDLED_TEMPLATES_DIR

DEFAULTS = {
    "magnet_size": "7.5x10",
    "print_mode": "thermal",
    "frame": None,
    "watch_folder": "",
    "output_folder": "output",
    "thermal_printer": "",
    "a4_printer": "",
    "a4_margin_cm": 0.3,
    "a4_gap_cm": 0.2,
    "crop_marks": True,
    "enhance": False,            # Fast AI Enhancer (local LUT) before framing
    "enhance_preset": "dye_sub",
    "cloud_style": None,         # optional Gemini style, e.g. "print_ready"
    "gemini_model": "gemini-3.1-flash-image",
    "gemini_api_key": "",        # or env var GEMINI_API_KEY
    "gemini_text_model": "gemini-3.8-flash",       # frame generator – Structured Output
    "gemini_art_model": "gemini-3.1-flash-image",  # frame generator – background art
    "photographer_credit": "שחר לוי גונן | 0525860073",  # vertical credit on generated frames
}


def settings_path() -> Path:
    """The settings file in use (MAGNETSTUDIO_SETTINGS overrides the default)."""
    env = os.environ.get("MAGNETSTUDIO_SETTINGS")
    return Path(env) if env else SETTINGS_PATH


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
