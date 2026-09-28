"""Japanese OCR with manga-ocr (handles vertical text and furigana)."""

from __future__ import annotations

import numpy as np
import torch
from PIL import Image


class JapaneseOcr:
    def __init__(self, device: str = "cuda"):
        from manga_ocr import MangaOcr

        self.model = MangaOcr(force_cpu=device != "cuda")
        if self.model.model.device.type == "cuda":
            # fp16 halves the weights (~430 -> ~240 MiB) with identical output and speed
            self.model.model.half()
            preprocess = self.model._preprocess
            self.model._preprocess = lambda img: preprocess(img).half()
            torch.cuda.empty_cache()

    def __call__(self, crop_rgb: np.ndarray) -> str:
        return self.model(Image.fromarray(crop_rgb)).strip()
