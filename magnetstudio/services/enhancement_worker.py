"""EnhancementWorker – runs the print enhancer (core/ai_enhancer.py) off the GUI thread."""
from __future__ import annotations

import logging

from PIL import Image
from PyQt6.QtCore import QThread, pyqtSignal

from magnetstudio.core.ai_enhancer import DEFAULT_GEMINI_MODEL, CloudUnavailable, enhance_cloud, enhance_local

log = logging.getLogger(__name__)

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
