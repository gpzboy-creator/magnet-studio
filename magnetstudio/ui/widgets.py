"""Shared UI helpers: bidi-safe text, fast thumbnails.

(Queue cards: ui/components/queue_panel.py; queue state: services/print_queue.py.)
"""
from __future__ import annotations

from PIL import Image, ImageOps
from PIL.ImageQt import ImageQt
from PyQt6.QtCore import QRectF, Qt
from PyQt6.QtGui import QColor, QPainter, QPainterPath, QPixmap


def ltr(s: str) -> str:
    """Isolate a left-to-right run ("+1", "×3") inside Hebrew text, so the bidi
    algorithm can't flip it into "1+" / "3×"."""
    return "⁦" + s + "⁩"


def make_thumb(path: str, size: int = 72, radius: int = 4) -> QPixmap:
    """Fast rounded-corner square thumbnail (JPEG draft decoding, EXIF-aware, HiDPI)."""
    try:
        with Image.open(path) as im:
            im.draft("RGB", (size * 2, size * 2))
            im = ImageOps.exif_transpose(im).convert("RGB")
            im = ImageOps.fit(im, (size * 2, size * 2), Image.Resampling.BILINEAR)
        src = QPixmap.fromImage(ImageQt(im))
    except Exception:
        src = QPixmap(size * 2, size * 2)
        src.fill(QColor("#2F333B"))
    src.setDevicePixelRatio(2.0)
    out = QPixmap(size * 2, size * 2)
    out.setDevicePixelRatio(2.0)
    out.fill(Qt.GlobalColor.transparent)
    p = QPainter(out)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    clip = QPainterPath()
    clip.addRoundedRect(QRectF(0, 0, size, size), radius, radius)
    p.setClipPath(clip)
    p.drawPixmap(0, 0, src)
    p.end()
    return out
