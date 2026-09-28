"""Japanese OCR with manga-ocr (handles vertical text and furigana)."""

from __future__ import annotations

import os
from pathlib import Path

import numpy as np
import torch
from PIL import Image

MODEL_ID = "kha-white/manga-ocr-base"


class JapaneseOcr:
    def __init__(self, device: str = "cuda"):
        # Once the model is cached, start without asking Hugging Face: faster, works offline and
        # skips the "unauthenticated requests" warning. Must be set before transformers is imported.
        hub = Path(os.environ.get("HF_HOME", Path.home() / ".cache" / "huggingface")) / "hub"
        if (hub / f"models--{MODEL_ID.replace('/', '--')}").is_dir():
            os.environ.setdefault("HF_HUB_OFFLINE", "1")
        from manga_ocr import MangaOcr

        self.model = MangaOcr(MODEL_ID, force_cpu=device != "cuda")
        if self.model.model.device.type == "cuda":
            # fp16 halves the weights (~430 -> ~240 MiB) with identical output and speed
            self.model.model.half()
            preprocess = self.model._preprocess
            self.model._preprocess = lambda img: preprocess(img).half()
            torch.cuda.empty_cache()

    def __call__(self, crop_rgb: np.ndarray) -> str:
        return self.model(Image.fromarray(crop_rgb)).strip()
