"""English OCR with RapidOCR (PaddleOCR models on ONNX Runtime)."""

from __future__ import annotations

import numpy as np


class EnglishOcr:
    def __init__(self):
        from rapidocr import RapidOCR

        # CPU on purpose: small crops of varying size make the CUDA provider ~12x slower (2.4 s vs 0.2 s per bubble)
        self.engine = RapidOCR()

    def read_line(self, crop_rgb: np.ndarray) -> str:
        """Recognition only, for a crop that is a single line. Uses the brightest channel so coloured
        text on a dark background (scanlator watermarks: red on black) doesn't vanish in greyscale;
        the line detector misses such thin strips entirely."""
        bright = crop_rgb.max(axis=2)
        result = self.engine(np.dstack([bright, bright, bright]), use_det=False, use_cls=False, use_rec=True)
        return result.txts[0] if result.txts else ""

    def __call__(self, crop_rgb: np.ndarray) -> str:
        # Modes must be explicit: RapidOCR keeps the flags of the previous call (see read_line)
        result = self.engine(crop_rgb, use_det=True, use_cls=True, use_rec=True)
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
