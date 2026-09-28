"""Background / text colour estimation for a text block, so the overlay blends into the bubble."""

from __future__ import annotations

import cv2
import numpy as np

_KERNEL = np.ones((5, 5), np.uint8)


def _hex(rgb: np.ndarray) -> str:
    r, g, b = (int(v) for v in rgb)
    return f"#{r:02x}{g:02x}{b:02x}"


def _luma(rgb: np.ndarray) -> float:
    return 0.299 * rgb[0] + 0.587 * rgb[1] + 0.114 * rgb[2]


def estimate_colors(img_rgb: np.ndarray, mask: np.ndarray, x1: int, y1: int, x2: int, y2: int) -> tuple[str, str]:
    crop = img_rgb[y1:y2, x1:x2]
    text_px = mask[y1:y2, x1:x2] > 127
    near_text = cv2.dilate(text_px.astype(np.uint8), _KERNEL, iterations=2) > 0

    bg_pixels = crop[~near_text]
    bg = np.median(bg_pixels, axis=0) if len(bg_pixels) else np.array([255, 255, 255])
    fg_pixels = crop[text_px]
    fg = np.median(fg_pixels, axis=0) if len(fg_pixels) else np.array([0, 0, 0])

    # Anti-aliased strokes pull the median towards the background: force readable contrast
    if abs(_luma(bg) - _luma(fg)) < 90:
        fg = np.array([0, 0, 0]) if _luma(bg) > 127 else np.array([255, 255, 255])
    return _hex(bg), _hex(fg)
