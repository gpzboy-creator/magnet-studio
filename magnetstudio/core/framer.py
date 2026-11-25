"""Apply a frame to a photo: either a ready PNG overlay or a JSON template."""
from pathlib import Path
from typing import Callable

from PIL import Image

from magnetstudio.core.image_processor import fit_to_size, load_image
from magnetstudio.core.sizes import DPI, get_size

PhotoFilter = Callable[[Image.Image], Image.Image]


def apply_frame(photo: Image.Image, frame_path: str | Path | None) -> Image.Image:
    """Composite a PNG frame (RGBA, same size as the photo) on top of the photo."""
    if not frame_path:
        return photo
    frame = Image.open(frame_path).convert("RGBA")
    if frame.size != photo.size:
        frame = frame.resize(photo.size, Image.Resampling.LANCZOS)
    base = photo.convert("RGBA")
    base.alpha_composite(frame)
    out = base.convert("RGB")
    out.info["dpi"] = (DPI, DPI)
    return out


def is_template(frame_path: str | Path | None) -> bool:
    return bool(frame_path) and Path(frame_path).suffix.lower() == ".json"


def render_magnet(photo_paths: list[str | Path] | str | Path, size_key: str,
                  frame_path: str | Path | None = None,
                  photo_filter: PhotoFilter | None = None,
                  frame_landscape: str | Path | None = None) -> Image.Image:
    """Photo(s) → finished magnet.

    Order: load → fit/crop to print size → photo_filter (enhancer) → frame on top.
    PNG frame / no frame: first photo fitted to `size_key`.
    JSON template: canvas size comes from the template; photos fill its slots.
    JSON pair (portrait + landscape): the variant matching the first photo's orientation.
    PNG pair: `frame_path` for portrait photos, `frame_landscape` for landscape ones (either may be
    missing – then the other one is used for every photo).
    """
    paths = [photo_paths] if isinstance(photo_paths, (str, Path)) else list(photo_paths)
    if is_template(frame_path):
        # a portrait/landscape pair picks the variant matching the photo (after EXIF rotation)
        from magnetstudio.core.templates import compose_auto, load_frame
        return compose_auto(load_frame(frame_path), [load_image(p) for p in paths],
                            photo_filter=photo_filter)
    photo = fit_to_size(load_image(paths[0]), get_size(size_key))
    if photo_filter:
        photo = photo_filter(photo)
    frame = frame_path
    if frame_landscape and (photo.width > photo.height or not frame_path):
        frame = frame_landscape
    return apply_frame(photo, frame)


def render_magnet_preview(photo_path: str | Path, size_key: str, frame_path: str | Path | None = None,
                          photo_filter: PhotoFilter | None = None, frame_landscape: str | Path | None = None,
                          max_side: int = 420) -> Image.Image:
    """A small finished-magnet image for the photo grid – same pipeline as printing, but the photo
    is decoded at reduced size (JPEG draft mode), so 50+ thumbnails render in seconds."""
    from PIL import ImageOps
    with Image.open(photo_path) as im:
        im.draft("RGB", (1400, 1400))           # JPEG: decode at 1/2, 1/4 … – much faster
        photo = ImageOps.exif_transpose(im).convert("RGB")
    if is_template(frame_path):
        from magnetstudio.core.templates import compose_auto, load_frame
        out = compose_auto(load_frame(frame_path), [photo], photo_filter=photo_filter)
    else:
        photo = fit_to_size(photo, get_size(size_key))
        if photo_filter:
            photo = photo_filter(photo)
        frame = frame_path
        if frame_landscape and (photo.width > photo.height or not frame_path):
            frame = frame_landscape
        out = apply_frame(photo, frame)
    out.thumbnail((max_side, max_side), Image.Resampling.LANCZOS)
    return out


def adjust(img: Image.Image, exposure: float = 0, contrast: float = 0, sharpness: float = 0) -> Image.Image:
    """Global sliders (−100…100): exposure (brightness), contrast, sharpness. 0 = unchanged."""
    from PIL import ImageEnhance
    if exposure:
        img = ImageEnhance.Brightness(img).enhance(1 + exposure / 200)
    if contrast:
        img = ImageEnhance.Contrast(img).enhance(1 + contrast / 200)
    if sharpness:
        img = ImageEnhance.Sharpness(img).enhance(1 + sharpness / 50)
    img.info["dpi"] = (DPI, DPI)
    return img


def make_enhance_filter(settings: dict) -> PhotoFilter | None:
    """Photo filter from app settings, or None when the enhancer is off.
    Cloud style is tried first when configured; otherwise / on failure the local LUT runs."""
    adj = {k: float(settings.get(k) or 0) for k in ("exposure", "contrast", "sharpness")}
    base = _enhance_filter(settings)
    if not any(adj.values()):
        return base
    if base is None:
        return lambda img: adjust(img, **adj)
    return lambda img: adjust(base(img), **adj)


def _enhance_filter(settings: dict) -> PhotoFilter | None:
    if not settings.get("enhance"):
        return None
    from magnetstudio.core.ai_enhancer import DEFAULT_GEMINI_MODEL, enhance
    from magnetstudio.core.secrets import get_api_key
    preset = settings.get("enhance_preset") or "dye_sub"
    style = settings.get("cloud_style") or None
    key = get_api_key(settings)
    model = settings.get("gemini_model") or DEFAULT_GEMINI_MODEL
    if style and key:
        return lambda img: enhance(img, preset, style, key, model)[0]
    return lambda img: enhance(img, preset)[0]
