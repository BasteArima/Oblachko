"""Japanese OCR with manga-ocr (handles vertical text and furigana)."""

from __future__ import annotations

import numpy as np
from PIL import Image


class JapaneseOcr:
    def __init__(self, device: str = "cuda"):
        from manga_ocr import MangaOcr

        self.model = MangaOcr(force_cpu=device != "cuda")

    def __call__(self, crop_rgb: np.ndarray) -> str:
        return self.model(Image.fromarray(crop_rgb)).strip()
