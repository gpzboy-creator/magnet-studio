"""Apply a frame to a photo: either a ready PNG overlay or a JSON template."""
from pathlib import Path
from typing import Callable

from PIL import Image

from core.image_processor import fit_to_size, load_image
from core.sizes import DPI, get_size

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
                  photo_filter: PhotoFilter | None = None) -> Image.Image:
    """Photo(s) → finished magnet.

    Order: load → fit/crop to print size → photo_filter (enhancer) → frame on top.
    PNG frame / no frame: first photo fitted to `size_key`.
    JSON template: canvas size comes from the template; photos fill its slots.
    JSON pair (portrait + landscape): the variant matching the first photo's orientation.
    """
    paths = [photo_paths] if isinstance(photo_paths, (str, Path)) else list(photo_paths)
    if is_template(frame_path):
        # a portrait/landscape pair picks the variant matching the photo (after EXIF rotation)
        from core.templates import compose_auto, load_frame
        return compose_auto(load_frame(frame_path), [load_image(p) for p in paths],
                            photo_filter=photo_filter)
    photo = fit_to_size(load_image(paths[0]), get_size(size_key))
    if photo_filter:
        photo = photo_filter(photo)
    return apply_frame(photo, frame_path)


def make_enhance_filter(settings: dict) -> PhotoFilter | None:
    """Photo filter from app settings, or None when the enhancer is off.
    Cloud style is tried first when configured; otherwise / on failure the local LUT runs."""
    if not settings.get("enhance"):
        return None
    from core.ai_enhancer import DEFAULT_GEMINI_MODEL, enhance, get_api_key
    preset = settings.get("enhance_preset") or "dye_sub"
    style = settings.get("cloud_style") or None
    key = get_api_key(settings)
    model = settings.get("gemini_model") or DEFAULT_GEMINI_MODEL
    if style and key:
        return lambda img: enhance(img, preset, style, key, model)[0]
    return lambda img: enhance(img, preset)[0]
