"""FrameGeneratorWorker – runs generator.generate_frame off the GUI thread."""
from __future__ import annotations

from PyQt6.QtCore import QThread, pyqtSignal

from magnetstudio.generator import (DEFAULT_ART_MODEL, DEFAULT_CREDIT, DEFAULT_TEXT_MODEL, GenerationResult,
                                    generate_frame)


class FrameGeneratorWorker(QThread):
    """progress(int, str) · finished(Template | TemplatePair) · failed(str)

    Note: `finished` intentionally shadows QThread.finished (per spec). It carries the
    TemplatePair for single-photo frames, else the Template; self.result has both.
    """
    progress = pyqtSignal(int, str)
    finished = pyqtSignal(object)
    failed = pyqtSignal(str)

    def __init__(self, prompt: str, profile: str, slot_count: int | None = None, use_ai: bool = True,
                 use_art: bool = True, api_key: str = "", text_model: str = DEFAULT_TEXT_MODEL,
                 art_model: str = DEFAULT_ART_MODEL, client=None, parent=None,
                 credit_text: str | None = DEFAULT_CREDIT, dual: bool = True):
        super().__init__(parent)
        self.kw = dict(prompt=prompt, profile=profile, slot_count=slot_count, use_ai=use_ai,
                       use_art=use_art, api_key=api_key, text_model=text_model,
                       art_model=art_model, client=client, credit_text=credit_text, dual=dual)
        self.result: GenerationResult | None = None

    def run(self) -> None:
        try:
            self.result = generate_frame(**self.kw, progress=lambda p, s: self.progress.emit(p, s))
            self.finished.emit(self.result.frame)
        except Exception as e:  # noqa: BLE001 – reported to the dialog, logged by the caller
            self.failed.emit(str(e))
