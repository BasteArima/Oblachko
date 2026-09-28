"""English OCR with RapidOCR (PaddleOCR models on ONNX Runtime)."""

from __future__ import annotations

import numpy as np


class EnglishOcr:
    def __init__(self):
        from rapidocr import RapidOCR

        # CPU on purpose: small crops of varying size make the CUDA provider ~12x slower (2.4 s vs 0.2 s per bubble)
        self.engine = RapidOCR()

    def __call__(self, crop_rgb: np.ndarray) -> str:
        result = self.engine(crop_rgb)
        if result.txts is None or len(result.txts) == 0:
            return ""
        # Top-to-bottom, then left-to-right
        lines = sorted(zip(result.boxes, result.txts), key=lambda bt: (bt[0][:, 1].min(), bt[0][:, 0].min()))
        text = ""
        for _, line in lines:
            line = line.strip()
            if not line:
                continue
            # Word split across lines with a hyphen ("WHAT-" + "EVER")
            if text.endswith("-"):
                text = text[:-1] + line
            else:
                text = f"{text} {line}" if text else line
        return text
