"""Print enhancement: a super-fast local LUT (default) + optional Gemini cloud styles.

Local path ("Fast AI Enhancer") – two C-level passes, no Python per-pixel work:
    1. saturation: one RGB→RGB matrix convert (scales chroma around Rec.601 luma)
    2. tone: ONE Image.point() with a 768-entry LUT – shadow lift, midtone gamma,
       gentle contrast, black/white output limits (Dye-Sub prints run darker & flatter)
    In the app it runs after fit_to_size (print resolution): ~30 ms for 15x20 cm.

Cloud path (optional, needs GEMINI_API_KEY + internet)
    Sends the image to a Gemini image model with a style prompt. Any failure
    (no key, offline, timeout, bad response) falls back to the local LUT automatically.

All outputs carry dpi=(300, 300).
"""
from __future__ import annotations

import base64
import logging
import io
import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass
from functools import lru_cache

from PIL import Image

from magnetstudio.core.sizes import DPI

log = logging.getLogger(__name__)

DEFAULT_GEMINI_MODEL = "gemini-3.1-flash-image"   # configurable in settings
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"


# ============================================================== local LUT

@dataclass(frozen=True)
class EnhanceParams:
    shadows: float = 0.25      # 0..1  lift dark tones (peak boost around 1/3 luma)
    gamma: float = 1.05        # >1 brightens midtones
    contrast: float = 1.05     # S-curve strength around mid-grey
    saturation: float = 1.15   # chroma multiplier
    black_out: int = 6         # darkest output level (avoid crushed blacks on dye-sub)
    white_out: int = 252       # brightest output level (keep a hint of detail in highlights)


PRESETS: dict[str, EnhanceParams] = {
    "dye_sub": EnhanceParams(),                                                     # default for DNP/Citizen
    "natural": EnhanceParams(shadows=0.12, gamma=1.02, contrast=1.0, saturation=1.05, black_out=3, white_out=254),
    "vivid": EnhanceParams(shadows=0.2, gamma=1.04, contrast=1.1, saturation=1.3),
    "night_event": EnhanceParams(shadows=0.45, gamma=1.12, contrast=1.02, saturation=1.12, black_out=8),
}

PRESET_LABELS = {
    "dye_sub": "הדפסת Dye-Sub (ברירת מחדל)",
    "natural": "טבעי",
    "vivid": "חי ורווי",
    "night_event": "אירוע ערב / תאורה חלשה",
}


def _clamp(v: float) -> int:
    return 0 if v < 0 else 255 if v > 255 else int(round(v))


@lru_cache(maxsize=32)
def build_lut(p: EnhanceParams) -> tuple[int, ...]:
    """768-entry RGB LUT (same tone curve on R, G, B). Cached per parameter set."""
    y_lut = []
    span = p.white_out - p.black_out
    for i in range(256):
        x = i / 255
        x = x + p.shadows * 3 * x * (1 - x) ** 2           # shadow lift, 0 and 1 stay fixed
        x = x ** (1 / p.gamma)                              # midtones
        x = 0.5 + (x - 0.5) * p.contrast                    # contrast around mid grey
        x = min(1.0, max(0.0, x))
        y_lut.append(_clamp(p.black_out + x * span))
    return tuple(y_lut * 3)


@lru_cache(maxsize=32)
def saturation_matrix(s: float) -> tuple[float, ...]:
    """12-value RGB→RGB matrix that scales chroma by `s` while keeping luma."""
    wr, wg, wb = 0.299, 0.587, 0.114
    k = 1 - s
    return (wr * k + s, wg * k, wb * k, 0.0,
            wr * k, wg * k + s, wb * k, 0.0,
            wr * k, wg * k, wb * k + s, 0.0)


def enhance_local(img: Image.Image, preset: str | EnhanceParams = "dye_sub") -> Image.Image:
    """Fast local enhancement. Returns a new RGB image with dpi=(300, 300)."""
    params = preset if isinstance(preset, EnhanceParams) else PRESETS.get(preset, PRESETS["dye_sub"])
    src = img if img.mode == "RGB" else img.convert("RGB")
    if abs(params.saturation - 1.0) > 1e-3:
        src = src.convert("RGB", saturation_matrix(params.saturation))
    out = src.point(build_lut(params))
    out.info["dpi"] = (DPI, DPI)
    return out


# ============================================================== cloud (Gemini)

CLOUD_STYLES = {
    "print_ready": "Improve this photo for printing on a dye-sublimation photo printer: brighten faces and "
                   "shadows, natural skin tones, slightly richer colors, keep it realistic. Do not add, remove "
                   "or change any people, objects or text. Keep the exact framing.",
    "warm_party": "Give this event photo a warm, flattering party look with soft glow, lifted shadows and "
                  "pleasant skin tones. Do not change people, faces, objects or framing.",
    "bw_classic": "Convert this photo to a classic high-quality black and white print with rich tonal range. "
                  "Do not change people, faces, objects or framing.",
}


class CloudUnavailable(RuntimeError):
    pass


def get_api_key(settings: dict | None = None) -> str:
    return ((settings or {}).get("gemini_api_key") or os.environ.get("GEMINI_API_KEY") or "").strip()


def enhance_cloud(img: Image.Image, api_key: str, style: str = "print_ready",
                  model: str = DEFAULT_GEMINI_MODEL, timeout: float = 25.0) -> Image.Image:
    """Gemini image edit. Raises CloudUnavailable on any failure."""
    if not api_key:
        raise CloudUnavailable("לא הוגדר GEMINI_API_KEY")
    buf = io.BytesIO()
    img.convert("RGB").save(buf, "JPEG", quality=92)
    body = {
        "contents": [{"parts": [
            {"text": CLOUD_STYLES.get(style, style)},
            {"inline_data": {"mime_type": "image/jpeg", "data": base64.b64encode(buf.getvalue()).decode()}},
        ]}],
        "generationConfig": {"responseModalities": ["IMAGE"]},
    }
    req = urllib.request.Request(GEMINI_URL.format(model=model), data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json", "x-goog-api-key": api_key},
                                 method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read())
    except urllib.error.HTTPError as e:
        raise CloudUnavailable(f"Gemini HTTP {e.code}") from e
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise CloudUnavailable(f"אין חיבור לענן ({e})") from e

    for cand in data.get("candidates", []):
        for part in cand.get("content", {}).get("parts", []):
            inline = part.get("inline_data") or part.get("inlineData")
            if inline and inline.get("data"):
                out = Image.open(io.BytesIO(base64.b64decode(inline["data"]))).convert("RGB")
                if out.size != img.size:  # cloud models return ~1–2K; restore print size
                    out = out.resize(img.size, Image.Resampling.LANCZOS)
                out.info["dpi"] = (DPI, DPI)
                return out
    raise CloudUnavailable("Gemini לא החזיר תמונה")


def enhance(img: Image.Image, preset: str = "dye_sub", cloud_style: str | None = None,
            api_key: str = "", model: str = DEFAULT_GEMINI_MODEL) -> tuple[Image.Image, str]:
    """Cloud style if requested and reachable, otherwise the local LUT.
    Returns (image, engine) where engine is 'cloud' or 'local' (or 'local-fallback')."""
    if cloud_style:
        try:
            return enhance_cloud(img, api_key, cloud_style, model), "cloud"
        except CloudUnavailable as e:
            log.warning("Cloud enhance (%s) unavailable – local LUT used: %s", cloud_style, e)
            return enhance_local(img, preset), "local-fallback"
    return enhance_local(img, preset), "local"


# ============================================================== worker (Qt)

try:
    from PyQt6.QtCore import QThread, pyqtSignal

    class EnhancementWorker(QThread):
        """Enhances images off the GUI thread. Emits (index, image, engine) per image."""
        enhanced = pyqtSignal(int, object, str)
        fallback = pyqtSignal(str)        # reason the cloud call failed
        failed = pyqtSignal(str)

        def __init__(self, images: list[Image.Image], preset: str = "dye_sub",
                     cloud_style: str | None = None, api_key: str = "",
                     model: str = DEFAULT_GEMINI_MODEL, parent=None):
            super().__init__(parent)
            self.images, self.preset = images, preset
            self.cloud_style, self.api_key, self.model = cloud_style, api_key, model

        def run(self) -> None:
            for i, img in enumerate(self.images):
                try:
                    if self.cloud_style:
                        try:
                            self.enhanced.emit(i, enhance_cloud(img, self.api_key, self.cloud_style,
                                                                self.model), "cloud")
                            continue
                        except CloudUnavailable as e:
                            log.warning("Cloud enhance unavailable – rest of batch local: %s", e)
                            self.fallback.emit(str(e))
                            self.cloud_style = None  # stay local for the rest of this batch
                    self.enhanced.emit(i, enhance_local(img, self.preset), "local")
                except Exception as e:
                    self.failed.emit(f"שיפור תמונה נכשל: {e}")
except ImportError:  # core stays usable without Qt (scripts, tests)
    EnhancementWorker = None  # type: ignore[assignment]
