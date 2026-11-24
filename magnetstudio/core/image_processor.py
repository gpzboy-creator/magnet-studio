"""Load photos and fit them to a target magnet size."""
from pathlib import Path

from PIL import Image, ImageOps

from magnetstudio.core.sizes import MagnetSize


def load_image(path: str | Path) -> Image.Image:
    """Open an image and apply EXIF orientation (phone photos)."""
    img = Image.open(path)
    img = ImageOps.exif_transpose(img)
    return img.convert("RGB")


def fit_to_size(img: Image.Image, size: MagnetSize, auto_rotate: bool = True) -> Image.Image:
    """Center-crop and resize so the image fills the magnet exactly."""
    target_w, target_h = size.size_px
    if auto_rotate and (img.width > img.height) != (target_w > target_h) and target_w != target_h:
        target_w, target_h = target_h, target_w
    return ImageOps.fit(img, (target_w, target_h), method=Image.Resampling.LANCZOS)
